"""Watch profile metadata so the UI can present a Garmin Express style selector."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass(slots=True)
class WatchProfile:
    """A single Garmin wearable preset."""

    identifier: str
    label: str
    music_subdir: str = "Internal Storage/Music"
    legacy_mount_paths: List[Path] = field(default_factory=list)

    @property
    def normalized_music_subdir(self) -> str:
        """Return the relative music dir inside the GVFS mount."""

        return self.music_subdir.strip("/")


HOME = Path.home()

DEFAULT_WATCH_PROFILES: tuple[WatchProfile, ...] = (
    WatchProfile(
        identifier="venu4",
        label="Venu 4",
        legacy_mount_paths=[HOME / "venu4"],
    ),
    WatchProfile(
        identifier="forerunner965",
        label="Forerunner 965",
        legacy_mount_paths=[HOME / "garmin"],
    ),
    WatchProfile(
        identifier="fenix7",
        label="Fenix 7",
    ),
)
