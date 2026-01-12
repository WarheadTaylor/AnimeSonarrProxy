"""Direct Nyaa.si RSS client for anime torrent searches."""

import asyncio
import logging
import re
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from xml.etree import ElementTree as ET
from urllib.parse import quote_plus
import httpx

from app.config import settings
from app.models import SearchResult

logger = logging.getLogger(__name__)

# Cache TTL for Nyaa search results (in seconds)
NYAA_CACHE_TTL = 60

# Rate limiting defaults
NYAA_MAX_CONCURRENT_REQUESTS = 2
NYAA_REQUEST_DELAY_SECONDS = 0.5

# Nyaa category codes
NYAA_CATEGORY_ANIME_ENGLISH = "1_2"
NYAA_CATEGORY_ANIME_NON_ENGLISH = "1_3"
NYAA_CATEGORY_ANIME_RAW = "1_4"
NYAA_CATEGORY_ALL_ANIME = "1_0"
NYAA_CATEGORY_ALL = "0_0"

# Nyaa filter codes
NYAA_FILTER_NONE = "0"
NYAA_FILTER_NO_REMAKES = "1"
NYAA_FILTER_TRUSTED = "2"

# Nyaa RSS namespace
NYAA_NS = {"nyaa": "https://nyaa.si/xmlns/nyaa"}


class NyaaClient:
    """Direct client for Nyaa.si RSS feed.

    Provides the same interface as ProwlarrClient but searches Nyaa.si directly,
    allowing for better filtering (English-only, trusted uploads) and removing
    the Prowlarr middleware dependency.

    Features:
    - Combined query support using Nyaa's | (OR) operator
    - Rate limiting with semaphore and delay between requests
    - Automatic retry with backoff on 429 errors
    """

    def __init__(self):
        self.base_url = settings.NYAA_URL.rstrip("/")
        # Search result cache: {cache_key: (results, timestamp)}
        self._search_cache: Dict[str, Tuple[List[SearchResult], datetime]] = {}
        # Rate limiting
        self._semaphore = asyncio.Semaphore(NYAA_MAX_CONCURRENT_REQUESTS)
        self._last_request_time: float = 0
        self._request_lock = asyncio.Lock()

    def _get_cache_key(
        self, query: str, category: str, filter_code: str, limit: int
    ) -> str:
        """Generate cache key for a search query."""
        return f"nyaa|{query}|{category}|{filter_code}|{limit}"

    def _get_cached_results(self, cache_key: str) -> Optional[List[SearchResult]]:
        """Get cached results if still valid."""
        if cache_key in self._search_cache:
            results, cached_at = self._search_cache[cache_key]
            age = (datetime.utcnow() - cached_at).total_seconds()
            if age < NYAA_CACHE_TTL:
                logger.debug(f"Nyaa cache hit for '{cache_key}' (age: {age:.1f}s)")
                return results
            else:
                # Cache expired, remove it
                del self._search_cache[cache_key]
        return None

    def _cache_results(self, cache_key: str, results: List[SearchResult]):
        """Cache search results."""
        self._search_cache[cache_key] = (results, datetime.utcnow())
        # Prune old cache entries (keep max 100)
        if len(self._search_cache) > 100:
            oldest_key = min(
                self._search_cache.keys(), key=lambda k: self._search_cache[k][1]
            )
            del self._search_cache[oldest_key]

    def clear_cache(self):
        """Clear the search result cache."""
        self._search_cache.clear()
        logger.debug("Nyaa search cache cleared")

    def _build_rss_url(self, query: str, category: str, filter_code: str) -> str:
        """Build Nyaa RSS search URL.

        Args:
            query: Search query string
            category: Nyaa category code (e.g., "1_2" for English anime)
            filter_code: Nyaa filter code (0=none, 1=no remakes, 2=trusted only)

        Returns:
            Full RSS URL for the search
        """
        encoded_query = quote_plus(query)
        return (
            f"{self.base_url}/?page=rss&q={encoded_query}&c={category}&f={filter_code}"
        )

    def build_combined_query(
        self,
        titles: List[str],
        episodes: Optional[List[int]] = None,
        keywords: Optional[List[str]] = None,
    ) -> str:
        """Build a combined Nyaa search query using | (OR) operator.

        Nyaa search syntax:
        - foo|bar matches foo OR bar
        - "foo bar" matches exact phrase
        - (foo|bar) baz matches (foo OR bar) AND baz

        Args:
            titles: List of title variants to search for
            episodes: Optional list of episode numbers to include
            keywords: Optional list of keywords (e.g., ["OVA", "Special", "Movie"])

        Returns:
            Combined query string optimized for Nyaa search

        Examples:
            titles=["Initial D Fifth Stage", "Initial D"], episodes=[1, 27]
            -> ("Initial D Fifth Stage"|"Initial D") (1|27)

            titles=["Kaguya-sama"], keywords=["OVA", "Special"]
            -> "Kaguya-sama" (OVA|Special)
        """
        if not titles:
            return ""

        # Sanitize and quote titles (multi-word titles need quotes)
        def quote_title(t: str) -> str:
            # Escape any quotes in the title
            t = t.replace('"', "")
            # Quote if contains spaces or special chars
            if " " in t or any(c in t for c in "|()"):
                return f'"{t}"'
            return t

        quoted_titles = [quote_title(t) for t in titles if t.strip()]

        # Build title part
        if len(quoted_titles) == 1:
            title_part = quoted_titles[0]
        else:
            title_part = f"({'|'.join(quoted_titles)})"

        # Build episode part if provided
        episode_part = ""
        if episodes:
            unique_eps = sorted(set(episodes))
            if len(unique_eps) == 1:
                episode_part = str(unique_eps[0])
            else:
                episode_part = f"({'|'.join(str(e) for e in unique_eps)})"

        # Build keyword part if provided
        keyword_part = ""
        if keywords:
            unique_kw = list(dict.fromkeys(keywords))  # Preserve order, remove dupes
            if len(unique_kw) == 1:
                keyword_part = unique_kw[0]
            else:
                keyword_part = f"({'|'.join(unique_kw)})"

        # Combine parts
        parts = [title_part]
        if keyword_part:
            parts.append(keyword_part)
        if episode_part:
            parts.append(episode_part)

        combined = " ".join(parts)

        # Log the combined query for debugging
        logger.debug(f"Built combined Nyaa query: {combined}")

        return combined

    async def _rate_limited_request(
        self, client: httpx.AsyncClient, url: str, max_retries: int = 3
    ) -> httpx.Response:
        """Make a rate-limited request with retry on 429.

        Args:
            client: httpx AsyncClient to use
            url: URL to request
            max_retries: Maximum number of retries on 429

        Returns:
            httpx Response object

        Raises:
            httpx.HTTPError: On non-429 HTTP errors after retries exhausted
        """
        async with self._semaphore:
            # Enforce minimum delay between requests
            async with self._request_lock:
                now = asyncio.get_event_loop().time()
                time_since_last = now - self._last_request_time
                if time_since_last < NYAA_REQUEST_DELAY_SECONDS:
                    await asyncio.sleep(NYAA_REQUEST_DELAY_SECONDS - time_since_last)
                self._last_request_time = asyncio.get_event_loop().time()

            # Make request with retry logic for 429 errors
            last_response = await client.get(url)
            attempt = 0

            while last_response.status_code == 429 and attempt < max_retries:
                attempt += 1
                backoff = attempt * 1.0  # 1s, 2s, 3s
                logger.warning(
                    f"Nyaa rate limited (429), retrying in {backoff}s "
                    f"(attempt {attempt}/{max_retries})"
                )
                await asyncio.sleep(backoff)
                last_response = await client.get(url)

            return last_response

    async def search(
        self,
        query: str,
        limit: Optional[int] = None,
        categories: Optional[
            List[int]
        ] = None,  # Ignored - uses NYAA_ENGLISH_ONLY setting
    ) -> List[SearchResult]:
        """
        Search Nyaa.si RSS feed.

        Matches the ProwlarrClient.search() interface for drop-in replacement.

        Args:
            query: Search query
            limit: Maximum results to return (applied after fetch)
            categories: Ignored - Nyaa filtering is controlled by settings

        Returns:
            List of SearchResult objects
        """
        if limit is None:
            limit = settings.MAX_RESULTS_PER_QUERY

        # Determine category based on settings
        if settings.NYAA_ENGLISH_ONLY:
            category = NYAA_CATEGORY_ANIME_ENGLISH
        else:
            category = NYAA_CATEGORY_ALL_ANIME

        # Determine filter based on settings
        if settings.NYAA_TRUSTED_ONLY:
            filter_code = NYAA_FILTER_TRUSTED
        else:
            filter_code = NYAA_FILTER_NONE

        # Check cache first
        cache_key = self._get_cache_key(query, category, filter_code, limit)
        cached = self._get_cached_results(cache_key)
        if cached is not None:
            logger.info(f"Nyaa cache hit for '{query}' ({len(cached)} results)")
            return cached

        # Build RSS URL
        url = self._build_rss_url(query, category, filter_code)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.info(f"Nyaa RSS request: GET {url}")

                response = await self._rate_limited_request(client, url)

                logger.debug(
                    f"Nyaa response: status={response.status_code}, content-type={response.headers.get('content-type')}"
                )
                response.raise_for_status()

                # Parse RSS response
                results = self._parse_rss_response(response.text)

                # Apply limit
                if len(results) > limit:
                    results = results[:limit]

                # Sort by seeders (descending) - matching current behavior
                results.sort(key=lambda x: x.seeders, reverse=True)

                # Cache the results
                self._cache_results(cache_key, results)

                # Log sample results
                if results:
                    sample_titles = [r.title for r in results[:3]]
                    logger.info(
                        f"Nyaa search '{query}' returned {len(results)} results. Sample: {sample_titles}"
                    )
                else:
                    logger.info(f"Nyaa search '{query}' returned 0 results")

                return results

        except httpx.HTTPError as e:
            logger.error(f"Nyaa search failed for query '{query}': {e}")
            return []
        except ET.ParseError as e:
            logger.error(f"Nyaa RSS parse error for query '{query}': {e}")
            return []

    async def search_multi(
        self,
        titles: List[str],
        episodes: Optional[List[int]] = None,
        keywords: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[SearchResult]:
        """
        Search Nyaa.si using a combined query with multiple titles/episodes.

        Uses Nyaa's | (OR) operator to combine multiple search terms into
        a single query, avoiding rate limiting from multiple requests.

        Args:
            titles: List of anime title variants to search for
            episodes: Optional list of episode numbers to include
            keywords: Optional list of keywords (e.g., ["OVA", "Special"])
            limit: Maximum results to return

        Returns:
            List of SearchResult objects

        Example:
            search_multi(
                titles=["Initial D Fifth Stage", "Initial D Second Stage"],
                episodes=[1, 27, 42]
            )
            -> Single query: ("Initial D Fifth Stage"|"Initial D Second Stage") (1|27|42)
        """
        if not titles:
            logger.warning("search_multi called with empty titles list")
            return []

        # Build combined query
        combined_query = self.build_combined_query(titles, episodes, keywords)

        if not combined_query:
            logger.warning("build_combined_query returned empty string")
            return []

        logger.info(f"Nyaa combined search: {combined_query}")

        # Use the standard search method with the combined query
        return await self.search(combined_query, limit=limit)

    def _parse_rss_response(self, xml_text: str) -> List[SearchResult]:
        """Parse Nyaa RSS XML response into SearchResult objects."""
        results = []

        try:
            if not xml_text or not xml_text.strip():
                logger.error("Nyaa returned empty response")
                return results

            root = ET.fromstring(xml_text)
            channel = root.find("channel")
            if channel is None:
                logger.warning("Nyaa RSS response has no channel element")
                return results

            for item in channel.findall("item"):
                try:
                    result = self._parse_item(item)
                    if result:
                        results.append(result)
                except Exception as e:
                    logger.warning(f"Failed to parse Nyaa RSS item: {e}")

        except ET.ParseError as e:
            logger.error(f"Failed to parse Nyaa RSS XML: {e}")
            preview = xml_text[:500] if xml_text else "(empty)"
            logger.error(f"Response preview: {preview}")

        return results

    def _parse_item(self, item: ET.Element) -> Optional[SearchResult]:
        """Parse a single RSS item into SearchResult."""
        title = item.findtext("title", "")
        guid = item.findtext("guid", "")  # View URL (e.g., https://nyaa.si/view/123)
        link = item.findtext("link", "")  # .torrent download URL
        pub_date_str = item.findtext("pubDate", "")

        if not all([title, guid, link]):
            return None

        # Parse Nyaa-specific fields from nyaa namespace
        # Using namespace-aware findtext
        seeders_str = self._get_nyaa_text(item, "seeders", "0")
        leechers_str = self._get_nyaa_text(item, "leechers", "0")
        size_str = self._get_nyaa_text(item, "size", "0 B")
        category_id = self._get_nyaa_text(item, "categoryId", "")
        info_hash = self._get_nyaa_text(item, "infoHash", "")
        trusted = self._get_nyaa_text(item, "trusted", "No")

        # Parse numeric fields
        try:
            seeders = int(seeders_str)
        except ValueError:
            seeders = 0

        try:
            leechers = int(leechers_str)
        except ValueError:
            leechers = 0

        size = self._parse_size(size_str)
        pub_date = self._parse_date(pub_date_str)

        # Log trusted status for debugging
        if trusted == "Yes":
            logger.debug(f"Trusted release: {title}")

        return SearchResult(
            title=title,
            guid=guid,
            link=link,  # .torrent download URL (user preference)
            info_url=guid,  # View page URL
            pub_date=pub_date,
            size=size,
            seeders=seeders,
            peers=leechers,
            indexer="nyaa",
            categories=[5070],  # Map to Torznab TV/Anime category for Sonarr
        )

    def _get_nyaa_text(self, item: ET.Element, tag: str, default: str = "") -> str:
        """Get text from a nyaa-namespaced element."""
        # Try with namespace
        elem = item.find(f"nyaa:{tag}", NYAA_NS)
        if elem is not None and elem.text:
            return elem.text

        # Fallback: try without namespace (some RSS feeds might not use it properly)
        elem = item.find(tag)
        if elem is not None and elem.text:
            return elem.text

        return default

    def _parse_size(self, size_str: str) -> int:
        """Parse human-readable size to bytes.

        Examples:
            "5.1 GiB" -> 5476083712
            "409.1 MiB" -> 429016268
            "1.2 TiB" -> 1319413953331
        """
        if not size_str:
            return 0

        match = re.match(r"([\d.]+)\s*(TiB|GiB|MiB|KiB|B)", size_str, re.IGNORECASE)
        if not match:
            logger.warning(f"Could not parse size: {size_str}")
            return 0

        value = float(match.group(1))
        unit = match.group(2).lower()

        multipliers = {
            "b": 1,
            "kib": 1024,
            "mib": 1024**2,
            "gib": 1024**3,
            "tib": 1024**4,
        }

        return int(value * multipliers.get(unit, 1))

    def _parse_date(self, date_str: str) -> datetime:
        """Parse RSS date string to datetime.

        Nyaa uses RFC 2822 format: "Tue, 09 Sep 2025 20:24:10 -0000"
        """
        if not date_str:
            return datetime.utcnow()

        # Try common RSS date formats
        formats = [
            "%a, %d %b %Y %H:%M:%S %z",  # RFC 2822 with timezone
            "%a, %d %b %Y %H:%M:%S GMT",  # RFC 2822 with GMT
            "%a, %d %b %Y %H:%M:%S -0000",  # Nyaa's typical format
            "%Y-%m-%dT%H:%M:%S",  # ISO 8601
            "%Y-%m-%d %H:%M:%S",  # Simple format
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        logger.warning(f"Could not parse date: {date_str}")
        return datetime.utcnow()


# Singleton instance
nyaa_client = NyaaClient()
