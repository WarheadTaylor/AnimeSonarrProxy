"""Pydantic models for data validation and serialization."""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class AnimeTitle(BaseModel):
    """Represents different title variations for an anime."""
    romaji: Optional[str] = None
    english: Optional[str] = None
    native: Optional[str] = None
    synonyms: List[str] = Field(default_factory=list)


class AnimeMapping(BaseModel):
    """Mapping between TVDB and anime databases."""
    tvdb_id: int
    anilist_id: Optional[int] = None
    mal_id: Optional[int] = None
    titles: AnimeTitle
    total_episodes: int = 0
    season_info: List[Dict[str, int]] = Field(default_factory=list)  # [{"season": 1, "episodes": 12}, ...]
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    user_override: bool = False  # True if manually set via WebUI


class TorznabQuery(BaseModel):
    """Torznab search query parameters."""
    t: str  # Query type: tvsearch, search, caps
    q: Optional[str] = None  # Search query
    tvdbid: Optional[int] = None
    season: Optional[int] = None
    ep: Optional[int] = None
    apikey: Optional[str] = None
    limit: Optional[int] = 100
    offset: Optional[int] = 0


class TorznabItem(BaseModel):
    """Torznab RSS item (search result)."""
    title: str
    guid: str
    link: str
    pubDate: str
    size: int
    category: List[int] = Field(default_factory=lambda: [5070])  # TV > Anime
    seeders: Optional[int] = None
    peers: Optional[int] = None
    grabs: Optional[int] = None
    tvdbid: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None


class SearchResult(BaseModel):
    """Internal search result before Torznab formatting."""
    title: str
    guid: str
    link: str
    pub_date: datetime
    size: int
    seeders: int = 0
    peers: int = 0
    indexer: str = ""

    def to_torznab_item(self, tvdbid: Optional[int] = None, season: Optional[int] = None, episode: Optional[int] = None) -> TorznabItem:
        """Convert to Torznab format."""
        return TorznabItem(
            title=self.title,
            guid=self.guid,
            link=self.link,
            pubDate=self.pub_date.strftime("%a, %d %b %Y %H:%M:%S +0000"),
            size=self.size,
            seeders=self.seeders,
            peers=self.peers,
            tvdbid=tvdbid,
            season=season,
            episode=episode
        )


class MappingOverride(BaseModel):
    """User-provided mapping override via WebUI."""
    tvdb_id: int
    anilist_id: Optional[int] = None
    mal_id: Optional[int] = None
    custom_titles: List[str] = Field(default_factory=list)
    season_episode_overrides: Dict[str, int] = Field(default_factory=dict)  # {"S01E01": 1, "S01E02": 2}
    notes: str = ""
