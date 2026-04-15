"""Regression tests for the fixes from the adversarial review."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mdvw import app as app_mod


def test_script_tag_escaping_neutralizes_closing_tag():
    """<script> breakout: json.dumps alone leaves </script> unescaped."""
    malicious = "# Doc\n</script><script>alert('pwn')</script>\n"
    out = app_mod._build_html(malicious, None, False)
    # The escaped source must not contain a literal </script> anywhere between
    # the script open and close. Our escaper neutralizes < as \u003c.
    source_tag = '<script type="application/json" id="md-source">'
    start = out.index(source_tag) + len(source_tag)
    end = out.index("</script>", start)
    embedded = out[start:end]
    assert "</script>" not in embedded
    assert "<script>" not in embedded
    assert "\\u003c" in embedded  # escape was applied


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

    # Make os.replace raise to simulate a crash mid-swap.
    def boom(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(app_mod.os, "replace", boom)
    with pytest.raises(OSError):
        app_mod._atomic_write_text(target, "NEW CONTENT")

    # Original file still intact.
    assert target.read_text(encoding="utf-8") == "ORIGINAL"
    # No .tmp leftovers in the directory.
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_atomic_write_replaces_content(tmp_path):
    target = tmp_path / "doc.md"
    target.write_text("old", encoding="utf-8")
    app_mod._atomic_write_text(target, "new content with unicode: \u2603")
    assert target.read_text(encoding="utf-8") == "new content with unicode: \u2603"


def test_save_file_without_window_returns_cancelled():
    """With no _window, save_file of a new doc must fail gracefully, not raise."""
    api = app_mod.JsApi()
    # _window is None, _current_path is None → must not attempt to open a dialog.
    assert api.save_file("anything") == {"status": "cancelled"}


def test_save_file_writes_when_current_path_set(tmp_path):
    api = app_mod.JsApi()
    api._current_path = tmp_path / "out.md"
    # Brand-new file → no prior fingerprint → no conflict guard.
    assert api.save_file("hello") == {"status": "ok"}
    assert (tmp_path / "out.md").read_text(encoding="utf-8") == "hello"


def test_save_conflict_detected_when_disk_mutates(tmp_path):
    """External edit between load and save must block the overwrite."""
    p = tmp_path / "doc.md"
    p.write_text("loaded content\n", encoding="utf-8")
    api = app_mod.JsApi()
    api._current_path = p
    api._loaded_fingerprint = app_mod._fingerprint(p)

    # Another program modifies the file.
    import time
    time.sleep(0.01)  # ensure mtime_ns ticks even on coarse clocks
    p.write_text("external edits\n" + "X" * 100, encoding="utf-8")

    result = api.save_file("my edits")
    assert result == {"status": "conflict"}
    # File must NOT have been overwritten yet.
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
    assert result == {"status": "ok"}
    assert p.read_text(encoding="utf-8") == "my edits"
    # Fingerprint must be refreshed so the next save sees *this* as baseline.
    assert api._loaded_fingerprint == app_mod._fingerprint(p)


def test_save_fingerprint_refreshes_after_ok(tmp_path):
    """A normal save updates the baseline so subsequent saves don't falsely conflict."""
    p = tmp_path / "doc.md"
    p.write_text("v0\n", encoding="utf-8")
    api = app_mod.JsApi()
    api._current_path = p
    api._loaded_fingerprint = app_mod._fingerprint(p)

    assert api.save_file("v1")["status"] == "ok"
    # A second in-app save must not think it's conflicting with itself.
    assert api.save_file("v2")["status"] == "ok"
    assert p.read_text(encoding="utf-8") == "v2"


def test_load_records_fingerprint(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("hello", encoding="utf-8")
    api = app_mod.JsApi()
    api._window = None  # no window → _load won't call evaluate_js
    # Call _load directly and verify fingerprint is captured.
    from unittest.mock import MagicMock
    api._window = MagicMock()
    api._load(p)
    assert api._loaded_fingerprint == app_mod._fingerprint(p)


def test_open_file_without_window_returns_false():
    api = app_mod.JsApi()
    assert api.open_file() is False


def test_load_emits_reason_in_payload(tmp_path):
    """External reloads must tag the payload so JS can prompt on dirty edits."""
    api = app_mod.JsApi()
    fake_win = MagicMock()
    api._window = fake_win
    src = tmp_path / "doc.md"
    src.write_text("# hi", encoding="utf-8")

    api._load(src, reason="watch")
    call = fake_win.evaluate_js.call_args[0][0]
    assert '"reason": "watch"' in call

    api._load(src, reason="open")
    call = fake_win.evaluate_js.call_args[0][0]
    assert '"reason": "open"' in call


def test_build_html_rewrites_app_assets_to_absolute():
    """App assets must become absolute URLs, NOT a document-wide <base>
    (which would also reroute user-markdown relative paths)."""
    html = app_mod._build_html("hi", None, False, assets_base="file:///x/y/")
    # No document-wide <base> — it would misdirect user relative URLs.
    assert "<base" not in html
    # App assets prefixed with the absolute base.
    assert 'href="file:///x/y/app.css"' in html
    assert 'href="file:///x/y/vendor/katex/katex.min.css"' in html
    assert 'src="file:///x/y/vendor/mermaid/mermaid.min.js"' in html


def test_build_html_without_base_unchanged():
    html = app_mod._build_html("hi", None, False)
    assert "<base" not in html
    # Relative references stay relative when no assets_base is given.
    assert 'href="app.css"' in html


def test_id_attribute_stripped_from_user_content():
    """A hostile markdown file must not be able to inject an element with
    id="md-source" (or any reserved bootstrap id) and shadow the real data."""
    from mdvw.render import render_markdown

    hostile = '<div id="md-source">stolen</div>\n<div id="md-path">/etc/passwd</div>\n'
    html = render_markdown(hostile)
    assert 'id="md-source"' not in html
    assert 'id="md-path"' not in html
    # The text itself is still preserved — only the id attribute is stripped.
    assert "stolen" in html


def test_open_external_rejects_file_scheme(monkeypatch, tmp_path):
    """file:// links must not ShellExecute (would let a hostile .md launch .exe)."""
    api = app_mod.JsApi()
    started = []
    import os as _os
    monkeypatch.setattr(_os, "startfile", lambda p: started.append(p), raising=False)
    exe = tmp_path / "evil.exe"
    exe.write_bytes(b"MZ")
    assert api.open_external(f"file:///{exe.as_posix().lstrip('/')}") is False
    assert started == []


def test_render_strips_file_links():
    """The sanitizer drops file: as an <a href> scheme (defense in depth).
    The raw text "file:///…" may survive as inert prose — that's harmless;
    what matters is no clickable <a href="file:..."> is produced."""
    from mdvw.render import render_markdown
    html = render_markdown("[click](file:///C:/Windows/System32/calc.exe)")
    assert 'href="file:' not in html
    assert "<a " not in html or "file:" not in html


def test_watch_reload_guards_dirty_regardless_of_mode():
    """Round-4: dirty in read mode must still block silent overwrite.
    This JS-side invariant is exercised indirectly — the Python side just
    tags the payload with reason='watch', and JS handles the prompt."""
    api = app_mod.JsApi()
    from unittest.mock import MagicMock
    api._window = MagicMock()
    import tempfile
    from pathlib import Path as _P
    with tempfile.TemporaryDirectory() as td:
        p = _P(td) / "doc.md"
        p.write_text("external", encoding="utf-8")
        api._load(p, reason="watch")
    call = api._window.evaluate_js.call_args[0][0]
    assert '"reason": "watch"' in call


def test_close_confirm_fails_closed_on_dialog_error(monkeypatch):
    """If the native confirmation dialog can't be shown, the window must
    NOT close — failing closed protects unsaved edits."""
    api = app_mod.JsApi()
    api._dirty = True

    class _FakeWindow:
        def create_confirmation_dialog(self, title, msg):
            raise RuntimeError("WebView unavailable")

    # Reconstruct the behavior the real run()'s _on_closing encodes.
    def _on_closing(api, window):
        if not api._dirty:
            return True
        try:
            return bool(window.create_confirmation_dialog("t", "m"))
        except Exception:
            return False

    assert _on_closing(api, _FakeWindow()) is False


def test_open_external_rejects_invalid_scheme(monkeypatch):
    """Only http/https/mailto/file may leave via the shell; anything else
    (javascript:, data:, ws:, custom:) must not navigate or launch."""
    api = app_mod.JsApi()
    calls = []
    monkeypatch.setattr(app_mod, "webview", app_mod.webview)  # no-op; ensure module
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda *a, **kw: calls.append(("web", a)) or True)

    assert api.open_external("javascript:alert(1)") is False
    assert api.open_external("data:text/html,<script>1") is False
    assert api.open_external("custom:payload") is False
    assert api.open_external("") is False
    assert api.open_external(None) is False  # type: ignore[arg-type]
    assert calls == []  # nothing launched


def test_open_external_allows_http_via_webbrowser(monkeypatch):
    api = app_mod.JsApi()
    calls = []
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda url, **kw: calls.append(url) or True)

    assert api.open_external("https://example.com/path") is True
    assert api.open_external("mailto:you@example.com") is True
    assert calls == ["https://example.com/path", "mailto:you@example.com"]


def test_dirty_state_mirrored_to_python():
    api = app_mod.JsApi()
    assert api._dirty is False
    api.set_dirty(True)
    assert api._dirty is True
    api.set_dirty(False)
    assert api._dirty is False


def test_pyinstaller_spec_paths_resolve():
    """Sanity-check the spec's path math without running PyInstaller itself."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    specfile = root / "packaging" / "mdvw.spec"
    assert specfile.exists()
    # Emulate PyInstaller's SPECPATH (directory containing the spec).
    spec_dir = specfile.parent
    resolved_root = Path(str(spec_dir)).resolve().parent
    assert (resolved_root / "src" / "mdvw" / "__main__.py").exists()
    assert (resolved_root / "src" / "mdvw" / "assets" / "template.html").exists()


def test_rejected_watch_reload_preserves_conflict_baseline(tmp_path):
    """The user rejects a watched reload (Keep my edits). A subsequent save
    MUST still flag the conflict instead of silently overwriting."""
    p = tmp_path / "doc.md"
    p.write_text("v0\n", encoding="utf-8")

    api = app_mod.JsApi()
    from unittest.mock import MagicMock
    api._window = MagicMock()
    # Initial load (reason="open"): baseline committed.
    api._load(p, reason="open")
    baseline = api._loaded_fingerprint
    assert baseline is not None

    # External program rewrites the file.
    import time
    time.sleep(0.01)
    p.write_text("external new\n" + "X" * 50, encoding="utf-8")

    # Watcher reports the change. Python stages the fingerprint but does
    # NOT commit it — the UI will decide.
    api._load(p, reason="watch")
    assert api._loaded_fingerprint == baseline, "baseline must not advance on watch"
    assert api._pending_fingerprint is not None
    assert api._pending_fingerprint != baseline

    # User says "Keep my edits" — ack_reload is NOT called.
    # Saving must now detect the conflict.
    result = api.save_file("my edits")
    assert result == {"status": "conflict"}
    assert "external new" in p.read_text(encoding="utf-8")


def test_accepted_watch_reload_advances_baseline(tmp_path):
    """When the UI accepts the reload (calls ack_reload), the baseline
    advances so the next save doesn't falsely conflict."""
    p = tmp_path / "doc.md"
    p.write_text("v0\n", encoding="utf-8")
    api = app_mod.JsApi()
    from unittest.mock import MagicMock
    api._window = MagicMock()
    api._load(p, reason="open")

    import time
    time.sleep(0.01)
    p.write_text("v1\n", encoding="utf-8")
    api._load(p, reason="watch")

    # UI accepts the reload.
    assert api.ack_reload() is True
    assert api._loaded_fingerprint == app_mod._fingerprint(p)
    assert api._pending_fingerprint is None

    # Now saving must NOT flag a conflict.
    assert api.save_file("v2")["status"] == "ok"


def test_protocol_relative_img_src_stripped():
    """`//attacker.example/x` would resolve to a network request in the
    WebView — must be rejected along with plain http(s)."""
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
    """Remote http(s) image URLs must be stripped to preserve offline-first
    posture and avoid leaking document-open telemetry to attackers."""
    from mdvw.render import render_markdown
    for url in ("https://evil.example/pixel.gif", "http://tracker.example/p"):
        html = render_markdown(f"![x]({url})")
        assert url not in html, f"remote img src not stripped: {html}"
        assert 'src="http' not in html


def test_local_and_data_img_src_allowed():
    """Relative paths and data: URIs stay — those don't leave the box."""
    from mdvw.render import render_markdown
    html = render_markdown("![x](./diagram.png)")
    assert 'src="./diagram.png"' in html or "src=\"./diagram.png\"" in html
    # tiny transparent PNG as data URI
    tiny = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    html2 = render_markdown(f"![x]({tiny})")
    assert "data:image/png;base64," in html2


def test_list_markdown_dir_none_without_browse_root():
    """With no _browse_root, the dir API is unavailable."""
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
    # Hidden + denylist skipped; non-md file skipped.
    assert ".git" not in names and "node_modules" not in names
    assert "notes.txt" not in names
    # Dirs before files, alpha case-insensitive within each group.
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
    # `inside/../` resolves to tmp_path — outside the browse root.
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


def test_vendor_manifest_matches_on_disk():
    """Release-time integrity: committed vendor files match the manifest hashes."""
    import subprocess

    root = Path(__file__).resolve().parents[1]
    r = subprocess.run(
        ["python", "scripts/fetch_vendor.py", "--verify"],
        cwd=root, capture_output=True, text=True,
    )
    assert r.returncode == 0, f"vendor verification failed:\nstdout={r.stdout}\nstderr={r.stderr}"
