"""Main FastAPI application for AnimeSonarrProxy."""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api import torznab, webui
from app.services.anime_db import anime_db
from app.services.mapping import mapping_service
from app.services.sonarr import sonarr_client
from app.services import episode

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

    # Initialize anime-offline-database
    logger.info("Initializing anime-offline-database...")
    await anime_db.initialize()

    # Initialize mapping service
    logger.info("Initializing mapping service...")
    await mapping_service.initialize()

    # Initialize episode translator
    logger.info("Initializing episode translator...")
    episode.episode_translator = episode.EpisodeTranslator(mapping_service)

    # Initialize Sonarr client (optional - for episode metadata lookup)
    if settings.SONARR_URL and settings.SONARR_API_KEY:
        logger.info("Initializing Sonarr client...")
        sonarr_client.configure(settings.SONARR_URL, settings.SONARR_API_KEY)
    else:
        logger.info(
            "Sonarr integration not configured (SONARR_URL/SONARR_API_KEY not set)"
        )

    logger.info(
        f"AnimeSonarrProxy started successfully on {settings.HOST}:{settings.PORT}"
    )
    logger.info(f"Torznab API: http://{settings.HOST}:{settings.PORT}/api")
    logger.info(f"WebUI: http://{settings.HOST}:{settings.PORT}/")

    yield

    # Shutdown
    logger.info("Shutting down AnimeSonarrProxy...")


# Create FastAPI app
app = FastAPI(
    title="AnimeSonarrProxy",
    description="Torznab-compatible proxy for anime title mapping between Sonarr and Prowlarr",
    version="1.0.0",
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
app.include_router(webui.router, tags=["WebUI"])

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level=settings.LOG_LEVEL.lower(),
    )
