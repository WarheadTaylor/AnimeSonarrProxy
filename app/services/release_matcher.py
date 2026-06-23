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
        matched_title = self._matched_title(parsed, context.search_titles)
        if not matched_title:
            return None

        if context.is_special:
            if not self._is_special_release(parsed):
                return None
        elif context.is_live_action:
            if not self._matches_live_action_episode(parsed, context):
                return None
        elif not self._matches_tv_episode(parsed, context):
            return None

        return result.model_copy(
            update={
                "title": self._tv_title(parsed, context, matched_title),
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
        if not self._matched_title(parsed, context.search_titles):
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

    def _matched_title(
        self, parsed: ParsedRelease, search_titles: list[str]
    ) -> Optional[str]:
        haystacks = [
            haystack
            for haystack in (
                self._normalize_title(parsed.series_title or ""),
                self._normalize_title(parsed.original_title),
            )
            if haystack
        ]
        for title in search_titles:
            needle = self._normalize_title(title)
            if not needle:
                continue
            if any(needle in haystack or haystack in needle for haystack in haystacks):
                return title
        return None

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

    def _matches_live_action_episode(
        self, parsed: ParsedRelease, context: TvSearchContext
    ) -> bool:
        if context.year and parsed.year and parsed.year != context.year:
            return False
        if parsed.season_numbers:
            return (
                context.season in parsed.season_numbers
                and context.episode in parsed.episode_numbers
            )
        if parsed.episode_numbers:
            return context.episode in parsed.episode_numbers
        return False

    def _tv_title(
        self, parsed: ParsedRelease, context: TvSearchContext, matched_title: str
    ) -> str:
        group = f"[{parsed.release_group}] " if parsed.release_group else ""
        version = parsed.release_version or ""
        episode_part = f"S{context.season:02d}E{context.episode:02d}{version}"
        returned_key = self._normalize_title(context.returned_title)
        matched_key = self._normalize_title(matched_title)
        display_title = context.returned_title
        if context.is_live_action and matched_key and matched_key != returned_key:
            display_title = f"{context.returned_title} | {matched_title}"

        parts = [display_title, episode_part]
        if context.absolute_episode and not context.is_live_action:
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
