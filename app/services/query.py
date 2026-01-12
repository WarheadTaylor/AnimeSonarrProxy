"""Query builder and result deduplication for multi-query searches."""

import logging
import asyncio
import re
from typing import List, Dict, Set, Optional
from app.config import settings
from app.models import AnimeMapping, SearchResult
from app.services.prowlarr import prowlarr_client
from app.services.nyaa import nyaa_client
from app.services.episode import get_episode_translator

logger = logging.getLogger(__name__)

# Common words to ignore when checking relevance
# Includes generic English words and common anime title words that aren't distinctive
STOP_WORDS = {
    # Articles and prepositions
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "as",
    "is",
    "was",
    "are",
    "were",
    "been",
    "be",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "must",
    "shall",
    "can",
    "need",
    "this",
    "that",
    "these",
    "those",
    "i",
    "you",
    "he",
    "she",
    "it",
    "we",
    "they",
    "what",
    "which",
    "who",
    "whom",
    "where",
    "when",
    "why",
    "how",
    "all",
    "each",
    "every",
    "both",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "no",
    "nor",
    "not",
    "only",
    "own",
    "same",
    "so",
    "than",
    "too",
    "very",
    "just",
    # Media-related terms
    "season",
    "episode",
    "ep",
    "vol",
    "volume",
    "part",
    "chapter",
    "s01",
    "s02",
    "s03",
    "s04",
    "s1",
    "s2",
    "s3",
    "s4",
    "ova",
    "ona",
    "movie",
    "film",
    "special",
    "specials",
    # Common anime title words that aren't distinctive
    "love",
    "war",
    "world",
    "story",
    "tale",
    "life",
    "time",
    "day",
    "days",
    "night",
    "girl",
    "girls",
    "boy",
    "boys",
    "man",
    "men",
    "woman",
    "women",
    "school",
    "high",
    "magic",
    "battle",
    "fight",
    "hero",
    "heroes",
    "dragon",
    "sword",
    "king",
    "queen",
    "prince",
    "princess",
    "knight",
    "angel",
    "demon",
    "god",
    "devil",
    "soul",
    "spirit",
    "heart",
    "dream",
    "star",
    "stars",
    "moon",
    "sun",
    "sky",
    "sea",
    "ocean",
    "fire",
    "ice",
    "dark",
    "light",
    "black",
    "white",
    "red",
    "blue",
    "green",
    "golden",
    "new",
    "last",
    "first",
    "final",
    "ultimate",
    "great",
    "super",
    "mega",
    "zero",
    "one",
    "two",
    "three",
    "ii",
    "iii",
    "iv",
}


class QueryService:
    """Handles building search queries and deduplicating results."""

    def __init__(self):
        self.prowlarr = prowlarr_client
        # Use Nyaa client if enabled, otherwise fall back to Prowlarr
        if settings.NYAA_ENABLED:
            self.search_client = nyaa_client
            logger.info("Using Nyaa.si direct search (NYAA_ENABLED=True)")
        else:
            self.search_client = prowlarr_client
            logger.info("Using Prowlarr for search (NYAA_ENABLED=False)")

    async def search_anime(
        self, mapping: AnimeMapping, season: int, episode: int
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
            logger.error(
                f"Could not determine absolute episode for TVDB {mapping.tvdb_id} S{season:02d}E{episode:02d}"
            )
            return []

        # Get all title variations
        titles = self._get_search_titles(mapping)
        if not titles:
            logger.error(f"No titles found for TVDB {mapping.tvdb_id}")
            return []

        # Detect if this is a special (season 0)
        is_special = season == 0

        # Build queries for each title + episode combination
        queries = self._build_queries(titles, absolute_ep, is_special=is_special)
        logger.info(
            f"Searching with {len(queries)} queries for TVDB {mapping.tvdb_id} S{season:02d}E{episode:02d} (abs: {absolute_ep}){' [SPECIAL]' if is_special else ''}"
        )

        # Execute all queries in parallel
        all_results = await self._execute_queries(queries)

        # Filter out irrelevant results (results that don't match any search title)
        relevant_results = self.filter_relevant_results(all_results, titles)
        logger.info(
            f"Relevance filter: {len(all_results)} -> {len(relevant_results)} results"
        )

        # Deduplicate results
        if settings.ENABLE_DEDUPLICATION:
            deduplicated = self._deduplicate_results(relevant_results)
            logger.info(
                f"Deduplicated {len(relevant_results)} results to {len(deduplicated)}"
            )
            return deduplicated
        else:
            return relevant_results

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

    def _build_queries(
        self, titles: List[str], absolute_episode: int, is_special: bool = False
    ) -> List[str]:
        """
        Build search query strings.

        Format: "{title} {episode}" or "{title} OVA/Special" for specials
        Example: "Frieren 28" or "Kaguya-sama OVA"
        """
        queries = []

        for title in titles:
            if is_special:
                # For specials (season 0), search with OVA/Special/Movie keywords
                # Episode number might not match, so also search without it
                queries.append(f"{title} OVA")
                queries.append(f"{title} Special")
                queries.append(f"{title} OVA {absolute_episode}")
                queries.append(f"{title} Special {absolute_episode}")
                # Some specials are movies
                queries.append(f"{title} Movie")
            else:
                # Regular episode: "Title Episode"
                query = f"{title} {absolute_episode}"
                queries.append(query)

        # Remove duplicates while preserving order
        seen = set()
        unique_queries = []
        for q in queries:
            if q not in seen:
                seen.add(q)
                unique_queries.append(q)

        return unique_queries

    async def _execute_queries(self, queries: List[str]) -> List[SearchResult]:
        """Execute multiple search queries in parallel."""
        tasks = [self.search_client.search(query) for query in queries]

        results_lists = await asyncio.gather(*tasks, return_exceptions=True)

        all_results = []
        for i, results in enumerate(results_lists):
            if isinstance(results, Exception):
                logger.error(f"Query failed: {results}")
                # Fallback to Prowlarr if Nyaa is enabled but failed
                if settings.NYAA_ENABLED and settings.NYAA_FALLBACK_TO_PROWLARR:
                    logger.info(f"Falling back to Prowlarr for query: {queries[i]}")
                    try:
                        fallback_results = await self.prowlarr.search(queries[i])
                        all_results.extend(fallback_results)
                    except Exception as e:
                        logger.error(f"Prowlarr fallback also failed: {e}")
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
            "1080p",
            "720p",
            "480p",
            "2160p",
            "hevc",
            "x264",
            "x265",
            "h264",
            "h265",
            "aac",
            "flac",
            "mp3",
            "web-dl",
            "webrip",
            "bluray",
            "bdrip",
            "dual audio",
            "multi-sub",
            "[",
            "]",
            "(",
            ")",
            "{",
            "}",
        ]

        for pattern in patterns_to_remove:
            normalized = normalized.replace(pattern, " ")

        # Collapse multiple spaces
        normalized = " ".join(normalized.split())

        return normalized.strip()

    def filter_relevant_results(
        self,
        results: List[SearchResult],
        search_titles: List[str],
        min_keyword_match: int = 1,
    ) -> List[SearchResult]:
        """
        Filter results to only include those relevant to the search titles.

        Args:
            results: List of search results to filter
            search_titles: List of title variations we searched for
            min_keyword_match: Minimum number of keywords that must match

        Returns:
            Filtered list of relevant results
        """
        if not results or not search_titles:
            return results

        # Extract significant keywords from all search titles
        search_keywords = self._extract_keywords(search_titles)
        if not search_keywords:
            logger.warning("No significant keywords found in search titles")
            return results

        logger.debug(f"Filtering results with keywords: {search_keywords}")

        relevant_results = []
        for result in results:
            if self._is_result_relevant(
                result.title, search_keywords, min_keyword_match
            ):
                relevant_results.append(result)
            else:
                logger.debug(f"Filtered out irrelevant result: {result.title}")

        filtered_count = len(results) - len(relevant_results)
        if filtered_count > 0:
            logger.info(
                f"Filtered out {filtered_count} irrelevant results (kept {len(relevant_results)})"
            )

        return relevant_results

    def _extract_keywords(self, titles: List[str]) -> Set[str]:
        """
        Extract significant keywords from title strings.

        Removes stop words, numbers, and short words.
        """
        keywords = set()

        for title in titles:
            # Remove episode numbers and common patterns
            cleaned = re.sub(r"\b\d+\b", "", title)  # Remove standalone numbers
            cleaned = re.sub(r"[^\w\s]", " ", cleaned)  # Remove punctuation

            words = cleaned.lower().split()
            for word in words:
                # Skip stop words and very short words
                if word not in STOP_WORDS and len(word) >= 3:
                    keywords.add(word)

        return keywords

    def _is_result_relevant(
        self, result_title: str, search_keywords: Set[str], min_match: int = 1
    ) -> bool:
        """
        Check if a result title is relevant to the search keywords.

        Args:
            result_title: The title of the search result
            search_keywords: Set of keywords we're looking for
            min_match: Minimum number of keywords that must match

        Returns:
            True if the result is relevant
        """
        # Clean and extract words from result title
        cleaned = re.sub(r"[^\w\s]", " ", result_title.lower())
        result_words = set(cleaned.split())

        # Count matching keywords
        matches = search_keywords & result_words
        match_count = len(matches)

        # Also check for partial matches (keyword is substring of result word)
        # This handles cases like "Kaguya" matching "Kaguyasama"
        # But we need to be strict - the shorter word must be substantial
        for keyword in search_keywords:
            if keyword not in matches:
                for result_word in result_words:
                    if self._is_valid_partial_match(keyword, result_word):
                        match_count += 1
                        break

        return match_count >= min_match

    def _is_valid_partial_match(self, keyword: str, result_word: str) -> bool:
        """
        Check if keyword and result_word have a valid partial match.

        To avoid false positives like "a" matching "kaguya", we require:
        - The shorter word must be at least 4 characters
        - The shorter word must be at least 50% the length of the longer word
        - One must be a substring of the other
        """
        if len(keyword) < 4 or len(result_word) < 4:
            return False

        shorter, longer = (
            (keyword, result_word)
            if len(keyword) <= len(result_word)
            else (result_word, keyword)
        )

        # Shorter word must be at least 50% of longer word's length
        if len(shorter) < len(longer) * 0.5:
            return False

        # Check substring relationship
        return shorter in longer


def filter_results_by_query(
    results: List[SearchResult], query: str, min_keyword_match: int = 1
) -> List[SearchResult]:
    """
    Standalone function to filter results based on a query string.

    Useful for generic searches where we don't have an AnimeMapping.

    Args:
        results: List of search results to filter
        query: The search query string
        min_keyword_match: Minimum number of keywords that must match

    Returns:
        Filtered list of relevant results
    """
    return query_service.filter_relevant_results(results, [query], min_keyword_match)


# Singleton instance
query_service = QueryService()
