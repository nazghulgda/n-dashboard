# Colour themes of the application

import settings

# Theme definitions

THEME_DARK = {
    "bg":                "#1a1a2e",
    "panel":             "#16213e",
    "card":              "#0f3460",
    "card_hover":        "#1a4a7a",
    "card_hover2":       "#1e3a5f",
    "accent":            "#e94560",
    "accent2":           "#f5a623",
    "text":              "#eaeaea",
    "text_dim":          "#8899aa",
    "progress_bg":       "#0a1628",
    "progress_fg":       "#e94560",
    "btn":               "#e94560",
    "btn_hover":         "#c73652",
    "btn_secondary":     "#0f3460",
    "btn_sec_hover":     "#1a4a7a",
    "border":            "#1e3a5f",
    "check_on":          "#e94560",
    "checkpoint_done":   "#1a3a1a",
    "checkpoint_undone": "#0f3460",
    "text_disabled":     "#4a5a6e",
    "btn_danger":        "#3a1515",
    "btn_danger_hover":  "#5a2020",
    "btn_danger_fg":     "#ff9999",
    "status_not_started": "#e0ed8c",
    "status_in_progress": "#d9b4bd",
    "status_completed":   "#4ade80",
    "overdue":            "#ff6b6b",
    "idle":               "#f5a623",
}

THEME_LIGHT = {
    "bg":                "#f0f2f5",
    "panel":             "#ffffff",
    "card":              "#ffffff",
    "card_hover":        "#e8edf5",
    "card_hover2":       "#dce4f0",
    "accent":            "#1a56db",
    "accent2":           "#b45309",
    "text":              "#111827",
    "text_dim":          "#4b5563",
    "progress_bg":       "#d1d5db",
    "progress_fg":       "#1a56db",
    "btn":               "#1a56db",
    "btn_hover":         "#1447b5",
    "btn_secondary":     "#e5e7eb",
    "btn_sec_hover":     "#d1d5db",
    "border":            "#d1d5db",
    "check_on":          "#1a56db",
    "checkpoint_done":   "#dcfce7",
    "checkpoint_undone": "#f9fafb",
    "text_disabled":     "#9ca3af",
    "btn_danger":        "#fee2e2",
    "btn_danger_hover":  "#fecaca",
    "btn_danger_fg":     "#b91c1c",
    "status_not_started": "#ca8a04",
    "status_in_progress": "#db2777",
    "status_completed":   "#16a34a",
    "overdue":            "#dc2626",
    "idle":               "#b45309",
}

THEMES = {
    "dark":  THEME_DARK,
    "light": THEME_LIGHT,
}

THEME_NAMES = {
    "dark":  "Dark (terminal)",
    "light": "Light (Windows)",
}

# Active theme

_current_theme_name: str = "dark"
_current_colors: dict = dict(THEME_DARK)


def load_theme():
    """Loads the saved theme (application start, data of an older version moved)."""
    global _current_theme_name
    name = settings.get("theme")
    if name not in THEMES:
        name = "dark"
    _current_theme_name = name
    _current_colors.clear()
    _current_colors.update(THEMES[name])


def set_theme(name: str):
    """Sets theme and saves the choice to the settings file."""
    global _current_theme_name
    if name not in THEMES:
        return
    _current_theme_name = name
    _current_colors.clear()
    _current_colors.update(THEMES[name])
    settings.update(theme=name)


def get_colors() -> dict:
    """Returns color dictionary of the active theme."""
    return _current_colors


def get_theme_name() -> str:
    return _current_theme_name
