"""Workspace task extraction for mdvw."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .app_document import _atomic_write_text

_SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".git", ".hg", ".svn", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
})

_MD_SUFFIXES = {".md", ".markdown"}
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+[ \t]*)?$")
_TASK_RE = re.compile(r"^\s*(?:[-+*]|\d+\.)\s+\[([ xX])\]\s*(.*?)\s*$")
_TASK_LINE_RE = re.compile(r"^(\s*(?:[-+*]|\d+\.)\s+\[)([ xX])(\]\s*.*)$")
_FENCE_RE = re.compile(r"^\s{0,3}((`{3,})|(~{3,})).*$")


def _normalize_inline_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def parse_markdown_tasks(text: str, *, include_done: bool = False) -> list[dict]:
    """Extract markdown task items from text.

    Returns a list of dicts: ``{line, checked, text, heading, context}``.
    Fenced code blocks are ignored.
    """
    tasks: list[dict] = []
    current_heading = ""
    fence_char = ""
    fence_len = 0

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.lstrip()

        if fence_char:
            if (
                stripped.startswith(fence_char * fence_len)
                and not stripped[fence_len:].strip(fence_char).strip()
            ):
                fence_char = ""
                fence_len = 0
            continue

        fence_match = _FENCE_RE.match(raw_line)
        if fence_match:
            fence = fence_match.group(1)
            fence_char = fence[0]
            fence_len = len(fence)
            continue

        heading_match = _HEADING_RE.match(raw_line)
        if heading_match:
            current_heading = _normalize_inline_text(heading_match.group(2))
            continue

        task_match = _TASK_RE.match(raw_line)
        if not task_match:
            continue

        checked = task_match.group(1).lower() == "x"
        if checked and not include_done:
            continue

        task_text = _normalize_inline_text(task_match.group(2))
        if not task_text:
            continue

        tasks.append({
            "line": lineno,
            "checked": checked,
            "text": task_text,
            "heading": current_heading,
            "context": raw_line.strip()[:200],
        })

    return tasks


def list_workspace_tasks(
    root: Path,
    *,
    include_done: bool = False,
    max_results: int = 500,
) -> list[dict]:
    """List Markdown tasks under *root*.

    Returns a list of dicts: ``{path, name, relative, line, checked, text,
    heading, context}``. Caps total results at *max_results* and total files
    scanned at 10 000.
    """
    if not root.is_dir():
        return []

    try:
        root_resolved = root.resolve()
    except OSError:
        return []

    results: list[dict] = []
    files_scanned = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            (
                dirname
                for dirname in dirnames
                if dirname not in _SKIP_DIRS and not dirname.startswith(".")
            ),
            key=str.casefold,
        )
        for name in sorted(filenames, key=str.casefold):
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

            try:
                relative = str(full.relative_to(root))
            except ValueError:
                relative = str(full)

            for task in parse_markdown_tasks(text, include_done=include_done):
                results.append({
                    "path": str(resolved),
                    "name": name,
                    "relative": relative,
                    **task,
                })
                if len(results) >= max_results:
                    return results

    return results


def _resolve_workspace_task_path(root: Path, path_str: str) -> Path | None:
    if not isinstance(path_str, str) or not path_str:
        return None

    try:
        root_resolved = root.resolve()
        target = Path(path_str).resolve()
    except OSError:
        return None

    if not target.is_relative_to(root_resolved):
        return None
    if target.suffix.lower() not in _MD_SUFFIXES:
        return None
    if not target.is_file():
        return None
    return target


def _split_line_ending(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def toggle_workspace_task(root: Path, path_str: str, line: int) -> dict:
    """Toggle a markdown task in-place."""
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        return {"status": "error", "message": "Invalid task line"}

    target = _resolve_workspace_task_path(root, path_str)
    if target is None:
        return {"status": "error", "message": "Invalid task path"}

    try:
        with target.open("r", encoding="utf-8", errors="replace", newline="") as file:
            original = file.read()
    except OSError:
        return {"status": "error", "message": "Could not read task file"}

    lines = original.splitlines(keepends=True)
    if line > len(lines):
        return {"status": "error", "message": "Task line out of range"}

    body, ending = _split_line_ending(lines[line - 1])
    match = _TASK_LINE_RE.match(body)
    if not match:
        return {"status": "error", "message": "Task not found"}

    checked = match.group(2).lower() != "x"
    marker = "x" if checked else " "
    lines[line - 1] = f"{match.group(1)}{marker}{match.group(3)}{ending}"

    try:
        _atomic_write_text(target, "".join(lines))
    except OSError:
        return {"status": "error", "message": "Could not update task"}

    task_text = _normalize_inline_text(match.group(3)[1:])
    return {
        "status": "ok",
        "path": str(target),
        "line": line,
        "checked": checked,
        "text": task_text,
    }
