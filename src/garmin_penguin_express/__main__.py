"""Module entry point so `python -m garmin_penguin_express` and PyInstaller builds work."""

try:
    # When run as a proper package (e.g., python -m garmin_penguin_express)
    from .app import main
except ImportError:  # pragma: no cover - PyInstaller entry
    # When frozen or run as a script, __package__ may be empty. Add the src root to sys.path.
    import pathlib
    import sys

    project_root = pathlib.Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.append(str(project_root))
    from garmin_penguin_express.app import main  # type: ignore


if __name__ == "__main__":
    main()
