"""AniList API client with rate limiting and caching."""
import asyncio
import logging
from typing import Optional, Dict, List
from datetime import datetime, timedelta
import httpx

from app.config import settings
from app.models import AnimeTitle

logger = logging.getLogger(__name__)


class AniListClient:
    """AniList GraphQL API client."""

    QUERY_BY_TVDB = """
    query ($tvdbId: Int) {
      Media(idMal: $tvdbId, type: ANIME) {
        id
        idMal
        title {
          romaji
          english
          native
        }
        synonyms
        episodes
        format
        season
        seasonYear
      }
    }
    """

    QUERY_BY_ID = """
    query ($id: Int) {
      Media(id: $id, type: ANIME) {
        id
        idMal
        title {
          romaji
          english
          native
        }
        synonyms
        episodes
        format
        season
        seasonYear
      }
    }
    """

    def __init__(self):
        self.api_url = settings.ANILIST_API_URL
        self.rate_limit_tokens = settings.ANILIST_RATE_LIMIT
        self.rate_limit_window = 60  # seconds
        self.last_reset = datetime.utcnow()
        self._lock = asyncio.Lock()

    async def _wait_for_rate_limit(self):
        """Handle rate limiting."""
        async with self._lock:
            now = datetime.utcnow()
            if (now - self.last_reset).total_seconds() >= self.rate_limit_window:
                self.rate_limit_tokens = settings.ANILIST_RATE_LIMIT
                self.last_reset = now

            if self.rate_limit_tokens <= 0:
                wait_time = self.rate_limit_window - (now - self.last_reset).total_seconds()
                if wait_time > 0:
                    logger.warning(f"Rate limit reached, waiting {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)
                    self.rate_limit_tokens = settings.ANILIST_RATE_LIMIT
                    self.last_reset = datetime.utcnow()

            self.rate_limit_tokens -= 1

    async def _query(self, query: str, variables: Dict) -> Optional[Dict]:
        """Execute GraphQL query with rate limiting."""
        await self._wait_for_rate_limit()

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.api_url,
                    json={"query": query, "variables": variables},
                    headers={"Content-Type": "application/json", "Accept": "application/json"}
                )
                response.raise_for_status()
                data = response.json()

                if "errors" in data:
                    logger.error(f"AniList API error: {data['errors']}")
                    return None

                return data.get("data", {}).get("Media")
        except httpx.HTTPError as e:
            logger.error(f"AniList API request failed: {e}")
            return None

    async def get_by_tvdb_id(self, tvdb_id: int) -> Optional[Dict]:
        """
        Get anime info by TVDB ID.
        Note: AniList doesn't have TVDB mapping, this is a placeholder.
        We rely on anime-offline-database for TVDB -> AniList mapping.
        """
        logger.warning("AniList API doesn't support direct TVDB lookup")
        return None

    async def get_by_anilist_id(self, anilist_id: int) -> Optional[Dict]:
        """Get anime info by AniList ID."""
        return await self._query(self.QUERY_BY_ID, {"id": anilist_id})

    def extract_titles(self, media: Dict) -> AnimeTitle:
        """Extract title information from AniList response."""
        title_data = media.get("title", {})

        return AnimeTitle(
            romaji=title_data.get("romaji"),
            english=title_data.get("english"),
            native=title_data.get("native"),
            synonyms=media.get("synonyms", [])
        )

    def get_all_titles(self, media: Dict) -> List[str]:
        """Get all unique title variations as a flat list."""
        titles = set()

        title_data = media.get("title", {})
        for key in ["romaji", "english", "native"]:
            if title_data.get(key):
                titles.add(title_data[key])

        for synonym in media.get("synonyms", []):
            if synonym:
                titles.add(synonym)

        return list(titles)

    def get_episode_count(self, media: Dict) -> int:
        """Get total episode count from AniList data."""
        return media.get("episodes") or 0


# Singleton instance
anilist_client = AniListClient()
