# Settings dialog and the editor of kanban templates

import tkinter as tk
from tkinter import messagebox, ttk

import settings
from config import DATA_DIR
from database import (
    get_templates, get_template_checkpoints, template_status_flow,
    create_template, duplicate_template, rename_template, delete_template,
    set_default_template, add_template_checkpoint, update_template_checkpoint,
    delete_template_checkpoint, move_template_checkpoint,
)
from theme import THEME_NAMES, get_theme_name, set_theme
from ui_helpers import (
    COLORS, FONT_HEADING, FONT_BODY, FONT_SMALL, font, Dialog, make_button,
    make_icon_button, make_scroll_area, open_path, remember_geometry,
)

AUTO_BACKUP_CHOICES = [("Off", 0), ("Every day", 1), ("Every 7 days", 7),
                       ("Every 14 days", 14), ("Every 30 days", 30)]
CHECKPOINT_TYPES = [("check", "Checkbox"), ("counter", "Counter (+/−)")]


# Settings

class SettingsDialog:
    """on_theme_change: called after the theme was changed (windows are rebuilt).
    on_templates: opens the editor of kanban templates."""

    def __init__(self, parent, on_theme_change=None, on_templates=None):
        self.on_theme_change = on_theme_change
        self.on_templates = on_templates

        self.window = tk.Toplevel(parent)
        self.window.title("Settings")
        self.window.configure(bg=COLORS["bg"])
        self.window.resizable(False, False)
        self.window.transient(parent)

        tk.Frame(self.window, bg=COLORS["accent"], height=3).pack(fill="x")
        hdr = tk.Frame(self.window, bg=COLORS["panel"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="SETTINGS", font=font(12, "bold"),
                 bg=COLORS["panel"], fg=COLORS["accent"],
                 padx=16, pady=10).pack(side="left")
        tk.Frame(self.window, bg=COLORS["accent"], height=1).pack(fill="x")

        body = tk.Frame(self.window, bg=COLORS["bg"], padx=20, pady=12)
        body.pack(fill="both", expand=True)

        # Theme
        self._section(body, "Color theme")
        self._theme_var = tk.StringVar(value=get_theme_name())
        for key, label in THEME_NAMES.items():
            tk.Radiobutton(body, text=label, variable=self._theme_var, value=key,
                           **self._radio_style()).pack(anchor="w")

        # Data folder
        self._section(body, "Data folder")
        row = tk.Frame(body, bg=COLORS["bg"])
        row.pack(fill="x")
        path = tk.Entry(row, font=FONT_SMALL, bg=COLORS["card"], fg=COLORS["text"],
                        relief="flat", readonlybackground=COLORS["card"], width=48)
        path.insert(0, str(DATA_DIR))
        path.config(state="readonly")   # can be selected and copied, not changed
        path.pack(side="left", fill="x", expand=True, ipady=4)
        make_button(row, "Open", lambda: open_path(str(DATA_DIR), parent=self.window),
                    kind="secondary", small=True).pack(side="left", padx=(6, 0))

        # Automatic backup
        self._section(body, "Automatic backup")
        row = tk.Frame(body, bg=COLORS["bg"])
        row.pack(fill="x")
        days = settings.get("auto_backup_days")
        current = next((label for label, d in AUTO_BACKUP_CHOICES if d == days),
                       f"Every {days} days")
        self._backup_var = tk.StringVar(value=current)
        ttk.Combobox(row, textvariable=self._backup_var, state="readonly", width=16,
                     values=[label for label, _ in AUTO_BACKUP_CHOICES],
                     font=FONT_BODY).pack(side="left")
        tk.Label(row, text="   keep the last", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(side="left")
        self._keep_var = tk.IntVar(value=settings.get("auto_backup_keep"))
        self._spinbox(row, self._keep_var, 1, 100).pack(side="left", padx=6)
        tk.Label(row, text="automatic backups", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(side="left")
        self._hint(body, "Checked at start and every 10 minutes. "
                         "Backups made by hand are never removed.")

        # Idle tasks
        self._section(body, "Idle tasks")
        row = tk.Frame(body, bg=COLORS["bg"])
        row.pack(fill="x")
        tk.Label(row, text="Highlight tasks without activity for", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(side="left")
        self._idle_var = tk.IntVar(value=settings.get("idle_days"))
        self._spinbox(row, self._idle_var, 0, 365).pack(side="left", padx=6)
        tk.Label(row, text="days", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(side="left")
        self._hint(body, "0 = off")

        # Templates
        self._section(body, "Kanban templates")
        make_button(body, "Edit templates...", self._open_templates,
                    kind="secondary", small=True).pack(anchor="w")

        btn_bar = tk.Frame(self.window, bg=COLORS["bg"], padx=20, pady=12)
        btn_bar.pack(fill="x")
        make_button(btn_bar, "Cancel", self.window.destroy,
                    kind="secondary").pack(side="right", padx=(8, 0))
        make_button(btn_bar, "Apply", self._apply, bold=True).pack(side="right")

        self.window.bind("<Escape>", lambda e: self.window.destroy())

    # Builders of single fields

    @staticmethod
    def _radio_style() -> dict:
        return dict(bg=COLORS["bg"], fg=COLORS["text"], activebackground=COLORS["bg"],
                    activeforeground=COLORS["text"], selectcolor=COLORS["card"], font=FONT_BODY)

    @staticmethod
    def _section(parent, text: str):
        tk.Label(parent, text=text, font=FONT_HEADING, bg=COLORS["bg"],
                 fg=COLORS["accent"]).pack(anchor="w", pady=(10, 4))

    @staticmethod
    def _hint(parent, text: str):
        tk.Label(parent, text=text, font=FONT_SMALL, bg=COLORS["bg"],
                 fg=COLORS["text_dim"]).pack(anchor="w", pady=(2, 0))

    @staticmethod
    def _spinbox(parent, var, low: int, high: int) -> tk.Spinbox:
        return tk.Spinbox(parent, from_=low, to=high, textvariable=var, width=5,
                          font=FONT_BODY, bg=COLORS["card"], fg=COLORS["text"],
                          buttonbackground=COLORS["btn_secondary"],
                          insertbackground=COLORS["text"], relief="flat")

    @staticmethod
    def _int_value(var, low: int, high: int, fallback: int) -> int:
        try:
            return min(max(int(var.get()), low), high)
        except (tk.TclError, ValueError):
            return fallback

    def _open_templates(self):
        if self.on_templates:
            self.on_templates()

    def _apply(self):
        days = next((d for label, d in AUTO_BACKUP_CHOICES if label == self._backup_var.get()),
                    settings.get("auto_backup_days"))
        settings.update(
            auto_backup_days=days,
            auto_backup_keep=self._int_value(self._keep_var, 1, 100,
                                             settings.get("auto_backup_keep")),
            idle_days=self._int_value(self._idle_var, 0, 365, settings.get("idle_days")),
        )
        chosen = self._theme_var.get()
        self.window.destroy()
        if chosen != get_theme_name():
            set_theme(chosen)
            if self.on_theme_change:
                self.on_theme_change()


# Kanban templates

class TemplatesWindow:
    """Editor of kanban templates: list of templates on the left, checkpoints of the
    selected one on the right. Changes are saved at once and affect only tasks
    created afterwards."""

    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("Kanban Templates")
        self.window.configure(bg=COLORS["bg"])
        self.window.minsize(720, 420)
        remember_geometry(self.window, "templates", "860x540")
        self._selected_id = None
        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self.window, bg=COLORS["panel"])
        header.pack(fill="x")
        tk.Label(header, text="KANBAN TEMPLATES", font=font(20, "bold"),
                 bg=COLORS["panel"], fg=COLORS["accent"], padx=20, pady=14).pack(side="left")
        tk.Frame(self.window, bg=COLORS["accent"], height=2).pack(fill="x")

        tk.Label(self.window,
                 text="Changes apply to tasks created from now on; existing tasks keep "
                      "their checkpoints and statuses.",
                 font=FONT_SMALL, bg=COLORS["bg"], fg=COLORS["text_dim"],
                 padx=16, pady=6).pack(anchor="w")

        main = tk.Frame(self.window, bg=COLORS["bg"])
        main.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        # Left: templates
        left = tk.Frame(main, bg=COLORS["bg"])
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        self.listbox = tk.Listbox(
            left, font=FONT_BODY, width=24, activestyle="none", exportselection=False,
            bg=COLORS["card"], fg=COLORS["text"], selectbackground=COLORS["accent"],
            selectforeground="white", relief="flat", highlightthickness=0)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._on_select())

        buttons = tk.Frame(left, bg=COLORS["bg"])
        buttons.pack(fill="x", pady=(8, 0))
        for text, command, kind in [("New", self._new, "primary"),
                                    ("Rename", self._rename, "secondary"),
                                    ("Duplicate", self._duplicate, "secondary"),
                                    ("Set as default", self._set_default, "secondary"),
                                    ("Delete", self._delete, "danger")]:
            make_button(buttons, text, command, kind=kind, small=True).pack(fill="x", pady=2)

        # Right: checkpoints of the selected template
        right = tk.Frame(main, bg=COLORS["bg"])
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        self.flow_label = tk.Label(right, text="", font=FONT_SMALL, bg=COLORS["panel"],
                                   fg=COLORS["text_dim"], anchor="w", justify="left",
                                   padx=10, pady=6, wraplength=520)
        self.flow_label.grid(row=0, column=0, sticky="ew")

        container, _, self.cp_inner = make_scroll_area(right)
        container.grid(row=1, column=0, sticky="nsew", pady=(4, 0))

        self._load_templates()

    # List of templates

    def _load_templates(self, select_id: int = None):
        self._templates = get_templates()
        self.listbox.delete(0, "end")
        for t in self._templates:
            mark = "  (default)" if t["is_default"] else ""
            self.listbox.insert("end", f"{t['name']}{mark}")
        ids = [t["id"] for t in self._templates]
        if select_id not in ids:
            select_id = self._selected_id if self._selected_id in ids else ids[0]
        index = ids.index(select_id)
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(index)
        self.listbox.see(index)
        self._selected_id = select_id
        self._load_checkpoints()

    def _on_select(self):
        sel = self.listbox.curselection()
        if sel:
            self._selected_id = self._templates[sel[0]]["id"]
            self._load_checkpoints()

    def _selected(self) -> dict:
        return next(t for t in self._templates if t["id"] == self._selected_id)

    def _ask_name(self, title: str, value: str = ""):
        dialog = NameDialog(self.window, title, value)
        self.window.wait_window(dialog.window)
        return dialog.result

    def _new(self):
        name = self._ask_name("New Template")
        if name:
            self._load_templates(create_template(name))

    def _rename(self):
        name = self._ask_name("Rename Template", self._selected()["name"])
        if name:
            rename_template(self._selected_id, name)
            self._load_templates()

    def _duplicate(self):
        name = self._ask_name("Duplicate Template", f"{self._selected()['name']} (copy)")
        if name:
            self._load_templates(duplicate_template(self._selected_id, name))

    def _set_default(self):
        set_default_template(self._selected_id)
        self._load_templates()

    def _delete(self):
        if len(self._templates) <= 1:
            messagebox.showinfo("Delete Template", "The last template can not be deleted.",
                                parent=self.window)
            return
        if messagebox.askyesno("Delete Template",
                               f"Delete the template \"{self._selected()['name']}\"?\n\n"
                               "Tasks created from it are not changed.",
                               parent=self.window):
            delete_template(self._selected_id)
            self._selected_id = None
            self._load_templates()

    # Checkpoints of the selected template

    def _load_checkpoints(self):
        for w in self.cp_inner.winfo_children():
            w.destroy()
        checkpoints = get_template_checkpoints(self._selected_id)
        self.flow_label.config(
            text="Statuses:  " + "  →  ".join(template_status_flow(self._selected_id)))

        for c in checkpoints:
            row = tk.Frame(self.cp_inner, bg=COLORS["card"], padx=10, pady=5)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=f"{c['position']:2}.", font=FONT_SMALL, bg=COLORS["card"],
                     fg=COLORS["text_dim"]).pack(side="left")
            kind = "counter" if c["checkpoint_type"] == "counter" else "checkbox"
            tk.Label(row, text=f"{c['name']}", font=FONT_BODY, bg=COLORS["card"],
                     fg=COLORS["text"]).pack(side="left", padx=(6, 0))
            tk.Label(row, text=f"  {kind}", font=FONT_SMALL, bg=COLORS["card"],
                     fg=COLORS["text_dim"]).pack(side="left")

            ctrl = tk.Frame(row, bg=COLORS["card"])
            ctrl.pack(side="right")
            make_icon_button(ctrl, "✏", lambda cp=c: self._edit_checkpoint(cp),
                             bg=COLORS["card"]).pack(side="right")
            for symbol, direction in (("▼", "down"), ("▲", "up")):
                make_icon_button(ctrl, symbol,
                                 lambda cid=c["id"], d=direction: self._move(cid, d),
                                 bg=COLORS["card"], font=font(7), padx=2).pack(side="right")
            if c["status_group"]:
                tk.Label(row, text=f"→ {c['status_group']}", font=FONT_SMALL,
                         bg=COLORS["card"], fg=COLORS["accent2"]).pack(side="right", padx=8)

        add = tk.Frame(self.cp_inner, bg=COLORS["bg"], pady=4)
        add.pack(fill="x", pady=(6, 0))
        make_button(add, "+ Add Checkpoint", self._add_checkpoint,
                    kind="secondary", small=True).pack(side="left")

    def _statuses(self) -> list[str]:
        return template_status_flow(self._selected_id)[1:-1]

    def _add_checkpoint(self):
        dialog = TemplateCheckpointDialog(self.window, self._statuses())
        self.window.wait_window(dialog.window)
        if dialog.result:
            add_template_checkpoint(self._selected_id, **dialog.result)
            self._load_templates()

    def _edit_checkpoint(self, checkpoint: dict):
        count = len(get_template_checkpoints(self._selected_id))
        dialog = TemplateCheckpointDialog(self.window, self._statuses(), checkpoint,
                                          can_delete=count > 1)
        self.window.wait_window(dialog.window)
        if dialog.result == "deleted":
            delete_template_checkpoint(checkpoint["id"])
        elif dialog.result:
            update_template_checkpoint(checkpoint["id"], **dialog.result)
        self._load_templates()

    def _move(self, checkpoint_id: int, direction: str):
        move_template_checkpoint(checkpoint_id, direction)
        self._load_checkpoints()


class NameDialog(Dialog):
    def __init__(self, parent, title: str, value: str = ""):
        super().__init__(parent, title, width=380)
        self.add_label("Name")
        self.name_var = self.add_entry(value, focus=True)
        self.add_buttons("Save", self._confirm)

    def _confirm(self):
        name = self.name_var.get().strip()
        if name:
            self.result = name
            self.window.destroy()


class TemplateCheckpointDialog(Dialog):
    """Checkpoint of a template: name, type and the status it leads to.
    result: None = cancelled, "deleted", or {name, checkpoint_type, status_group}."""

    NO_STATUS = "(no status)"

    def __init__(self, parent, statuses: list, checkpoint: dict = None, can_delete: bool = True):
        self.checkpoint = checkpoint
        super().__init__(parent, "Edit Template Checkpoint" if checkpoint
                         else "Add Template Checkpoint", width=440)

        self.add_label("Checkpoint Name")
        self.name_var = self.add_entry(checkpoint["name"] if checkpoint else "", focus=True)

        self.add_label("Checkpoint Type")
        self.type_var = self.add_radios(
            CHECKPOINT_TYPES, checkpoint["checkpoint_type"] if checkpoint else "check")

        self.add_label("Status reached")
        current = (checkpoint or {}).get("status_group") or self.NO_STATUS
        self.status_var = tk.StringVar(value=current)
        ttk.Combobox(self.form, textvariable=self.status_var, font=FONT_BODY,
                     values=[self.NO_STATUS] + statuses).pack(fill="x", ipady=3, pady=(2, 4))
        self.add_hint("Pick a status or type a new one. A task reaches a status when all\n"
                      "checkpoints with it (and with every earlier status) are completed.")

        btn_row = self.add_buttons("Save" if checkpoint else "Add", self._confirm)
        if checkpoint:
            make_button(btn_row, "Delete", self._delete, kind="danger",
                        enabled=can_delete).pack(side="left")

    def _confirm(self):
        name = self.name_var.get().strip()
        if not name:
            return
        status = self.status_var.get().strip()
        self.result = {
            "name": name,
            "checkpoint_type": self.type_var.get(),
            "status_group": None if status in ("", self.NO_STATUS) else status,
        }
        self.window.destroy()

    def _delete(self):
        if messagebox.askyesno("Delete Checkpoint",
                               f"Delete \"{self.checkpoint['name']}\" from the template?",
                               parent=self.window):
            self.result = "deleted"
            self.window.destroy()

