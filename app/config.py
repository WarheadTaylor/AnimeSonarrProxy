"""Configuration management for AnimeSonarrProxy."""

import json
from pathlib import Path
from typing import Annotated, Any, List, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode


class NewznabProviderSettings(BaseModel):
    """Configuration for one upstream Newznab provider."""

    id: str
    name: str
    url: str
    api_path: Optional[str] = None
    api_key: str
    enabled: bool = True
    categories: List[int] = Field(default_factory=lambda: [5070])
    priority: int = 100
    timeout: float = 30.0

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """Require an HTTP API URL without embedded credentials or query fields."""
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Use an HTTP(S) API URL; put the API key in api_key")
        return value

    @field_validator("api_path")
    @classmethod
    def validate_api_path(cls, value: Optional[str]) -> Optional[str]:
        """Allow an explicit API path relative to the provider base URL."""
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if (
            not value.startswith("/")
            or value.startswith("//")
            or any(char in value for char in "?#")
        ):
            raise ValueError("API path must start with / and have no query or fragment")
        return value.rstrip("/")

    @property
    def api_url(self) -> str:
        """Return the full endpoint, preserving providers that serve their API at /."""
        return self.url.rstrip("/") + (self.api_path or "")


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
    NEWZNAB_API_PATH: Optional[str] = None
    NEWZNAB_API_KEY: Optional[str] = None
    NEWZNAB_ID: str = "newznab"
    NEWZNAB_NAME: str = "Newznab"
    NEWZNAB_CATEGORIES: Annotated[List[int], NoDecode] = Field(
        default_factory=lambda: [5070]
    )
    NEWZNAB_MAX_QUERY_VARIANTS: int = 12
    NEWZNAB_DEFAULT_CATEGORIES: Annotated[List[int], NoDecode] = Field(
        default_factory=lambda: [5070]
    )
    PUBLIC_BASE_URL: Optional[str] = None

    @field_validator("NEWZNAB_CATEGORIES", "NEWZNAB_DEFAULT_CATEGORIES", mode="before")
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
