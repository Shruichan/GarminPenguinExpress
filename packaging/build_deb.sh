#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname "$0")/.." && pwd)
SRC_DIR="$ROOT_DIR/src/garmin_penguin_express"
DIST_DIR="$ROOT_DIR/dist"
APP_NAME="GarminPenguinExpress"
PKG_NAME="garmin-penguin-express"
ENTRYPOINT="$SRC_DIR/__main__.py"
DESKTOP_SRC="$ROOT_DIR/packaging/garmin-penguin-express.desktop"
ICON_SRC="$ROOT_DIR/assets/icon.png"

if ! command -v pyinstaller >/dev/null 2>&1; then
  echo "pyinstaller is required. Install it with 'pip install pyinstaller'." >&2
  exit 1
fi

VERSION=$(python3 - <<'PY'
import pathlib
import tomllib
pyproject = pathlib.Path('pyproject.toml')
data = tomllib.loads(pyproject.read_text())
print(data['project']['version'])
PY
)

echo "Building PyInstaller binary..."
pyinstaller --noconfirm --onefile --name "$APP_NAME" "$ENTRYPOINT"

BIN_PATH="$DIST_DIR/$APP_NAME"
if [[ ! -x "$BIN_PATH" ]]; then
  echo "PyInstaller binary not found at $BIN_PATH" >&2
  exit 1
fi

DEB_ROOT="$DIST_DIR/deb/${PKG_NAME}_${VERSION}_amd64"
BIN_DEST="$DEB_ROOT/usr/bin"
CONTROL_DIR="$DEB_ROOT/DEBIAN"
DESKTOP_DEST="$DEB_ROOT/usr/share/applications"
ICON_DEST="$DEB_ROOT/usr/share/icons/hicolor/256x256/apps"

rm -rf "$DEB_ROOT"
mkdir -p "$BIN_DEST" "$CONTROL_DIR" "$DESKTOP_DEST" "$ICON_DEST"
cp "$BIN_PATH" "$BIN_DEST/$APP_NAME"
chmod 755 "$BIN_DEST/$APP_NAME"
install -m 644 "$DESKTOP_SRC" "$DESKTOP_DEST/$PKG_NAME.desktop"
install -m 644 "$ICON_SRC" "$ICON_DEST/$PKG_NAME.png"

cat > "$CONTROL_DIR/control" <<CONTROL
Package: $PKG_NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Depends: libglib2.0-0, gvfs, gvfs-fuse, ffmpeg
Maintainer: Garmin Penguin Express
Description: Simple Garmin Express-style music sync helper for GVFS/MTP watches
CONTROL

dpkg-deb --build "$DEB_ROOT"

echo "Created $(dirname "$DEB_ROOT")/$(basename "$DEB_ROOT").deb"
