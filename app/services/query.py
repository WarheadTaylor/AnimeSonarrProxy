"""Query builder and result deduplication for multi-query searches."""
import logging
import asyncio
from typing import List, Dict, Set
from app.config import settings
from app.models import AnimeMapping, SearchResult
from app.services.prowlarr import prowlarr_client
from app.services.episode import get_episode_translator

logger = logging.getLogger(__name__)


class QueryService:
    """Handles building search queries and deduplicating results."""

    def __init__(self):
        self.prowlarr = prowlarr_client

    async def search_anime(
        self,
        mapping: AnimeMapping,
        season: int,
        episode: int
    ) -> List[SearchResult]:
        """
        Search for an anime episode using multiple title variations.

        Strategy: Send separate queries for each title variant, then deduplicate results.

        Args:
            mapping: Anime mapping with title variations
            season: Season number
            episode: Episode number within season

        Returns:
            Deduplicated list of search results
        """
        # Get absolute episode number
        translator = get_episode_translator()
        absolute_ep = await translator.to_absolute(mapping, season, episode)

        if absolute_ep is None:
            logger.error(f"Could not determine absolute episode for TVDB {mapping.tvdb_id} S{season:02d}E{episode:02d}")
            return []

        # Get all title variations
        titles = self._get_search_titles(mapping)
        if not titles:
            logger.error(f"No titles found for TVDB {mapping.tvdb_id}")
            return []

        # Build queries for each title + episode combination
        queries = self._build_queries(titles, absolute_ep)
        logger.info(f"Searching with {len(queries)} queries for TVDB {mapping.tvdb_id} S{season:02d}E{episode:02d} (abs: {absolute_ep})")

        # Execute all queries in parallel
        all_results = await self._execute_queries(queries)

        # Deduplicate results
        if settings.ENABLE_DEDUPLICATION:
            deduplicated = self._deduplicate_results(all_results)
            logger.info(f"Deduplicated {len(all_results)} results to {len(deduplicated)}")
            return deduplicated
        else:
            return all_results

    def _get_search_titles(self, mapping: AnimeMapping) -> List[str]:
        """Extract and prioritize title variations for searching."""
        titles = []

        # Prioritize certain titles
        if mapping.titles.romaji:
            titles.append(mapping.titles.romaji)

        if mapping.titles.english:
            titles.append(mapping.titles.english)

        # Add synonyms (but limit to avoid too many queries)
        for synonym in mapping.titles.synonyms[:3]:  # Max 3 synonyms
            if synonym and synonym not in titles:
                titles.append(synonym)

        # Native title (Japanese) - useful for Nyaa
        if mapping.titles.native and mapping.titles.native not in titles:
            titles.append(mapping.titles.native)

        return titles

    def _build_queries(self, titles: List[str], absolute_episode: int) -> List[str]:
        """
        Build search query strings.

        Format: "{title} {episode}"
        Example: "Frieren 28"
        """
        queries = []

        for title in titles:
            # Primary format: "Title Episode"
            query = f"{title} {absolute_episode}"
            queries.append(query)

        return queries

    async def _execute_queries(self, queries: List[str]) -> List[SearchResult]:
        """Execute multiple search queries in parallel."""
        tasks = [
            self.prowlarr.search(query)
            for query in queries
        ]

        results_lists = await asyncio.gather(*tasks, return_exceptions=True)

        all_results = []
        for results in results_lists:
            if isinstance(results, Exception):
                logger.error(f"Query failed: {results}")
                continue
            all_results.extend(results)

        return all_results

    def _deduplicate_results(self, results: List[SearchResult]) -> List[SearchResult]:
        """
        Deduplicate search results based on GUID and similar titles.

        Priority: Higher seeders, earlier pub_date
        """
        # First pass: deduplicate by exact GUID
        seen_guids: Set[str] = set()
        unique_results: Dict[str, SearchResult] = {}

        for result in results:
            if result.guid in seen_guids:
                # Check if this one is better
                existing = unique_results.get(result.guid)
                if existing and self._is_better_result(result, existing):
                    unique_results[result.guid] = result
            else:
                seen_guids.add(result.guid)
                unique_results[result.guid] = result

        # Second pass: deduplicate by similar titles (fuzzy matching)
        # This handles cases where the same release appears on different indexers
        final_results = self._fuzzy_deduplicate(list(unique_results.values()))

        # Sort by seeders (descending) then by pub_date (newest first)
        final_results.sort(key=lambda x: (x.seeders, x.pub_date), reverse=True)

        return final_results

    def _is_better_result(self, new: SearchResult, existing: SearchResult) -> bool:
        """Determine if new result is better than existing."""
        # Prefer more seeders
        if new.seeders > existing.seeders:
            return True
        elif new.seeders < existing.seeders:
            return False

        # If same seeders, prefer newer
        return new.pub_date > existing.pub_date

    def _fuzzy_deduplicate(self, results: List[SearchResult]) -> List[SearchResult]:
        """
        Remove results with very similar titles (likely same release).

        This is a simple implementation - could be enhanced with fuzzy string matching.
        """
        if len(results) <= 1:
            return results

        # Group by normalized title
        groups: Dict[str, List[SearchResult]] = {}

        for result in results:
            normalized = self._normalize_title(result.title)
            if normalized not in groups:
                groups[normalized] = []
            groups[normalized].append(result)

        # Keep the best from each group
        final = []
        for group in groups.values():
            # Sort by quality and keep the best
            best = max(group, key=lambda x: (x.seeders, x.pub_date))
            final.append(best)

        return final

    def _normalize_title(self, title: str) -> str:
        """
        Normalize title for comparison.

        Removes common variations like resolution, quality tags, etc.
        """
        normalized = title.lower()

        # Remove common patterns
        patterns_to_remove = [
            '1080p', '720p', '480p', '2160p',
            'hevc', 'x264', 'x265', 'h264', 'h265',
            'aac', 'flac', 'mp3',
            'web-dl', 'webrip', 'bluray', 'bdrip',
            'dual audio', 'multi-sub',
            '[', ']', '(', ')', '{', '}',
        ]

        for pattern in patterns_to_remove:
            normalized = normalized.replace(pattern, ' ')

        # Collapse multiple spaces
        normalized = ' '.join(normalized.split())

        return normalized.strip()


# Singleton instance
query_service = QueryService()
