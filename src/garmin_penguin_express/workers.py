"""Qt workers for running gio/ffmpeg tasks off the UI thread."""

from __future__ import annotations

import traceback
from typing import Any, Callable

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal


class WorkerSignals(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    log = pyqtSignal(str)


class GioWorker(QRunnable):
    def __init__(self, description: str, task_callable: Callable[[Callable[[str], None]], Any]):
        super().__init__()
        self.description = description
        self.task_callable = task_callable
        self.signals = WorkerSignals()

    def run(self) -> None:  # pragma: no cover - Qt thread
        try:
            result = self.task_callable(self.signals.log.emit)
            self.signals.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            self.signals.error.emit(f"{exc}\n{tb}")
