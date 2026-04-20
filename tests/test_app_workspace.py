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


def test_jsapi_get_workspace_tasks_filters_done_by_default(tmp_path):
    note = tmp_path / "Tasks.md"
    note.write_text(
        "# Inbox\n"
        "- [ ] open task\n"
        "- [x] done task\n",
        encoding="utf-8",
    )

    api = app_mod.JsApi()
    api._browse_root = tmp_path

    open_tasks = api.get_workspace_tasks()
    all_tasks = api.get_workspace_tasks(include_done=True)

    assert [task["text"] for task in open_tasks] == ["open task"]
    assert [task["text"] for task in all_tasks] == ["open task", "done task"]


def test_jsapi_toggle_workspace_task_updates_file(tmp_path):
    note = tmp_path / "Tasks.md"
    note.write_text("- [ ] open task\n", encoding="utf-8")

    api = app_mod.JsApi()
    api._browse_root = tmp_path

    result = api.toggle_workspace_task(str(note), 1)

    assert result["status"] == "ok"
    assert result["checked"] is True
    assert note.read_text(encoding="utf-8") == "- [x] open task\n"


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
    js = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "mdvw"
        / "assets"
        / "app"
        / "05-graph.js"
    ).read_text(encoding="utf-8")
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


def test_jsapi_get_note_templates_lists_markdown_files(tmp_path):
    templates = tmp_path / "Templates"
    templates.mkdir()
    (templates / "Meeting.md").write_text("# meeting", encoding="utf-8")
    (templates / "nested").mkdir()
    (templates / "nested" / "Daily.markdown").write_text("# daily", encoding="utf-8")
    (templates / "notes.txt").write_text("x", encoding="utf-8")

    api = app_mod.JsApi()
    api._browse_root = tmp_path

    result = api.get_note_templates()

    assert result == [
        {
            "name": "Meeting",
            "relative": "Meeting.md",
            "path": str((templates / "Meeting.md").resolve()),
        },
        {
            "name": "Daily",
            "relative": "nested/Daily.markdown",
            "path": str((templates / "nested" / "Daily.markdown").resolve()),
        },
    ]


def test_jsapi_create_note_uses_template_placeholders(tmp_path):
    current = tmp_path / "notes" / "Inbox.md"
    current.parent.mkdir()
    current.write_text("# Inbox\n", encoding="utf-8")
    templates = tmp_path / "Templates"
    templates.mkdir()
    (templates / "Meeting.md").write_text(
        "---\n"
        "title: {{title}}\n"
        "slug: {{slug}}\n"
        "path: {{path}}\n"
        "---\n"
        "# {{title}}\n",
        encoding="utf-8",
    )

    api = app_mod.JsApi()
    api._browse_root = tmp_path
    api._current_path = current
    api._window = MagicMock()

    result = api.create_note("Projects/Weekly Review", "Meeting.md")

    created = tmp_path / "notes" / "Projects" / "Weekly Review.md"
    assert result["status"] == "created"
    assert created.read_text(encoding="utf-8") == (
        "---\n"
        "title: Weekly Review\n"
        "slug: weekly-review\n"
        "path: notes/Projects/Weekly Review.md\n"
        "---\n"
        "# Weekly Review\n"
    )
    assert api._current_path == created.resolve()


def test_jsapi_open_daily_note_creates_daily_file_from_template(tmp_path):
    templates = tmp_path / "Templates"
    templates.mkdir()
    (templates / "Daily.md").write_text(
        "# {{title}}\n"
        "Date: {{date}}\n"
        "Path: {{path}}\n",
        encoding="utf-8",
    )

    api = app_mod.JsApi()
    api._browse_root = tmp_path
    api._window = MagicMock()

    result = api.open_daily_note("2026-04-20")

    created = tmp_path / "Daily" / "2026-04-20.md"
    assert result["status"] == "created"
    assert created.read_text(encoding="utf-8") == (
        "# 2026-04-20\n"
        "Date: 2026-04-20\n"
        "Path: Daily/2026-04-20.md\n"
    )
    assert api._current_path == created.resolve()


def test_note_commands_and_dialog_are_wired():
    root = Path(__file__).resolve().parents[1] / "src" / "mdvw" / "assets"
    shell_js = (root / "app" / "02-shell.js").read_text(encoding="utf-8")
    doc_js = (root / "app" / "07-document.js").read_text(encoding="utf-8")
    template = (root / "template.html").read_text(encoding="utf-8")

    assert "registerCommand('note.new'" in shell_js
    assert "registerCommand('note.new_template'" in shell_js
    assert "registerCommand('note.daily'" in shell_js
    assert "registerCommand('note.rename'" in shell_js
    assert "async function openNoteCreateDialog" in doc_js
    assert "async function openDailyNote" in doc_js
    assert "async function openNoteMoveDialog" in doc_js
    assert 'id="note-create-dialog"' in template
    assert 'id="note-move-dialog"' in template


def test_wiki_hover_preview_is_wired():
    root = Path(__file__).resolve().parents[1] / "src" / "mdvw" / "assets"
    doc_js = (root / "app" / "07-document.js").read_text(encoding="utf-8")
    overlay_css = (root / "app" / "04-overlays.css").read_text(encoding="utf-8")
    template = (root / "template.html").read_text(encoding="utf-8")

    assert "api.preview_wiki_link" in doc_js
    assert "function showWikiPreview" in doc_js
    assert 'id="wiki-hover-preview"' in template
    assert ".wiki-preview" in overlay_css
    assert "pointer-events: none;" in overlay_css


def test_task_pane_and_command_are_wired():
    root = Path(__file__).resolve().parents[1] / "src" / "mdvw" / "assets"
    shell_js = (root / "app" / "02-shell.js").read_text(encoding="utf-8")
    workspace_js = (root / "app" / "04-workspace.js").read_text(encoding="utf-8")
    template = (root / "template.html").read_text(encoding="utf-8")

    assert "registerCommand('pane.tasks'" in shell_js
    assert "async function loadTasks()" in workspace_js
    assert "api.toggle_workspace_task" in workspace_js
    assert 'data-section="tasks"' in template
    assert 'id="tasks-list"' in template


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
