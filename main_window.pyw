# Application start and the main window

import os
import sys

# Built as a windowed application there is no console: sys.stdout and sys.stderr are
# None and the first print() of any library would crash the program
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import queue
import threading
import tkinter as tk
from datetime import date, datetime
from tkinter import ttk, messagebox, filedialog

from filelock import FileLock, Timeout

import settings
from database import (
    init_db, backup_db, verify_db, migrate_legacy_data,
    get_all_tasks, get_on_hold_tasks, get_checkpoints_by_task, search_notes,
    create_task, set_on_hold, checkpoint_progress, checkpoint_status,
    get_templates, get_default_template_id,
)
from config import (APP_NAME, APP_TITLE, MAIN_WINDOW_SIZE, ARCHIVE_DIR,
                    DEFAULT_CHECKPOINT, DB_PATH, DB_CHECK_INTERVAL_MS, DATA_DIR,
                    LEGACY_DATA_DIR, ASSETS_DIR, INSTANCE_LOCK_PATH)
from archive import export_task_to_zip, import_task_from_zip, list_archive, remove_archived_task
from backup import (create_backup, list_backups, delete_backup, restore_backup,
                    auto_backup_due, prune_auto_backups)
from report import collect_rows, write_csv, write_markdown
from theme import load_theme

# The theme must load before ui_helpers and task_window read the colours
load_theme()

from ui_helpers import (COLORS, FONT_BODY, FONT_SMALL, font, Dialog, make_button,
                        set_button_enabled, bind_hover, make_scroll_area,
                        widget_alive, open_path, remember_geometry, save_geometries,
                        parse_due_date, due_text, due_color, DUE_DATE_HINT, make_root)
from settings_window import SettingsDialog, TemplatesWindow

FONT_TITLE   = font(20, "bold")
FONT_HEADING = font(12, "bold")

SORT_OPTIONS = [
    ("Last activity",  "last_activity"),
    ("Due date",       "due_date"),
    ("Creation date",  "created_at"),
    ("Progress",       "progress"),
    ("Title A–Z",      "title"),
]

# Refresh interval of the tasks list in ms
AUTO_REFRESH_MS = 5000


# Helper: mouse wheel scrolling

def _enable_mousewheel_scroll(root):
    """One mouse wheel handler for the whole application.
    The wheel scrolls the list under the cursor, in any window of the
    application, also in one which is in the background. A window covered by
    another one is not under the cursor, so it is never scrolled.
    Windows and macOS send <MouseWheel> (delta 120 per notch on Windows, small
    numbers on macOS); Linux/X11 sends <Button-4> (up) and <Button-5> (down)."""
    def _scroll(event, steps=None):
        try:
            widget = root.winfo_containing(event.x_root, event.y_root)
        except Exception:
            return
        if steps is None:
            steps = int(-1 * (event.delta / 120))
            if steps == 0:
                steps = -1 if event.delta > 0 else 1

        while widget is not None:
            if isinstance(widget, tk.Text):
                # Text widget scrolls itself when the event is addressed to it
                if widget is not event.widget:
                    widget.yview_scroll(steps, "units")
                return
            if isinstance(widget, tk.Canvas):
                # Nothing to scroll when the whole content is visible
                if widget.yview() != (0.0, 1.0):
                    widget.yview_scroll(steps, "units")
                return
            widget = widget.master

    root.bind_all("<MouseWheel>", _scroll)
    if sys.platform not in ("win32", "darwin"):
        root.bind_all("<Button-4>", lambda e: _scroll(e, -1))
        root.bind_all("<Button-5>", lambda e: _scroll(e, 1))


def _set_app_icon(root):
    """Window and taskbar icon. Windows uses the .ico file; Linux and macOS take PNGs
    in several sizes (kept in root.icons, otherwise the garbage collector
    removes the images and the icon disappears)."""
    try:
        if sys.platform == "win32":
            root.iconbitmap(default=str(ASSETS_DIR / "app.ico"))
        else:
            root.icons = [tk.PhotoImage(file=str(ASSETS_DIR / "png" / f"app-{size}.png"))
                          for size in (16, 32, 48, 64, 128, 256)]
            root.iconphoto(True, *root.icons)
    except Exception:
        pass   # no icon is not a reason to stop the application


def _rebuild_window(win):
    """Builds content of a window again, with colors of the active theme.
    The window itself stays open."""
    for w in win.window.winfo_children():
        w.destroy()
    win.window.configure(bg=COLORS["bg"])
    win._build_ui()


class MainWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.configure(bg=COLORS["bg"])
        self.root.minsize(860, 450)
        remember_geometry(self.root, "main", MAIN_WINDOW_SIZE)

        self._task_windows = {}   # task_id -> TaskWindow
        self._aux_windows  = []   # On Hold / Archive / Backup / Templates windows
        self._cards        = {}   # task_id -> widgets and state of the task card
        self._card_order   = []   # task ids in the order of cards on the list
        self._db_error_shown = False
        self._auto_backup_running = False
        self._auto_backup_error_shown = False

        # Check the database before anything is read from it
        db_status = verify_db()
        if db_status == "failed":
            messagebox.showerror(
                "Database Error",
                "The database is damaged and there is no working copy to restore it from.\n\n"
                f"{DB_PATH}\n\n"
                "The application will be closed.",
                parent=root
            )
            root.after(100, root.destroy)
            return

        init_db()
        backup_db()
        _enable_mousewheel_scroll(self.root)
        self._build_ui()
        self._load_tasks()
        self._start_auto_refresh()
        self.root.after(DB_CHECK_INTERVAL_MS, self._check_db)
        self.root.after(5000, self._auto_backup_tick)
        self.root.protocol("WM_DELETE_WINDOW", self._on_app_close)

        if db_status == "restored":
            self.root.after(300, self._show_db_restored)

    def _build_ui(self):
        header = tk.Frame(self.root, bg=COLORS["panel"])
        header.pack(fill="x", side="top")

        tk.Label(
            header, text=f"◈  {APP_TITLE.upper()}",
            font=FONT_TITLE, bg=COLORS["panel"],
            fg=COLORS["accent"], padx=20, pady=14
        ).pack(side="left")

        self._make_button(header, "+ New task",  lambda: self._new_task(),
                          side="right", padx=20, pady=12)
        self._make_button(header, "Archive",  lambda: self._open_archive(),
                          side="right", padx=(0, 4), pady=12, secondary=True)
        self._make_button(header, "On Hold",  lambda: self._open_on_hold(),
                          side="right", padx=(0, 4), pady=12, secondary=True)
        self._make_button(header, "Backup",   lambda: self._open_backup(),
                          side="right", padx=(0, 4), pady=12, secondary=True)
        self._make_button(header, "Settings", lambda: self._open_settings(),
                          side="right", padx=(0, 4), pady=12, secondary=True)
        self._make_button(header, "Export",   lambda: self._export(),
                          side="right", padx=(0, 4), pady=12, secondary=True)

        tk.Frame(self.root, bg=COLORS["accent"], height=2).pack(fill="x")

        filter_bar = tk.Frame(self.root, bg=COLORS["bg"], padx=16, pady=10)
        filter_bar.pack(fill="x")

        tk.Label(filter_bar, text="Search:", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text_dim"]).pack(side="left")

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._load_tasks())
        tk.Entry(
            filter_bar, textvariable=self.search_var,
            font=FONT_BODY, bg=COLORS["card"], fg=COLORS["text"],
            insertbackground=COLORS["text"], relief="flat", width=28
        ).pack(side="left", padx=(6, 20), ipady=4)

        # Sorting
        tk.Label(filter_bar, text="Sort by:", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text_dim"]).pack(side="left")

        self.sort_var = tk.StringVar(value=SORT_OPTIONS[0][0])
        sort_cb = ttk.Combobox(
            filter_bar, textvariable=self.sort_var,
            values=[opt[0] for opt in SORT_OPTIONS],
            state="readonly", width=18, font=FONT_BODY
        )
        sort_cb.pack(side="left", padx=(6, 0), ipady=2)
        sort_cb.bind("<<ComboboxSelected>>", lambda e: self._load_tasks())

        # Combobox style for the active theme
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox",
            fieldbackground=COLORS["card"],
            background=COLORS["card"],
            foreground=COLORS["text"],
            selectbackground=COLORS["card_hover"],
            selectforeground=COLORS["text"],
            bordercolor=COLORS["border"],
            arrowcolor=COLORS["text_dim"],
        )

        self.count_label = tk.Label(filter_bar, text="", font=FONT_SMALL,
                                    bg=COLORS["bg"], fg=COLORS["text_dim"])
        self.count_label.pack(side="right")

        list_frame, self.canvas, self.cards_frame = make_scroll_area(self.root)
        list_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    # Loading tasks

    def _get_sort_key(self) -> str:
        label = self.sort_var.get()
        for opt_label, opt_key in SORT_OPTIONS:
            if opt_label == label:
                return opt_key
        return "last_activity"

    @staticmethod
    def _get_task_state(task: dict, checkpoints: list) -> dict:
        """Returns everything what is shown on the task card besides the task record itself.
        Every change inside a task updates tasks.updated_at, the last activity."""
        done, total = checkpoint_progress(checkpoints)
        finished = total > 0 and done == total
        last_activity = task["updated_at"] or ""

        # Days without activity, when it is more than the limit from Settings (0 = not idle)
        idle = 0
        limit = settings.get("idle_days")
        if limit and last_activity and not finished:
            days = (datetime.now() - datetime.fromisoformat(last_activity)).days
            idle = days if days >= limit else 0

        return {
            "done":          done,
            "total":         total,
            "status":        checkpoint_status(checkpoints),
            "last_activity": last_activity,
            "idle_days":     idle,
            "due_date":      task["due_date"],
            "today":         date.today().isoformat(),   # "due today" changes at midnight
            "note_hit":      "",
        }

    def _get_sorted_tasks(self) -> list:
        """Returns list of (task, state) filtered and sorted according to the filter bar.
        The search looks in titles, descriptions and in the notes of the tasks."""
        query    = self.search_var.get().casefold().strip()
        sort_key = self._get_sort_key()

        tasks = get_all_tasks()   # default: created_at DESC

        note_hits = {}
        if query:
            note_hits = search_notes(query)
            tasks = [t for t in tasks if query in t["title"].casefold()
                     or query in (t["description"] or "").casefold()
                     or t["id"] in note_hits]

        checkpoints = get_checkpoints_by_task(on_hold=False)
        items = []
        for t in tasks:
            state = self._get_task_state(t, checkpoints.get(t["id"], []))
            if t["id"] in note_hits:
                titles = note_hits[t["id"]]
                more = f" (+{len(titles) - 2} more)" if len(titles) > 2 else ""
                state["note_hit"] = "found in notes: " + ", ".join(titles[:2]) + more
            items.append((t, state))

        if sort_key == "due_date":
            # Nearest due date first, tasks without one at the end
            items.sort(key=lambda i: (i[0]["due_date"] is None, i[0]["due_date"] or ""))
        elif sort_key == "last_activity":
            items.sort(key=lambda i: i[1]["last_activity"], reverse=True)
        elif sort_key == "created_at":
            items.sort(key=lambda i: i[0]["created_at"], reverse=True)
        elif sort_key == "progress":
            items.sort(key=lambda i: i[1]["done"] / i[1]["total"] if i[1]["total"] else 0.0,
                       reverse=True)
        elif sort_key == "title":
            items.sort(key=lambda i: i[0]["title"].lower())

        return items

    def _load_tasks(self):
        """Builds the whole list of task cards from scratch."""
        self._build_cards(self._get_sorted_tasks())

    def _build_cards(self, items: list):
        for w in self.cards_frame.winfo_children():
            w.destroy()
        self._cards = {}
        self._card_order = [task["id"] for task, _ in items]

        self.count_label.config(text=f"{len(items)} task{'s' if len(items) != 1 else ''}")

        if not items:
            tk.Label(
                self.cards_frame,
                text="No tasks available. Click '+ New task' to add the first one.",
                font=FONT_BODY, bg=COLORS["bg"], fg=COLORS["text_dim"], pady=40
            ).pack()
            return

        for task, state in items:
            self._make_task_card(task, state)

    def _refresh_tasks(self):
        """Refreshes the list without rebuilding it. Cards are built again only when
        the set of tasks, their order, title or description changed; otherwise only
        the changed values are updated in the existing cards, so nothing blinks."""
        items = self._get_sorted_tasks()

        if [task["id"] for task, _ in items] != self._card_order:
            self._build_cards(items)
            return

        for task, state in items:
            card = self._cards[task["id"]]
            if (task["title"], task["description"]) != (card["title"], card["description"]):
                self._build_cards(items)
                return
            if state != card["state"]:
                self._update_task_card(task, state)

    @staticmethod
    def _status_color(state: dict) -> str:
        if state["done"] == 0:
            return COLORS["status_not_started"]
        if state["done"] == state["total"]:
            return COLORS["status_completed"]
        return COLORS["status_in_progress"]

    @staticmethod
    def _activity_text(state: dict) -> str:
        if state["idle_days"]:
            return f"no activity for {state['idle_days']} days"
        last_act = state["last_activity"]
        return "last activity: " + (last_act[:16].replace("T", "  ") if last_act else "")

    @staticmethod
    def _is_finished(state: dict) -> bool:
        return state["total"] > 0 and state["done"] == state["total"]

    def _make_task_card(self, task: dict, state: dict):
        card = tk.Frame(self.cards_frame, bg=COLORS["card"], pady=12, padx=14)
        card.pack(fill="x", pady=4, padx=2)

        status_bar = tk.Frame(card, bg=self._status_color(state), width=4)
        status_bar.pack(side="left", fill="y", padx=(0, 12))

        info = tk.Frame(card, bg=COLORS["card"])
        info.pack(side="left", fill="both", expand=True)

        row1 = tk.Frame(info, bg=COLORS["card"])
        row1.pack(fill="x")
        tk.Label(row1, text=task["title"], font=FONT_HEADING,
                 bg=COLORS["card"], fg=COLORS["text"], anchor="w").pack(side="left")
        tk.Label(row1, text=task["created_at"][:10], font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"]).pack(side="right")
        due_label = tk.Label(row1, text="", font=font(8, "bold"),
                             bg=COLORS["card"], fg=COLORS["text_dim"])
        due_label.pack(side="right", padx=(0, 12))

        if task["description"]:
            desc = task["description"]
            if len(desc) > 80:
                desc = desc[:77] + "..."
            tk.Label(info, text=desc, font=FONT_SMALL,
                     bg=COLORS["card"], fg=COLORS["text_dim"], anchor="w").pack(fill="x", pady=(2, 4))

        # "found in notes: ..." while searching, only when a note matches
        note_label = tk.Label(info, text="", font=font(8, "italic"),
                              bg=COLORS["card"], fg=COLORS["accent2"], anchor="w")

        progress_frame = tk.Frame(info, bg=COLORS["progress_bg"], height=4)
        progress_frame.pack(fill="x", pady=(4, 2))
        progress_frame.pack_propagate(False)
        progress_fill = tk.Frame(progress_frame, bg=COLORS["progress_fg"])

        bottom_row = tk.Frame(info, bg=COLORS["card"])
        bottom_row.pack(fill="x", pady=(2, 0))

        status_label = tk.Label(bottom_row, text="",
                                font=font(8, "bold"), bg=COLORS["card"],
                                fg=COLORS["accent2"], anchor="w")
        status_label.pack(side="left")

        activity_label = tk.Label(bottom_row, text="",
                                  font=FONT_SMALL, bg=COLORS["card"],
                                  fg=COLORS["text_dim"], anchor="e")
        activity_label.pack(side="right")

        actions = tk.Frame(card, bg=COLORS["card"])
        actions.pack(side="right", padx=(12, 0))

        self._make_button(
            actions, "Put on hold",
            lambda tid=task["id"]: self._hold_task(tid),
            small=True, secondary=True, side="top", padx=2, pady=2
        )

        def open_on_click(e, tid=task["id"]):
            self._open_task(tid)

        for widget in [card, info, row1, bottom_row, progress_frame]:
            widget.bind("<Button-1>", open_on_click)
            widget.configure(cursor="hand2")

        for lbl in info.winfo_children() + row1.winfo_children() + bottom_row.winfo_children():
            try:
                lbl.bind("<Button-1>", open_on_click)
                lbl.configure(cursor="hand2")
            except Exception:
                pass

        bind_hover(card, COLORS["card"], COLORS["card_hover"],
                   exclude=[status_bar, progress_frame, actions])

        # Parts of the card which _update_task_card changes
        self._cards[task["id"]] = {
            "title":          task["title"],
            "description":    task["description"],
            "state":          None,
            "status_bar":     status_bar,
            "progress_fill":  progress_fill,
            "status_label":   status_label,
            "activity_label": activity_label,
            "due_label":      due_label,
            "note_label":     note_label,
            "progress_frame": progress_frame,
            "actions":        actions,
            "archive_btn":    None,
        }
        self._update_task_card(task, state)

    def _update_task_card(self, task: dict, state: dict):
        """Puts current values into an existing task card."""
        card = self._cards[task["id"]]
        is_finished = (state["done"] == state["total"] and state["total"] > 0)

        card["status_bar"].config(bg=self._status_color(state))

        if state["done"] > 0 and state["total"]:
            card["progress_fill"].place(relwidth=state["done"] / state["total"], relheight=1.0)
        else:
            card["progress_fill"].place_forget()

        card["status_label"].config(text=state["status"])
        card["activity_label"].config(
            text=self._activity_text(state),
            fg=COLORS["idle"] if state["idle_days"] else COLORS["text_dim"])

        due, finished = state["due_date"], self._is_finished(state)
        card["due_label"].config(text=due_text(due, finished), fg=due_color(due, finished))

        if state["note_hit"]:
            card["note_label"].config(text=state["note_hit"])
            card["note_label"].pack(fill="x", before=card["progress_frame"])
        else:
            card["note_label"].pack_forget()

        # Archive button is available only for a finished task
        if is_finished and card["archive_btn"] is None:
            card["archive_btn"] = self._make_button(
                card["actions"], "Archive",
                lambda tid=task["id"], ttl=task["title"]: self._archive_task(tid, ttl, "active"),
                small=True, secondary=True, side="top", padx=2, pady=2
            )
        elif not is_finished and card["archive_btn"] is not None:
            card["archive_btn"].destroy()
            card["archive_btn"] = None

        card["state"] = state

    # Actions

    def _new_task(self):
        dialog = NewTaskDialog(self.root)
        self.root.wait_window(dialog.window)
        if dialog.result:
            r = dialog.result
            create_task(r["title"], r["description"],
                        checkpoints=None if r["template_id"] else [],
                        due_date=r["due_date"], template_id=r["template_id"])
            self._load_tasks()

    def _open_task(self, task_id: int):
        from task_window import TaskWindow

        tw = self._task_windows.get(task_id)
        if tw is not None:
            if widget_alive(tw):
                tw.window.lift()
                tw.window.focus_force()
                return
            del self._task_windows[task_id]

        def on_task_close(tid=task_id):
            self._task_windows.pop(tid, None)
            self._refresh_tasks()

        def open_other_task(other_id):
            # A duplicate was created in the task window
            self._load_tasks()
            self._open_task(other_id)

        tw = TaskWindow(self.root, task_id, on_close=on_task_close, open_task=open_other_task)
        if widget_alive(tw):
            self._task_windows[task_id] = tw

    def _close_task_window(self, task_id: int):
        """Closes window of the task if it is open. Unsaved notes are saved first."""
        tw = self._task_windows.pop(task_id, None)
        if tw is not None and widget_alive(tw):
            tw.close()

    def _hold_task(self, task_id: int):
        set_on_hold(task_id, True)
        self._load_tasks()

    def _archive_task(self, task_id: int, title: str, source: str):
        if not messagebox.askyesno(
            "Archive Task",
            f"Are you sure you want to archive the task:\n\n\"{title}\"\n\n"
            f"The task will be removed from the database and saved as a ZIP file in the archive folder.",
            parent=self.root
        ):
            return
        try:
            self._close_task_window(task_id)
            zip_path = export_task_to_zip(task_id, source)
            self._load_tasks()
            messagebox.showinfo(
                "Archived",
                f"Task has been archived:\n{zip_path}",
                parent=self.root
            )
        except Exception as e:
            messagebox.showerror("Error", f"Failed to archive task:\n{e}", parent=self.root)

    def _open_backup(self):
        self._aux_windows.append(BackupWindow(self.root, on_restore=self._load_tasks))

    def _open_settings(self):
        SettingsDialog(self.root, on_theme_change=self._apply_theme,
                       on_templates=self._open_templates)

    def _open_templates(self):
        for win in self._aux_windows:
            if isinstance(win, TemplatesWindow) and widget_alive(win):
                win.window.lift()
                return
        self._aux_windows.append(TemplatesWindow(self.root))

    def _export(self):
        dialog = ExportDialog(self.root)
        self.root.wait_window(dialog.window)
        if not dialog.result:
            return
        ext = dialog.result["format"]
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Export Tasks", defaultextension=f".{ext}",
            initialfile=f"WinDashboard_tasks_{date.today().isoformat()}.{ext}",
            filetypes=[("Markdown", "*.md")] if ext == "md" else [("CSV", "*.csv")])
        if not path:
            return
        try:
            rows = collect_rows(include_on_hold=dialog.result["include_on_hold"])
            (write_markdown if ext == "md" else write_csv)(path, rows)
        except Exception as ex:
            messagebox.showerror("Export", f"Failed to export the tasks:\n{ex}", parent=self.root)
            return
        if messagebox.askyesno("Export", f"{len(rows)} task(s) exported to:\n{path}\n\n"
                               "Open the file now?", parent=self.root):
            open_path(path, parent=self.root)

    def _apply_theme(self):
        """Builds content of all open windows again with colors of the new theme.
        No window is closed and nothing typed in is lost."""
        search, sort_label = self.search_var.get(), self.sort_var.get()

        for w in self.root.winfo_children():
            if not isinstance(w, tk.Toplevel):
                w.destroy()
        self.root.configure(bg=COLORS["bg"])
        self._build_ui()
        self.sort_var.set(sort_label)
        self.search_var.set(search)   # loads the list of tasks as well

        for tw in list(self._task_windows.values()):
            if widget_alive(tw):
                tw.rebuild()

        self._aux_windows = [w for w in self._aux_windows if widget_alive(w)]
        for win in self._aux_windows:
            _rebuild_window(win)

    def _open_on_hold(self):
        self._aux_windows.append(OnHoldWindow(
            self.root, on_restore=self._load_tasks, on_archive=self._load_tasks,
            before_archive=self._close_task_window))

    def _open_archive(self):
        self._aux_windows.append(ArchiveWindow(self.root, on_restore=self._load_tasks))

    def _start_auto_refresh(self):
        # Planned first, so an error below doesn't stop the refreshing
        self.root.after(AUTO_REFRESH_MS, self._start_auto_refresh)

        dead = [tid for tid, tw in self._task_windows.items() if not widget_alive(tw)]
        for tid in dead:
            del self._task_windows[tid]
        self._aux_windows = [w for w in self._aux_windows if widget_alive(w)]

        self._refresh_tasks()

        # On Hold and Archive windows show changes made in other windows
        for win in self._aux_windows:
            refresh = getattr(win, "refresh", None)
            if refresh:
                try:
                    refresh()
                except Exception:
                    pass

    # Database check

    def _check_db(self):
        """Periodic check of the database. A database which is fine is saved as the
        last working copy; a damaged one is restored from that copy."""
        self.root.after(DB_CHECK_INTERVAL_MS, self._check_db)

        self._auto_backup_tick()

        db_status = verify_db()
        if db_status == "ok":
            backup_db()
            self._db_error_shown = False
        elif db_status == "restored":
            init_db()
            self._reload_after_db_change()
            self._show_db_restored()
        elif not self._db_error_shown:
            self._db_error_shown = True
            messagebox.showerror(
                "Database Error",
                "The database is damaged and there is no working copy to restore it from.\n\n"
                f"{DB_PATH}",
                parent=self.root
            )

    # Automatic backup

    def _auto_backup_tick(self):
        """Creates an automatic backup in the background when the last one is older than
        the interval from Settings, then removes the oldest automatic backups."""
        if self._auto_backup_running or not auto_backup_due(settings.get("auto_backup_days")):
            return
        self._auto_backup_running = True
        keep = settings.get("auto_backup_keep")
        result = queue.Queue()

        def worker():
            try:
                create_backup(auto=True)
                prune_auto_backups(keep)
                result.put(None)
            except Exception as ex:
                result.put(ex)

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(1000, self._poll_auto_backup, result)

    def _poll_auto_backup(self, result: queue.Queue):
        try:
            error = result.get_nowait()
        except queue.Empty:
            self.root.after(1000, self._poll_auto_backup, result)
            return
        self._auto_backup_running = False

        if error is None:
            self._auto_backup_error_shown = False
        elif not self._auto_backup_error_shown:
            self._auto_backup_error_shown = True   # once, not every 10 minutes
            messagebox.showwarning(
                "Automatic Backup",
                f"The automatic backup failed:\n{error}\n\n"
                "It will be tried again in 10 minutes.",
                parent=self.root)

        # An open Backup window shows the new file
        for win in self._aux_windows:
            if isinstance(win, BackupWindow) and widget_alive(win) and not win._backup_running:
                win._load()

    def _show_db_restored(self):
        messagebox.showwarning(
            "Database Restored",
            "The database was damaged and has been restored from the last working copy.\n\n"
            "Changes made after the last check of the database may be missing.\n"
            "The damaged file was kept next to the database (tasks.db.corrupt_...).",
            parent=self.root
        )

    def _reload_after_db_change(self):
        """Reloads everything shown after the database content was replaced."""
        for task_id, tw in list(self._task_windows.items()):
            if widget_alive(tw):
                tw.reload()
            if not widget_alive(tw):
                self._task_windows.pop(task_id, None)
        self._load_tasks()
        self._aux_windows = [w for w in self._aux_windows if widget_alive(w)]
        for win in self._aux_windows:
            _rebuild_window(win)

    def _on_app_close(self):
        """Closing the application: unsaved notes are saved, the database is checked
        and saved as the last working copy."""
        for tw in list(self._task_windows.values()):
            if widget_alive(tw):
                try:
                    tw.save_open_notes()
                except Exception:
                    pass
        backup_db()
        save_geometries()
        self.root.destroy()

    # UI helpers

    def _make_button(self, parent, text, command,
                     side="left", padx=4, pady=4,
                     small=False, secondary=False):
        btn = make_button(parent, text, command,
                          kind="secondary" if secondary else "primary", small=small)
        btn.pack(side=side, padx=padx, pady=pady)
        return btn


# Dialog: New task

class NewTaskDialog(Dialog):
    def __init__(self, parent):
        super().__init__(parent, "New Task", width=460)

        self.add_label("Title *")
        self.title_var = self.add_entry(focus=True)

        self.add_label("Short Description (Optional)")
        self.desc_text = self.add_text(height=3)

        self.add_label("Due date (optional)")
        self.due_var = self.add_entry()
        self.add_hint(DUE_DATE_HINT)

        # Templates (default first selected) and the empty kanban as the last choice
        self.add_label("Kanban")
        self._template_ids = [t["id"] for t in get_templates()] + [None]
        labels = [f"{t['name']}  ({t['checkpoint_count']} checkpoints)" for t in get_templates()]
        labels.append(f"Empty kanban  (\"{DEFAULT_CHECKPOINT['name']}\" only)")
        self.template_box = ttk.Combobox(self.form, values=labels, state="readonly",
                                         font=FONT_BODY)
        self.template_box.pack(fill="x", ipady=3, pady=(2, 14))
        default_id = get_default_template_id()
        self.template_box.current(self._template_ids.index(default_id)
                                  if default_id in self._template_ids else 0)

        self.add_buttons("Create Task", self._confirm)

    def _confirm(self):
        title = self.title_var.get().strip()
        if not title:
            return
        try:
            due_date = parse_due_date(self.due_var.get())
        except ValueError:
            self.show_error("Due date: use YYYY-MM-DD, \"today\" or +N days.")
            return
        self.result = {
            "title":        title,
            "description":  self.desc_text.get("1.0", "end").strip(),
            "due_date":     due_date,
            "template_id":  self._template_ids[self.template_box.current()],
        }
        self.window.destroy()


# Dialog: Export

class ExportDialog(Dialog):
    FORMATS = [("Markdown (.md): a table for any Markdown viewer", "md"),
               ("CSV (.csv): opens in Excel", "csv")]

    def __init__(self, parent):
        super().__init__(parent, "Export Tasks", width=420)
        self.add_label("Format")
        self.format_var = self.add_radios([(ext, label) for label, ext in self.FORMATS],
                                          "md", vertical=True)
        self.on_hold_var = self.add_checkbox("Include tasks on hold", True)
        self.add_buttons("Export...", self._confirm)

    def _confirm(self):
        self.result = {"format": self.format_var.get(),
                       "include_on_hold": self.on_hold_var.get()}
        self.window.destroy()


# Common header of the auxiliary windows

def _window_header(window, text: str, fg_key: str = "text_dim") -> tk.Frame:
    header = tk.Frame(window, bg=COLORS["panel"])
    header.pack(fill="x")
    tk.Label(header, text=text, font=FONT_TITLE,
             bg=COLORS["panel"], fg=COLORS[fg_key],
             padx=20, pady=14).pack(side="left")
    return header


# Window: On Hold

class OnHoldWindow:
    def __init__(self, parent, on_restore=None, on_archive=None, before_archive=None):
        self.on_restore = on_restore
        self.on_archive = on_archive
        self.before_archive = before_archive   # function(task_id) called before a task is archived
        self._signature = None

        self.window = tk.Toplevel(parent)
        self.window.title("On Hold")
        self.window.configure(bg=COLORS["bg"])
        self.window.minsize(500, 300)
        remember_geometry(self.window, "on_hold", "700x480")

        self._build_ui()

    def _build_ui(self):
        _window_header(self.window, "ON HOLD")
        tk.Frame(self.window, bg=COLORS["accent"], height=2).pack(fill="x")

        container, self.canvas, self.cards_frame = make_scroll_area(self.window)
        container.pack(fill="both", expand=True, padx=16, pady=12)

        self._load()

    @staticmethod
    def _get_items() -> list:
        """Returns list of (task, (done, total)) of the tasks on hold."""
        checkpoints = get_checkpoints_by_task(on_hold=True)
        return [(t, checkpoint_progress(checkpoints.get(t["id"], [])))
                for t in get_on_hold_tasks()]

    @staticmethod
    def _items_signature(items: list) -> list:
        return [(t["id"], t["title"], t["on_hold_at"], progress) for t, progress in items]

    def refresh(self):
        """Called by the main window every few seconds: the list is built again
        only when something on it changed, so nothing blinks."""
        items = self._get_items()
        if self._items_signature(items) != self._signature:
            self._load(items)

    def _load(self, items: list = None):
        if items is None:
            items = self._get_items()
        self._signature = self._items_signature(items)

        for w in self.cards_frame.winfo_children():
            w.destroy()

        if not items:
            tk.Label(self.cards_frame, text="No tasks on hold.",
                     font=FONT_BODY, bg=COLORS["bg"], fg=COLORS["text_dim"],
                     pady=40).pack()
            return

        for task, (done, total) in items:
            self._make_card(task, done, total)

    def _make_card(self, task: dict, done: int, total: int):
        card = tk.Frame(self.cards_frame, bg=COLORS["card"], pady=10, padx=14)
        card.pack(fill="x", pady=4, padx=2)

        tk.Frame(card, bg=COLORS["text_dim"], width=4).pack(side="left", fill="y", padx=(0, 12))

        info = tk.Frame(card, bg=COLORS["card"])
        info.pack(side="left", fill="both", expand=True)

        row1 = tk.Frame(info, bg=COLORS["card"])
        row1.pack(fill="x")
        tk.Label(row1, text=task["title"], font=font(11, "bold"),
                 bg=COLORS["card"], fg=COLORS["text_dim"], anchor="w").pack(side="left")
        hold_date = (task["on_hold_at"] or "")[:10]
        tk.Label(row1, text=f"on hold: {hold_date}", font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"]).pack(side="right")

        tk.Label(info, text=f"{done} of {total} checkpoints completed", font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"], anchor="w").pack(anchor="w", pady=(2, 0))

        actions = tk.Frame(card, bg=COLORS["card"])
        actions.pack(side="right", padx=(12, 0))

        make_button(actions, "▶ Restore", lambda tid=task["id"]: self._restore(tid),
                    small=True).pack(side="top", pady=2)
        make_button(actions, "Archive",
                    lambda tid=task["id"], ttl=task["title"]: self._archive(tid, ttl),
                    kind="secondary", small=True).pack(side="top", pady=2)

    def _restore(self, task_id: int):
        set_on_hold(task_id, False)
        if self.on_restore:
            self.on_restore()
        self._load()

    def _archive(self, task_id: int, title: str):
        if not messagebox.askyesno(
            "Archive Task",
            f"Are you sure you want to archive the task:\n\n\"{title}\"\n\n"
            f"The task will be deleted from the database and saved as a ZIP file.",
            parent=self.window
        ):
            return
        try:
            if self.before_archive:
                self.before_archive(task_id)
            zip_path = export_task_to_zip(task_id, "onhold")
            if self.on_archive:
                self.on_archive()
            self._load()
            messagebox.showinfo("Task Archived",
                                f"Task has been archived:\n{zip_path}",
                                parent=self.window)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to archive task:\n{e}",
                                 parent=self.window)


# Window: Backup

class BackupWindow:
    def __init__(self, parent, on_restore=None):
        self.on_restore = on_restore
        self._backup_running = False

        self.window = tk.Toplevel(parent)
        self.window.title("Backup")
        self.window.configure(bg=COLORS["bg"])
        self.window.minsize(560, 360)
        remember_geometry(self.window, "backup", "720x500")

        self._build_ui()

    def _build_ui(self):
        header = _window_header(self.window, "BACKUP", fg_key="accent")

        self.create_btn = make_button(header, "+ Create backup", self._create_backup)
        self.create_btn.pack(side="right", padx=12, pady=12)

        tk.Frame(self.window, bg=COLORS["accent"], height=2).pack(fill="x")

        # Backup progress, shown only while a backup is created
        self.status_bar = tk.Frame(self.window, bg=COLORS["panel"])
        self.status_label = tk.Label(
            self.status_bar, text="", font=FONT_SMALL,
            bg=COLORS["panel"], fg=COLORS["text_dim"], padx=16, pady=6
        )
        self.status_label.pack(side="left")

        self.list_frame, self.canvas, self.cards_frame = make_scroll_area(self.window)
        self.list_frame.pack(fill="both", expand=True, padx=16, pady=12)

        if self._backup_running:
            # Window rebuilt (theme changed) while a backup is being created
            set_button_enabled(self.create_btn, False, "Creating...")
            self.status_bar.pack(fill="x", before=self.list_frame)

        self._load()

    def _load(self):
        for w in self.cards_frame.winfo_children():
            w.destroy()

        backups = list_backups()

        if not backups:
            tk.Label(
                self.cards_frame,
                text="No backups available. Click '+ Create backup' to create the first one.",
                font=FONT_BODY, bg=COLORS["bg"], fg=COLORS["text_dim"],
                pady=40
            ).pack()
            return

        for b in backups:
            self._make_card(b)

    def _make_card(self, b: dict):
        meta = b.get("meta", {})
        card = tk.Frame(self.cards_frame, bg=COLORS["card"], pady=10, padx=14)
        card.pack(fill="x", pady=3, padx=2)

        tk.Frame(card, bg=COLORS["accent2"], width=4).pack(
            side="left", fill="y", padx=(0, 12))

        info = tk.Frame(card, bg=COLORS["card"])
        info.pack(side="left", fill="both", expand=True)

        # Line 1: file name + size
        row1 = tk.Frame(info, bg=COLORS["card"])
        row1.pack(fill="x")
        tk.Label(row1, text=b["filename"], font=FONT_BODY,
                 bg=COLORS["card"], fg=COLORS["text"], anchor="w").pack(side="left")
        if b.get("auto"):
            tk.Label(row1, text="  automatic", font=FONT_SMALL,
                     bg=COLORS["card"], fg=COLORS["accent2"]).pack(side="left")
        tk.Label(row1, text=f"{b['size_mb']} MB", font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"]).pack(side="right")

        # Line 2: statistics from metadata
        if meta:
            stats = (
                f"Tasks: {meta.get('tasks_active', '?')} active, "
                f"{meta.get('tasks_on_hold', '?')} on hold, "
                f"{meta.get('tasks_archived', '?')} archived  |  "
                f"Attachments: {meta.get('attachment_files', 0)} files  |  "
                f"Packed: {meta.get('packed_files', '?')} files"
            )
        else:
            stats = "No metadata"
        tk.Label(info, text=stats, font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"], anchor="w").pack(fill="x", pady=(2, 0))

        tk.Label(info, text=f"Created: {b['date']}", font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"], anchor="w").pack(fill="x")

        actions = tk.Frame(card, bg=COLORS["card"])
        actions.pack(side="right", padx=(12, 0))

        make_button(actions, "↩ Restore",
                    lambda p=b["zip_path"], fn=b["filename"]: self._restore(p, fn),
                    small=True).pack(pady=(0, 4))
        make_button(actions, "Open folder",
                    lambda p=b["zip_path"]: self._open_folder(p),
                    kind="secondary", small=True).pack(pady=(0, 4))
        make_button(actions, "Delete",
                    lambda p=b["zip_path"], fn=b["filename"]: self._delete(p, fn),
                    kind="danger", small=True).pack()

    # Creating a backup in a background thread, so the window stays responsive

    def _create_backup(self):
        if self._backup_running:
            return
        self._backup_running = True
        set_button_enabled(self.create_btn, False, "Creating...")
        self.status_bar.pack(fill="x", before=self.list_frame)
        self.status_label.config(text="Preparing backup...")

        messages = queue.Queue()

        def on_progress(arc_name: str, current: int, total: int):
            messages.put(("progress", arc_name, current, total))

        def worker():
            try:
                messages.put(("done", create_backup(progress_callback=on_progress)))
            except Exception as ex:
                messages.put(("error", ex))

        threading.Thread(target=worker, daemon=True).start()
        self.window.after(100, self._poll_backup, messages)

    def _poll_backup(self, messages: queue.Queue):
        """Shows progress of the backup thread; shows the result when it is finished.
        If the window was closed in the meantime the backup still completes."""
        if not widget_alive(self):
            return

        finished = None
        while True:
            try:
                msg = messages.get_nowait()
            except queue.Empty:
                break
            if msg[0] == "progress":
                _, arc_name, current, total = msg
                short = arc_name if len(arc_name) <= 60 else "..." + arc_name[-57:]
                self.status_label.config(text=f"Packing {current}/{total}: {short}")
            else:
                finished = msg

        if finished is None:
            self.window.after(100, self._poll_backup, messages)
            return

        self._backup_running = False
        self.status_bar.pack_forget()
        set_button_enabled(self.create_btn, True, "+ Create backup")

        if finished[0] == "error":
            messagebox.showerror("Backup Error",
                                 f"Failed to create backup:\n{finished[1]}",
                                 parent=self.window)
            return

        zip_path, skipped = finished[1]
        self._load()
        if skipped:
            shown = "\n".join(skipped[:10])
            more  = f"\n... and {len(skipped) - 10} more" if len(skipped) > 10 else ""
            messagebox.showwarning(
                "Backup Created With Warnings",
                f"Backup has been saved:\n{zip_path}\n\n"
                f"{len(skipped)} file(s) could not be read and are NOT in the backup:\n"
                f"{shown}{more}",
                parent=self.window
            )
        else:
            messagebox.showinfo("Backup Created",
                                f"Backup has been saved:\n{zip_path}",
                                parent=self.window)

    # Other actions

    def _restore(self, zip_path: str, filename: str):
        if not messagebox.askyesno(
            "Restore Backup",
            f"Restore data from the backup?\n\n{filename}\n\n"
            "Tasks and archived tasks which are missing now will be added from the backup.\n"
            "Existing tasks will not be changed or removed.",
            parent=self.window
        ):
            return
        try:
            result = restore_backup(zip_path)
            if self.on_restore:
                self.on_restore()
            messagebox.showinfo(
                "Backup Restored",
                f"Tasks added: {result['tasks_added']}\n"
                f"Tasks already existing (skipped): {result['tasks_skipped']}\n"
                f"Archived tasks added: {result['archives_added']}",
                parent=self.window
            )
        except Exception as ex:
            messagebox.showerror(
                "Backup Error",
                f"Failed to restore backup:\n{ex}",
                parent=self.window
            )

    def _open_folder(self, zip_path: str):
        """Opens backup folder in Windows Explorer."""
        open_path(os.path.dirname(zip_path), parent=self.window)

    def _delete(self, zip_path: str, filename: str):
        if not messagebox.askyesno(
            "Delete Backup",
            f"Are you sure you want to delete the backup?\n\n{filename}\n\n"
            "This operation can not be undone.",
            parent=self.window
        ):
            return
        try:
            delete_backup(zip_path)
            self._load()
        except Exception as ex:
            messagebox.showerror("Error",
                f"Failed to delete backup:\n{ex}",
                parent=self.window)


# Window: Archive

class ArchiveWindow:
    def __init__(self, parent, on_restore=None):
        self.on_restore = on_restore
        self._signature = None

        self.window = tk.Toplevel(parent)
        self.window.title("Archive")
        self.window.configure(bg=COLORS["bg"])
        self.window.minsize(600, 350)
        remember_geometry(self.window, "archive", "800x520")
        self._search = ""   # kept when the window is rebuilt (theme change)

        self._build_ui()

    def _build_ui(self):
        _window_header(self.window, "ARCHIVE")
        tk.Frame(self.window, bg=COLORS["accent"], height=2).pack(fill="x")

        search_bar = tk.Frame(self.window, bg=COLORS["bg"], padx=16, pady=(10))
        search_bar.pack(fill="x")
        tk.Label(search_bar, text="Search:", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text_dim"]).pack(side="left")
        self.search_var = tk.StringVar(value=self._search)
        tk.Entry(search_bar, textvariable=self.search_var, font=FONT_BODY,
                 bg=COLORS["card"], fg=COLORS["text"], insertbackground=COLORS["text"],
                 relief="flat", width=28).pack(side="left", padx=(6, 0), ipady=4)
        self.count_label = tk.Label(search_bar, text="", font=FONT_SMALL,
                                    bg=COLORS["bg"], fg=COLORS["text_dim"])
        self.count_label.pack(side="right")

        container, self.canvas, self.cards_frame = make_scroll_area(self.window)
        container.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        self._load()
        self.search_var.trace_add("write", lambda *_: self._load())

    @staticmethod
    def _folder_signature() -> list:
        """Names and modification times of the archive files; changes when an
        archive is added, removed or replaced."""
        try:
            return sorted((f, os.path.getmtime(os.path.join(ARCHIVE_DIR, f)))
                          for f in os.listdir(ARCHIVE_DIR) if f.endswith(".zip"))
        except OSError:
            return []

    def refresh(self):
        """Called by the main window every few seconds: the list is built again
        only when the archive folder changed."""
        if self._folder_signature() != self._signature:
            self._load()

    def _load(self):
        self._signature = self._folder_signature()
        for w in self.cards_frame.winfo_children():
            w.destroy()

        archives = list_archive()
        total = len(archives)
        self._search = self.search_var.get()
        query = self._search.casefold().strip()
        if query:
            archives = [a for a in archives if query in a["title"].casefold()
                        or query in (a["description"] or "").casefold()]
        self.count_label.config(text=f"{len(archives)} of {total}" if query else f"{total}")
        onhold   = [a for a in archives if a["source"] == "onhold"]
        finished = [a for a in archives if a["source"] != "onhold"]

        if not archives:
            text = "Nothing found." if total else "Archive is empty."
            tk.Label(self.cards_frame, text=text,
                     font=FONT_BODY, bg=COLORS["bg"], fg=COLORS["text_dim"],
                     pady=40).pack()
            return

        if onhold:
            self._section_header("On Hold")
            for a in onhold:
                self._make_card(a)

        if finished:
            self._section_header("Finished")
            for a in finished:
                self._make_card(a)

    def _section_header(self, text: str):
        frm = tk.Frame(self.cards_frame, bg=COLORS["bg"])
        frm.pack(fill="x", pady=(12, 4))
        tk.Label(frm, text=text, font=font(11, "bold"),
                 bg=COLORS["bg"], fg=COLORS["accent"], padx=4).pack(side="left")
        tk.Frame(frm, bg=COLORS["border"], height=1).pack(
            side="left", fill="x", expand=True, padx=(8, 0), pady=6)

    def _make_card(self, a: dict):
        card = tk.Frame(self.cards_frame, bg=COLORS["card"], pady=8, padx=14)
        card.pack(fill="x", pady=3, padx=2)

        src_color = COLORS["text_dim"] if a["source"] == "onhold" else COLORS["status_completed"]
        tk.Frame(card, bg=src_color, width=4).pack(side="left", fill="y", padx=(0, 12))

        info = tk.Frame(card, bg=COLORS["card"])
        info.pack(side="left", fill="both", expand=True)

        row1 = tk.Frame(info, bg=COLORS["card"])
        row1.pack(fill="x")
        tk.Label(row1, text=a["title"], font=font(11, "bold"),
                 bg=COLORS["card"], fg=COLORS["text"], anchor="w").pack(side="left")
        tk.Label(row1, text=f"archived: {a['export_date']}", font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"]).pack(side="right")

        row2 = tk.Frame(info, bg=COLORS["card"])
        row2.pack(fill="x")
        tk.Label(row2,
                 text=f"Progress: {a['progress']}  |  created: {a['created_at']}",
                 font=FONT_SMALL, bg=COLORS["card"], fg=COLORS["text_dim"],
                 anchor="w").pack(side="left")

        actions = tk.Frame(card, bg=COLORS["card"])
        actions.pack(side="right", padx=(12, 0))

        make_button(actions, "▶ Restore",
                    lambda zp=a["zip_path"], fn=a["filename"], src=a["source"]:
                        self._restore(zp, fn, src),
                    small=True).pack(pady=(0, 2))
        make_button(actions, "Delete",
                    lambda zp=a["zip_path"], ttl=a["title"]: self._remove(zp, ttl),
                    kind="danger", small=True).pack()

    def _restore(self, zip_path: str, filename: str, source: str):
        source_label = "On Hold" if source == "onhold" else "Active"
        if not messagebox.askyesno(
            "Restore Task",
            f"Restore task to the {source_label} list?\n\n{filename}\n\n"
            "The ZIP file will be moved to the 'archive/removed' folder.",
            parent=self.window
        ):
            return
        try:
            new_id = import_task_from_zip(zip_path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to restore task:\n{e}",
                                 parent=self.window)
            return

        # The ZIP is never deleted, archive/removed keeps it
        note = "The ZIP file was moved to the 'archive/removed' folder."
        try:
            remove_archived_task(zip_path)
        except Exception as e:
            note = f"The ZIP file could not be moved and is still in the archive:\n{e}"

        if self.on_restore:
            self.on_restore()
        self._load()
        messagebox.showinfo("Task Restored",
                            f"Task has been restored (id={new_id}).\n\n{note}",
                            parent=self.window)

    def _remove(self, zip_path: str, title: str):
        if not messagebox.askyesno(
            "Delete from Archive",
            f"Delete task from archive?\n\n\"{title}\"\n\n"
            f"The ZIP file will be moved to the 'archive/removed' folder.\n"
            f"You can manually recover it from there.",
            parent=self.window
        ):
            return
        try:
            remove_archived_task(zip_path)
            self._load()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete task:\n{e}",
                                 parent=self.window)


# Single instance

def _acquire_instance_lock():
    """Locks the lock file in the data folder so that a second copy of the application
    can not work on the same data. Returns the held lock (keep a reference while the
    application runs) or None if another copy holds it. The system releases the lock
    by itself when the process ends, also after a crash."""
    lock = FileLock(INSTANCE_LOCK_PATH, timeout=0)
    try:
        lock.acquire()
        return lock
    except Timeout:
        return None


# Run Application

def main():
    if sys.platform == "win32":
        # Own taskbar group and icon instead of the ones of Python
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_NAME)
        except Exception:
            pass

    # className must match StartupWMClass in the Linux .desktop file;
    # make_root adds drag and drop of files when tkinterdnd2 is available
    root = make_root(APP_NAME)
    _set_app_icon(root)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    instance_lock = _acquire_instance_lock()
    if instance_lock is None:
        root.withdraw()
        messagebox.showerror(
            APP_TITLE,
            f"{APP_TITLE} is already running.\n\n"
            "Only one copy of the application can work on the same data.",
            parent=root
        )
        root.destroy()
        return

    # Data of an older version, kept next to the program files, goes to the data folder
    try:
        migrated = migrate_legacy_data(LEGACY_DATA_DIR)
    except Exception as ex:
        root.withdraw()
        messagebox.showerror(
            APP_TITLE,
            f"Data of the previous version could not be moved:\n{LEGACY_DATA_DIR}\n\n"
            f"to the data folder:\n{DATA_DIR}\n\n{ex}\n\n"
            "Nothing was deleted. The application will be closed.",
            parent=root
        )
        root.destroy()
        return
    if migrated:
        settings.reload()   # settings.json of the previous version
        load_theme()

    MainWindow(root)   # keeps itself alive through its Tk callbacks
    if migrated:
        root.after(400, lambda: messagebox.showinfo(
            "Data Moved",
            f"Your data was copied from the program folder:\n{LEGACY_DATA_DIR}\n\n"
            f"to the data folder:\n{DATA_DIR}\n\n"
            "The old files were left untouched. When everything looks right you can "
            "delete them: tasks.db*, settings.json, archive/, attachments/, backups/.",
            parent=root
        ))
    root.mainloop()


if __name__ == "__main__":
    main()
