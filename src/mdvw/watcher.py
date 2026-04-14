from __future__ import annotations

import asyncio
import contextlib
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from watchfiles import Change, awatch

if TYPE_CHECKING:
    from .app import JsApi


_SKIP_SUFFIXES = (".tmp", ".swp", ".swx", ".bak")
_SKIP_PREFIXES = ("~$", ".~")


def _is_noise(path: Path) -> bool:
    n = path.name
    return n.endswith(_SKIP_SUFFIXES) or n.startswith(_SKIP_PREFIXES)


def start_watcher(file: Path, api: JsApi) -> threading.Thread:
    """Watch `file` and reload it in `api` on external changes. Runs in a daemon thread."""
    stop_event = threading.Event()

    async def _run() -> None:
        target = file.resolve()
        async for changes in awatch(
            target.parent,
            watch_filter=None,
            debounce=200,
            step=50,
            stop_event=stop_event,
        ):
            for change, path_str in changes:
                p = Path(path_str)
                if _is_noise(p):
                    continue
                if p.resolve() != target:
                    continue
                if change in (Change.added, Change.modified):
                    with contextlib.suppress(OSError):
                        api._load(p, reason="watch")

    def _thread() -> None:
        with contextlib.suppress(Exception):
            asyncio.run(_run())

    t = threading.Thread(target=_thread, name="mdvw-watcher", daemon=True)
    t.start()
    t._stop_event = stop_event  # type: ignore[attr-defined]
    return t


def stop_watcher(thread: threading.Thread) -> None:
    ev = getattr(thread, "_stop_event", None)
    if ev is not None:
        ev.set()
