#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname "$0")/.." && pwd)
DIST_DIR="$ROOT_DIR/dist"
APPDIR="$DIST_DIR/appimage/AppDir"
APP_NAME="GarminPenguinExpress"
PKG_NAME="garmin-penguin-express"
ENTRYPOINT="$ROOT_DIR/src/garmin_penguin_express/__main__.py"
ICON_SRC="$ROOT_DIR/assets/icon.png"
TOOLS_DIR="$ROOT_DIR/packaging/tools"
APPIMAGE_TOOL="$TOOLS_DIR/appimagetool"

if ! command -v pyinstaller >/dev/null 2>&1; then
  echo "pyinstaller is required. Activate the venv and run 'pip install pyinstaller'." >&2
  exit 1
fi

mkdir -p "$DIST_DIR" "$TOOLS_DIR"
VERSION=$(python3 - <<'PY'
import pathlib
import tomllib
pyproject = pathlib.Path('pyproject.toml')
data = tomllib.loads(pyproject.read_text())
print(data['project']['version'])
PY
)

echo "Building PyInstaller binary for AppImage..."
pyinstaller --noconfirm --onefile --name "$APP_NAME" "$ENTRYPOINT"
BIN_PATH="$DIST_DIR/$APP_NAME"
if [[ ! -x "$BIN_PATH" ]]; then
  echo "Binary $BIN_PATH not found" >&2
  exit 1
fi

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp "$BIN_PATH" "$APPDIR/usr/bin/$APP_NAME"
chmod 755 "$APPDIR/usr/bin/$APP_NAME"

cat > "$APPDIR/AppRun" <<'APP'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/GarminPenguinExpress" "$@"
APP
chmod 755 "$APPDIR/AppRun"

DESKTOP_PATH="$APPDIR/$PKG_NAME.desktop"
cat > "$DESKTOP_PATH" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Garmin Penguin Express
Exec=$APP_NAME
Icon=$PKG_NAME
Categories=AudioVideo;Utility;
Terminal=false
DESKTOP

install -Dm644 "$DESKTOP_PATH" "$APPDIR/usr/share/applications/$PKG_NAME.desktop"
cp "$ICON_SRC" "$APPDIR/$PKG_NAME.png"
install -Dm644 "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/256x256/apps/$PKG_NAME.png"

if [[ ! -x "$APPIMAGE_TOOL" ]]; then
  echo "Downloading appimagetool..."
  curl -L -o "$APPIMAGE_TOOL" "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
  chmod +x "$APPIMAGE_TOOL"
fi

APPIMAGE_OUT="$DIST_DIR/GarminPenguinExpress-${VERSION}-x86_64.AppImage"
"$APPIMAGE_TOOL" "$DIST_DIR/appimage/AppDir" "$APPIMAGE_OUT"
chmod +x "$APPIMAGE_OUT"
echo "AppImage created at $APPIMAGE_OUT"
