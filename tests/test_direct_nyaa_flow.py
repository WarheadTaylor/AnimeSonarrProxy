"""Regression coverage for the direct Nyaa search and Torznab rendering flow."""

from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import pytest

from app.api import torznab as torznab_module
from app.api.torznab import parse_categories
from app.models import SearchResult
from app.models import SeriesMetadata
from app.services import core as core_module
from app.services import metadata as metadata_module
from app.services import tvmaze as tvmaze_module
from app.services.core import CoreSearchService
from app.services.metadata import MetadataResolver, MovieSearchContext, TvSearchContext
from app.services.nyaa import NyaaClient
from app.services.nyaa import NYAA_CATEGORY_LIVE_ACTION_ENGLISH
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


class FakeSpecialMetadataResolver:
    """Fake metadata resolver returning a fixed TV special context."""

    async def resolve_tv(self, tvdb_id, season, episode, is_live_action=False):
        """Return a special context with a Sonarr episode title."""
        return TvSearchContext(
            tvdb_id=tvdb_id,
            season=season,
            episode=episode,
            absolute_episode=episode,
            episode_title="The Path to Victory",
            search_titles=["Uma Musume"],
            returned_title="Uma Musume",
            is_special=True,
            is_live_action=is_live_action,
        )


class FakeAnimeDb:
    """Fake anime database with no live-action mappings."""

    data = {"data": []}

    def get_by_tvdb_id(self, tvdb_id):
        """Return no anime mapping for live-action series."""
        return None


class FakeSonarrClient:
    """Fake Sonarr client exposing series metadata without episode metadata."""

    def is_configured(self):
        """Return enabled integration."""
        return True

    async def get_episode_by_season_episode(self, tvdb_id, season, episode):
        """Simulate an episode lookup miss."""
        return None

    async def get_series_metadata_by_tvdb_id(self, tvdb_id):
        """Return canonical Sonarr series metadata."""
        return SeriesMetadata(
            tvdb_id=tvdb_id,
            tvmaze_id=123,
            imdb_id="tt1234567",
            title="The Flowers of Evil",
            alternate_titles=["Flowers of Evil"],
            year=2026,
            source="sonarr",
        )


class FakeTMDbClient:
    """Fake disabled TMDb client."""

    def is_configured(self):
        """Return disabled TMDb integration."""
        return False


class FakeTVmazeClient:
    """Fake TVmaze client returning a live-action alias."""

    async def get_show(self, tvmaze_id):
        """Return TVmaze metadata by direct ID."""
        return SeriesMetadata(
            tvdb_id=470866,
            tvmaze_id=tvmaze_id,
            title="The Flowers of Evil",
            alternate_titles=["Aku no Hana"],
            year=2026,
            source="tvmaze",
        )

    async def lookup_by_tvdb_id(self, tvdb_id):
        """Return no lookup fallback result."""
        return None

    async def lookup_by_imdb_id(self, imdb_id):
        """Return no IMDb fallback result."""
        return None


class MissingTVmazeClient(FakeTVmazeClient):
    """Fake TVmaze miss for fallback coverage."""

    async def get_show(self, tvmaze_id):
        """Return no direct TVmaze result."""
        return None


class FakeTVmazeResponse:
    """Fake successful TVmaze API response."""

    status_code = 200

    def raise_for_status(self):
        """No-op for successful fake responses."""

    def json(self):
        """Return minimal show metadata."""
        return {
            "name": "The Flowers of Evil",
            "externals": {"thetvdb": 470866},
            "premiered": "2026-04-04",
        }


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
async def test_special_tv_search_includes_episode_title_keyword(monkeypatch):
    """Sonarr special episode titles should be included in Nyaa special searches."""
    nyaa = RecordingNyaaClient([])
    monkeypatch.setattr(core_module, "metadata_resolver", FakeSpecialMetadataResolver())
    monkeypatch.setattr(core_module, "nyaa_client", nyaa)

    await CoreSearchService().tv_search(12345, 0, 1, limit=25, categories=[5070])

    assert nyaa.search_multi_calls == [
        {
            "titles": ["Uma Musume"],
            "episodes": [1],
            "keywords": ["OVA", "OAD", "Special", "The Path to Victory"],
            "limit": 25,
            "categories": [5070],
        }
    ]


def test_special_release_can_match_by_episode_title_without_special_keyword():
    """Special releases may be named with the episode title instead of OVA/Special."""
    result = make_result("[SubsPlease] Uma Musume - The Path to Victory [1080p]")
    context = TvSearchContext(
        tvdb_id=12345,
        season=0,
        episode=1,
        absolute_episode=1,
        episode_title="The Path to Victory",
        search_titles=["Uma Musume"],
        returned_title="Uma Musume",
        is_special=True,
    )

    matched = release_matcher.match_tv(result, context)

    assert matched is not None
    assert matched.title.startswith("[SubsPlease] Uma Musume - S00E01 - 1")


@pytest.mark.asyncio
async def test_live_action_resolve_tv_uses_sonarr_series_when_anime_db_misses(
    monkeypatch,
):
    """Live-action TVDB lookups should use Sonarr title even without episode data."""
    monkeypatch.setattr(metadata_module, "anime_db", FakeAnimeDb())
    monkeypatch.setattr(metadata_module, "sonarr_client", FakeSonarrClient())
    monkeypatch.setattr(metadata_module, "tmdb_client", FakeTMDbClient())
    monkeypatch.setattr(metadata_module, "tvmaze_client", MissingTVmazeClient())

    context = await MetadataResolver().resolve_tv(
        470866, 1, 1, is_live_action=True
    )

    assert context is not None
    assert context.returned_title == "The Flowers of Evil"
    assert context.search_titles[:2] == ["The Flowers of Evil", "Flowers of Evil"]
    assert context.absolute_episode is None
    assert context.is_live_action is True


@pytest.mark.asyncio
async def test_live_action_resolve_tv_includes_tvmaze_alias(monkeypatch):
    """External drama metadata aliases should be added to searchable titles."""
    monkeypatch.setattr(metadata_module, "anime_db", FakeAnimeDb())
    monkeypatch.setattr(metadata_module, "sonarr_client", FakeSonarrClient())
    monkeypatch.setattr(metadata_module, "tmdb_client", FakeTMDbClient())
    monkeypatch.setattr(metadata_module, "tvmaze_client", FakeTVmazeClient())

    context = await MetadataResolver().resolve_tv(
        470866, 1, 1, is_live_action=True
    )

    assert context is not None
    assert "Aku no Hana" in context.search_titles


@pytest.mark.asyncio
async def test_tvmaze_lookup_follows_redirects(monkeypatch):
    """TVmaze lookup endpoints redirect to show URLs and should be followed."""
    async_client_kwargs = []

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            async_client_kwargs.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url, params=None):
            return FakeTVmazeResponse()

    monkeypatch.setattr(tvmaze_module.httpx, "AsyncClient", FakeAsyncClient)

    metadata = await tvmaze_module.TVmazeClient().lookup_by_tvdb_id(470866)

    assert metadata is not None
    assert metadata.title == "The Flowers of Evil"
    assert async_client_kwargs[0]["follow_redirects"] is True


def test_live_action_ep01_alias_matches_and_returns_pipe_separated_title():
    """Alias-only Nyaa titles should include canonical and alias titles."""
    result = make_result(
        "[MagicStar] Aku no Hana EP01 [WEBDL] [1080p] [DSNP] [JPN_ENG_CHT_SUB]"
    )
    context = TvSearchContext(
        tvdb_id=470866,
        season=1,
        episode=1,
        absolute_episode=None,
        search_titles=["The Flowers of Evil", "Aku no Hana"],
        returned_title="The Flowers of Evil",
        is_live_action=True,
    )

    matched = release_matcher.match_tv(result, context)

    assert matched is not None
    assert matched.title.startswith(
        "[MagicStar] The Flowers of Evil | Aku no Hana - S01E01"
    )
    assert "Aku no Hana EP01" not in matched.title
    assert matched.original_title == result.title


def test_live_action_canonical_title_match_does_not_duplicate_name():
    """Canonical live-action matches should not render duplicate pipe titles."""
    result = make_result(
        "The.Flowers.of.Evil.2026.S01E01.1080p.DSNP.WEB-DL.AAC2.0.H.264-VARYG"
    )
    context = TvSearchContext(
        tvdb_id=470866,
        season=1,
        episode=1,
        absolute_episode=None,
        search_titles=["The Flowers of Evil", "Aku no Hana"],
        returned_title="The Flowers of Evil",
        is_live_action=True,
    )

    matched = release_matcher.match_tv(result, context)

    assert matched is not None
    assert matched.title.startswith("[VARYG] The Flowers of Evil - S01E01")
    assert "The Flowers of Evil | The Flowers of Evil" not in matched.title


def test_live_action_ep11_alias_does_not_match_requested_ep01():
    """Episode-only live-action releases should reject the wrong episode number."""
    result = make_result(
        "[MagicStar] Aku no Hana EP11 [WEBDL] [1080p] [DSNP] [JPN_ENG_CHT_SUB]"
    )
    context = TvSearchContext(
        tvdb_id=470866,
        season=1,
        episode=1,
        absolute_episode=None,
        search_titles=["The Flowers of Evil", "Aku no Hana"],
        returned_title="The Flowers of Evil",
        is_live_action=True,
    )

    assert release_matcher.match_tv(result, context) is None


def test_live_action_episode_only_release_without_title_does_not_match():
    """EPxx-only releases should not match just because the episode number matches."""
    result = make_result("[MagicStar] EP01 [WEBDL] [1080p] [DSNP]")
    context = TvSearchContext(
        tvdb_id=470866,
        season=1,
        episode=1,
        absolute_episode=None,
        search_titles=["The Flowers of Evil", "Aku no Hana"],
        returned_title="The Flowers of Evil",
        is_live_action=True,
    )

    assert release_matcher.match_tv(result, context) is None


def test_live_action_s01e01_matches_and_s01e10_does_not():
    """Seasonal live-action releases should match both requested season and episode."""
    context = TvSearchContext(
        tvdb_id=470866,
        season=1,
        episode=1,
        absolute_episode=None,
        search_titles=["The Flowers of Evil", "Aku no Hana"],
        returned_title="The Flowers of Evil",
        is_live_action=True,
    )

    matching = make_result(
        "The.Flowers.of.Evil.2026.S01E01.1080p.DSNP.WEB-DL.AAC2.0.H.264-VARYG"
    )
    wrong_episode = make_result(
        "The Flowers of Evil 2026 S01E10 1080p DSNP WEB-DL AAC2.0 H 264-VARYG"
    )

    assert release_matcher.match_tv(matching, context) is not None
    assert release_matcher.match_tv(wrong_episode, context) is None


def test_live_action_rejects_wrong_year_when_release_has_year():
    """Live-action matches should reject parsed years from a different production."""
    context = TvSearchContext(
        tvdb_id=470866,
        season=1,
        episode=1,
        absolute_episode=None,
        search_titles=["The Flowers of Evil", "Aku no Hana"],
        returned_title="The Flowers of Evil",
        is_live_action=True,
        year=2026,
    )
    wrong_year = make_result("The Flowers of Evil 2013 S01E01 1080p WEB-DL")

    assert release_matcher.match_tv(wrong_year, context) is None


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


@pytest.mark.asyncio
async def test_generic_live_action_search_filters_episode_only_mismatches(
    monkeypatch,
):
    """Live-action generic searches should not keep wrong EPxx releases."""
    ep01 = make_result(
        "[MagicStar] Aku no Hana EP01 [WEBDL] [1080p] [DSNP]",
        guid="https://nyaa.si/view/ep01",
        seeders=10,
    )
    ep11 = make_result(
        "[MagicStar] Aku no Hana EP11 [WEBDL] [1080p] [DSNP]",
        guid="https://nyaa.si/view/ep11",
        seeders=100,
    )
    s01e01 = make_result(
        "The.Flowers.of.Evil.2026.S01E01.1080p.DSNP.WEB-DL",
        guid="https://nyaa.si/view/s01e01",
        seeders=20,
    )
    s01e10 = make_result(
        "The Flowers of Evil 2026 S01E10 1080p DSNP WEB-DL",
        guid="https://nyaa.si/view/s01e10",
        seeders=90,
    )
    nyaa = RecordingNyaaClient([ep11, s01e10, ep01, s01e01])
    monkeypatch.setattr(core_module, "nyaa_client", nyaa)

    results = await CoreSearchService().generic_search(
        "Flowers of Evil",
        limit=10,
        season=1,
        episode=1,
        categories=[TORZNAB_CATEGORY_LIVE_ACTION_ENGLISH],
    )

    assert [result.guid for result in results] == [
        "https://nyaa.si/view/s01e01",
        "https://nyaa.si/view/ep01",
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


def test_parser_extracts_live_action_episode_formats():
    """Live-action EPxx and SxxEyy titles should parse without year confusion."""
    ep_release = release_parser.parse(
        "[MagicStar] Aku no Hana EP01 [WEBDL] [1080p] [DSNP]"
    )
    dotted_release = release_parser.parse(
        "The.Flowers.of.Evil.2026.S01E01.1080p.DSNP.WEB-DL"
    )
    spaced_release = release_parser.parse(
        "The Flowers of Evil 2026 S01E01 1080p DSNP WEB-DL"
    )

    assert ep_release.episode_numbers == [1]
    assert ep_release.season_numbers == []
    assert dotted_release.season_numbers == [1]
    assert dotted_release.episode_numbers == [1]
    assert dotted_release.year == 2026
    assert 2026 not in dotted_release.episode_numbers
    assert spaced_release.season_numbers == [1]
    assert spaced_release.episode_numbers == [1]
    assert spaced_release.year == 2026
    assert 2026 not in spaced_release.episode_numbers


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


def test_nyaa_combined_query_quotes_multi_word_special_title_keyword():
    """Episode-title special keywords should be searched as phrases."""
    query = NyaaClient().build_combined_query(
        ["Uma Musume"],
        episodes=[1],
        keywords=["OVA", "OAD", "Special", "The Path to Victory"],
    )

    assert query == '"Uma Musume" (OVA|OAD|Special|"The Path to Victory") 1'


def test_nyaa_rss_live_action_category_maps_to_torznab_live_action():
    """Nyaa live-action RSS items should render with the live-action Torznab category."""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:nyaa="https://nyaa.si/xmlns/nyaa">
    <channel>
        <item>
            <title>[MagicStar] Aku no Hana EP01 [WEBDL] [1080p] [DSNP]</title>
            <guid>https://nyaa.si/view/1</guid>
            <link>https://nyaa.si/download/1.torrent</link>
            <pubDate>Tue, 09 Sep 2025 20:24:10 -0000</pubDate>
            <nyaa:seeders>5</nyaa:seeders>
            <nyaa:leechers>2</nyaa:leechers>
            <nyaa:size>1.0 GiB</nyaa:size>
            <nyaa:categoryId>{NYAA_CATEGORY_LIVE_ACTION_ENGLISH}</nyaa:categoryId>
            <nyaa:infoHash>ABC123</nyaa:infoHash>
            <nyaa:trusted>No</nyaa:trusted>
            <nyaa:remake>No</nyaa:remake>
        </item>
    </channel>
</rss>"""

    results = NyaaClient()._parse_rss_response(xml)

    assert len(results) == 1
    assert results[0].categories == [TORZNAB_CATEGORY_LIVE_ACTION_ENGLISH]


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


@pytest.mark.asyncio
async def test_search_multi_retries_individual_titles_when_combined_query_is_empty(
    monkeypatch,
):
    """Nyaa can return no rows for quoted OR queries even when single aliases match."""
    client = NyaaClient()
    magicstar = make_result(
        "[MagicStar] Aku no Hana EP01 [WEBDL] [1080p] [DSNP]",
        guid="https://nyaa.si/view/magicstar",
        seeders=24,
    )
    calls = []

    async def fake_search(query, limit=None, categories=None):
        calls.append((query, limit, categories))
        if query == "Aku no Hana":
            return [magicstar]
        return []

    monkeypatch.setattr(client, "search", fake_search)

    results = await client.search_multi(
        ["The Flowers of Evil", "Aku no Hana"],
        limit=100,
        categories=[TORZNAB_CATEGORY_LIVE_ACTION_ENGLISH],
    )

    assert results == [magicstar]
    assert calls == [
        (
            '("The Flowers of Evil"|"Aku no Hana")',
            100,
            [TORZNAB_CATEGORY_LIVE_ACTION_ENGLISH],
        ),
        ("The Flowers of Evil", 100, [TORZNAB_CATEGORY_LIVE_ACTION_ENGLISH]),
        ("Aku no Hana", 100, [TORZNAB_CATEGORY_LIVE_ACTION_ENGLISH]),
    ]


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
