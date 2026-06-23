"""TMDb API client for live-action series metadata lookup."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.config import settings
from app.models import SeriesMetadata

logger = logging.getLogger(__name__)


class TMDbClient:
    """TMDb TV metadata client with simple in-memory caching."""

    def __init__(self):
        self.base_url = "https://api.themoviedb.org/3"
        self._cache: dict[str, tuple[Optional[SeriesMetadata], datetime]] = {}

    def is_configured(self) -> bool:
        """Check whether TMDb lookup can be used."""
        return bool(settings.TMDB_API_KEY)

    async def get_tv(self, tmdb_id: int) -> Optional[SeriesMetadata]:
        """Get a TV series by TMDb ID."""
        if not self.is_configured():
            return None

        cache_key = f"tv:{tmdb_id}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        metadata = await self._fetch_tv(tmdb_id)
        self._cache_result(cache_key, metadata)
        return metadata

    async def find_tv_by_tvdb_id(self, tvdb_id: int) -> Optional[SeriesMetadata]:
        """Find a TV series by TVDB ID."""
        return await self._find_tv(str(tvdb_id), "tvdb_id")

    async def find_tv_by_imdb_id(self, imdb_id: str) -> Optional[SeriesMetadata]:
        """Find a TV series by IMDb ID."""
        return await self._find_tv(imdb_id, "imdb_id")

    async def _find_tv(
        self, external_id: str, external_source: str
    ) -> Optional[SeriesMetadata]:
        if not self.is_configured():
            return None

        cache_key = f"find:{external_source}:{external_id}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/find/{external_id}",
                    params={
                        "api_key": settings.TMDB_API_KEY,
                        "external_source": external_source,
                    },
                )
                response.raise_for_status()
                results = response.json().get("tv_results") or []
        except httpx.HTTPError as exc:
            logger.warning(
                "TMDb find failed for %s %s: %s",
                external_source,
                external_id,
                exc,
            )
            return None

        tmdb_id = results[0].get("id") if results else None
        metadata = await self._fetch_tv(tmdb_id) if tmdb_id else None
        self._cache_result(cache_key, metadata)
        return metadata

    async def _fetch_tv(self, tmdb_id: int) -> Optional[SeriesMetadata]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/tv/{tmdb_id}",
                    params={
                        "api_key": settings.TMDB_API_KEY,
                        "append_to_response": "external_ids,alternative_titles",
                    },
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("TMDb TV lookup failed for %s: %s", tmdb_id, exc)
            return None

        return self._metadata_from_response(data)

    def _metadata_from_response(self, data: dict[str, Any]) -> Optional[SeriesMetadata]:
        title = data.get("name")
        if not title:
            return None

        external_ids = data.get("external_ids") or {}
        alternate_titles = self._alternate_titles(data)
        first_air_date = data.get("first_air_date") or ""

        return SeriesMetadata(
            tvdb_id=external_ids.get("tvdb_id"),
            tmdb_id=data.get("id"),
            tvmaze_id=None,
            imdb_id=external_ids.get("imdb_id"),
            title=title,
            original_title=data.get("original_name"),
            alternate_titles=alternate_titles,
            year=self._year(first_air_date),
            country=self._first(data.get("origin_country")),
            language=data.get("original_language"),
            source="tmdb",
        )

    def _alternate_titles(self, data: dict[str, Any]) -> list[str]:
        titles: list[str] = []
        original_name = data.get("original_name")
        if original_name:
            titles.append(original_name)

        alt_data = data.get("alternative_titles") or {}
        for item in alt_data.get("results") or []:
            title = item.get("title")
            if title and self._is_searchable(title):
                titles.append(title)
        return self._dedupe(titles)

    def _get_cached(self, cache_key: str) -> Optional[SeriesMetadata]:
        cached = self._cache.get(cache_key)
        if not cached:
            return None
        metadata, cached_at = cached
        if datetime.now(timezone.utc) - cached_at < timedelta(
            seconds=settings.CACHE_TTL
        ):
            return metadata
        del self._cache[cache_key]
        return None

    def _cache_result(self, cache_key: str, metadata: Optional[SeriesMetadata]) -> None:
        if metadata is not None:
            self._cache[cache_key] = (metadata, datetime.now(timezone.utc))

    def _year(self, date_text: str) -> Optional[int]:
        if len(date_text) >= 4 and date_text[:4].isdigit():
            return int(date_text[:4])
        return None

    def _first(self, value: Any) -> Optional[str]:
        if isinstance(value, list) and value:
            return str(value[0])
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


tmdb_client = TMDbClient()
