# Full backup of the application data

import os
import json
import sqlite3
import tempfile
import zipfile
from datetime import datetime

from config import (DB_PATH, ARCHIVE_DIR, ATTACHMENTS_DIR, BACKUP_DIR, APP_VERSION,
                    SETTINGS_PATH)

# Paths of attachments inside the backup are relative to the data folder
APP_DIR = os.path.dirname(os.path.abspath(DB_PATH))


# Main backup function

# File name prefixes: automatic backups are removed by prune_auto_backups,
# backups made by hand never are
MANUAL_PREFIX = "WinDashboard_backup_"
AUTO_PREFIX   = "WinDashboard_autobackup_"


def create_backup(progress_callback=None, auto: bool = False) -> tuple[str, list[str]]:
    """
    Creates full backup of the application as a ZIP file.
    auto=True marks it as an automatic backup (see prune_auto_backups).
    Collects: database, database backup copy, attachments, tasks archives, settings.
    Returns (path of the created ZIP file, names of files which could not be packed).

    Safe to run in a background thread: it opens its own database connections.

    The database is copied with the SQLite backup API, so the copy is consistent.
    The ZIP is written under a temporary name and renamed only when complete,
    so an interrupted backup never shows up on the list as a valid one.

    progress_callback: optional function(name: str, current: int, total: int)
    called while files are packed.
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)

    from database import unique_path

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    prefix    = AUTO_PREFIX if auto else MANUAL_PREFIX
    zip_path  = unique_path(os.path.join(BACKUP_DIR, f"{prefix}{timestamp}.zip"))
    tmp_path  = zip_path + ".tmp"

    files_to_pack = _collect_files()
    total   = len(files_to_pack) + (1 if os.path.exists(DB_PATH) else 0)
    packed  = 0
    skipped = []
    snapshot = None

    try:
        with tempfile.TemporaryDirectory() as tmp_dir, \
             zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:

            # Consistent snapshot of the database; a backup without it makes no sense,
            # so an error here stops the backup
            if os.path.exists(DB_PATH):
                if progress_callback:
                    progress_callback("tasks.db", 1, total)
                snapshot = os.path.join(tmp_dir, "tasks.db")
                src = sqlite3.connect(DB_PATH)
                dst = sqlite3.connect(snapshot)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
                    src.close()
                zf.write(snapshot, "tasks.db")
                packed += 1

            for src_path, arc_name in files_to_pack:
                if progress_callback:
                    progress_callback(arc_name, packed + len(skipped) + 1, total)
                try:
                    zf.write(src_path, arc_name)
                    packed += 1
                except Exception:
                    skipped.append(arc_name)  # file not readable: skip it, keep going

            # Metadata is written last, so it reports what was really packed
            meta = _build_meta(snapshot, packed, skipped)
            meta["automatic"] = auto
            zf.writestr("backup_meta.json",
                        json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))

        os.replace(tmp_path, zip_path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise

    return zip_path, skipped


def _collect_files() -> list[tuple[str, str]]:
    """
    Returns list of (source_path, name_in_archive) for all files
    included in the backup, except the database itself (see create_backup).
    Names in archive always use "/" as separator.
    """
    files = []

    bak_path = DB_PATH + ".bak"
    if os.path.exists(bak_path):
        files.append((bak_path, "tasks.db.bak"))

    if os.path.exists(SETTINGS_PATH):
        files.append((SETTINGS_PATH, "settings.json"))

    if os.path.exists(ATTACHMENTS_DIR):
        for root, _, fnames in os.walk(ATTACHMENTS_DIR):
            for fname in fnames:
                src = os.path.join(root, fname)
                rel = os.path.relpath(src, APP_DIR)
                files.append((src, rel.replace("\\", "/")))

    if os.path.exists(ARCHIVE_DIR):
        for fname in os.listdir(ARCHIVE_DIR):
            if not fname.endswith(".zip"):
                continue
            src = os.path.join(ARCHIVE_DIR, fname)
            files.append((src, f"archive/{fname}"))

        # removed/ subfolder goes to backup as well
        removed_dir = os.path.join(ARCHIVE_DIR, "removed")
        if os.path.exists(removed_dir):
            for fname in os.listdir(removed_dir):
                src = os.path.join(removed_dir, fname)
                if os.path.isfile(src):
                    files.append((src, f"archive/removed/{fname}"))

    return files


def _build_meta(db_snapshot, file_count: int, skipped: list[str]) -> dict:
    """Builds backup metadata dictionary. Task counts are read from the packed
    database snapshot, so they describe exactly what is in the backup."""
    active = on_hold = 0
    if db_snapshot:
        try:
            conn = sqlite3.connect(db_snapshot)
            try:
                for flag, count in conn.execute(
                        "SELECT on_hold, COUNT(*) FROM tasks GROUP BY on_hold"):
                    if flag:
                        on_hold += count
                    else:
                        active += count
            finally:
                conn.close()
        except Exception:
            pass

    archive_count = 0
    if os.path.exists(ARCHIVE_DIR):
        archive_count = len([f for f in os.listdir(ARCHIVE_DIR)
                             if f.endswith(".zip")])

    att_count = 0
    if os.path.exists(ATTACHMENTS_DIR):
        for _, _, fnames in os.walk(ATTACHMENTS_DIR):
            att_count += len(fnames)

    return {
        "backup_date":      datetime.now().isoformat(),
        "app_version":      APP_VERSION,
        "tasks_active":     active,
        "tasks_on_hold":    on_hold,
        "tasks_archived":   archive_count,
        "attachment_files": att_count,
        "packed_files":     file_count,
        "skipped_files":    skipped,
    }


# Listing existing backups

def list_backups() -> list[dict]:
    """
    Returns list of existing backups sorted by newest.
    Each item: {zip_path, filename, date, size_mb, meta, auto}
    """
    if not os.path.exists(BACKUP_DIR):
        return []

    result = []
    for fname in _backup_files():
        zip_path = os.path.join(BACKUP_DIR, fname)
        size_mb  = os.path.getsize(zip_path) / (1024 * 1024)
        meta     = {}
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                if "backup_meta.json" in zf.namelist():
                    meta = json.loads(zf.read("backup_meta.json").decode("utf-8"))
        except Exception:
            pass
        result.append({
            "zip_path":  zip_path,
            "filename":  fname,
            "size_mb":   round(size_mb, 2),
            "meta":      meta,
            "date":      meta.get("backup_date", "")[:16].replace("T", "  "),
            "auto":      fname.startswith(AUTO_PREFIX),
        })
    return result


def _backup_files(prefix: str = "") -> list[str]:
    """Names of backup files, newest first (by modification time)."""
    if not os.path.exists(BACKUP_DIR):
        return []
    names = [f for f in os.listdir(BACKUP_DIR) if f.endswith(".zip") and f.startswith(prefix)]
    return sorted(names, key=lambda f: os.path.getmtime(os.path.join(BACKUP_DIR, f)),
                  reverse=True)


def auto_backup_due(every_days: int) -> bool:
    """True when automatic backups are on and the newest one is at least every_days old."""
    if every_days <= 0:
        return False
    newest = _backup_files(AUTO_PREFIX)
    if not newest:
        return True
    made = datetime.fromtimestamp(os.path.getmtime(os.path.join(BACKUP_DIR, newest[0])))
    return (datetime.now() - made).total_seconds() >= every_days * 86400


def prune_auto_backups(keep: int) -> list[str]:
    """Deletes the oldest automatic backups so that `keep` remain.
    Backups made by hand are never deleted. Returns names of the deleted files."""
    removed = []
    for fname in _backup_files(AUTO_PREFIX)[max(keep, 1):]:
        try:
            os.remove(os.path.join(BACKUP_DIR, fname))
            removed.append(fname)
        except OSError:
            pass
    return removed


# Restoring a backup

def restore_backup(zip_path: str) -> dict:
    """
    Restores a backup by merging it with the current data.
    Tasks and archived tasks which are missing now are added from the backup;
    nothing existing is changed or removed. A task is recognized by its title
    and creation date, so a task which exists now (active, on hold or archived)
    is never added for the second time.
    Returns: {tasks_added, tasks_skipped, archives_added}
    """
    from database import init_db, get_connection
    from archive import insert_task_data

    init_db()
    result = {"tasks_added": 0, "tasks_skipped": 0, "archives_added": 0}

    # Tasks known now: in the database and in the archive folder
    with get_connection() as conn:
        known = {(r[0], r[1]) for r in conn.execute("SELECT title, created_at FROM tasks")}
    if os.path.exists(ARCHIVE_DIR):
        for fname in os.listdir(ARCHIVE_DIR):
            if fname.endswith(".zip"):
                key = _archived_task_key(os.path.join(ARCHIVE_DIR, fname))
                if key:
                    known.add(key)

    with tempfile.TemporaryDirectory() as tmp_dir, zipfile.ZipFile(zip_path, "r") as zf:
        names = set(zf.namelist())

        # Tasks from the database of the backup
        if "tasks.db" in names:
            db_copy = os.path.join(tmp_dir, "tasks.db")
            with zf.open("tasks.db") as src, open(db_copy, "wb") as dst:
                dst.write(src.read())

            def open_attachment(att: dict):
                arc_name = att["stored_path"].replace("\\", "/")
                return zf.open(arc_name) if arc_name in names else None

            for data in _read_tasks(db_copy):
                key = (data["task"]["title"], data["task"]["created_at"])
                if key in known:
                    result["tasks_skipped"] += 1
                    continue
                insert_task_data(data, bool(data["task"].get("on_hold")), open_attachment)
                known.add(key)
                result["tasks_added"] += 1

        # Archived tasks
        for name in sorted(names):
            if not name.startswith("archive/") or not name.endswith(".zip"):
                continue
            if name.startswith("archive/removed/"):
                continue  # removed from the archive on purpose
            fname = os.path.basename(name)
            dest  = os.path.join(ARCHIVE_DIR, fname)
            if os.path.exists(dest):
                continue
            tmp_zip = os.path.join(tmp_dir, fname)
            with zf.open(name) as src, open(tmp_zip, "wb") as dst:
                dst.write(src.read())
            key = _archived_task_key(tmp_zip)
            if key is None or key in known:
                continue
            os.makedirs(ARCHIVE_DIR, exist_ok=True)
            os.replace(tmp_zip, dest)
            known.add(key)
            result["archives_added"] += 1

    return result


def _archived_task_key(zip_path: str):
    """Returns (title, created_at) of a task archived in the ZIP file, None if not readable."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            task = json.loads(zf.read("task.json").decode("utf-8")).get("task", {})
        return (task["title"], task["created_at"])
    except Exception:
        return None


def _read_tasks(db_path: str) -> list[dict]:
    """Reads all tasks from a database file into the format of task.json.
    Handles databases created before the checkpoint renaming as well."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        cp_table = "task_checkpoints" if "task_checkpoints" in tables else "task_stages"

        def rows(table: str, task_id: int) -> list[dict]:
            if table not in tables:
                return []
            return [dict(r) for r in conn.execute(
                f"SELECT * FROM {table} WHERE task_id = ? ORDER BY id", (task_id,))]

        result = []
        for task in conn.execute("SELECT * FROM tasks ORDER BY id"):
            task = dict(task)
            result.append({
                "task":        task,
                "checkpoints": rows(cp_table, task["id"]),
                "notes":       rows("task_notes", task["id"]),
                "links":       rows("task_links", task["id"]),
                "attachments": rows("task_attachments", task["id"]),
            })
        return result
    finally:
        conn.close()


# Deleting old backups

def delete_backup(zip_path: str):
    """Deletes backup file. Can not be undone."""
    if os.path.exists(zip_path):
        os.remove(zip_path)
