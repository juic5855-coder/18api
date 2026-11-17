from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

BASE = "https://oppai.stream"
SEARCH_API = f"{BASE}/api/search.php"
CDN_BASE = "https://s1.myspacecat.pictures"
CDN_DASH = "https://s2.myspacecat.pictures"

_WATCH_PATH_RE = re.compile(r"^/watch/([^/]+)(?:/from/\w+)?", re.I)
_CATEGORY_RE = re.compile(r"/category/([^/?]+)", re.I)
_STUDIO_RE = re.compile(r"/studio/([^/?]+)", re.I)


def can_handle(host: str) -> bool:
    h = (host or "").lower()
    if h == "oppai.stream" or (h.endswith(".oppai.stream") and not h.startswith("read.") and not h.startswith("rule34.")):
        return True
    return False


def _default_http_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"{BASE}/",
    }


def get_categories() -> list[dict[str, Any]]:
    try:
        path = os.path.join(os.path.dirname(__file__), "categories.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception as e:
        print(f"Error loading oppai categories: {e}")
    return []


async def fetch_html(url: str, method: str = "GET", data: dict | None = None) -> str:
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, connect=20.0),
        headers=_default_http_headers(),
    ) as client:
        if method == "POST" and data:
            r = await client.post(url, data=data)
        else:
            r = await client.get(url)
        r.raise_for_status()
        return r.text


def _normalize_watch_url(url: str) -> str:
    raw = (url or "").strip()
    p = urlparse(raw)
    if not p.netloc or not can_handle(p.netloc):
        raise ValueError("URL must be on oppai.stream (main site)")
    path = (p.path or "").rstrip("/")
    m = _WATCH_PATH_RE.match(path)
    if m:
        slug = m.group(1)
        return f"https://oppai.stream/watch/{slug}"
    if "/watch" not in path.lower():
        raise ValueError("Expected a watch URL such as https://oppai.stream/watch/Series-Name-1")
    raise ValueError("Could not parse watch URL slug from: " + raw)


def _slug_from_watch_url(url: str) -> str:
    raw = (url or "").strip()
    p = urlparse(raw)
    path = (p.path or "").rstrip("/")
    m = _WATCH_PATH_RE.match(path)
    if m:
        return m.group(1)
    qs = parse_qs(p.query)
    slug_list = qs.get("e") or qs.get("E")
    if slug_list and slug_list[0]:
        return slug_list[0].strip()
    raise ValueError("Could not extract slug from: " + raw)


def _meta_content(soup: BeautifulSoup, *, prop: str | None = None, name: str | None = None) -> str | None:
    if prop:
        tag = soup.find("meta", attrs={"property": prop})
    else:
        tag = soup.find("meta", attrs={"name": name})
    if tag and tag.get("content"):
        return str(tag.get("content")).strip()
    return None


def _quality_rank(label: str) -> int:
    q = (label or "").lower().replace("p", "")
    if q in ("4k", "2160", "uhd"):
        return 4
    if q in ("1080",):
        return 3
    if q in ("720",):
        return 2
    if q in ("480",):
        return 1
    return 0


def _quality_from_url(url: str) -> str:
    lower = url.lower()
    if "/4k/" in lower or "/2160/" in lower:
        return "4k"
    if "/1080/" in lower:
        return "1080p"
    if "/720/" in lower:
        return "720p"
    if "/480/" in lower:
        return "480p"
    return "unknown"


def _parse_inline_vars(html: str) -> dict[str, Any]:
    vars: dict[str, Any] = {}
    for m in re.finditer(r'var\s+(\w+)\s*=\s*([^;]+);', html):
        key, val = m.group(1), m.group(2).strip()
        try:
            vars[key] = json.loads(val)
        except (json.JSONDecodeError, ValueError):
            if val.startswith("[") or val.startswith("{"):
                continue
            vars[key] = val.strip('"\' ')
    return vars


def _build_stream_urls(folder: str, ep_str: str, res_list: list[str], resolutions: dict[str, str]) -> list[dict[str, Any]]:
    streams: list[dict[str, Any]] = []
    seen: set[str] = set()
    ep_num = int(ep_str) if ep_str.isdigit() else 1
    ep_fmt = f"{ep_num:02d}"

    for res in res_list:
        fmt = resolutions.get(res, "mp4")
        if fmt == "dash":
            url = f"{CDN_DASH}/{folder}/{res}/E{ep_fmt}_dash/E{ep_fmt}_dash.mpd"
        else:
            url = f"{CDN_BASE}/{folder}/ep.{fmt}"
        if url in seen:
            continue
        seen.add(url)
        streams.append({
            "quality": res,
            "url": url,
            "format": "dash" if fmt == "dash" else fmt,
            "server": "myspacecat-dash" if fmt == "dash" else "myspacecat",
        })

    fallback_resolutions = {
        "4k": "webm", "4k-1": "mp4", "4k-2": "webm",
        "1080": "mp4", "1080-1": "mp4",
        "720": "mp4",
    }
    for res, ext in fallback_resolutions.items():
        if res in res_list:
            continue
        if ext == "dash":
            url = f"{CDN_DASH}/{folder}/{res}/E{ep_fmt}_dash/E{ep_fmt}_dash.mpd"
        else:
            url = f"{CDN_BASE}/{folder}/ep.{ext}"
        if url in seen:
            continue
        seen.add(url)
        q = _quality_from_url(url)
        streams.append({
            "quality": q,
            "url": url,
            "format": "dash" if ext == "dash" else ext,
            "server": "myspacecat-dash" if ext == "dash" else "myspacecat",
        })

    streams.sort(key=lambda s: _quality_rank(str(s.get("quality", ""))), reverse=True)
    return streams


def _extract_streams(html: str, soup: BeautifulSoup) -> tuple[list[dict[str, Any]], str | None]:
    vars = _parse_inline_vars(html)
    folder = vars.get("folder", "")
    ep_str = str(vars.get("ep", "1"))
    res_list = vars.get("resList", [])
    resolutions = vars.get("resolutions", {})

    if not folder or not res_list:
        jsonld_m = re.search(r'"contentUrl"\s*:\s*"([^"]+)"', html)
        if jsonld_m:
            content_url = jsonld_m.group(1)
            streams = [{
                "quality": "unknown",
                "url": content_url,
                "format": content_url.split(".")[-1] if "." in content_url else "webm",
                "server": "myspacecat",
            }]
            return streams, content_url
        return [], None

    streams = _build_stream_urls(folder, ep_str, res_list, resolutions)
    default_url = streams[0]["url"] if streams else None
    return streams, default_url


def _title_from_page(soup: BeautifulSoup) -> str | None:
    h1 = soup.select_one("h1#episode-title")
    if h1:
        parts = []
        for child in h1.children:
            if hasattr(child, 'name') and child.name == 'font':
                parts.append(' ' + child.get_text(strip=True))
            else:
                t = child.get_text(strip=True)
                if t:
                    parts.append(t)
        if parts:
            text = ''.join(parts)
            h2 = soup.select_one("h2.white.bebas.line-3")
            if h2:
                series = h2.get_text(strip=True)
                if series and series not in text:
                    text = f"{series} {text}"
            return text
    og = _meta_content(soup, prop="og:title")
    if og:
        return re.sub(r"\s+on\s+Oppai\.Stream\s*$", "", og, flags=re.I).strip() or None
    tag = soup.find("title")
    if tag:
        return tag.get_text(strip=True) or None
    return None


def _description_from_page(soup: BeautifulSoup) -> str | None:
    el = soup.select_one("article#episode-description")
    if el:
        texts = []
        for p in el.find_all("p", recursive=False):
            t = p.get_text(strip=True)
            if t and "Watch" not in t and "Oppai.Stream" not in t:
                texts.append(t)
        if texts:
            return " ".join(texts)
        full = el.get_text(strip=True)
        if full:
            return full
    return _meta_content(soup, prop="og:description")


def _tags_from_page(soup: BeautifulSoup) -> list[str]:
    out: list[str] = []
    wrap = soup.select_one(".wrap-genres")
    if wrap:
        for a in wrap.select("a.button"):
            href = a.get("href", "")
            m = _CATEGORY_RE.search(href)
            if m:
                t = a.get_text(strip=True)
                if t:
                    out.append(t)
    return out


def _studio_from_page(soup: BeautifulSoup) -> str | None:
    wrap = soup.select_one(".wrap-genres")
    if wrap:
        for a in wrap.select("a.button"):
            href = a.get("href", "") or ""
            m = _STUDIO_RE.search(href)
            if m:
                t = a.get_text(strip=True)
                if t:
                    return t
    return None


def _related_videos(soup: BeautifulSoup, current_slug: str) -> list[dict[str, Any]]:
    related: list[dict[str, Any]] = []
    seen: set[str] = set()
    container = soup.select_one("#related-wrap")
    if not container:
        return related
    for a in container.select("a.episode"):
        href = a.get("href", "")
        if not href or "watch" not in href.lower():
            continue
        path_m = re.search(r"/watch/([^/]+)", href)
        if not path_m:
            continue
        slug = path_m.group(1)
        if slug == current_slug or slug in seen:
            continue
        seen.add(slug)
        title_el = a.select_one(".episode-title, p.episode-title")
        title = title_el.get_text(strip=True) if title_el else slug.replace("-", " ")
        ep_el = a.select_one(".episode-number, p.episode-number")
        if ep_el:
            ep_text = ep_el.get_text(strip=True)
            if ep_text:
                title = f"{title} {ep_text}".strip()
        thumb_el = a.select_one("img.cover")
        thumb = None
        if thumb_el:
            thumb = thumb_el.get("src") or thumb_el.get("data-src")
        duration_el = a.select_one(".ep-time, .ep_tag-time")
        duration = None
        if duration_el:
            t = duration_el.get_text(strip=True)
            if t:
                duration = t
        related.append({
            "url": f"https://oppai.stream/watch/{slug}",
            "title": title,
            "thumbnail_url": thumb,
            "duration": duration,
        })
    return related[:48]


def _results_section_key(base_url: str) -> str:
    u = (base_url or "").lower()
    p = urlparse(base_url or "")
    path = (p.path or "").lower()
    qs = parse_qs(p.query)
    a_val = (qs.get("a") or qs.get("A") or [""])[0].lower().strip()
    if a_val == "trending":
        return "views"
    if a_val == "random":
        return "random"
    if a_val == "uploaded":
        return "uploaded"
    if "popular" in path or "trending" in u:
        return "views"
    if "random" in u or "random" in path:
        return "random"
    if "new-releases" in path or "recent" in u:
        return "recent"
    return "recent"


def _browse_search_post_data(base_url: str, page: int, limit: int) -> dict[str, Any] | None:
    p = urlparse(base_url or "")
    qs = parse_qs(p.query)
    path = p.path.lower().strip("/")
    text = (qs.get("s") or qs.get("q") or qs.get("t") or [""])[0].strip()
    genres = (qs.get("categories") or qs.get("g") or [""])[0].strip()
    blacklist = (qs.get("blacklist") or [""])[0].strip()
    studios = (qs.get("studios") or qs.get("s") or [""])[0].strip()
    order = (qs.get("order") or ["recent"])[0].strip()
    if path == "search" and not any([text, genres, blacklist, studios]):
        return None
    if path.startswith("category/"):
        slug = path.split("/", 1)[1]
        if slug:
            genres = slug
    if path.startswith("studio/"):
        slug = path.split("/", 1)[1]
        if slug:
            studios = slug
    order_map = {"recent": "recent", "views": "views", "trending": "views", "uploaded": "uploaded", "random": "random"}
    return {
        "text": text,
        "tags": genres,
        "blacklist": blacklist,
        "studios": studios,
        "order": order_map.get(order, "recent"),
        "limit": str(min(limit, 100)),
        "page": str(page),
        "classes": "smaller-episode-gap",
        "character_filters": "{}",
    }


def _parse_list_html(fragment: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(fragment, "lxml")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for a in soup.select("a.episode"):
        href = a.get("href", "")
        if not href or "watch" not in href.lower():
            continue
        path_m = re.search(r"/watch/([^/]+)", href)
        if not path_m:
            continue
        slug = path_m.group(1)
        if slug in seen:
            continue
        seen.add(slug)
        title_el = a.select_one(".episode-title, p.episode-title")
        title = title_el.get_text(strip=True) if title_el else slug.replace("-", " ")
        ep_el = a.select_one(".episode-number, p.episode-number")
        if ep_el:
            ep_text = ep_el.get_text(strip=True)
            if ep_text:
                title = f"{title} {ep_text}".strip()
        thumb_el = a.select_one("img.cover")
        thumb = None
        if thumb_el:
            thumb = thumb_el.get("src") or thumb_el.get("data-src")
        views_el = a.select_one(".views p, .views")
        views = views_el.get_text(strip=True) if views_el else None
        duration_el = a.select_one(".ep-time p, .ep-time")
        duration = duration_el.get_text(strip=True) if duration_el else None
        items.append({
            "url": f"https://oppai.stream/watch/{slug}",
            "title": title,
            "thumbnail_url": thumb,
            "duration": duration,
            "views": views,
            "upload_date": None,
            "uploader_name": None,
            "tags": None,
        })
    return items


async def scrape(url: str) -> dict[str, Any]:
    watch_url = _normalize_watch_url(url)
    html = await fetch_html(watch_url)
    soup = BeautifulSoup(html, "lxml")
    slug = _slug_from_watch_url(watch_url)

    title = _title_from_page(soup)
    thumbnail = _meta_content(soup, prop="og:image")
    if not thumbnail:
        video_poster = soup.find("video", id="episode")
        if video_poster:
            thumbnail = video_poster.get("poster")
    if not thumbnail:
        video_cover = soup.select_one(".video-cover img.cover")
        if video_cover:
            thumbnail = video_cover.get("src")

    description = _description_from_page(soup)
    tags = _tags_from_page(soup)
    studio = _studio_from_page(soup)

    streams, default_url = _extract_streams(html, soup)

    jsonld_m = re.search(r'"uploadDate"\s*:\s*"([^"]+)"', html)
    upload_date = jsonld_m.group(1) if jsonld_m else None
    duration_m = re.search(r'"duration"\s*:\s*"PT(\d+)M(\d+)S"', html)
    duration = None
    if duration_m:
        duration = f"{duration_m.group(1)}:{duration_m.group(2)}"

    video_data = {
        "streams": streams,
        "default": default_url,
        "hls": None,
        "has_video": bool(default_url),
    }

    return {
        "url": watch_url,
        "title": title,
        "description": description,
        "thumbnail_url": thumbnail,
        "duration": duration,
        "views": None,
        "upload_date": upload_date,
        "uploader_name": studio,
        "category": None,
        "tags": tags,
        "video": video_data,
        "related_videos": _related_videos(soup, slug),
    }


async def list_videos(base_url: str, page: int = 1, limit: int = 100) -> list[dict[str, Any]]:
    page = max(1, page)
    limit = min(max(1, limit), 100)

    post_data = _browse_search_post_data(base_url, page, limit)
    if post_data:
        html = await fetch_html(SEARCH_API, method="POST", data=post_data)
        return _parse_list_html(html)

    p = urlparse(base_url or "")
    path = p.path.lower().strip("/")

    if path.startswith("category/") or path.startswith("studio/"):
        slug = path.split("/", 1)[1]
        post_data = {
            "text": "",
            "tags": slug if path.startswith("category/") else "",
            "blacklist": "",
            "studios": slug if path.startswith("studio/") else "",
            "order": "recent",
            "limit": str(limit),
            "page": str(page),
            "classes": "smaller-episode-gap",
            "character_filters": "{}",
        }
        html = await fetch_html(SEARCH_API, method="POST", data=post_data)
        return _parse_list_html(html)

    section = _results_section_key(base_url)
    section_to_url = {
        "views": f"{BASE}/popular",
        "recent": f"{BASE}/new-releases",
        "random": f"{BASE}/new-releases",
        "uploaded": f"{BASE}/new-releases",
    }
    listing_url = section_to_url.get(section, f"{BASE}/new-releases")
    html = await fetch_html(listing_url)
    return _parse_list_html(html)
