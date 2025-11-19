"""Workout template helpers and FIT export plumbing."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List

from .config_store import CONFIG_DIR
from .gio_utils import ensure_directory, gio_copy, GioError

WORKOUT_STORE = CONFIG_DIR / "workouts.json"

SPORT_TYPES: dict[str, dict[str, int | str]] = {
    "running": {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1},
    "cycling": {"sportTypeId": 2, "sportTypeKey": "cycling", "displayOrder": 2},
    "other": {"sportTypeId": 9, "sportTypeKey": "other", "displayOrder": 9},
}

STEP_TYPES = {
    "warmup": {"stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown", "displayOrder": 2},
    "interval": {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
    "recovery": {"stepTypeId": 4, "stepTypeKey": "recovery", "displayOrder": 4},
    "repeat": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
}

TARGET_NONE = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
TIME_CONDITION = {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True}
ITERATION_CONDITION = {"conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7, "displayable": False}


@dataclass(slots=True)
class WorkoutTemplate:
    name: str
    sport: str = "running"
    warmup_seconds: int = 300
    interval_seconds: int = 60
    recovery_seconds: int = 60
    repeats: int = 4
    cooldown_seconds: int = 300

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "WorkoutTemplate":
        return cls(
            name=payload.get("name", "Workout"),
            sport=payload.get("sport", "running"),
            warmup_seconds=int(payload.get("warmup_seconds", 0)),
            interval_seconds=int(payload.get("interval_seconds", 60)),
            recovery_seconds=int(payload.get("recovery_seconds", 60)),
            repeats=int(payload.get("repeats", 1)),
            cooldown_seconds=int(payload.get("cooldown_seconds", 0)),
        )

    @property
    def estimated_duration(self) -> int:
        total = 0
        total += max(0, self.warmup_seconds)
        total += max(0, self.cooldown_seconds)
        total += (max(0, self.interval_seconds) + max(0, self.recovery_seconds)) * max(0, self.repeats)
        return total


class WorkoutManager:
    def __init__(self, store: Path = WORKOUT_STORE) -> None:
        self.store = store
        self.templates: List[WorkoutTemplate] = []
        self._load()

    def _load(self) -> None:
        if not self.store.exists():
            return
        try:
            data = json.loads(self.store.read_text())
            self.templates = [WorkoutTemplate.from_dict(item) for item in data]
        except json.JSONDecodeError:
            self.templates = []

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = [template.to_dict() for template in self.templates]
        self.store.write_text(json.dumps(payload, indent=2))

    def add_template(self, template: WorkoutTemplate) -> None:
        self.templates.append(template)
        self.save()

    def delete_template(self, index: int) -> None:
        if 0 <= index < len(self.templates):
            self.templates.pop(index)
            self.save()

    def build_payload(self, template: WorkoutTemplate) -> dict:
        sport = SPORT_TYPES.get(template.sport, SPORT_TYPES["running"])
        steps: List[dict] = []
        order = 1
        if template.warmup_seconds > 0:
            steps.append(executable_step(order, "warmup", template.warmup_seconds))
            order += 1
        if template.repeats > 0 and template.interval_seconds > 0:
            repeat_block, order = build_repeat_block(order, template)
            steps.append(repeat_block)
        if template.cooldown_seconds > 0:
            steps.append(executable_step(order, "cooldown", template.cooldown_seconds))
        payload = {
            "workoutName": template.name,
            "sportType": sport,
            "estimatedDurationInSecs": template.estimated_duration,
            "workoutSegments": [
                {
                    "segmentOrder": 1,
                    "sportType": sport,
                    "workoutSteps": steps,
                }
            ],
        }
        return payload


def executable_step(order: int, step_type_key: str, seconds: int) -> dict:
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": STEP_TYPES[step_type_key],
        "endCondition": TIME_CONDITION,
        "endConditionValue": float(seconds),
        "targetType": TARGET_NONE,
        "strokeType": {"strokeTypeId": 0, "displayOrder": 0},
        "equipmentType": {"equipmentTypeId": 0, "displayOrder": 0},
    }


def build_repeat_block(order: int, template: WorkoutTemplate) -> tuple[dict, int]:
    interval_step = executable_step(order + 1, "interval", template.interval_seconds)
    recovery_step = executable_step(order + 2, "recovery", template.recovery_seconds)
    repeat_step = {
        "type": "RepeatGroupDTO",
        "stepOrder": order,
        "stepType": STEP_TYPES["repeat"],
        "numberOfIterations": int(template.repeats),
        "workoutSteps": [interval_step, recovery_step],
        "endConditionValue": float(template.repeats),
        "endCondition": ITERATION_CONDITION,
        "smartRepeat": False,
    }
    return repeat_step, order + 2


def copy_fit_bytes_to_watch(data: bytes, dest_dir: Path, filename: str) -> Path:
    """Persist FIT bytes into GARMIN/NewFiles using gio copy semantics."""

    ensure_directory(dest_dir, log=None)
    tmp_dir = Path(tempfile.mkdtemp(prefix="gpe_workout_"))
    tmp_file = tmp_dir / filename
    tmp_file.write_bytes(data)
    dest_path = dest_dir / filename
    try:
        result = gio_copy(tmp_file, dest_path, recursive=False)
        if not result.ok:
            raise GioError(f"gio copy failed: {result.stderr}")
        return dest_path
    finally:
        tmp_file.unlink(missing_ok=True)
        try:
            tmp_dir.rmdir()
        except OSError:
            pass


def sanitize_filename(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name.strip())
    return safe or "workout"
