# User settings kept in settings.json in the data folder

import json
import os

from config import SETTINGS_PATH

DEFAULTS = {
    "theme":            "dark",
    "geometry":         {},    # window key -> "WxH+X+Y" or "WxH"
    "auto_backup_days": 7,     # 0 = no automatic backups
    "auto_backup_keep": 5,     # automatic backups kept; manual ones are never removed
    "idle_days":        14,    # highlight tasks without activity for so many days; 0 = off
}

_cache = None


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                _cache = json.load(f)
            if not isinstance(_cache, dict):
                _cache = {}
        except Exception:
            _cache = {}
    return _cache


def get(key: str):
    """Returns a setting, or its default value when it was never saved."""
    value = _load().get(key, DEFAULTS.get(key))
    default = DEFAULTS.get(key)
    if default is not None and not isinstance(value, type(default)):
        return default   # damaged or hand-edited value of a wrong type
    return value


def update(**values):
    """Changes settings and saves the file (written under a temporary name first)."""
    data = _load()
    data.update(values)
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        tmp_path = SETTINGS_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, SETTINGS_PATH)
    except Exception:
        pass   # settings never stop the application


def reload():
    """Forgets the cached settings, so the next get() reads the file again
    (after data of an older version was moved into the data folder)."""
    global _cache
    _cache = None
