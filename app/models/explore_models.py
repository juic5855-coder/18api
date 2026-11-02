from pydantic import BaseModel
from typing import List, Optional

class ExploreSourceResponse(BaseModel):
    baseUrl: str
    nickname: str
    favicon: str
    accentColor: str
    category: str
    isVerified: bool = False
    hasCategories: bool = False
    searchUrlTemplate: str = ""
    sourceId: str
    disable: bool = False
    pageSize: int = 20
    hasRelatedVideos: bool = False
    relatedAsEpisodes: bool = False
    # "none" (default) = single thumbnail, categories JSON grid ignored;
    # "default" = default single list, per-category "grid" keys still apply;
    # "custom"/"enable" = categories JSON grid controls per-category layout;
    # "all-double" = site-wide double grid (missing/"none" grid → double);
    # "all-portrait" = site-wide portrait grid; plain "all" behaves like
    # "all-double". Any category with a "grid" key always overrides the
    # site-wide layout.
    gridSwitch: str = "none"

class ExploreCategoryResponse(BaseModel):
    id: str
    label: str

class ExploreConfigData(BaseModel):
    title: str = "SOURCES"
    categories: List[ExploreCategoryResponse]
    sources: List[ExploreSourceResponse]

class ExploreConfigResponse(BaseModel):
    status: str = "success"
    data: ExploreConfigData
