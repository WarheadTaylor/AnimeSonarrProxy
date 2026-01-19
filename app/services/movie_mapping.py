"""Movie title mapping service with fallback and caching."""

import json
import logging
from typing import Optional, List, Dict
from datetime import datetime

from app.config import settings
from app.models import MovieMapping, AnimeTitle, MovieMappingOverride
from app.services.anime_db import anime_db
from app.services.anilist import anilist_client

logger = logging.getLogger(__name__)


class MovieMappingService:
    """Manages anime movie title mappings with multiple data sources."""

    def __init__(self):
        self.mappings_file = settings.DATA_DIR / "movie_mappings.json"
        self.overrides_file = settings.DATA_DIR / "movie_overrides.json"
        self.cache: Dict[int, MovieMapping] = {}  # Keyed by TMDB ID
        self.imdb_to_tmdb: Dict[str, int] = {}  # IMDb ID -> TMDB ID lookup
        self.overrides: Dict[int, MovieMappingOverride] = {}

    async def initialize(self):
        """Initialize movie mapping service."""
        await self._load_cache()
        await self._load_overrides()

    async def _load_cache(self):
        """Load cached mappings from file."""
        if self.mappings_file.exists():
            try:
                with open(self.mappings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for tmdb_id_str, mapping_data in data.items():
                        tmdb_id = int(tmdb_id_str)
                        mapping = MovieMapping(**mapping_data)
                        self.cache[tmdb_id] = mapping
                        # Build IMDb -> TMDB index
                        if mapping.imdb_id:
                            self.imdb_to_tmdb[mapping.imdb_id] = tmdb_id
                logger.info(f"Loaded {len(self.cache)} cached movie mappings")
            except Exception as e:
                logger.error(f"Failed to load movie mappings cache: {e}")

    async def _save_cache(self):
        """Save cached mappings to file."""
        try:
            settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                str(tmdb_id): mapping.model_dump(mode="json")
                for tmdb_id, mapping in self.cache.items()
            }
            with open(self.mappings_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            logger.debug(f"Saved {len(self.cache)} movie mappings to cache")
        except Exception as e:
            logger.error(f"Failed to save movie mappings cache: {e}")

    async def _load_overrides(self):
        """Load user overrides from file."""
        if self.overrides_file.exists():
            try:
                with open(self.overrides_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for tmdb_id_str, override_data in data.items():
                        tmdb_id = int(tmdb_id_str)
                        self.overrides[tmdb_id] = MovieMappingOverride(**override_data)
                logger.info(f"Loaded {len(self.overrides)} movie user overrides")
            except Exception as e:
                logger.error(f"Failed to load movie overrides: {e}")

    async def save_override(self, override: MovieMappingOverride):
        """Save a user override."""
        self.overrides[override.tmdb_id] = override
        try:
            settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                str(tmdb_id): override_obj.model_dump(mode="json")
                for tmdb_id, override_obj in self.overrides.items()
            }
            with open(self.overrides_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved movie override for TMDB ID {override.tmdb_id}")

            # Invalidate cache for this TMDB ID
            if override.tmdb_id in self.cache:
                del self.cache[override.tmdb_id]

        except Exception as e:
            logger.error(f"Failed to save movie override: {e}")

    async def delete_override(self, tmdb_id: int) -> bool:
        """Delete a user override."""
        if tmdb_id not in self.overrides:
            return False

        del self.overrides[tmdb_id]
        try:
            settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                str(tid): override_obj.model_dump(mode="json")
                for tid, override_obj in self.overrides.items()
            }
            with open(self.overrides_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Deleted movie override for TMDB ID {tmdb_id}")

            # Invalidate cache
            if tmdb_id in self.cache:
                del self.cache[tmdb_id]

            return True
        except Exception as e:
            logger.error(f"Failed to delete movie override: {e}")
            return False

    async def get_mapping(self, tmdb_id: int) -> Optional[MovieMapping]:
        """
        Get movie mapping for TMDB ID.
        Priority: User Override > Cache > anime-offline-database > AniList API
        """
        # Check user overrides first
        if tmdb_id in self.overrides:
            override = self.overrides[tmdb_id]
            return await self._create_mapping_from_override(override)

        # Check cache
        if tmdb_id in self.cache:
            cached = self.cache[tmdb_id]
            # Check if cache is still valid
            age = (datetime.utcnow() - cached.last_updated).total_seconds()
            if age < settings.MAPPING_CACHE_TTL:
                logger.debug(f"Using cached movie mapping for TMDB {tmdb_id}")
                return cached

        # Try anime-offline-database
        anime = anime_db.get_by_tmdb_id(tmdb_id)
        if anime:
            logger.info(
                f"Found movie mapping in anime-offline-database for TMDB {tmdb_id}"
            )
            mapping = await self._create_mapping_from_anime_db(tmdb_id, anime)
            if mapping:
                await self._cache_mapping(mapping)
                return mapping

        logger.warning(f"No movie mapping found for TMDB {tmdb_id}")
        return None

    async def get_mapping_by_imdb(self, imdb_id: str) -> Optional[MovieMapping]:
        """
        Get movie mapping by IMDb ID.
        Looks up TMDB ID from cache first, then searches anime-offline-database.
        """
        # Check if we have a cached TMDB ID for this IMDb ID
        if imdb_id in self.imdb_to_tmdb:
            return await self.get_mapping(self.imdb_to_tmdb[imdb_id])

        # Search anime-offline-database for IMDb ID
        # This is a slower path as we need to scan all entries
        for anime in anime_db.data.get("data", []):
            for source in anime.get("sources", []):
                if f"imdb.com/title/{imdb_id}" in source:
                    # Found it! Extract TMDB ID if available
                    ids = anime_db.extract_movie_ids(anime)
                    if ids.get("tmdb_id"):
                        # Cache the IMDb -> TMDB mapping
                        self.imdb_to_tmdb[imdb_id] = ids["tmdb_id"]
                        return await self.get_mapping(ids["tmdb_id"])

                    # No TMDB ID, create mapping directly
                    mapping = await self._create_mapping_from_anime_db_imdb(
                        imdb_id, anime
                    )
                    if mapping:
                        return mapping

        logger.warning(f"No movie mapping found for IMDb {imdb_id}")
        return None

    async def _create_mapping_from_anime_db(
        self, tmdb_id: int, anime: Dict
    ) -> Optional[MovieMapping]:
        """Create MovieMapping from anime-offline-database entry."""
        ids = anime_db.extract_movie_ids(anime)
        titles = anime_db.extract_titles(anime)

        # Try to enrich with AniList data if we have AniList ID
        if ids.get("anilist_id"):
            try:
                anilist_data = await anilist_client.get_by_anilist_id(ids["anilist_id"])
                if anilist_data:
                    # Merge titles from AniList
                    anilist_titles = anilist_client.extract_titles(anilist_data)
                    titles = self._merge_titles(titles, anilist_titles)
            except Exception as e:
                logger.warning(f"Failed to enrich movie with AniList data: {e}")

        return MovieMapping(
            tmdb_id=tmdb_id,
            imdb_id=ids.get("imdb_id"),
            anidb_id=ids.get("anidb_id"),
            anilist_id=ids.get("anilist_id"),
            mal_id=ids.get("mal_id"),
            titles=titles,
            year=anime.get("animeSeason", {}).get("year"),
            user_override=False,
        )

    async def _create_mapping_from_anime_db_imdb(
        self, imdb_id: str, anime: Dict
    ) -> Optional[MovieMapping]:
        """Create MovieMapping from anime-offline-database entry using IMDb ID."""
        ids = anime_db.extract_movie_ids(anime)
        titles = anime_db.extract_titles(anime)

        # Try to enrich with AniList data if we have AniList ID
        if ids.get("anilist_id"):
            try:
                anilist_data = await anilist_client.get_by_anilist_id(ids["anilist_id"])
                if anilist_data:
                    anilist_titles = anilist_client.extract_titles(anilist_data)
                    titles = self._merge_titles(titles, anilist_titles)
            except Exception as e:
                logger.warning(f"Failed to enrich movie with AniList data: {e}")

        return MovieMapping(
            tmdb_id=ids.get("tmdb_id") or 0,  # May not have TMDB ID
            imdb_id=imdb_id,
            anidb_id=ids.get("anidb_id"),
            anilist_id=ids.get("anilist_id"),
            mal_id=ids.get("mal_id"),
            titles=titles,
            year=anime.get("animeSeason", {}).get("year"),
            user_override=False,
        )

    async def _create_mapping_from_override(
        self, override: MovieMappingOverride
    ) -> Optional[MovieMapping]:
        """Create MovieMapping from user override."""
        titles = AnimeTitle(synonyms=override.custom_titles)

        # Try to enrich with AniList data
        if override.anilist_id:
            try:
                anilist_data = await anilist_client.get_by_anilist_id(
                    override.anilist_id
                )
                if anilist_data:
                    anilist_titles = anilist_client.extract_titles(anilist_data)
                    titles = self._merge_titles(titles, anilist_titles)
            except Exception as e:
                logger.warning(f"Failed to get AniList data for movie override: {e}")

        return MovieMapping(
            tmdb_id=override.tmdb_id,
            imdb_id=override.imdb_id,
            anidb_id=override.anidb_id,
            anilist_id=override.anilist_id,
            mal_id=override.mal_id,
            titles=titles,
            year=override.year,
            user_override=True,
        )

    def _merge_titles(self, base: AnimeTitle, additional: AnimeTitle) -> AnimeTitle:
        """Merge two AnimeTitle objects, keeping all unique titles."""
        return AnimeTitle(
            romaji=base.romaji or additional.romaji,
            english=base.english or additional.english,
            native=base.native or additional.native,
            synonyms=list(set(base.synonyms + additional.synonyms)),
        )

    async def _cache_mapping(self, mapping: MovieMapping):
        """Cache a mapping."""
        self.cache[mapping.tmdb_id] = mapping
        # Update IMDb -> TMDB index
        if mapping.imdb_id:
            self.imdb_to_tmdb[mapping.imdb_id] = mapping.tmdb_id
        await self._save_cache()

    def get_all_titles(self, mapping: MovieMapping) -> List[str]:
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

    async def get_all_mappings(self) -> List[MovieMapping]:
        """Get all cached mappings for WebUI display."""
        return list(self.cache.values())

    async def get_all_overrides(self) -> List[MovieMappingOverride]:
        """Get all user overrides for WebUI display."""
        return list(self.overrides.values())


# Singleton instance
movie_mapping_service = MovieMappingService()
