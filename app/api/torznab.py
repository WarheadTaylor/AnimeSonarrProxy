"""Torznab API endpoints for Sonarr integration."""
import logging
from typing import Optional
from fastapi import APIRouter, Query, HTTPException, Response
from xml.etree.ElementTree import Element, SubElement, tostring

from app.config import settings
from app.models import TorznabQuery, SearchResult
from app.services.mapping import mapping_service
from app.services.query import query_service
from app.services.prowlarr import prowlarr_client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api")
async def torznab_api(
    t: str = Query(..., description="Query type"),
    q: Optional[str] = Query(None, description="Search query"),
    tvdbid: Optional[int] = Query(None, description="TVDB ID"),
    season: Optional[int] = Query(None, description="Season number"),
    ep: Optional[int] = Query(None, description="Episode number"),
    apikey: Optional[str] = Query(None, description="API key"),
    limit: Optional[int] = Query(100, description="Result limit"),
    offset: Optional[int] = Query(0, description="Result offset"),
):
    """
    Main Torznab API endpoint.

    Handles:
    - caps: Return capabilities
    - search: Generic search
    - tvsearch: TV search with anime title mapping
    """
    # Validate API key
    if apikey != settings.API_KEY:
        logger.warning(f"Invalid API key attempt: {apikey}")
        raise HTTPException(status_code=403, detail="Invalid API key")

    # Handle capabilities request
    if t == "caps":
        return await handle_caps()

    # Handle TV search (main use case)
    elif t == "tvsearch":
        if tvdbid is None:
            # Fall back to generic search if query string is provided
            if q:
                logger.info(f"tvsearch called without tvdbid, falling back to generic search with query: {q}")
                return await handle_search(q, limit, offset)
            else:
                # Sonarr may call tvsearch without parameters during indexer testing
                # Return recent anime results to pass the test
                logger.info("tvsearch called without tvdbid or query string - returning default anime search for indexer test")
                return await handle_search("anime", limit, offset)

        if season is None or ep is None:
            logger.warning(f"tvsearch called without season/ep for TVDB {tvdbid}")
            return create_empty_rss()

        return await handle_tvsearch(tvdbid, season, ep, limit, offset)

    # Handle generic search
    elif t == "search":
        if q is None:
            logger.warning("search called without query")
            return create_empty_rss()

        return await handle_search(q, limit, offset)

    else:
        logger.warning(f"Unknown query type: {t}")
        raise HTTPException(status_code=400, detail=f"Unsupported query type: {t}")


async def handle_caps() -> Response:
    """Return Torznab capabilities."""
    caps_xml = """<?xml version="1.0" encoding="UTF-8"?>
<caps>
    <server version="1.0" title="AnimeSonarrProxy" />
    <limits max="100" default="100"/>
    <searching>
        <search available="yes" supportedParams="q"/>
        <tv-search available="yes" supportedParams="q,tvdbid,season,ep"/>
    </searching>
    <categories>
        <category id="5000" name="TV">
            <subcat id="5070" name="Anime"/>
        </category>
    </categories>
</caps>"""

    return Response(content=caps_xml, media_type="application/xml")


async def handle_tvsearch(
    tvdb_id: int,
    season: int,
    episode: int,
    limit: int,
    offset: int
) -> Response:
    """
    Handle TV search with anime title mapping.

    This is the core functionality - maps TVDB to anime titles and searches.
    """
    logger.info(f"TV search: TVDB {tvdb_id} S{season:02d}E{episode:02d}")

    # Get anime mapping
    mapping = await mapping_service.get_mapping(tvdb_id)

    if mapping is None:
        logger.warning(f"No mapping found for TVDB {tvdb_id} - returning empty results")
        # TODO: Track this for WebUI to show unmapped series
        return create_empty_rss()

    # Search using multiple queries
    try:
        results = await query_service.search_anime(mapping, season, episode)
        logger.info(f"Found {len(results)} results for TVDB {tvdb_id} S{season:02d}E{episode:02d}")

        # Apply limit and offset
        paginated_results = results[offset:offset + limit]

        # Convert to Torznab RSS
        rss_xml = create_torznab_rss(
            paginated_results,
            tvdbid=tvdb_id,
            season=season,
            episode=episode
        )

        return Response(content=rss_xml, media_type="application/xml")

    except Exception as e:
        logger.error(f"Search failed for TVDB {tvdb_id}: {e}", exc_info=True)
        return create_empty_rss()


async def handle_search(query: str, limit: int, offset: int) -> Response:
    """
    Handle generic search - pass through to Prowlarr.

    This is for non-TV searches or manual queries.
    """
    logger.info(f"Generic search: {query}")

    try:
        results = await prowlarr_client.search(query, limit=limit)
        paginated_results = results[offset:offset + limit]

        rss_xml = create_torznab_rss(paginated_results)
        return Response(content=rss_xml, media_type="application/xml")

    except Exception as e:
        logger.error(f"Generic search failed: {e}", exc_info=True)
        return create_empty_rss()


def create_torznab_rss(
    results: list[SearchResult],
    tvdbid: Optional[int] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None
) -> str:
    """Create Torznab-compliant RSS XML from search results."""
    rss = Element("rss", version="2.0")
    rss.set("xmlns:atom", "http://www.w3.org/2005/Atom")
    rss.set("xmlns:torznab", "http://torznab.com/schemas/2015/feed")

    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = "AnimeSonarrProxy"
    SubElement(channel, "description").text = "Anime Torznab Proxy for Sonarr"
    SubElement(channel, "link").text = f"{settings.HOST}:{settings.PORT}"

    for result in results:
        item = SubElement(channel, "item")

        SubElement(item, "title").text = result.title
        SubElement(item, "guid").text = result.guid
        SubElement(item, "link").text = result.link
        SubElement(item, "pubDate").text = result.pub_date.strftime("%a, %d %b %Y %H:%M:%S +0000")

        # Torznab attributes
        SubElement(item, "torznab:attr", name="size", value=str(result.size))
        SubElement(item, "torznab:attr", name="seeders", value=str(result.seeders))
        SubElement(item, "torznab:attr", name="peers", value=str(result.peers))

        # Categories - use actual categories from the result
        for category in result.categories:
            SubElement(item, "torznab:attr", name="category", value=str(category))

        # Add TVDB metadata if available
        if tvdbid:
            SubElement(item, "torznab:attr", name="tvdbid", value=str(tvdbid))
        if season is not None:
            SubElement(item, "torznab:attr", name="season", value=str(season))
        if episode is not None:
            SubElement(item, "torznab:attr", name="episode", value=str(episode))

        # Enclosure (download link)
        SubElement(item, "enclosure", url=result.link, type="application/x-bittorrent")

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(rss, encoding='unicode')


def create_empty_rss() -> Response:
    """Create empty RSS response."""
    empty_xml = create_torznab_rss([])
    return Response(content=empty_xml, media_type="application/xml")
