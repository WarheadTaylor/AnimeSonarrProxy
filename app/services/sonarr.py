"""Sonarr API client for episode metadata lookup."""

import logging
from typing import Optional, List, Dict, Any
import httpx

from app.config import settings
from app.models import EpisodeInfo

logger = logging.getLogger(__name__)


class SonarrClient:
    """Client for Sonarr API v3.

    Used to get accurate episode metadata (season/episode numbers, specials)
    when Sonarr sends requests with absolute episode numbers.
    """

    def __init__(self):
        self._base_url: Optional[str] = None
        self._api_key: Optional[str] = None
        self._series_cache: Dict[int, Dict[str, Any]] = {}  # tvdb_id -> series data
        self._episodes_cache: Dict[
            int, List[Dict[str, Any]]
        ] = {}  # series_id -> episodes

    def configure(self, base_url: Optional[str], api_key: Optional[str]):
        """Configure the Sonarr client with URL and API key."""
        if base_url and api_key:
            self._base_url = base_url.rstrip("/")
            self._api_key = api_key
            logger.info(f"Sonarr client configured: {self._base_url}")
        else:
            self._base_url = None
            self._api_key = None
            logger.info("Sonarr client not configured (missing URL or API key)")

    def is_configured(self) -> bool:
        """Check if Sonarr integration is enabled and configured."""
        return bool(self._base_url and self._api_key)

    async def get_series_by_tvdb_id(self, tvdb_id: int) -> Optional[Dict[str, Any]]:
        """
        Get series information from Sonarr by TVDB ID.

        Args:
            tvdb_id: TVDB series ID

        Returns:
            Series data dict or None if not found
        """
        if not self.is_configured():
            return None

        # Check cache first
        if tvdb_id in self._series_cache:
            logger.debug(f"Using cached series data for TVDB {tvdb_id}")
            return self._series_cache[tvdb_id]

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self._base_url}/api/v3/series",
                    params={"tvdbId": tvdb_id},
                    headers={"X-Api-Key": self._api_key},
                )
                response.raise_for_status()

                series_list = response.json()

                if series_list and len(series_list) > 0:
                    series = series_list[0]
                    self._series_cache[tvdb_id] = series
                    logger.info(
                        f"Found series in Sonarr: '{series.get('title')}' "
                        f"(ID: {series.get('id')}, TVDB: {tvdb_id})"
                    )
                    return series
                else:
                    logger.debug(f"No series found in Sonarr for TVDB {tvdb_id}")
                    return None

        except httpx.HTTPStatusError as e:
            logger.error(f"Sonarr API error for TVDB {tvdb_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to query Sonarr for TVDB {tvdb_id}: {e}")
            return None

    async def get_episodes_by_series_id(self, series_id: int) -> List[Dict[str, Any]]:
        """
        Get all episodes for a series from Sonarr.

        Args:
            series_id: Sonarr series ID

        Returns:
            List of episode data dicts
        """
        if not self.is_configured():
            return []

        # Check cache first
        if series_id in self._episodes_cache:
            logger.debug(f"Using cached episodes for series ID {series_id}")
            return self._episodes_cache[series_id]

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self._base_url}/api/v3/episode",
                    params={"seriesId": series_id},
                    headers={"X-Api-Key": self._api_key},
                )
                response.raise_for_status()

                episodes = response.json()
                self._episodes_cache[series_id] = episodes
                logger.info(
                    f"Retrieved {len(episodes)} episodes for series ID {series_id}"
                )
                return episodes

        except httpx.HTTPStatusError as e:
            logger.error(f"Sonarr API error for series {series_id}: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to get episodes from Sonarr: {e}")
            return []

    async def get_episode_by_absolute_number(
        self, tvdb_id: int, absolute_ep: int
    ) -> Optional[EpisodeInfo]:
        """
        Find episode information by TVDB ID and absolute episode number.

        Args:
            tvdb_id: TVDB series ID
            absolute_ep: Absolute episode number

        Returns:
            EpisodeInfo with season/episode details, or None if not found
        """
        if not self.is_configured():
            logger.debug("Sonarr not configured, skipping episode lookup")
            return None

        # Get series first
        series = await self.get_series_by_tvdb_id(tvdb_id)
        if not series:
            logger.debug(f"Series TVDB {tvdb_id} not found in Sonarr")
            return None

        series_id = series.get("id")
        if not series_id:
            return None

        # Get all episodes for the series
        episodes = await self.get_episodes_by_series_id(series_id)
        if not episodes:
            logger.debug(f"No episodes found for series ID {series_id}")
            return None

        # Find episode by absolute number
        for episode in episodes:
            ep_absolute = episode.get("absoluteEpisodeNumber")
            if ep_absolute == absolute_ep:
                episode_info = EpisodeInfo.from_sonarr_response(episode, series)
                logger.info(
                    f"Found episode in Sonarr: TVDB {tvdb_id} abs {absolute_ep} -> "
                    f"S{episode_info.season_number:02d}E{episode_info.episode_number:02d} "
                    f"(special={episode_info.is_special})"
                )
                return episode_info

        # If no absolute match, try matching by episode number for non-anime series
        # Some series might not have absolute numbering
        series_type = series.get("seriesType", "standard")
        if series_type != "anime":
            logger.debug(
                f"Series {tvdb_id} is type '{series_type}', "
                f"absolute ep {absolute_ep} not found"
            )

        logger.debug(
            f"Episode with absolute number {absolute_ep} not found for TVDB {tvdb_id}"
        )
        return None

    async def get_episode_by_season_episode(
        self, tvdb_id: int, season: int, episode: int
    ) -> Optional[EpisodeInfo]:
        """
        Find episode information by TVDB ID and season/episode numbers.

        Args:
            tvdb_id: TVDB series ID
            season: Season number
            episode: Episode number within season

        Returns:
            EpisodeInfo with full details, or None if not found
        """
        if not self.is_configured():
            return None

        series = await self.get_series_by_tvdb_id(tvdb_id)
        if not series:
            return None

        series_id = series.get("id")
        if not series_id:
            return None

        episodes = await self.get_episodes_by_series_id(series_id)
        if not episodes:
            return None

        # Find episode by season and episode number
        for ep in episodes:
            if ep.get("seasonNumber") == season and ep.get("episodeNumber") == episode:
                return EpisodeInfo.from_sonarr_response(ep, series)

        logger.debug(
            f"Episode S{season:02d}E{episode:02d} not found for TVDB {tvdb_id}"
        )
        return None

    async def get_wanted_episode_by_episode_number(
        self, tvdb_id: int, episode_num: int
    ) -> Optional[EpisodeInfo]:
        """
        Find the wanted (monitored + missing) episode with the given episode number.

        When Sonarr sends q=01 without season info, it's the episode number within
        a season, not the absolute number. This method finds which season's episode
        is actually being searched (the one that's monitored but missing).

        Args:
            tvdb_id: TVDB series ID
            episode_num: Episode number within season (e.g., 1 for S2E01)

        Returns:
            EpisodeInfo for the wanted episode, or None if not found
        """
        if not self.is_configured():
            return None

        series = await self.get_series_by_tvdb_id(tvdb_id)
        if not series:
            return None

        series_id = series.get("id")
        if not series_id:
            return None

        episodes = await self.get_episodes_by_series_id(series_id)
        if not episodes:
            return None

        # Find all episodes with the matching episode number (could be S1E01, S2E01, etc.)
        candidates = []
        for ep in episodes:
            if ep.get("episodeNumber") == episode_num and ep.get("seasonNumber", 0) > 0:
                candidates.append(ep)

        if not candidates:
            logger.debug(
                f"No episodes with episodeNumber={episode_num} found for TVDB {tvdb_id}"
            )
            return None

        logger.debug(
            f"Found {len(candidates)} episodes with episodeNumber={episode_num}: "
            f"{[f'S{ep.get("seasonNumber")}E{ep.get("episodeNumber")}' for ep in candidates]}"
        )

        # Filter to monitored episodes without files (wanted/missing)
        wanted = [
            ep
            for ep in candidates
            if ep.get("monitored", False) and not ep.get("hasFile", True)
        ]

        if wanted:
            # If multiple wanted, prefer the most recent season (likely what user is searching)
            wanted.sort(key=lambda x: x.get("seasonNumber", 0), reverse=True)
            best_match = wanted[0]
            episode_info = EpisodeInfo.from_sonarr_response(best_match, series)
            logger.info(
                f"Found wanted episode: TVDB {tvdb_id} episodeNumber={episode_num} -> "
                f"S{episode_info.season_number:02d}E{episode_info.episode_number:02d} "
                f"(abs={episode_info.absolute_episode_number})"
            )
            return episode_info

        # No wanted episodes - fall back to the most recent season's episode
        # (User might be re-searching for an episode they already have)
        candidates.sort(key=lambda x: x.get("seasonNumber", 0), reverse=True)
        best_match = candidates[0]
        episode_info = EpisodeInfo.from_sonarr_response(best_match, series)
        logger.info(
            f"No wanted episodes, using most recent: TVDB {tvdb_id} episodeNumber={episode_num} -> "
            f"S{episode_info.season_number:02d}E{episode_info.episode_number:02d} "
            f"(abs={episode_info.absolute_episode_number})"
        )
        return episode_info

    def clear_cache(self):
        """Clear all cached data."""
        self._series_cache.clear()
        self._episodes_cache.clear()
        logger.debug("Sonarr cache cleared")


# Singleton instance
sonarr_client = SonarrClient()
