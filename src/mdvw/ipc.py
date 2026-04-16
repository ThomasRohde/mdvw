"""Single-instance handoff over a localhost loopback socket.

When the tray is running the first mdvw process sticks around after its
window is hidden; the tray icon is the whole point of that. A *second*
`mdvw file.md` invocation should reuse that warm process instead of
spinning up a second pywebview, second tray icon, second WebView2 host.

First launch: bind 127.0.0.1:<ephemeral>, write the port + pid to a
lockfile, accept newline-delimited JSON commands on a daemon thread.

Second launch: read the lockfile, connect, send `{"path": "..."}`,
exit 0. If the lockfile is missing or stale (connect refused), the
caller falls through and becomes the server itself.

Loopback-only — never bind 0.0.0.0. The protocol is unauthenticated,
so any local process (same user) can hand us a path; that's the same
trust boundary as the CLI and fine for this use.
"""
from __future__ import annotations

import contextlib
import json
import os
import socket
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from . import config

_HOST = "127.0.0.1"
_LOCK_NAME = "instance.lock"


def _lock_path() -> Path:
    # Piggyback on config's dir so we don't sprawl another data location.
    return Path(config.config_path()).parent / _LOCK_NAME


def _read_lock() -> tuple[int, int] | None:
    p = _lock_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return int(data["port"]), int(data["pid"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None


def _write_lock(port: int) -> None:
    p = _lock_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8"
    )


def _clear_lock() -> None:
    with contextlib.suppress(OSError):
        _lock_path().unlink(missing_ok=True)


def try_handoff(file: Path | None) -> bool:
    """If another mdvw instance is listening, hand `file` to it and return True.

    Returns False if no running instance was reached — caller should proceed
    to start a new one.
    """
    lock = _read_lock()
    if lock is None:
        return False
    port, pid = lock
    if sys.platform == "win32":
        with contextlib.suppress(Exception):
            import ctypes

            ctypes.windll.user32.AllowSetForegroundWindow(pid)
    payload = json.dumps({"path": str(file) if file else ""}) + "\n"
    try:
        with socket.create_connection((_HOST, port), timeout=1.0) as s:
            s.sendall(payload.encode("utf-8"))
            # Best-effort ack — we don't really care about the reply.
            with contextlib.suppress(OSError):
                s.settimeout(1.0)
                s.recv(64)
        return True
    except OSError:
        # Stale lockfile (process gone / port reused by nothing).
        _clear_lock()
        return False


def start_server(handler: Callable[[Path | None], None]) -> socket.socket | None:
    """Bind a loopback socket, write the lockfile, spawn an accept loop.

    `handler` is called on the accept thread with the Path (or None) sent
    by the peer. Returns the server socket so the caller can close it on
    shutdown, or None if binding failed.
    """
    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((_HOST, 0))
        srv.listen(4)
    except OSError:
        return None
    port = srv.getsockname()[1]
    _write_lock(port)

    def _accept_loop() -> None:
        while True:
            try:
                conn, _addr = srv.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(2.0)
                    buf = b""
                    while b"\n" not in buf and len(buf) < 8192:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                    line = buf.split(b"\n", 1)[0]
                    data = json.loads(line.decode("utf-8"))
                    raw = data.get("path") or ""
                    path = Path(raw) if raw else None
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                # Never let a handler crash take out the server.
                with contextlib.suppress(Exception):
                    handler(path)
                with contextlib.suppress(OSError):
                    conn.sendall(b"OK\n")

    threading.Thread(target=_accept_loop, name="mdvw-ipc", daemon=True).start()
    return srv


def stop_server(srv: socket.socket | None) -> None:
    if srv is not None:
        with contextlib.suppress(OSError):
            srv.close()
    _clear_lock()
