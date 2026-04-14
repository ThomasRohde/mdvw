from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mdvw", description="Offline Markdown viewer/editor.")
    p.add_argument("file", nargs="?", type=Path, help="Markdown file to open")
    p.add_argument("--edit", action="store_true", help="Start in edit mode")
    p.add_argument("--no-tray", action="store_true", help="Disable system tray icon")
    p.add_argument("--register", action="store_true", help="Associate .md files with mdvw")
    p.add_argument("--unregister", action="store_true", help="Remove .md association")
    p.add_argument("-V", "--version", action="version", version=f"mdvw {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.register or args.unregister:
        from .assoc import register, unregister

        return register() if args.register else unregister()

    from .app import run

    return run(file=args.file, edit=args.edit, tray=not args.no_tray)


if __name__ == "__main__":
    sys.exit(main())
