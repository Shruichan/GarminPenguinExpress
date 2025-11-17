#!/usr/bin/env bash
set -euo pipefail

if ! command -v rpmbuild >/dev/null 2>&1; then
  echo "rpmbuild is required but not installed. On Fedora: sudo dnf install rpm-build. On Ubuntu/Debian: sudo apt install rpm." >&2
  exit 1
fi

if ! command -v pyinstaller >/dev/null 2>&1; then
  echo "pyinstaller is required. Activate the venv and run 'pip install pyinstaller'." >&2
  exit 1
fi

ROOT_DIR=$(cd -- "$(dirname "$0")/.." && pwd)
DIST_DIR="$ROOT_DIR/dist"
RPM_DIR="$DIST_DIR/rpm"
RPMBUILD_ROOT="$RPM_DIR/rpmbuild"
ENTRYPOINT="$ROOT_DIR/src/garmin_penguin_express/__main__.py"
APP_NAME="GarminPenguinExpress"
PKG_NAME="garmin-penguin-express"
ICON_SRC="$ROOT_DIR/assets/icon.png"
DESKTOP_SRC="$ROOT_DIR/packaging/garmin-penguin-express.desktop"
SPEC_TEMPLATE="$ROOT_DIR/packaging/rpm/garmin-penguin-express.spec.in"

VERSION=$(python3 - <<'PY'
import pathlib
import tomllib
pyproject = pathlib.Path('pyproject.toml')
data = tomllib.loads(pyproject.read_text())
print(data['project']['version'])
PY
)

echo "Building PyInstaller binary for RPM..."
pyinstaller --noconfirm --onefile --name "$APP_NAME" "$ENTRYPOINT"
BIN_PATH="$DIST_DIR/$APP_NAME"
if [[ ! -x "$BIN_PATH" ]]; then
  echo "Binary not found at $BIN_PATH" >&2
  exit 1
fi

rm -rf "$RPM_DIR"
mkdir -p "$RPMBUILD_ROOT"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}

WORK_SRC="$RPM_DIR/source"
mkdir -p "$WORK_SRC"
cp "$BIN_PATH" "$WORK_SRC/GarminPenguinExpress"
cp "$DESKTOP_SRC" "$WORK_SRC/garmin-penguin-express.desktop"
cp "$ICON_SRC" "$WORK_SRC/icon.png"

ARCHIVE_NAME="$PKG_NAME-$VERSION.tar.gz"
tar -C "$WORK_SRC" -czf "$RPMBUILD_ROOT/SOURCES/$ARCHIVE_NAME" .
sed "s/@VERSION@/$VERSION/g" "$SPEC_TEMPLATE" > "$RPMBUILD_ROOT/SPECS/$PKG_NAME.spec"

rpmbuild --define "_topdir $RPMBUILD_ROOT" -bb "$RPMBUILD_ROOT/SPECS/$PKG_NAME.spec"

find "$RPMBUILD_ROOT/RPMS" -name '*.rpm' -exec cp {} "$DIST_DIR" \;
echo "RPM packages copied to $DIST_DIR"
