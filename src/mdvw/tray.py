from __future__ import annotations

import contextlib
import sys
import threading
from importlib.resources import files
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    import webview

_ICON_PATH = files(__package__) / "assets" / "icon.ico"

_tray_icon = None
_tray_thread: threading.Thread | None = None


def _make_icon(dark: bool) -> Image.Image:
    """Load the packaged Markdown-mark icon, invert for dark taskbars.

    The tray area on Windows is usually dark on light mode and light on
    dark mode, so invert the glyph when the system is in dark mode so
    the M↓ mark stays visible.
    """
    img = Image.open(str(_ICON_PATH))
    try:
        img.size = (32, 32)
        img.load()
    except Exception:
        pass
    img = img.convert("RGBA")
    if dark:
        # Invert RGB channels (keep alpha). Black glyph → white glyph.
        r, g, b, a = img.split()
        inv = Image.merge("RGB", (r, g, b)).point(lambda v: 255 - v).split()
        img = Image.merge("RGBA", (*inv, a))
    return img


def _system_dark() -> bool:
    try:
        import darkdetect

        return bool(darkdetect.isDark())
    except Exception:
        return False


def start_tray(window: webview.Window) -> threading.Thread:
    """Start a pystray tray icon in a background thread.

    Left-click (default) shows the window; menu offers Show/Hide and Quit.
    """
    if sys.platform != "win32":
        raise RuntimeError("Tray only supported on Windows")
    import pystray
    from pystray import Menu, MenuItem

    global _tray_icon, _tray_thread

    def on_show(icon, item):
        try:
            window.show()
            window.restore()
        except Exception:
            pass

    def on_hide(icon, item):
        with contextlib.suppress(Exception):
            window.hide()

    def on_quit(icon, item):
        icon.visible = False
        icon.stop()
        with contextlib.suppress(Exception):
            window.destroy()

    menu = Menu(
        MenuItem("Show", on_show, default=True),
        MenuItem("Hide", on_hide),
        Menu.SEPARATOR,
        MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon("mdvw", _make_icon(_system_dark()), "mdvw", menu)
    _tray_icon = icon

    def _theme_watcher() -> None:
        import time

        cur = _system_dark()
        while _tray_icon is icon and icon.visible:
            time.sleep(2.0)
            nxt = _system_dark()
            if nxt != cur:
                cur = nxt
                with contextlib.suppress(Exception):
                    icon.icon = _make_icon(cur)

    t = threading.Thread(target=icon.run, name="mdvw-tray", daemon=True)
    t.start()
    threading.Thread(target=_theme_watcher, name="mdvw-tray-theme", daemon=True).start()
    _tray_thread = t
    return t


def stop_tray() -> None:
    global _tray_icon
    if _tray_icon is not None:
        try:
            _tray_icon.visible = False
            _tray_icon.stop()
        except Exception:
            pass
        _tray_icon = None
