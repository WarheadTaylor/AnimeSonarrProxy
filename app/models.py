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
    original_title: Optional[str] = None
    info_hash: Optional[str] = None
    nyaa_category_id: Optional[str] = None
    trusted: bool = False
    remake: bool = False


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
