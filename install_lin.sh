#!/usr/bin/env bash
# install_lin.sh - installs n-dashboard for the current user, no sudo needed.
#   ./install_lin.sh               install (run it from the folder with the n-dashboard binary)
#   ./install_lin.sh --uninstall   remove the program; asks before deleting your data
set -e
cd "$(dirname "$0")"

APP=n-dashboard
ID=n-dashboard
SHARE="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN_DIR="$HOME/.local/bin"
ICON_DIR="$SHARE/icons/hicolor/256x256/apps"
APPS_DIR="$SHARE/applications"
DATA_DIR="$SHARE/$APP"

refresh_desktop() {
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
    gtk-update-icon-cache -f -t "$SHARE/icons/hicolor" >/dev/null 2>&1 || true
}

if [ "$1" = "--uninstall" ]; then
    rm -f "$BIN_DIR/$ID" "$ICON_DIR/$ID.png" "$APPS_DIR/$ID.desktop"
    refresh_desktop
    echo "$APP removed."
    if [ -d "$DATA_DIR" ]; then
        answer=""
        read -r -p "Delete your data as well (tasks, attachments, archive, backups) in $DATA_DIR? [y/N] " answer || true
        case "$answer" in
            [yY]*) rm -rf "$DATA_DIR"; echo "Data deleted." ;;
            *)     echo "Data kept in $DATA_DIR" ;;
        esac
    fi
    exit 0
fi

if [ ! -f "$APP" ] || [ ! -f "$APP.png" ]; then
    echo "ERROR: $APP and $APP.png must be in the same folder as this script."
    exit 1
fi

install -D -m 755 "$APP" "$BIN_DIR/$ID"
install -D -m 644 "$APP.png" "$ICON_DIR/$ID.png"
mkdir -p "$APPS_DIR"
cat > "$APPS_DIR/$ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$APP
Comment=Tasks with checkpoints, notes, links and attachments
Exec=$BIN_DIR/$ID
Icon=$ID
Terminal=false
Categories=Office;ProjectManagement;
StartupWMClass=$APP
EOF
refresh_desktop

echo "$APP installed: $BIN_DIR/$ID"
echo "It is in the applications menu now. On KDE run kbuildsycoca6 or log out and in if it is not."
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "Note: $BIN_DIR is not in PATH, so the terminal command '$ID' will not work (the menu entry will)." ;;
esac
