#!/usr/bin/env bash
# setup_lin.sh - creates the .venv virtual environment and installs the libraries (Linux)
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found. Install Python 3.10 or newer with your package manager."
    exit 1
fi

# venv, ensurepip and tkinter are separate system packages on many distributions
if ! python3 -c "import venv, ensurepip, tkinter" >/dev/null 2>&1; then
    echo "Installing missing system packages (venv, pip, tkinter) - sudo may ask for your password."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y python3-venv python3-pip python3-tk
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3-pip python3-tkinter
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --needed --noconfirm python-pip tk
    elif command -v zypper >/dev/null 2>&1; then
        sudo zypper install -y python3-pip python3-tk
    else
        echo "ERROR: unknown package manager. Install by hand: Python venv module, pip and tkinter."
        exit 1
    fi
    if ! python3 -c "import venv, ensurepip, tkinter" >/dev/null 2>&1; then
        echo "ERROR: venv, ensurepip or tkinter still missing after the installation."
        exit 1
    fi
fi

if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"; then
    echo "ERROR: Python 3.10 or newer is required, found $(python3 --version)."
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    echo "Creating virtual environment .venv ..."
    python3 -m venv .venv
fi

.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -U -r requirements.txt pyinstaller

echo
echo "Setup finished."
echo "  Run the application:   .venv/bin/python main_window.pyw"
echo "  Build the executable:  ./build_lin.sh"
