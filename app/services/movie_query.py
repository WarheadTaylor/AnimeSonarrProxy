"""Query builder and result deduplication for anime movie searches."""

import logging
import asyncio
import re
from typing import List, Set, Optional
from app.config import settings
from app.models import MovieMapping, SearchResult
from app.services.prowlarr import prowlarr_client
from app.services.nyaa import nyaa_client

logger = logging.getLogger(__name__)

# Common words to ignore when checking relevance (same as TV + movie-specific)
STOP_WORDS = {
    # Articles and prepositions
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "as", "is", "was", "are", "were", "been", "be",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "need", "this", "that",
    "these", "those", "i", "you", "he", "she", "it", "we", "they", "what",
    "which", "who", "whom", "where", "when", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such", "no",
    "nor", "not", "only", "own", "same", "so", "than", "too", "very", "just",
    # Media-related terms
    "movie", "film", "gekijouban", "theatrical", "cinema",
    "ova", "ona", "special", "specials",
    # Common anime title words
    "love", "war", "world", "story", "tale", "life", "time", "day", "days",
    "night", "girl", "girls", "boy", "boys", "man", "men", "woman", "women",
    "school", "high", "magic", "battle", "fight", "hero", "heroes", "dragon",
    "sword", "king", "queen", "prince", "princess", "knight", "angel", "demon",
    "god", "devil", "soul", "spirit", "heart", "dream", "star", "stars",
    "moon", "sun", "sky", "sea", "ocean", "fire", "ice", "dark", "light",
    "black", "white", "red", "blue", "green", "golden", "new", "last",
    "first", "final", "ultimate", "great", "super", "mega", "zero", "one",
    "two", "three", "ii", "iii", "iv",
}

# Keywords that indicate anime movies
MOVIE_KEYWORDS = ["movie", "film", "gekijouban", "theatrical"]


class MovieQueryService:
    """Handles building search queries and deduplicating results for anime movies."""

    def __init__(self):
        self.prowlarr = prowlarr_client
        # Use Nyaa client if enabled, otherwise fall back to Prowlarr
        if settings.NYAA_ENABLED:
            self.search_client = nyaa_client
            logger.info("MovieQueryService: Using Nyaa.si direct search")
        else:
            self.search_client = prowlarr_client
            logger.info("MovieQueryService: Using Prowlarr for search")

    async def search_movie(
        self,
        mapping: MovieMapping,
        year: Optional[int] = None,
    ) -> List[SearchResult]:
        """
        Search for an anime movie using multiple title variations.

        Args:
            mapping: Movie mapping with title variations
            year: Optional release year for filtering

        Returns:
            Deduplicated list of search results
        """
        # Get all title variations
        titles = self._get_search_titles(mapping)
        if not titles:
            logger.error(f"No titles found for TMDB {mapping.tmdb_id}")
            return []

        # Use year from mapping if not provided
        if year is None:
            year = mapping.year

        # Build queries for each title
        queries = self._build_queries(titles, year)
        logger.info(
            f"Searching movie with {len(queries)} queries for TMDB {mapping.tmdb_id}"
        )

        # Execute all queries in parallel
        all_results = await self._execute_queries(queries)

        # Filter out irrelevant results
        relevant_results = self.filter_relevant_results(all_results, titles)
        logger.info(
            f"Movie relevance filter: {len(all_results)} -> {len(relevant_results)} results"
        )

        # Deduplicate results
        if settings.ENABLE_DEDUPLICATION:
            deduplicated = self._deduplicate_results(relevant_results)
            logger.info(
                f"Deduplicated movie results: {len(relevant_results)} -> {len(deduplicated)}"
            )
            return deduplicated
        else:
            return relevant_results

    async def search_movie_by_query(self, query: str) -> List[SearchResult]:
        """
        Search for an anime movie by raw query string.

        Args:
            query: Search query (movie title)

        Returns:
            List of search results
        """
        # Add movie keywords to query
        queries = self._build_queries([query], year=None)

        logger.info(f"Searching movie by query: {query}")

        # Execute queries
        all_results = await self._execute_queries(queries)

        # Filter and deduplicate
        relevant_results = self.filter_relevant_results(all_results, [query])

        if settings.ENABLE_DEDUPLICATION:
            return self._deduplicate_results(relevant_results)
        return relevant_results

    def _get_search_titles(self, mapping: MovieMapping) -> List[str]:
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
        self, titles: List[str], year: Optional[int] = None
    ) -> List[str]:
        """
        Build search query strings for movies.

        For movies, we search:
        - "{title}" (plain title)
        - "{title} movie" (with movie keyword)
        - "{title} {year}" (with year if available)
        - "{title} gekijouban" (Japanese for theatrical film)
        """
        queries = []

        for title in titles:
            # Plain title search
            queries.append(title)

            # With movie keyword
            queries.append(f"{title} movie")

            # With year if available (helps filter results)
            if year:
                queries.append(f"{title} {year}")

            # Japanese theatrical keyword (common in releases)
            queries.append(f"{title} gekijouban")

        # Remove duplicates while preserving order
        seen = set()
        unique_queries = []
        for q in queries:
            q_lower = q.lower()
            if q_lower not in seen:
                seen.add(q_lower)
                unique_queries.append(q)

        return unique_queries

    async def _execute_queries(self, queries: List[str]) -> List[SearchResult]:
        """Execute multiple search queries in parallel."""
        tasks = [self.search_client.search(query) for query in queries]

        results_lists = await asyncio.gather(*tasks, return_exceptions=True)

        all_results = []
        for i, results in enumerate(results_lists):
            if isinstance(results, Exception):
                logger.error(f"Movie query failed: {results}")
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
        unique_results: dict[str, SearchResult] = {}

        for result in results:
            if result.guid in seen_guids:
                existing = unique_results.get(result.guid)
                if existing and self._is_better_result(result, existing):
                    unique_results[result.guid] = result
            else:
                seen_guids.add(result.guid)
                unique_results[result.guid] = result

        # Second pass: deduplicate by similar titles
        final_results = self._fuzzy_deduplicate(list(unique_results.values()))

        # Sort by seeders (descending) then by pub_date (newest first)
        final_results.sort(key=lambda x: (x.seeders, x.pub_date), reverse=True)

        return final_results

    def _is_better_result(self, new: SearchResult, existing: SearchResult) -> bool:
        """Determine if new result is better than existing."""
        if new.seeders > existing.seeders:
            return True
        elif new.seeders < existing.seeders:
            return False
        return new.pub_date > existing.pub_date

    def _fuzzy_deduplicate(self, results: List[SearchResult]) -> List[SearchResult]:
        """Remove results with very similar titles."""
        if len(results) <= 1:
            return results

        groups: dict[str, List[SearchResult]] = {}

        for result in results:
            normalized = self._normalize_title(result.title)
            if normalized not in groups:
                groups[normalized] = []
            groups[normalized].append(result)

        final = []
        for group in groups.values():
            best = max(group, key=lambda x: (x.seeders, x.pub_date))
            final.append(best)

        return final

    def _normalize_title(self, title: str) -> str:
        """Normalize title for comparison."""
        normalized = title.lower()

        patterns_to_remove = [
            "1080p", "720p", "480p", "2160p", "4k",
            "hevc", "x264", "x265", "h264", "h265", "av1",
            "aac", "flac", "mp3", "opus",
            "web-dl", "webrip", "bluray", "bdrip", "dvdrip",
            "dual audio", "multi-sub", "multi audio",
            "movie", "film", "gekijouban", "theatrical",
            "[", "]", "(", ")", "{", "}",
        ]

        for pattern in patterns_to_remove:
            normalized = normalized.replace(pattern, " ")

        # Remove year patterns like (2023) or [2023]
        normalized = re.sub(r"\b(19|20)\d{2}\b", " ", normalized)

        normalized = " ".join(normalized.split())
        return normalized.strip()

    def filter_relevant_results(
        self,
        results: List[SearchResult],
        search_titles: List[str],
        min_keyword_match: int = 1,
    ) -> List[SearchResult]:
        """Filter results to only include those relevant to the search titles."""
        if not results or not search_titles:
            return results

        search_keywords = self._extract_keywords(search_titles)
        if not search_keywords:
            logger.warning("No significant keywords found in movie search titles")
            return results

        logger.debug(f"Filtering movie results with keywords: {search_keywords}")

        relevant_results = []
        for result in results:
            if self._is_result_relevant(
                result.title, search_keywords, min_keyword_match
            ):
                relevant_results.append(result)
            else:
                logger.debug(f"Filtered out irrelevant movie result: {result.title}")

        return relevant_results

    def _extract_keywords(self, titles: List[str]) -> Set[str]:
        """Extract significant keywords from title strings."""
        keywords = set()

        for title in titles:
            cleaned = re.sub(r"\b\d+\b", "", title)
            cleaned = re.sub(r"[^\w\s]", " ", cleaned)

            words = cleaned.lower().split()
            for word in words:
                if word not in STOP_WORDS and len(word) >= 3:
                    keywords.add(word)

        return keywords

    def _is_result_relevant(
        self, result_title: str, search_keywords: Set[str], min_match: int = 1
    ) -> bool:
        """Check if a result title is relevant to the search keywords."""
        cleaned = re.sub(r"[^\w\s]", " ", result_title.lower())
        result_words = set(cleaned.split())

        matches = search_keywords & result_words
        match_count = len(matches)

        # Check for partial matches
        for keyword in search_keywords:
            if keyword not in matches:
                for result_word in result_words:
                    if self._is_valid_partial_match(keyword, result_word):
                        match_count += 1
                        break

        return match_count >= min_match

    def _is_valid_partial_match(self, keyword: str, result_word: str) -> bool:
        """Check if keyword and result_word have a valid partial match."""
        if len(keyword) < 4 or len(result_word) < 4:
            return False

        shorter, longer = (
            (keyword, result_word)
            if len(keyword) <= len(result_word)
            else (result_word, keyword)
        )

        if len(shorter) < len(longer) * 0.5:
            return False

        return shorter in longer


# Singleton instance
movie_query_service = MovieQueryService()
