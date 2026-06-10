"""Main FastAPI application for AnimeSonarrProxy."""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api import torznab
from app.services.anime_db import anime_db
from app.services.sonarr import sonarr_client
from app.services.radarr import radarr_client

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info("Starting AnimeSonarrProxy...")
    logger.info(
        f"Torznab default language metadata: {settings.TORZNAB_DEFAULT_LANGUAGE or 'disabled'}"
    )
    logger.info(
        "Nyaa search defaults: url=%s category=%s no_remakes=%s trusted_only=%s",
        settings.NYAA_URL,
        settings.NYAA_CATEGORY,
        settings.NYAA_NO_REMAKES,
        settings.NYAA_TRUSTED_ONLY,
    )

    # Initialize anime-offline-database
    logger.info("Initializing anime-offline-database...")
    await anime_db.initialize()

    # Initialize Sonarr client (optional - for episode metadata lookup)
    if settings.SONARR_URL and settings.SONARR_API_KEY:
        logger.info("Initializing Sonarr client...")
        sonarr_client.configure(settings.SONARR_URL, settings.SONARR_API_KEY)
    else:
        logger.info(
            "Sonarr integration not configured (SONARR_URL/SONARR_API_KEY not set)"
        )

    # Initialize Radarr client (optional - for movie metadata lookup)
    if settings.RADARR_URL and settings.RADARR_API_KEY:
        logger.info("Initializing Radarr client...")
        radarr_client.configure(settings.RADARR_URL, settings.RADARR_API_KEY)
    else:
        logger.info(
            "Radarr integration not configured (RADARR_URL/RADARR_API_KEY not set)"
        )

    logger.info(
        f"AnimeSonarrProxy started successfully on {settings.HOST}:{settings.PORT}"
    )
    logger.info(f"Torznab API: http://{settings.HOST}:{settings.PORT}/api")

    yield

    # Shutdown
    logger.info("Shutting down AnimeSonarrProxy...")


# Create FastAPI app
app = FastAPI(
    title="AnimeSonarrProxy",
    description="Torznab-compatible proxy for anime title normalization from Nyaa",
    version="2.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(torznab.router, tags=["Torznab"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level=settings.LOG_LEVEL.lower(),
    )
