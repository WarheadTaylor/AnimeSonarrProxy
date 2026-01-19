"""WebUI API endpoints for managing anime mappings."""

import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pathlib import Path

from app.models import AnimeMapping, MappingOverride, MovieMapping, MovieMappingOverride
from app.services.mapping import mapping_service
from app.services.movie_mapping import movie_mapping_service
from app.services.anilist import anilist_client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index():
    """Serve the WebUI HTML page."""
    html_path = Path(__file__).parent.parent / "static" / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    else:
        return HTMLResponse("<h1>AnimeSonarrProxy WebUI</h1><p>UI file not found</p>")


@router.get("/api/mappings")
async def get_mappings() -> List[AnimeMapping]:
    """Get all cached anime mappings."""
    mappings = await mapping_service.get_all_mappings()
    return mappings


@router.get("/api/mappings/{tvdb_id}")
async def get_mapping(tvdb_id: int) -> Optional[AnimeMapping]:
    """Get a specific mapping by TVDB ID."""
    mapping = await mapping_service.get_mapping(tvdb_id)
    if mapping is None:
        raise HTTPException(
            status_code=404, detail=f"No mapping found for TVDB {tvdb_id}"
        )
    return mapping


@router.post("/api/mappings/override")
async def create_override(override: MappingOverride):
    """Create or update a user override for a TVDB ID."""
    logger.info(f"Creating override for TVDB {override.tvdb_id}")

    # Validate AniList ID if provided
    if override.anilist_id:
        anilist_data = await anilist_client.get_by_anilist_id(override.anilist_id)
        if not anilist_data:
            raise HTTPException(
                status_code=400, detail=f"Invalid AniList ID: {override.anilist_id}"
            )

    await mapping_service.save_override(override)
    return {
        "status": "success",
        "message": f"Override saved for TVDB {override.tvdb_id}",
    }


@router.get("/api/mappings/override/{tvdb_id}")
async def get_override(tvdb_id: int) -> MappingOverride:
    """Get a specific override by TVDB ID for editing."""
    if tvdb_id in mapping_service.overrides:
        return mapping_service.overrides[tvdb_id]
    raise HTTPException(status_code=404, detail=f"No override found for TVDB {tvdb_id}")


@router.delete("/api/mappings/override/{tvdb_id}")
async def delete_override(tvdb_id: int):
    """Delete a user override."""
    if tvdb_id in mapping_service.overrides:
        del mapping_service.overrides[tvdb_id]
        # Re-save overrides file
        await mapping_service.save_override(
            MappingOverride(tvdb_id=0)
        )  # Dummy to trigger save
        if 0 in mapping_service.overrides:
            del mapping_service.overrides[0]
        return {"status": "success", "message": f"Override deleted for TVDB {tvdb_id}"}
    else:
        raise HTTPException(
            status_code=404, detail=f"No override found for TVDB {tvdb_id}"
        )


@router.get("/api/search/anilist")
async def search_anilist(query: str):
    """Search AniList for anime by title."""
    # This would require a search query for AniList
    # For now, return placeholder
    logger.info(f"AniList search: {query}")
    return {
        "results": [],
        "message": "AniList search not yet implemented - use AniList ID directly",
    }


@router.get("/api/stats")
async def get_stats():
    """Get proxy statistics."""
    return {
        "total_mappings": len(mapping_service.cache),
        "total_overrides": len(mapping_service.overrides),
        "total_movie_mappings": len(movie_mapping_service.cache),
        "total_movie_overrides": len(movie_mapping_service.overrides),
        "anime_db_last_update": anime_db.last_update.isoformat()
        if anime_db.last_update
        else None,
    }


# ==================== Movie Mapping Endpoints ====================


@router.get("/api/movies/mappings")
async def get_movie_mappings() -> List[MovieMapping]:
    """Get all cached movie mappings."""
    mappings = await movie_mapping_service.get_all_mappings()
    return mappings


@router.get("/api/movies/mappings/{tmdb_id}")
async def get_movie_mapping(tmdb_id: int) -> Optional[MovieMapping]:
    """Get a specific movie mapping by TMDB ID."""
    mapping = await movie_mapping_service.get_mapping(tmdb_id)
    if mapping is None:
        raise HTTPException(
            status_code=404, detail=f"No movie mapping found for TMDB {tmdb_id}"
        )
    return mapping


@router.post("/api/movies/mappings/override")
async def create_movie_override(override: MovieMappingOverride):
    """Create or update a user override for a TMDB ID."""
    logger.info(f"Creating movie override for TMDB {override.tmdb_id}")

    # Validate AniList ID if provided
    if override.anilist_id:
        anilist_data = await anilist_client.get_by_anilist_id(override.anilist_id)
        if not anilist_data:
            raise HTTPException(
                status_code=400, detail=f"Invalid AniList ID: {override.anilist_id}"
            )

    await movie_mapping_service.save_override(override)
    return {
        "status": "success",
        "message": f"Movie override saved for TMDB {override.tmdb_id}",
    }


@router.get("/api/movies/mappings/override/{tmdb_id}")
async def get_movie_override(tmdb_id: int) -> MovieMappingOverride:
    """Get a specific movie override by TMDB ID for editing."""
    if tmdb_id in movie_mapping_service.overrides:
        return movie_mapping_service.overrides[tmdb_id]
    raise HTTPException(
        status_code=404, detail=f"No movie override found for TMDB {tmdb_id}"
    )


@router.delete("/api/movies/mappings/override/{tmdb_id}")
async def delete_movie_override(tmdb_id: int):
    """Delete a movie user override."""
    success = await movie_mapping_service.delete_override(tmdb_id)
    if success:
        return {
            "status": "success",
            "message": f"Movie override deleted for TMDB {tmdb_id}",
        }
    else:
        raise HTTPException(
            status_code=404, detail=f"No movie override found for TMDB {tmdb_id}"
        )


@router.get("/api/movies/overrides")
async def get_all_movie_overrides() -> List[MovieMappingOverride]:
    """Get all movie user overrides."""
    return await movie_mapping_service.get_all_overrides()


# Import anime_db for stats
from app.services.anime_db import anime_db
