#!/usr/bin/env bash
# setup_macos.sh - creates the .venv virtual environment and installs the libraries (macOS)
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found."
    echo "Install Python 3.10 or newer from https://www.python.org/downloads/macos/"
    exit 1
fi

if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"; then
    echo "ERROR: Python 3.10 or newer is required, found $(python3 --version)."
    echo "Install it from https://www.python.org/downloads/macos/"
    exit 1
fi

# Only Apple Silicon is supported; an Intel-only Python (or a terminal under Rosetta)
# would build an x86_64 application
if [ "$(python3 -c 'import platform; print(platform.machine())')" != "arm64" ]; then
    echo "ERROR: this Python runs as $(python3 -c 'import platform; print(platform.machine())'),"
    echo "but WinDashboard supports Apple Silicon (arm64) only."
    echo "Use an Apple Silicon Mac, a terminal without Rosetta, and the universal2 Python"
    echo "from https://www.python.org/downloads/macos/"
    exit 1
fi

if ! python3 -c "import tkinter" >/dev/null 2>&1; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')")
    if command -v brew >/dev/null 2>&1 && [ "$(command -v python3)" = "$(brew --prefix)/bin/python3" ]; then
        echo "Installing tkinter for Homebrew Python $PY_VER ..."
        brew install "python-tk@$PY_VER"
    else
        echo "ERROR: this Python has no tkinter."
        echo "Install Python from https://www.python.org/downloads/macos/ (tkinter included)."
        exit 1
    fi
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
echo "  Build the application: ./build_macos.sh"
