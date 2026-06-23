"""Configuration management for AnimeSonarrProxy."""

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Settings
    API_KEY: str = "your-secret-api-key-here"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Nyaa Settings
    NYAA_URL: str = "https://nyaa.si"
    NYAA_NO_REMAKES: bool = True  # Nyaa filter f=1
    NYAA_TRUSTED_ONLY: bool = False  # Nyaa filter f=2; overrides no-remakes

    # Sonarr Settings (optional - for episode metadata lookup)
    SONARR_URL: Optional[str] = None  # e.g., "http://localhost:8989"
    SONARR_API_KEY: Optional[str] = None

    # Radarr Settings (optional - for movie metadata lookup)
    RADARR_URL: Optional[str] = None  # e.g., "http://localhost:7878"
    RADARR_API_KEY: Optional[str] = None

    # Database Settings
    DATA_DIR: Path = Path("/app/data")
    ANIME_DB_URL: str = (
        "https://github.com/manami-project/anime-offline-database/releases/latest/download/anime-offline-database-minified.json"
    )
    ANIME_DB_UPDATE_INTERVAL: int = 86400  # 24 hours in seconds

    # Cache Settings
    CACHE_TTL: int = 3600  # 1 hour

    # Search Settings
    MAX_RESULTS_PER_QUERY: int = 100
    TORZNAB_DEFAULT_LANGUAGE: Optional[str] = (
        "English"  # Language metadata to attach to anime releases
    )

    # Logging
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
