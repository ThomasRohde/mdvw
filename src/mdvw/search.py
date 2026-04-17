"""Workspace text search for mdvw.

Scans Markdown files under a root directory for a text query, returning
matching lines with context.  Designed for incremental on-demand use (no
persisted index).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".git", ".hg", ".svn", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
})

_MD_SUFFIXES = {".md", ".markdown"}


def search_workspace(
    root: Path,
    query: str,
    *,
    case_sensitive: bool = False,
    max_results: int = 100,
) -> list[dict]:
    """Search Markdown files under *root* for *query*.

    Returns a list of dicts: ``{path, name, relative, line, col, context}``.
    Caps total results at *max_results* and total files scanned at 10 000.
    """
    if not query or not root.is_dir():
        return []

    try:
        root_resolved = root.resolve()
    except OSError:
        return []

    flags = 0 if case_sensitive else re.IGNORECASE
    escaped = re.escape(query)
    pattern = re.compile(escaped, flags)

    results: list[dict] = []
    files_scanned = 0

    # `followlinks=False` (the default) skips symlinked *directories*, but
    # symlinked *files* inside the tree still get read by `read_text`. We
    # must resolve each file candidate and verify it stays under the
    # resolved root — otherwise a symlink like `notes.md -> C:/secrets.txt`
    # would leak arbitrary on-disk content through the search UI.
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS and not d.startswith(".")
        ]
        for name in filenames:
            if Path(name).suffix.lower() not in _MD_SUFFIXES:
                continue
            full = Path(dirpath) / name
            files_scanned += 1
            if files_scanned > 10_000:
                return results
            try:
                if full.is_symlink():
                    continue
                resolved = full.resolve()
            except OSError:
                continue
            if not resolved.is_relative_to(root_resolved):
                continue
            try:
                text = resolved.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line_text in enumerate(text.splitlines(), start=1):
                m = pattern.search(line_text)
                if not m:
                    continue
                try:
                    rel = str(full.relative_to(root))
                except ValueError:
                    rel = str(full)
                results.append({
                    "path": str(full),
                    "name": name,
                    "relative": rel,
                    "line": lineno,
                    "col": m.start() + 1,
                    "context": line_text.strip()[:200],
                })
                if len(results) >= max_results:
                    return results

    return results
