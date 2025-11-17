"""Helpers that wrap the gio CLI so Python can drive GVFS/MTP."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Sequence
from urllib.parse import unquote

LOG_FN = Callable[[str], None]
GVFS_BASE = Path(f"/run/user/{os.getuid()}/gvfs")


class GioError(RuntimeError):
    """Raised when a gio command fails."""


@dataclass(slots=True)
class GVFSMount:
    """Represents a mounted GVFS endpoint."""

    path: Path
    display_name: str
    uri: str

    def build_music_dir(self, relative_subdir: str) -> Path:
        return self.path / relative_subdir


@dataclass(slots=True)
class GioCommandResult:
    stdout: str
    stderr: str
    returncode: int

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(slots=True)
class GioEntry:
    name: str
    is_dir: bool


def _run(cmd: Sequence[str], check: bool = True) -> GioCommandResult:
    process = subprocess.run(cmd, capture_output=True, text=True)
    result = GioCommandResult(
        stdout=process.stdout.strip(), stderr=process.stderr.strip(), returncode=process.returncode
    )
    if check and not result.ok:
        raise GioError(
            f"Command {' '.join(shlex.quote(c) for c in cmd)} failed with "
            f"{result.returncode}: {result.stderr}"
        )
    return result


def ensure_gio_installed() -> None:
    if shutil.which("gio") is None:
        raise GioError("gio command not found. Please install the GVFS suite.")


def list_mtp_mount_paths() -> List[Path]:
    if not GVFS_BASE.exists():
        return []
    return sorted(GVFS_BASE.glob("mtp:host=*"))


def _decode_uri_from_path(path: Path) -> str:
    suffix = path.name.split("mtp:host=", 1)[-1]
    decoded = unquote(suffix)
    if not decoded.startswith("mtp://"):
        decoded = f"mtp://{decoded}"
    if not decoded.endswith("/"):
        decoded = f"{decoded}/"
    return decoded


def _gio_display_name(path: Path) -> str:
    result = _run(["gio", "info", str(path)], check=False)
    if not result.ok:
        return path.name
    for line in result.stdout.splitlines():
        if "display name" in line:
            return line.split(":", 1)[1].strip()
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip()
    return path.name


def discover_gvfs_mounts() -> List[GVFSMount]:
    mounts: List[GVFSMount] = []
    for path in list_mtp_mount_paths():
        mounts.append(GVFSMount(path=path, display_name=_gio_display_name(path), uri=_decode_uri_from_path(path)))
    return mounts


def list_gio_mountable_uris() -> List[str]:
    result = _run(["gio", "mount", "-li"], check=False)
    if not result.ok:
        return []
    uris: set[str] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.lower().startswith("default location:"):
            location = line.split(":", 1)[1].strip()
        elif line.startswith("activation_root="):
            location = line.split("=", 1)[1].strip()
        else:
            continue
        if location.startswith("mtp://"):
            if not location.endswith("/"):
                location = f"{location}/"
            uris.add(location)
    return sorted(uris)


def attempt_mount_all_mtp_devices(log: LOG_FN | None = None) -> None:
    for uri in list_gio_mountable_uris():
        if log:
            log(f"Attempting gio mount {uri}")
        result = _run(["gio", "mount", uri], check=False)
        if log:
            if result.ok:
                log(f"Mounted {uri}")
            else:
                log(f"gio mount {uri} -> {result.returncode}: {result.stderr}")


def unmount_uri(uri: str, log: LOG_FN | None = None) -> None:
    if log:
        log(f"gio mount -u {uri}")
    _run(["gio", "mount", "-u", uri], check=False)


def reset_third_party_mounts(candidate_paths: Iterable[Path], log: LOG_FN | None = None) -> None:
    for path in candidate_paths:
        if path.exists():
            result = _run(["fusermount", "-u", str(path)], check=False)
            if log:
                log(f"fusermount -u {path} -> {result.returncode}")
    result = _run(["pkill", "-f", "jmtpfs"], check=False)
    if log:
        log(f"pkill -f jmtpfs -> {result.returncode}")


def gio_list(path: Path) -> List[str]:
    result = _run(["gio", "list", str(path)], check=False)
    if not result.ok:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def gio_list_detailed(path: Path) -> List[GioEntry]:
    result = _run(["gio", "list", "-l", str(path)], check=False)
    entries: List[GioEntry] = []
    if not result.ok:
        return entries
    for raw in result.stdout.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parts = raw.split("\t")
        name = parts[0].strip()
        type_part = parts[-1].strip("() ")
        is_dir = "directory" in type_part.lower()
        entries.append(GioEntry(name=name, is_dir=is_dir))
    return entries


def gio_remove(path: Path, log: LOG_FN | None = None) -> None:
    result = _run(["gio", "remove", str(path)], check=False)
    if log:
        if result.ok:
            log(f"Removed {path}")
        else:
            log(f"Failed to remove {path}: {result.stderr}")


def wipe_directory(path: Path, log: LOG_FN | None = None) -> None:
    for entry in gio_list(path):
        full_path = path / entry
        if log:
            log(f"Removing {entry}")
        gio_remove(full_path, log=log)


def ensure_directory(path: Path, log: LOG_FN | None = None) -> None:
    result = _run(["gio", "make-directory", str(path)], check=False)
    if log:
        if result.ok:
            log(f"Created {path}")
        else:
            log(f"gio make-directory {path} -> {result.stderr or 'already exists?'}")


def copy_mp3s(src_dir: Path, dest_dir: Path, log: LOG_FN | None = None) -> None:
    files = sorted({*src_dir.glob("*.mp3"), *src_dir.glob("*.MP3")})
    if not files:
        if log:
            log("No .mp3 files found in source directory")
        return
    ensure_directory(dest_dir, log=log)
    for file in files:
        destination = dest_dir / file.name
        if log:
            log(f"Copying {file.name}")
        result = _run(["gio", "copy", str(file), str(destination)], check=False)
        if log and not result.ok:
            log(f"FAILED copying {file.name}: {result.stderr}")


def gio_copy(src: Path, dest: Path, recursive: bool = False) -> GioCommandResult:
    cmd = ["gio", "copy"]
    if recursive:
        cmd.append("-r")
    cmd.extend([str(src), str(dest)])
    return _run(cmd, check=False)


def list_music(dest_dir: Path) -> List[str]:
    return gio_list(dest_dir)
