"""UI state persistence for mdvw.

Stores transient UI state (pane widths, active section, recent files, etc.)
in ``%APPDATA%/mdvw/state.json``, separate from ``config.json`` which holds
user preferences and flags.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _state_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / "mdvw"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_path() -> Path:
    return _state_dir() / "state.json"


_DEFAULTS: dict = {
    "left_pane_width": 280,
    "left_pane_collapsed": False,
    "left_pane_section": "files",
    "right_pane_width": 300,
    "right_pane_collapsed": True,
    "mode": "read",
    "preview_narrow": False,
    "recent_files": [],
    "last_file": None,
    "last_browse_root": None,
}


def load() -> dict:
    p = state_path()
    if not p.exists():
        return dict(_DEFAULTS)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(_DEFAULTS)
    # Valid JSON may still be a list/null/string; those would crash the
    # setdefault loop below and brick startup. Fall back to defaults.
    if not isinstance(data, dict):
        return dict(_DEFAULTS)
    for k, v in _DEFAULTS.items():
        data.setdefault(k, v)
    return data


def save(data: dict) -> None:
    p = state_path()
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get(key: str, default=None):
    return load().get(key, default if default is not None else _DEFAULTS.get(key))


def set_key(key: str, value) -> None:
    data = load()
    data[key] = value
    save(data)


def add_recent(path: str, *, max_entries: int = 20) -> None:
    """Prepend *path* to the recent files list, dedup, and trim."""
    data = load()
    recent = data.get("recent_files", [])
    # Remove duplicates (case-insensitive on Windows).
    normalised = os.path.normcase(path)
    recent = [r for r in recent if os.path.normcase(r) != normalised]
    recent.insert(0, path)
    data["recent_files"] = recent[:max_entries]
    save(data)
