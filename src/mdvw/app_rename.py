from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote

from . import state
from .app_document import _atomic_write_text
from .links import normalize_note_name, parse_wiki_inner, resolve_wiki_link, source_relative_link

if TYPE_CHECKING:
    from .app import JsApi
    from .links import LinkIndex


_FENCE_RE = re.compile(r"^\s{0,3}((`{3,})|(~{3,})).*$")
_WIKI_RE = re.compile(r"(?<!!)\[\[([^\]\n]+?)\]\]")
_MD_LINK_RE = re.compile(r"!?\[([^\]]*)\]\(([^)]+)\)")
_MD_SUFFIXES = {".md", ".markdown"}
_REMOTE_SCHEMES = ("http:", "https:", "ftp:", "mailto:", "data:", "file:")


def _move_current_note(api: JsApi, raw_target: str) -> dict:
    root = _workspace_root(api)
    if root is None:
        return {"status": "error", "message": "No workspace"}

    current = _current_workspace_note(api, root)
    if current is None:
        return {"status": "error", "message": "Current note is not in the workspace"}
    if not isinstance(raw_target, str):
        return {"status": "error", "message": "Invalid target"}

    target = _resolve_move_target(root, current, raw_target)
    if target is None:
        return {"status": "error", "message": "Cannot move note there"}

    if _same_path(current, target):
        return {
            "status": "ok",
            "path": str(current),
            "relative": current.relative_to(root).as_posix(),
            "name": current.name,
            "updated_files": 0,
            "message": "Note unchanged",
        }
    if target.exists():
        return {"status": "error", "message": "Target already exists"}

    index = api._get_link_index()
    if index is None:
        return {"status": "error", "message": "No workspace"}

    try:
        rewrites = _plan_note_move(index, current, target)
        moved_content = rewrites.pop(current, _read_text(current))
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(target, moved_content)
        for path, content in rewrites.items():
            _atomic_write_text(path, content)
        current.unlink()
    except OSError as exc:
        return {"status": "error", "message": str(exc)}

    api._invalidate_link_index()
    api._load(target)
    state.remove_recent(str(current))
    return {
        "status": "ok",
        "path": str(target),
        "old_path": str(current),
        "relative": target.relative_to(root).as_posix(),
        "name": target.name,
        "updated_files": len(rewrites) + 1,
    }


def _plan_note_move(index: LinkIndex, current: Path, target: Path) -> dict[Path, str]:
    rewrites: dict[Path, str] = {}
    stem_counts = _stem_counts_after_move(index, current, target)
    for source in index.files:
        original = _read_text(source)
        updated = _rewrite_wiki_links(
            original,
            source,
            current,
            target,
            index,
            stem_counts,
        )
        updated = _rewrite_markdown_links(updated, source, current, target)
        if updated != original:
            rewrites[source] = updated
    return rewrites


def _rewrite_wiki_links(
    source: str,
    source_path: Path,
    current: Path,
    target: Path,
    index: LinkIndex,
    stem_counts: dict[str, int],
) -> str:
    lines: list[str] = []
    fence_char = ""
    fence_len = 0

    for line in source.splitlines(keepends=True):
        body, ending = _split_line_ending(line)
        stripped = body.lstrip()

        if fence_char:
            if (
                stripped.startswith(fence_char * fence_len)
                and not stripped[fence_len:].strip(fence_char).strip()
            ):
                fence_char = ""
                fence_len = 0
            lines.append(line)
            continue

        fence_match = _FENCE_RE.match(body)
        if fence_match:
            fence = fence_match.group(1)
            fence_char = fence[0]
            fence_len = len(fence)
            lines.append(line)
            continue

        rebuilt: list[str] = []
        last = 0
        changed = False
        for match in _WIKI_RE.finditer(body):
            if _inside_inline_code(body, match.start()):
                continue
            raw = match.group(1).strip()
            replacement = _rewrite_wiki_inner(
                raw,
                source_path,
                current,
                target,
                index,
                stem_counts,
            )
            if replacement is None or replacement == raw:
                continue
            rebuilt.append(body[last:match.start()])
            rebuilt.append(f"[[{replacement}]]")
            last = match.end()
            changed = True

        if changed:
            rebuilt.append(body[last:])
            lines.append("".join(rebuilt) + ending)
        else:
            lines.append(line)

    return "".join(lines)


def _rewrite_wiki_inner(
    raw: str,
    source_path: Path,
    current: Path,
    target: Path,
    index: LinkIndex,
    stem_counts: dict[str, int],
) -> str | None:
    parsed = parse_wiki_inner(raw)
    if parsed is None:
        return None
    link_target, heading, alias, _display = parsed
    if not link_target and heading:
        return None

    resolved = resolve_wiki_link(raw, source_path, index)
    output_source = target if _same_path(source_path, current) else source_path

    if resolved.target_path is not None and _same_path(resolved.target_path, current):
        new_target = _preferred_wiki_target(
            output_source,
            link_target,
            target,
            index.root,
            stem_counts,
        )
        return _compose_wiki_inner(new_target, heading, alias)

    if (
        _same_path(source_path, current)
        and _looks_path_like(link_target)
        and resolved.target_path is not None
    ):
        new_target = source_relative_link(output_source, resolved.target_path, index.root)
        return _compose_wiki_inner(new_target, heading, alias)

    return None


def _rewrite_markdown_links(
    source: str,
    source_path: Path,
    current: Path,
    target: Path,
) -> str:
    lines: list[str] = []
    fence_char = ""
    fence_len = 0

    for line in source.splitlines(keepends=True):
        body, ending = _split_line_ending(line)
        stripped = body.lstrip()

        if fence_char:
            if (
                stripped.startswith(fence_char * fence_len)
                and not stripped[fence_len:].strip(fence_char).strip()
            ):
                fence_char = ""
                fence_len = 0
            lines.append(line)
            continue

        fence_match = _FENCE_RE.match(body)
        if fence_match:
            fence = fence_match.group(1)
            fence_char = fence[0]
            fence_len = len(fence)
            lines.append(line)
            continue

        rebuilt: list[str] = []
        last = 0
        changed = False
        for match in _MD_LINK_RE.finditer(body):
            if _inside_inline_code(body, match.start()):
                continue
            href = match.group(2).strip()
            replacement = _rewrite_markdown_href(href, source_path, current, target)
            if replacement is None or replacement == href:
                continue
            rebuilt.append(body[last:match.start(2)])
            rebuilt.append(replacement)
            last = match.end(2)
            changed = True

        if changed:
            rebuilt.append(body[last:])
            lines.append("".join(rebuilt) + ending)
        else:
            lines.append(line)

    return "".join(lines)


def _rewrite_markdown_href(
    href: str,
    source_path: Path,
    current: Path,
    target: Path,
) -> str | None:
    if not _is_safe_relative_href(href):
        return None

    path_part, suffix = _split_href(href)
    decoded = unquote(path_part)
    if not decoded:
        return None

    try:
        resolved = (source_path.parent / decoded).resolve()
    except OSError:
        return None

    if _same_path(source_path, current):
        link_target = target if _same_path(resolved, current) else resolved
        return _relative_markdown_href(target.parent, link_target) + suffix

    if not _same_path(resolved, current):
        return None

    return _relative_markdown_href(source_path.parent, target) + suffix


def _workspace_root(api: JsApi) -> Path | None:
    if api._browse_root is None:
        return None
    try:
        root = api._browse_root.resolve()
    except OSError:
        return None
    return root if root.is_dir() else None


def _current_workspace_note(api: JsApi, root: Path) -> Path | None:
    if api._current_path is None:
        return None
    try:
        current = api._current_path.resolve()
    except OSError:
        return None
    if not current.is_relative_to(root):
        return None
    if current.suffix.lower() not in _MD_SUFFIXES or not current.is_file():
        return None
    return current


def _resolve_move_target(root: Path, current: Path, raw_target: str) -> Path | None:
    if not raw_target.strip():
        return None

    raw_path = raw_target.strip().replace("\\", "/")
    explicit_suffix = Path(raw_path.strip("/")).suffix.lower() in _MD_SUFFIXES
    relative = normalize_note_name(raw_path)
    if not relative:
        return None

    if not explicit_suffix:
        relative = str(Path(relative).with_suffix(current.suffix or ".md")).replace("\\", "/")

    try:
        if "/" in raw_path:
            target = (root / relative).resolve()
        else:
            target = (current.parent / Path(relative).name).resolve()
    except OSError:
        return None

    if not target.is_relative_to(root):
        return None
    return target


def _preferred_wiki_target(
    source_path: Path,
    original_target: str,
    target_path: Path,
    root: Path,
    stem_counts: dict[str, int],
) -> str:
    if _looks_path_like(original_target):
        return source_relative_link(source_path, target_path, root)
    if stem_counts.get(target_path.stem.casefold(), 0) == 1:
        return target_path.stem
    return source_relative_link(source_path, target_path, root)


def _stem_counts_after_move(index: LinkIndex, current: Path, target: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path, entry in index.files.items():
        if _same_path(path, current):
            continue
        key = entry.stem.casefold()
        counts[key] = counts.get(key, 0) + 1
    key = target.stem.casefold()
    counts[key] = counts.get(key, 0) + 1
    return counts


def _compose_wiki_inner(target: str, heading: str, alias: str) -> str:
    out = target
    if heading:
        out += f"#{heading}"
    if alias:
        out += f"|{alias}"
    return out


def _relative_markdown_href(base_dir: Path, target: Path) -> str:
    return os.path.relpath(target, base_dir).replace("\\", "/")


def _split_href(href: str) -> tuple[str, str]:
    idx = min((i for i in (href.find("#"), href.find("?")) if i != -1), default=-1)
    if idx != -1:
        return href[:idx], href[idx:]
    return href, ""


def _read_text(path: Path) -> str:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as file:
        return file.read()


def _split_line_ending(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def _inside_inline_code(line: str, pos: int) -> bool:
    return line[:pos].count("`") % 2 == 1


def _looks_path_like(target: str) -> bool:
    return "/" in target or "\\" in target or Path(target).suffix.lower() in _MD_SUFFIXES


def _is_safe_relative_href(href: str) -> bool:
    if not href or href.startswith("#"):
        return False
    lower = href.lower()
    if any(lower.startswith(prefix) for prefix in _REMOTE_SCHEMES):
        return False
    if href.startswith(("/", "\\", "//", "\\\\")):
        return False
    first_slash = min(
        (i for i in (href.find("/"), href.find("\\")) if i != -1),
        default=-1,
    )
    first_colon = href.find(":")
    if first_colon != -1 and (first_slash == -1 or first_colon < first_slash):
        return False
    return not (len(href) >= 2 and href[1] == ":" and href[0].isalpha())


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))
