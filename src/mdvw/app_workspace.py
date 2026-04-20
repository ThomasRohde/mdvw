from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import webview

from . import state
from .app_document import _json_for_script_tag
from .diagnostics import check_document as _check_document
from .links import (
    LinkIndex,
    build_graph_payload,
    build_link_index,
    fingerprint_root,
    incoming_links,
    resolve_wiki_link,
    search_wiki_targets,
)
from .search import search_workspace as _search_workspace_files
from .tasks import (
    list_workspace_tasks as _list_workspace_tasks_files,
)
from .tasks import (
    toggle_workspace_task as _toggle_workspace_task_file,
)

if TYPE_CHECKING:
    from .app import JsApi


_BROWSE_SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".git", ".hg", ".svn", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
})

_MD_SUFFIXES = (".md", ".markdown")

_UI_STATE_SCHEMA: ClassVar[dict[str, type | tuple[type, ...]]] = {
    "left_pane_width": int,
    "left_pane_collapsed": bool,
    "left_pane_section": str,
    "right_pane_width": int,
    "right_pane_collapsed": bool,
    "mode": str,
    "preview_narrow": bool,
}


def _int_option(value: object, *, default: int, min_value: int, max_value: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, number))


def _list_markdown_dir(api: JsApi, path_str: str = "") -> dict | None:
    """List markdown files and subdirectories of a single directory."""
    if api._browse_root is None:
        return None
    try:
        root = api._browse_root.resolve()
    except OSError:
        return None
    if path_str:
        if not isinstance(path_str, str):
            return None
        try:
            target = Path(path_str).resolve()
        except OSError:
            return None
        if target != root and not target.is_relative_to(root):
            return None
    else:
        target = root
    if not target.is_dir():
        return None
    entries: list[dict] = []
    try:
        children = list(target.iterdir())
    except OSError:
        return None
    children.sort(key=lambda path: (0 if path.is_dir() else 1, path.name.casefold()))
    for child in children:
        name = child.name
        if name.startswith("."):
            continue
        try:
            is_dir = child.is_dir()
        except OSError:
            continue
        if is_dir:
            if name in _BROWSE_SKIP_DIRS:
                continue
            entries.append({"type": "dir", "name": name, "path": str(child)})
            continue
        if child.suffix.lower() not in _MD_SUFFIXES:
            continue
        entries.append({"type": "file", "name": name, "path": str(child)})
    return {"path": str(target), "entries": entries}


def _open_path(api: JsApi, path_str: str) -> bool:
    """Load a file selected from the sidebar."""
    if api._browse_root is None or not isinstance(path_str, str) or not path_str:
        return False
    try:
        candidate = Path(path_str).resolve()
        root = api._browse_root.resolve()
    except OSError:
        return False
    if not candidate.is_relative_to(root):
        return False
    if candidate.suffix.lower() not in _MD_SUFFIXES:
        return False
    if not candidate.is_file():
        return False
    api._load(candidate)
    return True


def _open_file(api: JsApi) -> bool:
    if api._window is None:
        return False
    result = api._window.create_file_dialog(
        webview.OPEN_DIALOG,
        file_types=("Markdown (*.md;*.markdown)", "All files (*.*)"),
    )
    if not result:
        return False
    api._load(Path(result[0]))
    return True


def _open_directory(api: JsApi) -> bool:
    """Pick a workspace root via the native folder dialog."""
    if api._window is None:
        return False
    result = api._window.create_file_dialog(webview.FOLDER_DIALOG)
    picked = api._save_dialog_path(result)
    if picked is None:
        return False
    try:
        new_root = Path(picked).resolve()
    except OSError:
        return False
    if not new_root.is_dir():
        return False
    api._browse_root = new_root
    api._invalidate_link_index()
    state.set_key("last_browse_root", str(new_root))
    payload = _json_for_script_tag({"path": str(new_root)})
    api._window.evaluate_js(f"window.mdvwBrowseRootChanged({payload})")
    return True


def _open_recent(api: JsApi, path_str: str) -> bool:
    """Load a markdown file from the persisted recent-files list."""
    if not isinstance(path_str, str) or not path_str:
        return False
    try:
        candidate = Path(path_str).resolve()
    except OSError:
        return False
    if candidate.suffix.lower() not in _MD_SUFFIXES:
        return False
    if not candidate.is_file():
        return False
    candidate_key = os.path.normcase(str(candidate))
    allowed: set[str] = set()
    for item in state.get("recent_files", []) or []:
        try:
            allowed.add(os.path.normcase(str(Path(item).resolve())))
        except OSError:
            continue
    if candidate_key not in allowed:
        return False
    api._load(candidate)
    return True


def _save_ui_state(data: dict) -> None:
    """Persist UI state (pane widths, sections, etc.) from JS."""
    if not isinstance(data, dict):
        return
    cleaned: dict = {}
    for key, expected in _UI_STATE_SCHEMA.items():
        if key not in data:
            continue
        value = data[key]
        if expected is int and isinstance(value, bool):
            continue
        if not isinstance(value, expected):
            continue
        cleaned[key] = value
    if not cleaned:
        return
    current = state.load()
    current.update(cleaned)
    state.save(current)


def _get_recent_files() -> list[dict]:
    """Return the recent files list with existence flags."""
    recent = state.get("recent_files", [])
    result = []
    for path_str in recent:
        path = Path(path_str)
        result.append({"path": path_str, "name": path.name, "exists": path.is_file()})
    return result


def _clear_recent_files() -> None:
    state.set_key("recent_files", [])


def _search_filenames(api: JsApi, query: str, max_results: int = 50) -> list[dict]:
    """Search for markdown files by name within the browse root."""
    if not api._browse_root or not query or not isinstance(query, str):
        return []
    q = query.lower()
    results = []
    try:
        root = api._browse_root.resolve()
    except OSError:
        return []
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            dirname for dirname in dirnames
            if dirname not in _BROWSE_SKIP_DIRS and not dirname.startswith(".")
        ]
        for name in filenames:
            if not name.lower().endswith(_MD_SUFFIXES):
                continue
            if q not in name.lower():
                continue
            full = Path(dirpath) / name
            try:
                rel = full.relative_to(root)
            except ValueError:
                continue
            results.append({
                "name": name,
                "path": str(full),
                "relative": str(rel),
            })
            if len(results) >= max_results:
                return results
        count += 1
        if count > 10000:
            break
    return results


def _invalidate_link_index(api: JsApi) -> None:
    api._link_index = None
    api._link_index_fp = None
    api._link_index_root = None


def _get_link_index(api: JsApi) -> LinkIndex | None:
    if api._browse_root is None:
        return None
    try:
        root = api._browse_root.resolve()
    except OSError:
        return None
    fp = fingerprint_root(root)
    if (
        api._link_index is not None
        and api._link_index_root == root
        and api._link_index_fp == fp
    ):
        return api._link_index
    index = build_link_index(root)
    api._link_index = index
    api._link_index_fp = fp
    api._link_index_root = root
    return index


def _resolve_wiki_link(api: JsApi, raw_target: str) -> dict:
    """Resolve a wiki-link target in the current workspace."""
    if not isinstance(raw_target, str):
        return {"status": "invalid", "message": "Invalid wiki link"}
    index = _get_link_index(api)
    if index is None:
        return {"status": "no_workspace", "message": "No workspace"}
    resolved = resolve_wiki_link(raw_target, api._current_path, index)
    payload: dict = {
        "status": resolved.status,
        "message": resolved.message,
        "heading": resolved.heading,
    }
    if resolved.target_path is not None:
        payload["path"] = str(resolved.target_path)
        payload["relative"] = resolved.target_relative
    if resolved.matches:
        payload["matches"] = [
            {
                "path": str(path),
                "relative": str(path.relative_to(index.root)),
            }
            for path in resolved.matches
            if path.is_relative_to(index.root)
        ]
    return payload


def _open_wiki_link(api: JsApi, raw_target: str) -> dict:
    """Resolve and open a wiki link without creating missing notes."""
    resolved = _resolve_wiki_link(api, raw_target)
    if resolved.get("status") != "ok" or not resolved.get("path"):
        return resolved
    if not _open_path(api, str(resolved["path"])):
        return {"status": "error", "message": "Could not open file"}
    return resolved


def _get_incoming_links(api: JsApi, path_str: str | None = None) -> list[dict]:
    """Return incoming wiki links for a document."""
    index = _get_link_index(api)
    if index is None:
        return []
    if path_str:
        try:
            target = Path(path_str).resolve()
        except OSError:
            return []
    elif api._current_path is not None:
        try:
            target = api._current_path.resolve()
        except OSError:
            return []
    else:
        return []
    if not target.is_relative_to(index.root):
        return []
    return [
        {
            "source_path": str(item.source_path),
            "source_relative": item.source_relative,
            "line": item.line,
            "col": item.col,
            "display": item.display,
            "raw": item.raw,
            "context": item.context,
        }
        for item in incoming_links(index, target)
    ]


def _search_wiki_targets(
    api: JsApi,
    query: str,
    source_path: str | None = None,
    max_results: int = 50,
) -> list[dict]:
    """Search wiki-link autocomplete targets."""
    index = _get_link_index(api)
    if index is None:
        return []
    source = api._current_path
    if source_path:
        with contextlib.suppress(OSError):
            source = Path(source_path).resolve()
    return search_wiki_targets(
        index,
        query if isinstance(query, str) else "",
        source,
        max_results=max_results,
    )


def _get_graph(api: JsApi, options: dict | None = None) -> dict:
    """Return a workspace or local wiki-link graph payload."""
    index = _get_link_index(api)
    if index is None:
        return {
            "nodes": [],
            "edges": [],
            "stats": {
                "mode": "workspace",
                "depth": 1,
                "node_count": 0,
                "edge_count": 0,
                "total_nodes": 0,
                "total_edges": 0,
                "max_nodes": 500,
                "max_edges": 2_000,
                "truncated": False,
                "message": "No workspace",
            },
        }
    if not isinstance(options, dict):
        options = {}
    mode = options.get("mode")
    if mode not in {"workspace", "local"}:
        mode = "local" if api._current_path is not None else "workspace"
    depth = _int_option(options.get("depth"), default=1, min_value=1, max_value=2)
    max_nodes = _int_option(options.get("max_nodes"), default=500, min_value=1, max_value=5_000)
    max_edges = _int_option(
        options.get("max_edges"),
        default=2_000,
        min_value=1,
        max_value=20_000,
    )
    return build_graph_payload(
        index,
        api._current_path,
        mode=mode,
        depth=depth,
        include_unresolved=options.get("include_unresolved") is not False,
        include_orphans=options.get("include_orphans") is not False,
        max_nodes=max_nodes,
        max_edges=max_edges,
    )


def _run_diagnostics(api: JsApi, content: str) -> list[dict]:
    """Check the document for common issues."""
    doc_dir = str(api._current_path.parent) if api._current_path else None
    return _check_document(
        content,
        doc_dir=doc_dir,
        source_path=api._current_path,
        wiki_index=_get_link_index(api),
    )


def _search_workspace(api: JsApi, query: str, case_sensitive: bool = False) -> list[dict]:
    """Search Markdown files in the browse root for a text query."""
    if not api._browse_root:
        return []
    return _search_workspace_files(
        api._browse_root, query, case_sensitive=case_sensitive,
    )


def _get_workspace_tasks(api: JsApi, include_done: bool = False) -> list[dict]:
    """Return task-list items under the current browse root."""
    if not api._browse_root:
        return []
    return _list_workspace_tasks_files(
        api._browse_root,
        include_done=bool(include_done),
    )


def _toggle_workspace_task(api: JsApi, path_str: str, line: int) -> dict:
    """Toggle a task-list item in a workspace file."""
    if not api._browse_root:
        return {"status": "error", "message": "No workspace"}

    result = _toggle_workspace_task_file(api._browse_root, path_str, line)
    if result.get("status") != "ok" or not result.get("path"):
        return result

    if api._current_path is None:
        return result

    with contextlib.suppress(OSError):
        current = api._current_path.resolve()
        target = Path(str(result["path"])).resolve()
        if target == current:
            api._load(target, reason="watch")
    return result
