from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from mdvw import app as app_mod
from mdvw import state


def _make_files(tmp_path: Path, files: dict[str, str | bytes]) -> Path:
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return tmp_path


def test_move_current_note_updates_workspace_links(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    root = _make_files(tmp_path, {
        "Index.md": (
            "[[Old#Sec|Read]]\n"
            "[[journal/2026/Old#Sec]]\n"
            "[go](journal/2026/Old.md#top)\n"
        ),
        "journal/Guide.md": "# Guide\n",
        "journal/assets/pic.png": b"png",
        "journal/2026/Old.md": (
            "[[Old]]\n"
            "[[../Guide]]\n"
            "![img](../assets/pic.png)\n"
            "[me](Old.md)\n"
        ),
    })
    old = root / "journal" / "2026" / "Old.md"
    new = root / "Archive" / "New.md"

    api = app_mod.JsApi()
    api._browse_root = root
    api._current_path = old
    api._window = MagicMock()

    result = api.move_current_note("Archive/New")

    assert result == {
        "status": "ok",
        "path": str(new.resolve()),
        "old_path": str(old.resolve()),
        "relative": "Archive/New.md",
        "name": "New.md",
        "updated_files": 2,
    }
    assert not old.exists()
    assert new.read_text(encoding="utf-8") == (
        "[[New]]\n"
        "[[journal/Guide]]\n"
        "![img](../journal/assets/pic.png)\n"
        "[me](New.md)\n"
    )
    assert (root / "Index.md").read_text(encoding="utf-8") == (
        "[[New#Sec|Read]]\n"
        "[[Archive/New#Sec]]\n"
        "[go](Archive/New.md#top)\n"
    )
    assert api._current_path == new.resolve()
    assert state.get("recent_files") == [str(new.resolve())]
    assert state.get("last_file") == str(new.resolve())


def test_move_current_note_rejects_existing_target(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    root = _make_files(tmp_path, {
        "Old.md": "[[Old]]\n[go](Old.md)\n",
        "Target.md": "# taken\n",
        "Index.md": "[[Old]]\n",
    })
    old = root / "Old.md"

    api = app_mod.JsApi()
    api._browse_root = root
    api._current_path = old
    api._window = MagicMock()

    result = api.move_current_note("Target")

    assert result == {"status": "error", "message": "Target already exists"}
    assert old.read_text(encoding="utf-8") == "[[Old]]\n[go](Old.md)\n"
    assert (root / "Index.md").read_text(encoding="utf-8") == "[[Old]]\n"
    assert api._current_path == old
