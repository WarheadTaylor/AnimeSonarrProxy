"""Newznab XML rendering for upstream Usenet provider responses."""

from typing import Optional
from urllib.parse import urlencode
from xml.etree.ElementTree import Element, SubElement, register_namespace, tostring

from app.config import settings
from app.models import SearchResult
from app.services.newznab import NEWZNAB_NS

register_namespace("newznab", NEWZNAB_NS)


class NewznabRenderer:
    """Renders SearchResult objects as Newznab-compatible RSS XML."""

    def caps(self) -> str:
        """Render Newznab capabilities for Sonarr."""
        max_results = settings.MAX_RESULTS_PER_QUERY
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<caps>
    <server version="1.0" title="AnimeSonarrProxy Newznab" />
    <limits max="{max_results}" default="{max_results}"/>
    <searching>
        <search available="yes" supportedParams="q,cat"/>
        <tv-search available="yes" supportedParams="q,tvdbid,season,ep,cat"/>
    </searching>
    <categories>
        <category id="5000" name="TV">
            <subcat id="5070" name="Anime"/>
        </category>
    </categories>
</caps>"""

    def render(
        self,
        results: list[SearchResult],
        *,
        offset: int = 0,
        total: Optional[int] = None,
        request_base_url: str,
    ) -> str:
        """Render a Newznab RSS search response."""
        rss = Element("rss", version="2.0")
        channel = SubElement(rss, "channel")
        SubElement(channel, "title").text = "AnimeSonarrProxy Newznab"
        SubElement(channel, "description").text = "Anime Newznab proxy"
        SubElement(channel, "link").text = self._api_url(request_base_url)
        SubElement(
            channel,
            f"{{{NEWZNAB_NS}}}response",
            offset=str(offset),
            total=str(total if total is not None else len(results)),
        )

        for result in results:
            self._item(channel, result, request_base_url)

        return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(
            rss, encoding="unicode"
        )

    def _item(
        self, channel: Element, result: SearchResult, request_base_url: str
    ) -> None:
        item = SubElement(channel, "item")
        download_url = self._download_url(result, request_base_url)

        SubElement(item, "title").text = result.title
        SubElement(item, "guid").text = result.provider_guid or result.guid
        SubElement(item, "link").text = download_url
        if result.info_url:
            SubElement(item, "comments").text = result.info_url
        SubElement(item, "pubDate").text = result.pub_date.strftime(
            "%a, %d %b %Y %H:%M:%S +0000"
        )
        for category in result.categories:
            SubElement(item, "category").text = str(category)
        SubElement(
            item,
            "enclosure",
            url=download_url,
            type="application/x-nzb",
            length=str(result.size),
        )

        self._attr(item, "size", str(result.size))
        for category in result.categories:
            self._attr(item, "category", str(category))

        for name, value in result.provider_attrs.items():
            if name in {"size", "category"}:
                continue
            self._attr(item, name, value)

    def _api_url(self, request_base_url: str) -> str:
        return f"{self._base_url(request_base_url)}/newznab"

    def _download_url(self, result: SearchResult, request_base_url: str) -> str:
        query = urlencode(
            {
                "t": "get",
                "provider": result.provider_id or "",
                "id": result.provider_guid or result.guid,
                "apikey": settings.API_KEY,
            }
        )
        return f"{self._api_url(request_base_url)}?{query}"

    def _base_url(self, request_base_url: str) -> str:
        if settings.PUBLIC_BASE_URL:
            return settings.PUBLIC_BASE_URL.rstrip("/")
        return request_base_url.rstrip("/")

    def _attr(self, item: Element, name: str, value: str) -> None:
        SubElement(item, f"{{{NEWZNAB_NS}}}attr", name=name, value=value)


newznab_renderer = NewznabRenderer()
