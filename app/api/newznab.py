"""Newznab API endpoints backed by configurable upstream providers."""

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.api.torznab import parse_categories
from app.config import settings
from app.models import SearchResult
from app.services.newznab import configured_newznab_providers, get_newznab_provider
from app.services.newznab import newznab_client
from app.services.newznab_core import newznab_core_service
from app.services.newznab_renderer import newznab_renderer

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/newznab")
async def newznab_api(
    request: Request,
    t: str = Query(..., description="Query type"),
    q: Optional[str] = Query(None, description="Search query"),
    tvdbid: Optional[int] = Query(None, description="TVDB ID"),
    season: Optional[int] = Query(None, description="Season number"),
    ep: Optional[int] = Query(None, description="Episode number"),
    apikey: Optional[str] = Query(None, description="API key"),
    cat: Optional[str] = Query(None, description="Comma-separated category IDs"),
    limit: int = Query(100, description="Result limit"),
    offset: int = Query(0, description="Result offset"),
    id: Optional[str] = Query(None, description="Upstream Newznab item ID"),
    provider: Optional[str] = Query(None, description="Upstream provider ID"),
) -> Response:
    """Handle Newznab caps, TV, generic search, and NZB proxy requests."""
    if t == "caps":
        return Response(content=newznab_renderer.caps(), media_type="application/xml")

    if apikey != settings.API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")

    if t == "get":
        return await handle_get(provider, id)

    if not configured_newznab_providers():
        raise HTTPException(status_code=503, detail="No Newznab providers configured")

    limit = max(0, min(limit, settings.MAX_RESULTS_PER_QUERY))
    offset = max(0, offset)
    categories = parse_categories(cat)

    if t == "tvsearch":
        return await handle_tvsearch(
            request, tvdbid, season, ep, q, limit, offset, categories
        )
    if t == "search":
        return await handle_search(
            request,
            q or "",
            limit,
            offset,
            season=season,
            episode=ep,
            categories=categories,
        )

    raise HTTPException(status_code=400, detail=f"Unsupported query type: {t}")


async def handle_tvsearch(
    request: Request,
    tvdb_id: Optional[int],
    season: Optional[int],
    episode: Optional[int],
    query: Optional[str],
    limit: int,
    offset: int,
    categories: Optional[list[int]],
) -> Response:
    """Handle a Sonarr Newznab TV search."""
    if tvdb_id is None:
        return await handle_search(
            request,
            query or "",
            limit,
            offset,
            season=season,
            episode=episode,
            categories=categories,
        )

    if season is None or episode is None:
        logger.warning("Newznab tvsearch for TVDB %s missing season/episode", tvdb_id)
        return create_empty_rss(request, offset)

    try:
        results = await newznab_core_service.tv_search(
            tvdb_id, season, episode, limit + offset, categories=categories
        )
    except Exception as exc:
        logger.error(
            "Newznab TV search failed for TVDB %s S%sE%s: %s",
            tvdb_id,
            season,
            episode,
            exc,
            exc_info=True,
        )
        return create_empty_rss(request, offset)

    return render_results(request, results, limit, offset)


async def handle_search(
    request: Request,
    query: str,
    limit: int,
    offset: int,
    *,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    categories: Optional[list[int]] = None,
) -> Response:
    """Handle a generic Newznab search."""
    try:
        results = await newznab_core_service.generic_search(
            query,
            limit + offset,
            season=season,
            episode=episode,
            categories=categories,
        )
    except Exception as exc:
        logger.error(
            "Newznab generic search failed for query %r S%sE%s: %s",
            query,
            season,
            episode,
            exc,
            exc_info=True,
        )
        return create_empty_rss(request, offset)

    return render_results(request, results, limit, offset)


async def handle_get(
    provider_id: Optional[str], provider_guid: Optional[str]
) -> Response:
    """Proxy an NZB download from the selected upstream provider."""
    if not provider_id or not provider_guid:
        raise HTTPException(status_code=400, detail="Missing provider or id")

    provider = get_newznab_provider(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Unknown Newznab provider")

    try:
        upstream = await newznab_client.get_nzb(provider, provider_guid)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="NZB not found") from exc
        logger.warning("Newznab provider %s get failed: %s", provider.id, exc)
        raise HTTPException(status_code=502, detail="Upstream NZB fetch failed") from exc
    except httpx.HTTPError as exc:
        logger.warning("Newznab provider %s get failed: %s", provider.id, exc)
        raise HTTPException(status_code=502, detail="Upstream NZB fetch failed") from exc

    headers = {}
    if upstream.headers.get("content-disposition"):
        headers["Content-Disposition"] = upstream.headers["content-disposition"]
    return Response(
        content=upstream.content,
        media_type=upstream.headers.get("content-type", "application/x-nzb"),
        headers=headers,
    )


def render_results(
    request: Request, results: list[SearchResult], limit: int, offset: int
) -> Response:
    """Render paged Newznab RSS results."""
    paged = results[offset : offset + limit]
    return Response(
        content=newznab_renderer.render(
            paged,
            offset=offset,
            total=len(results),
            request_base_url=str(request.base_url),
        ),
        media_type="application/xml",
    )


def create_empty_rss(request: Request, offset: int = 0) -> Response:
    """Create an empty Newznab RSS response."""
    return Response(
        content=newznab_renderer.render(
            [],
            offset=offset,
            total=0,
            request_base_url=str(request.base_url),
        ),
        media_type="application/xml",
    )
