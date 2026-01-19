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
    anidb_id: Optional[int] = None
    anilist_id: Optional[int] = None
    mal_id: Optional[int] = None
    titles: AnimeTitle
    total_episodes: int = 0
    season_info: List[Dict[str, int]] = Field(
        default_factory=list
    )  # [{"season": 1, "episodes": 12}, ...]
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    user_override: bool = False  # True if manually set via WebUI

    def get_search_titles(self) -> List[str]:
        """Get all unique title variations for search queries."""
        titles = []
        if self.titles.romaji:
            titles.append(self.titles.romaji)
        if self.titles.english and self.titles.english not in titles:
            titles.append(self.titles.english)
        if self.titles.native and self.titles.native not in titles:
            titles.append(self.titles.native)
        for synonym in self.titles.synonyms:
            if synonym and synonym not in titles:
                titles.append(synonym)
        return titles


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
    link: str  # Download URL (torrent/magnet)
    info_url: Optional[str] = None  # Info/details page URL
    pub_date: datetime
    size: int
    seeders: int = 0
    peers: int = 0
    indexer: str = ""
    categories: List[int] = Field(default_factory=lambda: [5070])  # TV > Anime

    def to_torznab_item(
        self,
        tvdbid: Optional[int] = None,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> TorznabItem:
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
            episode=episode,
        )


class MappingOverride(BaseModel):
    """User-provided mapping override via WebUI."""

    tvdb_id: int
    anidb_id: Optional[int] = None
    anilist_id: Optional[int] = None
    mal_id: Optional[int] = None
    custom_titles: List[str] = Field(default_factory=list)
    season_episode_overrides: Dict[str, int] = Field(
        default_factory=dict
    )  # {"S01E01": 1, "S01E02": 2}
    season_ranges: List[Dict[str, int]] = Field(
        default_factory=list
    )  # [{"season": 1, "episodes": 12, "start_absolute": 1}]
    notes: str = ""


class MovieMapping(BaseModel):
    """Mapping between TMDB and anime databases for movies."""

    tmdb_id: int
    imdb_id: Optional[str] = None  # IMDb IDs are strings (e.g., "tt1234567")
    anidb_id: Optional[int] = None
    anilist_id: Optional[int] = None
    mal_id: Optional[int] = None
    titles: AnimeTitle
    year: Optional[int] = None
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    user_override: bool = False  # True if manually set via WebUI

    def get_search_titles(self) -> List[str]:
        """Get all unique title variations for search queries."""
        titles = []
        if self.titles.romaji:
            titles.append(self.titles.romaji)
        if self.titles.english and self.titles.english not in titles:
            titles.append(self.titles.english)
        if self.titles.native and self.titles.native not in titles:
            titles.append(self.titles.native)
        for synonym in self.titles.synonyms:
            if synonym and synonym not in titles:
                titles.append(synonym)
        return titles


class MovieMappingOverride(BaseModel):
    """User-provided movie mapping override via WebUI."""

    tmdb_id: int
    imdb_id: Optional[str] = None
    anidb_id: Optional[int] = None
    anilist_id: Optional[int] = None
    mal_id: Optional[int] = None
    custom_titles: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    notes: str = ""


class EpisodeInfo(BaseModel):
    """Episode information from Sonarr API."""

    series_id: int
    series_title: str
    season_number: int
    episode_number: int
    absolute_episode_number: Optional[int] = None
    title: Optional[str] = None
    is_special: bool = False  # True if seasonNumber == 0

    @classmethod
    def from_sonarr_response(
        cls, episode: Dict[str, Any], series: Dict[str, Any]
    ) -> "EpisodeInfo":
        """Create EpisodeInfo from Sonarr API response."""
        season_num = episode.get("seasonNumber", 0)
        return cls(
            series_id=episode.get("seriesId", 0),
            series_title=series.get("title", ""),
            season_number=season_num,
            episode_number=episode.get("episodeNumber", 0),
            absolute_episode_number=episode.get("absoluteEpisodeNumber"),
            title=episode.get("title"),
            is_special=(season_num == 0),
        )
