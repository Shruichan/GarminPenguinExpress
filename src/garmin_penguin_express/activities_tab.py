"""Activities & Workouts tab implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import partial
from pathlib import Path
from typing import Callable, List

from PyQt6.QtCore import QDate, Qt, QThreadPool
from PyQt6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .activity_sync import ActivityEntry, ActivityRepository
from .connect_client import ConnectClient, ConnectClientError
from .gio_utils import GVFSMount
from .watch_profiles import WatchProfile
from .workout_manager import (
    SPORT_TYPES,
    WorkoutManager,
    WorkoutTemplate,
    copy_fit_bytes_to_watch,
    sanitize_filename,
)
from .workers import GioWorker


@dataclass
class WorkoutUploadResult:
    workout_id: int
    filename: str | None = None


class ActivitiesTab(QWidget):
    """UI for Bluetooth passthrough (activity upload) and workout creation."""

    def __init__(self, parent: QWidget | None, log_fn: Callable[[str], None]) -> None:
        super().__init__(parent)
        self.log_fn = log_fn
        self.profile: WatchProfile | None = None
        self.mount: GVFSMount | None = None

        self.thread_pool = QThreadPool(self)
        self.activity_repo = ActivityRepository()
        self.workout_manager = WorkoutManager()
        self.connect_client = ConnectClient()

        self.activities: List[ActivityEntry] = []
        self._busy = False

        self.watch_label = QLabel("Watch profile: –")
        self.mount_label = QLabel("Mounted at: –")
        self.connect_status_label = QLabel("Not logged in to Garmin Connect")

        self.username_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.mfa_input = QLineEdit()
        self.mfa_input.setPlaceholderText("Optional")
        self.login_button = QPushButton("Login")
        self.logout_button = QPushButton("Logout")
        self.auto_upload_checkbox = QCheckBox("Auto-upload new activities")
        self.auto_upload_checkbox.setChecked(False)

        self.activity_table = QTableWidget(0, 6)
        self.refresh_button = QPushButton("Refresh watch")
        self.copy_button = QPushButton("Copy to Computer…")
        self.upload_button = QPushButton("Upload to Garmin Connect")
        self.mark_uploaded_button = QPushButton("Mark as Uploaded")

        self.workout_list = QListWidget()
        self.workout_name_input = QLineEdit()
        self.workout_warmup_input = QSpinBox()
        self.workout_interval_input = QSpinBox()
        self.workout_recovery_input = QSpinBox()
        self.workout_repeats_input = QSpinBox()
        self.workout_cooldown_input = QSpinBox()
        self.schedule_date = QDateEdit()

        self.add_workout_button = QPushButton("Add Template")
        self.delete_workout_button = QPushButton("Remove Template")
        self.upload_workout_button = QPushButton("Upload to Connect")
        self.send_watch_button = QPushButton("Send to Watch")
        self.schedule_button = QPushButton("Schedule Workout")

        self._build_ui()
        self._connect_signals()
        self._populate_workouts()
        self._update_connect_status()
        self._set_activity_controls(False)

    # UI builders ---------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout()
        layout.addWidget(self._build_status_box())
        body = QHBoxLayout()
        body.addWidget(self._build_activities_box(), 3)
        body.addWidget(self._build_workouts_box(), 2)
        layout.addLayout(body)
        self.setLayout(layout)

    def _build_status_box(self) -> QGroupBox:
        box = QGroupBox("Status")
        vbox = QVBoxLayout()
        vbox.addWidget(self.watch_label)
        vbox.addWidget(self.mount_label)
        vbox.addWidget(self.connect_status_label)

        form = QFormLayout()
        self.username_input.setPlaceholderText("you@example.com")
        form.addRow("Username", self.username_input)
        form.addRow("Password", self.password_input)
        form.addRow("MFA code", self.mfa_input)
        button_row = QHBoxLayout()
        button_row.addWidget(self.login_button)
        button_row.addWidget(self.logout_button)
        vbox.addLayout(form)
        vbox.addLayout(button_row)
        vbox.addWidget(self.auto_upload_checkbox)
        box.setLayout(vbox)
        return box

    def _build_activities_box(self) -> QGroupBox:
        box = QGroupBox("Watch Activities")
        vbox = QVBoxLayout()
        self.activity_table.setHorizontalHeaderLabels(
            ["File", "Source", "Date", "Duration", "Uploaded", "Upload ID"]
        )
        self.activity_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.activity_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.activity_table.setSelectionMode(QTableWidget.SelectionMode.MultiSelection)

        button_row = QHBoxLayout()
        button_row.addWidget(self.refresh_button)
        button_row.addWidget(self.copy_button)
        button_row.addWidget(self.upload_button)
        button_row.addWidget(self.mark_uploaded_button)

        vbox.addWidget(self.activity_table)
        vbox.addLayout(button_row)
        box.setLayout(vbox)
        return box

    def _build_workouts_box(self) -> QGroupBox:
        box = QGroupBox("Workouts & Calendar")
        vbox = QVBoxLayout()
        self.workout_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        vbox.addWidget(QLabel("Templates"))
        vbox.addWidget(self.workout_list, 2)

        form = QFormLayout()
        self.workout_name_input.setPlaceholderText("Tempo Tuesday")
        form.addRow("Name", self.workout_name_input)

        self.workout_warmup_input.setRange(0, 3600)
        self.workout_warmup_input.setValue(300)
        form.addRow("Warmup (s)", self.workout_warmup_input)

        self.workout_interval_input.setRange(30, 7200)
        self.workout_interval_input.setValue(60)
        form.addRow("Interval (s)", self.workout_interval_input)

        self.workout_recovery_input.setRange(15, 3600)
        self.workout_recovery_input.setValue(60)
        form.addRow("Recovery (s)", self.workout_recovery_input)

        self.workout_repeats_input.setRange(1, 99)
        self.workout_repeats_input.setValue(6)
        form.addRow("Repeats", self.workout_repeats_input)

        self.workout_cooldown_input.setRange(0, 3600)
        self.workout_cooldown_input.setValue(300)
        form.addRow("Cooldown (s)", self.workout_cooldown_input)

        self.sport_combo = QLineEdit("running")
        form.addRow("Sport (running/cycling)", self.sport_combo)

        self.schedule_date.setDate(QDate.currentDate())
        self.schedule_date.setCalendarPopup(True)
        form.addRow("Schedule date", self.schedule_date)

        vbox.addLayout(form)
        button_row = QHBoxLayout()
        button_row.addWidget(self.add_workout_button)
        button_row.addWidget(self.delete_workout_button)
        vbox.addLayout(button_row)

        action_row = QHBoxLayout()
        action_row.addWidget(self.upload_workout_button)
        action_row.addWidget(self.send_watch_button)
        action_row.addWidget(self.schedule_button)
        vbox.addLayout(action_row)
        box.setLayout(vbox)
        return box

    def _connect_signals(self) -> None:
        self.login_button.clicked.connect(self._handle_login)
        self.logout_button.clicked.connect(self._handle_logout)
        self.refresh_button.clicked.connect(self.refresh_activities)
        self.copy_button.clicked.connect(self.copy_selected_to_local)
        self.upload_button.clicked.connect(self.upload_selected_activities)
        self.mark_uploaded_button.clicked.connect(self.mark_selected_uploaded)

        self.add_workout_button.clicked.connect(self._add_workout_template)
        self.delete_workout_button.clicked.connect(self._delete_selected_template)
        self.upload_workout_button.clicked.connect(self._upload_template_only)
        self.send_watch_button.clicked.connect(self._send_template_to_watch)
        self.schedule_button.clicked.connect(self._schedule_template)
        self.auto_upload_checkbox.toggled.connect(lambda _: None)

    # Context hooks -------------------------------------------------------
    def set_profile(self, profile: WatchProfile | None) -> None:
        self.profile = profile
        self.watch_label.setText(f"Watch profile: {profile.label}" if profile else "Watch profile: –")

    def set_mount(self, mount: GVFSMount | None) -> None:
        self.mount = mount
        self.mount_label.setText(f"Mounted at: {mount.path}" if mount else "Mounted at: –")
        if self.auto_upload_checkbox.isChecked() and mount:
            self.refresh_activities()

    # Activity logic ------------------------------------------------------
    def refresh_activities(self) -> None:
        if not self.mount:
            QMessageBox.information(self, "No device", "Connect and mount a watch first.")
            return
        self._run_async(
            "Scanning watch activities",
            lambda log: self.activity_repo.scan(self.mount.path),
            on_success=self._populate_activity_table,
        )

    def copy_selected_to_local(self) -> None:
        entries = self._selected_entries()
        if not entries:
            QMessageBox.information(self, "No selection", "Select activities to copy.")
            return
        destination = QFileDialog.getExistingDirectory(self, "Destination folder", str(Path.home()))
        if not destination:
            return
        dest_path = Path(destination)
        self._run_async(
            "Copying activities to computer",
            lambda log: self.activity_repo.copy_to_local(entries, dest_path),
            on_success=lambda results: self.log_fn(f"Copied {len(results or [])} files"),
        )

    def upload_selected_activities(self) -> None:
        entries = self._selected_entries()
        if not entries:
            QMessageBox.information(self, "No selection", "Select activities to upload.")
            return
        try:
            self.connect_client.ensure_authenticated()
        except ConnectClientError as exc:
            QMessageBox.warning(self, "Garmin Connect", str(exc))
            return
        self._run_async(
            "Uploading activities",
            lambda log: self._upload_entries(entries, log),
            on_success=lambda _: self._refresh_after_upload(entries),
        )

    def mark_selected_uploaded(self) -> None:
        entries = self._selected_entries()
        if not entries:
            return
        self.activity_repo.mark_uploaded(entries, [None] * len(entries))
        self.refresh_activities()

    def _upload_entries(self, entries: List[ActivityEntry], log: Callable[[str], None]) -> List[str | None]:
        upload_ids: List[str | None] = []
        for entry in entries:
            log(f"Uploading {entry.relative_path}")
            result = self.connect_client.upload_activity(entry.path)
            upload_id = extract_upload_id(result)
            upload_ids.append(upload_id)
        self.activity_repo.mark_uploaded(entries, upload_ids)
        return upload_ids

    def _refresh_after_upload(self, entries: List[ActivityEntry]) -> None:
        QMessageBox.information(self, "Upload complete", f"Uploaded {len(entries)} activities.")
        self.refresh_activities()

    def _populate_activity_table(self, entries: List[ActivityEntry]) -> None:
        self.activities = entries or []
        self.activity_table.setRowCount(len(self.activities))
        for row, entry in enumerate(self.activities):
            self.activity_table.setItem(row, 0, QTableWidgetItem(Path(entry.relative_path).name))
            self.activity_table.setItem(row, 1, QTableWidgetItem(entry.source))
            self.activity_table.setItem(
                row,
                2,
                QTableWidgetItem(entry.recorded_time.isoformat(sep=" ") if entry.recorded_time else "Unknown"),
            )
            duration_text = f"{int(entry.duration_seconds or 0)}s"
            self.activity_table.setItem(row, 3, QTableWidgetItem(duration_text))
            self.activity_table.setItem(row, 4, QTableWidgetItem("✅" if entry.uploaded else "—"))
            self.activity_table.setItem(row, 5, QTableWidgetItem(entry.upload_id or ""))
        self._set_activity_controls(bool(entries))

    def _selected_entries(self) -> List[ActivityEntry]:
        rows = set(index.row() for index in self.activity_table.selectionModel().selectedRows())
        return [self.activities[idx] for idx in sorted(rows) if 0 <= idx < len(self.activities)]

    def _set_activity_controls(self, enabled: bool) -> None:
        for widget in (self.copy_button, self.upload_button, self.mark_uploaded_button):
            widget.setEnabled(enabled)

    # Workout logic -------------------------------------------------------
    def _populate_workouts(self) -> None:
        self.workout_list.clear()
        for template in self.workout_manager.templates:
            item = QListWidgetItem(f"{template.name} ({template.sport}) [{template.estimated_duration // 60} min]")
            item.setData(Qt.ItemDataRole.UserRole, template)
            self.workout_list.addItem(item)

    def _current_template(self) -> tuple[int, WorkoutTemplate] | tuple[None, None]:
        current = self.workout_list.currentRow()
        if current < 0 or current >= self.workout_list.count():
            return None, None
        template = self.workout_list.currentItem().data(Qt.ItemDataRole.UserRole)
        return current, template

    def _add_workout_template(self) -> None:
        name = self.workout_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Workout", "Enter a name for the template.")
            return
        sport = self.sport_combo.text().strip().lower() or "running"
        if sport not in SPORT_TYPES:
            QMessageBox.warning(self, "Workout", f"Unsupported sport '{sport}'. Use one of {', '.join(SPORT_TYPES)}.")
            return
        template = WorkoutTemplate(
            name=name,
            sport=sport,
            warmup_seconds=self.workout_warmup_input.value(),
            interval_seconds=self.workout_interval_input.value(),
            recovery_seconds=self.workout_recovery_input.value(),
            repeats=self.workout_repeats_input.value(),
            cooldown_seconds=self.workout_cooldown_input.value(),
        )
        self.workout_manager.add_template(template)
        self._populate_workouts()
        self.workout_name_input.clear()
        QMessageBox.information(self, "Workout", "Template saved.")

    def _delete_selected_template(self) -> None:
        index, template = self._current_template()
        if template is None:
            return
        self.workout_manager.delete_template(index)
        self._populate_workouts()

    def _upload_template_only(self) -> None:
        _, template = self._current_template()
        if not template:
            QMessageBox.information(self, "Workout", "Select a template first.")
            return
        try:
            self.connect_client.ensure_authenticated()
        except ConnectClientError as exc:
            QMessageBox.warning(self, "Garmin Connect", str(exc))
            return
        payload = self.workout_manager.build_payload(template)
        self._run_async(
            f"Uploading workout {template.name}",
            lambda log: self.connect_client.upload_workout(payload),
            on_success=lambda resp: QMessageBox.information(
                self, "Workout uploaded", f"Created workout ID {resp.get('workoutId', 'unknown')}"
            ),
        )

    def _send_template_to_watch(self) -> None:
        _, template = self._current_template()
        if not template:
            QMessageBox.information(self, "Workout", "Select a template first.")
            return
        if not self.mount:
            QMessageBox.warning(self, "No device", "Connect a watch first.")
            return
        try:
            self.connect_client.ensure_authenticated()
        except ConnectClientError as exc:
            QMessageBox.warning(self, "Garmin Connect", str(exc))
            return
        payload = self.workout_manager.build_payload(template)
        dest_dir = self.mount.path / "GARMIN" / "NewFiles"

        def task(log: Callable[[str], None]) -> WorkoutUploadResult:
            result = self.connect_client.upload_workout(payload)
            workout_id = int(result.get("workoutId"))
            log(f"Uploaded workout {workout_id}, downloading FIT asset")
            fit_bytes = self.connect_client.download_workout_fit(workout_id)
            filename = f"{sanitize_filename(template.name)}_{workout_id}.fit"
            copy_fit_bytes_to_watch(fit_bytes, dest_dir, filename)
            return WorkoutUploadResult(workout_id=workout_id, filename=str(dest_dir / filename))

        self._run_async(
            "Sending workout to watch",
            task,
            on_success=lambda result: QMessageBox.information(
                self,
                "Workout transferred",
                f"Workout {result.workout_id} copied to watch as {Path(result.filename or '').name}.",
            ),
        )

    def _schedule_template(self) -> None:
        _, template = self._current_template()
        if not template:
            QMessageBox.information(self, "Workout", "Select a template first.")
            return
        try:
            self.connect_client.ensure_authenticated()
        except ConnectClientError as exc:
            QMessageBox.warning(self, "Garmin Connect", str(exc))
            return
        target_date = self.schedule_date.date().toPyDate()
        payload = self.workout_manager.build_payload(template)

        def task(log: Callable[[str], None]) -> dict:
            result = self.connect_client.upload_workout(payload)
            workout_id = int(result.get("workoutId"))
            log(f"Scheduling workout {workout_id} for {target_date.isoformat()}")
            sport = SPORT_TYPES.get(template.sport, SPORT_TYPES["running"])
            schedule = self.connect_client.schedule_workout(workout_id, sport, target_date)
            return schedule

        self._run_async(
            "Scheduling workout",
            task,
            on_success=lambda _: QMessageBox.information(
                self,
                "Scheduled",
                f"Workout scheduled for {target_date.isoformat()}.",
            ),
        )

    # Auth handlers -------------------------------------------------------
    def _handle_login(self) -> None:
        username = self.username_input.text().strip()
        password = self.password_input.text()
        mfa = self.mfa_input.text().strip() or None
        if not username or not password:
            QMessageBox.warning(self, "Login", "Enter username and password.")
            return
        try:
            self.connect_client.login(username, password, mfa_code=mfa)
        except ConnectClientError as exc:
            QMessageBox.critical(self, "Garmin Connect", str(exc))
            return
        self.password_input.clear()
        self.mfa_input.clear()
        self._update_connect_status()
        QMessageBox.information(self, "Garmin Connect", "Login successful.")

    def _handle_logout(self) -> None:
        self.connect_client.logout()
        self._update_connect_status()

    def _update_connect_status(self) -> None:
        if self.connect_client.is_authenticated():
            user = self.connect_client.username or "session"
            self.connect_status_label.setText(f"Connected as {user}")
        else:
            self.connect_status_label.setText("Not logged in to Garmin Connect")

    # Worker plumbing -----------------------------------------------------
    def _run_async(self, description: str, task_callable, on_success=None) -> None:
        if self._busy:
            QMessageBox.information(self, "Busy", "Wait for the current operation to finish.")
            return
        self._busy = True
        self._set_enabled(False)
        worker = GioWorker(description, task_callable)
        worker.signals.log.connect(self.log_fn)
        worker.signals.error.connect(self._task_error)
        worker.signals.finished.connect(partial(self._task_finished, on_success))
        self.thread_pool.start(worker)

    def _task_finished(self, callback, result) -> None:
        self._busy = False
        self._set_enabled(True)
        if callback:
            callback(result)

    def _task_error(self, message: str) -> None:
        self._busy = False
        self._set_enabled(True)
        self.log_fn(message)
        QMessageBox.critical(self, "Operation failed", message)

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (
            self.refresh_button,
            self.copy_button,
            self.upload_button,
            self.mark_uploaded_button,
            self.add_workout_button,
            self.delete_workout_button,
            self.upload_workout_button,
            self.send_watch_button,
            self.schedule_button,
        ):
            widget.setEnabled(enabled)


def extract_upload_id(response: dict | None) -> str | None:
    if not response:
        return None
    detailed = response.get("detailedImportResult")
    if detailed and "uploadId" in detailed:
        return str(detailed["uploadId"])
    if "uploadId" in response:
        return str(response["uploadId"])
    return None
