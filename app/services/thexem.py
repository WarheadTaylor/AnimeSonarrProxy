"""TheXEM.info API client for episode and ID mapping."""

import logging
import httpx
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
import json
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


class TheXEMClient:
    """Client for TheXEM.info API."""

    def __init__(self):
        self.base_url = "https://thexem.info"
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl = timedelta(days=7)  # Cache XEM data for 7 days
        self.cache_file = settings.DATA_DIR / "thexem_cache.json"
        self._load_cache()

    def _load_cache(self):
        """Load cached TheXEM data from file."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Convert string timestamps back to datetime
                    for key, value in data.items():
                        if "cached_at" in value:
                            value["cached_at"] = datetime.fromisoformat(
                                value["cached_at"]
                            )
                    self.cache = data
                logger.info(f"Loaded {len(self.cache)} TheXEM cache entries")
            except Exception as e:
                logger.error(f"Failed to load TheXEM cache: {e}")

    def _save_cache(self):
        """Save TheXEM cache to file."""
        try:
            settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
            # Convert datetime to string for JSON serialization
            data = {}
            for key, value in self.cache.items():
                serialized = value.copy()
                if "cached_at" in serialized:
                    serialized["cached_at"] = serialized["cached_at"].isoformat()
                data[key] = serialized

            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"Saved {len(self.cache)} TheXEM cache entries")
        except Exception as e:
            logger.error(f"Failed to save TheXEM cache: {e}")

    def _get_cache_key(self, endpoint: str, params: Dict[str, Any]) -> str:
        """Generate cache key from endpoint and parameters."""
        param_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return f"{endpoint}?{param_str}"

    def _is_cache_valid(self, cached_at: datetime) -> bool:
        """Check if cached data is still valid."""
        return datetime.utcnow() - cached_at < self.cache_ttl

    async def get_all_mappings(
        self, show_id: int, origin: str = "tvdb"
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get all episode mappings for a show.

        Args:
            show_id: The show ID in the origin system (e.g., TVDB ID)
            origin: The source system ('tvdb', 'anidb', 'scene', etc.)

        Returns:
            List of episode mappings, each containing mappings to all destinations
            Example: [
                {
                    "tvdb": {"season": 1, "episode": 1, "absolute": 1},
                    "anidb": {"season": 1, "episode": 1, "absolute": 1},
                    "scene": {"season": 1, "episode": 1, "absolute": 1}
                },
                ...
            ]
        """
        cache_key = self._get_cache_key("map/all", {"id": show_id, "origin": origin})

        # Check cache first
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if self._is_cache_valid(cached_data["cached_at"]):
                logger.debug(f"Using cached TheXEM data for {origin} ID {show_id}")
                return cached_data["data"]

        # Make API request
        url = f"{self.base_url}/map/all"
        params = {"id": show_id, "origin": origin}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()

                result = response.json()

                if result.get("result") == "success":
                    data = result.get("data", [])

                    # Cache the result
                    self.cache[cache_key] = {
                        "data": data,
                        "cached_at": datetime.utcnow(),
                    }
                    self._save_cache()

                    logger.info(
                        f"Retrieved {len(data)} episode mappings from TheXEM for {origin} ID {show_id}"
                    )
                    return data
                else:
                    logger.warning(
                        f"TheXEM returned non-success result: {result.get('message')}"
                    )
                    return None

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.info(f"No TheXEM mapping found for {origin} ID {show_id}")
            else:
                logger.error(f"TheXEM API error: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to query TheXEM: {e}")
            return None

    async def get_single_mapping(
        self,
        show_id: int,
        origin: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        absolute: Optional[int] = None,
        destination: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get mapping for a single episode.

        Args:
            show_id: The show ID in the origin system
            origin: The source system ('tvdb', 'anidb', etc.)
            season: Season number (required if not using absolute)
            episode: Episode number (required if not using absolute)
            absolute: Absolute episode number (alternative to season/episode)
            destination: Target system (optional, returns all if not specified)

        Returns:
            Dictionary with mappings to destination system(s)
            Example: {
                "anidb": {"season": 1, "episode": 1, "absolute": 1},
                "scene": {"season": 1, "episode": 1, "absolute": 1}
            }
        """
        params = {"id": show_id, "origin": origin}

        if season is not None and episode is not None:
            params["season"] = season
            params["episode"] = episode
        elif absolute is not None:
            params["absolute"] = absolute
        else:
            logger.error("Must provide either (season + episode) or absolute")
            return None

        if destination:
            params["destination"] = destination

        url = f"{self.base_url}/map/single"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()

                result = response.json()

                if result.get("result") == "success":
                    return result.get("data", {})
                else:
                    logger.warning(
                        f"TheXEM single mapping failed: {result.get('message')}"
                    )
                    return None

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.debug(
                    f"No TheXEM single mapping found for {origin} ID {show_id}"
                )
            else:
                logger.error(f"TheXEM API error: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to query TheXEM single mapping: {e}")
            return None

    async def get_names_by_tvdb_id(self, tvdb_id: int) -> Optional[List[str]]:
        """
        Get all alternative names for a show by TVDB ID.

        Args:
            tvdb_id: TVDB show ID

        Returns:
            List of alternative names for the show, or None if not found
        """
        # First try to get from cached allNames data
        all_names = await self.get_all_names(origin="tvdb", default_names=True)
        if all_names and tvdb_id in all_names:
            names = all_names[tvdb_id]
            logger.info(
                f"Found {len(names)} names for TVDB {tvdb_id} from TheXEM: {names}"
            )
            return names

        logger.debug(f"No names found in TheXEM for TVDB {tvdb_id}")
        return None

    async def get_all_names(
        self,
        origin: str,
        season: Optional[str] = None,
        language: Optional[str] = None,
        default_names: bool = False,
    ) -> Optional[Dict[int, List[str]]]:
        """
        Get all show names available in TheXEM.

        Args:
            origin: The source system ('tvdb', 'anidb', etc.)
            season: Season filter (e.g., "1", "1,3,5", "le1", "ge2")
            language: Language code (e.g., 'us', 'jp')
            default_names: Include default names

        Returns:
            Dictionary mapping show IDs to lists of alternative names
            Example: {
                79604: ["Black-Lagoon", "ブラック・ラグーン", "Burakku Ragūn"],
                248812: ["Dont Trust the Bitch in Apartment 23"]
            }
        """
        params = {"origin": origin}

        if season:
            params["season"] = season
        if language:
            params["language"] = language
        if default_names:
            params["defaultNames"] = "1"

        cache_key = self._get_cache_key("map/allNames", params)

        # Check cache
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if self._is_cache_valid(cached_data["cached_at"]):
                return cached_data["data"]

        url = f"{self.base_url}/map/allNames"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()

                result = response.json()

                if result.get("result") == "success":
                    data = result.get("data", {})
                    # Convert string keys to int
                    int_data = {int(k): v for k, v in data.items()}

                    # Cache the result
                    self.cache[cache_key] = {
                        "data": int_data,
                        "cached_at": datetime.utcnow(),
                    }
                    self._save_cache()

                    logger.info(f"Retrieved {len(int_data)} show names from TheXEM")
                    return int_data
                else:
                    logger.warning(f"TheXEM allNames failed: {result.get('message')}")
                    return None

        except Exception as e:
            logger.error(f"Failed to query TheXEM allNames: {e}")
            return None

    def get_anidb_id_from_mappings(
        self, mappings: List[Dict[str, Any]]
    ) -> Optional[int]:
        """
        Extract AniDB ID from TheXEM mappings if available.

        Note: TheXEM mappings contain episode data, not show IDs directly.
        This is a helper to check if AniDB mappings exist for this show.

        Args:
            mappings: List of episode mappings from get_all_mappings()

        Returns:
            None (AniDB show IDs aren't in episode mappings)
            We just check if 'anidb' key exists to confirm AniDB mapping is available
        """
        if not mappings:
            return None

        # Check if any mapping has AniDB data
        for mapping in mappings:
            if "anidb" in mapping:
                # AniDB mapping exists, but we don't get the AniDB show ID from episode mappings
                # This would need to come from another source or be passed in
                logger.debug("AniDB mappings found in TheXEM data")
                return None  # We can't extract show ID from episode mappings

        return None

    async def tvdb_to_anidb_episode(
        self, tvdb_id: int, season: int, episode: int
    ) -> Optional[int]:
        """
        Convert TVDB season/episode to AniDB absolute episode number.

        Args:
            tvdb_id: TVDB show ID
            season: TVDB season number
            episode: TVDB episode number

        Returns:
            AniDB absolute episode number, or None if mapping not found
        """
        mapping = await self.get_single_mapping(
            show_id=tvdb_id,
            origin="tvdb",
            season=season,
            episode=episode,
            destination="anidb",
        )

        if mapping and "anidb" in mapping:
            anidb_data = mapping["anidb"]
            absolute = anidb_data.get("absolute")
            if absolute:
                logger.info(
                    f"TheXEM: TVDB {tvdb_id} S{season:02d}E{episode:02d} -> "
                    f"AniDB absolute {absolute}"
                )
                return absolute

        return None


# Singleton instance
thexem_client = TheXEMClient()
