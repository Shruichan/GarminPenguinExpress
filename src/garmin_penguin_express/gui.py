"""PyQt application that exposes the Garmin Penguin Express workflow."""

from __future__ import annotations

import sys
from functools import partial
from pathlib import Path

from PyQt6.QtCore import QThreadPool, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config_store import UserPreferences, load_preferences, save_preferences
from .explorer import FileBrowserWidget
from .sync_service import (
    copy_library_to_watch,
    full_sync,
    mount_via_gio,
    refresh_mounts,
    reset_environment,
    unmount_watch,
    wipe_watch_music,
)
from .watch_profiles import DEFAULT_WATCH_PROFILES, WatchProfile
from .gio_utils import GVFSMount, list_gio_mountable_uris
from .workers import GioWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Garmin Penguin Express")
        self.resize(840, 640)

        self.thread_pool = QThreadPool()
        self.preferences: UserPreferences = load_preferences()
        self.watch_profiles = list(DEFAULT_WATCH_PROFILES)
        self.current_mounts: list[GVFSMount] = []
        self._task_running = False

        self._build_ui()
        self._restore_watch_selection()
        QTimer.singleShot(500, self.refresh_devices)

    # UI helpers -----------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        main_layout = QVBoxLayout()

        # Controls layout
        controls = QGridLayout()
        controls.setColumnStretch(1, 1)

        controls.addWidget(QLabel("Watch"), 0, 0)
        self.watch_combo = QComboBox()
        for profile in self.watch_profiles:
            self.watch_combo.addItem(profile.label, userData=profile)
        self.watch_combo.currentIndexChanged.connect(self._on_watch_changed)
        controls.addWidget(self.watch_combo, 0, 1)

        self.auto_convert_checkbox = QCheckBox("Convert non-MP3 files to MP3 with ffmpeg")
        self.auto_convert_checkbox.setChecked(self.preferences.auto_convert_to_mp3)
        self.auto_convert_checkbox.stateChanged.connect(self._on_auto_convert_toggled)
        controls.addWidget(self.auto_convert_checkbox, 0, 2)

        controls.addWidget(QLabel("GVFS device"), 1, 0)
        self.device_combo = QComboBox()
        self.device_combo.setPlaceholderText("No GVFS mounts detected")
        self.device_combo.currentIndexChanged.connect(self._on_mount_changed)
        controls.addWidget(self.device_combo, 1, 1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_devices)
        controls.addWidget(self.refresh_button, 1, 2)

        button_row = QHBoxLayout()
        self.reset_button = QPushButton("Reset helpers")
        self.reset_button.clicked.connect(self.reset_helpers)
        self.mount_button = QPushButton("Mount via gio")
        self.mount_button.clicked.connect(self.mount_devices)
        self.wipe_button = QPushButton("Wipe Music")
        self.wipe_button.clicked.connect(self.wipe_music)
        self.copy_button = QPushButton("Copy Folder to Watch…")
        self.copy_button.clicked.connect(self.copy_music)
        self.sync_button = QPushButton("Sync Folder (wipe + copy)…")
        self.sync_button.clicked.connect(self.sync_watch)
        self.unmount_button = QPushButton("Unmount")
        self.unmount_button.clicked.connect(self.unmount_device)
        for btn in (
            self.reset_button,
            self.mount_button,
            self.wipe_button,
            self.copy_button,
            self.sync_button,
            self.unmount_button,
        ):
            button_row.addWidget(btn)
        controls.addLayout(button_row, 2, 0, 1, 3)

        main_layout.addLayout(controls)

        # Dual-pane browser
        self.browser_widget = FileBrowserWidget(self, self.append_log, lambda: self.auto_convert_checkbox.isChecked())
        main_layout.addWidget(self.browser_widget, 1)

        # Log console
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        main_layout.addWidget(QLabel("Log"))
        main_layout.addWidget(self.log_view)

        main_layout.setStretch(0, 0)
        main_layout.setStretch(1, 1)
        main_layout.setStretch(2, 0)

        central.setLayout(main_layout)
        self.setCentralWidget(central)

        self.action_buttons = [
            self.reset_button,
            self.mount_button,
            self.wipe_button,
            self.copy_button,
            self.sync_button,
            self.unmount_button,
            self.refresh_button,
        ]

    # Preference helpers ---------------------------------------------------------
    def _restore_watch_selection(self) -> None:
        preferred = self.preferences.last_selected_watch
        index_to_set = 0
        if preferred:
            for idx, profile in enumerate(self.watch_profiles):
                if profile.identifier == preferred:
                    index_to_set = idx
                    break
        self.watch_combo.blockSignals(True)
        self.watch_combo.setCurrentIndex(index_to_set)
        self.watch_combo.blockSignals(False)
        self._on_watch_changed(index_to_set)

    def _on_watch_changed(self, index: int) -> None:
        profile = self.watch_combo.currentData()
        if not isinstance(profile, WatchProfile):
            return
        self.preferences.last_selected_watch = profile.identifier
        save_preferences(self.preferences)

    def _on_auto_convert_toggled(self, _state: int) -> None:
        self.preferences.auto_convert_to_mp3 = self.auto_convert_checkbox.isChecked()
        save_preferences(self.preferences)

    def _prompt_local_folder(self, title: str) -> Path | None:
        directory = QFileDialog.getExistingDirectory(self, title, str(Path.home()))
        return Path(directory) if directory else None

    # Task helpers ---------------------------------------------------------------
    def run_task(self, description: str, task_callable, on_success=None) -> None:
        if self._task_running:
            QMessageBox.information(self, "Task running", "Wait for the current task to finish.")
            return
        self._task_running = True
        self._set_actions_enabled(False)
        self.append_log(f"→ {description}")
        worker = GioWorker(description, task_callable)
        worker.signals.log.connect(self.append_log)
        worker.signals.error.connect(self._task_error)
        worker.signals.finished.connect(partial(self._task_finished, on_success))
        self.thread_pool.start(worker)

    def _task_finished(self, callback, result) -> None:
        self._task_running = False
        self._set_actions_enabled(True)
        if callback:
            callback(result)

    def _task_error(self, message: str) -> None:
        self.append_log(message)
        QMessageBox.critical(self, "Task failed", message)
        self._task_running = False
        self._set_actions_enabled(True)

    def _set_actions_enabled(self, enabled: bool) -> None:
        for button in self.action_buttons:
            button.setEnabled(enabled)
        self.watch_combo.setEnabled(enabled)
        self.device_combo.setEnabled(enabled)

    def append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    # Current selections ---------------------------------------------------------
    def current_profile(self) -> WatchProfile:
        profile = self.watch_combo.currentData()
        if isinstance(profile, WatchProfile):
            return profile
        return self.watch_profiles[0]

    def current_mount(self) -> GVFSMount | None:
        data = self.device_combo.currentData()
        return data if isinstance(data, GVFSMount) else None

    # Button slots ---------------------------------------------------------------
    def reset_helpers(self) -> None:
        profile = self.current_profile()
        self.run_task(
            "Resetting helper mounts",
            lambda log: reset_environment(profile, log=log),
        )

    def refresh_devices(self) -> None:
        self.run_task(
            "Refreshing GVFS mounts",
            lambda log: refresh_mounts(log=log),
            on_success=self._populate_devices,
        )

    def mount_devices(self) -> None:
        self.run_task(
            "Mounting via gio",
            lambda log: mount_via_gio(log=log),
            on_success=self._populate_devices,
        )

    def wipe_music(self) -> None:
        mount = self.current_mount()
        if not mount:
            QMessageBox.warning(self, "No device", "Select a GVFS mount first.")
            return
        profile = self.current_profile()
        self.run_task(
            "Wiping music",
            lambda log: wipe_watch_music(mount, profile, log=log),
        )

    def copy_music(self) -> None:
        mount = self.current_mount()
        if not mount:
            QMessageBox.warning(self, "No device", "Select a GVFS mount first.")
            return
        folder = self._prompt_local_folder("Select folder to copy to the watch")
        if not folder:
            return
        profile = self.current_profile()
        convert = self.auto_convert_checkbox.isChecked()
        self.run_task(
            "Copying library",
            lambda log: copy_library_to_watch(folder, mount, profile, auto_convert=convert, log=log),
        )

    def sync_watch(self) -> None:
        mount = self.current_mount()
        if not mount:
            QMessageBox.warning(self, "No device", "Select a GVFS mount first.")
            return
        folder = self._prompt_local_folder("Select folder to sync to the watch")
        if not folder:
            return
        profile = self.current_profile()
        convert = self.auto_convert_checkbox.isChecked()
        self.run_task(
            "Full sync",
            lambda log: full_sync(folder, mount, profile, auto_convert=convert, log=log),
        )

    def unmount_device(self) -> None:
        mount = self.current_mount()
        if not mount:
            QMessageBox.warning(self, "No device", "Select a GVFS mount first.")
            return
        self.run_task(
            "Unmounting",
            lambda log: unmount_watch(mount, log=log),
            on_success=lambda _: self.refresh_devices(),
        )

    # Device handling ------------------------------------------------------------
    def _populate_devices(self, mounts: list[GVFSMount]) -> None:
        self.current_mounts = mounts
        self.device_combo.clear()
        if not mounts:
            self.device_combo.setPlaceholderText("No GVFS mounts detected")
            return
        for mount in mounts:
            label = f"{mount.display_name} ({mount.path.name})"
            self.device_combo.addItem(label, userData=mount)
        self.device_combo.setCurrentIndex(0)


def run() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
