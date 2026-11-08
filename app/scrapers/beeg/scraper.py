from __future__ import annotations

import json
import re
import os
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

API_BASE = "https://store.externulls.com"
STREAM_HOST = "https://video.beeg.com"
THUMBS_BASE = "https://thumbs.externulls.com"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://beeg.com",
    "Referer": "https://beeg.com/",
}


def can_handle(host: str) -> bool:
    return "beeg.com" in host.lower()


def get_categories() -> list[dict]:
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        json_path = os.path.join(current_dir, "categories.json")
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


async def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    }
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(20.0, connect=20.0),
        headers=headers,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


def _extract_video_id(url: str) -> Optional[str]:
    """Extract the numeric file id from a Beeg URL.

    Beeg page URLs look like https://beeg.com/-0{file_id} (the -0 / -1 are
    URL prefixes; the actual file id is the long number after them). Legacy
    plain /{id} URLs are also supported.
    """
    path = url.split("?")[0]
    if not path.startswith(("http://", "https://")):
        path = "https://" + path

    # Prefer the -0 / -1 prefixed form: drop the prefix, keep the numeric id.
    m = re.search(r'/-(?:0|1)(\d{6,})/?$', path)
    if m:
        return m.group(1)

    # Otherwise look for the last long numeric segment in the path.
    segments = path.split("/")
    for seg in reversed(segments):
        clean = re.sub(r'[^0-9]', '', seg)
        if len(clean) >= 6:
            return clean

    m = re.search(r'beeg\.com/.*?(\d{6,})', url)
    if m:
        return m.group(1)

    return None


async def scrape(url: str) -> dict[str, Any]:
    video_id = _extract_video_id(url)
    if not video_id:
        html = await fetch_html(url)
        return _parse_html_fallback(html, url)

    # The -0 URL prefix adds a leading zero, so cast through int to get the
    # canonical numeric file id used by the API.
    try:
        api_id = str(int(video_id))
    except Exception:
        api_id = video_id

    item: Optional[dict[str, Any]] = None
    play_template: Optional[str] = None

    try:
        async with httpx.AsyncClient(
            headers=_HEADERS, follow_redirects=True,
            timeout=httpx.Timeout(20.0, connect=15.0),
        ) as client:
            # 1) Metadata (title, duration, views, thumbnails, tags)
            resp = await client.get(f"{API_BASE}/facts/file/{api_id}")
            if resp.status_code == 200:
                try:
                    item = resp.json()
                except Exception:
                    item = None

            # 2) Signed HLS stream token. Response is a relative CDN path
            #    template, e.g.
            #      key=...,end=...,limit=10/data=.../media=hls4A/multi=.../_TPL_/....mp4.m3u8
            #    The "_TPL_" master URL itself resolves to an adaptive HLS
            #    master playlist served from https://video.beeg.com/.
            try:
                pr = await client.get(f"{API_BASE}/video/play_url/{api_id}")
                if pr.status_code == 200:
                    tpl = pr.text.strip()
                    if tpl.startswith("key="):
                        play_template = tpl
            except Exception:
                play_template = None
    except Exception as e:
        print(f"Beeg scrape error: {e}")

    if item:
        return _parse_externulls_response(item, url, api_id, play_template)

    try:
        html = await fetch_html(url)
    except Exception:
        html = ""
    return _parse_html_fallback(html, url)


def _parse_externulls_response(
    item: dict[str, Any], url: str, video_id: str, play_template: Optional[str]
) -> dict[str, Any]:
    file_info = item.get("file", {}) or {}

    title = "Unknown"
    for metaf in file_info.get("data", []):
        if metaf.get("cd_column") == "sf_name" and metaf.get("cd_value"):
            title = metaf["cd_value"]
            break

    facts_list = item.get("fc_facts", []) or []
    facts = facts_list[0] if facts_list else {}

    views = str(facts.get("fc_st_views", "0"))

    duration_sec = file_info.get("fl_duration", 0) or 0
    mins = duration_sec // 60
    secs = duration_sec % 60
    duration = f"{mins}:{secs:02d}"

    # Thumbnail: thumbs.externulls.com/videos/{file_id}/{frame}.webp
    thumb_url = None
    thumbs_list = facts.get("fc_thumbs", []) or []
    if thumbs_list:
        t_idx = thumbs_list[len(thumbs_list) // 2]
        thumb_url = f"{THUMBS_BASE}/videos/{video_id}/{t_idx}.webp?size=480x270"

    uploader = "Beeg"
    tags_raw = item.get("tags", []) or []
    for t in tags_raw:
        if t.get("is_owner") and t.get("tg_name"):
            uploader = t["tg_name"]
            break

    tags = [t.get("tg_name") for t in tags_raw if t.get("tg_name")] or []

    # Streams: the video/play_url endpoint returns a signed tokenized CDN
    # path. Prefixed with the video host it resolves to the adaptive HLS
    # master playlist (all qualities via EXT-X-STREAM-INF).
    streams: list[dict[str, Any]] = []
    hls_master: Optional[str] = None
    if play_template:
        hls_master = f"{STREAM_HOST}/{play_template}"
        streams.append({
            "quality": "adaptive",
            "format": "hls",
            "url": hls_master,
        })

    return {
        "url": url,
        "title": title,
        "description": "",
        "thumbnail_url": thumb_url,
        "duration": duration,
        "views": views,
        "uploader_name": uploader,
        "category": "Beeg",
        "tags": tags,
        "video": {
            "streams": streams,
            "default": streams[0]["url"] if streams else None,
            "has_video": len(streams) > 0,
        },
        "preview_url": thumb_url,
    }


def _parse_html_fallback(html: str, url: str) -> dict[str, Any]:
    # Placeholder for simple regex extraction if the API fails
    return {
        "url": url,
        "video": {"streams": [], "has_video": False},
    }


async def list_videos(base_url: str, page: int = 1, limit: int = 20) -> list[dict[str, Any]]:
    # Beeg serves feeds through store.externulls.com/tag/videos/{slug}.
    # The API requires limit >= 10 and an explicit offset.
    try:
        limit = max(10, int(limit))
    except Exception:
        limit = 20
    page = max(1, int(page or 1))
    offset = (page - 1) * limit

    # Determine the feed slug.
    if "q=" in base_url:
        # Search is websocket-based on this site; fall back to the homepage feed.
        slug = "index"
    elif "f=" in base_url:
        # Category: https://beeg.com/?f=Asian
        raw = base_url.split("f=")[1].split("&")[0]
        slug = re.sub(r'[^A-Za-z0-9]', '', raw).lower() or "index"
    else:
        slug = "index"

    api_url = f"{API_BASE}/tag/videos/{slug}?limit={limit}&offset={offset}"

    try:
        async with httpx.AsyncClient(
            headers=_HEADERS, follow_redirects=True,
            timeout=httpx.Timeout(20.0, connect=15.0),
        ) as client:
            resp = await client.get(api_url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        print(f"Beeg list error: {e}")
        return []

    if not isinstance(data, list):
        return []

    items = []
    for item in data:
        try:
            file_info = item.get("file", {}) or {}
            video_id = file_info.get("id")
            if not video_id:
                continue

            title = "Unknown"
            for metaf in file_info.get("data", []):
                if metaf.get("cd_column") == "sf_name" and metaf.get("cd_value"):
                    title = metaf["cd_value"]
                    break

            facts_list = item.get("fc_facts", []) or []
            if not facts_list:
                continue
            facts = facts_list[0]

            views_raw = facts.get("fc_st_views", 0) or 0
            if views_raw > 1000000:
                views = f"{views_raw / 1000000:.1f}M"
            elif views_raw > 1000:
                views = f"{views_raw / 1000:.1f}K"
            else:
                views = str(views_raw)

            thumbs_list = facts.get("fc_thumbs", []) or []
            thumb_url = None
            if thumbs_list:
                t_idx = thumbs_list[len(thumbs_list) // 2]
                thumb_url = f"{THUMBS_BASE}/videos/{video_id}/{t_idx}.webp?size=480x270"

            duration_sec = file_info.get("fl_duration", 0) or 0
            mins = duration_sec // 60
            secs = duration_sec % 60
            duration = f"{mins}:{secs:02d}"

            uploader = "Beeg"
            tags = item.get("tags", []) or []
            for t in tags:
                if t.get("is_owner") and t.get("tg_name"):
                    uploader = t["tg_name"]
                    break

            video_url = f"https://beeg.com/-0{video_id}"

            items.append({
                "url": video_url,
                "title": title,
                "thumbnail_url": thumb_url,
                "duration": duration,
                "views": views,
                "uploader_name": uploader,
            })
        except Exception:
            continue

    return items
