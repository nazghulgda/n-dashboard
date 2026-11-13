# Window of a single task, the note editor and their dialogs

import tkinter as tk
from tkinter import messagebox, filedialog
import os
import re
import shutil

from database import (
    get_task, get_checkpoints, set_checkpoint_completed, set_iteration_count,
    get_task_checkpoint_status,
    get_notes, create_note, update_note,
    get_links, create_link, update_link, delete_link,
    update_task,
    add_checkpoint, delete_checkpoint, update_checkpoint, move_checkpoint,
    get_attachments, create_attachment, soft_delete_attachment, restore_attachment,
    get_attachment_dir, resolve_attachment_path, unique_path, duplicate_task,
    checkpoint_progress,
)
from ui_helpers import (
    COLORS, FONT_HEADING, FONT_BODY, FONT_SMALL, font, mono_font,
    Dialog, make_button, make_icon_button, bind_hover, make_tooltip,
    make_scroll_area, widget_alive, open_path, grab_when_visible,
    remember_geometry, parse_due_date, due_text, due_color, DUE_DATE_HINT,
    enable_file_drop, drop_available,
)

FONT_TITLE = font(16, "bold")

HIGHLIGHT_COLORS = [
    ("#FFD700", "Yellow"),
    ("#FF6B6B", "Red"),
    ("#90EE90", "Green"),
    ("#87CEEB", "Blue"),
    ("#DDA0DD", "Purple"),
    ("#FFA500", "Orange"),
]

CHECKPOINT_TYPES = [("check", "Checkbox"), ("counter", "Counter (+/−)")]

# Main task window

class TaskWindow:
    def __init__(self, parent, task_id: int, on_close=None, open_task=None):
        self.task_id  = task_id
        self.on_close = on_close
        self.open_task = open_task   # function(task_id) opening another task (duplicate)
        self.task     = get_task(task_id)
        if not self.task:
            messagebox.showerror("Error", f"Task #{task_id} does not exist.", parent=parent)
            return

        self.window = tk.Toplevel(parent)
        self.window.title(self.task["title"])
        self.window.configure(bg=COLORS["bg"])
        self.window.minsize(800, 500)
        remember_geometry(self.window, "task", "1100x700", size_only=True)

        self.window.protocol("WM_DELETE_WINDOW", self.close)

        self._open_note_windows = {}
        self._checkpoints_canvas = None  # reference to kanban canvas
        self._build_ui()
        self._load_all()

    # Building layout

    def _build_ui(self):
        header = tk.Frame(self.window, bg=COLORS["panel"])
        header.pack(fill="x")

        self.title_label = tk.Label(
            header, text=self.task["title"],
            font=FONT_TITLE, bg=COLORS["panel"],
            fg=COLORS["accent"], padx=20, pady=12
        )
        self.title_label.pack(side="left")

        self.desc_label = tk.Label(
            header,
            text=self.task.get("description") or "",
            font=FONT_BODY, bg=COLORS["panel"],
            fg=COLORS["text_dim"], padx=4, pady=12
        )
        if self.task.get("description"):
            self.desc_label.pack(side="left")

        self.edit_btn = make_icon_button(header, "✏", self._edit_task_info,
                                         bg=COLORS["panel"], font=FONT_BODY, padx=10)
        self.edit_btn.pack(side="left", padx=(4, 0))

        make_button(header, "Duplicate", self._duplicate, kind="secondary",
                    small=True).pack(side="right", padx=12)
        self.due_label = tk.Label(header, text="", font=font(9, "bold"),
                                  bg=COLORS["panel"], fg=COLORS["text_dim"], padx=8)
        self.due_label.pack(side="right")

        tk.Frame(self.window, bg=COLORS["accent"], height=2).pack(fill="x")

        main = tk.Frame(self.window, bg=COLORS["bg"])
        main.pack(fill="both", expand=True)
        main.rowconfigure(0, weight=1)
        main.rowconfigure(1, weight=0)
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)

        self.kanban_frame = tk.Frame(main, bg=COLORS["bg"])
        self.kanban_frame.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        self._build_kanban_panel(self.kanban_frame)

        self.notes_frame = tk.Frame(main, bg=COLORS["bg"])
        self.notes_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)
        self._build_notes_panel(self.notes_frame)

        bottom = tk.Frame(main, bg=COLORS["bg"])
        bottom.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))
        bottom.columnconfigure(0, weight=3)
        bottom.columnconfigure(1, weight=2)

        self.links_frame = tk.Frame(bottom, bg=COLORS["bg"])
        self.links_frame.grid(row=0, column=0, sticky="new", padx=(0, 6))
        self._build_links_panel(self.links_frame)

        self.attachments_frame = tk.Frame(bottom, bg=COLORS["bg"])
        self.attachments_frame.grid(row=0, column=1, sticky="new", padx=(6, 0))
        self._build_attachments_panel(self.attachments_frame)

    # Panel: Kanban

    def _build_kanban_panel(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        hdr = tk.Frame(parent, bg=COLORS["panel"])
        hdr.grid(row=0, column=0, sticky="ew")
        tk.Label(hdr, text="CHECKPOINTS", font=FONT_HEADING,
                 bg=COLORS["panel"], fg=COLORS["accent"],
                 padx=12, pady=8).pack(side="left")
        self.progress_label = tk.Label(
            hdr, text="", font=FONT_SMALL,
            bg=COLORS["panel"], fg=COLORS["text_dim"], padx=12
        )
        self.progress_label.pack(side="right")

        container, canvas, self.checkpoints_inner = make_scroll_area(parent)
        container.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self._checkpoints_canvas = canvas

    def _load_kanban(self):
        for w in self.checkpoints_inner.winfo_children():
            w.destroy()

        checkpoints = get_checkpoints(self.task_id)
        checkpoints_count = len(checkpoints)
        status = get_task_checkpoint_status(self.task_id)
        self.progress_label.config(text=status)
        done, total = checkpoint_progress(checkpoints)
        self._finished = total > 0 and done == total
        self._update_due_label()

        self._checkpoint_vars = {}

        if not checkpoints:
            tk.Label(
                self.checkpoints_inner,
                text="Kanban is empty.\nAdd first checkpoint below.",
                font=FONT_SMALL, bg=COLORS["bg"], fg=COLORS["text_dim"],
                pady=16, justify="center"
            ).pack()
        else:
            for checkpoint in checkpoints:
                is_done = bool(checkpoint["completed"])
                bg = COLORS["checkpoint_done"] if is_done else COLORS["checkpoint_undone"]
                row = tk.Frame(self.checkpoints_inner, bg=bg, pady=6, padx=10)
                row.pack(fill="x", pady=2)

                if checkpoint.get("checkpoint_type", "check") == "counter":
                    self._make_counter_row(row, checkpoint, checkpoints_count)
                else:
                    self._make_check_row(row, checkpoint, checkpoints_count)

        add_frame = tk.Frame(self.checkpoints_inner, bg=COLORS["bg"], pady=4)
        add_frame.pack(fill="x", pady=(6, 0))
        make_button(add_frame, "+ Add Checkpoint", self._add_checkpoint,
                    kind="secondary", small=True).pack(side="left", padx=10)

    def _make_check_row(self, row: tk.Frame, checkpoint: dict, checkpoints_count: int):
        is_done = bool(checkpoint["completed"])
        bg = COLORS["checkpoint_done"] if is_done else COLORS["checkpoint_undone"]

        var = tk.BooleanVar(value=is_done)
        self._checkpoint_vars[checkpoint["id"]] = var

        cb = tk.Checkbutton(
            row, variable=var,
            bg=bg, activebackground=COLORS["card_hover"],
            selectcolor=COLORS["check_on"], fg=COLORS["text"],
            command=lambda sid=checkpoint["id"], v=var: self._toggle_checkpoint(sid, v)
        )
        cb.pack(side="left")

        tk.Label(
            row, text=checkpoint["name"], font=FONT_BODY, bg=bg,
            fg=COLORS["text"] if is_done else COLORS["text_dim"]
        ).pack(side="left", padx=(4, 0))

        self._pack_checkpoint_controls(row, checkpoint, checkpoints_count, bg)

    def _make_counter_row(self, row: tk.Frame, checkpoint: dict, checkpoints_count: int):
        count = checkpoint.get("iteration_count", 0)
        is_done = count > 0
        bg = COLORS["checkpoint_done"] if is_done else COLORS["checkpoint_undone"]

        minus = tk.Label(
            row, text=" − ", font=FONT_BODY,
            bg=COLORS["btn_secondary"], fg=COLORS["text"],
            cursor="hand2", relief="flat", padx=4
        )
        minus.pack(side="left")

        count_lbl = tk.Label(
            row, text=f"× {count}", font=mono_font(10, "bold"),
            bg=bg, fg=COLORS["accent2"] if is_done else COLORS["text_dim"],
            width=5, anchor="center"
        )
        count_lbl.pack(side="left", padx=2)

        plus = tk.Label(
            row, text=" + ", font=FONT_BODY,
            bg=COLORS["btn"], fg="white",
            cursor="hand2", relief="flat", padx=4
        )
        plus.pack(side="left")

        tk.Label(
            row, text=f"  {checkpoint['name']}  (optional, repeatable)",
            font=FONT_BODY, bg=bg,
            fg=COLORS["text"] if is_done else COLORS["text_dim"]
        ).pack(side="left", padx=(6, 0))

        self._pack_checkpoint_controls(row, checkpoint, checkpoints_count, bg)

        def change(delta, sid=checkpoint["id"]):
            current_checkpoints = get_checkpoints(self.task_id)
            current = next((s["iteration_count"] for s in current_checkpoints if s["id"] == sid), 0)
            set_iteration_count(sid, max(0, current + delta))
            self._reload_kanban_keep_scroll()

        minus.bind("<Button-1>", lambda e: change(-1))
        plus.bind("<Button-1>",  lambda e: change(+1))
        minus.bind("<Enter>", lambda e: minus.config(bg=COLORS["card_hover"]))
        minus.bind("<Leave>", lambda e: minus.config(bg=COLORS["btn_secondary"]))
        plus.bind("<Enter>",  lambda e: plus.config(bg=COLORS["btn_hover"]))
        plus.bind("<Leave>",  lambda e: plus.config(bg=COLORS["btn"]))

    def _pack_checkpoint_controls(self, row: tk.Frame, checkpoint: dict, checkpoints_count: int, bg: str):
        """Adds control buttons (up/down/edit) to the right side of the checkpoint row."""
        order = checkpoint["checkpoint_order"]

        ctrl = tk.Frame(row, bg=bg)
        ctrl.pack(side="right")

        # When it was completed (a counter: when it was used the last time)
        if checkpoint.get("completed_at") and checkpoint["completed"]:
            prefix = "last " if checkpoint.get("checkpoint_type") == "counter" else ""
            tk.Label(row, text=prefix + checkpoint["completed_at"][:10], font=FONT_SMALL,
                     bg=bg, fg=COLORS["text_dim"]).pack(side="right", padx=(0, 8))

        make_icon_button(
            ctrl, "✏",
            lambda s=dict(checkpoint): self._edit_checkpoint(s, checkpoints_count),
            bg=bg
        ).pack(side="right")

        # Arrows: an arrow which can not be used is invisible (text in background color)
        arrow_font = font(7)
        for symbol, direction, enabled in (("▼", "down", order < checkpoints_count),
                                           ("▲", "up",   order > 1)):
            if enabled:
                make_icon_button(
                    ctrl, symbol,
                    lambda sid=checkpoint["id"], d=direction: self._move_checkpoint(sid, d),
                    bg=bg, font=arrow_font, padx=2
                ).pack(side="right")
            else:
                tk.Label(ctrl, text=symbol, font=arrow_font, bg=bg, fg=bg,
                         padx=2).pack(side="right")

    # Kanban actions

    def _reload_kanban_keep_scroll(self):
        """Reloads the kanban board while keeping the scroll position."""
        yview = self._checkpoints_canvas.yview() if self._checkpoints_canvas else (0.0, 1.0)
        self._load_kanban()
        if self._checkpoints_canvas and yview[0] > 0:
            self._checkpoints_canvas.after(10,
                lambda y=yview[0]: self._checkpoints_canvas.yview_moveto(y))

    def _toggle_checkpoint(self, checkpoint_id: int, var: tk.BooleanVar):
        set_checkpoint_completed(checkpoint_id, var.get())
        self._reload_kanban_keep_scroll()

    def _move_checkpoint(self, checkpoint_id: int, direction: str):
        move_checkpoint(self.task_id, checkpoint_id, direction)
        self._reload_kanban_keep_scroll()

    def _edit_checkpoint(self, checkpoint: dict, checkpoints_count: int):
        dialog = CheckpointDialog(self.window, checkpoint, can_delete=checkpoints_count > 1)
        self.window.wait_window(dialog.window)
        if dialog.result == "deleted":
            delete_checkpoint(checkpoint["id"])
            self._reload_kanban_keep_scroll()
        elif dialog.result:
            update_checkpoint(checkpoint["id"], dialog.result["name"], dialog.result["checkpoint_type"])
            self._reload_kanban_keep_scroll()

    def _add_checkpoint(self):
        dialog = CheckpointDialog(self.window)
        self.window.wait_window(dialog.window)
        if dialog.result:
            add_checkpoint(self.task_id, dialog.result["name"], dialog.result["checkpoint_type"])
            self._load_kanban()
            # Scroll down to show the new checkpoint
            if self._checkpoints_canvas:
                self._checkpoints_canvas.after(50,
                    lambda: self._checkpoints_canvas.yview_moveto(1.0))

    # Panel: Notes

    def _build_notes_panel(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        hdr = tk.Frame(parent, bg=COLORS["panel"])
        hdr.grid(row=0, column=0, sticky="ew")
        tk.Label(hdr, text="NOTES", font=FONT_HEADING,
                 bg=COLORS["panel"], fg=COLORS["accent"],
                 padx=12, pady=8).pack(side="left")
        make_button(hdr, "+ New", self._new_note, small=True).pack(side="right", padx=8, pady=6)

        container, _, self.notes_inner = make_scroll_area(parent)
        container.grid(row=1, column=0, sticky="nsew", pady=(4, 0))

    def _load_notes(self):
        for w in self.notes_inner.winfo_children():
            w.destroy()

        notes = get_notes(self.task_id)

        if not notes:
            tk.Label(
                self.notes_inner, text="No existing notes.",
                font=FONT_SMALL, bg=COLORS["bg"], fg=COLORS["text_dim"],
                pady=12
            ).pack()
            return

        for note in notes:
            self._make_note_row(note)

    def _make_note_row(self, note: dict):
        row = tk.Frame(self.notes_inner, bg=COLORS["card"], pady=6, padx=10, cursor="hand2")
        row.pack(fill="x", pady=2)

        # Line 1: title (left) + edit icon + date (right)
        header_row = tk.Frame(row, bg=COLORS["card"])
        header_row.pack(fill="x")

        title_lbl = tk.Label(header_row, text=note["title"], font=FONT_BODY,
                             bg=COLORS["card"], fg=COLORS["text"], anchor="w")
        title_lbl.pack(side="left", fill="x", expand=True)

        edit_title_btn = make_icon_button(
            header_row, "✏",
            lambda n=note, lbl=title_lbl: self._edit_note_title(n, lbl),
            bg=COLORS["card"]
        )
        edit_title_btn.pack(side="right")

        # Date: updated if different from created, otherwise created
        if note.get("updated_at") and note["updated_at"] != note["created_at"]:
            dt_str = "updated: " + note["updated_at"][:16].replace("T", " ")
        else:
            dt_str = note["created_at"][:16].replace("T", " ")
        date_lbl = tk.Label(header_row, text=dt_str, font=FONT_SMALL,
                            bg=COLORS["card"], fg=COLORS["text_dim"])
        date_lbl.pack(side="right", padx=(0, 4))

        # Lines 2-3: note content preview
        preview_lbl = None
        preview = _note_preview(note.get("content") or "")
        if preview:
            preview_lbl = tk.Label(row, text=preview, font=FONT_SMALL,
                                   bg=COLORS["card"], fg=COLORS["text_dim"],
                                   anchor="w", justify="left")
            preview_lbl.pack(fill="x", pady=(2, 0))

        def open_note(e, n=note):
            nid = n["id"]
            editor = self._open_note_windows.get(nid)
            if editor is not None and widget_alive(editor):
                editor.window.lift()
                return

            def on_note_close(note_id=nid):
                self._open_note_windows.pop(note_id, None)
                self._load_notes()

            self._open_note_windows[nid] = NoteEditorWindow(
                self.window, n, on_save=self._load_notes, on_close=on_note_close)

        # Click anywhere on the row except the edit icon opens the note
        for w in (row, header_row, title_lbl, date_lbl, preview_lbl):
            if w is not None:
                w.bind("<Button-1>", open_note)

        bind_hover(row, COLORS["card"], COLORS["card_hover"])

    def _new_note(self):
        dialog = NoteTitleDialog(self.window, "New Note", ok_text="Create")
        self.window.wait_window(dialog.window)
        if dialog.result:
            create_note(self.task_id, dialog.result)
            self._load_notes()

    def _edit_note_title(self, note: dict, title_lbl: tk.Label):
        dialog = NoteTitleDialog(self.window, "Edit Note Title", note["title"])
        self.window.wait_window(dialog.window)
        if dialog.result:
            new_title = dialog.result
            update_note(note["id"], new_title, note.get("content") or "")
            note["title"] = new_title
            title_lbl.config(text=new_title)
            # Note opened in the editor shows the new title as well
            editor = self._open_note_windows.get(note["id"])
            if editor is not None and widget_alive(editor):
                editor.set_title(new_title)

    # Panel: Links

    def _build_links_panel(self, parent):
        parent.columnconfigure(0, weight=1)

        tk.Frame(parent, bg=COLORS["border"], height=1).pack(fill="x", pady=(0, 6))

        hdr = tk.Frame(parent, bg=COLORS["panel"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="LINKS", font=FONT_HEADING,
                 bg=COLORS["panel"], fg=COLORS["accent"],
                 padx=12, pady=6).pack(side="left")

        for label, ltype in [("+ File", "file"), ("+ Folder", "folder")]:
            make_button(hdr, label, lambda t=ltype: self._add_link(t),
                        small=True).pack(side="right", padx=(4, 8), pady=4)

        self.links_container = tk.Frame(parent, bg=COLORS["bg"])
        self.links_container.pack(fill="x", pady=(4, 0))

    def _load_links(self):
        for w in self.links_container.winfo_children():
            w.destroy()

        links = get_links(self.task_id)

        if not links:
            text = ("No links. Add a file or folder, or drop it here." if drop_available()
                    else "No links available. Add a file or folder.")
            tk.Label(
                self.links_container, text=text,
                font=FONT_SMALL, bg=COLORS["bg"], fg=COLORS["text_dim"],
                pady=6
            ).pack(side="left")
        else:
            for link in links:
                self._make_link_chip(link)
        enable_file_drop(self.links_frame, self._drop_links)

    def _drop_links(self, paths: list):
        """Files and folders dropped on the links panel become links."""
        for path in paths:
            path = os.path.normpath(path)
            link_type = "folder" if os.path.isdir(path) else "file"
            create_link(self.task_id, os.path.basename(path) or path, path, link_type)
        self._load_links()

    def _make_chip(self, container, text: str, tooltip: str, on_open, buttons: list):
        """Chip of a link or an attachment: click opens it, buttons = [(icon, command, font)]."""
        chip = tk.Frame(container, bg=COLORS["card"], padx=8, pady=4, cursor="hand2")
        chip.pack(side="left", padx=4, pady=4)

        label_lbl = tk.Label(chip, text=text, font=FONT_SMALL,
                             bg=COLORS["card"], fg=COLORS["text"])
        label_lbl.pack(side="left")

        for icon, command, icon_font in buttons:
            make_icon_button(chip, icon, command, bg=COLORS["card"],
                             font=icon_font, padx=3).pack(side="left")

        make_tooltip(chip, tooltip)
        for child in chip.winfo_children():
            make_tooltip(child, tooltip)

        # Click on chip (outside buttons) opens the path
        for w in (chip, label_lbl):
            w.bind("<Button-1>", lambda e: on_open())

        bind_hover(chip, COLORS["card"], COLORS["card_hover"])

    def _make_link_chip(self, link: dict):
        # A folder is marked with a trailing slash, like in a file listing
        text = f"{link['label']}/" if link["link_type"] == "folder" else link["label"]
        self._make_chip(
            self.links_container, text, link["path"],
            on_open=lambda p=link["path"]: open_path(p, parent=self.window),
            buttons=[
                ("✏", lambda l=dict(link): self._edit_link(l), FONT_SMALL),
                ("×", lambda l=dict(link): self._delete_link(l), FONT_BODY),
            ]
        )

    def _edit_link(self, link: dict):
        dialog = LinkEditDialog(self.window, link)
        self.window.wait_window(dialog.window)
        if dialog.result:
            update_link(link["id"], dialog.result["label"],
                        dialog.result["path"], link["link_type"])
            self._load_links()

    def _add_link(self, link_type: str):
        if link_type == "folder":
            path = filedialog.askdirectory(title="Select Folder", parent=self.window)
        else:
            path = filedialog.askopenfilename(title="Select File", parent=self.window)

        if not path:
            return

        path = os.path.normpath(path)
        label = os.path.basename(path) or path

        create_link(self.task_id, label, path, link_type)
        self._load_links()

    def _delete_link(self, link: dict):
        if not messagebox.askyesno(
            "Delete Link",
            f"Delete link?\n\n{link['label']}\n{link['path']}",
            parent=self.window
        ):
            return
        delete_link(link["id"])
        self._load_links()

    # Panel: Attachments

    def _build_attachments_panel(self, parent):
        parent.columnconfigure(0, weight=1)

        tk.Frame(parent, bg=COLORS["border"], height=1).pack(fill="x", pady=(0, 6))

        hdr = tk.Frame(parent, bg=COLORS["panel"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="ATTACHMENTS", font=FONT_HEADING,
                 bg=COLORS["panel"], fg=COLORS["accent"],
                 padx=12, pady=6).pack(side="left")
        make_button(hdr, "+ Add file", self._add_attachment,
                    small=True).pack(side="right", padx=(4, 8), pady=4)
        self.deleted_btn = make_button(hdr, "", self._show_deleted_attachments,
                                       kind="secondary", small=True)

        self.attachments_container = tk.Frame(parent, bg=COLORS["bg"])
        self.attachments_container.pack(fill="x", pady=(4, 0))

    def _load_attachments(self):
        for w in self.attachments_container.winfo_children():
            w.destroy()

        all_attachments = get_attachments(self.task_id, include_deleted=True)
        attachments = [a for a in all_attachments if not a["deleted"]]
        deleted_count = len(all_attachments) - len(attachments)

        # "Deleted (N)" only when there is something to restore
        if deleted_count:
            self.deleted_btn.config(text=f"Deleted ({deleted_count})")
            self.deleted_btn.pack(side="right", padx=(4, 0), pady=4)
        else:
            self.deleted_btn.pack_forget()

        if not attachments:
            text = ("No attachments. Add files or drop them here." if drop_available()
                    else "No attachments.")
            tk.Label(
                self.attachments_container, text=text,
                font=FONT_SMALL, bg=COLORS["bg"], fg=COLORS["text_dim"],
                pady=6
            ).pack(side="left")
        else:
            for att in attachments:
                self._make_attachment_chip(att)
        enable_file_drop(self.attachments_frame, self._attach_files)

    def _make_attachment_chip(self, att: dict):
        path = resolve_attachment_path(att["stored_path"])
        self._make_chip(
            self.attachments_container, att['filename'], path,
            on_open=lambda p=path: open_path(p, parent=self.window),
            buttons=[("×", lambda a=dict(att): self._delete_attachment(a), FONT_BODY)]
        )

    def _attachments_dir(self) -> str:
        """Returns attachments folder of this task. A folder which the task already
        uses is kept, also when the task title was changed in the meantime."""
        for att in get_attachments(self.task_id, include_deleted=True):
            folder = os.path.dirname(resolve_attachment_path(att["stored_path"]))
            if os.path.basename(folder) == "deleted":
                folder = os.path.dirname(folder)
            return folder
        return get_attachment_dir(self.task_id, self.task["title"])

    def _add_attachment(self):
        paths = filedialog.askopenfilenames(title="Select Files to Attach", parent=self.window)
        if paths:
            self._attach_files(paths)

    def _attach_files(self, paths):
        """Copies files into the attachments folder of the task (dialog or drag and drop)."""
        folders = [p for p in paths if os.path.isdir(p)]
        paths = [p for p in paths if not os.path.isdir(p)]
        if folders:
            messagebox.showinfo(
                "Attachments",
                "Folders can't be attached. Add them as links instead:\n\n"
                + "\n".join(folders),
                parent=self.window
            )
        if not paths:
            return

        task_dir = self._attachments_dir()
        os.makedirs(task_dir, exist_ok=True)

        for src_path in paths:
            dest_path = unique_path(os.path.join(task_dir, os.path.basename(src_path)))
            try:
                shutil.copy2(src_path, dest_path)
                create_attachment(self.task_id, os.path.basename(dest_path), dest_path)
            except Exception as ex:
                messagebox.showerror(
                    "Error",
                    f"Failed to attach the file:\n{src_path}\n\n{ex}",
                    parent=self.window
                )

        self._load_attachments()

    def _delete_attachment(self, att: dict):
        if not messagebox.askyesno(
            "Delete Attachment",
            f"Delete attachment?\n\n{att['filename']}\n\n"
            "The file will be moved to the 'deleted' folder; "
            "you can restore it later with the 'Deleted' button.",
            parent=self.window
        ):
            return

        src = resolve_attachment_path(att["stored_path"])
        deleted_dir = os.path.join(os.path.dirname(src), "deleted")

        try:
            os.makedirs(deleted_dir, exist_ok=True)
            dest = unique_path(os.path.join(deleted_dir, os.path.basename(src)))
            if os.path.exists(src):
                os.replace(src, dest)
            soft_delete_attachment(att["id"], dest)
        except Exception as ex:
            messagebox.showerror(
                "Error",
                f"Failed to delete attachment:\n{ex}",
                parent=self.window
            )
            return

        self._load_attachments()

    def _show_deleted_attachments(self):
        dialog = DeletedAttachmentsDialog(self.window, self.task_id)
        self.window.wait_window(dialog.window)
        if dialog.changed:
            self._load_attachments()

    # Due date, duplicate

    def _update_due_label(self):
        due = self.task.get("due_date")
        finished = getattr(self, "_finished", False)
        self.due_label.config(text=due_text(due, finished), fg=due_color(due, finished))

    def _duplicate(self):
        if not messagebox.askyesno(
            "Duplicate Task",
            f"Create a copy of \"{self.task['title']}\"?\n\n"
            "The copy gets the description, due date, checkpoints (not completed) and links. "
            "Notes and attachments are not copied.",
            parent=self.window
        ):
            return
        new_id = duplicate_task(self.task_id)
        if new_id and self.open_task:
            self.open_task(new_id)

    # Loading Everything / closing

    def _load_all(self):
        self._load_kanban()
        self._load_notes()
        self._load_links()
        self._load_attachments()

    def _note_editors(self) -> list:
        """Returns note editor windows which are open now."""
        self._open_note_windows = {nid: ed for nid, ed in self._open_note_windows.items()
                                   if widget_alive(ed)}
        return list(self._open_note_windows.values())

    def rebuild(self):
        """Builds content of the window again with colors of the active theme.
        The window and note editors opened from it stay open."""
        for w in self.window.winfo_children():
            if not isinstance(w, tk.Toplevel):
                w.destroy()
        self.window.configure(bg=COLORS["bg"])
        self._build_ui()
        self._load_all()
        for editor in self._note_editors():
            editor.rebuild()

    def reload(self):
        """Reads the task again after the database content was replaced.
        The window is closed if the task does not exist anymore."""
        self.task = get_task(self.task_id)
        if not self.task:
            self.window.destroy()
            return
        existing = {n["id"] for n in get_notes(self.task_id)}
        for editor in self._note_editors():
            if editor.note["id"] not in existing:
                editor.window.destroy()
        self.rebuild()

    def save_open_notes(self):
        """Saves unsaved changes of all notes opened from this window."""
        for editor in self._note_editors():
            editor.save_if_changed()

    def close(self):
        """Closes the window; unsaved notes are saved first."""
        self.save_open_notes()
        if self.on_close:
            self.on_close()
        self.window.destroy()

    def _edit_task_info(self):
        dialog = EditTaskDialog(self.window, self.task["title"],
                                self.task.get("description") or "",
                                self.task.get("due_date") or "")
        self.window.wait_window(dialog.window)
        if dialog.result:
            new_title = dialog.result["title"]
            new_desc  = dialog.result["description"]
            new_due   = dialog.result["due_date"]
            update_task(self.task_id, new_title, new_desc, new_due)
            self.task["title"]       = new_title
            self.task["description"] = new_desc
            self.task["due_date"]    = new_due
            self._update_due_label()
            self.window.title(new_title)
            self.title_label.config(text=new_title)
            self.desc_label.config(text=new_desc)
            if new_desc:
                self.desc_label.pack(side="left", before=self.edit_btn)
            else:
                self.desc_label.pack_forget()


# Dialog: Add / Edit Checkpoint

class CheckpointDialog(Dialog):
    """Without checkpoint: adds a new one. With checkpoint: edits its name and type
    or deletes it. result: None = cancelled, "deleted", or {name, checkpoint_type}."""

    def __init__(self, parent, checkpoint: dict = None, can_delete: bool = True):
        self.checkpoint = checkpoint
        super().__init__(parent, "Edit Checkpoint" if checkpoint else "Add Checkpoint")

        self.add_label("Checkpoint Name")
        self.name_var = self.add_entry(checkpoint["name"] if checkpoint else "", focus=True)

        self.add_label("Checkpoint Type")
        self.type_var = self.add_radios(
            CHECKPOINT_TYPES,
            checkpoint.get("checkpoint_type", "check") if checkpoint else "check")

        btn_row = self.add_buttons("Save" if checkpoint else "Add", self._confirm)

        if checkpoint:
            # A task needs at least one checkpoint to be finished
            del_btn = make_button(btn_row, "Delete", self._delete,
                                  kind="danger", enabled=can_delete)
            del_btn.pack(side="left")
            if not can_delete:
                make_tooltip(del_btn, "The last checkpoint of a task can not be deleted.")

    def _confirm(self):
        name = self.name_var.get().strip()
        if not name:
            return
        self.result = {"name": name, "checkpoint_type": self.type_var.get()}
        self.window.destroy()

    def _delete(self):
        if messagebox.askyesno(
            "Delete Checkpoint",
            f"Are you sure you want to delete the checkpoint:\n\n\"{self.checkpoint['name']}\"?\n\n"
            "Remaining checkpoints will be automatically renumbered.",
            parent=self.window
        ):
            self.result = "deleted"
            self.window.destroy()


# Dialog: Note Title (new note / rename)

class NoteTitleDialog(Dialog):
    """result: the entered title, or None if cancelled."""

    def __init__(self, parent, title: str, current_title: str = "", ok_text: str = "Save"):
        super().__init__(parent, title, width=400)
        self.add_label("Note Title")
        self.title_var = self.add_entry(current_title, focus=True)
        self.add_buttons(ok_text, self._confirm)

    def _confirm(self):
        title = self.title_var.get().strip()
        if not title:
            return
        self.result = title
        self.window.destroy()


# Dialog: Edit Task Title and Description

class EditTaskDialog(Dialog):
    def __init__(self, parent, current_title: str, current_desc: str, current_due: str = ""):
        super().__init__(parent, "Edit Task", width=460)

        self.add_label("Title *")
        self.title_var = self.add_entry(current_title, focus=True)

        self.add_label("Description (optional)")
        self.desc_text = self.add_text(current_desc, height=4)

        self.add_label("Due date (optional)")
        self.due_var = self.add_entry(current_due)
        self.add_hint(DUE_DATE_HINT)

        self.add_buttons("Save", self._confirm)

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
            "title":       title,
            "description": self.desc_text.get("1.0", "end").strip(),
            "due_date":    due_date,
        }
        self.window.destroy()


# Dialog: Deleted attachments

class DeletedAttachmentsDialog:
    """Deleted attachments of a task with buttons to open or restore them.
    changed = True when something was restored."""

    def __init__(self, parent, task_id: int):
        self.task_id = task_id
        self.changed = False

        self.window = tk.Toplevel(parent)
        self.window.title("Deleted Attachments")
        self.window.configure(bg=COLORS["bg"])
        self.window.minsize(460, 200)
        self.window.transient(parent)
        remember_geometry(self.window, "deleted_attachments", "520x320", size_only=True)

        tk.Label(self.window, text="Deleted Attachments", font=FONT_HEADING,
                 bg=COLORS["bg"], fg=COLORS["accent"], pady=12, padx=20).pack(anchor="w")
        tk.Frame(self.window, bg=COLORS["accent"], height=1).pack(fill="x")

        container, _, self.inner = make_scroll_area(self.window)
        container.pack(fill="both", expand=True, padx=16, pady=12)
        self.window.bind("<Escape>", lambda e: self.window.destroy())
        grab_when_visible(self.window)
        self._load()

    def _load(self):
        for w in self.inner.winfo_children():
            w.destroy()
        deleted = [a for a in get_attachments(self.task_id, include_deleted=True) if a["deleted"]]
        if not deleted:
            tk.Label(self.inner, text="No deleted attachments.", font=FONT_SMALL,
                     bg=COLORS["bg"], fg=COLORS["text_dim"], pady=20).pack()
            return
        for att in deleted:
            path = resolve_attachment_path(att["stored_path"])
            exists = os.path.exists(path)
            row = tk.Frame(self.inner, bg=COLORS["card"], padx=10, pady=6)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=att["filename"], font=FONT_BODY, bg=COLORS["card"],
                     fg=COLORS["text"] if exists else COLORS["text_dim"]).pack(side="left")
            if not exists:
                tk.Label(row, text="  (file missing)", font=FONT_SMALL, bg=COLORS["card"],
                         fg=COLORS["overdue"]).pack(side="left")
                continue
            make_button(row, "Restore", lambda a=att: self._restore(a),
                        small=True).pack(side="right")
            make_button(row, "Open", lambda p=path: open_path(p, parent=self.window),
                        kind="secondary", small=True).pack(side="right", padx=(0, 4))

    def _restore(self, att: dict):
        """Moves the file back from the 'deleted' subfolder and marks it active."""
        src = resolve_attachment_path(att["stored_path"])
        folder = os.path.dirname(src)
        if os.path.basename(folder) == "deleted":
            folder = os.path.dirname(folder)
        dest = unique_path(os.path.join(folder, att["filename"]))
        try:
            os.replace(src, dest)
            restore_attachment(att["id"], dest)
        except Exception as ex:
            messagebox.showerror("Error", f"Failed to restore the attachment:\n{ex}",
                                 parent=self.window)
            return
        self.changed = True
        self._load()


# Dialog: Edit Link

class LinkEditDialog(Dialog):
    def __init__(self, parent, link: dict):
        super().__init__(parent, "Edit Link", width=460)

        self.add_label("Label")
        self.label_var = self.add_entry(link["label"], focus=True)

        self.add_label("Path")
        self.path_var = self.add_entry(link["path"])

        self.add_buttons("Save", self._save)

    def _save(self):
        label = self.label_var.get().strip()
        path  = self.path_var.get().strip()
        if not label or not path:
            return
        self.result = {"label": label, "path": path}
        self.window.destroy()


# Note Editor Window

class NoteEditorWindow:
    def __init__(self, parent, note: dict, on_save=None, on_close=None):
        self.note     = note
        self.on_save  = on_save
        self.on_close = on_close
        self._edit_mode = False

        self.window = tk.Toplevel(parent)
        self.window.title(note["title"])
        self.window.configure(bg=COLORS["bg"])
        self.window.minsize(500, 350)
        remember_geometry(self.window, "note", "700x520", size_only=True)

        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._render_preview()

    def _on_close(self):
        if self.has_unsaved_changes():
            answer = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes in the note.\n\nDo you want to save them?",
                parent=self.window
            )
            if answer is None:
                return
            elif answer:
                self._save()
        if self.on_close:
            self.on_close()
        self.window.destroy()

    def has_unsaved_changes(self) -> bool:
        if not self._edit_mode:
            return False
        return self.editor_text.get("1.0", "end-1c") != (self.note.get("content") or "")

    def save_if_changed(self):
        """Saves the note if it has unsaved changes, when the window is closed
        from outside (task window or application closed)."""
        if self.has_unsaved_changes():
            self._save()

    def set_title(self, title: str):
        """Shows new title of the note in the window."""
        self.note["title"] = title
        self.window.title(title)
        self.title_label.config(text=title)

    def rebuild(self):
        """Builds content of the window again with colors of the active theme.
        Text which is being edited and the cursor position are kept."""
        editing = self._edit_mode
        if editing:
            text   = self.editor_text.get("1.0", "end-1c")
            cursor = self.editor_text.index("insert")

        for w in self.window.winfo_children():
            if not isinstance(w, tk.Toplevel):
                w.destroy()
        self.window.configure(bg=COLORS["bg"])
        self._edit_mode = False
        self._build_ui()
        self._render_preview()

        if editing:
            self._enter_edit_mode()
            self.editor_text.delete("1.0", "end")
            self.editor_text.insert("1.0", text)
            self.editor_text.mark_set("insert", cursor)

    def _build_ui(self):
        hdr = tk.Frame(self.window, bg=COLORS["panel"])
        hdr.pack(fill="x")

        self.title_label = tk.Label(
            hdr, text=self.note["title"],
            font=FONT_HEADING, bg=COLORS["panel"],
            fg=COLORS["accent"], padx=16, pady=10
        )
        self.title_label.pack(side="left")

        dt = self.note["created_at"][:16].replace("T", "  ")
        tk.Label(
            hdr, text=dt,
            font=FONT_SMALL, bg=COLORS["panel"],
            fg=COLORS["text_dim"], padx=8
        ).pack(side="left")

        self.mode_btn = make_button(hdr, "✏ Edit", self._toggle_mode, small=True)
        self.mode_btn.pack(side="right", padx=12, pady=8)

        tk.Frame(self.window, bg=COLORS["accent"], height=2).pack(fill="x")

        self.toolbar = tk.Frame(self.window, bg=COLORS["panel"])
        self._build_toolbar()

        self.content_frame = tk.Frame(self.window, bg=COLORS["bg"])
        self.content_frame.pack(fill="both", expand=True, padx=12, pady=8)
        self.content_frame.rowconfigure(0, weight=1)
        self.content_frame.columnconfigure(0, weight=1)

        self.preview_text = tk.Text(
            self.content_frame,
            font=FONT_BODY, bg=COLORS["card"], fg=COLORS["text"],
            relief="flat", wrap="word", padx=12, pady=8,
            state="disabled", cursor="arrow"
        )
        self.preview_text.grid(row=0, column=0, sticky="nsew")

        self.editor_text = tk.Text(
            self.content_frame,
            font=mono_font(10), bg=COLORS["panel"], fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat", wrap="word", padx=12, pady=8
        )
        # One scrollbar for both views; it scrolls the visible one
        sb = tk.Scrollbar(self.content_frame, orient="vertical",
                          command=lambda *args: self._visible_text().yview(*args))
        sb.grid(row=0, column=1, sticky="ns")
        self.preview_text.configure(yscrollcommand=sb.set)
        self.editor_text.configure(yscrollcommand=sb.set)

    def _visible_text(self) -> tk.Text:
        return self.editor_text if self._edit_mode else self.preview_text

    def _build_toolbar(self):
        tools = [
            ("B",  font(10, "bold"),   self._fmt_bold),
            ("I",  font(10, "italic"), self._fmt_italic),
            ("S",  font(10),           self._fmt_strike),
            ("H",  font(10, "bold underline"), self._fmt_highlight),
        ]
        for symbol, tool_font, cmd in tools:
            btn = tk.Label(
                self.toolbar, text=symbol, font=tool_font,
                bg=COLORS["panel"], fg=COLORS["text"],
                padx=10, pady=4, cursor="hand2", relief="flat"
            )
            btn.pack(side="left", padx=2, pady=4)
            btn.bind("<Button-1>", lambda e, c=cmd: c())
            btn.bind("<Enter>", lambda e, b=btn: b.config(bg=COLORS["card_hover2"]))
            btn.bind("<Leave>", lambda e, b=btn: b.config(bg=COLORS["panel"]))

        tk.Frame(self.toolbar, bg=COLORS["border"], width=1).pack(side="left", fill="y", padx=6)

        tk.Label(
            self.toolbar,
            text="**bold**  *italic*  ~~strikethrough~~",
            font=FONT_SMALL, bg=COLORS["panel"], fg=COLORS["text_dim"],
            padx=8
        ).pack(side="left")

    def _toggle_mode(self):
        if self._edit_mode:
            self._save()
        else:
            self._enter_edit_mode()

    def _enter_edit_mode(self):
        self._edit_mode = True
        self.mode_btn.config(text="Save")

        self.editor_text.delete("1.0", "end")
        self.editor_text.insert("1.0", self.note.get("content") or "")

        self.toolbar.pack(fill="x", before=self.content_frame)
        self.preview_text.grid_remove()
        self.editor_text.grid(row=0, column=0, sticky="nsew")
        self.editor_text.focus_set()

    def _save(self):
        content = self.editor_text.get("1.0", "end-1c")
        update_note(self.note["id"], self.note["title"], content)
        self.note["content"] = content
        self._edit_mode = False
        self.mode_btn.config(text="✏ Edit")

        self.toolbar.pack_forget()
        self.editor_text.grid_remove()
        self.preview_text.grid(row=0, column=0, sticky="nsew")

        self._render_preview()
        if self.on_save:
            self.on_save()

    # Markdown preview
    # Every piece of text gets one tag describing all its formats together
    # (e.g. "bold_hl_hexFFD700"), configured on first use in _configure_combo_tag.

    _PATTERNS = [
        (re.compile(r'==(#[0-9A-Fa-f]{6})==(.*?)=='), "highlight"),
        (re.compile(r'\*\*\*(.*?)\*\*\*'),            "bold_italic"),
        (re.compile(r'\*\*(.*?)\*\*'),                "bold"),
        (re.compile(r'\*([^*]+?)\*'),                 "italic"),
        (re.compile(r'~~(.*?)~~'),                    "strikethrough"),
    ]

    def _render_preview(self):
        content = self.note.get("content") or ""
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")

        for line in content.split("\n"):
            self._parse_segment(line, frozenset())
            self.preview_text.insert("end", "\n")

        self.preview_text.configure(state="disabled")

    def _parse_segment(self, text: str, active_tags: frozenset):
        if not text:
            return

        earliest_match = None
        earliest_pattern_type = None

        for pat, ptype in self._PATTERNS:
            m = pat.search(text)
            if m and (earliest_match is None or m.start() < earliest_match.start()):
                earliest_match = m
                earliest_pattern_type = ptype

        if earliest_match is None:
            self._insert_text(text, active_tags)
            return

        if earliest_match.start() > 0:
            self._insert_text(text[:earliest_match.start()], active_tags)

        if earliest_pattern_type == "highlight":
            color    = earliest_match.group(1)
            inner    = earliest_match.group(2)
            new_tags = active_tags | {f"hl_{color.replace('#', 'hex')}"}
        else:
            inner    = earliest_match.group(1)
            new_tags = active_tags | {earliest_pattern_type}

        self._parse_segment(inner, new_tags)

        rest = text[earliest_match.end():]
        if rest:
            self._parse_segment(rest, active_tags)

    def _insert_text(self, text: str, tags: frozenset):
        if not text:
            return
        if not tags:
            self.preview_text.insert("end", text)
            return
        tag_list = sorted(tags)
        combo_key = "_".join(tag_list)
        if combo_key not in self.preview_text.tag_names():
            self._configure_combo_tag(combo_key, tag_list)
        self.preview_text.insert("end", text, combo_key)

    def _configure_combo_tag(self, combo_key: str, tag_list: list):
        font_bold   = "bold"          in tag_list or "bold_italic" in tag_list
        font_italic = "italic"        in tag_list or "bold_italic" in tag_list
        overstrike  = "strikethrough" in tag_list

        style = " ".join(s for s, on in (("bold", font_bold), ("italic", font_italic)) if on)
        kwargs = {"font": font(10, style) if style else font(10),
                  "overstrike": overstrike}

        hl_tag = next((t for t in tag_list if t.startswith("hl_hex")), None)
        if hl_tag:
            kwargs["background"] = "#" + hl_tag[len("hl_hex"):]
            kwargs["foreground"] = "#1a1a2e"

        self.preview_text.tag_configure(combo_key, **kwargs)

    # Formatting toolbar

    def _wrap_selection(self, marker_open: str, marker_close: str = None):
        if marker_close is None:
            marker_close = marker_open
        try:
            sel_start = self.editor_text.index("sel.first")
            sel_end   = self.editor_text.index("sel.last")
            selected  = self.editor_text.get(sel_start, sel_end)
            self.editor_text.delete(sel_start, sel_end)
            self.editor_text.insert(sel_start, f"{marker_open}{selected}{marker_close}")
        except tk.TclError:
            self.editor_text.insert("insert", f"{marker_open}text{marker_close}")

    def _fmt_bold(self):    self._wrap_selection("**")
    def _fmt_italic(self):  self._wrap_selection("*")
    def _fmt_strike(self):  self._wrap_selection("~~")

    def _fmt_highlight(self):
        picker = HighlightColorPicker(self.window, HIGHLIGHT_COLORS)
        self.window.wait_window(picker.window)
        if picker.result:
            self._wrap_selection(f"=={picker.result}==", "==")


# Background Color Picker

class HighlightColorPicker:
    def __init__(self, parent, colors: list):
        self.result = None

        self.window = tk.Toplevel(parent)
        self.window.title("Select Background Color")
        self.window.configure(bg=COLORS["bg"])
        self.window.geometry("320x100")
        self.window.resizable(False, False)
        self.window.transient(parent)
        grab_when_visible(self.window)

        tk.Label(
            self.window, text="Select Color:",
            font=FONT_BODY, bg=COLORS["bg"], fg=COLORS["text"],
            padx=12, pady=8
        ).pack(anchor="w")

        row = tk.Frame(self.window, bg=COLORS["bg"])
        row.pack(padx=12)

        for hex_color, name in colors:
            swatch = tk.Label(
                row, text="  ", bg=hex_color,
                width=4, relief="flat", cursor="hand2",
                padx=2, pady=10
            )
            swatch.pack(side="left", padx=3)
            make_tooltip(swatch, name)
            swatch.bind("<Button-1>", lambda e, c=hex_color: self._pick(c))

        self.window.bind("<Escape>", lambda e: self.window.destroy())

    def _pick(self, color: str):
        self.result = color
        self.window.destroy()


# Helpers

def _note_preview(content: str, max_lines: int = 2, max_chars: int = 78) -> str:
    """Returns a preview of the note content: max_lines lines of max_chars characters.
    Removes markdown tags (same syntax as the note preview) before displaying."""
    if not content:
        return ""
    text = re.sub(r'==(#[0-9A-Fa-f]{6})==(.*?)==', r'\2', content)
    text = re.sub(r'\*\*\*(.*?)\*\*\*', r'\1', text)
    text = re.sub(r'\*\*(.*?)\*\*',     r'\1', text)
    text = re.sub(r'\*([^*]+?)\*',      r'\1', text)
    text = re.sub(r'~~(.*?)~~',         r'\1', text)

    lines = [l for l in text.split('\n') if l.strip()]
    preview = []
    for line in lines[:max_lines]:
        if len(line) > max_chars:
            line = line[:max_chars - 1] + "…"
        preview.append(line)
    return '\n'.join(preview)
