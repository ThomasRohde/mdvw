"""Document-facing regression tests for mdvw app behavior."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mdvw import app as app_mod
from mdvw import app_document as doc_mod


def test_script_tag_escaping_neutralizes_closing_tag():
    """<script> breakout: json.dumps alone leaves </script> unescaped."""
    malicious = "# Doc\n</script><script>alert('pwn')</script>\n"
    out = app_mod._build_html(malicious, None, False)
    source_tag = '<script type="application/json" id="md-source">'
    start = out.index(source_tag) + len(source_tag)
    end = out.index("</script>", start)
    embedded = out[start:end]
    assert "</script>" not in embedded
    assert "<script>" not in embedded
    assert "\\u003c" in embedded


def test_script_tag_escaping_handles_unicode_line_separators():
    """U+2028/U+2029 can break JS string literals even when HTML is fine."""
    src = "line1\u2028line2\u2029line3"
    out = app_mod._json_for_script_tag(src)
    assert "\u2028" not in out
    assert "\u2029" not in out
    assert "\\u2028" in out and "\\u2029" in out


def test_atomic_write_preserves_original_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "doc.md"
    target.write_text("ORIGINAL", encoding="utf-8")

    def boom(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(doc_mod.os, "replace", boom)
    with pytest.raises(OSError):
        app_mod._atomic_write_text(target, "NEW CONTENT")

    assert target.read_text(encoding="utf-8") == "ORIGINAL"
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_atomic_write_replaces_content(tmp_path):
    target = tmp_path / "doc.md"
    target.write_text("old", encoding="utf-8")
    app_mod._atomic_write_text(target, "new content with unicode: \u2603")
    assert target.read_text(encoding="utf-8") == "new content with unicode: \u2603"


def test_build_html_renders_frontmatter_card():
    source = "---\ntitle: Hello\nauthor: me\n---\n# Body\n"
    out = app_mod._build_html(source, None, False)
    assert 'class="md-frontmatter"' in out
    assert "title: Hello" in out
    assert "<p>title: Hello" not in out
    assert "<h1>Body</h1>" in out


def test_jsapi_render_markdown_includes_frontmatter_card():
    api = app_mod.JsApi()
    html = api.render_markdown("---\nkey: val\n---\nhello\n")
    assert "md-frontmatter" in html
    assert "key: val" in html
    assert "<p>hello</p>" in html


def test_jsapi_render_markdown_shows_yaml_error():
    api = app_mod.JsApi()
    html = api.render_markdown("---\ntitle: [bad\n---\nstill body\n")
    assert "md-frontmatter--error" in html
    assert "still body" in html


def test_parse_frontmatter_fields_is_json_serializable():
    import json

    api = app_mod.JsApi()
    fields = api.parse_frontmatter_fields(
        "---\ntitle: T\ndate: 2026-04-15\n---\nbody\n"
    )
    assert fields is not None
    json.dumps(fields)
    assert fields["title"] == "T"
    assert fields["date"] == "2026-04-15"


def test_save_file_roundtrips_frontmatter_verbatim(tmp_path):
    """Editing the body must not mangle the user's YAML whitespace/quoting."""
    api = app_mod.JsApi()
    api._current_path = tmp_path / "doc.md"
    source = "---\ntitle:   Hi   \ntags:\n  - one\n  - two\n---\n# Body\n"
    result = api.save_file(source)
    assert result["status"] == "ok"
    assert result["path"] == str(tmp_path / "doc.md")
    assert result["name"] == "doc.md"
    assert result["new_file"] is False
    assert (tmp_path / "doc.md").read_text(encoding="utf-8") == source


def test_save_file_without_window_returns_cancelled():
    """With no _window, save_file of a new doc must fail gracefully, not raise."""
    api = app_mod.JsApi()
    assert api.save_file("anything") == {"status": "cancelled"}


def test_save_file_new_document_returns_saved_path(tmp_path, monkeypatch):
    from mdvw import state

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    api = app_mod.JsApi()
    target = tmp_path / "New Note.md"
    api._window = MagicMock()
    api._window.create_file_dialog.return_value = (str(target),)

    result = api.save_file("# New Note\n")

    assert result == {
        "status": "ok",
        "path": str(target),
        "name": "New Note.md",
        "new_file": True,
    }
    assert target.read_text(encoding="utf-8") == "# New Note\n"
    assert api._current_path == target
    assert state.get("recent_files") == [str(target)]
    assert state.get("last_file") == str(target)


def test_save_file_writes_when_current_path_set(tmp_path):
    api = app_mod.JsApi()
    api._current_path = tmp_path / "out.md"
    result = api.save_file("hello")
    assert result["status"] == "ok"
    assert result["path"] == str(tmp_path / "out.md")
    assert result["name"] == "out.md"
    assert result["new_file"] is False
    assert (tmp_path / "out.md").read_text(encoding="utf-8") == "hello"


def test_save_conflict_detected_when_disk_mutates(tmp_path):
    """External edit between load and save must block the overwrite."""
    p = tmp_path / "doc.md"
    p.write_text("loaded content\n", encoding="utf-8")
    api = app_mod.JsApi()
    api._current_path = p
    api._loaded_fingerprint = app_mod._fingerprint(p)

    import time
    time.sleep(0.01)
    p.write_text("external edits\n" + "X" * 100, encoding="utf-8")

    result = api.save_file("my edits")
    assert result == {"status": "conflict"}
    assert "external edits" in p.read_text(encoding="utf-8")


def test_save_conflict_force_overwrites(tmp_path):
    """After user confirms overwrite, force=True must bypass the check."""
    p = tmp_path / "doc.md"
    p.write_text("original\n", encoding="utf-8")
    api = app_mod.JsApi()
    api._current_path = p
    api._loaded_fingerprint = app_mod._fingerprint(p)

    import time
    time.sleep(0.01)
    p.write_text("external changes\n", encoding="utf-8")

    result = api.save_file("my edits", force=True)
    assert result["status"] == "ok"
    assert result["path"] == str(p)
    assert p.read_text(encoding="utf-8") == "my edits"
    assert api._loaded_fingerprint == app_mod._fingerprint(p)


def test_save_fingerprint_refreshes_after_ok(tmp_path):
    """A normal save updates the baseline so subsequent saves don't falsely conflict."""
    p = tmp_path / "doc.md"
    p.write_text("v0\n", encoding="utf-8")
    api = app_mod.JsApi()
    api._current_path = p
    api._loaded_fingerprint = app_mod._fingerprint(p)

    assert api.save_file("v1")["status"] == "ok"
    assert api.save_file("v2")["status"] == "ok"
    assert p.read_text(encoding="utf-8") == "v2"


def test_load_records_fingerprint(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("hello", encoding="utf-8")
    api = app_mod.JsApi()
    api._window = MagicMock()
    api._load(p)
    assert api._loaded_fingerprint == app_mod._fingerprint(p)


def test_load_emits_reason_in_payload(tmp_path):
    """External reloads must tag the payload so JS can prompt on dirty edits."""
    api = app_mod.JsApi()
    api._window = MagicMock()
    src = tmp_path / "doc.md"
    src.write_text("# hi", encoding="utf-8")

    api._load(src, reason="watch")
    call = api._window.evaluate_js.call_args[0][0]
    assert '"reason": "watch"' in call

    api._load(src, reason="open")
    call = api._window.evaluate_js.call_args[0][0]
    assert '"reason": "open"' in call


def test_build_html_rewrites_app_assets_to_absolute():
    """App assets must become absolute URLs, NOT a document-wide <base>."""
    html = app_mod._build_html("hi", None, False, assets_base="file:///x/y/")
    assert "<base" not in html
    assert 'href="file:///x/y/app.css"' in html
    assert 'href="file:///x/y/vendor/katex/katex.min.css"' in html
    assert 'src="file:///x/y/vendor/mermaid/mermaid.min.js"' in html


def test_build_html_without_base_unchanged():
    html = app_mod._build_html("hi", None, False)
    assert "<base" not in html
    assert 'href="app.css"' in html


def test_id_attribute_stripped_from_user_content():
    """A hostile markdown file must not shadow reserved bootstrap ids."""
    from mdvw.render import render_markdown

    hostile = '<div id="md-source">stolen</div>\n<div id="md-path">/etc/passwd</div>\n'
    html = render_markdown(hostile)
    assert 'id="md-source"' not in html
    assert 'id="md-path"' not in html
    assert "stolen" in html


def test_render_strips_file_links():
    """The sanitizer drops file: as an <a href> scheme."""
    from mdvw.render import render_markdown

    html = render_markdown("[click](file:///C:/Windows/System32/calc.exe)")
    assert 'href="file:' not in html
    assert "<a " not in html or "file:" not in html


def test_watch_reload_guards_dirty_regardless_of_mode():
    """Python tags watched reloads so JS can guard dirty buffers."""
    api = app_mod.JsApi()
    api._window = MagicMock()
    import tempfile
    from pathlib import Path as _Path

    with tempfile.TemporaryDirectory() as td:
        p = _Path(td) / "doc.md"
        p.write_text("external", encoding="utf-8")
        api._load(p, reason="watch")
    call = api._window.evaluate_js.call_args[0][0]
    assert '"reason": "watch"' in call


def test_rejected_watch_reload_preserves_conflict_baseline(tmp_path):
    """Rejecting a watched reload must keep the old save-conflict baseline."""
    p = tmp_path / "doc.md"
    p.write_text("v0\n", encoding="utf-8")

    api = app_mod.JsApi()
    api._window = MagicMock()
    api._load(p, reason="open")
    baseline = api._loaded_fingerprint
    assert baseline is not None

    import time
    time.sleep(0.01)
    p.write_text("external new\n" + "X" * 50, encoding="utf-8")

    api._load(p, reason="watch")
    assert api._loaded_fingerprint == baseline
    assert api._pending_fingerprint is not None
    assert api._pending_fingerprint != baseline

    result = api.save_file("my edits")
    assert result == {"status": "conflict"}
    assert "external new" in p.read_text(encoding="utf-8")


def test_accepted_watch_reload_advances_baseline(tmp_path):
    """Accepting a watched reload advances the save baseline."""
    p = tmp_path / "doc.md"
    p.write_text("v0\n", encoding="utf-8")
    api = app_mod.JsApi()
    api._window = MagicMock()
    api._load(p, reason="open")

    import time
    time.sleep(0.01)
    p.write_text("v1\n", encoding="utf-8")
    api._load(p, reason="watch")

    assert api.ack_reload() is True
    assert api._loaded_fingerprint == app_mod._fingerprint(p)
    assert api._pending_fingerprint is None
    assert api.save_file("v2")["status"] == "ok"


def test_protocol_relative_img_src_stripped():
    """Protocol-relative and absolute image URLs must be rejected."""
    from mdvw.render import render_markdown

    for url in (
        "//attacker.example/pixel.png",
        "\\\\server\\share\\file.png",
        "/absolute/path.png",
        "\x01//attacker.example/evil.png",
        "  //attacker.example/evil.png",
    ):
        html = render_markdown(f'<img src="{url}">')
        assert f'src="{url}"' not in html, f"unsafe img src not stripped: {url!r}"


def test_data_uri_img_src_allowed():
    from mdvw.render import render_markdown

    tiny = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
    html = render_markdown(f'<img src="{tiny}">')
    assert tiny in html


def test_relative_paths_rewritten_against_doc_base():
    from mdvw.render import render_markdown

    html = render_markdown(
        "![d](./diagram.png)\n\n[next](other.md)",
        doc_base="file:///C:/notes/",
    )
    assert 'src="file:///C:/notes/./diagram.png"' in html or \
           'src="file:///C:/notes/diagram.png"' in html or \
           'file:///C:/notes/' in html
    assert 'href="file:///C:/notes/other.md"' in html


def test_remote_img_src_stripped():
    """Remote http(s) image URLs must be stripped."""
    from mdvw.render import render_markdown

    for url in ("https://evil.example/pixel.gif", "http://tracker.example/p"):
        html = render_markdown(f"![x]({url})")
        assert url not in html, f"remote img src not stripped: {html}"
        assert 'src="http' not in html


def test_local_and_data_img_src_allowed():
    """Relative paths and data: URIs stay."""
    from mdvw.render import render_markdown

    html = render_markdown("![x](./diagram.png)")
    assert 'src="./diagram.png"' in html or 'src="./diagram.png"' in html
    tiny = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    html2 = render_markdown(f"![x]({tiny})")
    assert "data:image/png;base64," in html2


def test_export_html_preserves_existing_file_on_failure(tmp_path, monkeypatch):
    """Export failing mid-write must not truncate a pre-existing target file."""
    existing = tmp_path / "report.html"
    existing.write_text("ORIGINAL HTML", encoding="utf-8")

    api = app_mod.JsApi()
    api._window = MagicMock()
    api._window.create_file_dialog.return_value = (str(existing),)

    def boom(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(doc_mod.os, "replace", boom)

    result = api.export_html("# hello\n")
    assert result["status"] == "error"
    assert existing.read_text(encoding="utf-8") == "ORIGINAL HTML"
    assert [p for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []


def test_export_html_writes_when_target_is_new(tmp_path):
    api = app_mod.JsApi()
    api._window = MagicMock()
    target = tmp_path / "out.html"
    api._window.create_file_dialog.return_value = (str(target),)

    result = api.export_html("# hello\n")
    assert result == {"status": "ok", "path": str(target)}
    assert "<h1>hello</h1>" in target.read_text(encoding="utf-8")


def test_export_html_accepts_bare_string_return(tmp_path):
    """Some pywebview backends still hand back a bare string."""
    api = app_mod.JsApi()
    api._window = MagicMock()
    target = tmp_path / "out.html"
    api._window.create_file_dialog.return_value = str(target)

    result = api.export_html("# hello\n")
    assert result == {"status": "ok", "path": str(target)}
    assert target.exists()


def test_save_image_writes_and_returns_relative_path(tmp_path):
    import base64

    doc = tmp_path / "note.md"
    doc.write_text("# hi", encoding="utf-8")
    api = app_mod.JsApi()
    api._current_path = doc
    api._window = MagicMock()

    raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    data_url = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    result = api.save_image(data_url, "pasted.png")

    assert result["status"] == "ok"
    rel = result["relative_path"]
    assert rel.startswith("images/")
    target = tmp_path / rel
    assert target.read_bytes() == raw


def test_save_image_rejects_oversized_payload(tmp_path):
    doc = tmp_path / "note.md"
    doc.write_text("# hi", encoding="utf-8")
    api = app_mod.JsApi()
    api._current_path = doc

    oversize = "A" * (api._IMAGE_MAX_DECODED_BYTES * 2)
    data_url = f"data:image/png;base64,{oversize}"
    result = api.save_image(data_url, "huge.png")

    assert result == {"status": "error", "message": "Image too large"}
    images_dir = tmp_path / "images"
    if images_dir.exists():
        assert list(images_dir.iterdir()) == []


def test_save_image_rejects_oversized_after_decode(tmp_path):
    """Enforce the cap on decoded bytes too."""
    import base64

    doc = tmp_path / "note.md"
    doc.write_text("# hi", encoding="utf-8")
    api = app_mod.JsApi()
    api._current_path = doc
    api._IMAGE_MAX_DECODED_BYTES = 1024  # type: ignore[misc]

    raw = b"X" * 2000
    data_url = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    result = api.save_image(data_url, "big.png")

    assert result == {"status": "error", "message": "Image too large"}


def test_save_image_rejects_invalid_base64(tmp_path):
    doc = tmp_path / "note.md"
    doc.write_text("# hi", encoding="utf-8")
    api = app_mod.JsApi()
    api._current_path = doc

    data_url = "data:image/png;base64,!!!not-base64!!!"
    result = api.save_image(data_url, "bad.png")

    assert result == {"status": "error", "message": "Invalid image data"}


def test_save_image_atomic_leaves_nothing_on_replace_failure(
    tmp_path, monkeypatch,
):
    """A failed write must not leave a half-written attachment or stray tmp file."""
    import base64

    doc = tmp_path / "note.md"
    doc.write_text("# hi", encoding="utf-8")
    api = app_mod.JsApi()
    api._current_path = doc

    def boom(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(doc_mod.os, "replace", boom)

    raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    data_url = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    result = api.save_image(data_url, "pasted.png")

    assert result["status"] == "error"
    images_dir = tmp_path / "images"
    leftover = list(images_dir.iterdir()) if images_dir.exists() else []
    assert leftover == []
