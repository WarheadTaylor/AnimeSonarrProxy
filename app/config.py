"""Configuration management for AnimeSonarrProxy."""

from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Settings
    API_KEY: str = "your-secret-api-key-here"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Prowlarr Settings
    PROWLARR_URL: str = "http://localhost:9696"
    PROWLARR_API_KEY: str = ""

    # AniList API Settings
    ANILIST_API_URL: str = "https://graphql.anilist.co"
    ANILIST_RATE_LIMIT: int = 90  # requests per minute

    # Database Settings
    DATA_DIR: Path = Path("/app/data")
    ANIME_DB_URL: str = "https://github.com/manami-project/anime-offline-database/releases/latest/download/anime-offline-database-minified.json"
    ANIME_DB_UPDATE_INTERVAL: int = 86400  # 24 hours in seconds

    # Cache Settings
    CACHE_TTL: int = 3600  # 1 hour
    MAPPING_CACHE_TTL: int = 604800  # 1 week

    # Search Settings
    MAX_RESULTS_PER_QUERY: int = 100
    ENABLE_DEDUPLICATION: bool = True

    # Logging
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
