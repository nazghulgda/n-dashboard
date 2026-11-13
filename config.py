# App configuration

import os
import sys
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "n-dashboard"

# Program folder: next to the .py files, or the folder PyInstaller unpacks the build into
PROGRAM_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

# Icons and other files shipped with the program
ASSETS_DIR = PROGRAM_DIR / "assets"

# Data folder in the standard place of the operating system:
#   Windows: %LOCALAPPDATA%\n-dashboard
#   macOS:   ~/Library/Application Support/n-dashboard
#   Linux:   ~/.local/share/n-dashboard  ($XDG_DATA_HOME if set)
# N_DASHBOARD_DATA_DIR overrides it (tests, trying out a build on separate data).
_DATA_DIR_OVERRIDE = os.environ.get("N_DASHBOARD_DATA_DIR")
DATA_DIR = Path(_DATA_DIR_OVERRIDE
                or user_data_dir(APP_NAME, appauthor=False, roaming=False))

# Folders of older versions, checked in this order on the first start; the first one
# with a database is copied to DATA_DIR by database.migrate_legacy_data:
#   - data folder of versions 0.6-0.7, when the app was called WinDashboard
#   - versions before 0.6 kept their data next to the .py files
LEGACY_DATA_DIRS = [d for d in (
    None if _DATA_DIR_OVERRIDE else Path(user_data_dir("WinDashboard", appauthor=False, roaming=False)),
    None if getattr(sys, "frozen", False) else Path(__file__).resolve().parent,
) if d is not None]

DB_PATH = str(DATA_DIR / "tasks.db")

ARCHIVE_DIR = str(DATA_DIR / "archive")

ATTACHMENTS_DIR = str(DATA_DIR / "attachments")

BACKUP_DIR = str(DATA_DIR / "backups")

SETTINGS_PATH = str(DATA_DIR / "settings.json")

# Lock file which allows only one running copy of the application
INSTANCE_LOCK_PATH = str(DATA_DIR / "n-dashboard.lock")

# Copied into a new database as the "Default" template, which is then edited in
# Settings -> Kanban templates; changes here affect new databases only.
#   type:   "check", or "counter" (optional: never blocks finishing or a status)
#   status: reached when this checkpoint and those of all earlier statuses are done
DEFAULT_TEMPLATE_NAME = "Default"
DEFAULT_TEMPLATE = [
  {"name": "Kick-off",     "type": "check",   "status": "Planned"},
  {"name": "CheckPoint 1", "type": "check",   "status": "Started"},
  {"name": "CheckPoint 2", "type": "check",   "status": "In progress"},
  {"name": "CheckPoint 3", "type": "check",   "status": "In progress"},
  {"name": "CheckPoint 4", "type": "check",   "status": "In progress"},
  {"name": "CheckPoint 5", "type": "counter", "status": None},
  {"name": "CheckPoint 6", "type": "counter", "status": "In review"},
  {"name": "CheckPoint 7", "type": "check",   "status": "In review"},
  {"name": "CheckPoint 8", "type": "check",   "status": "Rework / fixes"},
  {"name": "Closed",       "type": "check",   "status": None},
]

# The only checkpoint of a task created with "Empty kanban"
DEFAULT_CHECKPOINT = {"name": "Task completed", "type": "check"}

# Statuses which do not depend on the template
STATUS_NOT_STARTED = "Not started"   # no checkpoint completed
STATUS_IN_PROGRESS = "In progress"   # started, but no status of the template reached yet
STATUS_FINISHED    = "Finished"      # every checkpoint completed

# Main program window settings
APP_TITLE = "n-dashboard"
APP_VERSION = "0.8.0"
MAIN_WINDOW_SIZE = "900x600"

# Database check interval in ms (600 000 ms = 10 minutes)
DB_CHECK_INTERVAL_MS = 600_000

# Number of older daily copies of the database kept besides the last working copy
# (tasks.db.bak.1 = up to 1 day old, tasks.db.bak.2 = up to 2 days old, ...)
DB_BACKUP_DAILY_COPIES = 3

# Status colours of tasks are defined in theme.py (status_* keys)
