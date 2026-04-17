"""Tests for the workspace search module."""

from __future__ import annotations

from pathlib import Path

from mdvw.search import search_workspace


def _make_files(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def test_basic_search(tmp_path):
    root = _make_files(tmp_path, {
        "a.md": "Hello world\nGoodbye world",
        "b.md": "No match here",
    })
    results = search_workspace(root, "world")
    assert len(results) == 2
    assert results[0]["name"] == "a.md"
    assert results[0]["line"] == 1
    assert results[1]["line"] == 2


def test_case_insensitive_default(tmp_path):
    root = _make_files(tmp_path, {"a.md": "HELLO world"})
    results = search_workspace(root, "hello")
    assert len(results) == 1


def test_case_sensitive(tmp_path):
    root = _make_files(tmp_path, {"a.md": "HELLO world"})
    results = search_workspace(root, "hello", case_sensitive=True)
    assert len(results) == 0


def test_skips_hidden_and_noise_dirs(tmp_path):
    root = _make_files(tmp_path, {
        "good.md": "target",
        ".hidden/bad.md": "target",
        "node_modules/bad.md": "target",
    })
    results = search_workspace(root, "target")
    assert len(results) == 1
    assert results[0]["name"] == "good.md"


def test_max_results(tmp_path):
    files = {f"f{i}.md": "match" for i in range(20)}
    root = _make_files(tmp_path, files)
    results = search_workspace(root, "match", max_results=5)
    assert len(results) == 5


def test_empty_query(tmp_path):
    root = _make_files(tmp_path, {"a.md": "content"})
    assert search_workspace(root, "") == []


def test_no_markdown_files(tmp_path):
    root = _make_files(tmp_path, {"a.txt": "hello"})
    assert search_workspace(root, "hello") == []


def test_result_fields(tmp_path):
    root = _make_files(tmp_path, {"sub/doc.md": "first\nsecond match here"})
    results = search_workspace(root, "match")
    assert len(results) == 1
    r = results[0]
    assert r["name"] == "doc.md"
    assert r["line"] == 2
    assert r["col"] == 8
    assert "match" in r["context"]
    assert "sub" in r["relative"]


def test_symlink_to_outside_root_is_ignored(tmp_path):
    """A symlinked .md inside the root that points to secrets outside the
    root must not be read through search_workspace — otherwise the browse
    root is not a real trust boundary.
    """
    import os

    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.md"
    secret.write_text("TOPSECRET leak", encoding="utf-8")

    inside = tmp_path / "inside"
    inside.mkdir()
    (inside / "legit.md").write_text("legit content", encoding="utf-8")
    link = inside / "sneaky.md"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):
        import pytest
        pytest.skip("symlink creation not permitted on this platform")

    results = search_workspace(inside, "TOPSECRET")
    assert results == []

    # Control: legit file in-root still searchable.
    assert search_workspace(inside, "legit")
