"""Wrapper around python-garminconnect that handles login/token persistence."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from .config_store import CONFIG_DIR


class ConnectClientError(RuntimeError):
    """Application level exception for Garmin Connect interactions."""


SESSION_DIR = CONFIG_DIR / "connect_session"
SESSION_FILE = SESSION_DIR / "session.json"


@dataclass(slots=True)
class ConnectSessionInfo:
    username: str


class ConnectClient:
    """Stateful helper that hides the raw Garmin client."""

    def __init__(self) -> None:
        self._garmin: Garmin | None = None
        self._session: ConnectSessionInfo | None = None
        self._load_session()

    # Session helpers -----------------------------------------------------
    @property
    def username(self) -> str | None:
        return self._session.username if self._session else None

    def is_authenticated(self) -> bool:
        return self._garmin is not None

    def _load_session(self) -> None:
        if not SESSION_FILE.exists():
            return
        try:
            payload = json.loads(SESSION_FILE.read_text())
            username = payload.get("username")
            if not username:
                return
            garmin = Garmin()
            garmin.garth.load(str(SESSION_DIR))
            self._garmin = garmin
            self._session = ConnectSessionInfo(username=username)
        except Exception:
            # corrupted tokens - nuke and force re-login
            self._garmin = None
            self._session = None
            shutil.rmtree(SESSION_DIR, ignore_errors=True)

    def _persist_session(self, username: str) -> None:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(json.dumps({"username": username}, indent=2))
        self._session = ConnectSessionInfo(username=username)

    def logout(self) -> None:
        """Drop cached tokens."""

        self._garmin = None
        self._session = None
        shutil.rmtree(SESSION_DIR, ignore_errors=True)

    # Auth API ------------------------------------------------------------
    def login(self, username: str, password: str, mfa_code: str | None = None) -> None:
        """Perform a fresh login with credentials (optionally providing MFA)."""

        prompt_mfa = (lambda: mfa_code or "") if mfa_code else None
        garmin = Garmin(username, password, prompt_mfa=prompt_mfa, return_on_mfa=False)
        try:
            garmin.login()
        except GarminConnectAuthenticationError as exc:
            raise ConnectClientError(str(exc)) from exc
        except GarminConnectTooManyRequestsError as exc:
            raise ConnectClientError("Too many attempts. Wait a bit before retrying.") from exc
        except GarminConnectConnectionError as exc:
            raise ConnectClientError(f"Unable to reach Garmin Connect: {exc}") from exc
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        garmin.garth.dump(str(SESSION_DIR))
        self._garmin = garmin
        self._persist_session(username)

    def ensure_authenticated(self) -> Garmin:
        if not self._garmin:
            raise ConnectClientError("Login to Garmin Connect first.")
        return self._garmin

    # Activity helpers ----------------------------------------------------
    def upload_activity(self, activity_path: Path) -> dict[str, Any]:
        """Upload a FIT/GPX/TXC activity file to Garmin Connect."""

        client = self.ensure_authenticated()
        response = client.upload_activity(str(activity_path))
        return self._maybe_json(response)

    # Workout helpers -----------------------------------------------------
    def upload_workout(self, workout_payload: dict[str, Any]) -> dict[str, Any]:
        """Create a structured workout on Garmin Connect."""

        client = self.ensure_authenticated()
        return client.upload_workout(workout_payload)

    def download_workout_fit(self, workout_id: int) -> bytes:
        """Download the FIT asset for a workout."""

        client = self.ensure_authenticated()
        return client.download_workout(workout_id)

    def schedule_workout(self, workout_id: int, sport_type: dict[str, Any], day: date) -> dict[str, Any]:
        """Schedule a workout on a specific calendar date in Garmin Connect."""

        client = self.ensure_authenticated()
        payload = {
            "workoutId": int(workout_id),
            "sportType": sport_type,
            "scheduleType": "PLANNED",
            "startDate": day.isoformat(),
        }
        url = f"{client.garmin_workouts_schedule_url}"
        response = client.garth.post("connectapi", url, json=payload, api=True)
        return self._maybe_json(response)

    # Internal utilities --------------------------------------------------
    @staticmethod
    def _maybe_json(response: Any) -> dict[str, Any]:
        if not response:
            return {}
        if hasattr(response, "json"):
            try:
                return response.json()
            except ValueError:
                return {"status": getattr(response, "status_code", None), "text": getattr(response, "text", "")}
        return {"result": response}
