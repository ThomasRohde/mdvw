"""Workspace and wiki-link regression tests for mdvw app behavior."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from mdvw import app as app_mod


def test_open_file_without_window_returns_false():
    api = app_mod.JsApi()
    assert api.open_file() is False


def test_open_directory_without_window_returns_false():
    api = app_mod.JsApi()
    assert api.open_directory() is False


def test_open_directory_happy_path(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    api = app_mod.JsApi()
    api._window = MagicMock()
    api._window.create_file_dialog.return_value = (str(workspace),)

    assert api.open_directory() is True
    assert api._browse_root == workspace.resolve()

    from mdvw import state

    assert state.get("last_browse_root") == str(workspace.resolve())

    call = api._window.evaluate_js.call_args[0][0]
    assert "mdvwBrowseRootChanged" in call
    assert json.dumps(str(workspace.resolve()))[1:-1] in call


def test_open_directory_accepts_bare_string_return(tmp_path, monkeypatch):
    """Backend drift: some pywebview builds return a bare string."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    api = app_mod.JsApi()
    api._window = MagicMock()
    api._window.create_file_dialog.return_value = str(workspace)

    assert api.open_directory() is True
    assert api._browse_root == workspace.resolve()


def test_open_directory_user_cancels_leaves_state_untouched(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    original_root = tmp_path / "original"
    original_root.mkdir()

    api = app_mod.JsApi()
    api._browse_root = original_root
    api._window = MagicMock()
    api._window.create_file_dialog.return_value = ()

    assert api.open_directory() is False
    assert api._browse_root == original_root
    assert api._window.evaluate_js.call_count == 0

    from mdvw import state

    assert state.get("last_browse_root") is None


def test_open_directory_rejects_nonexistent_path(tmp_path, monkeypatch):
    """Defense-in-depth: bogus dialog return values must not mutate browse root."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    original_root = tmp_path / "original"
    original_root.mkdir()
    bogus = tmp_path / "does-not-exist"

    api = app_mod.JsApi()
    api._browse_root = original_root
    api._window = MagicMock()
    api._window.create_file_dialog.return_value = (str(bogus),)

    assert api.open_directory() is False
    assert api._browse_root == original_root
    assert api._window.evaluate_js.call_count == 0


def test_list_markdown_dir_none_without_browse_root():
    api = app_mod.JsApi()
    assert api.list_markdown_dir() is None


def test_list_markdown_dir_root_filters_and_sorts(tmp_path):
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "B.markdown").write_text("b", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("no", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "zz_later").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / "node_modules").mkdir()

    api = app_mod.JsApi()
    api._browse_root = tmp_path
    result = api.list_markdown_dir("")
    assert result is not None
    names = [e["name"] for e in result["entries"]]
    types = {e["name"]: e["type"] for e in result["entries"]}
    assert ".git" not in names and "node_modules" not in names
    assert "notes.txt" not in names
    assert names == ["sub", "zz_later", "a.md", "B.markdown"]
    assert types["sub"] == "dir" and types["a.md"] == "file"


def test_list_markdown_dir_loads_subdir_lazily(tmp_path):
    sub = tmp_path / "docs"
    sub.mkdir()
    (sub / "intro.md").write_text("i", encoding="utf-8")
    api = app_mod.JsApi()
    api._browse_root = tmp_path
    result = api.list_markdown_dir(str(sub))
    assert result is not None
    assert [e["name"] for e in result["entries"]] == ["intro.md"]


def test_list_markdown_dir_rejects_outside_root(tmp_path):
    inside = tmp_path / "inside"
    inside.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    api = app_mod.JsApi()
    api._browse_root = inside
    assert api.list_markdown_dir(str(outside)) is None


def test_list_markdown_dir_rejects_traversal(tmp_path):
    inside = tmp_path / "inside"
    inside.mkdir()
    api = app_mod.JsApi()
    api._browse_root = inside
    assert api.list_markdown_dir(str(inside / "..")) is None


def test_open_path_rejects_outside_root(tmp_path):
    inside = tmp_path / "inside"
    inside.mkdir()
    (inside / "ok.md").write_text("ok", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("no", encoding="utf-8")

    api = app_mod.JsApi()
    api._browse_root = inside
    api._window = MagicMock()

    assert api.open_path(str(outside)) is False
    assert api._window.evaluate_js.call_count == 0


def test_open_path_rejects_traversal(tmp_path):
    inside = tmp_path / "inside"
    inside.mkdir()
    (tmp_path / "secret.md").write_text("x", encoding="utf-8")

    api = app_mod.JsApi()
    api._browse_root = inside
    api._window = MagicMock()

    traversal = str(inside / ".." / "secret.md")
    assert api.open_path(traversal) is False
    assert api._window.evaluate_js.call_count == 0


def test_open_path_rejects_non_markdown_suffix(tmp_path):
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    api = app_mod.JsApi()
    api._browse_root = tmp_path
    api._window = MagicMock()

    assert api.open_path(str(tmp_path / "notes.txt")) is False
    assert api._window.evaluate_js.call_count == 0


def test_open_path_loads_valid_in_root_file(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# hi", encoding="utf-8")
    api = app_mod.JsApi()
    api._browse_root = tmp_path
    api._window = MagicMock()

    assert api.open_path(str(doc)) is True
    assert api._current_path == doc.resolve()
    call = api._window.evaluate_js.call_args[0][0]
    assert '"reason": "open"' in call
    assert '"name": "doc.md"' in call


def test_jsapi_resolve_wiki_link(tmp_path):
    index = tmp_path / "Index.md"
    note = tmp_path / "Note.md"
    index.write_text("[[Note#Details]]", encoding="utf-8")
    note.write_text("# Note\n## Details\n", encoding="utf-8")

    api = app_mod.JsApi()
    api._browse_root = tmp_path
    api._current_path = index

    result = api.resolve_wiki_link("Note#Details")

    assert result["status"] == "ok"
    assert result["path"] == str(note.resolve())
    assert result["heading"] == "Details"


def test_jsapi_incoming_links(tmp_path):
    target = tmp_path / "Target.md"
    source = tmp_path / "Source.md"
    target.write_text("# Target\n", encoding="utf-8")
    source.write_text("[[Target]]", encoding="utf-8")

    api = app_mod.JsApi()
    api._browse_root = tmp_path
    api._current_path = target

    incoming = api.get_incoming_links()

    assert len(incoming) == 1
    assert incoming[0]["source_path"] == str(source.resolve())
    assert incoming[0]["raw"] == "Target"


def test_jsapi_get_graph_defaults_to_local_with_current_note(tmp_path):
    current = tmp_path / "Index.md"
    target = tmp_path / "Target.md"
    current.write_text("[[Target]]", encoding="utf-8")
    target.write_text("# Target\n", encoding="utf-8")

    api = app_mod.JsApi()
    api._browse_root = tmp_path
    api._current_path = current

    graph = api.get_graph({})

    assert graph["stats"]["mode"] == "local"
    assert {node["id"] for node in graph["nodes"]} == {"Index.md", "Target.md"}
    assert graph["edges"][0]["status"] == "ok"


def test_jsapi_get_graph_returns_empty_without_workspace():
    api = app_mod.JsApi()

    graph = api.get_graph({"mode": "local"})

    assert graph["nodes"] == []
    assert graph["edges"] == []
    assert graph["stats"]["message"] == "No workspace"


def test_graph_click_only_creates_missing_unresolved_nodes():
    js = (Path(__file__).resolve().parents[1] / "src" / "mdvw" / "assets" / "app.js").read_text(
        encoding="utf-8"
    )
    function_start = js.index("async function openGraphNode(node)")
    create_note = js.index("const result = await api.create_wiki_note", function_start)
    missing_gate = js.index("node.status !== 'missing'", function_start)

    assert missing_gate < create_note


def test_jsapi_create_wiki_note_current_folder(tmp_path):
    current = tmp_path / "notes" / "Index.md"
    current.parent.mkdir()
    current.write_text("[[New Note]]", encoding="utf-8")

    api = app_mod.JsApi()
    api._browse_root = tmp_path
    api._current_path = current
    api._window = MagicMock()

    result = api.create_wiki_note("New Note")

    created = tmp_path / "notes" / "New Note.md"
    assert result["status"] == "created"
    assert result["path"] == str(created.resolve())
    assert result["name"] == "New Note.md"
    assert result["new_file"] is True
    assert created.is_file()
    assert api._current_path == created.resolve()


def test_jsapi_create_wiki_note_sanitizes_traversal(tmp_path):
    current = tmp_path / "Index.md"
    current.write_text("", encoding="utf-8")

    api = app_mod.JsApi()
    api._browse_root = tmp_path
    api._current_path = current
    api._window = MagicMock()

    result = api.create_wiki_note("../../Secret")

    assert result["status"] == "created"
    assert (tmp_path / "Secret.md").is_file()
    assert not (tmp_path.parent / "Secret.md").exists()


def test_open_recent_loads_file_outside_browse_root(tmp_path, monkeypatch):
    """Recent files span workspaces but remain allowlisted."""
    from mdvw import state

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    inside = tmp_path / "inside"
    inside.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("# elsewhere", encoding="utf-8")
    state.add_recent(str(outside.resolve()))

    api = app_mod.JsApi()
    api._browse_root = inside
    api._window = MagicMock()

    assert api.open_recent(str(outside)) is True
    assert api._current_path == outside.resolve()


def test_open_recent_rejects_non_markdown_suffix(tmp_path, monkeypatch):
    from mdvw import state

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    target = tmp_path / "notes.txt"
    target.write_text("x", encoding="utf-8")
    state.add_recent(str(target.resolve()))

    api = app_mod.JsApi()
    api._browse_root = tmp_path
    api._window = MagicMock()

    assert api.open_recent(str(target)) is False
    assert api._window.evaluate_js.call_count == 0


def test_open_recent_rejects_missing_file(tmp_path, monkeypatch):
    from mdvw import state

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    ghost = tmp_path / "ghost.md"
    state.add_recent(str(ghost.resolve()))

    api = app_mod.JsApi()
    api._browse_root = tmp_path
    api._window = MagicMock()

    assert api.open_recent(str(ghost)) is False
    assert api._window.evaluate_js.call_count == 0


def test_open_recent_rejects_empty_or_non_string():
    api = app_mod.JsApi()
    api._window = MagicMock()

    assert api.open_recent("") is False
    assert api.open_recent(None) is False  # type: ignore[arg-type]
    assert api._window.evaluate_js.call_count == 0


def test_save_ui_state_cannot_poison_recent_files_allowlist(
    tmp_path, monkeypatch,
):
    """The renderer must not be able to poison trusted state keys."""
    from mdvw import state

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    secret = tmp_path / "secret.md"
    secret.write_text("# secret", encoding="utf-8")

    api = app_mod.JsApi()
    api._browse_root = tmp_path
    api._window = MagicMock()

    api.save_ui_state({
        "recent_files": [str(secret.resolve())],
        "last_file": str(secret.resolve()),
        "last_browse_root": str(tmp_path),
        "left_pane_width": 333,
    })

    data = state.load()
    assert data["recent_files"] == []
    assert data["last_file"] is None
    assert data["last_browse_root"] is None
    assert data["left_pane_width"] == 333

    assert api.open_recent(str(secret)) is False
    assert api._window.evaluate_js.call_count == 0


def test_save_ui_state_rejects_wrong_types(tmp_path, monkeypatch):
    """Schema enforcement: wrong types are dropped, not coerced."""
    from mdvw import state

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    api = app_mod.JsApi()
    api.save_ui_state({
        "left_pane_width": "350",
        "left_pane_collapsed": 1,
        "mode": "edit",
        "preview_narrow": True,
    })
    data = state.load()
    assert data["left_pane_width"] == 280
    assert data["left_pane_collapsed"] is False
    assert data["mode"] == "edit"
    assert data["preview_narrow"] is True


def test_open_recent_rejects_path_not_in_allowlist(tmp_path, monkeypatch):
    """Only persisted recent-file entries are openable through open_recent."""
    from mdvw import state

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    listed = tmp_path / "listed.md"
    listed.write_text("# ok", encoding="utf-8")
    unlisted = tmp_path / "secret.md"
    unlisted.write_text("# secret", encoding="utf-8")
    state.add_recent(str(listed.resolve()))

    api = app_mod.JsApi()
    api._browse_root = tmp_path
    api._window = MagicMock()

    assert api.open_recent(str(unlisted)) is False
    assert api._window.evaluate_js.call_count == 0
    assert api.open_recent(str(listed)) is True
