"""Torznab XML rendering for manager responses."""

from typing import Optional
from xml.etree.ElementTree import Element, SubElement, tostring, register_namespace

from app.config import settings
from app.models import SearchResult

TORZNAB_NS = "http://torznab.com/schemas/2015/feed"
ATOM_NS = "http://www.w3.org/2005/Atom"

register_namespace("torznab", TORZNAB_NS)
register_namespace("atom", ATOM_NS)


class TorznabRenderer:
    """Renders SearchResult objects as Torznab-compatible RSS XML."""

    def render(
        self,
        results: list[SearchResult],
        *,
        tvdb_id: Optional[int] = None,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        tmdb_id: Optional[int] = None,
        imdb_id: Optional[str] = None,
        year: Optional[int] = None,
    ) -> str:
        """Render a Torznab RSS response."""
        rss = Element("rss", version="2.0")
        channel = SubElement(rss, "channel")
        SubElement(channel, "title").text = "AnimeSonarrProxy"
        SubElement(channel, "description").text = "Anime Nyaa Torznab proxy"
        SubElement(channel, "link").text = f"http://{settings.HOST}:{settings.PORT}/api"

        for result in results:
            self._item(
                channel,
                result,
                tvdb_id=tvdb_id,
                season=season,
                episode=episode,
                tmdb_id=tmdb_id,
                imdb_id=imdb_id,
                year=year,
            )

        return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(
            rss, encoding="unicode"
        )

    def caps(self) -> str:
        """Render Torznab capabilities."""
        return """<?xml version="1.0" encoding="UTF-8"?>
<caps>
    <server version="1.0" title="AnimeSonarrProxy" />
    <limits max="100" default="100"/>
    <searching>
        <search available="yes" supportedParams="q"/>
        <tv-search available="yes" supportedParams="q,tvdbid,season,ep"/>
        <movie-search available="yes" supportedParams="q,tmdbid,imdbid,year"/>
    </searching>
    <categories>
        <category id="2000" name="Movies">
            <subcat id="2060" name="Movies/Anime"/>
        </category>
        <category id="5000" name="TV">
            <subcat id="5070" name="Anime"/>
        </category>
    </categories>
</caps>"""

    def _item(
        self,
        channel: Element,
        result: SearchResult,
        *,
        tvdb_id: Optional[int],
        season: Optional[int],
        episode: Optional[int],
        tmdb_id: Optional[int],
        imdb_id: Optional[str],
        year: Optional[int],
    ) -> None:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = result.title
        SubElement(item, "guid").text = result.guid
        SubElement(item, "link").text = result.link
        if result.info_url:
            SubElement(item, "comments").text = result.info_url
        SubElement(item, "pubDate").text = result.pub_date.strftime(
            "%a, %d %b %Y %H:%M:%S +0000"
        )
        SubElement(
            item,
            "enclosure",
            url=result.link,
            type="application/x-bittorrent",
            length=str(result.size),
        )

        self._attr(item, "size", str(result.size))
        self._attr(item, "seeders", str(result.seeders))
        self._attr(item, "peers", str(result.peers))
        self._attr(item, "downloadvolumefactor", "1")
        self._attr(item, "uploadvolumefactor", "1")
        if result.info_hash:
            self._attr(item, "infohash", result.info_hash)

        for category in result.categories:
            self._attr(item, "category", str(category))
        if tvdb_id:
            self._attr(item, "tvdbid", str(tvdb_id))
        if season is not None:
            self._attr(item, "season", str(season))
        if episode is not None:
            self._attr(item, "episode", str(episode))
        if tmdb_id:
            self._attr(item, "tmdbid", str(tmdb_id))
        if imdb_id:
            self._attr(item, "imdbid", imdb_id)
        if year:
            self._attr(item, "year", str(year))
        if settings.TORZNAB_DEFAULT_LANGUAGE:
            self._attr(item, "language", settings.TORZNAB_DEFAULT_LANGUAGE)

    def _attr(self, item: Element, name: str, value: str) -> None:
        SubElement(item, f"{{{TORZNAB_NS}}}attr", name=name, value=value)


torznab_renderer = TorznabRenderer()
