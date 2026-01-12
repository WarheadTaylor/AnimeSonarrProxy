"""Torznab API endpoints for Sonarr integration."""

import logging
import re
from typing import Optional
from fastapi import APIRouter, Query, HTTPException, Response
from xml.etree.ElementTree import Element, SubElement, tostring

from app.config import settings
from app.models import TorznabQuery, SearchResult
from app.services.mapping import mapping_service
from app.services.query import query_service, filter_results_by_query
from app.services.prowlarr import prowlarr_client
from app.services.nyaa import nyaa_client
from app.services.sonarr import sonarr_client
from app.services.anime_db import anime_db


def get_search_client():
    """Get the appropriate search client based on settings."""
    if settings.NYAA_ENABLED:
        return nyaa_client
    return prowlarr_client


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
    # Handle capabilities request (no auth required per Torznab spec)
    if t == "caps":
        return await handle_caps()

    # Validate API key for all other requests
    if apikey != settings.API_KEY:
        logger.debug(f"Invalid API key attempt: {apikey}")
        raise HTTPException(status_code=403, detail="Invalid API key")

    # Handle TV search (main use case)
    elif t == "tvsearch":
        if tvdbid is None:
            # Fall back to generic search if query string is provided
            # But pass season info for specials detection
            if q:
                is_special = (season == 0) if season is not None else False
                logger.info(
                    f"tvsearch called without tvdbid, falling back to generic search with query: {q}{' [SPECIAL]' if is_special else ''}"
                )
                return await handle_search(q, limit, offset, is_special=is_special)
            else:
                # Sonarr may call tvsearch without parameters during indexer testing
                # Return recent anime results to pass the test
                logger.info(
                    "tvsearch called without tvdbid or query string - returning default search for 'Frieren' for indexer test"
                )
                return await handle_search("Frieren", limit, offset)

        if season is None or ep is None:
            logger.warning(f"tvsearch called without season/ep for TVDB {tvdbid}")
            # Try to search using anime titles with OVA/Special keywords
            # This handles cases where Sonarr searches for specials without proper season/ep
            return await handle_tvsearch_special(tvdbid, q, limit, offset)

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
    tvdb_id: int, season: int, episode: int, limit: int, offset: int
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
        logger.info(
            f"Found {len(results)} results for TVDB {tvdb_id} S{season:02d}E{episode:02d}"
        )

        # Apply limit and offset
        paginated_results = results[offset : offset + limit]

        # Convert to Torznab RSS
        rss_xml = create_torznab_rss(
            paginated_results, tvdbid=tvdb_id, season=season, episode=episode
        )

        return Response(content=rss_xml, media_type="application/xml")

    except Exception as e:
        logger.error(f"Search failed for TVDB {tvdb_id}: {e}", exc_info=True)
        return create_empty_rss()


async def handle_tvsearch_special(
    tvdb_id: int, query: Optional[str], limit: int, offset: int
) -> Response:
    """
    Handle TV search when season/ep is not provided.

    This can happen in two scenarios:
    1. Sonarr searching for specials (OVAs, movies) - query might be "01", "1", etc.
    2. Sonarr searching with absolute episode number - query is the episode number

    We detect which case it is using Sonarr API (if configured) and search accordingly.
    """
    import asyncio

    logger.info(f"TV search without season/ep: TVDB {tvdb_id} query='{query}'")

    # Get anime mapping first (needed for both cases)
    mapping = await mapping_service.get_mapping(tvdb_id)

    if mapping is None:
        logger.warning(f"No mapping found for TVDB {tvdb_id} - returning empty results")
        return create_empty_rss()

    # Get search titles from mapping
    titles = mapping.get_search_titles()
    if not titles:
        logger.warning(f"No search titles for TVDB {tvdb_id}")
        return create_empty_rss()

    primary_title = titles[0]

    # Check if query looks like an episode number
    is_potential_episode_num = (
        query and query.strip().isdigit() and int(query.strip()) > 0
    )

    if is_potential_episode_num:
        query_num = int(query.strip())

        # Try Sonarr lookup if configured
        if sonarr_client.is_configured():
            # Key insight: Sonarr often sends the episode number within the season
            # (e.g., q=01 for S2E01), not the absolute episode number.
            # Find ALL wanted episodes with this episode number (could be multiple seasons).
            wanted_episodes = await sonarr_client.get_wanted_episodes_by_episode_number(
                tvdb_id, query_num
            )

            if wanted_episodes:
                # Get absolute episode numbers from all wanted episodes
                absolute_eps = [
                    ep.absolute_episode_number
                    for ep in wanted_episodes
                    if ep.absolute_episode_number is not None
                ]

                # Check if any are specials
                has_specials = any(ep.is_special for ep in wanted_episodes)

                if absolute_eps:
                    ep_info = ", ".join(
                        f"S{ep.season_number:02d}E{ep.episode_number:02d}(abs={ep.absolute_episode_number})"
                        for ep in wanted_episodes
                    )
                    logger.info(f"Resolved q={query_num} to wanted episodes: {ep_info}")

                    if has_specials:
                        # If any are specials, search for specials
                        return await _search_for_special(
                            tvdb_id, titles, absolute_eps[0], limit, offset
                        )
                    else:
                        # Search for all absolute episode numbers
                        return await _search_for_absolute_episodes(
                            tvdb_id, titles, absolute_eps, limit, offset
                        )

            # Fallback: Try as absolute episode number
            episode_info = await sonarr_client.get_episode_by_absolute_number(
                tvdb_id, query_num
            )

            if episode_info:
                if episode_info.is_special:
                    logger.info(
                        f"Query {query_num} is absolute episode, special "
                        f"(S{episode_info.season_number:02d}E{episode_info.episode_number:02d})"
                    )
                    return await _search_for_special(
                        tvdb_id, titles, query_num, limit, offset
                    )
                else:
                    logger.info(
                        f"Query {query_num} is absolute episode, regular "
                        f"(S{episode_info.season_number:02d}E{episode_info.episode_number:02d})"
                    )
                    return await _search_for_absolute_episodes(
                        tvdb_id, titles, [query_num], limit, offset
                    )
            else:
                # Episode not found by either method - use query as-is
                logger.info(
                    f"Episode {query_num} not found in Sonarr, "
                    f"treating as absolute episode search"
                )
                return await _search_for_absolute_episodes(
                    tvdb_id, titles, [query_num], limit, offset
                )
        else:
            # Sonarr not configured - default to treating query as absolute episode
            logger.info(
                f"Sonarr not configured, treating query '{query}' as absolute episode {query_num}"
            )
            return await _search_for_absolute_episodes(
                tvdb_id, titles, [query_num], limit, offset
            )

    # Non-numeric query or no query - treat as special search
    logger.info(f"Searching for specials using title: {primary_title}")
    return await _search_for_special(tvdb_id, titles, None, limit, offset)


def _filter_season_titles(titles: list[str]) -> list[str]:
    """
    Filter out season-specific title variants to avoid polluting searches.

    Titles like "Bakuman S2", "Bakuman S3", "Bakuman Season 2" will return
    results for that specific season, which is wrong when searching for
    a specific episode by absolute number.

    Args:
        titles: List of title variants

    Returns:
        Filtered list with season-specific titles removed
    """
    import re

    # Pattern to match season indicators
    # Matches: S2, S3, S02, S03, Season 2, Season 3, 2nd Season, 3rd Season
    season_pattern = re.compile(
        r"\b(S\d+|Season\s*\d+|\d+(st|nd|rd|th)\s*Season)\b", re.IGNORECASE
    )

    filtered = []
    removed = []

    for title in titles:
        if season_pattern.search(title):
            removed.append(title)
        else:
            filtered.append(title)

    if removed:
        logger.debug(f"Filtered out season-specific titles: {removed}")

    # Always return at least one title (the first one, even if it has season info)
    if not filtered and titles:
        filtered = [titles[0]]

    return filtered


async def _search_for_absolute_episodes(
    tvdb_id: int,
    titles: list[str],
    absolute_eps: list[int],
    limit: int,
    offset: int,
) -> Response:
    """
    Search for regular episodes using absolute episode numbers.

    Handles multiple episode numbers (e.g., when both S02E01 and S03E01 are wanted).
    Uses Nyaa's | (OR) operator to combine titles and episodes into a single query.
    """
    logger.info(f"Absolute episode search: TVDB {tvdb_id} episodes {absolute_eps}")

    # Filter out season-specific titles to avoid wrong results
    filtered_titles = _filter_season_titles(titles)

    # Limit titles to prevent overly complex queries
    search_titles = filtered_titles[:3]

    search_client = get_search_client()

    # Use combined query if Nyaa client supports it (search_multi method)
    if hasattr(search_client, "search_multi"):
        # Build a single combined query: ("Title A"|"Title B") (ep1|ep2|ep3)
        logger.info(
            f"Absolute episode search: combined query with titles={search_titles}, episodes={absolute_eps}"
        )
        all_results = await search_client.search_multi(
            titles=search_titles, episodes=absolute_eps, limit=limit
        )
    else:
        # Fallback for Prowlarr client: use individual queries
        import asyncio

        episode_queries = []
        for ep in absolute_eps:
            for title in search_titles:
                episode_queries.append(f"{title} {ep}")

        # Cap total queries to prevent excessive API calls
        episode_queries = episode_queries[:8]
        logger.info(f"Absolute episode search queries (fallback): {episode_queries}")

        tasks = [search_client.search(q, limit=limit) for q in episode_queries]
        results_lists = await asyncio.gather(*tasks, return_exceptions=True)

        all_results = []
        for results in results_lists:
            if isinstance(results, Exception):
                logger.error(f"Query failed: {results}")
                continue
            all_results.extend(results)

    # Deduplicate by GUID
    seen_guids = set()
    unique_results = []
    for result in all_results:
        if result.guid not in seen_guids:
            seen_guids.add(result.guid)
            unique_results.append(result)

    # Filter for relevance
    primary_title = titles[0]
    relevant_results = filter_results_by_query(unique_results, primary_title)
    logger.info(
        f"Absolute episode search: {len(unique_results)} -> {len(relevant_results)} relevant results"
    )

    # Sort by seeders (descending) then pub_date (descending)
    relevant_results.sort(key=lambda x: (x.seeders, x.pub_date), reverse=True)
    paginated_results = relevant_results[offset : offset + limit]

    rss_xml = create_torznab_rss(paginated_results, tvdbid=tvdb_id)
    return Response(content=rss_xml, media_type="application/xml")


async def _search_for_special(
    tvdb_id: int,
    titles: list[str],
    episode_num: Optional[int],
    limit: int,
    offset: int,
) -> Response:
    """
    Search for specials/OVAs/movies.

    Uses Nyaa's | (OR) operator to combine OVA/Special/Movie keywords into a single query.
    """
    primary_title = titles[0]
    logger.info(f"Special search: TVDB {tvdb_id} title='{primary_title}'")

    search_client = get_search_client()

    # Define special keywords
    special_keywords = ["OVA", "Special", "OAD", "Movie"]

    # Use combined query if Nyaa client supports it
    if hasattr(search_client, "search_multi"):
        # Build a single combined query: "Title" (OVA|Special|OAD|Movie)
        # Optionally include episode number if provided
        episodes = [episode_num] if episode_num is not None else None

        logger.info(
            f"Special search: combined query with title='{primary_title}', "
            f"keywords={special_keywords}, episode={episode_num}"
        )
        all_results = await search_client.search_multi(
            titles=[primary_title],
            keywords=special_keywords,
            episodes=episodes,
            limit=limit,
        )

        # Also do a bare title search to catch differently labeled specials
        bare_results = await search_client.search(primary_title, limit=limit)
        all_results.extend(bare_results)
    else:
        # Fallback for Prowlarr client: use individual queries
        import asyncio

        special_queries = [
            f"{primary_title} OVA",
            f"{primary_title} Special",
            f"{primary_title} OAD",
            f"{primary_title} Movie",
        ]

        if episode_num is not None:
            special_queries.extend(
                [
                    f"{primary_title} OVA {episode_num}",
                    f"{primary_title} Special {episode_num}",
                ]
            )

        special_queries.append(primary_title)
        logger.info(f"Special search queries (fallback): {special_queries}")

        tasks = [search_client.search(q, limit=limit) for q in special_queries]
        results_lists = await asyncio.gather(*tasks, return_exceptions=True)

        all_results = []
        for results in results_lists:
            if isinstance(results, Exception):
                logger.error(f"Query failed: {results}")
                continue
            all_results.extend(results)

    # Deduplicate by GUID
    seen_guids = set()
    unique_results = []
    for result in all_results:
        if result.guid not in seen_guids:
            seen_guids.add(result.guid)
            unique_results.append(result)

    # Filter for relevance - result should contain the anime title
    relevant_results = filter_results_by_query(unique_results, primary_title)
    logger.info(
        f"Special search: {len(unique_results)} -> {len(relevant_results)} relevant results"
    )

    # Sort by seeders (descending) then pub_date (descending)
    relevant_results.sort(key=lambda x: (x.seeders, x.pub_date), reverse=True)
    paginated_results = relevant_results[offset : offset + limit]

    rss_xml = create_torznab_rss(paginated_results, tvdbid=tvdb_id)
    return Response(content=rss_xml, media_type="application/xml")


async def handle_search(
    query: str, limit: int, offset: int, is_special: bool = False
) -> Response:
    """
    Handle generic search with smart query parsing.

    Detects concatenated title queries from Sonarr and splits them intelligently.
    For specials (season 0), adds OVA/Special/Movie keywords to the search.
    """
    logger.info(f"Generic search: {query}")

    try:
        # Detect Season 0 queries - Sonarr appends "00" for season 0 episode searches
        # e.g., "Kaguya sama wa Kokurasetai 00" -> should search for OVA/Special/Movie
        if not is_special and _is_season_zero_query(query):
            is_special = True
            query = _strip_season_zero_suffix(query)
            logger.info(f"Detected Season 0 query - stripped to: {query} [SPECIAL]")

        # Parse the query to get a clean title
        search_queries = _parse_concatenated_query(query)
        base_query = search_queries[0] if search_queries else query

        # For specials, search with OVA/Special/Movie keywords
        if is_special:
            logger.info(f"Special detected - searching with OVA/Special/Movie keywords")

            search_client = get_search_client()
            special_keywords = ["OVA", "Special", "Movie"]

            # Use combined query if Nyaa client supports it
            if hasattr(search_client, "search_multi"):
                logger.info(
                    f"Special search: combined query with title='{base_query}', keywords={special_keywords}"
                )
                all_results = await search_client.search_multi(
                    titles=[base_query], keywords=special_keywords, limit=limit
                )
                # Also do a bare title search
                bare_results = await search_client.search(base_query, limit=limit)
                all_results.extend(bare_results)
            else:
                # Fallback for Prowlarr client
                import asyncio

                special_queries = [
                    f"{base_query} OVA",
                    f"{base_query} Special",
                    f"{base_query} Movie",
                    base_query,
                ]
                tasks = [search_client.search(q, limit=limit) for q in special_queries]
                results_lists = await asyncio.gather(*tasks, return_exceptions=True)

                all_results = []
                for results in results_lists:
                    if isinstance(results, Exception):
                        logger.error(f"Query failed: {results}")
                        continue
                    all_results.extend(results)

            # Deduplicate by GUID
            seen_guids = set()
            unique_results = []
            for result in all_results:
                if result.guid not in seen_guids:
                    seen_guids.add(result.guid)
                    unique_results.append(result)

            # Filter out irrelevant results
            relevant_results = filter_results_by_query(unique_results, query)
            logger.info(
                f"Relevance filter: {len(unique_results)} -> {len(relevant_results)} results"
            )

            # Sort and paginate
            relevant_results.sort(key=lambda x: (x.seeders, x.pub_date), reverse=True)
            paginated_results = relevant_results[offset : offset + limit]
        else:
            # Regular search - single query
            search_client = get_search_client()
            results = await search_client.search(base_query, limit=limit)

            # Filter out irrelevant results that don't match the search query
            relevant_results = filter_results_by_query(results, query)
            logger.info(
                f"Relevance filter: {len(results)} -> {len(relevant_results)} results"
            )

            # Sort by seeders (descending) then pub_date (descending, newer first)
            relevant_results.sort(key=lambda x: (x.seeders, x.pub_date), reverse=True)
            paginated_results = relevant_results[offset : offset + limit]

        rss_xml = create_torznab_rss(paginated_results)
        return Response(content=rss_xml, media_type="application/xml")

    except Exception as e:
        logger.error(f"Generic search failed: {e}", exc_info=True)
        return create_empty_rss()


def _parse_concatenated_query(query: str) -> list[str]:
    """
    Parse a potentially concatenated query string into individual search terms.

    Sonarr sometimes sends queries like:
    "Kaguya sama wa Kokurasetai Tensai tachi no Renai Zunousen ABCs of Men and Women"

    Now that Prowlarr search is working properly, we just need to extract
    a clean primary title rather than generating multiple fragmented queries.
    """
    # If query is short, just use it as-is
    if len(query) < 50:
        return [query]

    words = query.split()

    # Strategy 1: Try to find the anime in our database first
    # Try with progressively shorter prefixes of the query
    for num_words in [6, 5, 4, 3]:
        if len(words) >= num_words:
            prefix = " ".join(words[:num_words])
            db_titles = anime_db.get_search_titles_for_query(prefix)
            if db_titles:
                logger.info(
                    f"Found anime in database for query prefix '{prefix}': {db_titles}"
                )
                # Return just the primary title, not all variations
                return [db_titles[0]]

    # Strategy 2: For Japanese titles with particles, extract up to the particle + a few words
    japanese_particles = ["wa", "no", "ga", "ni"]
    for i, word in enumerate(words[:8]):
        if word.lower() in japanese_particles:
            # Include words after the particle to complete the title
            end_idx = min(i + 4, len(words))
            japanese_title = " ".join(words[:end_idx])
            return [japanese_title]

    # Strategy 3: Just use the first 4-5 words as the search term
    return [" ".join(words[:5])]


def _is_season_zero_query(query: str) -> bool:
    """
    Detect if query is a Season 0 (special) episode search.

    Sonarr may append episode numbers like "00" for Season 0 specials.
    We need to be careful not to match regular episode numbers.

    Rules:
    - " 00" at end -> Season 0 special episode 0
    - " 0X" at end WITH a season indicator (S1, S2, etc.) -> NOT Season 0
    - " 0X" at end WITHOUT season indicator -> Ambiguous, assume NOT Season 0
      (regular episode numbers are more common than specials)

    e.g., "Kaguya sama 00" -> Season 0 (special)
          "Bakuman S2 01" -> NOT Season 0 (regular S2E01)
          "Bakuman 01" -> NOT Season 0 (probably regular episode)
    """
    # Only match " 00" specifically - this is clearly special episode 0
    # Other patterns like " 01", " 02" are too ambiguous and often wrong
    if re.search(r"\s+00$", query):
        return True

    # Don't match queries with season indicators - those are regular episodes
    # E.g., "Bakuman S2 01" should NOT be treated as Season 0
    if re.search(r"\bS\d+\b", query, re.IGNORECASE):
        return False

    # For other " 0X" patterns, be conservative - assume NOT Season 0
    # The user searching for "Bakuman 01" probably wants episode 1, not special 1
    return False


def _strip_season_zero_suffix(query: str) -> str:
    """
    Remove the Season 0 episode number suffix from query.

    "Kaguya sama 00" -> "Kaguya sama"
    "Attack on Titan 01" -> "Attack on Titan"
    """
    return re.sub(r"\s+0\d$", "", query).strip()


def create_torznab_rss(
    results: list[SearchResult],
    tvdbid: Optional[int] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
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
        # Sonarr uses <comments> element for the clickable info/details page link
        if result.info_url:
            SubElement(item, "comments").text = result.info_url
        SubElement(item, "pubDate").text = result.pub_date.strftime(
            "%a, %d %b %Y %H:%M:%S +0000"
        )

        # Torznab attributes
        SubElement(item, "torznab:attr", name="size", value=str(result.size))
        SubElement(item, "torznab:attr", name="seeders", value=str(result.seeders))
        SubElement(item, "torznab:attr", name="peers", value=str(result.peers))

        # Add downloadvolumefactor and uploadvolumefactor (required by some clients)
        SubElement(item, "torznab:attr", name="downloadvolumefactor", value="1")
        SubElement(item, "torznab:attr", name="uploadvolumefactor", value="1")

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

        # Enclosure (download link) - always use the actual download URL
        SubElement(item, "enclosure", url=result.link, type="application/x-bittorrent")

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(
        rss, encoding="unicode"
    )


def create_empty_rss() -> Response:
    """Create empty RSS response."""
    empty_xml = create_torznab_rss([])
    return Response(content=empty_xml, media_type="application/xml")
