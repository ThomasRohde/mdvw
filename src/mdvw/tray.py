from __future__ import annotations

import contextlib
import sys
import threading
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw

if TYPE_CHECKING:
    import webview

_tray_icon = None
_tray_thread: threading.Thread | None = None


def _make_icon(dark: bool) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bg = (201, 100, 66, 255) if not dark else (224, 128, 96, 255)
    d.rounded_rectangle((2, 2, size - 2, size - 2), radius=12, fill=bg)
    # "M" glyph
    d.text((16, 8), "M", fill=(255, 255, 255, 255))
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
