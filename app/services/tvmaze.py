"""TVmaze API client for live-action series metadata lookup."""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from app.config import settings
from app.models import SeriesMetadata

logger = logging.getLogger(__name__)


class TVmazeClient:
    """TVmaze metadata client with simple in-memory caching."""

    def __init__(self):
        self.base_url = "https://api.tvmaze.com"
        self._cache: dict[str, tuple[Optional[SeriesMetadata], datetime]] = {}

    async def get_show(self, tvmaze_id: int) -> Optional[SeriesMetadata]:
        """Get a TVmaze show by ID."""
        cache_key = f"show:{tvmaze_id}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        metadata = await self._fetch_show(f"{self.base_url}/shows/{tvmaze_id}")
        self._cache_result(cache_key, metadata)
        return metadata

    async def lookup_by_tvdb_id(self, tvdb_id: int) -> Optional[SeriesMetadata]:
        """Lookup a TVmaze show by TVDB ID."""
        return await self._lookup("thetvdb", str(tvdb_id))

    async def lookup_by_imdb_id(self, imdb_id: str) -> Optional[SeriesMetadata]:
        """Lookup a TVmaze show by IMDb ID."""
        return await self._lookup("imdb", imdb_id)

    async def _lookup(self, provider: str, external_id: str) -> Optional[SeriesMetadata]:
        cache_key = f"lookup:{provider}:{external_id}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        metadata = await self._fetch_show(
            f"{self.base_url}/lookup/shows",
            params={provider: external_id},
        )
        self._cache_result(cache_key, metadata)
        return metadata

    async def _fetch_show(
        self, url: str, params: Optional[dict[str, str]] = None
    ) -> Optional[SeriesMetadata]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("TVmaze lookup failed for %s: %s", url, exc)
            return None

        metadata = self._metadata_from_response(data)
        if metadata and metadata.tvmaze_id:
            metadata.alternate_titles.extend(await self._akas(metadata.tvmaze_id))
            metadata.alternate_titles = self._dedupe(metadata.alternate_titles)
        return metadata

    async def _akas(self, tvmaze_id: int) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/shows/{tvmaze_id}/akas")
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.debug("TVmaze AKAs lookup failed for %s: %s", tvmaze_id, exc)
            return []

        titles = []
        for item in data if isinstance(data, list) else []:
            name = item.get("name") if isinstance(item, dict) else None
            if name and self._is_searchable(name):
                titles.append(name)
        return self._dedupe(titles)

    def _metadata_from_response(self, data: dict[str, Any]) -> Optional[SeriesMetadata]:
        title = data.get("name")
        if not title:
            return None

        externals = data.get("externals") or {}
        network = data.get("network") or data.get("webChannel") or {}

        return SeriesMetadata(
            tvdb_id=externals.get("thetvdb"),
            tmdb_id=externals.get("themoviedb"),
            tvmaze_id=data.get("id"),
            imdb_id=externals.get("imdb"),
            title=title,
            original_title=None,
            alternate_titles=[],
            year=self._year(data.get("premiered") or ""),
            country=(network.get("country") or {}).get("code")
            if isinstance(network, dict)
            else None,
            language=data.get("language"),
            source="tvmaze",
        )

    def _get_cached(self, cache_key: str) -> Optional[SeriesMetadata]:
        cached = self._cache.get(cache_key)
        if not cached:
            return None
        metadata, cached_at = cached
        if datetime.utcnow() - cached_at < timedelta(seconds=settings.CACHE_TTL):
            return metadata
        del self._cache[cache_key]
        return None

    def _cache_result(self, cache_key: str, metadata: Optional[SeriesMetadata]) -> None:
        if metadata is not None:
            self._cache[cache_key] = (metadata, datetime.utcnow())

    def _year(self, date_text: str) -> Optional[int]:
        if len(date_text) >= 4 and date_text[:4].isdigit():
            return int(date_text[:4])
        return None

    def _dedupe(self, titles: list[str]) -> list[str]:
        seen = set()
        unique = []
        for title in titles:
            cleaned = " ".join(str(title).split())
            key = cleaned.casefold()
            if cleaned and key not in seen:
                seen.add(key)
                unique.append(cleaned)
        return unique

    def _is_searchable(self, title: str) -> bool:
        letters = [char for char in title if char.isalpha()]
        if not letters:
            return True
        latin = sum(1 for char in letters if "A" <= char.upper() <= "Z")
        return latin / len(letters) >= 0.5


tvmaze_client = TVmazeClient()
