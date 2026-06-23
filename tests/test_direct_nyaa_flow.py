"""Regression coverage for the direct Nyaa search and Torznab rendering flow."""

from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import pytest

from app.api import torznab as torznab_module
from app.api.torznab import parse_categories
from app.models import SearchResult
from app.services import core as core_module
from app.services.core import CoreSearchService
from app.services.metadata import MovieSearchContext
from app.services.nyaa import NyaaClient
from app.services.nyaa import TORZNAB_CATEGORY_LIVE_ACTION_ENGLISH
from app.services.release_matcher import release_matcher
from app.services.release_parser import release_parser
from app.services.torznab_renderer import TORZNAB_NS, TorznabRenderer


def make_result(
    title: str,
    *,
    guid: str | None = None,
    info_hash: str | None = None,
    pub_date: datetime | None = None,
    seeders: int = 10,
    categories: list[int] | None = None,
) -> SearchResult:
    """Create a realistic SearchResult without relying on network fixtures."""
    guid = guid or f"https://nyaa.si/view/{abs(hash(title))}"
    return SearchResult(
        title=title,
        original_title=title,
        guid=guid,
        link=f"{guid}.torrent",
        info_url=guid,
        pub_date=pub_date or datetime(2026, 1, 1, tzinfo=timezone.utc),
        size=1024,
        seeders=seeders,
        peers=seeders + 1,
        indexer="nyaa",
        categories=categories or [5070],
        info_hash=info_hash,
    )


class FakeMetadataResolver:
    """Fake metadata resolver returning a fixed movie context."""

    async def resolve_movie(self, tmdb_id, imdb_id, query, year):
        """Return a movie context using the manager-provided query and year."""
        return MovieSearchContext(
            search_titles=[query or "Suzume"],
            returned_title=query or "Suzume",
            year=year,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
        )


class RecordingNyaaClient:
    """Fake Nyaa client that records core search requests."""

    def __init__(self, results: list[SearchResult]):
        self.results = results
        self.search_queries: list[tuple[str, int | None]] = []
        self.search_calls: list[dict[str, object]] = []
        self.search_multi_calls: list[dict[str, object]] = []

    async def search(
        self,
        query: str,
        limit: int | None = None,
        categories: list[int] | None = None,
    ):
        """Record a direct search query and return canned results."""
        self.search_queries.append((query, limit))
        self.search_calls.append(
            {
                "query": query,
                "limit": limit,
                "categories": categories,
            }
        )
        return self.results

    async def search_multi(
        self,
        titles: list[str],
        episodes: list[int] | None = None,
        keywords: list[str] | None = None,
        limit: int | None = None,
        categories: list[int] | None = None,
    ):
        """Record a combined search request and return canned results."""
        self.search_multi_calls.append(
            {
                "titles": titles,
                "episodes": episodes,
                "keywords": keywords,
                "limit": limit,
                "categories": categories,
            }
        )
        return self.results


class RecordingCoreSearchService:
    """Fake core service that records generic search requests."""

    def __init__(self, results: list[SearchResult]):
        self.results = results
        self.generic_search_calls: list[dict[str, object]] = []

    async def generic_search(
        self,
        query: str,
        limit: int,
        season: int | None = None,
        episode: int | None = None,
        categories: list[int] | None = None,
    ):
        """Record a generic search call and return canned results."""
        self.generic_search_calls.append(
            {
                "query": query,
                "limit": limit,
                "season": season,
                "episode": episode,
                "categories": categories,
            }
        )
        return self.results


def test_dash_delimited_movie_year_is_not_treated_as_episode():
    """A movie title like 'Title - 2022' should still match as a movie."""
    result = make_result("[SubsPlease] Suzume - 2022 [1080p][BDRip]")
    context = MovieSearchContext(
        search_titles=["Suzume"],
        returned_title="Suzume",
        year=2022,
        tmdb_id=916224,
        imdb_id="tt16428256",
    )

    parsed = release_parser.parse(result.title)
    matched = release_matcher.match_movie(result, context)

    assert parsed.year == 2022
    assert parsed.episode_numbers == []
    assert matched is not None
    assert matched.title == "Suzume (2022) [1080p][BDRip] -SubsPlease"
    assert matched.categories == [2000, 2060]


@pytest.mark.asyncio
async def test_movie_search_with_year_keeps_bare_title_retrieval_path(monkeypatch):
    """Year-qualified movie searches should not rely only on year/movie keywords."""
    nyaa = RecordingNyaaClient([make_result("[SubsPlease] Suzume [1080p][BDRip]")])
    monkeypatch.setattr(core_module, "metadata_resolver", FakeMetadataResolver())
    monkeypatch.setattr(core_module, "nyaa_client", nyaa)

    await CoreSearchService().movie_search(
        tmdb_id=916224,
        imdb_id="tt16428256",
        query="Suzume",
        year=2022,
        limit=25,
    )

    assert any(
        call["titles"] == ["Suzume"] and not call["keywords"]
        for call in nyaa.search_multi_calls
    )


@pytest.mark.asyncio
async def test_generic_search_with_season_episode_returns_ranked_raw_results(
    monkeypatch,
):
    """Generic tvsearch fallback should not discard absolute-numbered raw releases."""
    older = make_result(
        "[SubsPlease] One Piece - 1156 [1080p]",
        guid="https://nyaa.si/view/old",
        info_hash="same-info-hash",
        pub_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        seeders=5,
    )
    newer = make_result(
        "[SubsPlease] One Piece - 1156 [720p]",
        guid="https://nyaa.si/view/new",
        info_hash="same-info-hash",
        pub_date=datetime(2026, 1, 2, tzinfo=timezone.utc),
        seeders=7,
    )
    lower_ranked = make_result(
        "[Other] One Piece - 1156 [480p]",
        guid="https://nyaa.si/view/lower",
        info_hash="different-info-hash",
        pub_date=datetime(2026, 1, 3, tzinfo=timezone.utc),
        seeders=1,
    )
    nyaa = RecordingNyaaClient([older, lower_ranked, newer])
    monkeypatch.setattr(core_module, "nyaa_client", nyaa)

    results = await CoreSearchService().generic_search(
        "One Piece",
        limit=10,
        season=23,
        episode=1,
    )

    assert nyaa.search_queries == [("One Piece", 10)]
    assert [result.guid for result in results] == [
        "https://nyaa.si/view/new",
        "https://nyaa.si/view/lower",
    ]


@pytest.mark.asyncio
async def test_generic_tvsearch_filters_known_seasonal_mismatches(monkeypatch):
    """Alias fallback searches should reject releases for the wrong seasonal ep."""
    wrong_s04e11 = make_result(
        "[ToonsHub] That Time I Got Reincarnated as a Slime S04E11 1080p "
        "BILI WEB-DL AAC2.0 H.265 (Tensei Shitara Slime Datta Ken, Multi-Subs)",
        guid="https://nyaa.si/view/s04e11",
        seeders=100,
    )
    wrong_fourth_09 = make_result(
        "[Asakura] Tensei Shitara Slime Datta Ken 4th Season - 09 "
        "[1080p WEB AAC x264] [532BC33A] | That Time I Got Reincarnated as "
        "a Slime Season 4 | Episode 81",
        guid="https://nyaa.si/view/fourth-09",
        seeders=99,
    )
    valid_s4_10 = make_result(
        "[SubsPlease] Tensei Shitara Slime Datta Ken S4 - 10 (1080p) "
        "[7FA8BA37].mkv",
        guid="https://nyaa.si/view/s4-10",
        seeders=10,
    )
    valid_fourth_10 = make_result(
        "[Erai-raws] Tensei Shitara Slime Datta Ken 4th Season - 10 "
        "[1080p CR WEB-DL AVC AAC][MultiSub][80510B57]",
        guid="https://nyaa.si/view/fourth-10",
        seeders=20,
    )
    ambiguous_absolute = make_result(
        "[SubsPlease] One Piece - 1156 (1080p) [ABC123].mkv",
        guid="https://nyaa.si/view/absolute",
        seeders=5,
    )
    nyaa = RecordingNyaaClient(
        [
            wrong_s04e11,
            wrong_fourth_09,
            valid_s4_10,
            valid_fourth_10,
            ambiguous_absolute,
        ]
    )
    monkeypatch.setattr(core_module, "nyaa_client", nyaa)

    results = await CoreSearchService().generic_search(
        "Tensei Shitara Slime Datta Ken S4",
        limit=10,
        season=4,
        episode=10,
    )

    assert [result.guid for result in results] == [
        "https://nyaa.si/view/fourth-10",
        "https://nyaa.si/view/s4-10",
        "https://nyaa.si/view/absolute",
    ]


def test_parser_extracts_nonstandard_season_markers():
    """Common Nyaa season markers should be available to fallback filtering."""
    s4_release = release_parser.parse(
        "[SubsPlease] Tensei Shitara Slime Datta Ken S4 - 10 (1080p) "
        "[7FA8BA37].mkv"
    )
    fourth_release = release_parser.parse(
        "[Erai-raws] Tensei Shitara Slime Datta Ken 4th Season - 10 "
        "[1080p CR WEB-DL AVC AAC][MultiSub][80510B57]"
    )
    season_release = release_parser.parse(
        "[Asakura] Tensei Shitara Slime Datta Ken 4th Season - 10 "
        "[1080p WEB AAC x264] | That Time I Got Reincarnated as a Slime "
        "Season 4 | Episode 82"
    )

    assert s4_release.season_numbers == [4]
    assert fourth_release.season_numbers == [4]
    assert season_release.season_numbers == [4]


def test_missing_and_malformed_nyaa_dates_are_timezone_aware_and_rankable():
    """Fallback Nyaa dates must not mix naive and aware datetimes during ranking."""
    client = NyaaClient()
    missing = client._parse_date("")
    malformed = client._parse_date("not a date")
    parsed = client._parse_date("Tue, 09 Sep 2025 20:24:10 -0000")

    assert missing.tzinfo is not None
    assert malformed.tzinfo is not None
    assert parsed.tzinfo is not None

    results = [
        make_result("missing date", pub_date=missing, seeders=1),
        make_result("malformed date", pub_date=malformed, seeders=1),
        make_result("parsed date", pub_date=parsed, seeders=1),
    ]

    ranked = CoreSearchService()._rank(results, limit=10)

    assert len(ranked) == 3


def test_nyaa_selected_categories_returns_empty_without_torznab_categories():
    """Searches without selected supported categories should not hit Nyaa."""
    assert NyaaClient()._selected_categories() == []


def test_nyaa_selected_categories_ignores_unknown_torznab_categories():
    """Unknown Torznab categories should not fall back to a Nyaa category."""
    assert NyaaClient()._selected_categories([999999]) == []


def test_nyaa_selected_categories_can_use_torznab_category_selection():
    """Selected Torznab live-action category should map to Nyaa 4_1."""
    assert NyaaClient()._selected_categories(
        [TORZNAB_CATEGORY_LIVE_ACTION_ENGLISH]
    ) == ["4_1"]


def test_parse_categories_dedupes_and_ignores_invalid_values():
    """Torznab cat parsing should tolerate comma-separated manager input."""
    assert parse_categories("5070, 100041, invalid,5070") == [5070, 100041]


@pytest.mark.asyncio
async def test_tvsearch_test_request_uses_latest_selected_category(monkeypatch):
    """Indexer tests without identifiers should not hardcode an anime title."""
    core = RecordingCoreSearchService([make_result("Latest live action")])
    monkeypatch.setattr(torznab_module, "core_search_service", core)

    await torznab_module.handle_tvsearch(
        tvdb_id=None,
        season=None,
        episode=None,
        query=None,
        limit=100,
        offset=0,
        categories=[TORZNAB_CATEGORY_LIVE_ACTION_ENGLISH],
    )

    assert core.generic_search_calls == [
        {
            "query": "",
            "limit": 100,
            "season": None,
            "episode": None,
            "categories": [TORZNAB_CATEGORY_LIVE_ACTION_ENGLISH],
        }
    ]


@pytest.mark.asyncio
async def test_nyaa_search_without_selected_category_skips_request(monkeypatch):
    """No selected supported category means no Nyaa request."""
    client = NyaaClient()

    async def fake_search_category(query, category, filter_code, limit):
        raise AssertionError("Nyaa should not be searched without a category")

    monkeypatch.setattr(client, "_search_category", fake_search_category)

    assert await client.search("Kingdom", limit=25) == []


@pytest.mark.asyncio
async def test_generic_search_passes_selected_torznab_categories(monkeypatch):
    """Core generic searches should preserve manager-selected categories."""
    nyaa = RecordingNyaaClient([make_result("Kingdom live action")])
    monkeypatch.setattr(core_module, "nyaa_client", nyaa)

    await CoreSearchService().generic_search(
        "Kingdom",
        limit=10,
        categories=[TORZNAB_CATEGORY_LIVE_ACTION_ENGLISH],
    )

    assert nyaa.search_calls == [
        {
            "query": "Kingdom",
            "limit": 10,
            "categories": [TORZNAB_CATEGORY_LIVE_ACTION_ENGLISH],
        }
    ]


@pytest.mark.asyncio
async def test_nyaa_multi_category_search_calls_each_category(monkeypatch):
    """Selected categories should fan out to one Nyaa request per category."""
    client = NyaaClient()
    calls = []

    async def fake_search_category(query, category, filter_code, limit):
        calls.append((query, category, filter_code, limit))
        return []

    monkeypatch.setattr(client, "_search_category", fake_search_category)

    await client.search(
        "Kingdom", limit=25, categories=[5070, TORZNAB_CATEGORY_LIVE_ACTION_ENGLISH]
    )

    assert [call[1] for call in calls] == ["1_2", "4_1"]
    assert all(call[0] == "Kingdom" for call in calls)
    assert all(call[3] == 25 for call in calls)


@pytest.mark.asyncio
async def test_nyaa_multi_category_search_dedupes_by_info_hash(monkeypatch):
    """Duplicate info hashes across categories should keep the best-ranked result."""
    client = NyaaClient()
    lower = make_result(
        "Live Action lower",
        guid="https://nyaa.si/view/lower",
        info_hash="same-hash",
        seeders=2,
    )
    higher = make_result(
        "Live Action higher",
        guid="https://nyaa.si/view/higher",
        info_hash="same-hash",
        seeders=9,
    )

    async def fake_search_category(query, category, filter_code, limit):
        return [lower] if category == "1_2" else [higher]

    monkeypatch.setattr(client, "_search_category", fake_search_category)

    results = await client.search(
        "Kingdom", limit=25, categories=[5070, TORZNAB_CATEGORY_LIVE_ACTION_ENGLISH]
    )

    assert results == [higher]


@pytest.mark.asyncio
async def test_nyaa_multi_category_search_dedupes_by_guid(monkeypatch):
    """Duplicate GUIDs should be deduped when no info hash is available."""
    client = NyaaClient()
    older = make_result(
        "Older same guid",
        guid="https://nyaa.si/view/same",
        pub_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        seeders=4,
    )
    newer = make_result(
        "Newer same guid",
        guid="https://nyaa.si/view/same",
        pub_date=datetime(2026, 1, 2, tzinfo=timezone.utc),
        seeders=4,
    )

    async def fake_search_category(query, category, filter_code, limit):
        return [older] if category == "1_2" else [newer]

    monkeypatch.setattr(client, "_search_category", fake_search_category)

    results = await client.search(
        "Kingdom", limit=25, categories=[5070, TORZNAB_CATEGORY_LIVE_ACTION_ENGLISH]
    )

    assert results == [newer]


@pytest.mark.asyncio
async def test_nyaa_multi_category_search_sorts_and_limits_after_merge(monkeypatch):
    """Final limit should apply after all category results are merged and ranked."""
    client = NyaaClient()
    low = make_result("Low", guid="https://nyaa.si/view/low", seeders=1)
    high = make_result("High", guid="https://nyaa.si/view/high", seeders=20)
    mid = make_result("Mid", guid="https://nyaa.si/view/mid", seeders=10)

    async def fake_search_category(query, category, filter_code, limit):
        return [low, high] if category == "1_2" else [mid]

    monkeypatch.setattr(client, "_search_category", fake_search_category)

    results = await client.search(
        "Kingdom", limit=2, categories=[5070, TORZNAB_CATEGORY_LIVE_ACTION_ENGLISH]
    )

    assert results == [high, mid]


def test_torznab_renderer_includes_expected_metadata_attrs():
    """Renderer should preserve Torznab attrs expected by Sonarr and Radarr."""
    result = make_result(
        "Suzume (2022) [1080p][BDRip] -SubsPlease",
        guid="https://nyaa.si/view/916224",
        info_hash="abc123",
        categories=[2000, 2060],
    )

    xml = TorznabRenderer().render(
        [result],
        tvdb_id=12345,
        season=1,
        episode=2,
        tmdb_id=916224,
        imdb_id="tt16428256",
        year=2022,
    )

    root = ET.fromstring(xml)
    attrs = {
        attr.attrib["name"]: attr.attrib["value"]
        for attr in root.findall(f".//{{{TORZNAB_NS}}}attr")
    }
    categories = [
        attr.attrib["value"]
        for attr in root.findall(f".//{{{TORZNAB_NS}}}attr")
        if attr.attrib["name"] == "category"
    ]

    assert attrs["size"] == "1024"
    assert attrs["seeders"] == "10"
    assert attrs["peers"] == "11"
    assert attrs["downloadvolumefactor"] == "1"
    assert attrs["uploadvolumefactor"] == "1"
    assert attrs["infohash"] == "abc123"
    assert categories == ["2000", "2060"]
    assert attrs["tvdbid"] == "12345"
    assert attrs["season"] == "1"
    assert attrs["episode"] == "2"
    assert attrs["tmdbid"] == "916224"
    assert attrs["imdbid"] == "tt16428256"
    assert attrs["year"] == "2022"
    assert attrs["language"] == "English"


def test_torznab_caps_exposes_live_action_category():
    """Caps should expose selectable category metadata to indexer clients."""
    root = ET.fromstring(TorznabRenderer().caps())
    live_action = root.find(
        ".//category[@id='5000']/subcat[@id='100041'][@name='Live Action/English-translated']"
    )
    tv_search = root.find(".//tv-search")

    assert live_action is not None
    assert tv_search is not None
    assert "cat" in tv_search.attrib["supportedParams"].split(",")
