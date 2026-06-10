"""Anime release title parsing built around aniparse metadata."""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import aniparse

logger = logging.getLogger(__name__)


@dataclass
class ParsedRelease:
    """Parsed metadata extracted from a Nyaa release title."""

    original_title: str
    release_group: Optional[str] = None
    series_title: Optional[str] = None
    episode_numbers: list[int] = field(default_factory=list)
    episode_ranges: list[tuple[int, int]] = field(default_factory=list)
    year: Optional[int] = None
    resolution: Optional[str] = None
    source: Optional[str] = None
    release_version: Optional[str] = None
    metadata_suffix: str = ""
    parser_confidence: float = 0.0

    @property
    def is_batch(self) -> bool:
        """Whether the parsed title appears to be a batch or episode range."""
        lowered = self.original_title.lower()
        if any(term in lowered for term in ("batch", "complete", "season pack")):
            return True
        return bool(self.episode_ranges)


class ReleaseParser:
    """Parses Nyaa release titles into the subset of metadata used by the proxy."""

    def parse(self, title: str) -> ParsedRelease:
        """Parse a Nyaa release title."""
        try:
            parsed = aniparse.parse(title) or {}
        except Exception as exc:
            logger.warning("aniparse failed for title '%s': %s", title, exc)
            parsed = {}

        release = ParsedRelease(
            original_title=title,
            release_group=self._first_text(parsed.get("release_group")),
            parser_confidence=float(parsed.get("_confidence") or 0.0),
        )

        series = self._first_dict(parsed.get("series"))
        if series:
            release.series_title = self._first_title(series.get("title"))
            release.episode_numbers = self._episode_numbers(series.get("episode"))
            release.episode_ranges = self._episode_ranges(series.get("episode"))
            release.year = self._number_from_any(series.get("year"))

        release.resolution = self._resolution(parsed.get("video_resolution"))
        release.source = self._first_text(parsed.get("source"))
        release.release_version = self._release_version(parsed, series)
        release.metadata_suffix = self._metadata_suffix(title)

        if not release.episode_numbers:
            release.episode_numbers = self._episode_numbers_from_text(title)
        if release.year is None:
            release.year = self._year_from_text(title)
        if release.release_group is None:
            release.release_group = self._leading_group(title)

        return release

    def _first_dict(self, value: Any) -> Optional[dict[str, Any]]:
        if isinstance(value, list):
            return next((item for item in value if isinstance(item, dict)), None)
        if isinstance(value, dict):
            return value
        return None

    def _first_text(self, value: Any) -> Optional[str]:
        if isinstance(value, list):
            for item in value:
                text = self._first_text(item)
                if text:
                    return text
            return None
        if isinstance(value, dict):
            return self._first_text(value.get("name") or value.get("value"))
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _first_title(self, value: Any) -> Optional[str]:
        text = self._first_text(value)
        return re.sub(r"\s+", " ", text).strip() if text else None

    def _number_from_any(self, value: Any) -> Optional[int]:
        if isinstance(value, list):
            for item in value:
                number = self._number_from_any(item)
                if number is not None:
                    return number
            return None
        if isinstance(value, dict):
            return self._number_from_any(value.get("number"))
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    def _episode_numbers(self, value: Any) -> list[int]:
        numbers: list[int] = []
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict) and "number" in item:
                number = self._number_from_any(item.get("number"))
                if number is not None:
                    numbers.append(number)
            elif isinstance(item, int):
                numbers.append(item)
        return sorted(dict.fromkeys(numbers))

    def _episode_ranges(self, value: Any) -> list[tuple[int, int]]:
        ranges: list[tuple[int, int]] = []
        for item in value if isinstance(value, list) else [value]:
            if not isinstance(item, dict):
                continue
            start = self._number_from_any(item.get("start"))
            end = self._number_from_any(item.get("end"))
            if start is not None and end is not None and end > start:
                ranges.append((start, end))
        return ranges

    def _episode_numbers_from_text(self, title: str) -> list[int]:
        patterns = [
            r"(?<![A-Za-z0-9])EP\s*0*(\d{1,5})(?:v\d+)?(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9])-?\s0*(\d{1,5})(?:v\d+)?(?:\s|\[|\(|$)",
        ]
        numbers: list[int] = []
        for pattern in patterns:
            for match in re.finditer(pattern, title, re.IGNORECASE):
                number = int(match.group(1))
                if number > 0 and number not in numbers:
                    numbers.append(number)
        return numbers

    def _year_from_text(self, title: str) -> Optional[int]:
        match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", title)
        return int(match.group(1)) if match else None

    def _resolution(self, value: Any) -> Optional[str]:
        if isinstance(value, list):
            return next((self._resolution(item) for item in value if item), None)
        if isinstance(value, dict):
            height = value.get("video_height")
            scan = value.get("scan_method") or "p"
            return f"{height}{scan}" if height else None
        return self._first_text(value)

    def _release_version(
        self, parsed: dict[str, Any], series: Optional[dict[str, Any]]
    ) -> Optional[str]:
        version = self._first_text(parsed.get("release_version"))
        if version:
            return f"v{version.lstrip('v')}"

        episodes = series.get("episode") if series else None
        for item in episodes if isinstance(episodes, list) else [episodes]:
            if isinstance(item, dict) and item.get("release_version"):
                return f"v{str(item['release_version']).lstrip('v')}"

        match = re.search(
            r"(?<![A-Za-z0-9])(v\d+)(?![A-Za-z0-9])",
            parsed.get("file_name", ""),
            re.IGNORECASE,
        )
        return match.group(1).lower() if match else None

    def _leading_group(self, title: str) -> Optional[str]:
        match = re.match(r"^\[([^\]]+)]", title)
        return match.group(1).strip() if match else None

    def _metadata_suffix(self, title: str) -> str:
        without_group = re.sub(r"^\[[^\]]+]\s*", "", title).strip()
        markers = [
            r"\bS\d{1,2}E\d{1,3}(?:v\d+)?\b",
            r"\bEP\s*\d{1,5}(?:v\d+)?\b",
            r"\s-\s0*\d{1,5}(?:v\d+)?\b",
            r"\((?:19|20)\d{2}\)(?=\s|\[|$)",
            r"\b(?!19\d{2}\b|20\d{2}\b)0*\d{1,5}(?:v\d+)?\b",
            r"\)(?=\s|\[|$)",
        ]
        for marker in markers:
            match = re.search(marker, without_group, re.IGNORECASE)
            if not match:
                continue
            suffix = without_group[match.end() :].strip()
            suffix = re.sub(r"^(?:[-_.]\s*)+", "", suffix).strip()
            if suffix:
                return suffix

        bracketed = re.findall(r"(\[[^\]]+])", without_group)
        return " ".join(bracketed).strip()


release_parser = ReleaseParser()
