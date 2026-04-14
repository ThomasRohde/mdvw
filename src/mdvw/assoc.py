"""Windows .md file association for mdvw.

Writes per-user (HKCU) registry entries — no admin required. The ProgID
`mdvw.Markdown.1` owns the icon + verbs; `.md` registers mdvw as a handler
via `OpenWithProgids`. Refreshes Explorer via SHChangeNotify.
"""
from __future__ import annotations

import contextlib
import shutil
import sys

PROG_ID = "mdvw.Markdown.1"
APP_NAME = "mdvw"


def _mdvw_exe() -> str:
    """Best-guess command to re-invoke mdvw with a file argument."""
    # Frozen PyInstaller exe
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # pip-installed console script
    found = shutil.which("mdvw")
    if found:
        return f'"{found}"'
    # Fallback: python -m mdvw
    return f'"{sys.executable}" -m mdvw'


def _require_windows() -> None:
    if sys.platform != "win32":
        raise SystemExit("File associations are only supported on Windows.")


def register() -> int:
    _require_windows()
    import winreg

    cmd = f'{_mdvw_exe()} "%1"'

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "Markdown Document")
        winreg.SetValueEx(k, "FriendlyTypeName", 0, winreg.REG_SZ, "Markdown Document")

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}\shell\open\command"
    ) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)

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
    print(f"Registered .md/.markdown -> {PROG_ID}")
    return 0


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

    for p in (
        rf"Software\Classes\{PROG_ID}",
        rf"Software\{APP_NAME}",
    ):
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
    print("Unregistered mdvw .md/.markdown associations.")
    return 0


def _refresh_explorer() -> None:
    try:
        import ctypes

        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except Exception:
        pass
