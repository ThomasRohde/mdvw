from __future__ import annotations

import base64
import binascii
import contextlib
import json
import logging
import os
import re
import sys
import tempfile
import threading
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import ClassVar

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

from . import __version__, config, state  # noqa: E402  (must run after logger filter)
from .diagnostics import check_document as _check_document  # noqa: E402
from .export import build_standalone_html as _build_standalone_html  # noqa: E402
from .frontmatter import parse_frontmatter, split_frontmatter  # noqa: E402
from .render import render_frontmatter_card, render_markdown  # noqa: E402
from .search import search_workspace as _search_workspace  # noqa: E402


def _render_with_frontmatter(source: str, doc_base: str | None = None) -> str:
    """Render ``source`` to HTML, prepending a frontmatter card when present."""
    raw_yaml, body = split_frontmatter(source)
    if raw_yaml is not None:
        _meta, _body, err = parse_frontmatter(source)
        card = render_frontmatter_card(raw_yaml, err)
    else:
        card = ""
    return card + render_markdown(body, doc_base=doc_base)

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


def _json_for_script_tag(value: object) -> str:
    """JSON-encode a value safely for embedding inside an HTML <script> element.

    Accepts any JSON-serializable value (string, dict, list, etc.).
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


def _build_html(
    source: str,
    path: Path | None,
    edit: bool,
    assets_base: str = "",
    browse_root: Path | None = None,
) -> str:
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
    html_body = _render_with_frontmatter(source, doc_base=doc_base)
    return (
        template
        .replace("{{MD_HTML}}", html_body)
        .replace("{{MD_SOURCE}}", _json_for_script_tag(source))
        .replace("{{MD_NAME}}", name)
        .replace("{{MD_FOLDER}}", folder)
        .replace("{{MD_PATH}}", path_str)
        .replace("{{MD_START_MODE}}", "edit" if edit else "read")
        .replace("{{MD_BROWSE_ROOT}}", str(browse_root) if browse_root else "")
        .replace("{{MD_VERSION}}", __version__)
        .replace("{{MD_UI_STATE}}", _json_for_script_tag(state.load()))
    )


def _save_dialog_path(result: object) -> str | None:
    """Normalize the return of ``create_file_dialog(SAVE_DIALOG, ...)``.

    pywebview 6.x on Windows (winforms backend) returns a 1-tuple
    ``(path,)`` for save dialogs; older or other backends may return a
    bare string. Both shapes land here. ``Path(tuple)`` would otherwise
    raise ``TypeError`` and pywebview's bridge silently swallows the
    exception, which is why export-HTML previously "failed silently".
    """
    if not result:
        return None
    if isinstance(result, str):
        return result
    # Sequence[str]
    return result[0] if result else None


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


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Byte-oriented counterpart to ``_atomic_write_text``.

    A crash mid-write (disk full, AV lock, process kill) leaves the tmp file
    behind instead of a half-written target — critical for binary assets
    (pasted images) where a truncated PNG is silently corrupt.
    """
    path = Path(path)
    directory = path.parent if path.parent != Path("") else Path.cwd()
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(directory)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            with contextlib.suppress(OSError):
                os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def _stderr_print(message: str) -> None:
    """Best-effort diagnostic print to stderr.

    Under `pythonw.exe` / a PyInstaller windowed build, `sys.stderr` is
    `None`; a plain `print(..., file=sys.stderr)` would raise
    `AttributeError: 'NoneType' object has no attribute 'write'` and take
    down whatever code path emitted the diagnostic. Silently drop the
    message in that case — it would have been invisible anyway.
    """
    stream = sys.stderr
    if stream is None:
        return
    with contextlib.suppress(Exception):
        print(message, file=stream)


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
        self._quitting: bool = False
        # Directory mdvw was launched in, when no file arg was provided.
        # Populated by run(). None means "single-file launch"; the file
        # browser sidebar is only offered when this is set.
        self._browse_root: Path | None = None
        # Cached top-level HWND for DWM title-bar theming. Populated once
        # on the `loaded` event; set_titlebar_dark is a no-op until then.
        self._hwnd: int | None = None

    def set_dirty(self, value: bool) -> None:
        self._dirty = bool(value)

    def set_titlebar_dark(self, dark: bool) -> None:
        """Flip the Windows title bar to dark/light to match the app theme.

        Called from JS whenever the resolved theme changes (user toggle,
        system `prefers-color-scheme` change, pywebview bridge coming
        online). No-op off Windows or before the HWND has been resolved.
        """
        if sys.platform != "win32" or self._hwnd is None:
            return
        _apply_titlebar_theme(self._hwnd, bool(dark))

    def confirm_quit(self) -> None:
        """Called from JS when the user confirms quit from the tray dialog."""
        from .tray import stop_tray

        self._quitting = True
        stop_tray()
        if self._window is not None:
            self._window.destroy()

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
        doc_base = None
        if self._current_path:
            doc_base = self._current_path.parent.resolve().as_uri() + "/"
        return _render_with_frontmatter(text, doc_base=doc_base)

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
            _stderr_print(f"[mdvw] save_file failed: {e}")
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

    _BROWSE_SKIP_DIRS = frozenset({
        "node_modules", "__pycache__", ".venv", "venv",
        "dist", "build", ".git", ".hg", ".svn", ".tox",
        ".mypy_cache", ".pytest_cache", ".ruff_cache",
    })

    def list_markdown_dir(self, path_str: str = "") -> dict | None:
        """List markdown files and subdirectories of a single directory.

        Called lazily from the sidebar so large trees don't block the UI
        on first paint — each folder's contents are fetched only when the
        user expands it.

        `path_str=""` means "the browse root". Any other value must be
        a directory inside the browse root; path-traversal is rejected.
        Returns `{"path": str, "entries": [...]}` or `None` on error.
        """
        if self._browse_root is None:
            return None
        try:
            root = self._browse_root.resolve()
        except OSError:
            return None
        if path_str:
            if not isinstance(path_str, str):
                return None
            try:
                target = Path(path_str).resolve()
            except OSError:
                return None
            if target != root and not target.is_relative_to(root):
                return None
        else:
            target = root
        if not target.is_dir():
            return None
        entries: list[dict] = []
        try:
            children = list(target.iterdir())
        except OSError:
            return None
        # Dirs first, then files, each alphabetical case-insensitive.
        children.sort(key=lambda p: (0 if p.is_dir() else 1, p.name.casefold()))
        for child in children:
            name = child.name
            if name.startswith("."):
                continue
            try:
                is_dir = child.is_dir()
            except OSError:
                continue
            if is_dir:
                if name in self._BROWSE_SKIP_DIRS:
                    continue
                entries.append({"type": "dir", "name": name, "path": str(child)})
            else:
                if child.suffix.lower() not in (".md", ".markdown"):
                    continue
                entries.append({"type": "file", "name": name, "path": str(child)})
        return {"path": str(target), "entries": entries}

    def open_path(self, path_str: str) -> bool:
        """Load a file selected from the sidebar.

        Validates that the path lies under `self._browse_root` and has a
        markdown suffix. Rejects anything else so a hostile caller (or a
        bug in the frontend) can't coerce an arbitrary disk read through
        this bridge method.
        """
        if self._browse_root is None or not isinstance(path_str, str) or not path_str:
            return False
        try:
            candidate = Path(path_str).resolve()
            root = self._browse_root.resolve()
        except OSError:
            return False
        if not candidate.is_relative_to(root):
            return False
        if candidate.suffix.lower() not in (".md", ".markdown"):
            return False
        if not candidate.is_file():
            return False
        self._load(candidate)
        return True

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

    def open_recent(self, path_str: str) -> bool:
        """Load a markdown file from the persisted recent-files list.

        Unlike ``open_path`` (sidebar browser) this does NOT require the
        target to sit under ``self._browse_root`` — the recent list spans
        previous workspaces. But pywebview exposes every API method to the
        renderer, so if a sanitizer bypass in a viewed document landed a
        call here it could otherwise read any ``.md`` on disk. We gate on
        an allowlist: the caller-supplied path must match an entry in the
        persisted recent-files list (case-insensitive on Windows).
        """
        if not isinstance(path_str, str) or not path_str:
            return False
        try:
            candidate = Path(path_str).resolve()
        except OSError:
            return False
        if candidate.suffix.lower() not in (".md", ".markdown"):
            return False
        if not candidate.is_file():
            return False
        candidate_key = os.path.normcase(str(candidate))
        allowed: set[str] = set()
        for p in state.get("recent_files", []) or []:
            try:
                allowed.add(os.path.normcase(str(Path(p).resolve())))
            except OSError:
                continue
        if candidate_key not in allowed:
            return False
        self._load(candidate)
        return True

    def register_association(self) -> bool:
        from .assoc import register

        ok = register() == 0
        config.set_key("association_prompted", True)
        return ok

    def decline_association(self) -> None:
        config.set_key("association_prompted", True)

    # -- UI state persistence --------------------------------------------------

    # Keys the renderer is allowed to persist via ``save_ui_state``.
    # Python-owned trust-boundary keys (``recent_files``, ``last_file``,
    # ``last_browse_root``) are deliberately excluded — ``open_recent``
    # uses ``recent_files`` as an allowlist, so a renderer that could
    # write it would defeat the workspace boundary.
    _UI_STATE_SCHEMA: ClassVar[dict[str, type | tuple[type, ...]]] = {
        "left_pane_width": int,
        "left_pane_collapsed": bool,
        "left_pane_section": str,
        "right_pane_width": int,
        "right_pane_collapsed": bool,
        "mode": str,
        "preview_narrow": bool,
    }

    def save_ui_state(self, data: dict) -> None:
        """Persist UI state (pane widths, sections, etc.) from JS.

        Only the keys in ``_UI_STATE_SCHEMA`` are merged — any other field
        (especially ``recent_files``, ``last_file``) is dropped. pywebview
        exposes this method to the renderer, so without a whitelist a
        sanitizer bypass could poison the recent-file allowlist and
        smuggle arbitrary ``.md`` reads through ``open_recent``.
        """
        if not isinstance(data, dict):
            return
        cleaned: dict = {}
        for key, expected in self._UI_STATE_SCHEMA.items():
            if key not in data:
                continue
            value = data[key]
            # bool is a subclass of int — reject it when int is expected
            # so a caller can't pass True where an int width belongs.
            if expected is int and isinstance(value, bool):
                continue
            if not isinstance(value, expected):
                continue
            cleaned[key] = value
        if not cleaned:
            return
        current = state.load()
        current.update(cleaned)
        state.save(current)

    def get_ui_state(self) -> dict:
        """Return the persisted UI state for JS initialisation."""
        return state.load()

    def get_recent_files(self) -> list[dict]:
        """Return the recent files list with existence flags."""
        recent = state.get("recent_files", [])
        result = []
        for p in recent:
            pp = Path(p)
            result.append({"path": p, "name": pp.name, "exists": pp.is_file()})
        return result

    def clear_recent_files(self) -> None:
        state.set_key("recent_files", [])

    def search_filenames(self, query: str, max_results: int = 50) -> list[dict]:
        """Search for markdown files by name within the browse root."""
        if not self._browse_root or not query or not isinstance(query, str):
            return []
        q = query.lower()
        results = []
        try:
            root = self._browse_root.resolve()
        except OSError:
            return []
        count = 0
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune skipped directories in-place.
            dirnames[:] = [
                d for d in dirnames
                if d not in self._BROWSE_SKIP_DIRS and not d.startswith(".")
            ]
            for name in filenames:
                if not name.lower().endswith((".md", ".markdown")):
                    continue
                if q not in name.lower():
                    continue
                full = Path(dirpath) / name
                try:
                    rel = full.relative_to(root)
                except ValueError:
                    continue
                results.append({
                    "name": name,
                    "path": str(full),
                    "relative": str(rel),
                })
                if len(results) >= max_results:
                    return results
            count += 1
            if count > 10000:
                break
        return results

    _IMAGE_EXT_WHITELIST: ClassVar[frozenset[str]] = frozenset(
        {"png", "jpg", "jpeg", "gif", "webp"}
    )
    # Max decoded size for a pasted image. 25 MB is well above legitimate
    # screenshot sizes but caps memory/disk cost when a renderer (or a
    # sanitizer bypass calling the bridge directly) sends a huge payload.
    _IMAGE_MAX_DECODED_BYTES: ClassVar[int] = 25 * 1024 * 1024

    def save_image(self, data_url: str, suggested_name: str) -> dict:
        """Save a base64 data-URL image to the document's images/ folder.

        Only raster image types in ``_IMAGE_EXT_WHITELIST`` are accepted —
        SVG is excluded on purpose because a saved .svg can execute script
        if a user later opens it directly in a browser. A fixed size cap
        and strict base64 decoding guard against renderer payloads that
        would otherwise stall the app or fill the document volume.

        Returns ``{status, relative_path}`` on success, or an error dict.
        """
        if self._current_path is None:
            return {"status": "error", "message": "Save the document first"}
        if not isinstance(data_url, str):
            return {"status": "error", "message": "Invalid image data"}

        doc_dir = self._current_path.parent
        images_dir = doc_dir / "images"
        images_dir.mkdir(exist_ok=True)

        # Parse data URL: data:image/png;base64,iVBOR...
        m = re.match(r"data:image/([\w+.-]+);base64,(.+)", data_url, re.DOTALL)
        if not m:
            return {"status": "error", "message": "Invalid image data"}
        ext = m.group(1).lower()
        if ext == "jpeg":
            ext = "jpg"
        if ext not in self._IMAGE_EXT_WHITELIST:
            return {"status": "error", "message": f"Unsupported image type: {ext}"}
        raw = m.group(2)

        # Cheap pre-decode size bound. Base64 is ~4/3 the decoded size, so
        # reject before allocating the decoded bytes at all. +16 absorbs
        # whitespace/padding variance.
        max_encoded = (self._IMAGE_MAX_DECODED_BYTES * 4 + 2) // 3 + 16
        if len(raw) > max_encoded:
            return {"status": "error", "message": "Image too large"}

        try:
            data = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            return {"status": "error", "message": "Invalid image data"}
        if len(data) > self._IMAGE_MAX_DECODED_BYTES:
            return {"status": "error", "message": "Image too large"}

        ts = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
        name = suggested_name or f"image-{ts}.{ext}"
        # Sanitize filename
        name = re.sub(r"[^\w.\-]", "_", name)
        if not name.lower().endswith(f".{ext}"):
            name = f"{name}.{ext}"

        target = images_dir / name
        # Collision-safe
        if target.exists():
            stem = target.stem
            i = 2
            while target.exists():
                target = images_dir / f"{stem}-{i}{target.suffix}"
                i += 1

        # Security: ensure target is under doc_dir
        try:
            target.resolve().relative_to(doc_dir.resolve())
        except ValueError:
            return {"status": "error", "message": "Path traversal rejected"}

        try:
            _atomic_write_bytes(target, data)
        except OSError as e:
            return {"status": "error", "message": str(e)}

        relative = target.relative_to(doc_dir).as_posix()
        return {"status": "ok", "relative_path": relative}

    def run_diagnostics(self, content: str) -> list[dict]:
        """Check the document for common issues."""
        doc_dir = str(self._current_path.parent) if self._current_path else None
        return _check_document(content, doc_dir=doc_dir)

    def export_html(self, content: str) -> dict:
        """Export the current document as self-contained HTML."""
        if self._window is None:
            return {"status": "error", "message": "No window"}
        name = self._current_path.stem if self._current_path else "untitled"
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=f"{name}.html",
            file_types=("HTML (*.html)", "All files (*.*)"),
        )
        path_str = _save_dialog_path(result)
        if path_str is None:
            return {"status": "cancelled"}
        out_path = Path(path_str)
        title = self._current_path.name if self._current_path else "mdvw export"
        doc_dir = self._current_path.parent if self._current_path else None
        html = _build_standalone_html(content, doc_dir=doc_dir, title=title)
        # Atomic write so a crash / disk-full / AV mid-write can't truncate
        # a pre-existing HTML at the target path.
        try:
            _atomic_write_text(out_path, html)
        except OSError as e:
            return {"status": "error", "message": str(e)}
        return {"status": "ok", "path": str(out_path)}

    def print_document(self) -> None:
        """Trigger the browser print dialog."""
        if self._window is not None:
            self._window.evaluate_js("window.print()")

    def search_workspace(self, query: str, case_sensitive: bool = False) -> list[dict]:
        """Search Markdown files in the browse root for a text query."""
        if not self._browse_root:
            return []
        return _search_workspace(
            self._browse_root, query, case_sensitive=case_sensitive,
        )

    def parse_frontmatter_fields(self, text: str) -> dict | None:
        """Return parsed frontmatter as a dict, or None if absent/invalid.

        PyYAML converts `date: 2026-04-15` into a `datetime.date` (and times
        into `datetime.time`, etc.), which pywebview cannot JSON-serialize
        across the bridge — the Inspector would silently go blank. Coerce
        any non-JSON-native values to strings via `default=str` so the
        result round-trips cleanly.
        """
        meta, _body, err = parse_frontmatter(text)
        if err or meta is None:
            return None
        return json.loads(json.dumps(meta, default=str))

    def _pick_save_path(self) -> Path | None:
        if self._window is None:
            return None
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename="untitled.md",
            file_types=("Markdown (*.md)", "All files (*.*)"),
        )
        path_str = _save_dialog_path(result)
        return Path(path_str) if path_str else None

    def _load(self, path: Path, reason: str = "open") -> None:
        source = path.read_text(encoding="utf-8")
        html = _render_with_frontmatter(source)
        self._current_path = path
        new_fp = _fingerprint(path)
        if reason != "watch":
            state.add_recent(str(path))
            state.set_key("last_file", str(path))
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


def _apply_titlebar_theme(hwnd: int, dark: bool) -> None:
    """Toggle Windows immersive dark-mode title bar via DWM.

    ``DWMWA_USE_IMMERSIVE_DARK_MODE`` is attribute 20 on Win10 20H1+
    (build 19041) and was the undocumented 19 on earlier insider builds.
    We try 20 first and fall back to 19 — both fail silently on older
    Windows versions, in which case the chrome just stays light.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        dwmapi = ctypes.windll.dwmapi
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):
            if dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value),
            ) == 0:
                return
    except Exception as exc:
        _stderr_print(f"[mdvw] could not set titlebar theme: {exc!r}")


def _find_hwnd_by_title(title: str) -> int | None:
    """Return the top-level HWND whose title matches ``title``, or None."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        return int(hwnd) or None
    except Exception:
        return None


def _system_apps_dark() -> bool:
    """Return True iff Windows is currently using the dark apps theme.

    Reads ``AppsUseLightTheme`` under the Personalize key: 0 = dark,
    1 = light. Used for the initial DWM apply so the title bar matches
    the HTML's ``auto`` theme resolution from the very first paint
    instead of flashing light → dark once JS boots.
    """
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return val == 0
    except OSError:
        return False


def _set_window_icon(window: webview.Window, title: str) -> None:
    """Attach the packaged icon.ico to the running window via WM_SETICON.

    pywebview 5.x exposes no icon parameter on Windows; without this the
    taskbar/titlebar keep the host exe's icon (Python.exe during dev).
    We look up the HWND by the window's current title and send two icon
    handles (big + small). Failure is non-fatal — the window just keeps
    the default icon.
    """
    if sys.platform != "win32":
        return
    ico = Path(str(ASSETS)).resolve() / "icon.ico"
    if not ico.exists():
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        LR_LOADFROMFILE = 0x00000010
        IMAGE_ICON = 1
        WM_SETICON = 0x0080
        ICON_SMALL, ICON_BIG = 0, 1

        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return
        big = user32.LoadImageW(None, str(ico), IMAGE_ICON, 256, 256, LR_LOADFROMFILE)
        small = user32.LoadImageW(None, str(ico), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        if big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big)
        if small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small)
    except Exception as exc:
        _stderr_print(f"[mdvw] could not set window icon: {exc!r}")


def _bring_to_front() -> None:
    """Force our window to the foreground on Windows.

    Finds the top-level window belonging to this process (by PID) and
    does a brief TOPMOST toggle + SetForegroundWindow.  Works even when
    the title has changed since creation.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        pid = os.getpid()
        found_hwnd = None

        WNDENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.wintypes.BOOL,
            ctypes.wintypes.HWND,
            ctypes.wintypes.LPARAM,
        )

        def _enum_cb(hwnd: int, _lp: int) -> bool:
            nonlocal found_hwnd
            wp = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wp))
            if wp.value == pid and user32.IsWindowVisible(hwnd):
                found_hwnd = hwnd
                return False
            return True

        user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
        if not found_hwnd:
            return

        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040
        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW

        user32.SetWindowPos(found_hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
        user32.SetWindowPos(found_hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
        user32.SetForegroundWindow(found_hwnd)
    except Exception as exc:
        _stderr_print(f"[mdvw] could not bring window to front: {exc!r}")


def _maybe_prompt_association(window: webview.Window) -> None:
    if sys.platform != "win32":
        return
    if config.get("association_prompted"):
        return

    def _later() -> None:
        with contextlib.suppress(Exception):
            window.evaluate_js("window.mdvwPromptAssociation && window.mdvwPromptAssociation()")

    threading.Timer(1.2, _later).start()


def _set_app_user_model_id() -> None:
    """Give the process its own AUMID so the Windows taskbar groups mdvw
    windows separately from the host Python.exe and uses our icon for
    the group thumbnail.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "dev.ThomasRohde.mdvw"
        )
    except Exception as exc:
        _stderr_print(f"[mdvw] could not set AUMID: {exc!r}")


def run(file: Path | None, edit: bool, tray: bool) -> int:
    # Single-instance handoff — only when the tray is on, because that's
    # the only config where an existing process is actually kept alive
    # across invocations. Without the tray, X destroys the window and
    # webview.start() returns, so there's never a server to hand off to.
    if tray and sys.platform == "win32":
        from .ipc import try_handoff

        resolved = file.resolve() if file else None
        if try_handoff(resolved):
            return 0

    _set_app_user_model_id()
    browse_root: Path | None = None
    try:
        browse_root = Path.cwd().resolve()
    except OSError:
        browse_root = None
    # Reopen last file if none was provided on the command line — but only
    # when it belongs to the workspace we were just launched in. Otherwise
    # a `mdvw` in a different project silently reopens an unrelated
    # document while the sidebar/search operate on the new cwd.
    if file is None and browse_root is not None:
        last = state.get("last_file")
        if last:
            try:
                last_path = Path(last).resolve()
            except OSError:
                last_path = None
            if (
                last_path is not None
                and last_path.is_file()
                and last_path.is_relative_to(browse_root)
            ):
                file = last_path
    path, source = _initial_file(file)

    # Resolve the packaged assets dir and rewrite app-asset refs in the
    # template to absolute URLs rooted there. This avoids a document-wide
    # <base href>, which would silently reroute user-document relative
    # URLs (./image.png, ./other.md) to the assets dir.
    assets_dir = Path(str(ASSETS)).resolve()
    assets_base = assets_dir.as_uri().rstrip("/") + "/"
    html = _build_html(
        source, path, edit,
        assets_base=assets_base,
        browse_root=browse_root,
    )

    # Per-instance temp file in a user-writable location — not the package
    # dir (which may be read-only in installed envs) and with a unique
    # name (so concurrent mdvw instances don't race on a shared filename).
    instance_dir = Path(tempfile.mkdtemp(prefix="mdvw-"))
    index = instance_dir / "index.html"
    index.write_text(html, encoding="utf-8")

    api = JsApi()
    api._current_path = path
    api._browse_root = browse_root
    if path is not None:
        api._loaded_fingerprint = _fingerprint(path)
        state.add_recent(str(path))
        state.set_key("last_file", str(path))

    window_title = f"{path.name if path else 'mdvw'} — mdvw"
    window = webview.create_window(
        title=window_title,
        url=index.as_uri(),
        js_api=api,
        width=1100,
        height=780,
        min_size=(600, 400),
    )
    api._window = window

    def _on_loaded() -> None:
        _set_window_icon(window, window_title)
        # Cache HWND and apply the initial title-bar theme from the
        # system setting. The template starts in `data-theme="auto"`, so
        # matching the registry here aligns the chrome with what JS will
        # resolve on first paint. Subsequent changes come through the
        # `set_titlebar_dark` bridge method.
        hwnd = _find_hwnd_by_title(window_title)
        if hwnd is not None:
            api._hwnd = hwnd
            _apply_titlebar_theme(hwnd, _system_apps_dark())
        _bring_to_front()
        _maybe_prompt_association(window)

    window.events.loaded += _on_loaded

    tray_thread = None
    ipc_server = None
    if tray and sys.platform == "win32":
        from .tray import start_tray

        tray_thread = start_tray(window, api)

        from . import tray as tray_mod
        from .ipc import start_server

        def _on_remote_open(p: Path | None) -> None:
            # Always pop the window forward so the user sees the handoff
            # landed — matches what they'd expect from "open another file".
            with contextlib.suppress(Exception):
                window.show()
                window.restore()
            _bring_to_front()
            if tray_mod._tray_icon is not None:
                with contextlib.suppress(Exception):
                    tray_mod._tray_icon.title = "mdvw"
            if p is not None and p.exists() and p.is_file():
                with contextlib.suppress(Exception):
                    api._load(p)

        ipc_server = start_server(_on_remote_open)

    # Dirty-state guard: the closing event runs on the UI thread, so we
    # must NOT call evaluate_js here (that would block waiting on the
    # same thread it was dispatched from and hang the window). Instead
    # trust the `api._dirty` mirror updated by JS on each edit. There's
    # a small race where a user types + closes faster than the bridge
    # can mirror, but an unresponsive close is a worse UX than a rare
    # missed prompt.
    def _on_closing() -> bool:
        if api._quitting:
            return True
        if tray_thread is not None:
            # Close-to-tray: hide the window and veto the destroy. The
            # buffer (and api._dirty) live on in the hidden window; the
            # unsaved-changes prompt moves to the tray's Quit action.
            with contextlib.suppress(Exception):
                window.hide()
            return False
        if not api._dirty:
            return True
        try:
            confirm = window.create_confirmation_dialog(
                "Unsaved changes",
                "You have unsaved edits. Quit anyway?",
            )
        except Exception as exc:
            _stderr_print(
                f"[mdvw] unable to show close confirmation ({exc!r}); "
                "refusing close to protect unsaved edits."
            )
            return False
        if confirm:
            # Prevent re-entrant closing events from spawning more dialogs.
            api._quitting = True
        return bool(confirm)

    window.events.closing += _on_closing

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
        if ipc_server is not None:
            from .ipc import stop_server

            stop_server(ipc_server)
        if tray_thread is not None:
            from .tray import stop_tray

            stop_tray()
    return 0
