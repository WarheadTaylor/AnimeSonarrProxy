"""Core Sonarr Newznab request flow for upstream Usenet providers."""

import logging
import re
from typing import Optional

from app.config import NewznabProviderSettings, settings
from app.models import SearchResult
from app.services.metadata import TvSearchContext, metadata_resolver
from app.services.newznab import configured_newznab_providers, newznab_client
from app.services.release_matcher import release_matcher
from app.services.release_parser import release_parser

logger = logging.getLogger(__name__)


class NewznabCoreService:
    """Coordinates metadata resolution, provider search, matching, and ranking."""

    async def tv_search(
        self,
        tvdb_id: int,
        season: int,
        episode: int,
        limit: int,
        categories: Optional[list[int]] = None,
    ) -> list[SearchResult]:
        """Search Newznab providers for a Sonarr TV request."""
        context = await metadata_resolver.resolve_tv(tvdb_id, season, episode)
        if context is None:
            return []

        providers = configured_newznab_providers()
        results: list[SearchResult] = []
        for provider in providers:
            for params in self._tv_params(provider, context, limit, categories):
                results.extend(
                    await newznab_client.search(
                        provider,
                        params,
                        fallback_categories=self._categories(provider, categories),
                    )
                )

        matched = [
            normalized
            for result in results
            if (normalized := release_matcher.match_tv(result, context)) is not None
        ]
        return self._rank(matched, limit, providers)

    async def generic_search(
        self,
        query: str,
        limit: int,
        *,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        categories: Optional[list[int]] = None,
    ) -> list[SearchResult]:
        """Run a generic Newznab provider search."""
        providers = configured_newznab_providers()
        results: list[SearchResult] = []
        for provider in providers:
            params = self._generic_params(provider, query, limit, categories)
            results.extend(
                await newznab_client.search(
                    provider,
                    params,
                    fallback_categories=self._categories(provider, categories),
                )
            )

        series_title, absolute_episode = self._split_trailing_episode(query)

        if season is not None and episode is not None:
            if series_title and absolute_episode is not None:
                context = TvSearchContext(
                    tvdb_id=0,
                    season=season,
                    episode=episode,
                    absolute_episode=absolute_episode,
                    episode_title=None,
                    search_titles=[series_title],
                    returned_title=series_title,
                )
                matched = [
                    normalized
                    for result in results
                    if (normalized := release_matcher.match_tv(result, context))
                    is not None
                ]
                return self._rank(matched, limit, providers)
            return self._rank(
                self._filter_episode_mismatches(results, season, episode),
                limit,
                providers,
            )

        if series_title and absolute_episode is not None:
            matched = [
                normalized
                for result in results
                if (
                    normalized := release_matcher.match_tv_absolute(
                        result, series_title, absolute_episode
                    )
                )
                is not None
            ]
            if matched:
                return self._rank(matched, limit, providers)
        return self._rank(results, limit, providers)

    def _split_trailing_episode(
        self, query: str
    ) -> tuple[Optional[str], Optional[int]]:
        """Split a Sonarr-style '<title> <episode>' query into title and episode."""
        match = re.search(r"^(?P<title>.*\S)\s+0*(?P<ep>\d{1,4})\s*$", query or "")
        if not match:
            return None, None
        episode = int(match.group("ep"))
        if episode <= 0 or 1900 <= episode <= 2099:
            return None, None
        return match.group("title").strip(), episode

    def _tv_params(
        self,
        provider: NewznabProviderSettings,
        context: TvSearchContext,
        limit: int,
        categories: Optional[list[int]],
    ) -> list[dict[str, object]]:
        selected_categories = self._categories(provider, categories)
        variants: list[dict[str, object]] = [
            {
                "t": "tvsearch",
                "tvdbid": context.tvdb_id,
                "season": context.season,
                "ep": context.episode,
                "cat": selected_categories,
                "limit": limit,
            }
        ]

        query_values = self._tv_queries(context)
        for query in query_values[: settings.NEWZNAB_MAX_QUERY_VARIANTS]:
            variants.append(
                {
                    "t": "search",
                    "q": query,
                    "cat": selected_categories,
                    "limit": limit,
                }
            )
        return variants

    def _generic_params(
        self,
        provider: NewznabProviderSettings,
        query: str,
        limit: int,
        categories: Optional[list[int]],
    ) -> dict[str, object]:
        params: dict[str, object] = {
            "t": "search",
            "cat": self._categories(provider, categories),
            "limit": limit,
        }
        if query:
            params["q"] = query
        return params

    def _tv_queries(self, context: TvSearchContext) -> list[str]:
        queries: list[str] = []
        for title in context.search_titles:
            if context.absolute_episode:
                queries.append(f"{title} {context.absolute_episode}")
                queries.append(f"{title} {context.absolute_episode:02d}")
            queries.append(f"{title} S{context.season:02d}E{context.episode:02d}")
            if context.is_special:
                for keyword in self._special_keywords(context.episode_title):
                    queries.append(f"{title} {keyword}")
        return self._dedupe_text(queries)

    def _special_keywords(self, episode_title: Optional[str]) -> list[str]:
        keywords = ["OVA", "OAD", "Special"]
        cleaned_title = " ".join((episode_title or "").split())
        if cleaned_title:
            keywords.append(cleaned_title)
        return keywords

    def _categories(
        self,
        provider: NewznabProviderSettings,
        categories: Optional[list[int]],
    ) -> list[int]:
        return categories or provider.categories or settings.NEWZNAB_DEFAULT_CATEGORIES

    def _filter_episode_mismatches(
        self, results: list[SearchResult], season: int, episode: int
    ) -> list[SearchResult]:
        filtered = []
        for result in results:
            parsed = release_parser.parse(result.original_title or result.title)
            if parsed.is_batch:
                continue
            if not parsed.season_numbers:
                filtered.append(result)
                continue
            if season not in parsed.season_numbers:
                continue
            if parsed.episode_numbers and episode not in parsed.episode_numbers:
                continue
            filtered.append(result)
        return filtered

    def _rank(
        self,
        results: list[SearchResult],
        limit: int,
        providers: list[NewznabProviderSettings],
    ) -> list[SearchResult]:
        priorities = {provider.id: provider.priority for provider in providers}
        unique: dict[str, SearchResult] = {}
        for result in results:
            key = self._dedupe_key(result)
            current = unique.get(key)
            if current is None or self._sort_key(result, priorities) > self._sort_key(
                current, priorities
            ):
                unique[key] = result

        ranked = list(unique.values())
        ranked.sort(key=lambda result: self._sort_key(result, priorities), reverse=True)
        return ranked[: min(limit, settings.MAX_RESULTS_PER_QUERY)]

    def _sort_key(
        self, result: SearchResult, priorities: dict[str, int]
    ) -> tuple[int, object, int]:
        priority = priorities.get(result.provider_id or "", 100)
        return (-priority, result.pub_date, result.size)

    def _dedupe_key(self, result: SearchResult) -> str:
        if result.provider_attrs.get("guid"):
            return result.provider_attrs["guid"]
        if result.provider_guid:
            return result.provider_guid
        if result.guid:
            return result.guid
        normalized_title = re.sub(r"\s+", " ", result.title.casefold()).strip()
        return f"{normalized_title}|{result.size}|{result.pub_date.isoformat()}"

    def _dedupe_text(self, values: list[str]) -> list[str]:
        unique: list[str] = []
        seen = set()
        for value in values:
            cleaned = " ".join(value.split())
            key = cleaned.casefold()
            if cleaned and key not in seen:
                seen.add(key)
                unique.append(cleaned)
        return unique


newznab_core_service = NewznabCoreService()
