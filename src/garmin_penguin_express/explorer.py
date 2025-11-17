"""Dual-pane file browser embedded in the main Garmin Penguin Express UI."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List

from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .gio_utils import GVFSMount
from .watch_profiles import WatchProfile
from .sync_service import (
    copy_local_items_to_watch,
    copy_watch_items_to_local,
    delete_watch_items,
    list_watch_entries,
)
from .workers import GioWorker


class FileBrowserWidget(QWidget):
    """A two-pane browser: local files on the left, watch contents on the right."""

    def __init__(
        self,
        parent,
        log_fn: Callable[[str], None],
        auto_convert_provider: Callable[[], bool],
    ) -> None:
        super().__init__(parent)
        self.log_fn = log_fn
        self.auto_convert_provider = auto_convert_provider
        self.thread_pool = QThreadPool(self)

        self.local_current = Path.home()
        self.mount: GVFSMount | None = None
        self.profile: WatchProfile | None = None
        self.watch_root: Path | None = None
        self.watch_mount_root: Path | None = None
        self.watch_current: Path | None = None
        self._task_running = False

        self._build_ui()
        self._refresh_local()
        self._update_watch_paths()

    # Public API -------------------------------------------------------------
    def set_profile(self, profile: WatchProfile) -> None:
        self.profile = profile
        self._update_watch_paths()

    def set_mount(self, mount: GVFSMount | None) -> None:
        self.mount = mount
        self._update_watch_paths()

    def is_busy(self) -> bool:
        return self._task_running

    # UI construction -------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QGridLayout()
        local_panel = self._build_local_panel()
        watch_panel = self._build_watch_panel()
        action_layout = self._build_action_buttons()
        layout.addWidget(local_panel, 0, 0)
        layout.addLayout(action_layout, 0, 1)
        layout.addWidget(watch_panel, 0, 2)
        layout.setColumnStretch(0, 4)
        layout.setColumnStretch(1, 0)
        layout.setColumnStretch(2, 4)
        self.setLayout(layout)

    def _build_local_panel(self) -> QGroupBox:
        box = QGroupBox("Computer")
        vbox = QVBoxLayout()
        path_row = QHBoxLayout()
        self.local_path_label = QLabel(str(self.local_current))
        self.local_up_button = QPushButton("Up")
        self.local_up_button.clicked.connect(self._local_go_up)
        self.local_home_button = QPushButton("Home")
        self.local_home_button.clicked.connect(self._local_go_home)
        self.local_choose_button = QPushButton("Choose Folder…")
        self.local_choose_button.clicked.connect(self._local_choose_folder)
        path_row.addWidget(self.local_path_label)
        path_row.addWidget(self.local_up_button)
        path_row.addWidget(self.local_home_button)
        path_row.addWidget(self.local_choose_button)
        vbox.addLayout(path_row)

        self.local_list = QListWidget()
        self.local_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.local_list.itemDoubleClicked.connect(self._local_open)
        vbox.addWidget(self.local_list)

        box.setLayout(vbox)
        return box

    def _build_watch_panel(self) -> QGroupBox:
        box = QGroupBox("Watch")
        vbox = QVBoxLayout()
        path_row = QHBoxLayout()
        self.watch_path_label = QLabel("No device connected")
        self.watch_up_button = QPushButton("Up")
        self.watch_up_button.clicked.connect(self._watch_go_up)
        self.watch_root_button = QPushButton("Music Root")
        self.watch_root_button.clicked.connect(self._watch_go_root)
        path_row.addWidget(self.watch_path_label)
        path_row.addWidget(self.watch_up_button)
        path_row.addWidget(self.watch_root_button)
        vbox.addLayout(path_row)

        self.watch_list = QListWidget()
        self.watch_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.watch_list.itemDoubleClicked.connect(self._watch_open)
        vbox.addWidget(self.watch_list)

        box.setLayout(vbox)
        return box

    def _build_action_buttons(self) -> QVBoxLayout:
        vbox = QVBoxLayout()
        self.copy_to_watch_button = QPushButton("→ Copy to Watch")
        self.copy_to_watch_button.clicked.connect(self.copy_to_watch)
        self.copy_to_local_button = QPushButton("← Copy to Computer")
        self.copy_to_local_button.clicked.connect(self.copy_to_local)
        self.delete_watch_button = QPushButton("Delete from Watch")
        self.delete_watch_button.clicked.connect(self.delete_from_watch)
        self.refresh_watch_button = QPushButton("Refresh Watch")
        self.refresh_watch_button.clicked.connect(self._refresh_watch)

        for btn in (
            self.copy_to_watch_button,
            self.copy_to_local_button,
            self.delete_watch_button,
            self.refresh_watch_button,
        ):
            vbox.addWidget(btn)
        vbox.addStretch(1)
        self._watch_controls = [
            self.watch_list,
            self.watch_up_button,
            self.watch_root_button,
            self.copy_to_watch_button,
            self.copy_to_local_button,
            self.delete_watch_button,
            self.refresh_watch_button,
        ]
        return vbox

    # Local navigation -------------------------------------------------------
    def _local_go_home(self) -> None:
        self.local_current = Path.home()
        self._refresh_local()

    def _local_go_up(self) -> None:
        parent = self.local_current.parent
        if parent != self.local_current:
            self.local_current = parent
            self._refresh_local()

    def _local_choose_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select local folder", str(self.local_current))
        if directory:
            self.local_current = Path(directory)
            self._refresh_local()

    def _local_open(self, item: QListWidgetItem) -> None:
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        if path.is_dir():
            self.local_current = path
            self._refresh_local()

    # Watch navigation -------------------------------------------------------
    def _watch_go_up(self) -> None:
        if not self.watch_current or not self.watch_mount_root:
            return
        if self.watch_current == self.watch_mount_root:
            return
        parent = self.watch_current.parent
        if parent != self.watch_current:
            self.watch_current = parent
            self._refresh_watch()

    def _watch_go_root(self) -> None:
        if self.watch_root is None:
            return
        self.watch_current = self.watch_root
        self._refresh_watch()

    def _watch_open(self, item: QListWidgetItem) -> None:
        is_dir = bool(item.data(Qt.ItemDataRole.UserRole + 1))
        if not is_dir:
            return
        self.watch_current = Path(item.data(Qt.ItemDataRole.UserRole))
        self._refresh_watch()

    # Actions ----------------------------------------------------------------
    def copy_to_watch(self) -> None:
        if not self.watch_current:
            QMessageBox.information(self, "No watch", "Connect and mount a watch first.")
            return
        local_paths = self._selected_local_paths()
        if not local_paths:
            QMessageBox.information(self, "No files", "Select local files or folders first.")
            return
        auto_convert = self.auto_convert_provider()
        self._run_task(
            "Copying to watch",
            lambda log: copy_local_items_to_watch(local_paths, self.watch_current, auto_convert, log=log),
            on_success=lambda *_: self._refresh_watch(),
        )

    def copy_to_local(self) -> None:
        watch_entries = self._selected_watch_entries()
        if not watch_entries:
            QMessageBox.information(self, "No files", "Select watch files first.")
            return
        directory = QFileDialog.getExistingDirectory(self, "Select destination folder", str(self.local_current))
        if not directory:
            return
        dest_path = Path(directory)
        self.local_current = dest_path
        self._run_task(
            "Copying to computer",
            lambda log: copy_watch_items_to_local(watch_entries, dest_path, log=log),
            on_success=lambda *_: self._refresh_local(),
        )

    def delete_from_watch(self) -> None:
        watch_entries = self._selected_watch_entries()
        if not watch_entries:
            QMessageBox.information(self, "No selection", "Select watch files to delete.")
            return
        if QMessageBox.question(self, "Delete", "Remove the selected items from the watch?") != QMessageBox.StandardButton.Yes:
            return
        self._run_task(
            "Deleting from watch",
            lambda log: delete_watch_items(watch_entries, log=log),
            on_success=lambda *_: self._refresh_watch(),
        )

    # Refresh helpers --------------------------------------------------------
    def _refresh_local(self) -> None:
        self.local_path_label.setText(str(self.local_current))
        self.local_list.clear()
        try:
            iter_entries = list(self.local_current.iterdir())
        except PermissionError:
            QMessageBox.warning(self, "Access denied", f"Cannot access {self.local_current}")
            iter_entries = []
        entries = sorted(iter_entries, key=lambda p: (not p.is_dir(), p.name.lower()))
        for entry in entries:
            item = QListWidgetItem(example_label(entry))
            item.setData(Qt.ItemDataRole.UserRole, str(entry))
            self.local_list.addItem(item)

    def _refresh_watch(self) -> None:
        if not self.watch_current:
            self.watch_path_label.setText("No device connected")
            self.watch_list.clear()
            self._set_watch_enabled(False)
            return
        self.watch_path_label.setText(str(self.watch_current))
        self._set_watch_enabled(True)
        self.watch_list.clear()
        entries = sorted(list_watch_entries(self.watch_current), key=lambda e: (not e.is_dir, e.name.lower()))
        for entry in entries:
            label = f"{entry.name}/" if entry.is_dir else entry.name
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, str(self.watch_current / entry.name))
            item.setData(Qt.ItemDataRole.UserRole + 1, entry.is_dir)
            self.watch_list.addItem(item)

    def _selected_local_paths(self) -> List[Path]:
        return [Path(item.data(Qt.ItemDataRole.UserRole)) for item in self.local_list.selectedItems()]

    def _selected_watch_entries(self) -> List[tuple[Path, bool]]:
        entries: List[tuple[Path, bool]] = []
        for item in self.watch_list.selectedItems():
            path = Path(item.data(Qt.ItemDataRole.UserRole))
            is_dir = bool(item.data(Qt.ItemDataRole.UserRole + 1))
            entries.append((path, is_dir))
        return entries

    # Internal utilities -----------------------------------------------------
    def _update_watch_paths(self) -> None:
        if self.mount and self.profile:
            self.watch_mount_root = self.mount.path
            self.watch_root = self.mount.build_music_dir(self.profile.normalized_music_subdir)
            self.watch_current = self.watch_root
        else:
            self.watch_mount_root = None
            self.watch_root = None
            self.watch_current = None
        self._refresh_watch()

    def _set_watch_enabled(self, enabled: bool) -> None:
        for widget in self._watch_controls:
            widget.setEnabled(enabled)

    # Worker plumbing --------------------------------------------------------
    def _run_task(self, description: str, task_callable, on_success=None) -> None:
        if self._task_running:
            QMessageBox.information(self, "Busy", "Please wait for the current operation to finish.")
            return
        self._task_running = True
        self._set_enabled(False)
        worker = GioWorker(description, task_callable)
        worker.signals.log.connect(self.log_fn)
        worker.signals.error.connect(self._task_error)
        worker.signals.finished.connect(lambda result: self._task_finished(result, on_success))
        self.thread_pool.start(worker)

    def _task_finished(self, result, callback) -> None:
        self._task_running = False
        self._set_enabled(True)
        if callback:
            callback(result)

    def _task_error(self, message: str) -> None:
        self.log_fn(message)
        QMessageBox.critical(self, "Operation failed", message)
        self._task_running = False
        self._set_enabled(True)

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (
            self.local_list,
            self.local_up_button,
            self.local_home_button,
            self.local_choose_button,
            *self._watch_controls,
        ):
            widget.setEnabled(enabled)


def example_label(path: Path) -> str:
    return f"{path.name}/" if path.is_dir() else path.name
