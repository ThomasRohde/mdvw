from __future__ import annotations

import contextlib
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import webview

from . import state
from .app_document import ASSETS, _build_html, _fingerprint, _initial_file, _stderr_print
from .app_windows import (
    _apply_titlebar_theme,
    _bring_to_front,
    _find_hwnd_by_title,
    _maybe_prompt_association,
    _set_app_user_model_id,
    _set_window_icon,
    _system_apps_dark,
)

if TYPE_CHECKING:
    from .app import JsApi


def _maybe_try_handoff(file: Path | None, tray: bool) -> bool:
    if not tray or sys.platform != "win32":
        return False
    from .ipc import try_handoff

    resolved = file.resolve() if file else None
    return try_handoff(resolved)


def _restore_launch_file(file: Path | None) -> tuple[Path | None, Path | None]:
    browse_root: Path | None = None
    persisted_root = state.get("last_browse_root")
    if isinstance(persisted_root, str) and persisted_root:
        try:
            candidate_root = Path(persisted_root).resolve()
        except OSError:
            candidate_root = None
        if candidate_root is not None and candidate_root.is_dir():
            browse_root = candidate_root
    if browse_root is None:
        try:
            browse_root = Path.cwd().resolve()
        except OSError:
            browse_root = None
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
    return file, browse_root


def _create_instance_page(
    source: str,
    path: Path | None,
    edit: bool,
    browse_root: Path | None,
) -> tuple[Path, Path]:
    assets_dir = Path(str(ASSETS)).resolve()
    assets_base = assets_dir.as_uri().rstrip("/") + "/"
    html = _build_html(
        source, path, edit,
        assets_base=assets_base,
        browse_root=browse_root,
    )
    instance_dir = Path(tempfile.mkdtemp(prefix="mdvw-"))
    index = instance_dir / "index.html"
    index.write_text(html, encoding="utf-8")
    return instance_dir, index


def _seed_api(api: JsApi, path: Path | None, browse_root: Path | None) -> None:
    api._current_path = path
    api._browse_root = browse_root
    if path is not None:
        api._loaded_fingerprint = _fingerprint(path)
        state.add_recent(str(path))
        state.set_key("last_file", str(path))


def _attach_loaded_handler(window: webview.Window, api: JsApi, window_title: str) -> None:
    def _on_loaded() -> None:
        _set_window_icon(window, window_title)
        hwnd = _find_hwnd_by_title(window_title)
        if hwnd is not None:
            api._hwnd = hwnd
            _apply_titlebar_theme(hwnd, _system_apps_dark())
        _bring_to_front()
        _maybe_prompt_association(window)

    window.events.loaded += _on_loaded


def _start_tray_and_ipc(
    window: webview.Window,
    api: JsApi,
    tray: bool,
) -> tuple[object | None, object | None]:
    tray_thread = None
    ipc_server = None
    if tray and sys.platform == "win32":
        from .tray import start_tray

        tray_thread = start_tray(window, api)

        from . import tray as tray_mod
        from .ipc import start_server

        def _on_remote_open(path: Path | None) -> None:
            with contextlib.suppress(Exception):
                window.show()
                window.restore()
            _bring_to_front()
            if tray_mod._tray_icon is not None:
                with contextlib.suppress(Exception):
                    tray_mod._tray_icon.title = "mdvw"
            if path is not None and path.exists() and path.is_file():
                with contextlib.suppress(Exception):
                    api._load(path)

        ipc_server = start_server(_on_remote_open)
    return tray_thread, ipc_server


def _attach_closing_handler(
    window: webview.Window,
    api: JsApi,
    tray_thread: object | None,
) -> None:
    def _on_closing() -> bool:
        if api._quitting:
            return True
        if tray_thread is not None:
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
            api._quitting = True
        return bool(confirm)

    window.events.closing += _on_closing


def _maybe_start_watcher(file: Path | None, edit: bool, api: JsApi) -> None:
    if file and file.exists() and not edit:
        from .watcher import start_watcher

        start_watcher(file, api)


def _cleanup_runtime(
    index: Path,
    instance_dir: Path,
    ipc_server: object | None,
    tray_thread: object | None,
) -> None:
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


def _create_window(index: Path, api: JsApi, window_title: str) -> webview.Window:
    window = webview.create_window(
        title=window_title,
        url=index.as_uri(),
        js_api=api,
        width=1100,
        height=780,
        min_size=(600, 400),
    )
    api._window = window
    return window


def _start_app(file: Path | None, edit: bool, tray: bool, api: JsApi) -> int:
    if _maybe_try_handoff(file, tray):
        return 0

    _set_app_user_model_id()
    file, browse_root = _restore_launch_file(file)
    path, source = _initial_file(file)
    instance_dir, index = _create_instance_page(source, path, edit, browse_root)
    _seed_api(api, path, browse_root)

    window_title = f"{path.name if path else 'mdvw'} — mdvw"
    window = _create_window(index, api, window_title)
    _attach_loaded_handler(window, api, window_title)
    tray_thread, ipc_server = _start_tray_and_ipc(window, api, tray)
    _attach_closing_handler(window, api, tray_thread)
    _maybe_start_watcher(file, edit, api)

    try:
        webview.start()
    finally:
        _cleanup_runtime(index, instance_dir, ipc_server, tray_thread)
    return 0
