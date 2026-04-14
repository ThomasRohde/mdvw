from __future__ import annotations

import json
import os
from pathlib import Path


def _config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / "mdvw"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return _config_dir() / "config.json"


def load() -> dict:
    p = config_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save(data: dict) -> None:
    p = config_path()
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get(key: str, default=None):
    return load().get(key, default)


def set_key(key: str, value) -> None:
    data = load()
    data[key] = value
    save(data)
