"""Configuration management for AnimeSonarrProxy."""

import json
from pathlib import Path
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings


class NewznabProviderSettings(BaseModel):
    """Configuration for one upstream Newznab provider."""

    id: str
    name: str
    url: str
    api_key: str
    enabled: bool = True
    categories: List[int] = Field(default_factory=lambda: [5070])
    priority: int = 100
    timeout: float = 30.0


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

    # Newznab Settings (optional - for upstream Usenet providers)
    NEWZNAB_PROVIDERS: List[NewznabProviderSettings] = Field(default_factory=list)
    NEWZNAB_URL: Optional[str] = None
    NEWZNAB_API_KEY: Optional[str] = None
    NEWZNAB_ID: str = "newznab"
    NEWZNAB_NAME: str = "Newznab"
    NEWZNAB_CATEGORIES: List[int] = Field(default_factory=lambda: [5070])
    NEWZNAB_MAX_QUERY_VARIANTS: int = 8
    NEWZNAB_DEFAULT_CATEGORIES: List[int] = Field(default_factory=lambda: [5070])
    PUBLIC_BASE_URL: Optional[str] = None

    @field_validator(
        "NEWZNAB_CATEGORIES", "NEWZNAB_DEFAULT_CATEGORIES", mode="before"
    )
    @classmethod
    def parse_newznab_categories(cls, value: Any) -> Any:
        """Allow Newznab category lists as JSON arrays or comma-separated text."""
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                return json.loads(stripped)
            return [
                int(category.strip())
                for category in stripped.split(",")
                if category.strip()
            ]
        return value

    @field_validator("NEWZNAB_PROVIDERS", mode="before")
    @classmethod
    def parse_newznab_providers(cls, value: Any) -> Any:
        """Allow Newznab providers as JSON text from environment variables."""
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            return json.loads(stripped)
        return value

    # Sonarr Settings (optional - for episode metadata lookup)
    SONARR_URL: Optional[str] = None  # e.g., "http://localhost:8989"
    SONARR_API_KEY: Optional[str] = None

    # Radarr Settings (optional - for movie metadata lookup)
    RADARR_URL: Optional[str] = None  # e.g., "http://localhost:7878"
    RADARR_API_KEY: Optional[str] = None

    # Live-action drama metadata settings
    TMDB_API_KEY: Optional[str] = None
    DRAMA_METADATA_ENABLED: bool = True
    DRAMA_METADATA_SOURCE_ORDER: List[str] = Field(
        default_factory=lambda: ["sonarr", "tmdb", "tvmaze"]
    )

    @field_validator("DRAMA_METADATA_SOURCE_ORDER", mode="before")
    @classmethod
    def parse_drama_metadata_source_order(cls, value: Any) -> Any:
        """Allow drama metadata source order as JSON or comma-separated text."""
        if isinstance(value, str) and not value.strip().startswith("["):
            return [source.strip() for source in value.split(",") if source.strip()]
        return value

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
