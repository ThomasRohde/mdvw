from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import ClassVar

import webview

# Silence pywebview's internal attribute-introspection warnings (e.g. the
# .NET Rectangle.Empty self-recursion spam and WebView2 shutdown class
# unregister noise — both cosmetic).
for _name in ("pywebview", "pywebview.util", "pywebview.platforms.edgechromium", "webview"):
    logging.getLogger(_name).setLevel(logging.CRITICAL)


class _EmptySpamFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "Empty.Empty" not in record.getMessage()


logging.getLogger().addFilter(_EmptySpamFilter())

from . import config, state  # noqa: E402  (must run after logger filter)
from .app_document import (  # noqa: E402
    ASSETS,
    _atomic_write_text,
    _build_html,
    _export_html,
    _fingerprint,
    _json_for_script_tag,
    _load_document,
    _parse_frontmatter_fields,
    _render_current_markdown,
    _save_current_file,
    _save_dialog_path,
    _save_image,
)
from .app_notes import (  # noqa: E402
    _create_note,
    _create_wiki_note,
    _get_note_templates,
    _open_daily_note,
)
from .app_preview import _preview_wiki_link  # noqa: E402
from .app_rename import _move_current_note  # noqa: E402
from .app_runtime import _start_app  # noqa: E402
from .app_windows import _apply_titlebar_theme  # noqa: E402
from .app_workspace import (  # noqa: E402
    _clear_recent_files,
    _get_graph,
    _get_incoming_links,
    _get_link_index,
    _get_recent_files,
    _get_workspace_tasks,
    _invalidate_link_index,
    _list_markdown_dir,
    _open_directory,
    _open_file,
    _open_path,
    _open_recent,
    _open_wiki_link,
    _resolve_wiki_link,
    _run_diagnostics,
    _save_ui_state,
    _search_filenames,
    _search_wiki_targets,
    _search_workspace,
    _toggle_workspace_task,
)
from .links import LinkIndex  # noqa: E402

__all__ = [
    "ASSETS",
    "JsApi",
    "_atomic_write_text",
    "_build_html",
    "_fingerprint",
    "_json_for_script_tag",
    "run",
]


class JsApi:
    _IMAGE_EXT_WHITELIST: ClassVar[frozenset[str]] = frozenset(
        {"png", "jpg", "jpeg", "gif", "webp"}
    )
    _IMAGE_MAX_DECODED_BYTES: ClassVar[int] = 25 * 1024 * 1024

    def __init__(self) -> None:
        self._window: webview.Window | None = None
        self._current_path: Path | None = None
        self._loaded_fingerprint: tuple[int, int] | None = None
        self._pending_fingerprint: tuple[int, int] | None = None
        self._dirty: bool = False
        self._quitting: bool = False
        self._browse_root: Path | None = None
        self._hwnd: int | None = None
        self._link_index: LinkIndex | None = None
        self._link_index_fp: tuple[tuple[str, int, int], ...] | None = None
        self._link_index_root: Path | None = None

    def set_dirty(self, value: bool) -> None:
        self._dirty = bool(value)

    def set_titlebar_dark(self, dark: bool) -> None:
        if sys.platform != "win32" or self._hwnd is None:
            return
        _apply_titlebar_theme(self._hwnd, bool(dark))

    def confirm_quit(self) -> None:
        from .tray import stop_tray

        self._quitting = True
        stop_tray()
        if self._window is not None:
            self._window.destroy()

    def ack_reload(self) -> bool:
        if self._pending_fingerprint is None:
            return False
        self._loaded_fingerprint = self._pending_fingerprint
        self._pending_fingerprint = None
        return True

    def render_markdown(self, text: str) -> str:
        return _render_current_markdown(
            self._current_path,
            self._browse_root,
            text,
            wiki_index=self._get_link_index(),
        )

    def save_file(self, content: str, force: bool = False) -> dict:
        return _save_current_file(self, content, force=force)

    def open_external(self, url: str) -> bool:
        import webbrowser

        if not isinstance(url, str) or not url:
            return False
        scheme = url.split(":", 1)[0].lower() if ":" in url else ""
        if scheme in ("http", "https", "mailto"):
            webbrowser.open(url, new=2)
            return True
        return False

    def list_markdown_dir(self, path_str: str = "") -> dict | None:
        return _list_markdown_dir(self, path_str)

    def open_path(self, path_str: str) -> bool:
        return _open_path(self, path_str)

    def open_file(self) -> bool:
        return _open_file(self)

    def open_directory(self) -> bool:
        return _open_directory(self)

    def open_recent(self, path_str: str) -> bool:
        return _open_recent(self, path_str)

    def register_association(self) -> bool:
        from .assoc import register

        ok = register() == 0
        config.set_key("association_prompted", True)
        return ok

    def decline_association(self) -> None:
        config.set_key("association_prompted", True)

    def save_ui_state(self, data: dict) -> None:
        _save_ui_state(data)

    def get_ui_state(self) -> dict:
        return state.load()

    def get_recent_files(self) -> list[dict]:
        return _get_recent_files()

    def clear_recent_files(self) -> None:
        _clear_recent_files()

    def search_filenames(self, query: str, max_results: int = 50) -> list[dict]:
        return _search_filenames(self, query, max_results=max_results)

    def _invalidate_link_index(self) -> None:
        _invalidate_link_index(self)

    def _get_link_index(self) -> LinkIndex | None:
        return _get_link_index(self)

    def resolve_wiki_link(self, raw_target: str) -> dict:
        return _resolve_wiki_link(self, raw_target)

    def open_wiki_link(self, raw_target: str) -> dict:
        return _open_wiki_link(self, raw_target)

    def preview_wiki_link(self, raw_target: str) -> dict:
        return _preview_wiki_link(self, raw_target)

    def create_wiki_note(self, raw_target: str) -> dict:
        return _create_wiki_note(self, raw_target)

    def create_note(self, raw_target: str, template_path: str = "") -> dict:
        return _create_note(self, raw_target, template_path=template_path)

    def get_note_templates(self) -> list[dict]:
        return _get_note_templates(self)

    def open_daily_note(self, date_str: str = "") -> dict:
        return _open_daily_note(self, date_str=date_str)

    def move_current_note(self, raw_target: str) -> dict:
        return _move_current_note(self, raw_target)

    def get_incoming_links(self, path_str: str | None = None) -> list[dict]:
        return _get_incoming_links(self, path_str)

    def get_workspace_tasks(self, include_done: bool = False) -> list[dict]:
        return _get_workspace_tasks(self, include_done=include_done)

    def toggle_workspace_task(self, path_str: str, line: int) -> dict:
        return _toggle_workspace_task(self, path_str, line)

    def search_wiki_targets(
        self,
        query: str,
        source_path: str | None = None,
        max_results: int = 50,
    ) -> list[dict]:
        return _search_wiki_targets(
            self,
            query,
            source_path=source_path,
            max_results=max_results,
        )

    def get_graph(self, options: dict | None = None) -> dict:
        return _get_graph(self, options)

    def save_image(self, data_url: str, suggested_name: str) -> dict:
        return _save_image(self, data_url, suggested_name)

    def run_diagnostics(self, content: str) -> list[dict]:
        return _run_diagnostics(self, content)

    def export_html(self, content: str) -> dict:
        return _export_html(self, content)

    def print_document(self) -> None:
        if self._window is not None:
            self._window.evaluate_js("window.print()")

    def search_workspace(self, query: str, case_sensitive: bool = False) -> list[dict]:
        return _search_workspace(self, query, case_sensitive=case_sensitive)

    def parse_frontmatter_fields(self, text: str) -> dict | None:
        return _parse_frontmatter_fields(text)

    def _save_dialog_path(self, result: object) -> str | None:
        return _save_dialog_path(result)

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
        _load_document(self, path, reason=reason)


def run(file: Path | None, edit: bool, tray: bool) -> int:
    return _start_app(file, edit, tray, JsApi())
