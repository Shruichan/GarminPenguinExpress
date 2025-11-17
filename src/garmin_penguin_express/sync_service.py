"""High-level orchestration for syncing Garmin watches."""

from __future__ import annotations

from pathlib import Path
from typing import List

from .gio_utils import (
    GVFS_BASE,
    GVFSMount,
    LOG_FN,
    GioEntry,
    attempt_mount_all_mtp_devices,
    discover_gvfs_mounts,
    ensure_directory,
    ensure_gio_installed,
    gio_copy,
    gio_remove,
    gio_list,
    gio_list_detailed,
    list_music,
    reset_third_party_mounts,
    unmount_uri,
    wipe_directory,
)
from .watch_profiles import WatchProfile
from .conversion import maybe_convert_to_mp3


def _log(log: LOG_FN | None, message: str) -> None:
    if log:
        log(message)


def refresh_mounts(log: LOG_FN | None = None) -> List[GVFSMount]:
    ensure_gio_installed()
    mounts = discover_gvfs_mounts()
    if not mounts:
        _log(log, "No GVFS MTP mounts detected.")
    else:
        for mount in mounts:
            _log(log, f"Found {mount.display_name} at {mount.path}")
    return mounts


def reset_environment(profile: WatchProfile, log: LOG_FN | None = None) -> None:
    _log(log, "Resetting old FUSE/jmtpfs mounts")
    reset_third_party_mounts(profile.legacy_mount_paths, log=log)


def mount_via_gio(log: LOG_FN | None = None) -> List[GVFSMount]:
    ensure_gio_installed()
    attempt_mount_all_mtp_devices(log=log)
    return refresh_mounts(log=log)


def _music_dir(mount: GVFSMount, profile: WatchProfile) -> Path:
    subdir = profile.normalized_music_subdir
    return mount.build_music_dir(subdir)


def wipe_watch_music(mount: GVFSMount, profile: WatchProfile, log: LOG_FN | None = None) -> None:
    music_dir = _music_dir(mount, profile)
    _log(log, f"Wiping {music_dir}")
    ensure_directory(music_dir.parent, log=None)
    ensure_directory(music_dir, log=None)
    wipe_directory(music_dir, log=log)


def copy_library_to_watch(
    src_dir: Path,
    mount: GVFSMount,
    profile: WatchProfile,
    auto_convert: bool,
    log: LOG_FN | None = None,
) -> None:
    if not src_dir.exists():
        raise FileNotFoundError(f"Source directory {src_dir} does not exist")
    music_dir = _music_dir(mount, profile)
    _log(log, f"Copying files from {src_dir} -> {music_dir}")
    files = sorted(p for p in src_dir.iterdir() if p.is_file())
    if not files:
        _log(log, f"No files found in {src_dir}")
        return
    ensure_directory(music_dir, log=None)
    for file_path in files:
        _copy_local_file_to_watch(file_path, music_dir, auto_convert=auto_convert, log=log)


def list_watch_library(mount: GVFSMount, profile: WatchProfile) -> List[str]:
    music_dir = _music_dir(mount, profile)
    return list_music(music_dir)


def unmount_watch(mount: GVFSMount, log: LOG_FN | None = None) -> None:
    unmount_uri(mount.uri, log=log)


def full_sync(
    src_dir: Path,
    mount: GVFSMount,
    profile: WatchProfile,
    auto_convert: bool,
    log: LOG_FN | None = None,
) -> None:
    wipe_watch_music(mount, profile, log=log)
    copy_library_to_watch(src_dir, mount, profile, auto_convert=auto_convert, log=log)


def copy_local_items_to_watch(
    paths: List[Path],
    dest_dir: Path,
    auto_convert: bool,
    log: LOG_FN | None = None,
) -> None:
    ensure_directory(dest_dir, log=None)
    for path in paths:
        if not path.exists():
            continue
        if path.is_dir():
            _copy_local_directory_to_watch(path, dest_dir, log=log)
        else:
            _copy_local_file_to_watch(path, dest_dir, auto_convert=auto_convert, log=log)


def copy_watch_items_to_local(
    entries: List[tuple[Path, bool]], local_dir: Path, log: LOG_FN | None = None
) -> None:
    local_dir.mkdir(parents=True, exist_ok=True)
    for path, is_dir in entries:
        destination = local_dir / path.name
        _gio_copy_with_log(path, destination, recursive=is_dir, log=log)


def delete_watch_items(entries: List[tuple[Path, bool]], log: LOG_FN | None = None) -> None:
    for path, _ in entries:
        _log(log, f"Removing {path.name}")
        gio_remove(path, log=log)


def list_watch_entries(path: Path) -> List[GioEntry]:
    return gio_list_detailed(path)


def _copy_local_file_to_watch(
    src: Path, dest_dir: Path, auto_convert: bool, log: LOG_FN | None = None
) -> None:
    with maybe_convert_to_mp3(src, enable=auto_convert, log=log) as (path_to_copy, dest_name):
        destination = dest_dir / dest_name
        _gio_copy_with_log(path_to_copy, destination, recursive=False, log=log)


def _copy_local_directory_to_watch(src: Path, dest_dir: Path, log: LOG_FN | None = None) -> None:
    destination = dest_dir / src.name
    _log(log, f"Copying directory {src} -> {destination}")
    ensure_directory(destination.parent, log=None)
    result = gio_copy(src, destination, recursive=True)
    if log:
        if result.ok:
            log(f"Copied folder {src.name}")
        else:
            log(f"Failed copying {src.name}: {result.stderr}")


def _gio_copy_with_log(src: Path, dest: Path, recursive: bool, log: LOG_FN | None = None) -> None:
    _ensure_destination_parent(dest)
    result = gio_copy(src, dest, recursive=recursive)
    if log:
        if result.ok:
            log(f"Copied {src.name} -> {dest}")
        else:
            log(f"Failed to copy {src} -> {dest}: {result.stderr}")


def _ensure_destination_parent(dest: Path) -> None:
    dest_parent = dest.parent
    if str(dest_parent).startswith(str(GVFS_BASE)):
        ensure_directory(dest_parent, log=None)
    else:
        dest_parent.mkdir(parents=True, exist_ok=True)
