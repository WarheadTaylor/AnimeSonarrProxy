"""Episode number translation between seasonal and absolute numbering."""
import logging
from typing import Optional, Dict
from app.models import AnimeMapping, MappingOverride
from app.services.thexem import thexem_client

logger = logging.getLogger(__name__)


class EpisodeTranslator:
    """Translates between S##E## and absolute episode numbering."""

    def __init__(self, mapping_service):
        self.mapping_service = mapping_service
        self.thexem = thexem_client

    async def to_absolute(
        self,
        mapping: AnimeMapping,
        season: int,
        episode: int
    ) -> Optional[int]:
        """
        Convert season/episode to absolute episode number.

        Priority:
        1. User override
        2. TheXEM mapping (TVDB -> AniDB)
        3. season_info metadata
        4. Fallback calculation

        Args:
            mapping: The anime mapping with season info
            season: Season number (1-indexed)
            episode: Episode number within season (1-indexed)

        Returns:
            Absolute episode number or None if cannot determine
        """
        # Check for user override first
        if mapping.user_override:
            override = self.mapping_service.overrides.get(mapping.tvdb_id)
            if override:
                override_key = f"S{season:02d}E{episode:02d}"
                if override_key in override.season_episode_overrides:
                    absolute = override.season_episode_overrides[override_key]
                    logger.info(f"Using override: {override_key} -> {absolute}")
                    return absolute

        # Try TheXEM first - most accurate source for anime
        try:
            xem_absolute = await self.thexem.tvdb_to_anidb_episode(
                mapping.tvdb_id,
                season,
                episode
            )
            if xem_absolute:
                logger.info(f"Using TheXEM mapping for TVDB {mapping.tvdb_id} S{season:02d}E{episode:02d} -> {xem_absolute}")
                return xem_absolute
        except Exception as e:
            logger.warning(f"TheXEM lookup failed: {e}")

        # If we have season_info, use it
        if mapping.season_info:
            absolute = self._calculate_from_season_info(mapping.season_info, season, episode)
            if absolute:
                return absolute

        # Fallback: Simple calculation assuming continuous numbering
        if season == 1:
            # First season, absolute = episode
            return episode
        elif mapping.total_episodes > 0:
            # Try to estimate based on total episodes
            # This is a simplification - in reality we'd need more metadata
            logger.warning(f"Using simplified calculation for TVDB {mapping.tvdb_id} S{season:02d}E{episode:02d}")
            # Assume 12-13 episodes per season (common anime pattern)
            estimated_eps_per_season = 12
            absolute = ((season - 1) * estimated_eps_per_season) + episode
            return absolute
        else:
            # No season info and no total episodes - just try the episode number
            logger.warning(f"No season info available for TVDB {mapping.tvdb_id}, using episode as absolute")
            return episode

    def _calculate_from_season_info(
        self,
        season_info: list,
        target_season: int,
        target_episode: int
    ) -> Optional[int]:
        """Calculate absolute episode from season info list."""
        absolute = 0

        for season_data in sorted(season_info, key=lambda x: x.get('season', 0)):
            season_num = season_data.get('season', 0)
            episode_count = season_data.get('episodes', 0)

            if season_num < target_season:
                # Add all episodes from previous seasons
                absolute += episode_count
            elif season_num == target_season:
                # Add the target episode
                if target_episode <= episode_count:
                    absolute += target_episode
                    return absolute
                else:
                    logger.warning(
                        f"Episode {target_episode} exceeds season {target_season} "
                        f"episode count ({episode_count})"
                    )
                    return None
            else:
                # We've passed the target season
                break

        return None

    def format_episode_queries(self, absolute_episode: int) -> list[str]:
        """
        Generate different episode number formats for searching.

        Args:
            absolute_episode: Absolute episode number

        Returns:
            List of formatted episode strings to try
        """
        formats = [
            f"{absolute_episode}",  # "28"
            f"{absolute_episode:02d}",  # "28" or "05"
            f"- {absolute_episode}",  # "- 28" (common in releases)
            f"- {absolute_episode:02d}",  # "- 05"
        ]

        return formats


# This will be initialized with mapping_service in main.py
episode_translator = None


def get_episode_translator():
    """Get the global episode translator instance."""
    return episode_translator
