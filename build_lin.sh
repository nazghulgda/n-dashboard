#!/usr/bin/env bash
# build_lin.sh - builds dist/WinDashboard (Linux, one file) plus the icon and install_lin.sh
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/pyinstaller ]; then
    echo "ERROR: PyInstaller not found in .venv - run ./setup_lin.sh first."
    exit 1
fi

ICONS=()
for size in 16 32 48 64 128 256; do
    ICONS+=(--add-data "assets/png/app-$size.png:assets/png")
done

.venv/bin/pyinstaller --windowed --onefile --clean --noconfirm \
    --name WinDashboard \
    "${ICONS[@]}" \
    main_window.pyw

# An ELF file has no icon of its own: the icon and the installer go next to it
cp assets/png/app-256.png dist/WinDashboard.png
cp install_lin.sh dist/install_lin.sh
chmod +x dist/WinDashboard dist/install_lin.sh

echo
echo "Build finished: dist/WinDashboard"
echo "Install for the current user (menu entry and icon):  dist/install_lin.sh"
