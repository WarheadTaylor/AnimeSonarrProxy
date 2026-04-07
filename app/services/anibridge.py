"""AniBridge mappings handler for offline cross-database lookups."""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class AniBridgeMappings:
    """Handles AniBridge mapping dataset download and TVDB lookup indexes."""

    def __init__(self):
        self.db_path = settings.DATA_DIR / "anibridge-mappings.json"
        self.data: Dict[str, Dict[str, Dict[str, str]]] = {}
        self.last_update: Optional[datetime] = None
        self._tvdb_index: Dict[int, Dict[str, int]] = {}
        self._tvdb_index_priority: Dict[int, Dict[str, int]] = {}
        self._tvdb_scoped_index: Dict[Tuple[int, Optional[str]], Dict[str, int]] = {}
        self._tvdb_episode_targets: Dict[
            Tuple[int, Optional[str]], Dict[str, List[Tuple[range, str]]]
        ] = {}

    async def initialize(self) -> None:
        """Initialize mappings database from local cache or remote source."""
        if self.db_path.exists():
            await self._load_from_file()
            if self._needs_update():
                await self.update_database()
        else:
            await self.update_database()

    def _needs_update(self) -> bool:
        """Check whether the cached dataset should be refreshed."""
        if not self.last_update:
            return True

        elapsed = datetime.utcnow() - self.last_update
        return elapsed.total_seconds() > settings.ANIBRIDGE_UPDATE_INTERVAL

    async def update_database(self) -> None:
        """Download the latest AniBridge mappings release."""
        logger.info(
            f"Downloading AniBridge mappings from {settings.ANIBRIDGE_MAPPINGS_URL}"
        )
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                response = await client.get(settings.ANIBRIDGE_MAPPINGS_URL)
                response.raise_for_status()

                self.data = response.json()

                settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
                with open(self.db_path, "w", encoding="utf-8") as file_handle:
                    json.dump(self.data, file_handle, ensure_ascii=False, indent=2)

                self.last_update = datetime.utcnow()
                self._build_tvdb_index()
                logger.info(
                    f"Loaded AniBridge mappings with {len(self._tvdb_index)} TVDB entries"
                )
        except Exception as exc:
            logger.error(f"Failed to update AniBridge mappings: {exc}")
            if not self.data and self.db_path.exists():
                await self._load_from_file()

    async def _load_from_file(self) -> None:
        """Load AniBridge mappings from local file."""
        try:
            with open(self.db_path, "r", encoding="utf-8") as file_handle:
                self.data = json.load(file_handle)

            self.last_update = datetime.fromtimestamp(self.db_path.stat().st_mtime)
            self._build_tvdb_index()
            logger.info(
                f"Loaded AniBridge mappings with {len(self._tvdb_index)} TVDB entries"
            )
        except Exception as exc:
            logger.error(f"Failed to load AniBridge mappings: {exc}")
            self.data = {}
            self._tvdb_index = {}
            self._tvdb_index_priority = {}
            self._tvdb_scoped_index = {}
            self._tvdb_episode_targets = {}

    def _build_tvdb_index(self) -> None:
        """Build TVDB indexes for ID lookups and episode translation."""
        self._tvdb_index = {}
        self._tvdb_index_priority = {}
        self._tvdb_scoped_index = {}
        self._tvdb_episode_targets = {}

        for descriptor, targets in self.data.items():
            parsed_descriptor = self._parse_descriptor(descriptor)
            if not parsed_descriptor:
                continue

            provider, raw_id, scope = parsed_descriptor
            if provider != "tvdb_show":
                continue

            scoped_entry = self._tvdb_scoped_index.setdefault((raw_id, scope), {})
            entry = self._tvdb_index.setdefault(raw_id, {})
            entry_priority = self._tvdb_index_priority.setdefault(raw_id, {})

            for target_descriptor in targets:
                parsed_target = self._parse_descriptor(target_descriptor)
                if not parsed_target:
                    continue

                target_provider, target_id, _ = parsed_target
                if target_provider in {"anidb", "anilist", "mal"}:
                    scoped_entry[f"{target_provider}_id"] = target_id
                    self._set_preferred_id(
                        entry, entry_priority, target_provider, target_id, scope
                    )

                if target_provider not in {"anidb", "anilist", "mal"}:
                    continue

                target_ranges = self._build_target_ranges(targets[target_descriptor])
                if target_ranges:
                    episode_targets = self._tvdb_episode_targets.setdefault(
                        (raw_id, scope), {}
                    )
                    episode_targets[target_provider] = target_ranges

    def get_ids_by_tvdb_id(self, tvdb_id: int) -> Optional[Dict[str, int]]:
        """Get AniBridge-linked anime IDs for a TVDB show."""
        return self._tvdb_index.get(tvdb_id)

    def get_ids_by_tvdb_scope(
        self, tvdb_id: int, season: int
    ) -> Optional[Dict[str, int]]:
        """Get AniBridge-linked anime IDs for a TVDB show season."""
        scope = self._season_to_scope(season)
        scoped = self._tvdb_scoped_index.get((tvdb_id, scope))
        if scoped:
            return scoped

        if season > 0:
            return self._tvdb_index.get(tvdb_id)

        return None

    def map_tvdb_episode(
        self, tvdb_id: int, season: int, episode: int, target_provider: str = "anidb"
    ) -> Optional[int]:
        """Map a TVDB season/episode to a target provider episode number."""
        scope = self._season_to_scope(season)
        targets = self._tvdb_episode_targets.get((tvdb_id, scope), {})
        mappings = targets.get(target_provider, [])

        for source_range, target_range in mappings:
            if episode not in source_range:
                continue

            translated = self._map_episode_with_range(
                source_range, target_range, episode
            )
            if translated is not None:
                return translated

        return None

    def _build_target_ranges(
        self, source_to_target: Dict[str, Optional[str]]
    ) -> List[Tuple[range, str]]:
        """Parse AniBridge source-to-target range mappings."""
        parsed_ranges: List[Tuple[range, str]] = []

        for source_range, target_range in source_to_target.items():
            if not target_range:
                continue

            parsed_source = self._parse_source_range(source_range)
            if not parsed_source:
                continue

            parsed_ranges.append((parsed_source, target_range))

        parsed_ranges.sort(
            key=lambda item: (item[0].start, item[0].stop - item[0].start)
        )
        return parsed_ranges

    def _set_preferred_id(
        self,
        entry: Dict[str, int],
        entry_priority: Dict[str, int],
        provider: str,
        target_id: int,
        scope: Optional[str],
    ) -> None:
        """Prefer season 1 IDs, then regular seasons, then specials."""
        key = f"{provider}_id"
        priority = self._scope_priority(scope)
        if key not in entry or priority > entry_priority.get(key, -1):
            entry[key] = target_id
            entry_priority[key] = priority

    def _scope_priority(self, scope: Optional[str]) -> int:
        """Rank scopes so global ID fallbacks prefer regular seasons."""
        if scope == "s1":
            return 3
        if scope and scope.startswith("s") and scope[1:].isdigit() and scope != "s0":
            return 2
        if scope is None:
            return 1
        return 0

    def _parse_source_range(self, source_range: str) -> Optional[range]:
        """Parse a source range into a Python range."""
        if "-" not in source_range:
            if not source_range.isdigit():
                return None
            episode_num = int(source_range)
            return range(episode_num, episode_num + 1)

        start_str, end_str = source_range.split("-", 1)
        if not start_str.isdigit():
            return None

        start = int(start_str)
        if end_str == "":
            return range(start, 10**9)
        if not end_str.isdigit():
            return None

        end = int(end_str)
        return range(start, end + 1)

    def _map_episode_with_range(
        self, source_range: range, target_range: str, source_episode: int
    ) -> Optional[int]:
        """Translate one source episode using a target range expression."""
        segments, ratio = self._split_target_range(target_range)
        if not segments:
            return None

        source_offset = source_episode - source_range.start

        if ratio is None or ratio == 1:
            return self._map_contiguous_segments(segments, source_offset)

        if ratio > 1:
            return self._map_positive_ratio(segments, source_offset, ratio)

        return self._map_negative_ratio(segments, source_offset, abs(ratio))

    def _split_target_range(
        self, target_range: str
    ) -> Tuple[List[Tuple[int, Optional[int]]], Optional[int]]:
        """Split a target range into segments and ratio."""
        ratio = None
        range_part = target_range

        if "|" in target_range:
            range_part, ratio_part = target_range.rsplit("|", 1)
            try:
                ratio = int(ratio_part)
            except ValueError:
                ratio = None

        segments: List[Tuple[int, Optional[int]]] = []
        for segment in range_part.split(","):
            parsed_segment = self._parse_target_segment(segment)
            if parsed_segment:
                segments.append(parsed_segment)

        return segments, ratio

    def _parse_target_segment(
        self, segment: str
    ) -> Optional[Tuple[int, Optional[int]]]:
        """Parse a target range segment."""
        if "-" not in segment:
            if not segment.isdigit():
                return None
            value = int(segment)
            return value, value

        start_str, end_str = segment.split("-", 1)
        if not start_str.isdigit():
            return None

        start = int(start_str)
        if end_str == "":
            return start, None
        if not end_str.isdigit():
            return None

        return start, int(end_str)

    def _map_contiguous_segments(
        self, segments: List[Tuple[int, Optional[int]]], source_offset: int
    ) -> Optional[int]:
        """Map an episode across contiguous or concatenated segments."""
        remaining = source_offset

        for start, end in segments:
            if end is None:
                return start + remaining

            segment_length = (end - start) + 1
            if remaining < segment_length:
                return start + remaining

            remaining -= segment_length

        return None

    def _map_positive_ratio(
        self, segments: List[Tuple[int, Optional[int]]], source_offset: int, ratio: int
    ) -> Optional[int]:
        """Map a source episode when each source episode spans multiple target episodes."""
        target_offset = source_offset * ratio
        return self._map_contiguous_segments(segments, target_offset)

    def _map_negative_ratio(
        self, segments: List[Tuple[int, Optional[int]]], source_offset: int, ratio: int
    ) -> Optional[int]:
        """Map a source episode when multiple source episodes map to one target episode."""
        target_offset = source_offset // ratio
        return self._map_contiguous_segments(segments, target_offset)

    def _season_to_scope(self, season: int) -> str:
        """Convert a TVDB season number to AniBridge scope syntax."""
        return f"s{season}"

    def _parse_descriptor(
        self, descriptor: str
    ) -> Optional[tuple[str, int, Optional[str]]]:
        """Parse an AniBridge descriptor into provider, id, and scope."""
        parts = descriptor.lstrip("^").split(":")
        if len(parts) < 2:
            return None

        provider = parts[0]
        raw_id = parts[1]
        scope = parts[2] if len(parts) > 2 else None

        if not raw_id.isdigit():
            return None

        return provider, int(raw_id), scope


anibridge_mappings = AniBridgeMappings()
