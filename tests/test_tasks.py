"""Tests for the workspace task module."""

from __future__ import annotations

from pathlib import Path

from mdvw.tasks import list_workspace_tasks, parse_markdown_tasks, toggle_workspace_task


def _make_files(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


def test_parse_markdown_tasks_tracks_heading_and_done_items():
    text = (
        "# Inbox\n"
        "- [ ] first task\n"
        "- [x] done task\n"
        "## Later\n"
        "1. [ ] ordered task\n"
    )

    tasks = parse_markdown_tasks(text, include_done=True)

    assert tasks == [
        {
            "line": 2,
            "checked": False,
            "text": "first task",
            "heading": "Inbox",
            "context": "- [ ] first task",
        },
        {
            "line": 3,
            "checked": True,
            "text": "done task",
            "heading": "Inbox",
            "context": "- [x] done task",
        },
        {
            "line": 5,
            "checked": False,
            "text": "ordered task",
            "heading": "Later",
            "context": "1. [ ] ordered task",
        },
    ]


def test_parse_markdown_tasks_skips_fenced_code_blocks():
    text = (
        "# Note\n"
        "```md\n"
        "- [ ] not a real task\n"
        "```\n"
        "- [ ] real task\n"
    )

    tasks = parse_markdown_tasks(text)

    assert [task["text"] for task in tasks] == ["real task"]


def test_list_workspace_tasks_filters_done_and_skips_noise_dirs(tmp_path):
    root = _make_files(tmp_path, {
        "good.md": "# Inbox\n- [ ] keep me\n- [x] done\n",
        ".hidden/skip.md": "- [ ] hidden\n",
        "node_modules/skip.md": "- [ ] noise\n",
    })

    tasks = list_workspace_tasks(root)

    assert tasks == [
        {
            "path": str((root / "good.md").resolve()),
            "name": "good.md",
            "relative": "good.md",
            "line": 2,
            "checked": False,
            "text": "keep me",
            "heading": "Inbox",
            "context": "- [ ] keep me",
        },
    ]


def test_list_workspace_tasks_ignores_symlink_to_outside_root(tmp_path):
    import os

    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.md"
    secret.write_text("- [ ] TOPSECRET", encoding="utf-8")

    inside = tmp_path / "inside"
    inside.mkdir()
    (inside / "legit.md").write_text("- [ ] legit", encoding="utf-8")
    link = inside / "sneaky.md"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):
        import pytest

        pytest.skip("symlink creation not permitted on this platform")

    tasks = list_workspace_tasks(inside)

    assert len(tasks) == 1
    assert tasks[0]["text"] == "legit"


def test_toggle_workspace_task_updates_marker_in_place(tmp_path):
    note = tmp_path / "Tasks.md"
    note.write_bytes(
        b"# Inbox\r\n- [ ] open task\r\n- [x] done task\r\n",
    )

    result = toggle_workspace_task(tmp_path, str(note), 2)

    assert result == {
        "status": "ok",
        "path": str(note.resolve()),
        "line": 2,
        "checked": True,
        "text": "open task",
    }
    assert note.read_bytes() == b"# Inbox\r\n- [x] open task\r\n- [x] done task\r\n"
