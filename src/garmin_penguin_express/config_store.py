"""Tiny JSON-backed configuration helper."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path.home() / ".config" / "GarminPenguinExpress"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class UserPreferences:
    last_selected_watch: Optional[str] = None
    auto_convert_to_mp3: bool = True

    def to_json(self) -> dict:
        return {
            "last_selected_watch": self.last_selected_watch,
            "auto_convert_to_mp3": self.auto_convert_to_mp3,
        }

    @classmethod
    def from_json(cls, payload: dict | None) -> "UserPreferences":
        if not payload:
            return cls()
        return cls(
            last_selected_watch=payload.get("last_selected_watch"),
            auto_convert_to_mp3=payload.get("auto_convert_to_mp3", True),
        )


def load_preferences() -> UserPreferences:
    if not CONFIG_FILE.exists():
        return UserPreferences()
    try:
        payload = json.loads(CONFIG_FILE.read_text())
        return UserPreferences.from_json(payload)
    except json.JSONDecodeError:
        return UserPreferences()


def save_preferences(prefs: UserPreferences) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(prefs.to_json(), indent=2))
