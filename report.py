# Summary of the tasks exported to Markdown or CSV

import csv
from datetime import date, datetime

from config import APP_TITLE, STATUS_FINISHED
from database import (get_all_tasks, get_on_hold_tasks, get_checkpoints_by_task,
                      checkpoint_progress, checkpoint_status)

COLUMNS = ["Title", "List", "Status", "Progress", "Due date", "Created",
           "Last activity", "Description"]


def collect_rows(include_on_hold: bool = True) -> list[dict]:
    """One row per task: active tasks first, then tasks on hold; each group sorted by
    due date (tasks without one at the end), then by title."""
    rows = []
    groups = [("Active", get_all_tasks(), False)]
    if include_on_hold:
        groups.append(("On hold", get_on_hold_tasks(), True))
    for list_name, tasks, on_hold in groups:
        checkpoints = get_checkpoints_by_task(on_hold=on_hold)
        tasks = sorted(tasks, key=lambda t: (t["due_date"] or "9999-99-99", t["title"].lower()))
        for t in tasks:
            cps = checkpoints.get(t["id"], [])
            done, total = checkpoint_progress(cps)
            rows.append({
                "Title":         t["title"],
                "List":          list_name,
                "Status":        checkpoint_status(cps),
                "Progress":      f"{done}/{total}",
                "Due date":      t["due_date"] or "",
                "Created":       t["created_at"][:10],
                "Last activity": (t["updated_at"] or "")[:16].replace("T", " "),
                "Description":   " ".join((t["description"] or "").split()),
            })
    return rows


def write_csv(path: str, rows: list[dict]):
    """CSV in UTF-8 with BOM, so Excel shows Polish letters correctly."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: str, rows: list[dict]):
    def cell(text: str) -> str:
        return str(text).replace("|", "\\|")

    today = date.today().isoformat()
    lines = [
        f"# {APP_TITLE}: tasks on {today}",
        "",
        f"Exported {datetime.now().strftime('%Y-%m-%d %H:%M')}, {len(rows)} task(s).",
        "",
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "|".join("---" for _ in COLUMNS) + "|",
    ]
    for r in rows:
        due = r["Due date"]
        if due and due < today and r["Status"] != STATUS_FINISHED:
            due = f"**{due} (overdue)**"
        values = dict(r, **{"Due date": due})
        lines.append("| " + " | ".join(cell(values[c]) for c in COLUMNS) + " |")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
