# Tests of the data layer. They run in a temporary folder and never touch real data.
#
# Run: .venv/bin/python test_db.py   (Windows: .venv\Scripts\python.exe test_db.py)

import os
import sys
import tempfile
import zipfile
import json
from datetime import datetime

import config
import database
import archive
import backup
import report
import settings
import ui_helpers


def _isolate(tmp: str):
    """Points every module at the temporary folder. Modules copy paths from
    config at import time, so each copy is replaced."""
    db_path  = os.path.join(tmp, "tasks.db")
    arch_dir = os.path.join(tmp, "archive")
    att_dir  = os.path.join(tmp, "attachments")

    database.DB_PATH           = db_path
    database.LAST_WORKING_PATH = db_path + ".bak"
    database.APP_DIR           = tmp
    database.ATTACHMENTS_DIR   = att_dir

    archive.ARCHIVE_DIR     = arch_dir
    archive.ATTACHMENTS_DIR = att_dir

    backup.DB_PATH         = db_path
    backup.APP_DIR         = tmp
    backup.BACKUP_DIR      = os.path.join(tmp, "backups")
    backup.ARCHIVE_DIR     = arch_dir
    backup.ATTACHMENTS_DIR = att_dir
    backup.SETTINGS_PATH   = os.path.join(tmp, "settings.json")

    settings.SETTINGS_PATH = os.path.join(tmp, "settings.json")
    settings.reload()


def test_crud():
    tid = database.create_task("Test task", "Test task description")
    cps = database.get_checkpoints(tid)
    assert len(cps) == len(config.DEFAULT_TEMPLATE)
    assert cps[0]["name"] == config.DEFAULT_TEMPLATE[0]["name"]

    nid = database.create_note(tid, "First meeting", "Project scope discussed")
    assert database.get_notes(tid)[0]["id"] == nid

    database.create_link(tid, "Project folder", r"C:\projects\TestProject", "folder")
    database.create_link(tid, "Specification", r"C:\projects\TestProject\spec.docx", "file")
    assert len(database.get_links(tid)) == 2

    database.delete_task(tid)
    assert database.get_task(tid) is None
    assert database.get_checkpoints(tid) == []
    assert database.get_notes(tid) == []
    assert database.get_links(tid) == []

    # Changing a checkpoint which does not exist anymore is not an error
    database.set_checkpoint_completed(cps[0]["id"], True)
    database.set_iteration_count(cps[0]["id"], 1)
    database.update_checkpoint(cps[0]["id"], "x", "check")


def test_counters_are_optional():
    tid = database.create_task("Counters")
    cps = database.get_checkpoints(tid)
    counters = [c for c in cps if c["checkpoint_type"] == "counter"]
    checks   = [c for c in cps if c["checkpoint_type"] != "counter"]
    assert counters, "template is expected to contain counters"

    # Unused counters are not counted
    assert database.get_task_progress(tid) == (0, len(checks))
    assert database.get_task_checkpoint_status(tid) == config.STATUS_NOT_STARTED

    # All checkboxes done, counters untouched -> task is finished
    for c in checks:
        database.set_checkpoint_completed(c["id"], True)
    assert database.get_task_progress(tid) == (len(checks), len(checks))
    assert database.get_task_checkpoint_status(tid) == config.STATUS_FINISHED

    # A used counter counts as a finished checkpoint
    database.set_iteration_count(counters[0]["id"], 2)
    assert database.get_task_progress(tid) == (len(checks) + 1, len(checks) + 1)

    # Group containing a counter is completed by its checkboxes alone
    for c in checks:
        database.set_checkpoint_completed(c["id"], False)
    database.set_iteration_count(counters[0]["id"], 0)
    # ("In review" = template checkpoints 7 and 8, where 7 is a counter)
    for c in checks:
        if c["template_order"] in (1, 2, 3, 4, 5, 8):
            database.set_checkpoint_completed(c["id"], True)
    assert database.get_task_checkpoint_status(tid) == "In review"

    database.delete_task(tid)


def test_archive_name_is_unique():
    # An archive with the same name already exists (e.g. the task id was used
    # again after the database was restored from its last working copy)
    tid  = database.create_task("Same title", checkpoints=[])
    name = (f"task_{tid}_finished_{archive._safe_filename('Same title')}_"
            f"{datetime.now().strftime('%Y-%m-%d')}.zip")
    existing = os.path.join(archive.ARCHIVE_DIR, name)
    os.makedirs(archive.ARCHIVE_DIR, exist_ok=True)
    with open(existing, "wb") as f:
        f.write(b"older archive")

    new_path = archive.export_task_to_zip(tid, "active")
    assert new_path != existing
    with open(existing, "rb") as f:
        assert f.read() == b"older archive", "existing archive was overwritten"
    assert zipfile.is_zipfile(new_path)


def test_backup():
    tid = database.create_task("Backed up")
    database.create_note(tid, "Note", "content")
    zip_path, skipped = backup.create_backup()
    assert skipped == []
    assert zip_path.endswith(".zip") and os.path.exists(zip_path)
    assert not os.path.exists(zip_path + ".tmp")
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        meta  = json.loads(zf.read("backup_meta.json"))
    assert "tasks.db" in names
    assert meta["packed_files"] == len(names) - 1   # all except the metadata
    assert meta["skipped_files"] == []


def _write(path: str, content: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def _read(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def test_status_after_move_delete():
    # Groups are bound to template checkpoints, not to their position on the list
    tid = database.create_task("Status")
    by_tpl = {c["template_order"]: c for c in database.get_checkpoints(tid)}
    database.set_checkpoint_completed(by_tpl[1]["id"], True)
    database.set_checkpoint_completed(by_tpl[2]["id"], True)
    assert database.get_task_checkpoint_status(tid) == "Started"

    for _ in range(len(by_tpl)):
        database.move_checkpoint(tid, by_tpl[2]["id"], "down")
    assert database.get_checkpoints(tid)[-1]["id"] == by_tpl[2]["id"]
    assert database.get_task_checkpoint_status(tid) == "Started"

    # "In progress" = 3, 4, 5; with 3 deleted the group is completed by 4 and 5
    assert database.delete_checkpoint(by_tpl[3]["id"])
    orders = [c["checkpoint_order"] for c in database.get_checkpoints(tid)]
    assert orders == list(range(1, len(orders) + 1)), "orders not renumbered"
    assert database.get_task_checkpoint_status(tid) == "Started"
    database.set_checkpoint_completed(by_tpl[4]["id"], True)
    database.set_checkpoint_completed(by_tpl[5]["id"], True)
    assert database.get_task_checkpoint_status(tid) == "In progress"

    # The same status computed from the batch query of the task list
    batch = database.get_checkpoints_by_task(on_hold=False)[tid]
    assert database.checkpoint_status(batch) == "In progress"
    database.delete_task(tid)


def test_archive_roundtrip():
    tid = database.create_task("Roundtrip", "with everything")
    database.create_note(tid, "Note", "**content**")
    database.create_link(tid, "Folder", r"C:\somewhere", "folder")
    att_dir = database.get_attachment_dir(tid, "Roundtrip")
    kept    = os.path.join(att_dir, "kept.txt")
    removed = os.path.join(att_dir, "removed.txt")
    _write(kept, b"kept")
    _write(removed, b"removed")
    database.create_attachment(tid, "kept.txt", kept)
    rid = database.create_attachment(tid, "removed.txt", removed)
    moved = os.path.join(att_dir, "deleted", "removed.txt")
    _write(moved, _read(removed))
    os.remove(removed)
    database.soft_delete_attachment(rid, moved)

    zip_path = archive.export_task_to_zip(tid, "active")
    assert database.get_task(tid) is None
    assert not os.path.exists(att_dir), "attachments folder not removed"
    assert not os.path.exists(zip_path + ".tmp")

    new_id = archive.import_task_from_zip(zip_path)
    task = database.get_task(new_id)
    assert task["title"] == "Roundtrip" and task["description"] == "with everything"
    assert len(database.get_checkpoints(new_id)) == len(config.DEFAULT_TEMPLATE)
    assert [n["content"] for n in database.get_notes(new_id)] == ["**content**"]
    assert [l["path"] for l in database.get_links(new_id)] == [r"C:\somewhere"]

    atts = {a["filename"]: a for a in database.get_attachments(new_id, include_deleted=True)}
    assert set(atts) == {"kept.txt", "removed.txt"}
    assert atts["removed.txt"]["deleted"] == 1
    assert _read(database.resolve_attachment_path(atts["kept.txt"]["stored_path"])) == b"kept"
    assert _read(database.resolve_attachment_path(atts["removed.txt"]["stored_path"])) == b"removed"

    # Removing from the archive moves the ZIP, never deletes it
    archive.remove_archived_task(zip_path)
    assert not os.path.exists(zip_path)
    assert os.path.exists(os.path.join(archive.ARCHIVE_DIR, "removed", os.path.basename(zip_path)))
    database.delete_task(new_id)


def test_restore_backup_merge():
    keep = database.create_task("Keep")
    lost = database.create_task("Lost")
    database.create_note(lost, "Lost note", "text")
    zip_path, _ = backup.create_backup()

    database.delete_task(lost)
    result = backup.restore_backup(zip_path)
    assert result["tasks_added"] == 1

    titles = [t["title"] for t in database.get_all_tasks()]
    assert titles.count("Keep") == 1 and titles.count("Lost") == 1
    restored = next(t for t in database.get_all_tasks() if t["title"] == "Lost")
    assert [n["title"] for n in database.get_notes(restored["id"])] == ["Lost note"]

    # Restoring the same backup again adds nothing
    assert backup.restore_backup(zip_path)["tasks_added"] == 0
    database.delete_task(keep)
    database.delete_task(restored["id"])


def test_verify_db_restores():
    tid = database.create_task("Survivor")
    assert database.backup_db()
    assert database.backup_db()       # second copy: the first one becomes the daily copy .bak.1
    assert os.path.exists(database.LAST_WORKING_PATH + ".1")
    assert database.verify_db() == "ok"

    # Database and the last working copy damaged, so the daily copy is used
    garbage = b"this is not a database" * 100
    _write(database.DB_PATH, garbage)
    _write(database.LAST_WORKING_PATH, garbage)
    assert database.verify_db() == "restored"
    assert database.get_task(tid)["title"] == "Survivor"
    folder = os.path.dirname(database.DB_PATH)
    assert any(f.startswith("tasks.db.corrupt_") for f in os.listdir(folder))
    database.delete_task(tid)


def test_unique_path():
    folder = os.path.join(os.path.dirname(database.DB_PATH), "unique")
    path = os.path.join(folder, "a.txt")
    assert database.unique_path(path) == path
    _write(path, b"1")
    second = database.unique_path(path)
    assert second.endswith("a_2.txt")
    _write(second, b"2")
    assert database.unique_path(path).endswith("a_3.txt")


def test_migrate_legacy_data():
    # Data of a version before 0.6 lies next to the program files
    tid = database.create_task("Legacy task")
    root = os.path.dirname(database.DB_PATH)
    legacy = os.path.join(root, "legacy")
    _write(os.path.join(legacy, "tasks.db"), _read(database.DB_PATH))
    _write(os.path.join(legacy, "tasks.db.bak"), _read(database.DB_PATH))
    _write(os.path.join(legacy, "settings.json"), b'{"theme": "light"}')
    _write(os.path.join(legacy, "attachments", "1_x", "a.txt"), b"att")
    _write(os.path.join(legacy, "main_window.pyw"), b"program file - not data")
    database.delete_task(tid)

    saved = (database.DB_PATH, database.APP_DIR)
    new_dir = os.path.join(root, "new_data")
    database.DB_PATH = os.path.join(new_dir, "tasks.db")
    database.APP_DIR = new_dir
    try:
        copied = database.migrate_legacy_data(legacy)
        assert set(copied) == {"tasks.db", "tasks.db.bak", "settings.json", "attachments"}, copied
        assert any(t["title"] == "Legacy task" for t in database.get_all_tasks())
        assert _read(os.path.join(new_dir, "attachments", "1_x", "a.txt")) == b"att"
        assert not os.path.exists(os.path.join(new_dir, "main_window.pyw"))
        assert os.path.exists(os.path.join(legacy, "tasks.db")), "old data must stay"
        # Second start: the data folder has a database, nothing is copied again
        assert database.migrate_legacy_data(legacy) == []
        assert database.migrate_legacy_data(None) == []
    finally:
        database.DB_PATH, database.APP_DIR = saved


def test_due_date_and_duplicate():
    tid = database.create_task("Due", "desc", due_date="2030-01-31")
    assert database.get_task(tid)["due_date"] == "2030-01-31"
    database.update_task(tid, "Due", "desc", None)
    assert database.get_task(tid)["due_date"] is None
    database.update_task(tid, "Due", "desc", "2030-02-01")

    cps = database.get_checkpoints(tid)
    database.set_checkpoint_completed(cps[0]["id"], True)
    database.create_note(tid, "Note", "x")
    database.create_link(tid, "Spec", r"C:\spec.docx", "file")

    copy_id = database.duplicate_task(tid)
    copy = database.get_task(copy_id)
    assert copy["title"] == "Due (copy)" and copy["due_date"] == "2030-02-01"
    copy_cps = database.get_checkpoints(copy_id)
    assert [c["name"] for c in copy_cps] == [c["name"] for c in cps]
    assert [c["status_group"] for c in copy_cps] == [c["status_group"] for c in cps]
    assert not any(c["completed"] for c in copy_cps), "copy must start not completed"
    assert [l["path"] for l in database.get_links(copy_id)] == [r"C:\spec.docx"]
    assert database.get_notes(copy_id) == []
    database.delete_task(tid)
    database.delete_task(copy_id)


def test_parse_due_date():
    from datetime import date, timedelta
    p = ui_helpers.parse_due_date
    assert p("") is None
    assert p("2026-02-28") == "2026-02-28"
    assert p("today") == date.today().isoformat()
    assert p("+7") == (date.today() + timedelta(days=7)).isoformat()
    for wrong in ("2026-02-30", "31.12.2026", "tomorrow", "+x"):
        try:
            p(wrong)
        except ValueError:
            continue
        raise AssertionError(f"accepted {wrong!r}")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert ui_helpers.due_state(yesterday, finished=False) == "overdue"
    assert ui_helpers.due_state(yesterday, finished=True) is None


def test_completed_at():
    tid = database.create_task("Dates")
    cps = database.get_checkpoints(tid)
    check = next(c for c in cps if c["checkpoint_type"] == "check")
    counter = next(c for c in cps if c["checkpoint_type"] == "counter")

    def get(cid):
        return next(c for c in database.get_checkpoints(tid) if c["id"] == cid)

    database.set_checkpoint_completed(check["id"], True)
    assert get(check["id"])["completed_at"]
    database.set_checkpoint_completed(check["id"], False)
    assert get(check["id"])["completed_at"] is None

    database.set_iteration_count(counter["id"], 1)
    first = get(counter["id"])["completed_at"]
    assert first
    database.set_iteration_count(counter["id"], 0)
    assert get(counter["id"])["completed_at"] is None
    database.delete_task(tid)


def test_templates():
    tpl = database.create_template("Review")
    first = database.get_template_checkpoints(tpl)[0]
    database.update_template_checkpoint(first["id"], "Draft", "check", "Drafted")
    database.add_template_checkpoint(tpl, "Iterations", "counter", None)
    database.add_template_checkpoint(tpl, "Reviewed", "check", "Reviewed")
    database.add_template_checkpoint(tpl, "Sent", "check", None)
    assert database.template_status_flow(tpl) == [
        config.STATUS_NOT_STARTED, "Drafted", "Reviewed", config.STATUS_FINISHED]

    tid = database.create_task("From template", template_id=tpl)
    cps = {c["name"]: c for c in database.get_checkpoints(tid)}
    assert list(cps) == ["Draft", "Iterations", "Reviewed", "Sent"]
    database.set_checkpoint_completed(cps["Draft"]["id"], True)
    assert database.get_task_checkpoint_status(tid) == "Drafted"
    database.set_checkpoint_completed(cps["Reviewed"]["id"], True)
    assert database.get_task_checkpoint_status(tid) == "Reviewed"

    # Changing the template does not change the existing task
    database.update_template_checkpoint(first["id"], "Draft", "check", "Something else")
    assert database.get_task_checkpoint_status(tid) == "Reviewed"

    # Default template: new tasks without template_id use it
    database.set_default_template(tpl)
    assert database.get_default_template_id() == tpl
    plain = database.create_task("Default now")
    assert database.get_checkpoints(plain)[0]["name"] == "Draft"

    # Moving and deleting checkpoints of a template
    sent = database.get_template_checkpoints(tpl)[-1]
    database.move_template_checkpoint(sent["id"], "up")
    assert database.get_template_checkpoints(tpl)[-2]["name"] == "Sent"
    assert database.delete_template_checkpoint(sent["id"])
    assert [c["position"] for c in database.get_template_checkpoints(tpl)] == [1, 2, 3]

    # Deleting the default template makes another one the default; the last one stays
    copy = database.duplicate_template(tpl, "Review copy")
    assert len(database.get_template_checkpoints(copy)) == 3
    assert database.delete_template(tpl)
    assert database.get_default_template_id() is not None
    for t in database.get_templates()[1:]:
        database.delete_template(t["id"])
    assert not database.delete_template(database.get_templates()[0]["id"])

    # Back to the default template of the other tests
    database.set_default_template(database.get_templates()[0]["id"])
    database.delete_task(tid)
    database.delete_task(plain)


def test_legacy_archive_status():
    # Checkpoints saved before 0.7: no status_group, status from template_order or name
    data = {
        "meta": {"source": "active"},
        "task": {"title": "Old archive", "created_at": "2025-01-01T10:00:00"},
        "stages": [
            {"stage_order": 1, "name": "Kick-off", "stage_type": "check", "completed": 1},
            {"stage_order": 2, "name": "CheckPoint 1", "stage_type": "check", "completed": 1},
            {"stage_order": 3, "name": "CheckPoint 2", "stage_type": "check", "completed": 0},
        ],
    }
    tid = archive.insert_task_data(data, on_hold=False)
    assert database.get_task_checkpoint_status(tid) == "Started"
    database.delete_task(tid)


def test_search_notes():
    tid = database.create_task("Search")
    database.create_note(tid, "Spotkanie", "Wyjazd do ŁODZI w piątek")
    database.create_note(tid, "Other", "nothing here")
    assert database.search_notes("łódź") == {}
    assert database.search_notes("łodzi") == {tid: ["Spotkanie"]}
    assert database.search_notes("spotk") == {tid: ["Spotkanie"]}
    assert database.search_notes("   ") == {}
    database.delete_task(tid)


def test_restore_attachment():
    tid = database.create_task("Attachments")
    folder = database.get_attachment_dir(tid, "Attachments")
    path = os.path.join(folder, "a.txt")
    _write(path, b"data")
    att = database.create_attachment(tid, "a.txt", path)
    moved = os.path.join(folder, "deleted", "a.txt")
    _write(moved, b"data")
    os.remove(path)
    database.soft_delete_attachment(att, moved)
    assert database.get_attachments(tid) == []
    os.replace(moved, path)
    database.restore_attachment(att, path)
    restored = database.get_attachments(tid)
    assert len(restored) == 1 and database.resolve_attachment_path(
        restored[0]["stored_path"]) == os.path.abspath(path)
    database.delete_task(tid)


def test_auto_backup():
    import time
    for f in os.listdir(backup.BACKUP_DIR) if os.path.exists(backup.BACKUP_DIR) else []:
        os.remove(os.path.join(backup.BACKUP_DIR, f))
    assert not backup.auto_backup_due(0), "0 days = automatic backups off"
    assert backup.auto_backup_due(7)

    manual, _ = backup.create_backup()
    autos = []
    for age_days in (30, 20, 10):
        path, _ = backup.create_backup(auto=True)
        old = time.time() - age_days * 86400
        os.utime(path, (old, old))
        autos.append(path)
    # The newest automatic backup is 10 days old
    assert backup.auto_backup_due(7)
    assert not backup.auto_backup_due(14)

    removed = backup.prune_auto_backups(keep=2)
    assert removed == [os.path.basename(autos[0])], removed
    assert os.path.exists(manual), "a backup made by hand must never be removed"
    listed = backup.list_backups()
    assert [b["auto"] for b in listed].count(True) == 2


def test_report():
    tid = database.create_task("Report | pipe", "line one\nline two", due_date="2000-01-01")
    held = database.create_task("Held")
    database.set_on_hold(held, True)

    rows = report.collect_rows(include_on_hold=True)
    titles = [r["Title"] for r in rows]
    assert "Report | pipe" in titles and "Held" in titles
    assert "Held" not in [r["Title"] for r in report.collect_rows(include_on_hold=False)]
    row = next(r for r in rows if r["Title"] == "Report | pipe")
    assert row["Description"] == "line one line two" and row["Due date"] == "2000-01-01"

    folder = os.path.dirname(database.DB_PATH)
    md, csv_path = os.path.join(folder, "r.md"), os.path.join(folder, "r.csv")
    report.write_markdown(md, rows)
    report.write_csv(csv_path, rows)
    text = _read(md).decode("utf-8")
    assert "Report \\| pipe" in text and "(overdue)" in text
    assert _read(csv_path).startswith(b"\xef\xbb\xbf"), "CSV needs a BOM for Excel"
    database.delete_task(tid)
    database.delete_task(held)


def test_old_schema_migration():
    # Database of an early version: task_stages table, no on_hold, no attachments,
    # no template columns, no due dates
    import sqlite3
    folder = os.path.join(os.path.dirname(database.DB_PATH), "old_schema")
    os.makedirs(folder, exist_ok=True)
    old_db = os.path.join(folder, "tasks.db")
    conn = sqlite3.connect(old_db)
    conn.executescript("""
        CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            description TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE task_stages (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
            stage_order INTEGER NOT NULL, name TEXT NOT NULL,
            stage_type TEXT NOT NULL DEFAULT 'check', completed INTEGER NOT NULL DEFAULT 0,
            iteration_count INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE task_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
            title TEXT NOT NULL, content TEXT DEFAULT '', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL);
        CREATE TABLE task_links (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
            label TEXT NOT NULL, path TEXT NOT NULL, link_type TEXT NOT NULL DEFAULT 'file');
        INSERT INTO tasks VALUES (1, 'Old task', '', '2025-01-01T10:00:00', '2025-01-02T10:00:00');
        INSERT INTO task_stages (task_id, stage_order, name, completed) VALUES
            (1, 1, 'Kick-off', 1), (1, 2, 'CheckPoint 1', 1), (1, 3, 'CheckPoint 2', 0);
        INSERT INTO task_notes VALUES (1, 1, 'Note', 'x', '2025-01-01T10:00:00',
                                       '2025-03-01T10:00:00');
    """)
    conn.commit()
    conn.close()

    saved = (database.DB_PATH, database.APP_DIR)
    database.DB_PATH, database.APP_DIR = old_db, folder
    try:
        database.init_db()
        database.init_db()   # a second start must not fail or change anything
        task = database.get_task(1)
        assert task["due_date"] is None and task["on_hold"] == 0
        assert task["updated_at"] == "2025-03-01T10:00:00", "last activity from the note"
        assert database.get_task_checkpoint_status(1) == "Started"
        assert [t["name"] for t in database.get_templates()] == [config.DEFAULT_TEMPLATE_NAME]
        assert database.get_attachments(1) == []
    finally:
        database.DB_PATH, database.APP_DIR = saved


def test_settings():
    assert settings.get("idle_days") == settings.DEFAULTS["idle_days"]
    settings.update(idle_days=30, geometry={"main": "900x600+10+10"})
    settings.reload()
    assert settings.get("idle_days") == 30
    assert settings.get("geometry")["main"] == "900x600+10+10"
    settings.update(idle_days="wrong type")
    assert settings.get("idle_days") == settings.DEFAULTS["idle_days"]


def main():
    tests = [test_crud, test_counters_are_optional, test_status_after_move_delete,
             test_archive_name_is_unique, test_archive_roundtrip, test_backup,
             test_restore_backup_merge, test_unique_path, test_migrate_legacy_data,
             test_due_date_and_duplicate, test_parse_due_date, test_completed_at,
             test_templates, test_legacy_archive_status, test_search_notes,
             test_restore_attachment, test_auto_backup, test_report,
             test_old_schema_migration, test_settings,
             test_verify_db_restores]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        _isolate(tmp)
        database.init_db()
        failed = 0
        for t in tests:
            try:
                t()
                print(f"PASS  {t.__name__}")
            except Exception as ex:
                failed += 1
                print(f"FAIL  {t.__name__}: {type(ex).__name__}: {ex}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
