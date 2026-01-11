"""Prowlarr API client for forwarding search queries."""

import logging
from typing import List, Dict, Optional, Any, Tuple
import httpx
import json
from xml.etree import ElementTree as ET
from datetime import datetime, timedelta

from app.config import settings
from app.models import SearchResult

logger = logging.getLogger(__name__)

# Cache TTL for Prowlarr search results (in seconds)
PROWLARR_CACHE_TTL = 60


class ProwlarrClient:
    """Client for interacting with Prowlarr API."""

    def __init__(self):
        self.base_url = settings.PROWLARR_URL.rstrip("/")
        self.api_key = settings.PROWLARR_API_KEY
        # Search result cache: {cache_key: (results, timestamp)}
        self._search_cache: Dict[str, Tuple[List[SearchResult], datetime]] = {}

    def _get_cache_key(self, query: str, categories: List[int], limit: int) -> str:
        """Generate cache key for a search query."""
        return f"{query}|{','.join(map(str, sorted(categories)))}|{limit}"

    def _get_cached_results(self, cache_key: str) -> Optional[List[SearchResult]]:
        """Get cached results if still valid."""
        if cache_key in self._search_cache:
            results, cached_at = self._search_cache[cache_key]
            age = (datetime.utcnow() - cached_at).total_seconds()
            if age < PROWLARR_CACHE_TTL:
                logger.debug(f"Cache hit for '{cache_key}' (age: {age:.1f}s)")
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
        logger.debug("Prowlarr search cache cleared")

    async def search(
        self,
        query: str,
        limit: Optional[int] = None,
        categories: Optional[List[int]] = None,
    ) -> List[SearchResult]:
        """
        Search Prowlarr with a query string.

        Results are cached for 60 seconds to avoid duplicate requests
        during Sonarr pagination.

        Args:
            query: Search query
            limit: Maximum results to return
            categories: Torznab category IDs (default: [5070] for TV/Anime)

        Returns:
            List of SearchResult objects
        """
        if limit is None:
            limit = settings.MAX_RESULTS_PER_QUERY

        if categories is None:
            categories = [5070]  # TV > Anime

        # Check cache first
        cache_key = self._get_cache_key(query, categories, limit)
        cached = self._get_cached_results(cache_key)
        if cached is not None:
            logger.info(f"Prowlarr cache hit for '{query}' ({len(cached)} results)")
            return cached

        # Prowlarr's /api/v1/search uses 'query' not 'q' (unlike Torznab API)
        params = {
            "query": query,
            "categories": categories,
            "limit": limit,
            "type": "search",
        }

        # Prowlarr API key goes in header, not query params
        headers = {"X-Api-Key": self.api_key}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                url = f"{self.base_url}/api/v1/search"
                logger.info(
                    f"Prowlarr request: GET {url}?query={query}&categories={categories}&limit={limit}"
                )

                response = await client.get(url, params=params, headers=headers)

                logger.debug(
                    f"Prowlarr response: status={response.status_code}, content-type={response.headers.get('content-type')}"
                )
                response.raise_for_status()

                # Parse JSON response from Prowlarr API
                results = self._parse_json_response(response.text)

                # Cache the results
                self._cache_results(cache_key, results)

                # Log first few result titles to help debug relevance issues
                if results:
                    sample_titles = [r.title for r in results[:3]]
                    logger.info(
                        f"Prowlarr search '{query}' returned {len(results)} results. Sample: {sample_titles}"
                    )
                else:
                    logger.info(f"Prowlarr search '{query}' returned 0 results")

                return results

        except httpx.HTTPError as e:
            logger.error(f"Prowlarr search failed for query '{query}': {e}")
            return []

    async def get_capabilities(self) -> Dict:
        """Get Prowlarr capabilities (for caps endpoint)."""
        params = {"t": "caps", "apikey": self.api_key}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/search", params=params
                )
                response.raise_for_status()
                return {"xml": response.text}

        except httpx.HTTPError as e:
            logger.error(f"Failed to get Prowlarr capabilities: {e}")
            return {}

    def _parse_json_response(self, json_text: str) -> List[SearchResult]:
        """Parse JSON response from Prowlarr API into SearchResult objects."""
        results = []

        try:
            # Check if response is empty
            if not json_text or not json_text.strip():
                logger.error("Prowlarr returned empty response")
                return results

            # Parse JSON array
            data = json.loads(json_text)

            if not isinstance(data, list):
                logger.error(f"Expected JSON array but got {type(data)}")
                return results

            for item in data:
                try:
                    result = self._parse_json_item(item)
                    if result:
                        results.append(result)
                except Exception as e:
                    logger.warning(f"Failed to parse search result item: {e}")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Prowlarr JSON response: {e}")
            # Log first 500 chars of response to help debug
            preview = json_text[:500] if json_text else "(empty)"
            logger.error(f"Response preview: {preview}")

        return results

    def _parse_json_item(self, item: Dict[str, Any]) -> Optional[SearchResult]:
        """Parse a single JSON item into SearchResult."""
        title = item.get("title", "")
        guid = item.get("guid", "")
        download_url = item.get("downloadUrl", "")

        if not all([title, guid, download_url]):
            return None

        # Extract fields from JSON
        size = item.get("size", 0)
        seeders = item.get("seeders", 0)
        peers = item.get("peers", 0)
        indexer = item.get("indexer", "prowlarr")

        # Parse publication date
        publish_date_str = item.get("publishDate", "")
        pub_date = self._parse_iso_date(publish_date_str)

        # Categories - Prowlarr returns categories as list of objects: [{"id": 5070, "name": "TV/Anime"}]
        categories_raw = item.get("categories", [])
        categories = []

        if isinstance(categories_raw, list):
            for cat in categories_raw:
                if isinstance(cat, dict):
                    # Extract 'id' from category object
                    cat_id = cat.get("id")
                    if cat_id is not None:
                        categories.append(cat_id)
                elif isinstance(cat, int):
                    # Already an integer
                    categories.append(cat)

        if not categories:
            categories = [5070]  # Default to anime category

        # Filter: Only accept results with valid TV/Anime categories
        # Valid categories: 5000 (TV), 5070 (TV > Anime)
        valid_categories = {5000, 5070}
        if not any(cat in valid_categories for cat in categories):
            logger.debug(
                f"Skipping result '{title}' - invalid categories: {categories}"
            )
            return None

        return SearchResult(
            title=title,
            guid=guid,
            link=download_url,
            pub_date=pub_date,
            size=size,
            seeders=seeders,
            peers=peers,
            indexer=indexer,
            categories=categories,
        )

    def _parse_iso_date(self, date_str: str) -> datetime:
        """Parse ISO 8601 date string to datetime."""
        if not date_str:
            return datetime.utcnow()

        try:
            # Try parsing ISO 8601 format (2008-06-23T03:24:00Z)
            if date_str.endswith("Z"):
                date_str = date_str[:-1] + "+00:00"
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            logger.warning(f"Could not parse date: {date_str}")
            return datetime.utcnow()

    def _parse_torznab_response(self, xml_text: str) -> List[SearchResult]:
        """Parse Torznab XML response into SearchResult objects."""
        results = []

        try:
            # Check if response is empty
            if not xml_text or not xml_text.strip():
                logger.error("Prowlarr returned empty response")
                return results

            root = ET.fromstring(xml_text)
            channel = root.find("channel")
            if channel is None:
                return results

            for item in channel.findall("item"):
                try:
                    result = self._parse_item(item)
                    if result:
                        results.append(result)
                except Exception as e:
                    logger.warning(f"Failed to parse search result item: {e}")

        except ET.ParseError as e:
            logger.error(f"Failed to parse Prowlarr XML response: {e}")
            # Log first 500 chars of response to help debug
            preview = xml_text[:500] if xml_text else "(empty)"
            logger.error(f"Response preview: {preview}")

        return results

    def _parse_item(self, item: ET.Element) -> Optional[SearchResult]:
        """Parse a single RSS item into SearchResult."""
        title = self._get_text(item, "title")
        guid = self._get_text(item, "guid")
        link = self._get_text(item, "link")
        pub_date_str = self._get_text(item, "pubDate")

        if not all([title, guid, link]):
            return None

        # Parse size from torznab attributes
        size = 0
        seeders = 0
        peers = 0
        categories = []

        # Find torznab/newznab attributes
        for attr in item.findall("{http://torznab.com/schemas/2015/feed}attr"):
            name = attr.get("name")
            value = attr.get("value")

            if name == "size":
                size = int(value) if value and value.isdigit() else 0
            elif name == "seeders":
                seeders = int(value) if value and value.isdigit() else 0
            elif name == "peers":
                peers = int(value) if value and value.isdigit() else 0
            elif name == "category":
                # Extract category and add to list
                if value and value.isdigit():
                    categories.append(int(value))

        # Parse publication date
        pub_date = self._parse_date(pub_date_str)

        # If no categories found, default to 5070 (Anime)
        if not categories:
            categories = [5070]

        # Filter: Only accept results with valid TV/Anime categories
        # Valid categories: 5000 (TV), 5070 (TV > Anime)
        valid_categories = {5000, 5070}
        if not any(cat in valid_categories for cat in categories):
            logger.debug(
                f"Skipping result '{title}' - invalid categories: {categories}"
            )
            return None

        # Try to extract indexer from enclosure url or other fields
        indexer = "prowlarr"
        enclosure = item.find("enclosure")
        if enclosure is not None:
            url = enclosure.get("url", "")
            # Try to extract indexer name from URL
            if "nyaa" in url.lower():
                indexer = "nyaa"

        return SearchResult(
            title=title,
            guid=guid,
            link=link,
            pub_date=pub_date,
            size=size,
            seeders=seeders,
            peers=peers,
            indexer=indexer,
            categories=categories,
        )

    def _get_text(self, element: ET.Element, tag: str) -> str:
        """Safely get text from XML element."""
        child = element.find(tag)
        return child.text if child is not None and child.text else ""

    def _parse_date(self, date_str: str) -> datetime:
        """Parse RSS date string to datetime."""
        if not date_str:
            return datetime.utcnow()

        # Try common RSS date formats
        formats = [
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S GMT",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        logger.warning(f"Could not parse date: {date_str}")
        return datetime.utcnow()


# Singleton instance
prowlarr_client = ProwlarrClient()
