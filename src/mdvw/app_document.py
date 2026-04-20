from __future__ import annotations

import base64
import binascii
import contextlib
import json
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

import webview

from . import __version__, state
from .export import build_standalone_html as _build_standalone_html
from .frontmatter import parse_frontmatter, split_frontmatter
from .render import render_frontmatter_card, render_markdown

if TYPE_CHECKING:
    from .app import JsApi
    from .link_support import LinkIndex


ASSETS = files(__package__) / "assets"

_APP_ASSET_ATTR_RE = re.compile(
    r'(src|href)="((?:vendor/|app(?:/[\w.-]+)*\.(?:css|js)|app\.(?:css|js))[^"]*)"'
)


def _render_with_frontmatter(
    source: str,
    *,
    path: Path | None = None,
    browse_root: Path | None = None,
    doc_base: str | None = None,
    wiki_index: LinkIndex | None = None,
) -> str:
    """Render ``source`` to HTML, prepending a frontmatter card when present."""
    raw_yaml, body = split_frontmatter(source)
    if raw_yaml is not None:
        _meta, _body, err = parse_frontmatter(source)
        card = render_frontmatter_card(raw_yaml, err)
    else:
        card = ""
    if doc_base is None and path is not None:
        doc_base = path.parent.resolve().as_uri() + "/"
    return card + render_markdown(
        body,
        doc_base=doc_base,
        current_path=path,
        browse_root=browse_root,
        _transclude_index=wiki_index,
    )


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


def _rewrite_app_asset_urls(template: str, assets_base: str) -> str:
    """Prefix app-asset references in the template with an absolute URL.

    Replaces `src="vendor/foo.js"` and `href="app/01-theme.css"` with
    their absolute file:// equivalents. Avoids a document-wide
    `<base href>`, which would also reroute user-document relative URLs
    and break `![diagram](./diagram.png)` against the Markdown file's
    directory.
    """
    base = assets_base.rstrip("/") + "/"

    def _sub(match: re.Match[str]) -> str:
        return f'{match.group(1)}="{base}{match.group(2)}"'

    return _APP_ASSET_ATTR_RE.sub(_sub, template)


def _build_html(
    source: str,
    path: Path | None,
    edit: bool,
    assets_base: str = "",
    browse_root: Path | None = None,
    wiki_index: LinkIndex | None = None,
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
    html_body = _render_with_frontmatter(
        source,
        path=path,
        browse_root=browse_root,
        doc_base=doc_base,
        wiki_index=wiki_index,
    )
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
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as file:
            file.write(content)
            file.flush()
            with contextlib.suppress(OSError):
                os.fsync(file.fileno())
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
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            with contextlib.suppress(OSError):
                os.fsync(file.fileno())
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


def _render_current_markdown(
    current_path: Path | None,
    browse_root: Path | None,
    text: str,
    wiki_index: LinkIndex | None = None,
) -> str:
    doc_base = None
    if current_path:
        doc_base = current_path.parent.resolve().as_uri() + "/"
    return _render_with_frontmatter(
        text,
        path=current_path,
        browse_root=browse_root,
        doc_base=doc_base,
        wiki_index=wiki_index,
    )


def _parse_frontmatter_fields(text: str) -> dict | None:
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


def _save_current_file(api: JsApi, content: str, force: bool = False) -> dict:
    """Save the current document atomically."""
    path = api._current_path
    was_untitled = path is None
    if path is None:
        picked = api._pick_save_path()
        if picked is None:
            return {"status": "cancelled"}
        path = picked
        api._current_path = path
        api._loaded_fingerprint = None
    if not force and api._loaded_fingerprint is not None:
        current = _fingerprint(path)
        if current != api._loaded_fingerprint:
            return {"status": "conflict"}
    try:
        _atomic_write_text(path, content)
    except OSError as exc:
        _stderr_print(f"[mdvw] save_file failed: {exc}")
        return {"status": "error", "message": str(exc)}
    api._loaded_fingerprint = _fingerprint(path)
    api._invalidate_link_index()
    if was_untitled:
        state.add_recent(str(path))
        state.set_key("last_file", str(path))
    return {
        "status": "ok",
        "path": str(path),
        "name": path.name,
        "new_file": was_untitled,
    }


def _load_document(api: JsApi, path: Path, reason: str = "open") -> None:
    source = path.read_text(encoding="utf-8")
    html = _render_with_frontmatter(
        source,
        path=path,
        browse_root=api._browse_root,
        wiki_index=api._get_link_index(),
    )
    api._current_path = path
    new_fp = _fingerprint(path)
    if reason != "watch":
        state.add_recent(str(path))
        state.set_key("last_file", str(path))
    if reason == "watch":
        api._pending_fingerprint = new_fp
    else:
        api._loaded_fingerprint = new_fp
        api._pending_fingerprint = None
    if api._window is not None:
        payload = json.dumps({
            "html": html,
            "source": source,
            "name": path.name,
            "path": str(path),
            "reason": reason,
        })
        api._window.evaluate_js(f"window.mdvwSetDocument({payload})")


def _export_html(api: JsApi, content: str) -> dict:
    """Export the current document as self-contained HTML."""
    if api._window is None:
        return {"status": "error", "message": "No window"}
    name = api._current_path.stem if api._current_path else "untitled"
    result = api._window.create_file_dialog(
        webview.SAVE_DIALOG,
        save_filename=f"{name}.html",
        file_types=("HTML (*.html)", "All files (*.*)"),
    )
    path_str = _save_dialog_path(result)
    if path_str is None:
        return {"status": "cancelled"}
    out_path = Path(path_str)
    title = api._current_path.name if api._current_path else "mdvw export"
    doc_dir = api._current_path.parent if api._current_path else None
    html = _build_standalone_html(content, doc_dir=doc_dir, title=title)
    try:
        _atomic_write_text(out_path, html)
    except OSError as exc:
        return {"status": "error", "message": str(exc)}
    return {"status": "ok", "path": str(out_path)}


def _save_image(api: JsApi, data_url: str, suggested_name: str) -> dict:
    """Save a base64 data-URL image to the document's images/ folder."""
    if api._current_path is None:
        return {"status": "error", "message": "Save the document first"}
    if not isinstance(data_url, str):
        return {"status": "error", "message": "Invalid image data"}

    doc_dir = api._current_path.parent
    images_dir = doc_dir / "images"
    images_dir.mkdir(exist_ok=True)

    match = re.match(r"data:image/([\w+.-]+);base64,(.+)", data_url, re.DOTALL)
    if not match:
        return {"status": "error", "message": "Invalid image data"}
    ext = match.group(1).lower()
    if ext == "jpeg":
        ext = "jpg"
    if ext not in api._IMAGE_EXT_WHITELIST:
        return {"status": "error", "message": f"Unsupported image type: {ext}"}
    raw = match.group(2)

    max_encoded = (api._IMAGE_MAX_DECODED_BYTES * 4 + 2) // 3 + 16
    if len(raw) > max_encoded:
        return {"status": "error", "message": "Image too large"}

    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return {"status": "error", "message": "Invalid image data"}
    if len(data) > api._IMAGE_MAX_DECODED_BYTES:
        return {"status": "error", "message": "Image too large"}

    ts = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    name = suggested_name or f"image-{ts}.{ext}"
    name = re.sub(r"[^\w.\-]", "_", name)
    if not name.lower().endswith(f".{ext}"):
        name = f"{name}.{ext}"

    target = images_dir / name
    if target.exists():
        stem = target.stem
        index = 2
        while target.exists():
            target = images_dir / f"{stem}-{index}{target.suffix}"
            index += 1

    try:
        target.resolve().relative_to(doc_dir.resolve())
    except ValueError:
        return {"status": "error", "message": "Path traversal rejected"}

    try:
        _atomic_write_bytes(target, data)
    except OSError as exc:
        return {"status": "error", "message": str(exc)}

    relative = target.relative_to(doc_dir).as_posix()
    return {"status": "ok", "relative_path": relative}
