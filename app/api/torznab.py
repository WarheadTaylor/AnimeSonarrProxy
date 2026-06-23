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
    cat: Optional[str] = Query(None, description="Comma-separated category IDs"),
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
    categories = parse_categories(cat)

    if t == "tvsearch":
        return await handle_tvsearch(tvdbid, season, ep, q, limit, offset, categories)
    if t == "movie":
        return await handle_movie_search(
            tmdbid, imdbid, q, year, limit, offset, categories
        )
    if t == "search":
        if not q:
            return create_empty_rss()
        return await handle_search(
            q, limit, offset, season=season, episode=ep, categories=categories
        )

    raise HTTPException(status_code=400, detail=f"Unsupported query type: {t}")


def handle_caps() -> Response:
    """Return Torznab capabilities."""
    return Response(content=torznab_renderer.caps(), media_type="application/xml")


def parse_categories(raw_categories: Optional[str]) -> Optional[list[int]]:
    """Parse Torznab cat parameter into category IDs."""
    if not raw_categories:
        return None

    categories: list[int] = []
    seen = set()
    for raw_category in raw_categories.split(","):
        raw_category = raw_category.strip()
        if not raw_category:
            continue
        try:
            category = int(raw_category)
        except ValueError:
            logger.warning("Ignoring invalid Torznab category %r", raw_category)
            continue
        if category in seen:
            continue
        seen.add(category)
        categories.append(category)

    return categories or None


async def handle_tvsearch(
    tvdb_id: Optional[int],
    season: Optional[int],
    episode: Optional[int],
    query: Optional[str],
    limit: int,
    offset: int,
    categories: Optional[list[int]] = None,
) -> Response:
    """Handle a Sonarr TV search."""
    if tvdb_id is None:
        if query:
            return await handle_search(
                query,
                limit,
                offset,
                season=season,
                episode=episode,
                categories=categories,
            )
        logger.info(
            "tvsearch test request without identifiers; searching latest selected category releases"
        )
        return await handle_search("", limit, offset, categories=categories)

    if season is None or episode is None:
        logger.warning("tvsearch for TVDB %s missing season/episode", tvdb_id)
        return create_empty_rss()

    try:
        results, attrs = await core_search_service.tv_search(
            tvdb_id, season, episode, limit + offset, categories=categories
        )
    except Exception as e:
        logger.error(
            "TV search failed for TVDB %s S%sE%s: %s",
            tvdb_id,
            season,
            episode,
            e,
            exc_info=True,
        )
        return create_empty_rss()

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
    categories: Optional[list[int]] = None,
) -> Response:
    """Handle a Radarr movie search."""
    if tmdb_id is None and imdb_id is None and not query:
        logger.info("movie test request without identifiers; searching Suzume")
        query = "Suzume"

    try:
        results, attrs = await core_search_service.movie_search(
            tmdb_id, imdb_id, query, year, limit + offset, categories=categories
        )
    except Exception as e:
        logger.error(
            "Movie search failed for TMDB %s IMDb %s query %r year %s: %s",
            tmdb_id,
            imdb_id,
            query,
            year,
            e,
            exc_info=True,
        )
        return create_empty_rss()

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
    categories: Optional[list[int]] = None,
) -> Response:
    """Handle guarded generic searches."""
    try:
        results = await core_search_service.generic_search(
            query,
            limit + offset,
            season=season,
            episode=episode,
            categories=categories,
        )
    except Exception as e:
        logger.error(
            "Generic search failed for query %r S%sE%s: %s",
            query,
            season,
            episode,
            e,
            exc_info=True,
        )
        return create_empty_rss()

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
