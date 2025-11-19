# Garmin Penguin Express – Bluetooth Passthrough & Activities/Workouts Tab Plan

## Goals
- Let any Garmin watch that can expose its storage over MTP sync activities, health metrics, and workouts without relying on the watch’s Bluetooth radio.
- Mirror the “Bluetooth sync” experience by uploading FIT/JSON payloads directly to Garmin Connect cloud services so that Garmin Connect Mobile on the phone receives the data moments later.
- Extend the UI with a second tab dedicated to activities, workouts, and calendar management so users can copy activities off the watch, build/import workouts, and push them back to the watch and Garmin Connect.

## Research Notes
### Watch filesystem structure (confirmed via connected devices and Garmin documentation)
- `GARMIN/Activity/` – recorded activities (`.fit`).
- `GARMIN/Monitor/` – daily summaries / health data (`.fit`).
- `GARMIN/Workouts/` – workouts synced down from Garmin Connect.
- `GARMIN/NewFiles/` – drop-in location for new workouts/courses/calendar entries generated on the host.
- `GARMIN/Schedule/` (some devices `GARMIN/Calendar/`) – scheduled workout FIT files.
- Watches expect new workouts/schedules to appear as `.fit` payloads generated according to the FIT SDK profiles.

### Garmin Connect upload APIs
- Web Garmin Express uploads activities through `https://connect.garmin.com/modern/proxy/upload-service/upload/.fit`.
- Authentication can be handled via the unofficial `python-garminconnect` / `garth` libraries which perform the same SSO/OAuth flow as Garmin Connect Mobile.
- Once an activity is uploaded to the cloud, Garmin Connect Mobile synchronizes it via HTTPS within seconds, satisfying the “sync to phone” requirement even without actual BLE.
- Workouts and calendar entries can be created through the `workout-service`/`calendar-service` endpoints or by uploading the generated FIT to the user account, then pulling them down to the watch by dropping the files to `NewFiles`.

### Bluetooth passthrough interpretation
- True BLE emulation would require re-implementing Garmin’s proprietary GATT profile and pairing process; this is out of scope and fragile.
- Achieving the user outcome (“data lands in Garmin Connect Mobile without working watch Bluetooth”) is feasible by performing USB → cloud uploads, effectively acting as Garmin Express.
- Optional stretch: expose a BLE peripheral via BlueZ that simply forwards notifications once the cloud upload finishes (nice-to-have, not required for MVP).

### Libraries / tooling
- `python-garminconnect` (MIT) for authentication + REST helpers. The `garth` project can refresh OAuth tokens.
- `fitparse` (read FIT) and `fitencode` or the official FIT SDK python codegen to build workouts/calendar FIT files.
- `pydbus` if we later experiment with BlueZ.
- `watchdog` (optional) for filesystem monitoring of the mounted GVFS tree to auto-detect new files.

## Architecture Overview
### New modules
1. `connect_client.py`
   - Wraps login, token refresh, and the handful of Connect endpoints we need (activity upload, workout creation, calendar assignment).
   - Persists tokens securely (JSON in `~/.config/GarminPenguinExpress/connect_session.json`, optionally guarded by `keyring`).

2. `activity_sync.py`
   - Discovers FIT files under `GARMIN/Activity`, `GARMIN/Monitor`.
   - Maintains a local SQLite/JSON manifest of uploaded files (sha256, filename, timestamp).
   - Provides APIs to copy FITs to the PC, upload them to Connect, or mark them as ignored.

3. `workout_manager.py`
   - Loads workouts from watch/local disk.
   - Offers helpers to create workouts via a simple builder UI (Warmup/Intervals/Cooldown) and encodes them to FIT.
   - Handles pushing workouts or scheduled workouts by writing to `GARMIN/NewFiles` (or `Workouts` for immediate availability) and optionally creating matching calendar entries through `connect_client`.

4. `activities_tab.py`
   - PyQt widget plugged into the new “Activities & Workouts” tab.
   - Displays watch FIT inventory, local library, workout composer, and Bluetooth passthrough upload controls.
   - Talks to `activity_sync` / `workout_manager` using worker threads similar to the existing `FileBrowserWidget`.

### Data flow for “Bluetooth passthrough”
1. User plugs watch in → GVFS mount appears (already handled).
2. `activity_sync.ActivityRepository` scans `GARMIN/Activity`.
3. User selects activities ⇒ click “Upload to Garmin Connect”.
4. `connect_client` uploads FIT via HTTPS, stores upload ID.
5. Upon success we optionally drop a marker file so we never re-upload the same FIT unless user forces it.
6. Garmin Connect Mobile syncs from the cloud, so activities appear in the phone app as if they were synced over BLE.

### Data flow for workouts/calendar
1. User creates or imports a workout in the Activities tab.
2. `workout_manager` encodes it to FIT.
3. User can:
   - Push directly to watch (copy FIT to `GARMIN/NewFiles`).
   - Add to Garmin Connect calendar via REST API (optional) which cascades to phone.
   - Schedule locally (store metadata + push to watch schedule directory).

### UI layout
- Convert the main window to `QTabWidget`.
- Tab 1 “Music” = existing controls.
- Tab 2 “Activities & Workouts” contains four sections:
  1. **Status Header**: active watch/mount, Connect login state, last sync.
  2. **Activities Pane**: list of FITs on watch, metadata preview, buttons for “Copy to computer”, “Upload to Connect”, “Mark as uploaded”.
  3. **Workouts Pane**: local workouts, Create / Import / Export, push to watch/calendar.
  4. **Passthrough Log**: share existing log widget or embed a per-tab console.

## Implementation Phases
1. **Foundation / Dependencies**
   - Add optional dependencies (`python-garminconnect`, `fitparse`, `fitencode`, `watchdog`).
   - Factor a shared thread utility for long-running uploads (reuse `GioWorker` or add `BackgroundWorker` for HTTP tasks).

2. **Tab & wiring**
   - Refactor `MainWindow` to host a `QTabWidget`.
   - Create `ActivitiesTab` skeleton that receives `WatchProfile`, `GVFSMount`, and logging callbacks.
   - Expose signals from `MainWindow` when mount/profile changes so both tabs stay in sync.

3. **Activity ingestion**
   - Implement `ActivityRepository` to list FIT files, parse metadata (date, sport) using `fitparse`.
   - Store manifest in JSON (location, checksum, uploaded flag).
   - Surface UI list with filters (date range, uploaded state).

4. **Garmin Connect client**
   - Build `ConnectClient` that can login with username/password, persist OAuth tokens, and expose:
     - `upload_activity(path_or_bytes)`
     - `create_workout(payload)`
     - `schedule_workout(workout_id, date)`
   - Provide status indicator + logout button in the tab.

5. **Passthrough upload workflow (MVP)**
   - Allow selecting multiple FIT files, upload sequentially, update status.
   - After upload success, mark manifest entry as synced and display Garmin activity ID.
   - Optional “auto upload new activities when detected” toggle.

6. **Workout builder & injection**
   - UI for simple structured workouts (Warmup/Repeat/Cooldown). Store templates as JSON.
   - Encode to FIT using `fitencode` and copy to `GARMIN/NewFiles`.
   - Provide “Add to Garmin Connect Calendar” by calling REST endpoint and optionally writing a scheduled FIT to watch.

7. **Calendar sync to watch**
   - Expose picker for local calendar events (maybe ICS import) and convert to Garmin schedule FIT files.
   - Drop generated FIT into `GARMIN/NewFiles` or `Schedule`.

8. **Stretch: BLE peripheral shim**
   - Investigate presenting a BLE Peripheral via BlueZ that reports “activity upload complete” to emulate watch notifications. Non-critical.

## Risks / Open Questions
- Garmin Connect endpoints are unofficial; rate limiting or auth changes may break uploads. Need good error UX and telemetry.
- FIT generation requires precise profiles per device. We should start with run/cycle workouts and gate advanced steps.
- GVFS latency can make `watchdog` unreliable; may need polling fallback.
- Credential storage must be explicit (warn users if stored unencrypted).
- Calendar format differences between devices (e.g., Fenix vs Venu) must be tested.

## Immediate Next Steps
1. Land GUI refactor with the placeholder Activities tab (done in this change set).
2. Implement `activity_sync` scaffolding with manifest storage.
3. Integrate `python-garminconnect` and surface login fields on the Activities tab.
4. Build FIT parsing pipeline and list activities in the new tab.
5. Implement upload + workout creation flows iteratively, guarding features behind “experimental” toggles until stable.
