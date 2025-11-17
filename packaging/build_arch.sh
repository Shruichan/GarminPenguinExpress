#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname "$0")/.." && pwd)
DIST_DIR="$ROOT_DIR/dist"
ARCH_DIR="$DIST_DIR/arch/garmin-penguin-express-bin"
ENTRYPOINT="$ROOT_DIR/src/garmin_penguin_express/__main__.py"
APP_NAME="GarminPenguinExpress"
PKG_NAME="garmin-penguin-express"
ICON_SRC="$ROOT_DIR/assets/icon.png"
DESKTOP_SRC="$ROOT_DIR/packaging/garmin-penguin-express.desktop"
PKGBUILD_TEMPLATE="$ROOT_DIR/packaging/arch/PKGBUILD.in"

if ! command -v pyinstaller >/dev/null 2>&1; then
  echo "pyinstaller is required. Activate the venv and run 'pip install pyinstaller'." >&2
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

echo "Building PyInstaller binary for Arch package..."
pyinstaller --noconfirm --onefile --name "$APP_NAME" "$ENTRYPOINT"
BIN_PATH="$DIST_DIR/$APP_NAME"
if [[ ! -x "$BIN_PATH" ]]; then
  echo "Binary not found at $BIN_PATH" >&2
  exit 1
fi

rm -rf "$ARCH_DIR"
mkdir -p "$ARCH_DIR"
cp "$BIN_PATH" "$ARCH_DIR/GarminPenguinExpress"
cp "$DESKTOP_SRC" "$ARCH_DIR/garmin-penguin-express.desktop"
cp "$ICON_SRC" "$ARCH_DIR/icon.png"
sed "s/@VERSION@/$VERSION/g" "$PKGBUILD_TEMPLATE" > "$ARCH_DIR/PKGBUILD"

echo "Arch package sources prepared at $ARCH_DIR"
if command -v makepkg >/dev/null 2>&1; then
  echo "Detected makepkg. Building package..."
  (cd "$ARCH_DIR" && makepkg -sf)
else
  echo "makepkg not found; run 'cd $ARCH_DIR && makepkg -si' on an Arch-based system to build the package." >&2
fi
