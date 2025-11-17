"""Entry point for launching the PyQt UI."""

from __future__ import annotations

from . import __version__
from .gui import run


def main() -> None:
    run()


__all__ = ["main", "__version__"]
