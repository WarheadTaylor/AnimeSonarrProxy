"""Radarr API client for movie metadata lookup."""

import logging
from typing import Optional, Dict, Any, List
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class MovieInfo:
    """Movie information from Radarr API."""

    def __init__(
        self,
        radarr_id: int,
        title: str,
        tmdb_id: Optional[int] = None,
        imdb_id: Optional[str] = None,
        year: Optional[int] = None,
        original_title: Optional[str] = None,
        alternative_titles: Optional[List[str]] = None,
    ):
        self.radarr_id = radarr_id
        self.title = title
        self.tmdb_id = tmdb_id
        self.imdb_id = imdb_id
        self.year = year
        self.original_title = original_title
        self.alternative_titles = alternative_titles or []

    @classmethod
    def from_radarr_response(cls, data: Dict[str, Any]) -> "MovieInfo":
        """Create MovieInfo from Radarr API response."""
        alt_titles = []
        for alt in data.get("alternateTitles", []):
            if alt.get("title"):
                alt_titles.append(alt["title"])

        return cls(
            radarr_id=data.get("id", 0),
            title=data.get("title", ""),
            tmdb_id=data.get("tmdbId"),
            imdb_id=data.get("imdbId"),
            year=data.get("year"),
            original_title=data.get("originalTitle"),
            alternative_titles=alt_titles,
        )


class RadarrClient:
    """Client for Radarr API v3.

    Used to get movie metadata (titles, IDs) for enhanced searching.
    """

    def __init__(self):
        self._base_url: Optional[str] = None
        self._api_key: Optional[str] = None
        self._movie_cache: Dict[int, Dict[str, Any]] = {}  # tmdb_id -> movie data
        self._imdb_to_tmdb: Dict[str, int] = {}  # imdb_id -> tmdb_id

    def configure(self, base_url: Optional[str], api_key: Optional[str]):
        """Configure the Radarr client with URL and API key."""
        if base_url and api_key:
            self._base_url = base_url.rstrip("/")
            self._api_key = api_key
            logger.info(f"Radarr client configured: {self._base_url}")
        else:
            self._base_url = None
            self._api_key = None
            logger.info("Radarr client not configured (missing URL or API key)")

    def is_configured(self) -> bool:
        """Check if Radarr integration is enabled and configured."""
        return bool(self._base_url and self._api_key)

    async def get_movie_by_tmdb_id(self, tmdb_id: int) -> Optional[MovieInfo]:
        """
        Get movie information from Radarr by TMDB ID.

        Args:
            tmdb_id: TMDB movie ID

        Returns:
            MovieInfo or None if not found
        """
        if not self.is_configured():
            return None

        # Check cache first
        if tmdb_id in self._movie_cache:
            logger.debug(f"Using cached movie data for TMDB {tmdb_id}")
            return MovieInfo.from_radarr_response(self._movie_cache[tmdb_id])

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Search for movie by TMDB ID
                response = await client.get(
                    f"{self._base_url}/api/v3/movie",
                    params={"tmdbId": tmdb_id},
                    headers={"X-Api-Key": self._api_key},
                )
                response.raise_for_status()

                movies = response.json()

                if movies and len(movies) > 0:
                    movie = movies[0]
                    self._movie_cache[tmdb_id] = movie

                    # Also cache IMDb -> TMDB mapping
                    if movie.get("imdbId"):
                        self._imdb_to_tmdb[movie["imdbId"]] = tmdb_id

                    logger.info(
                        f"Found movie in Radarr: '{movie.get('title')}' "
                        f"(ID: {movie.get('id')}, TMDB: {tmdb_id})"
                    )
                    return MovieInfo.from_radarr_response(movie)
                else:
                    logger.debug(f"No movie found in Radarr for TMDB {tmdb_id}")
                    return None

        except httpx.HTTPStatusError as e:
            logger.error(f"Radarr API error for TMDB {tmdb_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to query Radarr for TMDB {tmdb_id}: {e}")
            return None

    async def get_movie_by_imdb_id(self, imdb_id: str) -> Optional[MovieInfo]:
        """
        Get movie information from Radarr by IMDb ID.

        Args:
            imdb_id: IMDb movie ID (e.g., "tt1234567")

        Returns:
            MovieInfo or None if not found
        """
        if not self.is_configured():
            return None

        # Check if we have a cached TMDB ID for this IMDb ID
        if imdb_id in self._imdb_to_tmdb:
            return await self.get_movie_by_tmdb_id(self._imdb_to_tmdb[imdb_id])

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Search for movie by IMDb ID
                response = await client.get(
                    f"{self._base_url}/api/v3/movie",
                    params={"imdbId": imdb_id},
                    headers={"X-Api-Key": self._api_key},
                )
                response.raise_for_status()

                movies = response.json()

                if movies and len(movies) > 0:
                    movie = movies[0]
                    tmdb_id = movie.get("tmdbId")

                    if tmdb_id:
                        self._movie_cache[tmdb_id] = movie
                        self._imdb_to_tmdb[imdb_id] = tmdb_id

                    logger.info(
                        f"Found movie in Radarr: '{movie.get('title')}' "
                        f"(ID: {movie.get('id')}, IMDb: {imdb_id})"
                    )
                    return MovieInfo.from_radarr_response(movie)
                else:
                    logger.debug(f"No movie found in Radarr for IMDb {imdb_id}")
                    return None

        except httpx.HTTPStatusError as e:
            logger.error(f"Radarr API error for IMDb {imdb_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to query Radarr for IMDb {imdb_id}: {e}")
            return None

    async def lookup_movie(self, query: str) -> List[MovieInfo]:
        """
        Search for movies in Radarr by title.

        Args:
            query: Movie title to search for

        Returns:
            List of matching MovieInfo objects
        """
        if not self.is_configured():
            return []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self._base_url}/api/v3/movie/lookup",
                    params={"term": query},
                    headers={"X-Api-Key": self._api_key},
                )
                response.raise_for_status()

                movies = response.json()

                results = []
                for movie in movies[:10]:  # Limit to 10 results
                    movie_info = MovieInfo.from_radarr_response(movie)
                    results.append(movie_info)

                    # Cache TMDB -> movie mapping
                    if movie.get("tmdbId"):
                        self._movie_cache[movie["tmdbId"]] = movie
                        if movie.get("imdbId"):
                            self._imdb_to_tmdb[movie["imdbId"]] = movie["tmdbId"]

                logger.info(f"Radarr lookup for '{query}' returned {len(results)} movies")
                return results

        except httpx.HTTPStatusError as e:
            logger.error(f"Radarr lookup error for '{query}': {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to lookup movie in Radarr: {e}")
            return []

    def clear_cache(self):
        """Clear all cached data."""
        self._movie_cache.clear()
        self._imdb_to_tmdb.clear()
        logger.debug("Radarr cache cleared")


# Singleton instance
radarr_client = RadarrClient()
