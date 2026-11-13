#!/usr/bin/env bash
# build_macos.sh - builds dist/n-dashboard.app and dist/n-dashboard-macos.zip (macOS)
set -e
cd "$(dirname "$0")"

# python -m PyInstaller, not .venv/bin/pyinstaller: that script keeps the absolute path
# of the folder .venv was created in and breaks when the project folder is renamed
if ! .venv/bin/python -c "import PyInstaller" >/dev/null 2>&1; then
    echo "ERROR: PyInstaller not found in .venv - run ./setup_macos.sh first."
    exit 1
fi

# Only Apple Silicon is supported. A terminal running under Rosetta reports x86_64 too.
if [ "$(.venv/bin/python -c 'import platform; print(platform.machine())')" != "arm64" ]; then
    echo "ERROR: n-dashboard is built for Apple Silicon (arm64) only."
    echo "Run the build on an Apple Silicon Mac, in a terminal that is not using Rosetta,"
    echo "with an arm64 or universal2 Python (re-create .venv with ./setup_macos.sh if needed)."
    exit 1
fi

# .icns icon made from the PNG files
ICONSET=build/app.iconset
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
    cp "assets/png/app-$size.png"         "$ICONSET/icon_${size}x${size}.png"
    cp "assets/png/app-$((size * 2)).png" "$ICONSET/icon_${size}x${size}@2x.png"
done
iconutil -c icns "$ICONSET" -o build/app.icns

ICONS=()
for size in 16 32 48 64 128 256; do
    ICONS+=(--add-data "assets/png/app-$size.png:assets/png")
done

# No --onefile: for .app bundles it is deprecated and causes problems
.venv/bin/python -m PyInstaller --windowed --clean --noconfirm \
    --name n-dashboard \
    --target-arch arm64 \
    --icon build/app.icns \
    "${ICONS[@]}" \
    main_window.pyw

# ditto keeps symbolic links and permissions; plain zip breaks the .app
rm -f dist/n-dashboard-macos.zip
ditto -c -k --keepParent dist/n-dashboard.app dist/n-dashboard-macos.zip

echo
echo "Build finished: dist/n-dashboard.app"
echo "Archive for distribution: dist/n-dashboard-macos.zip"
