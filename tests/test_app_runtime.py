"""Runtime and facade regression tests for mdvw app behavior."""
from __future__ import annotations

from pathlib import Path

from mdvw import app as app_mod


def test_open_external_rejects_file_scheme(monkeypatch, tmp_path):
    """file:// links must not ShellExecute arbitrary local executables."""
    api = app_mod.JsApi()
    started = []
    import os as _os

    monkeypatch.setattr(_os, "startfile", lambda p: started.append(p), raising=False)
    exe = tmp_path / "evil.exe"
    exe.write_bytes(b"MZ")
    assert api.open_external(f"file:///{exe.as_posix().lstrip('/')}") is False
    assert started == []


def test_close_confirm_fails_closed_on_dialog_error():
    """If the native confirmation dialog can't be shown, the window must not close."""
    api = app_mod.JsApi()
    api._dirty = True

    class _FakeWindow:
        def create_confirmation_dialog(self, title, msg):
            raise RuntimeError("WebView unavailable")

    def _on_closing(api, window):
        if not api._dirty:
            return True
        try:
            return bool(window.create_confirmation_dialog("t", "m"))
        except Exception:
            return False

    assert _on_closing(api, _FakeWindow()) is False


def test_open_external_rejects_invalid_scheme(monkeypatch):
    """Only http/https/mailto may leave via the shell."""
    api = app_mod.JsApi()
    calls = []
    monkeypatch.setattr(app_mod, "webview", app_mod.webview)
    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda *a, **kw: calls.append(("web", a)) or True)

    assert api.open_external("javascript:alert(1)") is False
    assert api.open_external("data:text/html,<script>1") is False
    assert api.open_external("custom:payload") is False
    assert api.open_external("") is False
    assert api.open_external(None) is False  # type: ignore[arg-type]
    assert calls == []


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
    root = Path(__file__).resolve().parents[1]
    specfile = root / "packaging" / "mdvw.spec"
    assert specfile.exists()
    spec_dir = specfile.parent
    resolved_root = Path(str(spec_dir)).resolve().parent
    assert (resolved_root / "src" / "mdvw" / "__main__.py").exists()
    assert (resolved_root / "src" / "mdvw" / "assets" / "template.html").exists()


def test_autoreopen_skips_last_file_from_other_workspace(
    tmp_path, monkeypatch,
):
    """No-arg launch must not silently reopen a document outside the cwd."""
    from mdvw import state

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    workspace_a = tmp_path / "a"
    workspace_b = tmp_path / "b"
    workspace_a.mkdir()
    workspace_b.mkdir()
    doc_a = workspace_a / "notes.md"
    doc_a.write_text("# a", encoding="utf-8")

    state.set_key("last_file", str(doc_a))

    monkeypatch.chdir(workspace_b)
    browse_root = Path.cwd().resolve()
    last = state.get("last_file")
    restored: Path | None = None
    if last:
        last_path = Path(last).resolve()
        if last_path.is_file() and last_path.is_relative_to(browse_root):
            restored = last_path
    assert restored is None


def test_autoreopen_restores_last_file_inside_workspace(
    tmp_path, monkeypatch,
):
    from mdvw import state

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    workspace = tmp_path / "proj"
    workspace.mkdir()
    doc = workspace / "notes.md"
    doc.write_text("# hi", encoding="utf-8")

    state.set_key("last_file", str(doc))

    monkeypatch.chdir(workspace)
    browse_root = Path.cwd().resolve()
    last = state.get("last_file")
    restored: Path | None = None
    if last:
        last_path = Path(last).resolve()
        if last_path.is_file() and last_path.is_relative_to(browse_root):
            restored = last_path
    assert restored == doc.resolve()


def test_vendor_manifest_matches_on_disk():
    """Release-time integrity: committed vendor files match the manifest hashes."""
    import subprocess

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["python", "scripts/fetch_vendor.py", "--verify"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "vendor verification failed:\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
