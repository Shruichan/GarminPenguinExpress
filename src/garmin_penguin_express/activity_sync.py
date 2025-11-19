"""Activity ingestion + manifest tracking for Bluetooth passthrough."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

from fitparse import FitFile

from .config_store import CONFIG_DIR

ACTIVITY_DIRS = (
    Path("GARMIN") / "Activity",
    Path("GARMIN") / "Monitor",
)
MANIFEST_FILE = CONFIG_DIR / "activities_manifest.json"


@dataclass(slots=True)
class ActivityEntry:
    path: Path
    relative_path: str
    recorded_time: datetime | None
    sport: str | None
    duration_seconds: float | None
    size_bytes: int
    sha256: str
    uploaded: bool
    upload_id: str | None
    source: str


class ActivityManifest:
    def __init__(self, path: Path = MANIFEST_FILE) -> None:
        self.path = path
        self._payload: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            self._payload = json.loads(self.path.read_text())
        except json.JSONDecodeError:
            self._payload = {}

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._payload, indent=2, default=str))

    def mark_uploaded(self, relative_path: str, sha256: str, upload_id: str | None) -> None:
        record = self._payload.setdefault(relative_path, {})
        record.update(
            {
                "sha256": sha256,
                "uploaded": True,
                "upload_id": upload_id,
                "last_uploaded": datetime.utcnow().isoformat(timespec="seconds"),
            }
        )
        self.save()

    def mark_copied(self, relative_path: str, sha256: str) -> None:
        record = self._payload.setdefault(relative_path, {})
        record.setdefault("sha256", sha256)
        self.save()

    def is_uploaded(self, relative_path: str, sha256: str) -> tuple[bool, str | None]:
        record = self._payload.get(relative_path)
        if not record:
            return False, None
        if record.get("sha256") != sha256:
            return False, None
        return bool(record.get("uploaded")), record.get("upload_id")


class ActivityRepository:
    """Scans watch storage and keeps track of uploads."""

    def __init__(self, manifest: ActivityManifest | None = None) -> None:
        self.manifest = manifest or ActivityManifest()

    def scan(self, mount_root: Path) -> List[ActivityEntry]:
        entries: List[ActivityEntry] = []
        for relative_dir in ACTIVITY_DIRS:
            target_dir = mount_root / relative_dir
            if not target_dir.exists():
                continue
            entries.extend(self._collect_entries(target_dir, relative_dir))
        entries.sort(key=lambda e: (e.recorded_time or datetime.fromtimestamp(0)), reverse=True)
        return entries

    def copy_to_local(self, activities: Iterable[ActivityEntry], destination: Path) -> List[Path]:
        destination.mkdir(parents=True, exist_ok=True)
        copied: List[Path] = []
        for entry in activities:
            dest_path = destination / Path(entry.relative_path).name
            shutil.copy2(entry.path, dest_path)
            self.manifest.mark_copied(entry.relative_path, entry.sha256)
            copied.append(dest_path)
        return copied

    def _collect_entries(self, directory: Path, relative_dir: Path) -> List[ActivityEntry]:
        entries: List[ActivityEntry] = []
        for file_path in sorted(directory.glob("*.fit")):
            rel = str(relative_dir / file_path.name)
            sha256 = hash_file(file_path)
            recorded, sport, duration = read_fit_metadata(file_path)
            uploaded, upload_id = self.manifest.is_uploaded(rel, sha256)
            entries.append(
                ActivityEntry(
                    path=file_path,
                    relative_path=rel,
                    recorded_time=recorded,
                    sport=sport,
                    duration_seconds=duration,
                    size_bytes=file_path.stat().st_size,
                    sha256=sha256,
                    uploaded=uploaded,
                    upload_id=upload_id,
                    source=relative_dir.name,
                )
            )
        return entries

    def mark_uploaded(self, entries: Iterable[ActivityEntry], upload_ids: list[str | None]) -> None:
        for entry, upload_id in zip(entries, upload_ids, strict=False):
            self.manifest.mark_uploaded(entry.relative_path, entry.sha256, upload_id)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 512):
            digest.update(chunk)
    return digest.hexdigest()


def read_fit_metadata(path: Path) -> tuple[datetime | None, str | None, float | None]:
    """Return `(start_time, sport, duration_seconds)` from the FIT session message."""

    try:
        fit = FitFile(str(path))
        fit.parse()
        for message in fit.get_messages("session"):
            data = {field.name: field.value for field in message}
            start_time = data.get("start_time")
            if isinstance(start_time, datetime):
                start = start_time
            else:
                start = None
            sport = data.get("sport")
            duration = data.get("total_timer_time")
            return start, str(sport) if sport is not None else None, float(duration) if duration else None
    except Exception:
        return None, None, None
    return None, None, None
