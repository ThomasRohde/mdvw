from __future__ import annotations

from mdvw import app as app_mod


def test_preview_wiki_link_returns_heading_excerpt(tmp_path):
    index = tmp_path / "Index.md"
    note = tmp_path / "Note.md"
    index.write_text("[[Note#Details]]\n", encoding="utf-8")
    note.write_text(
        "# Note\n"
        "Intro text\n\n"
        "## Details\n"
        "alpha detail\n\n"
        "### Nested\n"
        "more detail\n\n"
        "## Later\n"
        "later detail\n",
        encoding="utf-8",
    )

    api = app_mod.JsApi()
    api._browse_root = tmp_path
    api._current_path = index

    result = api.preview_wiki_link("Note#Details")

    assert result["status"] == "ok"
    assert result["path"] == str(note.resolve())
    assert result["title"] == "Details"
    assert result["relative"] == "Note.md"
    assert "alpha detail" in result["html"]
    assert "more detail" in result["html"]
    assert "later detail" not in result["html"]


def test_preview_wiki_link_strips_frontmatter_from_excerpt(tmp_path):
    index = tmp_path / "Index.md"
    note = tmp_path / "Note.md"
    index.write_text("[[Note]]\n", encoding="utf-8")
    note.write_text(
        "---\n"
        "title: Hidden Title\n"
        "status: open\n"
        "---\n"
        "# Real Title\n\n"
        "First paragraph.\n",
        encoding="utf-8",
    )

    api = app_mod.JsApi()
    api._browse_root = tmp_path
    api._current_path = index

    result = api.preview_wiki_link("Note")

    assert result["status"] == "ok"
    assert result["title"] == "Real Title"
    assert "First paragraph." in result["html"]
    assert "Hidden Title" not in result["html"]
    assert "status: open" not in result["html"]


def test_preview_wiki_link_reports_unresolved_target(tmp_path):
    index = tmp_path / "Index.md"
    index.write_text("[[Ghost]]\n", encoding="utf-8")

    api = app_mod.JsApi()
    api._browse_root = tmp_path
    api._current_path = index

    result = api.preview_wiki_link("Ghost")

    assert result["status"] == "error"
    assert result["message"]
