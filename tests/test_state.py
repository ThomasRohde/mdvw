"""Tests for the state persistence module."""

from __future__ import annotations

import json

from mdvw import state


def test_load_returns_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    data = state.load()
    assert data["left_pane_width"] == 280
    assert data["recent_files"] == []
    assert data["left_pane_section"] == "files"


def test_save_and_load_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    data = state.load()
    data["left_pane_width"] = 350
    data["mode"] = "edit"
    state.save(data)
    reloaded = state.load()
    assert reloaded["left_pane_width"] == 350
    assert reloaded["mode"] == "edit"


def test_load_fills_missing_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    # Write a partial state file.
    p = tmp_path / "mdvw" / "state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"left_pane_width": 400}), encoding="utf-8")
    data = state.load()
    assert data["left_pane_width"] == 400
    assert data["recent_files"] == []  # default filled in


def test_load_handles_corrupt_json(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    p = tmp_path / "mdvw" / "state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{bad json", encoding="utf-8")
    data = state.load()
    assert data["left_pane_width"] == 280  # defaults


def test_load_handles_non_object_json(tmp_path, monkeypatch):
    """Valid JSON that isn't an object (``[]``, ``null``, a string) must
    not brick startup — ``load()`` calls ``setdefault`` on the result."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    p = tmp_path / "mdvw" / "state.json"
    p.parent.mkdir(parents=True, exist_ok=True)

    for payload in ("[]", "null", '"oops"', "42"):
        p.write_text(payload, encoding="utf-8")
        data = state.load()
        assert isinstance(data, dict)
        assert data["left_pane_width"] == 280
        assert data["recent_files"] == []


def test_get_and_set_key(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert state.get("mode") == "read"
    state.set_key("mode", "source")
    assert state.get("mode") == "source"


def test_add_recent_prepends_and_deduplicates(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    state.add_recent("/a/b.md")
    state.add_recent("/c/d.md")
    state.add_recent("/a/b.md")  # duplicate — should move to front
    data = state.load()
    assert data["recent_files"] == ["/a/b.md", "/c/d.md"]


def test_add_recent_trims_to_max(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    for i in range(25):
        state.add_recent(f"/file{i}.md")
    data = state.load()
    assert len(data["recent_files"]) == 20
    assert data["recent_files"][0] == "/file24.md"


def test_state_path(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    p = state.state_path()
    assert p.name == "state.json"
    assert "mdvw" in str(p)


def test_save_ui_state_preserves_recent_files(tmp_path, monkeypatch):
    """The JS ``save_ui_state`` call carries only pane/mode fields. It
    must merge into the existing state — replacing the whole document
    wiped out ``recent_files`` and ``last_file`` on every pane resize or
    mode switch.
    """
    from mdvw.app import JsApi

    monkeypatch.setenv("APPDATA", str(tmp_path))
    # Seed persisted state the way run() does on launch.
    state.add_recent("/a/file1.md")
    state.set_key("last_file", "/a/file1.md")

    api = JsApi()
    # Payload shape matches what app.js:persistState() sends.
    api.save_ui_state({
        "left_pane_width": 350,
        "left_pane_collapsed": False,
        "left_pane_section": "files",
        "right_pane_width": 300,
        "right_pane_collapsed": True,
        "mode": "edit",
        "preview_narrow": False,
    })

    data = state.load()
    assert data["left_pane_width"] == 350
    assert data["mode"] == "edit"
    # Critical: unrelated keys survive.
    assert data["recent_files"] == ["/a/file1.md"]
    assert data["last_file"] == "/a/file1.md"
