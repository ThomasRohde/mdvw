"""Windows .md file association for mdvw.

Writes per-user (HKCU) registry entries — no admin required. The ProgID
`mdvw.Markdown.1` owns the icon + verbs; `.md` registers mdvw as a handler
via `OpenWithProgids`. Refreshes Explorer via SHChangeNotify.
"""
from __future__ import annotations

import contextlib
import shutil
import sys
from importlib.resources import files
from pathlib import Path

PROG_ID = "mdvw.Markdown.1"
APP_NAME = "mdvw"


def _stdout_print(message: str) -> None:
    """Best-effort stdout print. Under pythonw / a windowed build
    `sys.stdout` may be None; the register/unregister commands may also
    be invoked from the in-app JS bridge where no console is attached.
    """
    stream = sys.stdout
    if stream is None:
        return
    with contextlib.suppress(Exception):
        print(message, file=stream)


def _mdvw_exe_path() -> str | None:
    """Absolute path to the installed mdvw launcher, or None when running
    from `python -m mdvw` without a generated exe."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return shutil.which("mdvw")


def _mdvw_launch_cmd() -> str:
    """Command string suitable for a registry `shell\\open\\command`."""
    p = _mdvw_exe_path()
    if p:
        return f'"{p}"'
    return f'"{sys.executable}" -m mdvw'


def _icon_path() -> str | None:
    """Absolute filesystem path to the packaged icon.ico, or None if missing."""
    try:
        ico = Path(str(files("mdvw") / "assets" / "icon.ico"))
    except (ModuleNotFoundError, FileNotFoundError):
        return None
    return str(ico) if ico.exists() else None


def _require_windows() -> None:
    if sys.platform != "win32":
        raise SystemExit("File associations are only supported on Windows.")


def register(open_settings: bool = False) -> int:
    _require_windows()
    import winreg

    exe_path = _mdvw_exe_path()
    cmd = f'{_mdvw_launch_cmd()} "%1"'
    icon = _icon_path()

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "Markdown Document")
        winreg.SetValueEx(k, "FriendlyTypeName", 0, winreg.REG_SZ, "Markdown Document")

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}\shell\open\command"
    ) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)

    # ProgID icon — what Explorer draws on a .md file once mdvw is the default
    # (and what the "Open With" dialog sometimes uses for the ProgID row).
    if icon:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}\DefaultIcon"
        ) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, icon)

    # Applications\<exe>\DefaultIcon overrides the icon embedded in the launcher
    # itself. Without this, pip's gui_launcher stub icon (a generic pyramid)
    # shows up next to "mdvw.EXE" in the Open With dialog.
    if icon and exe_path:
        exe_name = Path(exe_path).name
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, rf"Software\Classes\Applications\{exe_name}"
        ) as k:
            winreg.SetValueEx(k, "FriendlyAppName", 0, winreg.REG_SZ, "mdvw")
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            rf"Software\Classes\Applications\{exe_name}\DefaultIcon",
        ) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, icon)
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            rf"Software\Classes\Applications\{exe_name}\shell\open\command",
        ) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
        # Advertise which types this exe knows how to open (drives the
        # "Suggested apps" grouping in the Open With dialog).
        for ext in (".md", ".markdown"):
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                rf"Software\Classes\Applications\{exe_name}\SupportedTypes",
            ) as k:
                winreg.SetValueEx(k, ext, 0, winreg.REG_SZ, "")

    # Register under .md's OpenWithProgids (non-destructive — doesn't steal default).
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, r"Software\Classes\.md\OpenWithProgids"
    ) as k:
        winreg.SetValueEx(k, PROG_ID, 0, winreg.REG_NONE, b"")
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, r"Software\Classes\.markdown\OpenWithProgids"
    ) as k:
        winreg.SetValueEx(k, PROG_ID, 0, winreg.REG_NONE, b"")

    # Register app in RegisteredApplications for "Open with" UX.
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, rf"Software\{APP_NAME}\Capabilities"
    ) as k:
        winreg.SetValueEx(k, "ApplicationName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(
            k, "ApplicationDescription", 0, winreg.REG_SZ,
            "Fast, portable, fully offline Markdown viewer/editor.",
        )
        if icon:
            winreg.SetValueEx(k, "ApplicationIcon", 0, winreg.REG_SZ, icon)
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, rf"Software\{APP_NAME}\Capabilities\FileAssociations"
    ) as k:
        winreg.SetValueEx(k, ".md", 0, winreg.REG_SZ, PROG_ID)
        winreg.SetValueEx(k, ".markdown", 0, winreg.REG_SZ, PROG_ID)
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, r"Software\RegisteredApplications"
    ) as k:
        winreg.SetValueEx(
            k, APP_NAME, 0, winreg.REG_SZ, rf"Software\{APP_NAME}\Capabilities"
        )

    _refresh_explorer()
    _stdout_print(f"Registered .md/.markdown -> {PROG_ID}")
    _stdout_print(
        "To make mdvw the default viewer, open Settings → Default apps, "
        "search for mdvw, and set its file types there. (Windows doesn't "
        "allow apps to set themselves as default without a user action.)"
    )
    if open_settings:
        _open_default_apps_settings()
    return 0


def _open_default_apps_settings() -> None:
    """Open Windows Settings to the Default Apps page, preselected on mdvw."""
    import os

    with contextlib.suppress(OSError):
        os.startfile(f"ms-settings:defaultapps?registeredAppUser={APP_NAME}")


def unregister() -> int:
    _require_windows()
    import winreg

    def _del_tree(root, path: str) -> None:
        try:
            with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as k:
                while True:
                    try:
                        sub = winreg.EnumKey(k, 0)
                    except OSError:
                        break
                    _del_tree(root, f"{path}\\{sub}")
            winreg.DeleteKey(root, path)
        except FileNotFoundError:
            pass

    paths = [
        rf"Software\Classes\{PROG_ID}",
        rf"Software\{APP_NAME}",
    ]
    exe_path = _mdvw_exe_path()
    if exe_path:
        paths.append(rf"Software\Classes\Applications\{Path(exe_path).name}")
    for p in paths:
        _del_tree(winreg.HKEY_CURRENT_USER, p)

    for ext in (".md", ".markdown"):
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                rf"Software\Classes\{ext}\OpenWithProgids",
                0, winreg.KEY_ALL_ACCESS,
            ) as k, contextlib.suppress(FileNotFoundError):
                winreg.DeleteValue(k, PROG_ID)
        except FileNotFoundError:
            pass

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\RegisteredApplications",
            0, winreg.KEY_ALL_ACCESS,
        ) as k, contextlib.suppress(FileNotFoundError):
            winreg.DeleteValue(k, APP_NAME)
    except FileNotFoundError:
        pass

    _refresh_explorer()
    _stdout_print("Unregistered mdvw .md/.markdown associations.")
    return 0


def _refresh_explorer() -> None:
    try:
        import ctypes

        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except Exception:
        pass
