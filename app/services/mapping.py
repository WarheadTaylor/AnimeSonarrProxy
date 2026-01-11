"""Title mapping service with fallback and caching."""
import json
import logging
from typing import Optional, List, Dict
from pathlib import Path
from datetime import datetime

from app.config import settings
from app.models import AnimeMapping, AnimeTitle, MappingOverride
from app.services.anime_db import anime_db
from app.services.anilist import anilist_client

logger = logging.getLogger(__name__)


class MappingService:
    """Manages anime title mappings with multiple data sources."""

    def __init__(self):
        self.mappings_file = settings.DATA_DIR / "mappings.json"
        self.overrides_file = settings.DATA_DIR / "overrides.json"
        self.cache: Dict[int, AnimeMapping] = {}
        self.overrides: Dict[int, MappingOverride] = {}

    async def initialize(self):
        """Initialize mapping service."""
        await self._load_cache()
        await self._load_overrides()

    async def _load_cache(self):
        """Load cached mappings from file."""
        if self.mappings_file.exists():
            try:
                with open(self.mappings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for tvdb_id_str, mapping_data in data.items():
                        tvdb_id = int(tvdb_id_str)
                        self.cache[tvdb_id] = AnimeMapping(**mapping_data)
                logger.info(f"Loaded {len(self.cache)} cached mappings")
            except Exception as e:
                logger.error(f"Failed to load mappings cache: {e}")

    async def _save_cache(self):
        """Save cached mappings to file."""
        try:
            settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                str(tvdb_id): mapping.model_dump(mode='json')
                for tvdb_id, mapping in self.cache.items()
            }
            with open(self.mappings_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            logger.debug(f"Saved {len(self.cache)} mappings to cache")
        except Exception as e:
            logger.error(f"Failed to save mappings cache: {e}")

    async def _load_overrides(self):
        """Load user overrides from file."""
        if self.overrides_file.exists():
            try:
                with open(self.overrides_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for tvdb_id_str, override_data in data.items():
                        tvdb_id = int(tvdb_id_str)
                        self.overrides[tvdb_id] = MappingOverride(**override_data)
                logger.info(f"Loaded {len(self.overrides)} user overrides")
            except Exception as e:
                logger.error(f"Failed to load overrides: {e}")

    async def save_override(self, override: MappingOverride):
        """Save a user override."""
        self.overrides[override.tvdb_id] = override
        try:
            settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                str(tvdb_id): override_obj.model_dump(mode='json')
                for tvdb_id, override_obj in self.overrides.items()
            }
            with open(self.overrides_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved override for TVDB ID {override.tvdb_id}")

            # Invalidate cache for this TVDB ID
            if override.tvdb_id in self.cache:
                del self.cache[override.tvdb_id]

        except Exception as e:
            logger.error(f"Failed to save override: {e}")

    async def get_mapping(self, tvdb_id: int) -> Optional[AnimeMapping]:
        """
        Get anime mapping for TVDB ID.
        Priority: User Override > Cache > anime-offline-database > AniList API
        """
        # Check user overrides first
        if tvdb_id in self.overrides:
            override = self.overrides[tvdb_id]
            return await self._create_mapping_from_override(override)

        # Check cache
        if tvdb_id in self.cache:
            cached = self.cache[tvdb_id]
            # Check if cache is still valid
            age = (datetime.utcnow() - cached.last_updated).total_seconds()
            if age < settings.MAPPING_CACHE_TTL:
                logger.debug(f"Using cached mapping for TVDB {tvdb_id}")
                return cached

        # Try anime-offline-database
        anime = anime_db.get_by_tvdb_id(tvdb_id)
        if anime:
            logger.info(f"Found mapping in anime-offline-database for TVDB {tvdb_id}")
            mapping = await self._create_mapping_from_anime_db(tvdb_id, anime)
            if mapping:
                await self._cache_mapping(mapping)
                return mapping

        # Fallback: Check if we have AniList ID from override
        # (This would require external TVDB->AniList mapping which we don't have)
        logger.warning(f"No mapping found for TVDB {tvdb_id}")
        return None

    async def _create_mapping_from_anime_db(self, tvdb_id: int, anime: Dict) -> Optional[AnimeMapping]:
        """Create AnimeMapping from anime-offline-database entry."""
        ids = anime_db.extract_ids(anime)
        titles = anime_db.extract_titles(anime)

        # Try to enrich with AniList data if we have AniList ID
        total_episodes = 0
        if ids.get("anilist_id"):
            try:
                anilist_data = await anilist_client.get_by_anilist_id(ids["anilist_id"])
                if anilist_data:
                    # Merge titles from AniList
                    anilist_titles = anilist_client.extract_titles(anilist_data)
                    titles = self._merge_titles(titles, anilist_titles)
                    total_episodes = anilist_client.get_episode_count(anilist_data)
            except Exception as e:
                logger.warning(f"Failed to enrich with AniList data: {e}")

        return AnimeMapping(
            tvdb_id=tvdb_id,
            anidb_id=ids.get("anidb_id"),
            anilist_id=ids.get("anilist_id"),
            mal_id=ids.get("mal_id"),
            titles=titles,
            total_episodes=total_episodes,
            season_info=[],
            user_override=False
        )

    async def _create_mapping_from_override(self, override: MappingOverride) -> Optional[AnimeMapping]:
        """Create AnimeMapping from user override."""
        titles = AnimeTitle(synonyms=override.custom_titles)

        # Try to enrich with AniList data
        total_episodes = 0
        if override.anilist_id:
            try:
                anilist_data = await anilist_client.get_by_anilist_id(override.anilist_id)
                if anilist_data:
                    anilist_titles = anilist_client.extract_titles(anilist_data)
                    titles = self._merge_titles(titles, anilist_titles)
                    total_episodes = anilist_client.get_episode_count(anilist_data)
            except Exception as e:
                logger.warning(f"Failed to get AniList data for override: {e}")

        return AnimeMapping(
            tvdb_id=override.tvdb_id,
            anidb_id=override.anidb_id,
            anilist_id=override.anilist_id,
            mal_id=override.mal_id,
            titles=titles,
            total_episodes=total_episodes,
            season_info=[],
            user_override=True
        )

    def _merge_titles(self, base: AnimeTitle, additional: AnimeTitle) -> AnimeTitle:
        """Merge two AnimeTitle objects, keeping all unique titles."""
        return AnimeTitle(
            romaji=base.romaji or additional.romaji,
            english=base.english or additional.english,
            native=base.native or additional.native,
            synonyms=list(set(base.synonyms + additional.synonyms))
        )

    async def _cache_mapping(self, mapping: AnimeMapping):
        """Cache a mapping."""
        self.cache[mapping.tvdb_id] = mapping
        await self._save_cache()

    def get_all_titles(self, mapping: AnimeMapping) -> List[str]:
        """Get all unique title variations from mapping."""
        titles = set()

        if mapping.titles.romaji:
            titles.add(mapping.titles.romaji)
        if mapping.titles.english:
            titles.add(mapping.titles.english)
        if mapping.titles.native:
            titles.add(mapping.titles.native)

        for synonym in mapping.titles.synonyms:
            if synonym:
                titles.add(synonym)

        return list(titles)

    async def get_all_mappings(self) -> List[AnimeMapping]:
        """Get all cached mappings for WebUI display."""
        return list(self.cache.values())

    async def get_unmapped_tvdb_ids(self) -> List[int]:
        """Get list of TVDB IDs that failed to map (for WebUI)."""
        # This would need to be tracked separately during failed lookups
        # For now, return empty list
        return []


# Singleton instance
mapping_service = MappingService()
