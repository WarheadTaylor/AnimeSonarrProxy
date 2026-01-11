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


class AnimeOfflineDatabase:
    """Handles anime-offline-database operations."""

    def __init__(self):
        self.db_path = settings.DATA_DIR / "anime-offline-database.json"
        self.data: Dict = {}
        self.last_update: Optional[datetime] = None
        self._tvdb_index: Dict[int, Dict] = {}

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
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(settings.ANIME_DB_URL)
                response.raise_for_status()

                self.data = response.json()

                # Save to file
                settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
                with open(self.db_path, 'w', encoding='utf-8') as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)

                self.last_update = datetime.utcnow()
                self._build_tvdb_index()
                logger.info(f"Successfully updated anime-offline-database with {len(self.data.get('data', []))} entries")
        except Exception as e:
            logger.error(f"Failed to update anime-offline-database: {e}")
            # If we have existing data, continue using it
            if not self.data and self.db_path.exists():
                await self._load_from_file()

    async def _load_from_file(self):
        """Load database from local file."""
        try:
            with open(self.db_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            self.last_update = datetime.fromtimestamp(self.db_path.stat().st_mtime)
            self._build_tvdb_index()
            logger.info(f"Loaded anime-offline-database with {len(self.data.get('data', []))} entries")
        except Exception as e:
            logger.error(f"Failed to load anime-offline-database: {e}")
            self.data = {}

    def _build_tvdb_index(self):
        """Build TVDB ID index for fast lookups."""
        self._tvdb_index = {}
        for anime in self.data.get('data', []):
            sources = anime.get('sources', [])
            for source in sources:
                if 'thetvdb.com/series/' in source:
                    try:
                        # Extract TVDB ID from URL
                        tvdb_id = int(source.split('/')[-1])
                        self._tvdb_index[tvdb_id] = anime
                    except (ValueError, IndexError):
                        continue

    def get_by_tvdb_id(self, tvdb_id: int) -> Optional[Dict]:
        """Get anime entry by TVDB ID."""
        return self._tvdb_index.get(tvdb_id)

    def extract_ids(self, anime: Dict) -> Dict[str, Optional[int]]:
        """Extract AniList and MAL IDs from anime entry."""
        ids = {"anilist_id": None, "mal_id": None}

        for source in anime.get('sources', []):
            if 'anilist.co/anime/' in source:
                try:
                    ids["anilist_id"] = int(source.split('/')[-1])
                except (ValueError, IndexError):
                    pass
            elif 'myanimelist.net/anime/' in source:
                try:
                    ids["mal_id"] = int(source.split('/')[-1])
                except (ValueError, IndexError):
                    pass

        return ids

    def extract_titles(self, anime: Dict) -> AnimeTitle:
        """Extract all title variations from anime entry."""
        title = anime.get('title', '')
        synonyms = anime.get('synonyms', [])

        return AnimeTitle(
            romaji=title,
            english=None,  # anime-offline-database doesn't separate these
            native=None,
            synonyms=synonyms
        )

    def get_all_titles(self, anime: Dict) -> List[str]:
        """Get all unique title variations as a flat list."""
        titles = set()

        if anime.get('title'):
            titles.add(anime['title'])

        for synonym in anime.get('synonyms', []):
            titles.add(synonym)

        return list(titles)

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

        for anime in self.data.get('data', []):
            title = anime.get('title', '').lower()
            synonyms = [s.lower() for s in anime.get('synonyms', [])]
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
                matches.append({
                    'anime': anime,
                    'score': best_score
                })

        # Sort by score descending
        matches.sort(key=lambda x: x['score'], reverse=True)

        return [m['anime'] for m in matches[:limit]]

    def get_search_titles_for_query(self, query: str) -> List[str]:
        """
        Try to identify anime from query and return optimal search titles.

        This is useful when Sonarr sends a generic search with a long/concatenated query.
        """
        matches = self.search_by_title(query, limit=1)
        if matches:
            anime = matches[0]
            titles = self.get_all_titles(anime)
            # Return the main title and first synonym
            return titles[:2] if len(titles) > 1 else titles
        return []


# Singleton instance
anime_db = AnimeOfflineDatabase()
