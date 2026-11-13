#!/usr/bin/env bash
# build_lin.sh - builds dist/n-dashboard (Linux, one file) plus the icon and install_lin.sh
set -e
cd "$(dirname "$0")"

# python -m PyInstaller, not .venv/bin/pyinstaller: that script keeps the absolute path
# of the folder .venv was created in and breaks when the project folder is renamed
if ! .venv/bin/python -c "import PyInstaller" >/dev/null 2>&1; then
    echo "ERROR: PyInstaller not found in .venv - run ./setup_lin.sh first."
    exit 1
fi

ICONS=()
for size in 16 32 48 64 128 256; do
    ICONS+=(--add-data "assets/png/app-$size.png:assets/png")
done

.venv/bin/python -m PyInstaller --windowed --onefile --clean --noconfirm \
    --name n-dashboard \
    "${ICONS[@]}" \
    main_window.pyw

# An ELF file has no icon of its own: the icon and the installer go next to it
cp assets/png/app-256.png dist/n-dashboard.png
cp install_lin.sh dist/install_lin.sh
chmod +x dist/n-dashboard dist/install_lin.sh

echo
echo "Build finished: dist/n-dashboard"
echo "Install for the current user (menu entry and icon):  dist/install_lin.sh"
