"""Torznab API endpoints backed by direct Nyaa search."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response

from app.config import settings
from app.models import SearchResult
from app.services.core import core_search_service
from app.services.torznab_renderer import torznab_renderer

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api")
async def torznab_api(
    t: str = Query(..., description="Query type"),
    q: Optional[str] = Query(None, description="Search query"),
    tvdbid: Optional[int] = Query(None, description="TVDB ID"),
    season: Optional[int] = Query(None, description="Season number"),
    ep: Optional[int] = Query(None, description="Episode number"),
    tmdbid: Optional[int] = Query(None, description="TMDB ID"),
    imdbid: Optional[str] = Query(None, description="IMDb ID"),
    year: Optional[int] = Query(None, description="Release year"),
    apikey: Optional[str] = Query(None, description="API key"),
    limit: int = Query(100, description="Result limit"),
    offset: int = Query(0, description="Result offset"),
) -> Response:
    """Handle Torznab caps, TV, movie, and guarded generic searches."""
    if t == "caps":
        return handle_caps()

    if apikey != settings.API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")

    limit = max(0, min(limit, settings.MAX_RESULTS_PER_QUERY))
    offset = max(0, offset)

    if t == "tvsearch":
        return await handle_tvsearch(tvdbid, season, ep, q, limit, offset)
    if t == "movie":
        return await handle_movie_search(tmdbid, imdbid, q, year, limit, offset)
    if t == "search":
        if not q:
            return create_empty_rss()
        return await handle_search(q, limit, offset, season=season, episode=ep)

    raise HTTPException(status_code=400, detail=f"Unsupported query type: {t}")


def handle_caps() -> Response:
    """Return Torznab capabilities."""
    return Response(content=torznab_renderer.caps(), media_type="application/xml")


async def handle_tvsearch(
    tvdb_id: Optional[int],
    season: Optional[int],
    episode: Optional[int],
    query: Optional[str],
    limit: int,
    offset: int,
) -> Response:
    """Handle a Sonarr TV search."""
    if tvdb_id is None:
        if query:
            return await handle_search(
                query, limit, offset, season=season, episode=episode
            )
        logger.info("tvsearch test request without identifiers; searching Frieren")
        return await handle_search("Frieren", limit, offset)

    if season is None or episode is None:
        logger.warning("tvsearch for TVDB %s missing season/episode", tvdb_id)
        return create_empty_rss()

    results, attrs = await core_search_service.tv_search(
        tvdb_id, season, episode, limit + offset
    )
    paged = results[offset : offset + limit]
    return Response(
        content=torznab_renderer.render(
            paged,
            tvdb_id=attrs.get("tvdb_id") if attrs else tvdb_id,
            season=attrs.get("season") if attrs else season,
            episode=attrs.get("episode") if attrs else episode,
        ),
        media_type="application/xml",
    )


async def handle_movie_search(
    tmdb_id: Optional[int],
    imdb_id: Optional[str],
    query: Optional[str],
    year: Optional[int],
    limit: int,
    offset: int,
) -> Response:
    """Handle a Radarr movie search."""
    if tmdb_id is None and imdb_id is None and not query:
        logger.info("movie test request without identifiers; searching Suzume")
        query = "Suzume"

    results, attrs = await core_search_service.movie_search(
        tmdb_id, imdb_id, query, year, limit + offset
    )
    paged = results[offset : offset + limit]
    return Response(
        content=torznab_renderer.render(
            paged,
            tmdb_id=attrs.get("tmdb_id") if attrs else tmdb_id,
            imdb_id=attrs.get("imdb_id") if attrs else imdb_id,
            year=attrs.get("year") if attrs else year,
        ),
        media_type="application/xml",
    )


async def handle_search(
    query: str,
    limit: int,
    offset: int,
    season: Optional[int] = None,
    episode: Optional[int] = None,
) -> Response:
    """Handle guarded generic searches."""
    results = await core_search_service.generic_search(
        query, limit + offset, season=season, episode=episode
    )
    paged = results[offset : offset + limit]
    return Response(
        content=torznab_renderer.render(paged),
        media_type="application/xml",
    )


def create_torznab_rss(
    results: list[SearchResult],
    tvdbid: Optional[int] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
) -> str:
    """Compatibility wrapper for tests and simple RSS rendering."""
    return torznab_renderer.render(
        results,
        tvdb_id=tvdbid,
        season=season,
        episode=episode,
    )


def create_empty_rss() -> Response:
    """Create an empty Torznab RSS response."""
    return Response(content=torznab_renderer.render([]), media_type="application/xml")
