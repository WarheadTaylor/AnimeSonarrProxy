"""Resolve manager requests into search contexts for Nyaa."""

import logging
from dataclasses import dataclass
from typing import Optional

from app.services.anime_db import anime_db
from app.services.radarr import radarr_client
from app.services.sonarr import sonarr_client
from app.services.thexem import thexem_client

logger = logging.getLogger(__name__)


@dataclass
class TvSearchContext:
    """Resolved metadata for a Sonarr episode search."""

    tvdb_id: int
    season: int
    episode: int
    absolute_episode: Optional[int]
    search_titles: list[str]
    returned_title: str
    is_special: bool = False


@dataclass
class MovieSearchContext:
    """Resolved metadata for a Radarr movie search."""

    search_titles: list[str]
    returned_title: str
    year: Optional[int] = None
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None


class MetadataResolver:
    """Resolves Sonarr and Radarr identifiers into Nyaa search metadata."""

    async def resolve_tv(
        self, tvdb_id: int, season: int, episode: int
    ) -> Optional[TvSearchContext]:
        """Resolve a TVDB season/episode request."""
        episode_info = None
        if sonarr_client.is_configured():
            episode_info = await sonarr_client.get_episode_by_season_episode(
                tvdb_id, season, episode
            )

        anime = anime_db.get_by_tvdb_id(tvdb_id)
        titles = self._titles_from_anime(anime) if anime else []
        if episode_info and episode_info.series_title:
            titles = self._prepend_unique(titles, episode_info.series_title)

        if not titles:
            logger.warning("TVDB %s could not be resolved to search titles", tvdb_id)
            return None

        absolute_episode = (
            episode_info.absolute_episode_number if episode_info else None
        ) or await self._absolute_episode(tvdb_id, season, episode)

        if absolute_episode is None and season == 1:
            absolute_episode = episode

        if absolute_episode is None and season != 0:
            logger.warning(
                "TVDB %s S%02dE%02d has no confident absolute episode",
                tvdb_id,
                season,
                episode,
            )
            return None

        return TvSearchContext(
            tvdb_id=tvdb_id,
            season=season,
            episode=episode,
            absolute_episode=absolute_episode,
            search_titles=titles[:4],
            returned_title=episode_info.series_title if episode_info else titles[0],
            is_special=season == 0 or bool(episode_info and episode_info.is_special),
        )

    async def resolve_movie(
        self,
        tmdb_id: Optional[int],
        imdb_id: Optional[str],
        query: Optional[str],
        year: Optional[int],
    ) -> Optional[MovieSearchContext]:
        """Resolve a Radarr movie request."""
        if imdb_id and not imdb_id.startswith("tt"):
            imdb_id = f"tt{imdb_id}"

        movie_info = None
        if tmdb_id and radarr_client.is_configured():
            movie_info = await radarr_client.get_movie_by_tmdb_id(tmdb_id)
        elif imdb_id and radarr_client.is_configured():
            movie_info = await radarr_client.get_movie_by_imdb_id(imdb_id)

        anime = anime_db.get_by_tmdb_id(tmdb_id) if tmdb_id else None
        if anime is None and imdb_id:
            anime = self._anime_by_imdb_id(imdb_id)

        titles = self._titles_from_anime(anime) if anime else []
        if movie_info:
            titles = self._prepend_unique(
                titles,
                movie_info.title,
                movie_info.original_title,
                *movie_info.alternative_titles,
            )
            year = year or movie_info.year
            tmdb_id = tmdb_id or movie_info.tmdb_id
            imdb_id = imdb_id or movie_info.imdb_id

        if anime:
            year = year or anime.get("animeSeason", {}).get("year")

        if query:
            titles = self._prepend_unique(titles, query)

        if not titles:
            logger.warning("Movie request could not be resolved to search titles")
            return None

        return MovieSearchContext(
            search_titles=titles[:4],
            returned_title=movie_info.title if movie_info else titles[0],
            year=year,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
        )

    async def _absolute_episode(
        self, tvdb_id: int, season: int, episode: int
    ) -> Optional[int]:
        if season == 0:
            return episode
        try:
            return await thexem_client.tvdb_to_anidb_episode(tvdb_id, season, episode)
        except Exception as exc:
            logger.warning("TheXEM episode lookup failed for TVDB %s: %s", tvdb_id, exc)
            return None

    def _anime_by_imdb_id(self, imdb_id: str) -> Optional[dict]:
        for anime in anime_db.data.get("data", []):
            if any(
                f"imdb.com/title/{imdb_id}" in source
                for source in anime.get("sources", [])
            ):
                return anime
        return None

    def _titles_from_anime(self, anime: Optional[dict]) -> list[str]:
        if not anime:
            return []
        return self._dedupe(
            title
            for title in anime_db.get_all_titles(anime)
            if self._is_searchable(title)
        )

    def _prepend_unique(
        self, titles: list[str], *candidates: Optional[str]
    ) -> list[str]:
        merged = [candidate for candidate in candidates if candidate]
        merged.extend(titles)
        return self._dedupe(merged)

    def _dedupe(self, titles) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for title in titles:
            cleaned = " ".join(str(title).split())
            key = cleaned.casefold()
            if cleaned and key not in seen:
                seen.add(key)
                unique.append(cleaned)
        return unique

    def _is_searchable(self, title: str) -> bool:
        letters = [char for char in title if char.isalpha()]
        if not letters:
            return True
        latin = sum(1 for char in letters if "A" <= char.upper() <= "Z")
        return latin / len(letters) >= 0.5


metadata_resolver = MetadataResolver()
