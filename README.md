# Garmin Penguin Express

Garmin Penguin Express is a desktop helper that recreates the "copy music" workflow of Garmin Express for Linux desktops. It guides you through mounting a Garmin wearable that exposes its storage over GVFS+MTP and then mirrors the contents of a selected source folder (typically `~/Music/Flacs_MP3`) into the watch's `Internal Storage/Music` directory using `gio` commands so we avoid the usual `cp`/`rsync` FUSE failures.

## Features

- PyQt6 UI with a watch selector and per-transfer prompts so you always choose exactly which folder you want to mirror.
- Buttons for every step of the proven `gio` workflow: reset lingering FUSE mounts, connect via `gio mount`, wipe the watch music folder, copy MP3 files, and unmount.
- Optional auto-conversion (enabled by default) that runs `ffmpeg` to transcode FLAC/OGG/WAV/etc. into MP3s before pushing them to the watch.
- Dual-pane file explorer so you can browse both the computer and the watch storage, copy folders in either direction, or delete files directly on the device.
- Real-time logging area so you can see the exact `gio` feedback without leaving the app.
- Per-user config stored under `~/.config/GarminPenguinExpress/config.json`.
- Works entirely through the GVFS stack, so it behaves exactly like the manual instructions you already validated.

## Goals

- Detect Garmin wearables that show up via GVFS' MTP backend.
- Provide a friendly UI that mirrors Garmin Express' flow: mount → pick what you want → copy/sync.
- Execute the safe `gio` operations (mount, list, remove, copy, unmount) behind buttons so you do not need to run shell scripts.
- Offer a single-button "Sync" that wipes the watch's music folder and recopies the current MP3s.
- Ship with instructions for producing a standalone executable via PyInstaller for distribution.

## Getting Started

```bash
sudo apt install ffmpeg
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

Launch the UI:

```bash
python3 -m garmin_penguin_express
```

### Daily workflow

1. Plug the watch in via USB and wait for it to appear in `gio mount -li`.
2. Start Garmin Penguin Express and pick the watch profile you want to manage.
3. Press **Mount via gio** so GVFS exposes `/run/user/$UID/gvfs/mtp:host=...`.
4. Pick the detected GVFS mount from the combo box (if you only have one, it will auto-select).
5. Leave “Convert non-MP3 files…” checked if you want anything that isn't already MP3 to be run through `ffmpeg` automatically.
6. Hit **Copy Folder to Watch…** or **Sync Folder (wipe + copy)…**; each action opens a system file picker so you can choose the exact source directory for that transfer.
7. Click **Open Watch Explorer** to bring up the dual-pane browser for manual drag/drop style workflows or to copy watch files back to the computer (you'll be prompted for the destination folder when doing so).
8. Press **Unmount** when you're done, then unplug the USB cable and check the watch's Music app.

### Watch Explorer

The explorer window shows your computer (left) and the watch storage (right). Navigate by double-clicking folders or using the Up/Home buttons, then:

- `→ Copy to Watch` uploads the selected local files or folders (converting them to MP3 if the checkbox is still enabled).
- `← Copy to Computer` prompts for a destination folder and downloads the selected watch items there.
- `Delete from Watch` removes whatever is highlighted on the device.
- `Refresh Watch` asks GVFS for the latest directory listing if you plugged/unplugged the device while the window is open.

## Building a stand-alone executable (PyInstaller)

```bash
pip install pyinstaller
pyinstaller --noconfirm --onefile --name GarminPenguinExpress src/garmin_penguin_express/__main__.py
```

The resulting binary will live under `dist/GarminPenguinExpress`. Copy it wherever you want. PyInstaller automatically bundles the Python runtime and PyQt so the target system only needs the standard `gio`/`gvfs` stack.

## Limitations

- You still need `gio`, `gvfsd-mtp`, and udev permissions already working under your user account.
- The tool assumes MP3s are copied; FLAC or AAC will be treated the same if the device supports them.
- Automatic conversion requires `ffmpeg`; uncheck the option if you do not have it installed.
- Real Garmin Express performs metadata management and DRM checks; this helper only mirrors files.

## Roadmap

- Persist user source folders per watch profile.
- Progress bars for each `gio copy` call.
- Detection of multiple MTP endpoints with friendly naming via `gio info` and USB vendor parsing.
