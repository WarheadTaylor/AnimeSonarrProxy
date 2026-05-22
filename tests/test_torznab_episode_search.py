"""Tests for Torznab episode search filtering and metadata."""

from datetime import datetime
from xml.etree import ElementTree as ET

import pytest

from app.api import torznab
from app.api.torznab import create_torznab_rss
from app.config import settings
from app.models import EpisodeInfo, SearchResult
from app.services.query import query_service


def _result(title: str) -> SearchResult:
    """Create a minimal search result for tests."""
    return SearchResult(
        title=title,
        guid=title,
        link="https://example.test/download.torrent",
        pub_date=datetime(2026, 5, 22),
        size=1024,
        seeders=10,
        peers=2,
    )


def test_episode_filter_removes_results_without_absolute_episode() -> None:
    """Episode filtering should remove title-only leaks when episode matches exist."""
    results = [
        _result("One Piece: Baron Omatsuri and the Secret Island (2005)"),
        _result("[SubsPlease] One Piece - 1156 (1080p) [662D886D].mkv"),
        _result("[Judas] One Piece - 1156v2 [1080p][HEVC x265 10bit]"),
        _result("[ToonsHub] One Piece EP1156 1080p WEB-DL AAC2.0 H.264"),
    ]

    filtered = query_service.filter_by_episode_numbers(results, [1156])

    assert [result.title for result in filtered] == [
        "[SubsPlease] One Piece - 1156 (1080p) [662D886D].mkv",
        "[Judas] One Piece - 1156v2 [1080p][HEVC x265 10bit]",
        "[ToonsHub] One Piece EP1156 1080p WEB-DL AAC2.0 H.264",
    ]


def test_episode_filter_keeps_original_results_when_no_episode_matches() -> None:
    """Unusual naming schemes should not be turned into empty result sets."""
    results = [_result("[Group] One Piece latest episode")]

    filtered = query_service.filter_by_episode_numbers(results, [1156])

    assert filtered == results


def test_torznab_rss_includes_episode_and_language_metadata() -> None:
    """RSS items should expose metadata Sonarr can use for release decisions."""
    xml_text = create_torznab_rss(
        [_result("[SubsPlease] One Piece - 1156 (1080p) [662D886D].mkv")],
        tvdbid=81797,
        season=23,
        episode=1,
    )

    root = ET.fromstring(xml_text)
    attrs = {
        attr.attrib["name"]: attr.attrib["value"]
        for attr in root.findall(".//{http://torznab.com/schemas/2015/feed}attr")
    }

    assert attrs["tvdbid"] == "81797"
    assert attrs["season"] == "23"
    assert attrs["episode"] == "1"
    assert attrs["language"] == "English"


def test_sonarr_title_normalizer_is_opt_in(monkeypatch) -> None:
    """Normalizer should not alter release titles unless explicitly enabled."""
    monkeypatch.setattr(settings, "SONARR_TITLE_NORMALIZER_ENABLED", False)
    results = [_result("[SubsPlease] One Piece - 1156 (1080p) [662D886D].mkv")]

    normalized = torznab._normalize_result_titles_for_sonarr(
        results,
        series_title="One Piece",
        season=23,
        episode=1,
        absolute_episode=1156,
    )

    assert normalized[0].title == results[0].title


def test_sonarr_title_normalizer_rewrites_to_canonical_episode(monkeypatch) -> None:
    """Beta normalizer should return titles centered on Sonarr's SxxEyy parser."""
    monkeypatch.setattr(settings, "SONARR_TITLE_NORMALIZER_ENABLED", True)
    results = [_result("[SubsPlease] One Piece - 1156 (1080p) [662D886D].mkv")]

    normalized = torznab._normalize_result_titles_for_sonarr(
        results,
        series_title="One Piece",
        season=23,
        episode=1,
        absolute_episode=1156,
    )

    assert normalized[0].title == "[SubsPlease] One Piece - S23E01 - 1156 (1080p)"
    assert results[0].title == "[SubsPlease] One Piece - 1156 (1080p) [662D886D].mkv"


@pytest.mark.asyncio
async def test_generic_search_filters_trailing_episode_number(monkeypatch) -> None:
    """Generic searches like 'One Piece 1156' should drop title-only leaks."""

    class FakeSearchClient:
        async def search(self, query: str, limit: int = 100):
            return [
                _result(
                    "One Piece: Baron Omatsuri and the Secret Island (2005) "
                    "[BD Remux 1080p AVC TrueHD 5.1]"
                ),
                _result("[SubsPlease] One Piece - 1156 (1080p) [662D886D].mkv"),
                _result("[ToonsHub] One Piece EP1156 1080p WEB-DL AAC2.0 H.264"),
            ]

    monkeypatch.setattr(torznab, "get_search_client", lambda: FakeSearchClient())

    response = await torznab.handle_search("One Piece 1156", limit=100, offset=0)
    root = ET.fromstring(response.body.decode("utf-8"))
    titles = [element.text for element in root.findall(".//item/title")]

    assert titles == [
        "[SubsPlease] One Piece - 1156 (1080p) [662D886D].mkv",
        "[ToonsHub] One Piece EP1156 1080p WEB-DL AAC2.0 H.264",
    ]


@pytest.mark.asyncio
async def test_generic_tvsearch_context_enables_title_normalizer(monkeypatch) -> None:
    """A no-TVDB tvsearch with season/episode should still normalize titles."""

    class FakeSearchClient:
        async def search(self, query: str, limit: int = 100):
            return [_result("[SubsPlease] One Piece - 1156 (1080p) [662D886D].mkv")]

    monkeypatch.setattr(settings, "SONARR_TITLE_NORMALIZER_ENABLED", True)
    monkeypatch.setattr(torznab, "get_search_client", lambda: FakeSearchClient())

    response = await torznab.handle_search(
        "One Piece 1156", limit=100, offset=0, season=23, episode=1
    )
    root = ET.fromstring(response.body.decode("utf-8"))
    titles = [element.text for element in root.findall(".//item/title")]

    assert titles == ["[SubsPlease] One Piece - S23E01 - 1156 (1080p)"]


@pytest.mark.asyncio
async def test_generic_search_without_absolute_episode_does_not_normalize(
    monkeypatch,
) -> None:
    """Generic title-only searches should not rewrite unrelated episodes."""

    class FakeSearchClient:
        async def search(self, query: str, limit: int = 100):
            return [
                _result("[SubsPlease] One Piece - 1162 (1080p) [34C9E856].mkv"),
                _result("[SubsPlease] One Piece - 1161 (1080p) [9BEAE717].mkv"),
            ]

    monkeypatch.setattr(settings, "SONARR_TITLE_NORMALIZER_ENABLED", True)
    monkeypatch.setattr(torznab, "get_search_client", lambda: FakeSearchClient())

    response = await torznab.handle_search(
        "One Piece", limit=100, offset=0, season=23, episode=1
    )
    root = ET.fromstring(response.body.decode("utf-8"))
    titles = [element.text for element in root.findall(".//item/title")]

    assert titles == [
        "[SubsPlease] One Piece - 1162 (1080p) [34C9E856].mkv",
        "[SubsPlease] One Piece - 1161 (1080p) [9BEAE717].mkv",
    ]


@pytest.mark.asyncio
async def test_tvsearch_uses_sonarr_metadata_when_mapping_missing(monkeypatch) -> None:
    """A TVDB search without local mapping should fall back to Sonarr metadata."""

    class FakeSearchClient:
        async def search_multi(self, titles, episodes=None, keywords=None, limit=100):
            return [_result("[SubsPlease] One Piece - 1156 (1080p) [662D886D].mkv")]

    async def fake_get_mapping(tvdb_id: int):
        return None

    async def fake_get_episode_by_season_episode(
        tvdb_id: int, season: int, episode: int
    ):
        return EpisodeInfo(
            series_id=1,
            series_title="One Piece",
            season_number=23,
            episode_number=1,
            absolute_episode_number=1156,
            title="The Long-sought Elbaph! The Big Reunion Banquet",
        )

    monkeypatch.setattr(settings, "SONARR_TITLE_NORMALIZER_ENABLED", True)
    monkeypatch.setattr(torznab.mapping_service, "get_mapping", fake_get_mapping)
    monkeypatch.setattr(torznab.sonarr_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        torznab.sonarr_client,
        "get_episode_by_season_episode",
        fake_get_episode_by_season_episode,
    )
    monkeypatch.setattr(torznab, "get_search_client", lambda: FakeSearchClient())

    response = await torznab.handle_tvsearch(81797, 23, 1, limit=100, offset=0)
    root = ET.fromstring(response.body.decode("utf-8"))
    titles = [element.text for element in root.findall(".//item/title")]

    assert titles == ["[SubsPlease] One Piece - S23E01 - 1156 (1080p)"]
