from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import sys
import tempfile
import threading
from importlib.resources import files
from pathlib import Path

import webview

# Silence pywebview's internal attribute-introspection warnings (e.g. the
# .NET Rectangle.Empty self-recursion spam and WebView2 shutdown class
# unregister noise — both cosmetic).
# Silence pywebview + WebView2 startup introspection noise.
for _name in ("pywebview", "pywebview.util", "pywebview.platforms.edgechromium", "webview"):
    logging.getLogger(_name).setLevel(logging.CRITICAL)
# Nuclear option: filter any log record whose message contains the .NET
# Rectangle.Empty self-recursion walk.
class _EmptySpamFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "Empty.Empty" not in record.getMessage()
logging.getLogger().addFilter(_EmptySpamFilter())

from . import __version__, config  # noqa: E402  (must run after logger filter)
from .render import render_markdown  # noqa: E402

ASSETS = files(__package__) / "assets"


def _load_template() -> str:
    return (ASSETS / "template.html").read_text(encoding="utf-8")


def _initial_file(file: Path | None) -> tuple[Path | None, str]:
    if file:
        file = file.resolve()
        if file.exists():
            return file, file.read_text(encoding="utf-8")
        return file, ""
    example = ASSETS / "example.md"
    return None, example.read_text(encoding="utf-8")


def _json_for_script_tag(value: str) -> str:
    """JSON-encode a value safely for embedding inside an HTML <script> element.

    Standard json.dumps does not escape `</script>`, so a document that
    contains that sequence would break out of the script tag and execute
    arbitrary HTML/JS before the sanitizer runs. We additionally neutralize
    `<`, `>`, and `&` with `\\uXXXX` escapes, and `U+2028`/`U+2029` which are
    valid string breaks in HTML but invalid in JS string literals.
    """
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


_APP_ASSET_ATTR_RE = re.compile(
    r'(src|href)="((?:vendor/|app\.css|app\.js)[^"]*)"'
)


def _rewrite_app_asset_urls(template: str, assets_base: str) -> str:
    """Prefix app-asset references in the template with an absolute URL.

    Replaces `src="vendor/foo.js"` and `href="app.css"` with their
    absolute file:// equivalents. Avoids a document-wide `<base href>`,
    which would also reroute user-document relative URLs and break
    `![diagram](./diagram.png)` against the Markdown file's directory.
    """
    base = assets_base.rstrip("/") + "/"

    def _sub(m: re.Match[str]) -> str:
        return f'{m.group(1)}="{base}{m.group(2)}"'

    return _APP_ASSET_ATTR_RE.sub(_sub, template)


def _build_html(source: str, path: Path | None, edit: bool, assets_base: str = "") -> str:
    """Render the template with the given source embedded.

    `assets_base` is an absolute URL (with trailing slash) pointing at the
    packaged assets directory. App asset references in the template are
    rewritten to absolute URLs rooted there, so they keep working when
    the generated HTML file lives in a per-instance temp dir. User
    Markdown relative URLs are rewritten separately by `render_markdown`
    against the document's own directory.
    """
    template = _load_template()
    if assets_base:
        template = _rewrite_app_asset_urls(template, assets_base)
    name = path.name if path else "Welcome"
    folder = str(path.parent) if path else ""
    path_str = str(path) if path else ""
    doc_base = path.parent.resolve().as_uri() + "/" if path else None
    html_body = render_markdown(source, doc_base=doc_base)
    return (
        template
        .replace("{{MD_HTML}}", html_body)
        .replace("{{MD_SOURCE}}", _json_for_script_tag(source))
        .replace("{{MD_NAME}}", name)
        .replace("{{MD_FOLDER}}", folder)
        .replace("{{MD_PATH}}", path_str)
        .replace("{{MD_START_MODE}}", "edit" if edit else "read")
        .replace("{{MD_VERSION}}", __version__)
    )


def _atomic_write_text(path: Path, content: str) -> None:
    """Write `content` to `path` atomically. Preserves the original file on failure.

    Uses a temp file in the same directory, flushes + fsyncs, then os.replace
    to make the swap atomic at the filesystem level. Avoids partial writes
    from crashes, antivirus locks, full disks, or OSError mid-write.
    """
    path = Path(path)
    directory = path.parent if path.parent != Path("") else Path.cwd()
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(directory)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
            f.flush()
            with contextlib.suppress(OSError):
                os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def _fingerprint(path: Path) -> tuple[int, int] | None:
    """Cheap (mtime_ns, size) fingerprint for concurrent-edit detection.

    Returns None if the file is absent or unreadable, which we treat as
    distinct from any present-file fingerprint.
    """
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


class JsApi:
    def __init__(self) -> None:
        self._window: webview.Window | None = None
        self._current_path: Path | None = None
        # (mtime_ns, size) of the file when we last loaded or saved it.
        # None means "no known version" (e.g., new untitled document).
        self._loaded_fingerprint: tuple[int, int] | None = None
        # Proposed fingerprint for a watched change the UI hasn't yet
        # committed to. Only promotes to _loaded_fingerprint when JS calls
        # ack_reload(); otherwise the old baseline is retained so a
        # subsequent save still flags the conflict.
        self._pending_fingerprint: tuple[int, int] | None = None
        # Mirrored from JS via set_dirty() so native close/quit paths can
        # show a "discard edits?" prompt without round-tripping to JS.
        self._dirty: bool = False

    def set_dirty(self, value: bool) -> None:
        self._dirty = bool(value)

    def ack_reload(self) -> bool:
        """JS calls this when it actually applied a watched reload.

        Promotes the pending fingerprint to the committed baseline.
        Required because rejecting a watched reload (user keeps edits) must
        NOT advance the save-conflict baseline, or subsequent saves would
        silently overwrite the disk edits the user chose not to take.
        """
        if self._pending_fingerprint is None:
            return False
        self._loaded_fingerprint = self._pending_fingerprint
        self._pending_fingerprint = None
        return True

    def render_markdown(self, text: str) -> str:
        return render_markdown(text)

    def save_file(self, content: str, force: bool = False) -> dict:
        """Save the current document atomically.

        Returns a dict:
          {"status": "ok"}                — written successfully
          {"status": "cancelled"}         — user cancelled save-as dialog
          {"status": "conflict"}          — disk changed since load;
                                            caller should prompt user and
                                            retry with force=True
          {"status": "error", "message"}  — OS-level write failure
        """
        path = self._current_path
        if path is None:
            picked = self._pick_save_path()
            if picked is None:
                return {"status": "cancelled"}
            path = picked
            self._current_path = path
            self._loaded_fingerprint = None  # brand new file — no prior state
        if not force and self._loaded_fingerprint is not None:
            current = _fingerprint(path)
            # If disk state differs from what we loaded (and it existed then),
            # block the overwrite until the user explicitly opts in.
            if current != self._loaded_fingerprint:
                return {"status": "conflict"}
        try:
            _atomic_write_text(path, content)
        except OSError as e:
            print(f"[mdvw] save_file failed: {e}", file=sys.stderr)
            return {"status": "error", "message": str(e)}
        # Refresh fingerprint after successful write so the next save sees
        # this save as the new baseline.
        self._loaded_fingerprint = _fingerprint(path)
        return {"status": "ok"}

    def open_external(self, url: str) -> bool:
        """Open a user-document link outside the WebView.

        The preview window carries a native `js_api` bridge; letting an
        untrusted document navigate it would hand that bridge to the
        destination. Only http/https/mailto are allowed — `file://` links
        are rejected because a hostile Markdown document could otherwise
        ShellExecute arbitrary .exe/.lnk/etc. via `os.startfile`.
        """
        import webbrowser

        if not isinstance(url, str) or not url:
            return False
        scheme = url.split(":", 1)[0].lower() if ":" in url else ""
        if scheme in ("http", "https", "mailto"):
            webbrowser.open(url, new=2)
            return True
        return False

    def open_file(self) -> bool:
        if self._window is None:
            return False
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=("Markdown (*.md;*.markdown)", "All files (*.*)"),
        )
        if not result:
            return False
        self._load(Path(result[0]))
        return True

    def register_association(self) -> bool:
        from .assoc import register

        ok = register() == 0
        config.set_key("association_prompted", True)
        return ok

    def decline_association(self) -> None:
        config.set_key("association_prompted", True)

    def _pick_save_path(self) -> Path | None:
        if self._window is None:
            return None
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename="untitled.md",
            file_types=("Markdown (*.md)", "All files (*.*)"),
        )
        return Path(result) if result else None

    def _load(self, path: Path, reason: str = "open") -> None:
        source = path.read_text(encoding="utf-8")
        html = render_markdown(source)
        self._current_path = path
        new_fp = _fingerprint(path)
        if reason == "watch":
            # Hold the new fingerprint in escrow — only promote if JS
            # confirms it applied the reload (via ack_reload).
            self._pending_fingerprint = new_fp
        else:
            # Explicit open / initial load / programmatic reload: the UI
            # will unconditionally replace its source, so commit baseline.
            self._loaded_fingerprint = new_fp
            self._pending_fingerprint = None
        if self._window is not None:
            payload = json.dumps({
                "html": html,
                "source": source,
                "name": path.name,
                "path": str(path),
                "reason": reason,
            })
            self._window.evaluate_js(f"window.mdvwSetDocument({payload})")


def _maybe_prompt_association(window: webview.Window) -> None:
    if sys.platform != "win32":
        return
    if config.get("association_prompted"):
        return

    def _later() -> None:
        with contextlib.suppress(Exception):
            window.evaluate_js("window.mdvwPromptAssociation && window.mdvwPromptAssociation()")

    threading.Timer(1.2, _later).start()


def run(file: Path | None, edit: bool, tray: bool) -> int:
    path, source = _initial_file(file)

    # Resolve the packaged assets dir and rewrite app-asset refs in the
    # template to absolute URLs rooted there. This avoids a document-wide
    # <base href>, which would silently reroute user-document relative
    # URLs (./image.png, ./other.md) to the assets dir.
    assets_dir = Path(str(ASSETS)).resolve()
    assets_base = assets_dir.as_uri().rstrip("/") + "/"
    html = _build_html(source, path, edit, assets_base=assets_base)

    # Per-instance temp file in a user-writable location — not the package
    # dir (which may be read-only in installed envs) and with a unique
    # name (so concurrent mdvw instances don't race on a shared filename).
    instance_dir = Path(tempfile.mkdtemp(prefix="mdvw-"))
    index = instance_dir / "index.html"
    index.write_text(html, encoding="utf-8")

    api = JsApi()
    api._current_path = path
    if path is not None:
        api._loaded_fingerprint = _fingerprint(path)

    window = webview.create_window(
        title=f"{path.name if path else 'mdvw'} — mdvw",
        url=index.as_uri(),
        js_api=api,
        width=1100,
        height=780,
        min_size=(600, 400),
    )
    api._window = window
    window.events.loaded += lambda: _maybe_prompt_association(window)

    # Dirty-state guard: confirm before destroying if there are unsaved
    # edits. We query JS *synchronously* via evaluate_js rather than
    # reading the mirrored `api._dirty` attribute, because the JS→Python
    # set_dirty() call is async — a user can type + close fast enough
    # that Python never saw the dirty update.  Fail closed on any error.
    def _on_closing() -> bool:
        try:
            js_dirty = window.evaluate_js(
                "(typeof window.mdvwIsDirty === 'function') "
                "? !!window.mdvwIsDirty() : false"
            )
        except Exception as exc:
            # JS bridge unavailable → be pessimistic: block the close so
            # the user can investigate rather than silently losing edits.
            print(
                f"[mdvw] could not read dirty state on close ({exc!r}); "
                "blocking close.",
                file=sys.stderr,
            )
            return False
        if not js_dirty:
            return True
        try:
            confirm = window.create_confirmation_dialog(
                "Unsaved changes",
                "You have unsaved edits. Quit anyway?",
            )
        except Exception as exc:
            print(
                f"[mdvw] unable to show close confirmation ({exc!r}); "
                "refusing close to protect unsaved edits.",
                file=sys.stderr,
            )
            return False
        return bool(confirm)

    window.events.closing += _on_closing

    tray_thread = None
    if tray and sys.platform == "win32":
        from .tray import start_tray

        tray_thread = start_tray(window)

    if file and file.exists() and not edit:
        from .watcher import start_watcher

        start_watcher(file, api)

    try:
        webview.start()
    finally:
        # Clean up only our own instance files.
        with contextlib.suppress(OSError):
            index.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            instance_dir.rmdir()
        if tray_thread is not None:
            from .tray import stop_tray

            stop_tray()
    return 0
