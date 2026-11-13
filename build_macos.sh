#!/usr/bin/env bash
# build_macos.sh - builds dist/WinDashboard.app and dist/WinDashboard-macos.zip (macOS)
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/pyinstaller ]; then
    echo "ERROR: PyInstaller not found in .venv - run ./setup_macos.sh first."
    exit 1
fi

# Only Apple Silicon is supported. A terminal running under Rosetta reports x86_64 too.
if [ "$(.venv/bin/python -c 'import platform; print(platform.machine())')" != "arm64" ]; then
    echo "ERROR: WinDashboard is built for Apple Silicon (arm64) only."
    echo "Run the build on an Apple Silicon Mac, in a terminal that is not using Rosetta,"
    echo "with an arm64 or universal2 Python (re-create .venv with ./setup_macos.sh if needed)."
    exit 1
fi

# .icns icon made from the PNG files
ICONSET=build/app.iconset
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for size in 16 32 128 256; do
    cp "assets/png/app-$size.png"         "$ICONSET/icon_${size}x${size}.png"
    cp "assets/png/app-$((size * 2)).png" "$ICONSET/icon_${size}x${size}@2x.png"
done
cp assets/png/app-512.png "$ICONSET/icon_512x512.png"
iconutil -c icns "$ICONSET" -o build/app.icns

ICONS=()
for size in 16 32 48 64 128 256; do
    ICONS+=(--add-data "assets/png/app-$size.png:assets/png")
done

# No --onefile: for .app bundles it is deprecated and causes problems
.venv/bin/pyinstaller --windowed --clean --noconfirm \
    --name WinDashboard \
    --target-arch arm64 \
    --icon build/app.icns \
    "${ICONS[@]}" \
    main_window.pyw

# ditto keeps symbolic links and permissions; plain zip breaks the .app
rm -f dist/WinDashboard-macos.zip
ditto -c -k --keepParent dist/WinDashboard.app dist/WinDashboard-macos.zip

echo
echo "Build finished: dist/WinDashboard.app"
echo "Archive for distribution: dist/WinDashboard-macos.zip"
