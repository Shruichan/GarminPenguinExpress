"""Helpers for converting audio files to MP3 using ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .gio_utils import LOG_FN


class FFmpegError(RuntimeError):
    """Raised when ffmpeg is unavailable or conversion fails."""


def ensure_ffmpeg_available() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise FFmpegError("ffmpeg command not found. Install ffmpeg to enable conversion")
    return path


def convert_file_to_mp3(src: Path, log: LOG_FN | None = None) -> Path:
    ensure_ffmpeg_available()
    if log:
        log(f"Converting {src.name} to MP3 via ffmpeg")
    tmp_dir = Path(tempfile.mkdtemp(prefix="gpe_ffmpeg_"))
    dest = tmp_dir / f"{src.stem}.mp3"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vn",
        "-acodec",
        "libmp3lame",
        "-qscale:a",
        "2",
        str(dest),
    ]
    process = subprocess.run(cmd, capture_output=True, text=True)
    if process.returncode != 0:
        raise FFmpegError(process.stderr.strip() or "ffmpeg conversion failed")
    return dest


@contextmanager
def maybe_convert_to_mp3(src: Path, enable: bool, log: LOG_FN | None = None) -> Iterator[tuple[Path, str]]:
    """Return a tuple of (path_to_copy, destination_filename)."""

    if enable and src.suffix.lower() != ".mp3":
        converted = convert_file_to_mp3(src, log=log)
        try:
            yield converted, f"{src.stem}.mp3"
        finally:
            try:
                converted.unlink(missing_ok=True)
                converted.parent.rmdir()
            except OSError:
                pass
    else:
        yield src, src.name
