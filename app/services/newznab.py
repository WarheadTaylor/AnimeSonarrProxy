"""Newznab upstream provider client and RSS parsing."""

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional
from xml.etree import ElementTree as ET

import httpx

from app.config import NewznabProviderSettings, settings
from app.models import SearchResult

logger = logging.getLogger(__name__)

NEWZNAB_NS = "http://www.newznab.com/DTD/2010/feeds/attributes/"


def configured_newznab_providers() -> list[NewznabProviderSettings]:
    """Return enabled upstream Newznab providers from settings."""
    providers = list(settings.NEWZNAB_PROVIDERS)
    if not providers and settings.NEWZNAB_URL and settings.NEWZNAB_API_KEY:
        providers = [
            NewznabProviderSettings(
                id=settings.NEWZNAB_ID,
                name=settings.NEWZNAB_NAME,
                url=settings.NEWZNAB_URL,
                api_key=settings.NEWZNAB_API_KEY,
                categories=settings.NEWZNAB_CATEGORIES,
            )
        ]
    return [
        provider
        for provider in providers
        if provider.enabled and provider.url and provider.api_key
    ]


def get_newznab_provider(provider_id: str) -> Optional[NewznabProviderSettings]:
    """Return one enabled provider by ID."""
    for provider in configured_newznab_providers():
        if provider.id == provider_id:
            return provider
    return None


class NewznabClient:
    """Client for Newznab-compatible upstream providers."""

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        """Create the shared HTTP client used for upstream requests."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient()

    async def close(self) -> None:
        """Close the shared upstream HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def search(
        self,
        provider: NewznabProviderSettings,
        params: dict[str, Any],
        fallback_categories: Optional[list[int]] = None,
    ) -> list[SearchResult]:
        """Search one upstream provider and parse Newznab RSS results."""
        request_params = self._request_params(provider, params)
        try:
            client = await self._get_client()
            response = await client.get(
                provider.url.rstrip("/"),
                params=request_params,
                timeout=provider.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Newznab provider %s search failed: %s", provider.id, exc)
            return []

        return self.parse_rss(provider, response.text, fallback_categories)

    async def get_nzb(
        self, provider: NewznabProviderSettings, provider_guid: str
    ) -> httpx.Response:
        """Fetch one NZB from an upstream provider."""
        client = await self._get_client()
        response = await client.get(
            provider.url.rstrip("/"),
            params={
                "t": "get",
                "apikey": provider.api_key,
                "id": provider_guid,
            },
            timeout=provider.timeout,
        )
        response.raise_for_status()
        return response

    async def _get_client(self) -> httpx.AsyncClient:
        """Return the shared client, initializing it for direct service use."""
        await self.start()
        assert self._client is not None
        return self._client

    def parse_rss(
        self,
        provider: NewznabProviderSettings,
        xml: str,
        fallback_categories: Optional[list[int]] = None,
    ) -> list[SearchResult]:
        """Parse a Newznab RSS response into normalized search results."""
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            logger.warning(
                "Newznab provider %s returned invalid XML: %s", provider.id, exc
            )
            return []

        results: list[SearchResult] = []
        for item in root.findall(".//item"):
            result = self._parse_item(provider, item, fallback_categories)
            if result:
                results.append(result)
        return results

    def _request_params(
        self, provider: NewznabProviderSettings, params: dict[str, Any]
    ) -> dict[str, str]:
        request_params: dict[str, str] = {"apikey": provider.api_key}
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, list):
                request_params[key] = ",".join(str(item) for item in value)
            else:
                request_params[key] = str(value)
        return request_params

    def _parse_item(
        self,
        provider: NewznabProviderSettings,
        item: ET.Element,
        fallback_categories: Optional[list[int]],
    ) -> Optional[SearchResult]:
        title = item.findtext("title", "").strip()
        guid = item.findtext("guid", "").strip()
        link = item.findtext("link", "").strip()
        if not title or not (guid or link):
            return None

        attrs = self._newznab_attrs(item)
        provider_guid = attrs.get("guid") or guid or link
        categories = self._categories(attrs, fallback_categories or provider.categories)
        size = self._size(attrs, item)
        pub_date = self._parse_date(item.findtext("pubDate", ""))

        return SearchResult(
            title=title,
            original_title=title,
            guid=f"{provider.id}:{provider_guid}",
            link=link or guid,
            info_url=item.findtext("comments", "") or link or guid,
            pub_date=pub_date,
            size=size,
            seeders=self._int_attr(attrs, "seeders"),
            peers=self._int_attr(attrs, "peers"),
            indexer=provider.name,
            categories=categories,
            protocol="usenet",
            provider_id=provider.id,
            provider_guid=provider_guid,
            provider_attrs=attrs,
        )

    def _newznab_attrs(self, item: ET.Element) -> dict[str, str]:
        attrs: dict[str, str] = {}
        for element in item.iter():
            if not element.tag.endswith("attr"):
                continue
            name = element.attrib.get("name")
            value = element.attrib.get("value")
            if name and value is not None:
                if name in attrs and attrs[name] != value:
                    attrs[name] = f"{attrs[name]},{value}"
                else:
                    attrs[name] = value
        return attrs

    def _categories(
        self, attrs: dict[str, str], fallback_categories: list[int]
    ) -> list[int]:
        categories: list[int] = []
        for raw_category in attrs.get("category", "").split(","):
            raw_category = raw_category.strip()
            if not raw_category:
                continue
            try:
                category = int(raw_category)
            except ValueError:
                continue
            if category not in categories:
                categories.append(category)
        return categories or list(fallback_categories)

    def _size(self, attrs: dict[str, str], item: ET.Element) -> int:
        raw_size = attrs.get("size")
        if raw_size:
            return self._safe_int(raw_size)

        enclosure = item.find("enclosure")
        if enclosure is not None:
            return self._safe_int(enclosure.attrib.get("length", "0"))
        return 0

    def _int_attr(self, attrs: dict[str, str], name: str) -> int:
        return self._safe_int(attrs.get(name, "0"))

    def _safe_int(self, value: str) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _parse_date(self, value: str) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError):
            return datetime.now(timezone.utc)


newznab_client = NewznabClient()
