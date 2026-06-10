"""Tests for the direct Nyaa core rewrite."""

from datetime import datetime
from xml.etree import ElementTree as ET

import pytest

from app.api import torznab
from app.models import SearchResult
from app.services.metadata import MovieSearchContext, TvSearchContext
from app.services.nyaa import nyaa_client
from app.services.release_matcher import release_matcher
from app.services.release_parser import release_parser
from app.services.torznab_renderer import TORZNAB_NS, torznab_renderer


def _result(title: str) -> SearchResult:
    return SearchResult(
        title=title,
        original_title=title,
        guid=f"https://nyaa.si/view/{abs(hash(title))}",
        link="https://nyaa.si/download/1.torrent",
        info_url=f"https://nyaa.si/view/{abs(hash(title))}",
        pub_date=datetime(2026, 5, 22),
        size=1024,
        seeders=10,
        peers=12,
        indexer="nyaa",
        categories=[5070],
        info_hash="abcdef123456",
        nyaa_category_id="1_2",
    )


def _attrs(xml_text: str) -> dict[str, list[str]]:
    root = ET.fromstring(xml_text)
    attrs: dict[str, list[str]] = {}
    for attr in root.findall(f".//{{{TORZNAB_NS}}}attr"):
        attrs.setdefault(attr.attrib["name"], []).append(attr.attrib["value"])
    return attrs


def test_nyaa_rss_parser_extracts_required_metadata() -> None:
    """Nyaa RSS parsing should preserve RSS and Nyaa-specific metadata."""
    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:nyaa="https://nyaa.si/xmlns/nyaa">
  <channel>
    <item>
      <title>[SubsPlease] One Piece - 1156 (1080p)</title>
      <guid>https://nyaa.si/view/123</guid>
      <link>https://nyaa.si/download/123.torrent</link>
      <pubDate>Tue, 09 Sep 2025 20:24:10 -0000</pubDate>
      <nyaa:seeders>20</nyaa:seeders>
      <nyaa:leechers>4</nyaa:leechers>
      <nyaa:size>1.5 GiB</nyaa:size>
      <nyaa:categoryId>1_2</nyaa:categoryId>
      <nyaa:infoHash>ABCDEF123456</nyaa:infoHash>
      <nyaa:trusted>Yes</nyaa:trusted>
      <nyaa:remake>No</nyaa:remake>
    </item>
  </channel>
</rss>"""

    results = nyaa_client._parse_rss_response(xml_text)

    assert len(results) == 1
    result = results[0]
    assert result.title == "[SubsPlease] One Piece - 1156 (1080p)"
    assert result.original_title == result.title
    assert result.size == 1610612736
    assert result.seeders == 20
    assert result.peers == 24
    assert result.info_hash == "abcdef123456"
    assert result.nyaa_category_id == "1_2"
    assert result.trusted is True
    assert result.remake is False


def test_tv_match_normalizes_absolute_episode_title() -> None:
    """Sonarr returned titles should center on SxxEyy plus absolute episode."""
    context = TvSearchContext(
        tvdb_id=81797,
        season=23,
        episode=1,
        absolute_episode=1156,
        search_titles=["One Piece"],
        returned_title="One Piece",
    )

    matched = release_matcher.match_tv(
        _result("[SubsPlease] One Piece - 1156 (1080p) [662D886D].mkv"),
        context,
    )

    assert matched is not None
    assert (
        matched.title == "[SubsPlease] One Piece - S23E01 - 1156 (1080p) [662D886D].mkv"
    )


def test_tv_match_accepts_ep_prefix_episode_title() -> None:
    """EP-prefixed absolute numbers should parse as episode matches."""
    context = TvSearchContext(
        tvdb_id=81797,
        season=23,
        episode=1,
        absolute_episode=1156,
        search_titles=["One Piece"],
        returned_title="One Piece",
    )

    matched = release_matcher.match_tv(
        _result("[ToonsHub] One Piece EP1156 1080p WEB-DL AAC2.0 H.264"),
        context,
    )

    assert matched is not None
    assert matched.title == (
        "[ToonsHub] One Piece - S23E01 - 1156 " "1080p WEB-DL AAC2.0 H.264"
    )


def test_tv_match_preserves_release_revision() -> None:
    """Release versions should stay attached to the normalized episode token."""
    context = TvSearchContext(
        tvdb_id=1,
        season=1,
        episode=1,
        absolute_episode=1,
        search_titles=["Show Name"],
        returned_title="Show Name",
    )

    matched = release_matcher.match_tv(
        _result("[Group] Show Name - 01v2 [1080p]"),
        context,
    )

    assert matched is not None
    assert matched.title == "[Group] Show Name - S01E01v2 - 1 [1080p]"


def test_tv_match_rejects_batches() -> None:
    """Batch and range releases should not satisfy exact episode searches."""
    context = TvSearchContext(
        tvdb_id=1,
        season=1,
        episode=1,
        absolute_episode=1,
        search_titles=["Show Name"],
        returned_title="Show Name",
    )

    matched = release_matcher.match_tv(
        _result("[Group] Show Name Season 1 01-12 Batch [1080p]"),
        context,
    )

    assert matched is None


def test_movie_match_uses_radarr_title_year_first() -> None:
    """Radarr returned titles should start with movie title and year."""
    context = MovieSearchContext(
        search_titles=["Suzume no Tojimari", "Suzume"],
        returned_title="Suzume",
        year=2022,
        tmdb_id=916224,
    )

    matched = release_matcher.match_movie(
        _result("[Group] Suzume no Tojimari (2022) [1080p][BDRip]"),
        context,
    )

    assert matched is not None
    assert matched.title == "Suzume (2022) [1080p][BDRip] -Group"
    assert matched.categories == [2000, 2060]


def test_torznab_renderer_includes_required_attrs() -> None:
    """Torznab XML should include parser-critical metadata attrs."""
    xml_text = torznab_renderer.render(
        [_result("[SubsPlease] One Piece - S23E01 - 1156 (1080p)")],
        tvdb_id=81797,
        season=23,
        episode=1,
    )

    attrs = _attrs(xml_text)

    assert attrs["size"] == ["1024"]
    assert attrs["seeders"] == ["10"]
    assert attrs["peers"] == ["12"]
    assert attrs["infohash"] == ["abcdef123456"]
    assert attrs["category"] == ["5070"]
    assert attrs["tvdbid"] == ["81797"]
    assert attrs["season"] == ["23"]
    assert attrs["episode"] == ["1"]
    assert attrs["language"] == ["English"]
    root = ET.fromstring(xml_text)
    enclosure = root.find(".//enclosure")
    assert enclosure is not None
    assert enclosure.attrib["length"] == "1024"


@pytest.mark.asyncio
async def test_tvsearch_flow_uses_resolver_nyaa_and_normalizer(monkeypatch) -> None:
    """Exact Sonarr flow should resolve, search, match, and render normalized XML."""

    async def fake_resolve_tv(tvdb_id: int, season: int, episode: int):
        return TvSearchContext(
            tvdb_id=tvdb_id,
            season=season,
            episode=episode,
            absolute_episode=1156,
            search_titles=["One Piece"],
            returned_title="One Piece",
        )

    async def fake_search_multi(**kwargs):
        return [_result("[SubsPlease] One Piece - 1156 (1080p)")]

    monkeypatch.setattr(
        "app.services.core.metadata_resolver.resolve_tv", fake_resolve_tv
    )
    monkeypatch.setattr("app.services.core.nyaa_client.search_multi", fake_search_multi)

    response = await torznab.handle_tvsearch(81797, 23, 1, None, 100, 0)
    root = ET.fromstring(response.body.decode("utf-8"))

    assert root.findtext(".//item/title") == (
        "[SubsPlease] One Piece - S23E01 - 1156 (1080p)"
    )


@pytest.mark.asyncio
async def test_tvsearch_flow_returns_empty_for_missing_mapping(monkeypatch) -> None:
    """Unresolved TV requests should produce an empty RSS response."""

    async def fake_resolve_tv(tvdb_id: int, season: int, episode: int):
        return None

    monkeypatch.setattr(
        "app.services.core.metadata_resolver.resolve_tv", fake_resolve_tv
    )

    response = await torznab.handle_tvsearch(1, 1, 1, None, 100, 0)
    root = ET.fromstring(response.body.decode("utf-8"))

    assert root.findall(".//item") == []


@pytest.mark.asyncio
async def test_specials_require_special_release_keyword(monkeypatch) -> None:
    """Special searches should reject regular episode-looking releases."""

    async def fake_resolve_tv(tvdb_id: int, season: int, episode: int):
        return TvSearchContext(
            tvdb_id=tvdb_id,
            season=season,
            episode=episode,
            absolute_episode=1,
            search_titles=["Prison School"],
            returned_title="Prison School",
            is_special=True,
        )

    async def fake_search_multi(**kwargs):
        return [
            _result("[Group] Prison School - 01 [1080p]"),
            _result("[Group] Prison School OVA - 01 [1080p]"),
        ]

    monkeypatch.setattr(
        "app.services.core.metadata_resolver.resolve_tv", fake_resolve_tv
    )
    monkeypatch.setattr("app.services.core.nyaa_client.search_multi", fake_search_multi)

    response = await torznab.handle_tvsearch(293267, 0, 1, None, 100, 0)
    root = ET.fromstring(response.body.decode("utf-8"))
    titles = [item.text for item in root.findall(".//item/title")]

    assert titles == ["[Group] Prison School - S00E01 - 1 [1080p]"]


@pytest.mark.asyncio
async def test_movie_flow_supports_tmdb_imdb_and_query_fallback(monkeypatch) -> None:
    """Movie flow should render Radarr-friendly movie attrs for resolved requests."""
    calls = []

    async def fake_resolve_movie(tmdb_id, imdb_id, query, year):
        calls.append((tmdb_id, imdb_id, query, year))
        return MovieSearchContext(
            search_titles=["Suzume no Tojimari", "Suzume"],
            returned_title="Suzume",
            year=2022,
            tmdb_id=tmdb_id or 916224,
            imdb_id=imdb_id or "tt16428256",
        )

    async def fake_search_multi(**kwargs):
        return [_result("[Group] Suzume no Tojimari (2022) [1080p][BDRip]")]

    monkeypatch.setattr(
        "app.services.core.metadata_resolver.resolve_movie", fake_resolve_movie
    )
    monkeypatch.setattr("app.services.core.nyaa_client.search_multi", fake_search_multi)

    for args in [
        (916224, None, None, None),
        (None, "tt16428256", None, None),
        (None, None, "Suzume", 2022),
    ]:
        response = await torznab.handle_movie_search(*args, limit=100, offset=0)
        root = ET.fromstring(response.body.decode("utf-8"))
        assert root.findtext(".//item/title") == "Suzume (2022) [1080p][BDRip] -Group"
        attrs = _attrs(response.body.decode("utf-8"))
        assert attrs["tmdbid"] == ["916224"]
        assert attrs["imdbid"] == ["tt16428256"]
        assert attrs["year"] == ["2022"]

    assert calls == [
        (916224, None, None, None),
        (None, "tt16428256", None, None),
        (None, None, "Suzume", 2022),
    ]
