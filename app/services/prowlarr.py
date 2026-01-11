"""Prowlarr API client for forwarding search queries."""
import logging
from typing import List, Dict, Optional
import httpx
from xml.etree import ElementTree as ET
from datetime import datetime

from app.config import settings
from app.models import SearchResult

logger = logging.getLogger(__name__)


class ProwlarrClient:
    """Client for interacting with Prowlarr API."""

    def __init__(self):
        self.base_url = settings.PROWLARR_URL.rstrip('/')
        self.api_key = settings.PROWLARR_API_KEY

    async def search(
        self,
        query: str,
        limit: Optional[int] = None,
        categories: Optional[List[int]] = None
    ) -> List[SearchResult]:
        """
        Search Prowlarr with a query string.

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

        params = {
            "t": "search",
            "q": query,
            "apikey": self.api_key,
            "limit": limit,
            "cat": ",".join(map(str, categories))
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/search",
                    params=params
                )
                response.raise_for_status()

                # Parse Torznab XML response
                results = self._parse_torznab_response(response.text)
                logger.info(f"Prowlarr search '{query}' returned {len(results)} results")
                return results

        except httpx.HTTPError as e:
            logger.error(f"Prowlarr search failed for query '{query}': {e}")
            return []

    async def get_capabilities(self) -> Dict:
        """Get Prowlarr capabilities (for caps endpoint)."""
        params = {
            "t": "caps",
            "apikey": self.api_key
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/search",
                    params=params
                )
                response.raise_for_status()
                return {"xml": response.text}

        except httpx.HTTPError as e:
            logger.error(f"Failed to get Prowlarr capabilities: {e}")
            return {}

    def _parse_torznab_response(self, xml_text: str) -> List[SearchResult]:
        """Parse Torznab XML response into SearchResult objects."""
        results = []

        try:
            root = ET.fromstring(xml_text)
            channel = root.find('channel')
            if channel is None:
                return results

            for item in channel.findall('item'):
                try:
                    result = self._parse_item(item)
                    if result:
                        results.append(result)
                except Exception as e:
                    logger.warning(f"Failed to parse search result item: {e}")

        except ET.ParseError as e:
            logger.error(f"Failed to parse Prowlarr XML response: {e}")

        return results

    def _parse_item(self, item: ET.Element) -> Optional[SearchResult]:
        """Parse a single RSS item into SearchResult."""
        title = self._get_text(item, 'title')
        guid = self._get_text(item, 'guid')
        link = self._get_text(item, 'link')
        pub_date_str = self._get_text(item, 'pubDate')

        if not all([title, guid, link]):
            return None

        # Parse size from torznab attributes
        size = 0
        seeders = 0
        peers = 0
        categories = []

        # Find torznab/newznab attributes
        for attr in item.findall('{http://torznab.com/schemas/2015/feed}attr'):
            name = attr.get('name')
            value = attr.get('value')

            if name == 'size':
                size = int(value) if value and value.isdigit() else 0
            elif name == 'seeders':
                seeders = int(value) if value and value.isdigit() else 0
            elif name == 'peers':
                peers = int(value) if value and value.isdigit() else 0
            elif name == 'category':
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
            logger.debug(f"Skipping result '{title}' - invalid categories: {categories}")
            return None

        # Try to extract indexer from enclosure url or other fields
        indexer = "prowlarr"
        enclosure = item.find('enclosure')
        if enclosure is not None:
            url = enclosure.get('url', '')
            # Try to extract indexer name from URL
            if 'nyaa' in url.lower():
                indexer = 'nyaa'

        return SearchResult(
            title=title,
            guid=guid,
            link=link,
            pub_date=pub_date,
            size=size,
            seeders=seeders,
            peers=peers,
            indexer=indexer,
            categories=categories
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
            "%Y-%m-%d %H:%M:%S"
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
