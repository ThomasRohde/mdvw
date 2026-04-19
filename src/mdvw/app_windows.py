from __future__ import annotations

import contextlib
import os
import sys
import threading
from importlib.resources import files
from pathlib import Path

import webview

from . import config
from .app_document import _stderr_print

ASSETS = files(__package__) / "assets"


def _apply_titlebar_theme(hwnd: int, dark: bool) -> None:
    """Toggle Windows immersive dark-mode title bar via DWM."""
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
    """Return True iff Windows is currently using the dark apps theme."""
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
    """Attach the packaged icon.ico to the running window via WM_SETICON."""
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
    """Force our window to the foreground on Windows."""
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
    """Give the process its own AUMID for separate Windows taskbar grouping."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "dev.ThomasRohde.mdvw"
        )
    except Exception as exc:
        _stderr_print(f"[mdvw] could not set AUMID: {exc!r}")
