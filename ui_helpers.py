# Widgets and helpers shared by all windows

import os
import re
import subprocess
import sys
import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, ttk

import settings
from theme import get_colors

# Drag and drop of files is optional; the app works without it
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
except Exception:
    TkinterDnD = DND_FILES = None
_dnd_ready = False

# The active theme dictionary, updated in place by theme.set_theme()
COLORS = get_colors()

# Font families of each system; Tk falls back to its default font if one is missing
if sys.platform == "win32":
    FONT_FAMILY, MONO_FAMILY = "Segoe UI", "Consolas"
elif sys.platform == "darwin":
    FONT_FAMILY, MONO_FAMILY = "Helvetica Neue", "Menlo"
else:
    FONT_FAMILY, MONO_FAMILY = "DejaVu Sans", "DejaVu Sans Mono"


def font(size: int, style: str = "") -> tuple:
    """Font of the application in the given size; style: '', 'bold', 'italic', 'bold italic'."""
    return (FONT_FAMILY, size, style) if style else (FONT_FAMILY, size)


def mono_font(size: int, style: str = "") -> tuple:
    return (MONO_FAMILY, size, style) if style else (MONO_FAMILY, size)


FONT_HEADING = font(11, "bold")
FONT_BODY    = font(10)
FONT_BOLD    = font(10, "bold")
FONT_SMALL   = font(8)

# kind -> (background, hover background, foreground) as keys of the theme;
# foreground None = white
_BUTTON_KINDS = {
    "primary":   ("btn",           "btn_hover",        None),
    "secondary": ("btn_secondary", "btn_sec_hover",    "text_dim"),
    "danger":    ("btn_danger",    "btn_danger_hover", "btn_danger_fg"),
}


# Buttons

def make_button(parent, text, command, kind="primary", small=False, bold=False,
                enabled=True):
    """Flat button (tk.Label) in colors of the active theme.
    kind: 'primary' | 'secondary' | 'danger'. The caller places the button."""
    font = FONT_SMALL if small else (FONT_BOLD if bold else FONT_BODY)
    btn = tk.Label(parent, text=text, font=font, relief="flat",
                   padx=8 if small else 14, pady=4 if small else 6)
    btn._kind = kind
    btn._command = command

    def on_click(e):
        if btn._enabled:
            btn._command()

    def on_enter(e):
        if btn._enabled:
            btn.config(bg=COLORS[_BUTTON_KINDS[btn._kind][1]])

    def on_leave(e):
        if btn._enabled:
            btn.config(bg=COLORS[_BUTTON_KINDS[btn._kind][0]])

    btn.bind("<Button-1>", on_click)
    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)
    set_button_enabled(btn, enabled)
    return btn


def set_button_enabled(btn, enabled: bool, text: str = None):
    """Enables or disables a button made by make_button, optionally changes its text."""
    btn._enabled = enabled
    if text is not None:
        btn.config(text=text)
    if enabled:
        bg, _, fg = _BUTTON_KINDS[btn._kind]
        btn.config(bg=COLORS[bg], fg=COLORS[fg] if fg else "white", cursor="hand2")
    else:
        btn.config(bg=COLORS["btn_secondary"], fg=COLORS["text_disabled"], cursor="")


def make_icon_button(parent, text, command, bg, font=FONT_SMALL, padx=6):
    """Small icon button (✏, ×, ▲ ...) without its own background; highlighted on hover."""
    btn = tk.Label(parent, text=text, font=font, bg=bg, fg=COLORS["text_dim"],
                   padx=padx, cursor="hand2")
    btn.bind("<Button-1>", lambda e: command())
    btn.bind("<Enter>", lambda e: btn.config(fg=COLORS["accent"]))
    btn.bind("<Leave>", lambda e: btn.config(fg=COLORS["text_dim"]))
    return btn


# Hover, tooltip

def bind_hover(widget, color_normal, color_hover, exclude=()):
    """Changes background of the widget and everything inside it (at any depth) while
    the cursor is over it. Widgets from exclude (and their content) keep their colors.
    Other <Enter>/<Leave> bindings of the widget (e.g. tooltip) are kept."""
    def set_color(w, color):
        try:
            w.config(bg=color)
        except tk.TclError:
            pass
        for child in w.winfo_children():
            if child not in exclude and not isinstance(child, tk.Toplevel):
                set_color(child, color)

    def on_enter(e):
        set_color(widget, color_hover)

    def on_leave(e):
        # Moving the cursor onto a child of the widget is not leaving it
        try:
            under = str(widget.winfo_containing(*widget.winfo_pointerxy()) or "")
        except Exception:
            under = ""
        if under == str(widget) or under.startswith(str(widget) + "."):
            return
        set_color(widget, color_normal)

    widget.bind("<Enter>", on_enter, add="+")
    widget.bind("<Leave>", on_leave, add="+")


def make_tooltip(widget, text: str):
    tip_window = None

    def show(e):
        nonlocal tip_window
        if tip_window is not None:
            return
        x = widget.winfo_rootx() + 10
        y = widget.winfo_rooty() + widget.winfo_height() + 4
        tip_window = tk.Toplevel(widget)
        tip_window.wm_overrideredirect(True)
        tip_window.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tip_window, text=text,
            font=FONT_SMALL, bg="#ffffe0", fg="#1a1a2e",
            relief="solid", borderwidth=1, padx=6, pady=3
        ).pack()

    def hide(e):
        nonlocal tip_window
        if tip_window is not None:
            tip_window.destroy()
            tip_window = None

    # add="+" keeps other <Enter>/<Leave> handlers of the widget (hover colors)
    widget.bind("<Enter>", show, add="+")
    widget.bind("<Leave>", hide, add="+")


# Scrollable list

def make_scroll_area(parent):
    """Canvas with a vertical scrollbar and a frame inside it.
    Returns (container, canvas, inner): the caller places container,
    content goes into inner."""
    container = tk.Frame(parent, bg=COLORS["bg"])
    container.rowconfigure(0, weight=1)
    container.columnconfigure(0, weight=1)

    canvas = tk.Canvas(container, bg=COLORS["bg"], highlightthickness=0, bd=0)
    sb = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=sb.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    sb.grid(row=0, column=1, sticky="ns")

    inner = tk.Frame(canvas, bg=COLORS["bg"])
    win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))
    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    return container, canvas, inner


# Modal dialog

class Dialog:
    """Base of modal dialogs: header, form and button row.
    A subclass fills self.form, sets self.result and calls self.window.destroy()."""

    def __init__(self, parent, title: str, width: int = 420):
        self.result = None
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.configure(bg=COLORS["bg"])
        self.window.resizable(False, False)
        self.window.minsize(width, 1)
        self.window.transient(parent)
        grab_when_visible(self.window)

        tk.Label(self.window, text=title, font=FONT_HEADING,
                 bg=COLORS["bg"], fg=COLORS["accent"],
                 pady=12, padx=20).pack(anchor="w")
        tk.Frame(self.window, bg=COLORS["accent"], height=1).pack(fill="x")

        self.form = tk.Frame(self.window, bg=COLORS["bg"], padx=20, pady=14)
        self.form.pack(fill="both", expand=True)

        self.window.bind("<Escape>", lambda e: self.window.destroy())

    def add_label(self, text: str):
        tk.Label(self.form, text=text, font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w")

    def add_entry(self, value: str = "", focus: bool = False) -> tk.StringVar:
        var = tk.StringVar(value=value)
        entry = tk.Entry(self.form, textvariable=var, font=FONT_BODY,
                         bg=COLORS["card"], fg=COLORS["text"],
                         insertbackground=COLORS["text"], relief="flat")
        entry.pack(fill="x", ipady=5, pady=(2, 12))
        if focus:
            entry.focus_set()
            entry.select_range(0, "end")
        return var

    def add_text(self, value: str = "", height: int = 3) -> tk.Text:
        text = tk.Text(self.form, height=height, font=FONT_BODY,
                       bg=COLORS["card"], fg=COLORS["text"],
                       insertbackground=COLORS["text"], relief="flat", wrap="word")
        text.insert("1.0", value)
        text.pack(fill="x", pady=(2, 12))
        return text

    def add_radios(self, options: list, value: str, vertical: bool = False) -> tk.StringVar:
        """options: list of (value, label)."""
        var = tk.StringVar(value=value)
        frame = tk.Frame(self.form, bg=COLORS["bg"])
        frame.pack(anchor="w", pady=(2, 14))
        style = dict(
            bg=COLORS["bg"], fg=COLORS["text"],
            activebackground=COLORS["bg"], activeforeground=COLORS["text"],
            selectcolor=COLORS["card"], font=FONT_BODY
        )
        for val, label in options:
            rb = tk.Radiobutton(frame, text=label, variable=var, value=val, **style)
            if vertical:
                rb.pack(anchor="w")
            else:
                rb.pack(side="left", padx=(0, 20))
        return var

    def add_checkbox(self, text: str, value: bool = False) -> tk.BooleanVar:
        var = tk.BooleanVar(value=value)
        tk.Checkbutton(self.form, text=text, variable=var, font=FONT_BODY,
                       bg=COLORS["bg"], fg=COLORS["text"],
                       activebackground=COLORS["bg"], activeforeground=COLORS["text"],
                       selectcolor=COLORS["card"]).pack(anchor="w", pady=(0, 12))
        return var

    def add_combobox(self, values: list, value: str) -> tk.StringVar:
        var = tk.StringVar(value=value)
        ttk.Combobox(self.form, textvariable=var, values=values, state="readonly",
                     font=FONT_BODY).pack(fill="x", ipady=3, pady=(2, 12))
        return var

    def add_hint(self, text: str):
        """Small grey text under the previous field."""
        tk.Label(self.form, text=text, font=FONT_SMALL, bg=COLORS["bg"],
                 fg=COLORS["text_dim"], justify="left").pack(anchor="w", pady=(0, 12))

    def show_error(self, text: str):
        """Shows a message above the buttons, e.g. about a wrong value in a field."""
        if not hasattr(self, "_error_label"):
            self._error_label = tk.Label(self.form, font=FONT_SMALL, bg=COLORS["bg"],
                                         fg=COLORS["overdue"], justify="left")
            self._error_label.pack(anchor="w", pady=(0, 8), before=self._button_row)
        self._error_label.config(text=text)

    def add_buttons(self, ok_text: str, on_ok, cancel: bool = True) -> tk.Frame:
        """Button row: OK (and Cancel) on the right. Enter = OK.
        Returns the row, so more buttons can be added on its left side."""
        row = tk.Frame(self.form, bg=COLORS["bg"])
        row.pack(fill="x")
        self._button_row = row
        if cancel:
            make_button(row, "Cancel", self.window.destroy,
                        kind="secondary").pack(side="right", padx=(8, 0))
        make_button(row, ok_text, on_ok, bold=True).pack(side="right")
        self.window.bind("<Return>", lambda e: on_ok())
        return row


# Due dates

DUE_DATE_HINT = "YYYY-MM-DD, \"today\" or +N (days from today); empty = no due date"


def parse_due_date(text: str):
    """Converts what the user typed into 'YYYY-MM-DD' (None = no due date).
    Accepts 2026-11-20, "today" and +N = N days from today. Raises ValueError."""
    text = text.strip().lower()
    if not text:
        return None
    if text == "today":
        return date.today().isoformat()
    if re.fullmatch(r"\+\d{1,4}", text):
        return (date.today() + timedelta(days=int(text[1:]))).isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise ValueError(f"Unknown date: {text}")
    return date.fromisoformat(text).isoformat()


def due_state(due_date, finished: bool):
    """'overdue' | 'today' | 'soon' (within 3 days) | 'later' | None (no date or finished)."""
    if not due_date or finished:
        return None
    days = (date.fromisoformat(due_date) - date.today()).days
    if days < 0:
        return "overdue"
    if days == 0:
        return "today"
    return "soon" if days <= 3 else "later"


def due_text(due_date, finished: bool) -> str:
    state = due_state(due_date, finished)
    if not due_date:
        return ""
    if state == "overdue":
        return f"overdue since {due_date}"
    if state == "today":
        return "due today"
    return f"due {due_date}"


def due_color(due_date, finished: bool) -> str:
    state = due_state(due_date, finished)
    if state in ("overdue", "today"):
        return COLORS["overdue"]
    if state == "soon":
        return COLORS["idle"]
    return COLORS["text_dim"]


# Window size and position remembered between starts

_geometries = {}   # key -> geometry seen last, saved to settings.json


def remember_geometry(window, key: str, default: str, size_only: bool = False):
    """Opens the window with its size (and position) from the last time and keeps
    track of changes. size_only=True for windows which can be open many times at once
    (task, note), or they would all land in the same place."""
    saved = settings.get("geometry").get(key)
    window.geometry(_usable_geometry(window, saved, size_only) or default)

    def on_configure(e):
        if e.widget is not window:
            return
        try:
            if window.state() != "normal":
                return   # minimized or maximized: keep the normal size
            geo = window.geometry()
        except tk.TclError:
            return
        _geometries[key] = geo.split("+")[0] if size_only else geo

    def on_destroy(e):
        if e.widget is window:
            save_geometries()

    window.bind("<Configure>", on_configure, add="+")
    window.bind("<Destroy>", on_destroy, add="+")


def save_geometries():
    if _geometries:
        geometries = dict(settings.get("geometry"))
        geometries.update(_geometries)
        settings.update(geometry=geometries)


def _usable_geometry(window, saved, size_only: bool):
    """Saved geometry, without the position when it would put the window off the screen
    (e.g. a monitor which is not connected anymore). None if nothing usable was saved."""
    m = re.fullmatch(r"(\d+)x(\d+)(?:\+(-?\d+)\+(-?\d+))?", saved or "")
    if not m:
        return None
    w, h = max(int(m.group(1)), 200), max(int(m.group(2)), 150)
    if size_only or m.group(3) is None:
        return f"{w}x{h}"
    x, y = int(m.group(3)), int(m.group(4))
    screen_w = max(window.winfo_screenwidth(), window.winfo_vrootwidth())
    screen_h = max(window.winfo_screenheight(), window.winfo_vrootheight())
    if -w + 100 < x < screen_w - 100 and -20 < y < screen_h - 100:
        return f"{w}x{h}+{x}+{y}"
    return f"{w}x{h}"


# Drag and drop of files

def make_root(class_name: str) -> tk.Tk:
    """Main window of the application, with drag and drop of files when tkinterdnd2
    and its Tk extension can be loaded; a plain tk.Tk otherwise."""
    global _dnd_ready
    if TkinterDnD is not None:
        try:
            root = TkinterDnD.Tk(className=class_name)
            _dnd_ready = True
            return root
        except Exception:
            pass
    return tk.Tk(className=class_name)


def drop_available() -> bool:
    return _dnd_ready


def enable_file_drop(widget, on_paths):
    """Accepts files and folders dropped from the file manager onto the widget or
    anything inside it; on_paths(list of paths) is called after the drop has finished.
    Call it again after the content of the widget was built anew."""
    if not _dnd_ready:
        return

    def on_drop(event):
        paths = [p for p in widget.tk.splitlist(event.data) if p]
        # Run after the drop: a dialog opened inside the handler would keep the
        # file manager waiting
        widget.after_idle(on_paths, paths)
        return event.action

    def register(w):
        try:
            w.drop_target_register(DND_FILES)
            w.dnd_bind("<<Drop>>", on_drop)
        except Exception:
            return
        for child in w.winfo_children():
            if not isinstance(child, tk.Toplevel):
                register(child)

    register(widget)


# Windows and files

def grab_when_visible(window):
    """Makes the window modal. On Linux grab_set fails ("window not viewable")
    when it is called before the window is shown, so it waits for that first."""
    try:
        window.wait_visibility()
        window.grab_set()
    except tk.TclError:
        pass


def widget_alive(win) -> bool:
    """True if the window of a window object (anything with .window) still exists."""
    try:
        return bool(win.window.winfo_exists())
    except Exception:
        return False


def open_path(path: str, parent=None):
    """Opens a file or folder with the default application of the system."""
    try:
        if not os.path.exists(path):
            raise FileNotFoundError("The file or folder does not exist.")
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as ex:
        messagebox.showerror("Error", f"Can't be opened:\n{path}\n\n{ex}", parent=parent)
