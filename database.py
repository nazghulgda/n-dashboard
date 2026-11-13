# Database structure and all reads and writes

import os
import re
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from config import (DB_PATH, ATTACHMENTS_DIR, DEFAULT_TEMPLATE, DEFAULT_TEMPLATE_NAME,
                    DEFAULT_CHECKPOINT, STATUS_NOT_STARTED, STATUS_IN_PROGRESS,
                    STATUS_FINISHED, DB_BACKUP_DAILY_COPIES)

# Attachment paths are stored relative to the data folder
APP_DIR = os.path.dirname(os.path.abspath(DB_PATH))

# Last working copy of the database
LAST_WORKING_PATH = DB_PATH + ".bak"


# Connection

@contextmanager
def get_connection():
    """Opens the database for one operation: commits on success, rolls back on error
    and always closes the connection, so the database file is never left open."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            yield conn
    finally:
        conn.close()


# Database initialization

def init_db():
    """Creates tables in not exists. Migrates for existing databases."""
    with get_connection() as conn:
        _migrate_legacy_stage_names(conn)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT    NOT NULL,
                description TEXT    DEFAULT '',
                on_hold     INTEGER NOT NULL DEFAULT 0,
                on_hold_at  TEXT,
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_checkpoints (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id         INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                checkpoint_order INTEGER NOT NULL,
                name            TEXT    NOT NULL,
                checkpoint_type TEXT    NOT NULL DEFAULT 'check',
                completed       INTEGER NOT NULL DEFAULT 0,
                iteration_count INTEGER NOT NULL DEFAULT 0,
                template_order  INTEGER,
                status_group    TEXT,
                group_order     INTEGER,
                completed_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS task_notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                title       TEXT    NOT NULL,
                content     TEXT    DEFAULT '',
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_links (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                label       TEXT    NOT NULL,
                path        TEXT    NOT NULL,
                link_type   TEXT    NOT NULL DEFAULT 'file'
            );

            CREATE TABLE IF NOT EXISTS task_attachments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                filename    TEXT    NOT NULL,
                stored_path TEXT    NOT NULL,
                deleted     INTEGER NOT NULL DEFAULT 0,
                added_at    TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS kanban_templates (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                is_default  INTEGER NOT NULL DEFAULT 0,
                position    INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS template_checkpoints (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id     INTEGER NOT NULL REFERENCES kanban_templates(id) ON DELETE CASCADE,
                position        INTEGER NOT NULL,
                name            TEXT    NOT NULL,
                checkpoint_type TEXT    NOT NULL DEFAULT 'check',
                status_group    TEXT
            );
        """)

        # Migration for existing databases
        cp_cols = [r[1] for r in conn.execute("PRAGMA table_info(task_checkpoints)").fetchall()]
        if "checkpoint_type" not in cp_cols:
            conn.execute("ALTER TABLE task_checkpoints ADD COLUMN checkpoint_type TEXT NOT NULL DEFAULT 'check'")
        if "iteration_count" not in cp_cols:
            conn.execute("ALTER TABLE task_checkpoints ADD COLUMN iteration_count INTEGER NOT NULL DEFAULT 0")
        if "template_order" not in cp_cols:
            conn.execute("ALTER TABLE task_checkpoints ADD COLUMN template_order INTEGER")
            # Existing checkpoints are matched with the template by name
            conn.executemany(
                "UPDATE task_checkpoints SET template_order = ? WHERE name = ?",
                [(order, name) for name, order in _LEGACY_ORDER_BY_NAME.items()]
            )
        if "completed_at" not in cp_cols:
            conn.execute("ALTER TABLE task_checkpoints ADD COLUMN completed_at TEXT")
        if "status_group" not in cp_cols:
            conn.execute("ALTER TABLE task_checkpoints ADD COLUMN status_group TEXT")
            conn.execute("ALTER TABLE task_checkpoints ADD COLUMN group_order INTEGER")
            # Statuses of tasks created from the template of versions before 0.7
            conn.executemany(
                "UPDATE task_checkpoints SET status_group = ?, group_order = ? "
                "WHERE template_order = ?",
                [(name, group_order, order)
                 for order, (name, group_order) in _LEGACY_STATUS_BY_ORDER.items()]
            )

        tasks_cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
        if "on_hold" not in tasks_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN on_hold INTEGER NOT NULL DEFAULT 0")
        if "on_hold_at" not in tasks_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN on_hold_at TEXT")
        if "due_date" not in tasks_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN due_date TEXT")

        # Default template on the first start
        if conn.execute("SELECT COUNT(*) FROM kanban_templates").fetchone()[0] == 0:
            _insert_template(conn, DEFAULT_TEMPLATE_NAME, DEFAULT_TEMPLATE, is_default=True)

        # Notes edited before every change started to update the task: the task gets
        # the date of its newest note, so tasks.updated_at is the last activity
        conn.execute("""
            UPDATE tasks SET updated_at = (
                SELECT MAX(n.updated_at) FROM task_notes n WHERE n.task_id = tasks.id)
            WHERE (SELECT MAX(n.updated_at) FROM task_notes n WHERE n.task_id = tasks.id)
                  > updated_at
        """)


# Fixed template of versions before 0.7, used to give statuses to their tasks and
# archives. Never change it.
_LEGACY_ORDER_BY_NAME = {
    "Kick-off": 1, "CheckPoint 1": 2, "CheckPoint 2": 3, "CheckPoint 3": 4,
    "CheckPoint 4": 5, "CheckPoint 5": 6, "CheckPoint 6": 7, "CheckPoint 7": 8,
    "CheckPoint 8": 9, "Closed": 10,
}
_LEGACY_STATUS_BY_ORDER = {
    1: ("Planned", 1), 2: ("Started", 2),
    3: ("In progress", 3), 4: ("In progress", 3), 5: ("In progress", 3),
    7: ("In review", 4), 8: ("In review", 4),
    9: ("Rework / fixes", 5),
}


def legacy_status_of(checkpoint: dict) -> tuple:
    """(status_group, group_order) of a checkpoint saved by a version before 0.7
    (archives, backups), found by its template_order or, in older ones, by its name."""
    order = checkpoint.get("template_order")
    if order is None:
        order = _LEGACY_ORDER_BY_NAME.get(checkpoint.get("name"))
    return _LEGACY_STATUS_BY_ORDER.get(order, (None, None))


def _migrate_legacy_stage_names(conn):
    """Backward compatibility: renames the old 'task_stages' table and its
    'stage_order' / 'stage_type' columns to the checkpoint naming.
    Does nothing for a new database or one that is already migrated."""
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
    if "task_stages" in tables and "task_checkpoints" not in tables:
        conn.execute("ALTER TABLE task_stages RENAME TO task_checkpoints")
        tables.add("task_checkpoints")
    if "task_checkpoints" not in tables:
        return
    cols = [r[1] for r in conn.execute("PRAGMA table_info(task_checkpoints)").fetchall()]
    if "stage_order" in cols and "checkpoint_order" not in cols:
        conn.execute("ALTER TABLE task_checkpoints RENAME COLUMN stage_order TO checkpoint_order")
    if "stage_type" in cols and "checkpoint_type" not in cols:
        conn.execute("ALTER TABLE task_checkpoints RENAME COLUMN stage_type TO checkpoint_type")


# Database check and last working copy

def check_db(path: str = None) -> bool:
    """Checks if the database file (default: the application database) can be opened
    and its structure is not damaged."""
    try:
        conn = sqlite3.connect(path or DB_PATH)
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
        finally:
            conn.close()
        return bool(row) and row[0] == "ok"
    except Exception:
        return False


def working_copies() -> list[str]:
    """Paths of all working copies of the database, newest first:
    tasks.db.bak, tasks.db.bak.1, tasks.db.bak.2, ..."""
    return [LAST_WORKING_PATH] + [f"{LAST_WORKING_PATH}.{n}"
                                  for n in range(1, DB_BACKUP_DAILY_COPIES + 1)]


def _rotate_daily_copies():
    """Once a day the last working copy becomes tasks.db.bak.1, the older copies
    move one place down and the oldest one is removed. Thanks to this a mistake
    noticed later (e.g. data removed by accident) can still be undone."""
    if DB_BACKUP_DAILY_COPIES < 1 or not os.path.exists(LAST_WORKING_PATH):
        return
    newest_daily = f"{LAST_WORKING_PATH}.1"
    if os.path.exists(newest_daily):
        age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(newest_daily))
        if age < timedelta(days=1):
            return
    copies = working_copies()
    # .bak.2 -> .bak.3, .bak.1 -> .bak.2, .bak -> .bak.1
    for newer, older in reversed(list(zip(copies[:-1], copies[1:]))):
        if os.path.exists(newer):
            os.replace(newer, older)


def backup_db() -> bool:
    """Saves the database as the last working copy (tasks.db.bak).
    Only a database which passes the check is copied, so a damaged
    database never replaces a good copy. Returns True if the copy was saved."""
    if not os.path.exists(DB_PATH) or not check_db():
        return False
    tmp_path = LAST_WORKING_PATH + ".tmp"
    try:
        _rotate_daily_copies()
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(tmp_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        os.replace(tmp_path, LAST_WORKING_PATH)
        return True
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return False


def verify_db() -> str:
    """Checks the database and restores it from the newest good working copy if it is damaged.
    Returns:
      "ok":       database is fine (or does not exist yet and there is no copy)
      "restored": database was damaged or missing and was restored from a working copy
      "failed":   database is damaged and there is no good working copy to restore from
    The damaged file is kept as tasks.db.corrupt_<date>_<time>."""
    copies = [p for p in working_copies() if os.path.exists(p) and os.path.getsize(p) > 0]
    has_db = os.path.exists(DB_PATH)

    if has_db:
        # SQLite accepts an empty file as an empty database; with a copy around it's damage
        emptied = os.path.getsize(DB_PATH) == 0 and bool(copies)
        if not emptied and check_db():
            return "ok"
    elif not copies:
        return "ok"

    good_copy = next((p for p in copies if check_db(p)), None)
    if good_copy is None:
        return "failed"

    try:
        if has_db:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            os.replace(DB_PATH, f"{DB_PATH}.corrupt_{stamp}")
        shutil.copy2(good_copy, DB_PATH)
    except Exception:
        return "failed"
    return "restored" if check_db() else "failed"


# Moving data of older versions

# Data of versions before 0.6, kept next to the .py files
_LEGACY_DIRS  = ("archive", "attachments", "backups")
_LEGACY_FILES = ("settings.json",)


def migrate_legacy_data(legacy_dir) -> list[str]:
    """Copies data of an older version (kept next to the .py files) into the data folder.
    Runs only when the data folder has no database yet and legacy_dir has one.
    The old files are left untouched, so nothing is lost if the copy fails half way;
    the database is copied last, so an interrupted copy is simply repeated on the next start.
    Returns names of the copied items (empty list = nothing was done)."""
    if legacy_dir is None:
        return []
    legacy_dir = os.path.abspath(legacy_dir)
    if (os.path.normcase(legacy_dir) == os.path.normcase(APP_DIR)
            or os.path.exists(DB_PATH)
            or not os.path.exists(os.path.join(legacy_dir, "tasks.db"))):
        return []

    os.makedirs(APP_DIR, exist_ok=True)
    copied = []
    for name in sorted(os.listdir(legacy_dir)):
        src = os.path.join(legacy_dir, name)
        dst = os.path.join(APP_DIR, name)
        if name in _LEGACY_DIRS and os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif (name in _LEGACY_FILES
              or re.fullmatch(r"tasks\.db\.(bak(\.\d+)?|corrupt_\d{8}_\d{6})", name)):
            shutil.copy2(src, dst)
        else:
            continue
        copied.append(name)

    # SQLite backup API gives a consistent copy; written under a temporary name
    tmp_path = DB_PATH + ".tmp"
    src = sqlite3.connect(os.path.join(legacy_dir, "tasks.db"))
    dst = sqlite3.connect(tmp_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.replace(tmp_path, DB_PATH)
    copied.append("tasks.db")
    return copied


def _touch_task(conn, task_id: int):
    """Every change inside a task updates its updated_at, so that column holds
    the date of the last activity."""
    conn.execute(
        "UPDATE tasks SET updated_at = ? WHERE id = ?",
        (datetime.now().isoformat(), task_id)
    )


def _touch_task_of_checkpoint(conn, checkpoint_id: int):
    """_touch_task for the task owning the checkpoint. Does nothing when the
    checkpoint does not exist anymore (e.g. database restored in the meantime)."""
    row = conn.execute(
        "SELECT task_id FROM task_checkpoints WHERE id = ?", (checkpoint_id,)
    ).fetchone()
    if row:
        _touch_task(conn, row[0])


def unique_path(path: str) -> str:
    """Returns path, or path with a number suffix (_2, _3, ...) if the file already exists."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{base}_{n}{ext}"):
        n += 1
    return f"{base}_{n}{ext}"


# Tasks

def create_task(title: str, description: str = "", checkpoints: list = None,
                due_date: str = None, template_id: int = None) -> int:
    """Creates new task.
    checkpoints=None  -> checkpoints of the template template_id (None = default template)
    checkpoints=[]    -> empty kanban (config.DEFAULT_CHECKPOINT only)
    checkpoints=[...] -> given list of {name, type, status} (format of config.DEFAULT_TEMPLATE)
    due_date: 'YYYY-MM-DD' or None
    """
    now = datetime.now().isoformat()
    with get_connection() as conn:
        if checkpoints is None:
            if template_id is None:
                row = conn.execute(
                    "SELECT id FROM kanban_templates ORDER BY is_default DESC, position, id"
                ).fetchone()
                template_id = row[0] if row else None
            checkpoints = _template_rows(conn, template_id) if template_id else []
        checkpoints = checkpoints or [DEFAULT_CHECKPOINT]

        cur = conn.execute(
            """INSERT INTO tasks (title, description, due_date, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (title, description, due_date, now, now)
        )
        task_id = cur.lastrowid
        _insert_task_checkpoints(conn, task_id, checkpoints)
    return task_id


def _insert_task_checkpoints(conn, task_id: int, checkpoints: list):
    """Inserts checkpoints given as {name, type, status} into a task. The status of a
    checkpoint and the order of the statuses are copied into the task, so later changes
    of the template, or moving checkpoints inside the task, never change its status."""
    group_orders = _group_orders(c.get("status") for c in checkpoints)
    conn.executemany(
        """INSERT INTO task_checkpoints
           (task_id, checkpoint_order, name, checkpoint_type, completed, iteration_count,
            template_order, status_group, group_order)
           VALUES (?, ?, ?, ?, 0, 0, ?, ?, ?)""",
        [(task_id, position, c["name"], c.get("type", "check"), position,
          c.get("status"), group_orders.get(c.get("status")))
         for position, c in enumerate(checkpoints, start=1)]
    )


def _group_orders(statuses) -> dict:
    """{status: order}: statuses follow each other in the order of their first checkpoint."""
    orders = {}
    for status in statuses:
        if status and status not in orders:
            orders[status] = len(orders) + 1
    return orders


def duplicate_task(task_id: int) -> int | None:
    """Creates a copy of the task: title with " (copy)", description, due date,
    checkpoints (not completed, statuses kept) and links. Notes and attachments
    belong to the work done, so they are not copied. Returns id of the new task."""
    task = get_task(task_id)
    if not task:
        return None
    now = datetime.now().isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO tasks (title, description, due_date, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (f"{task['title']} (copy)", task["description"], task["due_date"], now, now)
        )
        new_id = cur.lastrowid
        conn.execute(
            """INSERT INTO task_checkpoints
               (task_id, checkpoint_order, name, checkpoint_type, completed, iteration_count,
                template_order, status_group, group_order)
               SELECT ?, checkpoint_order, name, checkpoint_type, 0, 0,
                      template_order, status_group, group_order
               FROM task_checkpoints WHERE task_id = ? ORDER BY checkpoint_order""",
            (new_id, task_id)
        )
        conn.execute(
            """INSERT INTO task_links (task_id, label, path, link_type)
               SELECT ?, label, path, link_type FROM task_links WHERE task_id = ? ORDER BY id""",
            (new_id, task_id)
        )
    return new_id


def get_all_tasks() -> list:
    """Returns active tasks sorted by newest."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE on_hold = 0 ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_on_hold_tasks() -> list:
    """Returns holded tasks sorted by lastest holded."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE on_hold = 1 ORDER BY on_hold_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_task(task_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(row) if row else None


def update_task(task_id: int, title: str, description: str, due_date: str = None):
    """Updates title, description and due date ('YYYY-MM-DD' or None = no due date)."""
    now = datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE tasks SET title = ?, description = ?, due_date = ?, updated_at = ? "
            "WHERE id = ?",
            (title, description, due_date, now, task_id)
        )


def delete_task(task_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


def set_on_hold(task_id: int, on_hold: bool):
    now = datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE tasks SET on_hold = ?, on_hold_at = ?, updated_at = ? WHERE id = ?",
            (1 if on_hold else 0, now if on_hold else None, now, task_id)
        )


# Task checkpoints

def get_checkpoints(task_id: int) -> list:
    """Returns checkpoints of particular task in order."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM task_checkpoints WHERE task_id = ? ORDER BY checkpoint_order",
            (task_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_checkpoints_by_task(on_hold: bool = False) -> dict:
    """Returns {task_id: [checkpoints in order]} for all active (or on hold) tasks
    with one query, for the task lists refreshed every few seconds."""
    result = {}
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT c.* FROM task_checkpoints c JOIN tasks t ON t.id = c.task_id
               WHERE t.on_hold = ? ORDER BY c.task_id, c.checkpoint_order""",
            (1 if on_hold else 0,)
        ).fetchall()
    for r in rows:
        result.setdefault(r["task_id"], []).append(dict(r))
    return result


def set_checkpoint_completed(checkpoint_id: int, completed: bool):
    """Sets state of checkbox of checkpoint and updates updated_at of task."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE task_checkpoints SET completed = ?, completed_at = ? WHERE id = ?",
            (1 if completed else 0, datetime.now().isoformat() if completed else None,
             checkpoint_id)
        )
        _touch_task_of_checkpoint(conn, checkpoint_id)


def set_iteration_count(checkpoint_id: int, count: int):
    """Sets checkpoint iteration counter. count >= 0."""
    count = max(0, count)
    completed = 1 if count > 0 else 0
    with get_connection() as conn:
        row = conn.execute(
            "SELECT iteration_count FROM task_checkpoints WHERE id = ?", (checkpoint_id,)
        ).fetchone()
        old_count = row[0] if row else 0
        # completed_at of a counter = date of its last iteration
        if count == 0:
            completed_at_sql, params = "NULL", ()
        elif count > old_count:
            completed_at_sql, params = "?", (datetime.now().isoformat(),)
        else:
            completed_at_sql, params = "completed_at", ()
        conn.execute(
            f"UPDATE task_checkpoints SET iteration_count = ?, completed = ?, "
            f"completed_at = {completed_at_sql} WHERE id = ?",
            (count, completed, *params, checkpoint_id)
        )
        _touch_task_of_checkpoint(conn, checkpoint_id)


def is_counter(checkpoint: dict) -> bool:
    """True for a counter checkpoint (old archives use the 'stage_type' key)."""
    return checkpoint.get("checkpoint_type", checkpoint.get("stage_type", "check")) == "counter"


def checkpoint_progress(checkpoints: list) -> tuple[int, int]:
    """Returns (finished, all) for a list of checkpoints.
    Counters are optional: a counter which was never used is not counted at all,
    a counter used at least once counts as a finished checkpoint."""
    done = total = 0
    for c in checkpoints:
        if is_counter(c) and not c.get("completed"):
            continue
        total += 1
        if c.get("completed"):
            done += 1
    return done, total


def get_task_progress(task_id: int) -> tuple[int, int]:
    """(finished, all) checkpoints of the task, see checkpoint_progress."""
    return checkpoint_progress(get_checkpoints(task_id))


def get_task_checkpoint_status(task_id: int) -> str:
    """Status of the task, see checkpoint_status."""
    return checkpoint_status(get_checkpoints(task_id))


def checkpoint_status(checkpoints: list) -> str:
    """Returns status name of a task with the given checkpoints.

    No checkpoint completed   -> STATUS_NOT_STARTED
    All checkpoints completed -> STATUS_FINISHED
    Otherwise                 -> the last status reached in a row. A status is reached when
                                 all checkpoints with this status are completed; statuses are
                                 taken in their order from the template (group_order), which
                                 is stored in each checkpoint, so moving, adding or deleting
                                 checkpoints does not change the meaning of a status.
    No status reached yet, or no checkpoints with a status -> STATUS_IN_PROGRESS.
    Counters are optional (see checkpoint_progress) and never block a status."""
    done, total = checkpoint_progress(checkpoints)

    if done == 0:
        return STATUS_NOT_STARTED
    if done == total:
        return STATUS_FINISHED

    groups = {}   # group_order -> (status name, [completed flags])
    for c in checkpoints:
        if c.get("status_group") and not is_counter(c):
            order = c.get("group_order") or 0
            groups.setdefault(order, (c["status_group"], []))[1].append(bool(c["completed"]))

    current_status = STATUS_IN_PROGRESS
    for order in sorted(groups):
        name, states = groups[order]
        if not all(states):
            break
        current_status = name
    return current_status


def add_checkpoint(task_id: int, name: str, checkpoint_type: str = "check") -> int:
    """Adds a new checkpoint at the end of the kanban list of the task."""
    with get_connection() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(checkpoint_order), 0) FROM task_checkpoints WHERE task_id = ?",
            (task_id,)
        ).fetchone()[0]
        cur = conn.execute(
            """INSERT INTO task_checkpoints
               (task_id, checkpoint_order, name, checkpoint_type, completed, iteration_count)
               VALUES (?, ?, ?, ?, 0, 0)""",
            (task_id, max_order + 1, name, checkpoint_type)
        )
        _touch_task(conn, task_id)
    return cur.lastrowid


def delete_checkpoint(checkpoint_id: int) -> bool:
    """Deletes a checkpoint and renumbers the remaining checkpoints of the task.
    The last checkpoint of a task can not be deleted. Returns True if deleted."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT task_id, checkpoint_order FROM task_checkpoints WHERE id = ?", (checkpoint_id,)
        ).fetchone()
        if not row:
            return False
        task_id, deleted_order = row[0], row[1]
        count = conn.execute(
            "SELECT COUNT(*) FROM task_checkpoints WHERE task_id = ?", (task_id,)
        ).fetchone()[0]
        if count <= 1:
            return False
        conn.execute("DELETE FROM task_checkpoints WHERE id = ?", (checkpoint_id,))
        # Shift down all checkpoints above the deleted one
        conn.execute(
            "UPDATE task_checkpoints SET checkpoint_order = checkpoint_order - 1 "
            "WHERE task_id = ? AND checkpoint_order > ?",
            (task_id, deleted_order)
        )
        _touch_task(conn, task_id)
    return True


def update_checkpoint(checkpoint_id: int, name: str, checkpoint_type: str):
    """Updates name and type of a checkpoint."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE task_checkpoints SET name = ?, checkpoint_type = ? WHERE id = ?",
            (name, checkpoint_type, checkpoint_id)
        )
        _touch_task_of_checkpoint(conn, checkpoint_id)


def move_checkpoint(task_id: int, checkpoint_id: int, direction: str):
    """Moves a checkpoint up ('up') or down ('down') by swapping checkpoint_order with its neighbour."""
    with get_connection() as conn:
        current = conn.execute(
            "SELECT checkpoint_order FROM task_checkpoints WHERE id = ?", (checkpoint_id,)
        ).fetchone()
        if not current:
            return
        current_order = current[0]
        target_order = current_order - 1 if direction == "up" else current_order + 1

        neighbor = conn.execute(
            "SELECT id FROM task_checkpoints WHERE task_id = ? AND checkpoint_order = ?",
            (task_id, target_order)
        ).fetchone()
        if not neighbor:
            return  # already at the edge of the list

        conn.execute(
            "UPDATE task_checkpoints SET checkpoint_order = ? WHERE id = ?",
            (target_order, checkpoint_id)
        )
        conn.execute(
            "UPDATE task_checkpoints SET checkpoint_order = ? WHERE id = ?",
            (current_order, neighbor[0])
        )
        _touch_task(conn, task_id)


# Task notes

def create_note(task_id: int, title: str, content: str = "") -> int:
    now = datetime.now().isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO task_notes (task_id, title, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (task_id, title, content, now, now)
        )
        _touch_task(conn, task_id)
    return cur.lastrowid


def get_notes(task_id: int) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM task_notes WHERE task_id = ? ORDER BY created_at DESC",
            (task_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def update_note(note_id: int, title: str, content: str):
    now = datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE task_notes SET title = ?, content = ?, updated_at = ? WHERE id = ?",
            (title, content, now, note_id)
        )
        row = conn.execute(
            "SELECT task_id FROM task_notes WHERE id = ?", (note_id,)
        ).fetchone()
        if row:
            _touch_task(conn, row[0])


# Task links

def create_link(task_id: int, label: str, path: str, link_type: str = "file") -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO task_links (task_id, label, path, link_type) VALUES (?, ?, ?, ?)",
            (task_id, label, path, link_type)
        )
        _touch_task(conn, task_id)
    return cur.lastrowid


def get_links(task_id: int) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM task_links WHERE task_id = ?", (task_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def update_link(link_id: int, label: str, path: str, link_type: str):
    with get_connection() as conn:
        conn.execute(
            "UPDATE task_links SET label = ?, path = ?, link_type = ? WHERE id = ?",
            (label, path, link_type, link_id)
        )
        row = conn.execute(
            "SELECT task_id FROM task_links WHERE id = ?", (link_id,)
        ).fetchone()
        if row:
            _touch_task(conn, row[0])


def delete_link(link_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT task_id FROM task_links WHERE id = ?", (link_id,)
        ).fetchone()
        conn.execute("DELETE FROM task_links WHERE id = ?", (link_id,))
        if row:
            _touch_task(conn, row[0])


# Task attachments
# An attachment is a copy of a file in ATTACHMENTS_DIR/<task_id>_<task title>/. stored_path
# is relative to the data folder and uses "/", so the folder can move to another place.

def get_attachment_dir(task_id: int, task_title: str) -> str:
    """Returns path of the attachments folder of the task."""
    safe_title = re.sub(r'[^\w\s-]', '', task_title).strip()
    safe_title = re.sub(r'[\s]+', '_', safe_title)[:40]
    return os.path.join(ATTACHMENTS_DIR, f"{task_id}_{safe_title}")


def to_stored_path(path: str) -> str:
    """Converts file path into the form kept in the database."""
    return os.path.relpath(path, APP_DIR).replace("\\", "/")


def resolve_attachment_path(stored_path: str) -> str:
    """Returns full path of an attachment file from its stored_path."""
    if os.path.isabs(stored_path):
        return stored_path
    return os.path.join(APP_DIR, *stored_path.split("/"))


def create_attachment(task_id: int, filename: str, path: str) -> int:
    """Registers new attachment. The file has to be already copied to path."""
    now = datetime.now().isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO task_attachments (task_id, filename, stored_path, deleted, added_at)
               VALUES (?, ?, ?, 0, ?)""",
            (task_id, filename, to_stored_path(path), now)
        )
        _touch_task(conn, task_id)
    return cur.lastrowid


def get_attachments(task_id: int, include_deleted: bool = False) -> list:
    """Returns attachments of the task. include_deleted=True returns deleted ones as well."""
    query = "SELECT * FROM task_attachments WHERE task_id = ?"
    if not include_deleted:
        query += " AND deleted = 0"
    with get_connection() as conn:
        rows = conn.execute(query + " ORDER BY added_at", (task_id,)).fetchall()
    return [dict(r) for r in rows]


def restore_attachment(att_id: int, new_path: str):
    """Marks a deleted attachment as active again. new_path = place of the file after
    moving it back from the 'deleted' subfolder."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT task_id FROM task_attachments WHERE id = ?", (att_id,)
        ).fetchone()
        if not row:
            return
        conn.execute(
            "UPDATE task_attachments SET deleted = 0, stored_path = ? WHERE id = ?",
            (to_stored_path(new_path), att_id)
        )
        _touch_task(conn, row[0])


def soft_delete_attachment(att_id: int, new_path: str):
    """Marks attachment as deleted. new_path = place of the file after moving it
    to the 'deleted' subfolder."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT task_id FROM task_attachments WHERE id = ?", (att_id,)
        ).fetchone()
        if not row:
            return
        conn.execute(
            "UPDATE task_attachments SET deleted = 1, stored_path = ? WHERE id = ?",
            (to_stored_path(new_path), att_id)
        )
        _touch_task(conn, row[0])


# Search in notes

def search_notes(query: str, on_hold: bool = False) -> dict:
    """Returns {task_id: [titles of matching notes]} for active (or on hold) tasks
    whose notes contain query in the title or the content.
    Matching is done in Python with casefold(): SQLite's LIKE ignores case only for
    ASCII letters, so "Łódź" would not match "łódź"; it also finds any part of a word."""
    needle = query.casefold().strip()
    if not needle:
        return {}
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT n.task_id, n.title, n.content FROM task_notes n
               JOIN tasks t ON t.id = n.task_id
               WHERE t.on_hold = ? ORDER BY n.created_at DESC""",
            (1 if on_hold else 0,)
        ).fetchall()
    result = {}
    for task_id, title, content in rows:
        if needle in title.casefold() or needle in (content or "").casefold():
            result.setdefault(task_id, []).append(title)
    return result


# Kanban templates
# A template is a named list of checkpoints {name, type, status}. A new task copies
# them (see _insert_task_checkpoints), so editing a template never changes existing tasks.

def _insert_template(conn, name: str, checkpoints: list, is_default: bool = False) -> int:
    position = conn.execute(
        "SELECT COALESCE(MAX(position), 0) + 1 FROM kanban_templates").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO kanban_templates (name, is_default, position) VALUES (?, ?, ?)",
        (name, 1 if is_default else 0, position)
    )
    conn.executemany(
        """INSERT INTO template_checkpoints
           (template_id, position, name, checkpoint_type, status_group)
           VALUES (?, ?, ?, ?, ?)""",
        [(cur.lastrowid, i, c["name"], c.get("type", "check"), c.get("status") or None)
         for i, c in enumerate(checkpoints, start=1)]
    )
    return cur.lastrowid


def _template_rows(conn, template_id: int) -> list:
    rows = conn.execute(
        """SELECT name, checkpoint_type, status_group FROM template_checkpoints
           WHERE template_id = ? ORDER BY position""", (template_id,)
    ).fetchall()
    return [{"name": r[0], "type": r[1], "status": r[2]} for r in rows]


def get_templates() -> list:
    """Returns templates in their order: {id, name, is_default, position, checkpoint_count}."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT t.*, (SELECT COUNT(*) FROM template_checkpoints c
                            WHERE c.template_id = t.id) AS checkpoint_count
               FROM kanban_templates t ORDER BY t.position, t.id"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_default_template_id() -> int | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM kanban_templates ORDER BY is_default DESC, position, id"
        ).fetchone()
    return row[0] if row else None


def get_template_checkpoints(template_id: int) -> list:
    """Returns checkpoints of a template: {id, position, name, checkpoint_type, status_group}."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM template_checkpoints WHERE template_id = ? ORDER BY position",
            (template_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def template_status_flow(template_id: int) -> list[str]:
    """Statuses a task of this template goes through, in order."""
    middle = list(_group_orders(c["status_group"] for c in get_template_checkpoints(template_id)))
    return [STATUS_NOT_STARTED] + middle + [STATUS_FINISHED]


def create_template(name: str) -> int:
    """New template with one checkpoint (a task needs at least one)."""
    with get_connection() as conn:
        return _insert_template(conn, name, [DEFAULT_CHECKPOINT])


def duplicate_template(template_id: int, name: str) -> int:
    with get_connection() as conn:
        return _insert_template(conn, name, _template_rows(conn, template_id))


def rename_template(template_id: int, name: str):
    with get_connection() as conn:
        conn.execute("UPDATE kanban_templates SET name = ? WHERE id = ?", (name, template_id))


def set_default_template(template_id: int):
    with get_connection() as conn:
        conn.execute("UPDATE kanban_templates SET is_default = (id = ?)", (template_id,))


def delete_template(template_id: int) -> bool:
    """Deletes a template. The last template can not be deleted. If the default one
    is deleted, the first remaining template becomes the default."""
    with get_connection() as conn:
        if conn.execute("SELECT COUNT(*) FROM kanban_templates").fetchone()[0] <= 1:
            return False
        conn.execute("DELETE FROM kanban_templates WHERE id = ?", (template_id,))
        if not conn.execute("SELECT 1 FROM kanban_templates WHERE is_default = 1").fetchone():
            conn.execute(
                "UPDATE kanban_templates SET is_default = 1 WHERE id = "
                "(SELECT id FROM kanban_templates ORDER BY position, id LIMIT 1)")
    return True


def add_template_checkpoint(template_id: int, name: str, checkpoint_type: str = "check",
                            status_group: str = None) -> int:
    with get_connection() as conn:
        position = conn.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM template_checkpoints WHERE template_id = ?",
            (template_id,)
        ).fetchone()[0]
        cur = conn.execute(
            """INSERT INTO template_checkpoints
               (template_id, position, name, checkpoint_type, status_group)
               VALUES (?, ?, ?, ?, ?)""",
            (template_id, position, name, checkpoint_type, status_group or None)
        )
    return cur.lastrowid


def update_template_checkpoint(checkpoint_id: int, name: str, checkpoint_type: str,
                               status_group: str = None):
    with get_connection() as conn:
        conn.execute(
            "UPDATE template_checkpoints SET name = ?, checkpoint_type = ?, status_group = ? "
            "WHERE id = ?",
            (name, checkpoint_type, status_group or None, checkpoint_id)
        )


def delete_template_checkpoint(checkpoint_id: int) -> bool:
    """Deletes a checkpoint of a template and renumbers the rest.
    The last checkpoint of a template can not be deleted."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT template_id, position FROM template_checkpoints WHERE id = ?",
            (checkpoint_id,)
        ).fetchone()
        if not row:
            return False
        template_id, position = row
        if conn.execute("SELECT COUNT(*) FROM template_checkpoints WHERE template_id = ?",
                        (template_id,)).fetchone()[0] <= 1:
            return False
        conn.execute("DELETE FROM template_checkpoints WHERE id = ?", (checkpoint_id,))
        conn.execute(
            "UPDATE template_checkpoints SET position = position - 1 "
            "WHERE template_id = ? AND position > ?", (template_id, position)
        )
    return True


def move_template_checkpoint(checkpoint_id: int, direction: str):
    """Moves a checkpoint of a template up ('up') or down ('down')."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT template_id, position FROM template_checkpoints WHERE id = ?",
            (checkpoint_id,)
        ).fetchone()
        if not row:
            return
        template_id, position = row
        target = position - 1 if direction == "up" else position + 1
        neighbor = conn.execute(
            "SELECT id FROM template_checkpoints WHERE template_id = ? AND position = ?",
            (template_id, target)
        ).fetchone()
        if not neighbor:
            return
        conn.execute("UPDATE template_checkpoints SET position = ? WHERE id = ?",
                     (target, checkpoint_id))
        conn.execute("UPDATE template_checkpoints SET position = ? WHERE id = ?",
                     (position, neighbor[0]))
