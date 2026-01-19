"""anime-offline-database handler for offline title mapping."""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime, timedelta
import httpx

from app.config import settings
from app.models import AnimeTitle

logger = logging.getLogger(__name__)


def _is_latin_script(text: str) -> bool:
    """
    Check if a string is primarily Latin script (ASCII letters, common accents).

    Returns True if the majority of alphabetic characters are Latin-based,
    making the title suitable for searching on sites like Nyaa.

    Allows: ASCII letters, common European accented chars, numbers, punctuation.
    Rejects: CJK, Cyrillic, Arabic, Hebrew, Telugu, Thai, etc.
    """
    if not text:
        return False

    latin_count = 0
    non_latin_count = 0

    for char in text:
        if char.isalpha():
            # Basic Latin (A-Za-z) and Latin Extended (accented chars like é, ü, ñ)
            code = ord(char)
            if (
                0x0041 <= code <= 0x007A  # Basic Latin
                or 0x00C0 <= code <= 0x024F  # Latin Extended-A/B
                or 0x1E00 <= code <= 0x1EFF
            ):  # Latin Extended Additional
                latin_count += 1
            else:
                non_latin_count += 1

    # If no alphabetic chars, consider it neutral (e.g., just numbers)
    if latin_count + non_latin_count == 0:
        return True

    # Require majority Latin (>50%)
    return latin_count > non_latin_count


class AnimeOfflineDatabase:
    """Handles anime-offline-database operations."""

    def __init__(self):
        self.db_path = settings.DATA_DIR / "anime-offline-database.json"
        self.data: Dict = {}
        self.last_update: Optional[datetime] = None
        self._tvdb_index: Dict[int, Dict] = {}
        self._tmdb_index: Dict[int, Dict] = {}  # For movie lookups

    async def initialize(self):
        """Initialize database - load or download if needed."""
        if self.db_path.exists():
            await self._load_from_file()
            # Check if update needed
            if self._needs_update():
                await self.update_database()
        else:
            await self.update_database()

    def _needs_update(self) -> bool:
        """Check if database needs updating."""
        if not self.last_update:
            return True
        elapsed = datetime.utcnow() - self.last_update
        return elapsed.total_seconds() > settings.ANIME_DB_UPDATE_INTERVAL

    async def update_database(self):
        """Download latest anime-offline-database."""
        logger.info(f"Downloading anime-offline-database from {settings.ANIME_DB_URL}")
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(settings.ANIME_DB_URL)
                response.raise_for_status()

                self.data = response.json()

                # Save to file
                settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
                with open(self.db_path, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)

                self.last_update = datetime.utcnow()
                self._build_tvdb_index()
                logger.info(
                    f"Successfully updated anime-offline-database with {len(self.data.get('data', []))} entries"
                )
        except Exception as e:
            logger.error(f"Failed to update anime-offline-database: {e}")
            # If we have existing data, continue using it
            if not self.data and self.db_path.exists():
                await self._load_from_file()

    async def _load_from_file(self):
        """Load database from local file."""
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
            self.last_update = datetime.fromtimestamp(self.db_path.stat().st_mtime)
            self._build_tvdb_index()
            logger.info(
                f"Loaded anime-offline-database with {len(self.data.get('data', []))} entries"
            )
        except Exception as e:
            logger.error(f"Failed to load anime-offline-database: {e}")
            self.data = {}

    def _build_tvdb_index(self):
        """Build TVDB and TMDB ID indexes for fast lookups."""
        self._tvdb_index = {}
        self._tmdb_index = {}
        for anime in self.data.get("data", []):
            sources = anime.get("sources", [])
            for source in sources:
                if "thetvdb.com/series/" in source:
                    try:
                        # Extract TVDB ID from URL
                        tvdb_id = int(source.split("/")[-1])
                        self._tvdb_index[tvdb_id] = anime
                    except (ValueError, IndexError):
                        continue
                elif "themoviedb.org/movie/" in source:
                    try:
                        # Extract TMDB movie ID from URL
                        tmdb_id = int(source.split("/")[-1])
                        self._tmdb_index[tmdb_id] = anime
                    except (ValueError, IndexError):
                        continue

    def get_by_tvdb_id(self, tvdb_id: int) -> Optional[Dict]:
        """Get anime entry by TVDB ID."""
        return self._tvdb_index.get(tvdb_id)

    def get_by_tmdb_id(self, tmdb_id: int) -> Optional[Dict]:
        """Get anime movie entry by TMDB ID."""
        return self._tmdb_index.get(tmdb_id)

    def extract_ids(self, anime: Dict) -> Dict[str, Optional[int]]:
        """Extract AniDB, AniList and MAL IDs from anime entry."""
        ids = {"anidb_id": None, "anilist_id": None, "mal_id": None}

        for source in anime.get("sources", []):
            if (
                "anidb.net/anime/" in source
                or "anidb.net/perl-bin/animedb.pl?show=anime&aid=" in source
            ):
                try:
                    # Handle both formats:
                    # https://anidb.net/anime/12345
                    # https://anidb.net/perl-bin/animedb.pl?show=anime&aid=12345
                    if "aid=" in source:
                        aid_str = source.split("aid=")[-1].split("&")[0]
                        ids["anidb_id"] = int(aid_str)
                    else:
                        ids["anidb_id"] = int(source.split("/")[-1])
                except (ValueError, IndexError):
                    pass
            elif "anilist.co/anime/" in source:
                try:
                    ids["anilist_id"] = int(source.split("/")[-1])
                except (ValueError, IndexError):
                    pass
            elif "myanimelist.net/anime/" in source:
                try:
                    ids["mal_id"] = int(source.split("/")[-1])
                except (ValueError, IndexError):
                    pass

        return ids

    def extract_movie_ids(self, anime: Dict) -> Dict[str, Optional[any]]:
        """Extract TMDB, IMDb, AniDB, AniList and MAL IDs from anime movie entry."""
        ids = {
            "tmdb_id": None,
            "imdb_id": None,  # String like "tt1234567"
            "anidb_id": None,
            "anilist_id": None,
            "mal_id": None,
        }

        for source in anime.get("sources", []):
            if "themoviedb.org/movie/" in source:
                try:
                    ids["tmdb_id"] = int(source.split("/")[-1])
                except (ValueError, IndexError):
                    pass
            elif "imdb.com/title/" in source:
                try:
                    # Extract IMDb ID (e.g., "tt1234567")
                    imdb_part = source.split("/title/")[-1]
                    ids["imdb_id"] = imdb_part.rstrip("/").split("/")[0]
                except (ValueError, IndexError):
                    pass
            elif (
                "anidb.net/anime/" in source
                or "anidb.net/perl-bin/animedb.pl?show=anime&aid=" in source
            ):
                try:
                    if "aid=" in source:
                        aid_str = source.split("aid=")[-1].split("&")[0]
                        ids["anidb_id"] = int(aid_str)
                    else:
                        ids["anidb_id"] = int(source.split("/")[-1])
                except (ValueError, IndexError):
                    pass
            elif "anilist.co/anime/" in source:
                try:
                    ids["anilist_id"] = int(source.split("/")[-1])
                except (ValueError, IndexError):
                    pass
            elif "myanimelist.net/anime/" in source:
                try:
                    ids["mal_id"] = int(source.split("/")[-1])
                except (ValueError, IndexError):
                    pass

        return ids

    def extract_titles(self, anime: Dict) -> AnimeTitle:
        """Extract all title variations from anime entry."""
        title = anime.get("title", "")
        synonyms = anime.get("synonyms", [])

        return AnimeTitle(
            romaji=title,
            english=None,  # anime-offline-database doesn't separate these
            native=None,
            synonyms=synonyms,
        )

    def get_all_titles(self, anime: Dict) -> List[str]:
        """
        Get all unique title variations as a flat list.

        Titles are ordered with Latin-script titles first (for searchability),
        followed by non-Latin titles. The primary title is always first if Latin.
        """
        primary_title = anime.get("title", "")
        synonyms = anime.get("synonyms", [])

        # Separate Latin and non-Latin titles
        latin_titles = []
        non_latin_titles = []

        # Process primary title first
        if primary_title:
            if _is_latin_script(primary_title):
                latin_titles.append(primary_title)
            else:
                non_latin_titles.append(primary_title)

        # Process synonyms
        for synonym in synonyms:
            if synonym == primary_title:
                continue  # Skip duplicate
            if _is_latin_script(synonym):
                if synonym not in latin_titles:
                    latin_titles.append(synonym)
            else:
                if synonym not in non_latin_titles:
                    non_latin_titles.append(synonym)

        # Return Latin titles first, then non-Latin
        return latin_titles + non_latin_titles

    def search_by_title(self, query: str, limit: int = 5) -> List[Dict]:
        """
        Search for anime entries by partial title match.

        Args:
            query: Search query (partial title)
            limit: Maximum number of results

        Returns:
            List of matching anime entries with match scores
        """
        query_lower = query.lower().strip()
        if not query_lower or len(query_lower) < 3:
            return []

        matches = []
        query_words = set(query_lower.split())

        for anime in self.data.get("data", []):
            title = anime.get("title", "").lower()
            synonyms = [s.lower() for s in anime.get("synonyms", [])]
            all_titles = [title] + synonyms

            best_score = 0

            for t in all_titles:
                score = 0

                # Exact match
                if query_lower == t:
                    score = 100
                # Query is contained in title
                elif query_lower in t:
                    score = 80
                # Title starts with query
                elif t.startswith(query_lower):
                    score = 70
                # Word overlap scoring
                else:
                    title_words = set(t.split())
                    overlap = query_words & title_words
                    if overlap:
                        score = len(overlap) / max(len(query_words), 1) * 50

                best_score = max(best_score, score)

            if best_score > 20:
                matches.append({"anime": anime, "score": best_score})

        # Sort by score descending
        matches.sort(key=lambda x: x["score"], reverse=True)

        return [m["anime"] for m in matches[:limit]]

    def get_search_titles_for_query(self, query: str) -> List[str]:
        """
        Try to identify anime from query and return optimal search titles.

        This is useful when Sonarr sends a generic search with a long/concatenated query.

        Returns only Latin-script titles suitable for searching on Nyaa/torrent sites.
        Non-Latin titles (Telugu, Chinese, Japanese kanji, etc.) are filtered out
        since they won't return results.
        """
        matches = self.search_by_title(query, limit=1)
        if matches:
            anime = matches[0]
            titles = self.get_all_titles(anime)
            # Filter to only Latin-script titles (already sorted Latin-first by get_all_titles)
            latin_titles = [t for t in titles if _is_latin_script(t)]
            if latin_titles:
                # Return the main title and first synonym
                return latin_titles[:2] if len(latin_titles) > 1 else latin_titles
            # Fallback: if no Latin titles found, log warning and return first available
            logger.warning(
                f"No Latin-script titles found for anime: {anime.get('title')}"
            )
            return titles[:1] if titles else []
        return []


# Singleton instance
anime_db = AnimeOfflineDatabase()
