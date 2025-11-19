# Garmin Penguin Express

Garmim Penguin Express is a PyQt based helper that allows you to interact with the storage on your garmin watch and upload or delete music from it in addition to copying music from the watch to your computer. The Garmin Venu4 which was used in testing for this doesnt support FLAC playback so `ffmpeg` was used in order to convert any non mp3 file to mp3 (this is an optional checkbox so if your garmin watch happens to support it you can playback other formats), the helper has a dual pane browser that allows for file navigation on your pc for easy drag and drop music management.

## Install & Run 

- `.deb` (Ubuntu/Debian based): `sudo apt install ./garmin-penguin-express_<version>_amd64.deb`
- AppImage: `chmod +x GarminPenguinExpress-<version>-x86_64.AppImage && ./GarminPenguinExpress-<version>-x86_64.AppImage`
- `.rpm` (Fedora/RHEL): `sudo dnf install garmin-penguin-express-<version>.rpm`
- Arch-based: build/install the PKGBUILD under `dist/arch/garmin-penguin-express-bin/` via `makepkg -si`

Once installed, launch **Garmin Penguin Express** from your desktop menu (or run `GarminPenguinExpress` in a terminal). Plug the watch in, press **Mount via gio**, if it isnt automatically detected/mounted.

## How to contribute

- Make a branch and implement a feature you think is relevant then submit a pull request after testing
- Make a file dump of your watches file system, and upload either a mega or zip containing the structure and some example files to the Watch_Filesystem folder on this repository

## Develop locally

```bash
sudo apt install ffmpeg
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python3 -m garmin_penguin_express
```

## Packaging shortcuts (requires `pyinstaller`)

- `.deb`: `./packaging/build_deb.sh`
- AppImage: `./packaging/build_appimage.sh`
- `.rpm`: `./packaging/build_rpm.sh` (needs `rpmbuild`)
- Arch PKGBUILD: `./packaging/build_arch.sh` → run `makepkg -si` on Arch

## Requirements

- `gio`, `gvfs-fuse`, and `gvfs-backends` (GVFS MTP support).
- `ffmpeg` for optional conversion.
- Watch must expose its storage over MTP when unlocked.


## TODO
- Get art for the favicon
- Figure out what might be needed for maps support
- Start towards feature parity with GarminExpress
- Bluetooth passthrough of some kind for watches with broken bluetooth chips
- Activitiy/workout creation and upload to watch



