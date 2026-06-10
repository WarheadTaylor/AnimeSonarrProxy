"""Core Sonarr/Radarr request flow for direct Nyaa search."""

import logging
import re
from typing import Optional

from app.config import settings
from app.models import SearchResult
from app.services.metadata import metadata_resolver
from app.services.nyaa import nyaa_client
from app.services.release_matcher import release_matcher

logger = logging.getLogger(__name__)


class CoreSearchService:
    """Coordinates metadata resolution, Nyaa search, matching, and normalization."""

    async def tv_search(
        self, tvdb_id: int, season: int, episode: int, limit: int
    ) -> tuple[list[SearchResult], dict[str, object]]:
        """Search Nyaa for a Sonarr TV request."""
        context = await metadata_resolver.resolve_tv(tvdb_id, season, episode)
        if context is None:
            return [], {}

        if context.is_special:
            results = await nyaa_client.search_multi(
                titles=context.search_titles,
                episodes=(
                    [context.absolute_episode] if context.absolute_episode else None
                ),
                keywords=["OVA", "OAD", "Special"],
                limit=limit,
            )
        else:
            results = await nyaa_client.search_multi(
                titles=context.search_titles,
                episodes=(
                    [context.absolute_episode] if context.absolute_episode else None
                ),
                limit=limit,
            )

        matched = [
            normalized
            for result in results
            if (normalized := release_matcher.match_tv(result, context)) is not None
        ]
        return self._rank(matched, limit), {
            "tvdb_id": tvdb_id,
            "season": season,
            "episode": episode,
        }

    async def movie_search(
        self,
        tmdb_id: Optional[int],
        imdb_id: Optional[str],
        query: Optional[str],
        year: Optional[int],
        limit: int,
    ) -> tuple[list[SearchResult], dict[str, object]]:
        """Search Nyaa for a Radarr movie request."""
        context = await metadata_resolver.resolve_movie(tmdb_id, imdb_id, query, year)
        if context is None:
            return [], {}

        keywords = ["movie", "gekijouban"]
        if context.year:
            keywords.insert(0, str(context.year))

        results = await nyaa_client.search_multi(
            titles=context.search_titles,
            keywords=keywords if context.year else None,
            limit=limit,
        )
        matched = [
            normalized
            for result in results
            if (normalized := release_matcher.match_movie(result, context)) is not None
        ]
        return self._rank(matched, limit), {
            "tmdb_id": context.tmdb_id,
            "imdb_id": context.imdb_id,
            "year": context.year,
        }

    async def generic_search(
        self,
        query: str,
        limit: int,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> list[SearchResult]:
        """Run a guarded generic Nyaa search for indexer tests and manual searches."""
        results = await nyaa_client.search(query, limit=limit)
        absolute_episode = self._trailing_episode(query)
        if absolute_episode is None or season is None or episode is None:
            return self._rank(results, limit)

        series_title = re.sub(r"\s+\d{1,5}\s*$", "", query).strip()
        if not series_title:
            return self._rank(results, limit)

        from app.services.metadata import TvSearchContext

        context = TvSearchContext(
            tvdb_id=0,
            season=season,
            episode=episode,
            absolute_episode=absolute_episode,
            search_titles=[series_title],
            returned_title=series_title,
        )
        matched = [
            normalized
            for result in results
            if (normalized := release_matcher.match_tv(result, context)) is not None
        ]
        return self._rank(matched, limit)

    def _rank(self, results: list[SearchResult], limit: int) -> list[SearchResult]:
        unique: dict[str, SearchResult] = {}
        for result in results:
            key = result.info_hash or result.guid
            current = unique.get(key)
            if current is None or (result.seeders, result.pub_date) > (
                current.seeders,
                current.pub_date,
            ):
                unique[key] = result

        ranked = list(unique.values())
        ranked.sort(key=lambda result: (result.seeders, result.pub_date), reverse=True)
        return ranked[: min(limit, settings.MAX_RESULTS_PER_QUERY)]

    def _trailing_episode(self, query: str) -> Optional[int]:
        match = re.search(r"(?:^|\s)(\d{1,5})\s*$", query or "")
        if not match:
            return None
        episode = int(match.group(1))
        return episode if episode > 0 else None


core_search_service = CoreSearchService()
