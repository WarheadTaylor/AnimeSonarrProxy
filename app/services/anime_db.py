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


# Singleton instance
anime_db = AnimeOfflineDatabase()
