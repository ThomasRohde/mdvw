"""Shared wiki-link parsing and rendering helpers for mdvw."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

_SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".git", ".hg", ".svn", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
})

_MD_SUFFIXES = {".md", ".markdown"}
_WIKI_RE = re.compile(r"(?<!!)\[\[([^\]\n]+?)\]\]")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


@dataclass(frozen=True)
class Heading:
    title: str
    level: int
    line: int
    slug: str


@dataclass(frozen=True)
class WikiLink:
    raw: str
    target: str
    heading: str
    alias: str
    display: str
    line: int
    col: int
    context: str


@dataclass(frozen=True)
class FileEntry:
    path: Path
    relative: str
    name: str
    stem: str
    headings: tuple[Heading, ...]


@dataclass(frozen=True)
class ResolvedLink:
    status: str
    target_path: Path | None = None
    target_relative: str = ""
    heading: str = ""
    matches: tuple[Path, ...] = ()
    message: str = ""


@dataclass(frozen=True)
class IncomingLink:
    source_path: Path
    source_relative: str
    line: int
    col: int
    display: str
    raw: str
    context: str


@dataclass(frozen=True)
class LinkIndex:
    root: Path
    files: dict[Path, FileEntry]
    links: dict[Path, tuple[WikiLink, ...]]


def parse_wiki_links(source: str) -> list[WikiLink]:
    """Return wiki links in *source*, skipping fenced code blocks."""
    links: list[WikiLink] = []
    in_fence = False
    fence_marker = ""
    for lineno, line in enumerate(source.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            continue
        if in_fence:
            continue
        for match in _WIKI_RE.finditer(line):
            if _inside_inline_code(line, match.start()):
                continue
            raw = match.group(1).strip()
            parsed = _parse_inner(raw)
            if parsed is None:
                continue
            target, heading, alias = parsed
            display = alias or heading or Path(target).stem or target
            links.append(WikiLink(
                raw=raw,
                target=target,
                heading=heading,
                alias=alias,
                display=display,
                line=lineno,
                col=match.start() + 1,
                context=line.strip()[:200],
            ))
    return links


def extract_headings(source: str) -> list[Heading]:
    """Extract Markdown ATX headings from *source*, skipping fenced code blocks."""
    headings: list[Heading] = []
    used: set[str] = set()
    in_fence = False
    fence_marker = ""
    for lineno, line in enumerate(source.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            continue
        if in_fence:
            continue
        match = _HEADING_RE.match(line)
        if not match:
            continue
        title = _strip_heading_markup(match.group(2).strip())
        slug = slugify(title, used)
        headings.append(Heading(title=title, level=len(match.group(1)), line=lineno, slug=slug))
    return headings


def render_wiki_links(text: str) -> str:
    """Replace wiki links in already-sanitized text with safe anchor HTML."""
    out: list[str] = []
    last = 0
    for match in _WIKI_RE.finditer(text):
        raw = match.group(1).strip()
        parsed = _parse_inner(raw)
        if parsed is None:
            continue
        target, heading, alias = parsed
        display = alias or heading or Path(target).stem or target
        out.append(text[last:match.start()])
        attrs = [
            'href="#"',
            'class="mdvw-wikilink"',
            f'data-wikilink="{_escape_attr(raw)}"',
        ]
        if target:
            attrs.append(f'data-wikilink-target="{_escape_attr(target)}"')
        if heading:
            attrs.append(f'data-wikilink-heading="{_escape_attr(heading)}"')
        out.append(f'<a {" ".join(attrs)}>{_escape_text(display)}</a>')
        last = match.end()
    out.append(text[last:])
    return "".join(out)


def parse_wiki_inner(raw: str) -> tuple[str, str, str, str] | None:
    """Parse inner wiki-link text into target, heading, alias, display."""
    parsed = _parse_inner(raw)
    if parsed is None:
        return None
    target, heading, alias = parsed
    display = alias or heading or Path(target).stem or target
    return target, heading, alias, display


def normalize_note_name(target: str) -> str:
    """Convert a wiki-link target into a safe Markdown filename/path."""
    path_part = target.split("#", 1)[0].strip().replace("\\", "/")
    path_part = path_part.strip("/")
    if not path_part:
        return ""
    parts = [
        _safe_filename_part(part)
        for part in path_part.split("/")
        if part not in ("", ".", "..")
    ]
    if not parts:
        return ""
    leaf = parts[-1]
    if Path(leaf).suffix.lower() not in _MD_SUFFIXES:
        parts[-1] = f"{leaf}.md"
    return "/".join(parts)


def source_relative_link(source: Path | None, target: Path, root: Path) -> str:
    """Return a source-relative wiki target path without the Markdown suffix."""
    try:
        root_resolved = root.resolve()
        target_resolved = target.resolve()
    except OSError:
        return target.stem
    if source is not None:
        try:
            source_resolved = source.resolve()
            base = source_resolved.parent
            rel = os.path.relpath(target_resolved, base).replace("\\", "/")
            if not rel.startswith("../") and not rel.startswith("/"):
                return _without_md_suffix(rel)
        except OSError:
            pass
    return _without_md_suffix(target_resolved.relative_to(root_resolved).as_posix())


def uri_fragment_for_heading(heading: str) -> str:
    return quote(heading, safe="")


def slugify(text: str, used: set[str] | None = None) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.ASCII)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    if not s:
        s = "section"
    if used is None:
        return s
    out = s
    i = 2
    while out in used:
        out = f"{s}-{i}"
        i += 1
    used.add(out)
    return out


def _coerce_link(link: WikiLink | str) -> WikiLink | None:
    if isinstance(link, WikiLink):
        return link
    parsed = _parse_inner(str(link).strip())
    if parsed is None:
        return None
    target, heading, alias = parsed
    display = alias or heading or Path(target).stem or target
    return WikiLink(
        raw=str(link).strip(),
        target=target,
        heading=heading,
        alias=alias,
        display=display,
        line=1,
        col=1,
        context="",
    )


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def _parse_inner(raw: str) -> tuple[str, str, str] | None:
    if not raw or raw.startswith("!"):
        return None
    body, alias = _split_once(raw, "|")
    body = body.strip()
    alias = alias.strip()
    if not body:
        return None
    target, heading = _split_once(body, "#")
    return target.strip(), heading.strip(), alias


def _split_once(value: str, sep: str) -> tuple[str, str]:
    if sep not in value:
        return value, ""
    before, after = value.split(sep, 1)
    return before, after


def _inside_inline_code(line: str, pos: int) -> bool:
    return line[:pos].count("`") % 2 == 1


def _strip_heading_markup(text: str) -> str:
    text = re.sub(r"\s+#+\s*$", "", text)
    text = re.sub(r"[*_`~\[\]]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _without_md_suffix(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() in _MD_SUFFIXES:
        return p.with_suffix("").as_posix()
    return path


def _safe_filename_part(part: str) -> str:
    cleaned = re.sub(r'[<>:"|?*\x00-\x1f]', "_", part).strip(" .")
    return cleaned[:120] or "Untitled"


def _escape_text(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _escape_attr(value: str) -> str:
    return (
        _escape_text(value)
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
