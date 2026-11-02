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
    # "custom"/"enable" = categories JSON grid controls per-category layout;
    # "all" = site-wide grid (missing/"none" grid falls back to double).
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
