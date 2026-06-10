"""Release matching and manager-specific title normalization."""

import re
from typing import Optional

from app.models import SearchResult
from app.services.metadata import MovieSearchContext, TvSearchContext
from app.services.release_parser import ParsedRelease, release_parser


class ReleaseMatcher:
    """Filters Nyaa results to confident Sonarr/Radarr matches."""

    def match_tv(
        self, result: SearchResult, context: TvSearchContext
    ) -> Optional[SearchResult]:
        """Return a normalized TV result when the Nyaa title confidently matches."""
        parsed = release_parser.parse(result.original_title or result.title)
        if parsed.is_batch:
            return None
        if not self._title_matches(parsed, context.search_titles):
            return None

        if context.is_special:
            if not self._is_special_release(parsed):
                return None
        elif not self._matches_tv_episode(parsed, context):
            return None

        return result.model_copy(
            update={
                "title": self._tv_title(parsed, context),
                "original_title": result.original_title or result.title,
            }
        )

    def match_movie(
        self, result: SearchResult, context: MovieSearchContext
    ) -> Optional[SearchResult]:
        """Return a normalized movie result when the Nyaa title confidently matches."""
        parsed = release_parser.parse(result.original_title or result.title)
        if parsed.is_batch:
            return None
        if not self._title_matches(parsed, context.search_titles):
            return None
        if parsed.episode_numbers:
            return None
        if context.year and parsed.year and parsed.year != context.year:
            return None
        return result.model_copy(
            update={
                "title": self._movie_title(parsed, context),
                "original_title": result.original_title or result.title,
                "categories": [2000, 2060],
            }
        )

    def _title_matches(self, parsed: ParsedRelease, search_titles: list[str]) -> bool:
        haystacks = [
            self._normalize_title(parsed.series_title or ""),
            self._normalize_title(parsed.original_title),
        ]
        for title in search_titles:
            needle = self._normalize_title(title)
            if not needle:
                continue
            if any(needle in haystack or haystack in needle for haystack in haystacks):
                return True
        return False

    def _is_special_release(self, parsed: ParsedRelease) -> bool:
        lowered = parsed.original_title.lower()
        return any(term in lowered for term in ("ova", "oad", "special"))

    def _matches_tv_episode(
        self, parsed: ParsedRelease, context: TvSearchContext
    ) -> bool:
        seasonal_match = (
            context.season in parsed.season_numbers
            and context.episode in parsed.episode_numbers
        )
        absolute_match = (
            context.absolute_episode is not None
            and context.absolute_episode in parsed.episode_numbers
        )
        if context.absolute_episode is None:
            return seasonal_match
        return absolute_match or seasonal_match

    def _tv_title(self, parsed: ParsedRelease, context: TvSearchContext) -> str:
        group = f"[{parsed.release_group}] " if parsed.release_group else ""
        version = parsed.release_version or ""
        episode_part = f"S{context.season:02d}E{context.episode:02d}{version}"
        parts = [context.returned_title, episode_part]
        if context.absolute_episode:
            parts.append(str(context.absolute_episode))
        title = f"{group}{' - '.join(parts)}"
        metadata = self._metadata(parsed)
        if metadata and context.absolute_episode is None:
            return f"{title} - {metadata}".strip()
        return f"{title} {metadata}".strip()

    def _movie_title(self, parsed: ParsedRelease, context: MovieSearchContext) -> str:
        title = context.returned_title
        if context.year:
            title = f"{title} ({context.year})"
        metadata = self._metadata(parsed)
        if metadata:
            title = f"{title} {metadata}"
        if parsed.release_group:
            title = f"{title} -{parsed.release_group}"
        return title.strip()

    def _metadata(self, parsed: ParsedRelease) -> str:
        if parsed.metadata_suffix:
            return parsed.metadata_suffix

        parts = []
        if parsed.resolution:
            parts.append(parsed.resolution)
        if parsed.source:
            parts.append(parsed.source)
        return f"({' '.join(parts)})" if parts else ""

    def _normalize_title(self, title: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", title.casefold())
        return " ".join(normalized.split())


release_matcher = ReleaseMatcher()
