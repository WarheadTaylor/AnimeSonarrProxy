"""Regression coverage for Newznab provider proxy support."""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree as ET

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import newznab as newznab_module
from app.config import NewznabProviderSettings, Settings, settings
from app.models import SearchResult
from app.services.metadata import TvSearchContext
from app.services.newznab import NEWZNAB_NS, NewznabClient, configured_newznab_providers
from app.services.newznab_core import (
    NEWZNAB_FALLBACK_CONCURRENCY,
    NewznabCoreService,
)
from app.services.newznab_renderer import NewznabRenderer
from app.services.release_matcher import release_matcher


def make_provider(**updates) -> NewznabProviderSettings:
    """Create a provider config for Newznab tests."""
    data = {
        "id": "nzbgeek",
        "name": "NZBGeek",
        "url": "https://api.nzbgeek.info",
        "api_key": "upstream-secret",
        "categories": [5070],
    }
    data.update(updates)
    return NewznabProviderSettings(**data)


def make_usenet_result() -> SearchResult:
    """Create a Newznab-backed search result."""
    return SearchResult(
        title="[SubsPlease] One Piece - S23E01 - 1156 (1080p)",
        original_title="[SubsPlease] One Piece - 1156 (1080p)",
        guid="nzbgeek:abc123",
        link="https://api.nzbgeek.info/api?t=get&id=abc123&apikey=upstream-secret",
        info_url="https://nzbgeek.info/geekseek.php?guid=abc123",
        pub_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        size=2048,
        indexer="NZBGeek",
        categories=[5070],
        protocol="usenet",
        provider_id="nzbgeek",
        provider_guid="abc123",
        provider_attrs={"guid": "abc123", "grabs": "5"},
    )


def make_provider_result(provider_id: str, guid: str) -> SearchResult:
    """Create a matching result owned by a specific upstream provider."""
    return make_usenet_result().model_copy(
        update={
            "guid": f"{provider_id}:{guid}",
            "provider_id": provider_id,
            "provider_guid": guid,
            "provider_attrs": {"guid": guid},
        }
    )


def make_tv_context() -> TvSearchContext:
    """Create a One Piece absolute-numbering TV search context."""
    return TvSearchContext(
        tvdb_id=81797,
        season=23,
        episode=1,
        absolute_episode=1156,
        search_titles=["One Piece", "Wan Pisu"],
        returned_title="One Piece",
    )


def test_newznab_settings_parse_comma_categories():
    """Newznab category env values should accept comma-separated manager input."""
    parsed = Settings(
        _env_file=None,
        NEWZNAB_CATEGORIES="5070,5040",
        NEWZNAB_DEFAULT_CATEGORIES="5070,5045",
    )

    assert parsed.NEWZNAB_CATEGORIES == [5070, 5040]
    assert parsed.NEWZNAB_DEFAULT_CATEGORIES == [5070, 5045]


def test_configured_newznab_providers_uses_single_provider_fallback(monkeypatch):
    """Single-provider env values should create an enabled provider."""
    monkeypatch.setattr(settings, "NEWZNAB_PROVIDERS", [])
    monkeypatch.setattr(settings, "NEWZNAB_URL", "https://api.nzbgeek.info")
    monkeypatch.setattr(settings, "NEWZNAB_API_KEY", "upstream-secret")
    monkeypatch.setattr(settings, "NEWZNAB_ID", "nzbgeek")
    monkeypatch.setattr(settings, "NEWZNAB_NAME", "NZBGeek")
    monkeypatch.setattr(settings, "NEWZNAB_CATEGORIES", [5070])

    providers = configured_newznab_providers()

    assert len(providers) == 1
    assert providers[0].id == "nzbgeek"
    assert providers[0].categories == [5070]


def test_configured_newznab_providers_ignores_disabled(monkeypatch):
    """Disabled Newznab providers should not be searched."""
    monkeypatch.setattr(
        settings,
        "NEWZNAB_PROVIDERS",
        [make_provider(enabled=False), make_provider(id="enabled", enabled=True)],
    )
    monkeypatch.setattr(settings, "NEWZNAB_URL", None)
    monkeypatch.setattr(settings, "NEWZNAB_API_KEY", None)

    providers = configured_newznab_providers()

    assert [provider.id for provider in providers] == ["enabled"]


@pytest.mark.asyncio
async def test_newznab_tv_search_uses_concurrent_provider_fast_paths(monkeypatch):
    """Providers should run concurrently and skip fallbacks after a primary match."""
    providers = [
        make_provider(id="first", name="First"),
        make_provider(id="second", name="Second"),
    ]
    monkeypatch.setattr(settings, "NEWZNAB_PROVIDERS", providers)
    monkeypatch.setattr(settings, "NEWZNAB_URL", None)
    monkeypatch.setattr(settings, "NEWZNAB_API_KEY", None)

    async def fake_resolve_tv(tvdb_id, season, episode):
        return make_tv_context()

    active = 0
    max_active = 0
    calls = []

    async def fake_search(provider, params, fallback_categories=None):
        nonlocal active, max_active
        calls.append((provider.id, params["t"]))
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return [make_provider_result(provider.id, f"{provider.id}-guid")]

    service = NewznabCoreService()
    monkeypatch.setattr(
        "app.services.newznab_core.metadata_resolver.resolve_tv", fake_resolve_tv
    )
    monkeypatch.setattr("app.services.newznab_core.newznab_client.search", fake_search)

    results = await service.tv_search(81797, 23, 1, 100)

    assert max_active == 2
    assert sorted(calls) == [("first", "tvsearch"), ("second", "tvsearch")]
    assert {result.provider_id for result in results} == {"first", "second"}


@pytest.mark.asyncio
async def test_newznab_tv_search_bounds_fallback_concurrency(monkeypatch):
    """A primary miss should run all configured fallbacks with bounded concurrency."""
    provider = make_provider()
    monkeypatch.setattr(settings, "NEWZNAB_PROVIDERS", [provider])
    monkeypatch.setattr(settings, "NEWZNAB_URL", None)
    monkeypatch.setattr(settings, "NEWZNAB_API_KEY", None)
    monkeypatch.setattr(settings, "NEWZNAB_MAX_QUERY_VARIANTS", 5)

    async def fake_resolve_tv(tvdb_id, season, episode):
        return make_tv_context()

    active = 0
    max_active = 0
    fallback_calls = 0

    async def fake_search(provider, params, fallback_categories=None):
        nonlocal active, max_active, fallback_calls
        if params["t"] == "tvsearch":
            return []
        fallback_calls += 1
        call_number = fallback_calls
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return [make_provider_result(provider.id, f"fallback-{call_number}")]

    service = NewznabCoreService()
    monkeypatch.setattr(
        "app.services.newznab_core.metadata_resolver.resolve_tv", fake_resolve_tv
    )
    monkeypatch.setattr("app.services.newznab_core.newznab_client.search", fake_search)

    expected_fallbacks = (
        len(service._tv_params(provider, make_tv_context(), 100, None)) - 1
    )
    results = await service.tv_search(81797, 23, 1, 100)

    assert fallback_calls == expected_fallbacks
    assert max_active == NEWZNAB_FALLBACK_CONCURRENCY
    assert len(results) == expected_fallbacks


@pytest.mark.asyncio
async def test_newznab_client_reuses_shared_http_client(monkeypatch):
    """Repeated upstream requests should reuse one HTTP connection pool."""
    instances = []

    class FakeAsyncClient:
        def __init__(self):
            self.is_closed = False
            self.calls = 0
            instances.append(self)

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            return httpx.Response(
                200,
                text="<rss><channel /></rss>",
                request=httpx.Request("GET", url),
            )

        async def aclose(self):
            self.is_closed = True

    monkeypatch.setattr("app.services.newznab.httpx.AsyncClient", FakeAsyncClient)
    client = NewznabClient()
    provider = make_provider()

    await client.search(provider, {"t": "search", "q": "one piece"})
    await client.search(provider, {"t": "search", "q": "one piece 1156"})
    await client.close()

    assert len(instances) == 1
    assert instances[0].calls == 2
    assert instances[0].is_closed is True


def test_newznab_client_parses_rss_item():
    """Client should parse Newznab RSS into SearchResult metadata."""
    provider = make_provider()
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">
  <channel>
    <item>
      <title>[SubsPlease] One Piece - 1156 (1080p)</title>
      <guid>fallback-guid</guid>
      <link>https://api.nzbgeek.info/api?t=get&amp;id=fallback-guid</link>
      <comments>https://nzbgeek.info/geekseek.php?guid=abc123</comments>
      <pubDate>Thu, 01 Jan 2026 00:00:00 +0000</pubDate>
      <enclosure url="https://api.nzbgeek.info/api?t=get&amp;id=fallback-guid" length="1" type="application/x-nzb" />
      <newznab:attr name="guid" value="abc123" />
      <newznab:attr name="size" value="2048" />
      <newznab:attr name="category" value="5070" />
      <newznab:attr name="grabs" value="5" />
    </item>
  </channel>
</rss>"""

    result = NewznabClient().parse_rss(provider, xml)[0]

    assert result.protocol == "usenet"
    assert result.provider_id == "nzbgeek"
    assert result.provider_guid == "abc123"
    assert result.size == 2048
    assert result.categories == [5070]
    assert result.indexer == "NZBGeek"
    assert result.provider_attrs["grabs"] == "5"


def test_newznab_renderer_uses_nzb_links_without_upstream_key(monkeypatch):
    """Renderer should expose local proxied NZB links and hide upstream API keys."""
    monkeypatch.setattr(settings, "API_KEY", "local-secret")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", None)

    xml = NewznabRenderer().render(
        [make_usenet_result()],
        offset=0,
        total=1,
        request_base_url="http://proxy.local/",
    )

    root = ET.fromstring(xml)
    response = root.find(f".//{{{NEWZNAB_NS}}}response")
    enclosure = root.find(".//enclosure")
    link = root.findtext(".//item/link")

    assert response is not None
    assert response.attrib["total"] == "1"
    assert enclosure is not None
    assert enclosure.attrib["type"] == "application/x-nzb"
    assert link is not None
    assert link.startswith("http://proxy.local/newznab?t=get")
    assert "apikey=local-secret" in link
    assert "upstream-secret" not in xml


def make_test_app() -> TestClient:
    """Create an isolated FastAPI client for the Newznab router."""
    app = FastAPI()
    app.include_router(newznab_module.router)
    return TestClient(app)


def test_newznab_search_rejects_invalid_local_api_key(monkeypatch):
    """Search requests should require the local proxy API key."""
    monkeypatch.setattr(settings, "API_KEY", "local-secret")

    response = make_test_app().get("/newznab?t=search&q=one+piece&apikey=bad")

    assert response.status_code == 403


def test_newznab_search_requires_configured_provider(monkeypatch):
    """Search requests should fail clearly when no upstream providers exist."""
    monkeypatch.setattr(settings, "API_KEY", "local-secret")
    monkeypatch.setattr(settings, "NEWZNAB_PROVIDERS", [])
    monkeypatch.setattr(settings, "NEWZNAB_URL", None)
    monkeypatch.setattr(settings, "NEWZNAB_API_KEY", None)

    response = make_test_app().get("/newznab?t=search&q=one+piece&apikey=local-secret")

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_newznab_get_proxies_upstream_nzb(monkeypatch):
    """t=get should proxy upstream NZB bytes without exposing provider credentials."""
    provider = make_provider()
    monkeypatch.setattr(settings, "API_KEY", "local-secret")
    monkeypatch.setattr(settings, "NEWZNAB_PROVIDERS", [provider])
    monkeypatch.setattr(settings, "NEWZNAB_URL", None)
    monkeypatch.setattr(settings, "NEWZNAB_API_KEY", None)

    async def fake_get_nzb(upstream_provider, provider_guid):
        assert upstream_provider.id == "nzbgeek"
        assert provider_guid == "abc123"
        return httpx.Response(
            200,
            content=b"<?xml version='1.0'?><nzb />",
            headers={
                "content-type": "application/x-nzb",
                "content-disposition": 'attachment; filename="release.nzb"',
            },
        )

    monkeypatch.setattr(newznab_module.newznab_client, "get_nzb", fake_get_nzb)

    response = make_test_app().get(
        "/newznab?t=get&provider=nzbgeek&id=abc123&apikey=local-secret"
    )

    assert response.status_code == 200
    assert response.content == b"<?xml version='1.0'?><nzb />"
    assert response.headers["content-type"].startswith("application/x-nzb")
    assert (
        response.headers["content-disposition"] == 'attachment; filename="release.nzb"'
    )


@pytest.mark.asyncio
async def test_newznab_tvsearch_uses_core_service(monkeypatch):
    """API tvsearch should delegate to the Newznab core and render normalized results."""
    monkeypatch.setattr(settings, "API_KEY", "local-secret")
    monkeypatch.setattr(settings, "NEWZNAB_PROVIDERS", [make_provider()])

    calls = []

    async def fake_tv_search(tvdb_id, season, episode, limit, categories=None):
        calls.append(
            {
                "tvdb_id": tvdb_id,
                "season": season,
                "episode": episode,
                "limit": limit,
                "categories": categories,
            }
        )
        return [make_usenet_result()]

    monkeypatch.setattr(
        newznab_module.newznab_core_service, "tv_search", fake_tv_search
    )

    response = make_test_app().get(
        "/newznab?t=tvsearch&tvdbid=81797&season=23&ep=1&cat=5070&apikey=local-secret"
    )

    assert response.status_code == 200
    assert calls == [
        {
            "tvdb_id": 81797,
            "season": 23,
            "episode": 1,
            "limit": 100,
            "categories": [5070],
        }
    ]
    assert "application/x-nzb" in response.text


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("5070", [5070]),
        ("5070,5040", [5070, 5040]),
        ("[5070,5040]", [5070, 5040]),
        ("", []),
    ],
)
@pytest.mark.parametrize("source", ["environment", "dotenv"])
def test_category_settings_from_real_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw: str,
    expected: List[int],
    source: str,
) -> None:
    """Both category settings accept documented formats through settings sources."""
    names = ("NEWZNAB_CATEGORIES", "NEWZNAB_DEFAULT_CATEGORIES")
    for name in names:
        monkeypatch.delenv(name, raising=False)
    if source == "environment":
        for name in names:
            monkeypatch.setenv(name, raw)
        parsed = Settings(_env_file=None)
    else:
        env_file = tmp_path / "test.env"
        env_file.write_text(
            "\n".join(f"{name}='{raw}'" for name in names), encoding="utf-8"
        )
        parsed = Settings(_env_file=env_file)
    for name in names:
        assert getattr(parsed, name) == expected


@pytest.mark.parametrize(
    "comments",
    [
        "",
        "<comments>https://provider.invalid/details?id=abc&amp;apikey=upstream-secret</comments>",
    ],
)
@pytest.mark.parametrize(
    "guid",
    ["abc", "https://provider.invalid/api?t=get&amp;id=abc&amp;apikey=upstream-secret"],
)
def test_rss_does_not_expose_authenticated_upstream_urls(
    comments: str, guid: str
) -> None:
    """Parsed feeds keep download IDs usable without publishing upstream credentials."""
    xml = f"""<rss xmlns:newznab="{NEWZNAB_NS}"><channel><item>
      <title>One Piece - 01</title><guid>{guid}</guid>
      <link>https://provider.invalid/api?t=get&amp;id=abc&amp;apikey=upstream-secret</link>
      {comments}
      <newznab:attr name="downloadurl" value="https://provider.invalid/?apikey=upstream-secret" />
      <newznab:attr name="apikey" value="upstream-secret" />
      <newznab:attr name="grabs" value="5" />
    </item></channel></rss>"""
    results = NewznabClient().parse_rss(make_provider(), xml)
    assert len(results) == 1
    rendered = NewznabRenderer().render(
        results, request_base_url="http://proxy.invalid"
    )
    assert "upstream-secret" not in rendered
    root = ET.fromstring(rendered)
    download = root.findtext(".//item/link")
    assert parse_qs(urlsplit(download).query)["id"] == ["abc"]
    assert root.find(f".//{{{NEWZNAB_NS}}}attr[@name='grabs']").attrib["value"] == "5"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["success", "status", "timeout"])
async def test_search_logs_hide_upstream_key(
    caplog: pytest.LogCaptureFixture,
    failure: str,
) -> None:
    """Application errors and HTTPX request logs must omit upstream keys."""
    caplog.set_level(logging.DEBUG)

    def respond(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout(str(request.url), request=request)
        return httpx.Response(401 if failure == "status" else 200, text="<rss />")

    client = NewznabClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        assert await client.search(make_provider(), {"t": "search"}) == []
    finally:
        await client.close()
    assert "upstream-secret" not in caplog.text
    if failure != "success":
        assert "search failed" in caplog.text


@pytest.mark.parametrize("failure", ["status", "timeout"])
def test_download_failure_logs_hide_upstream_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: str,
) -> None:
    """Failed proxied downloads retain safe diagnostics and return a gateway error."""
    monkeypatch.setattr(settings, "API_KEY", "local-secret")
    monkeypatch.setattr(settings, "NEWZNAB_PROVIDERS", [make_provider()])

    async def fail(provider: NewznabProviderSettings, guid: str) -> httpx.Response:
        request = httpx.Request(
            "GET", provider.url, params={"apikey": provider.api_key}
        )
        if failure == "timeout":
            raise httpx.ReadTimeout(str(request.url), request=request)
        response = httpx.Response(401, request=request)
        response.raise_for_status()
        return response

    monkeypatch.setattr(newznab_module.newznab_client, "get_nzb", fail)
    response = make_test_app().get(
        "/newznab?t=get&provider=nzbgeek&id=abc&apikey=local-secret"
    )
    assert response.status_code == 502
    assert "get failed" in caplog.text
    assert "upstream-secret" not in caplog.text + response.text


@pytest.mark.parametrize(
    "title,accepted",
    [
        ("[Group] One Piece S02E01 (1080p)", False),
        ("[Group] One Piece S01E01 (1080p)", False),
        ("[Group] One Piece - 01 (1080p)", True),
        ("[Group] One Piece - 02 (1080p)", False),
    ],
)
def test_absolute_matching_requires_absolute_numbering(
    title: str, accepted: bool
) -> None:
    """A seasonal episode number alone cannot establish an absolute match."""
    result = make_usenet_result().model_copy(
        update={"title": title, "original_title": title}
    )
    matched = release_matcher.match_tv_absolute(result, "One Piece", 1)
    assert (matched is not None) == accepted


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query,expected_count", [("One Piece 01", 0), ("One Piece 02", 1), ("One Piece", 1)]
)
async def test_generic_search_preserves_empty_episode_matches(
    monkeypatch: pytest.MonkeyPatch,
    query: str,
    expected_count: int,
) -> None:
    """Recognized episode queries remain filtered even when no release matches."""
    monkeypatch.setattr(settings, "NEWZNAB_PROVIDERS", [make_provider()])
    title = "[Group] One Piece - 02 (1080p)"
    result = make_usenet_result().model_copy(
        update={"title": title, "original_title": title}
    )

    async def search(*args: object, **kwargs: object) -> List[SearchResult]:
        return [result]

    monkeypatch.setattr("app.services.newznab_core.newznab_client.search", search)
    results = await NewznabCoreService().generic_search(query, 100)
    assert len(results) == expected_count


def test_seasonal_match_with_resolved_context_still_works() -> None:
    """TVDB-resolved seasonal matches continue to use the confirmed episode mapping."""
    title = "[Group] One Piece S23E01 (1080p)"
    result = make_usenet_result().model_copy(
        update={"title": title, "original_title": title}
    )
    matched = release_matcher.match_tv(result, make_tv_context())
    assert matched is not None
    assert "S23E01" in matched.title
