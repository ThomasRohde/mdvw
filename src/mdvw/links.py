"""Workspace wiki-link indexing for mdvw.

Supports an Obsidian-style core subset:
``[[Note]]``, ``[[Note|alias]]``, ``[[Note#Heading]]``, and ``[[#Heading]]``.
The index is in-memory and rebuilt on demand by ``JsApi``.
"""

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
        for m in _WIKI_RE.finditer(line):
            if _inside_inline_code(line, m.start()):
                continue
            raw = m.group(1).strip()
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
                col=m.start() + 1,
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
        m = _HEADING_RE.match(line)
        if not m:
            continue
        title = _strip_heading_markup(m.group(2).strip())
        slug = slugify(title, used)
        headings.append(Heading(title=title, level=len(m.group(1)), line=lineno, slug=slug))
    return headings


def build_link_index(root: Path) -> LinkIndex:
    """Scan Markdown files under *root* and build a wiki-link index."""
    try:
        root_resolved = root.resolve()
    except OSError:
        return LinkIndex(root=root, files={}, links={})
    files: dict[Path, FileEntry] = {}
    links: dict[Path, tuple[WikiLink, ...]] = {}
    files_scanned = 0
    for dirpath, dirnames, filenames in os.walk(root_resolved):
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
                return LinkIndex(root=root_resolved, files=files, links=links)
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
            rel = resolved.relative_to(root_resolved).as_posix()
            files[resolved] = FileEntry(
                path=resolved,
                relative=rel,
                name=resolved.name,
                stem=resolved.stem,
                headings=tuple(extract_headings(text)),
            )
            links[resolved] = tuple(parse_wiki_links(text))
    return LinkIndex(root=root_resolved, files=files, links=links)


def resolve_wiki_link(
    link: WikiLink | str,
    source_path: Path | None,
    index: LinkIndex,
) -> ResolvedLink:
    """Resolve a wiki link against *source_path* and *index*."""
    parsed = _coerce_link(link)
    if parsed is None:
        return ResolvedLink(status="invalid", message="Invalid wiki link")
    target, heading = parsed.target, parsed.heading
    source_resolved = _resolve_source(source_path, index)

    if not target and heading:
        if source_resolved is None:
            return ResolvedLink(status="missing", heading=heading, message="No current document")
        if _heading_exists(index.files.get(source_resolved), heading):
            return ResolvedLink(
                status="ok",
                target_path=source_resolved,
                target_relative=index.files[source_resolved].relative,
                heading=heading,
            )
        return ResolvedLink(
            status="missing_heading",
            target_path=source_resolved,
            target_relative=index.files.get(source_resolved, FileEntry(
                source_resolved, "", source_resolved.name, source_resolved.stem, (),
            )).relative,
            heading=heading,
            message=f"Missing heading: {heading}",
        )

    candidates = _candidate_paths(target, source_resolved, index)
    if len(candidates) > 1:
        return ResolvedLink(
            status="ambiguous",
            heading=heading,
            matches=tuple(candidates),
            message=f"Ambiguous wiki link: {target}",
        )
    if not candidates:
        return ResolvedLink(
            status="missing",
            heading=heading,
            message=f"Unresolved wiki link: {target}",
        )

    target_path = candidates[0]
    entry = index.files.get(target_path)
    target_relative = entry.relative if entry else _safe_relative(target_path, index.root)
    if heading and not _heading_exists(entry, heading):
        return ResolvedLink(
            status="missing_heading",
            target_path=target_path,
            target_relative=target_relative,
            heading=heading,
            message=f"Missing heading: {heading}",
        )
    return ResolvedLink(
        status="ok",
        target_path=target_path,
        target_relative=target_relative,
        heading=heading,
    )


def incoming_links(index: LinkIndex, target_path: Path) -> list[IncomingLink]:
    """Return resolved backlinks pointing at *target_path*."""
    try:
        target = target_path.resolve()
    except OSError:
        return []
    result: list[IncomingLink] = []
    for source, links in index.links.items():
        for link in links:
            resolved = resolve_wiki_link(link, source, index)
            if resolved.status != "ok" or resolved.target_path != target:
                continue
            source_entry = index.files.get(source)
            source_relative = (
                source_entry.relative if source_entry else _safe_relative(source, index.root)
            )
            result.append(IncomingLink(
                source_path=source,
                source_relative=source_relative,
                line=link.line,
                col=link.col,
                display=link.display,
                raw=link.raw,
                context=link.context,
            ))
    result.sort(key=lambda item: (item.source_relative.casefold(), item.line, item.col))
    return result


def diagnose_wiki_links(
    source: str,
    source_path: Path | None,
    index: LinkIndex | None,
) -> list[dict]:
    """Return diagnostics for wiki links in the current document."""
    if index is None:
        return []
    issues: list[dict] = []
    for link in parse_wiki_links(source):
        resolved = resolve_wiki_link(link, source_path, index)
        if resolved.status == "ok":
            continue
        if resolved.status == "ambiguous":
            matches = ", ".join(_safe_relative(p, index.root) for p in resolved.matches[:3])
            issues.append({
                "severity": "warning",
                "message": f"Ambiguous wiki link: [[{link.raw}]] matches {matches}",
                "line": link.line,
            })
        elif resolved.status == "missing_heading":
            where = resolved.target_relative or link.target or "current note"
            issues.append({
                "severity": "warning",
                "message": f"Missing wiki heading: [[{link.raw}]] in {where}",
                "line": link.line,
            })
        elif resolved.status == "invalid":
            issues.append({
                "severity": "warning",
                "message": f"Invalid wiki link: [[{link.raw}]]",
                "line": link.line,
            })
        else:
            issues.append({
                "severity": "warning",
                "message": f"Unresolved wiki link: [[{link.raw}]]",
                "line": link.line,
            })
    return issues


def search_wiki_targets(
    index: LinkIndex,
    query: str,
    source_path: Path | None = None,
    *,
    max_results: int = 50,
) -> list[dict]:
    """Return file and heading suggestions for wiki-link autocomplete."""
    q = query.casefold().strip()
    source_resolved = _resolve_source(source_path, index)
    results: list[dict] = []
    for entry in sorted(index.files.values(), key=lambda e: e.relative.casefold()):
        insert = _display_target(entry, index, source_resolved)
        haystack = f"{entry.stem} {entry.name} {entry.relative}".casefold()
        if not q or q in haystack:
            results.append({
                "type": "file",
                "label": entry.stem,
                "detail": entry.relative,
                "insert": insert,
                "path": str(entry.path),
            })
            if len(results) >= max_results:
                return results
        for heading in entry.headings:
            heading_insert = f"{insert}#{heading.title}" if insert else f"#{heading.title}"
            heading_haystack = f"{entry.stem} {entry.relative} {heading.title}".casefold()
            if q and q not in heading_haystack:
                continue
            results.append({
                "type": "heading",
                "label": heading.title,
                "detail": f"{entry.relative} H{heading.level}",
                "insert": heading_insert,
                "path": str(entry.path),
                "heading": heading.title,
            })
            if len(results) >= max_results:
                return results
    return results


def fingerprint_root(root: Path) -> tuple[tuple[str, int, int], ...]:
    """Return a cheap fingerprint for Markdown files under *root*."""
    try:
        root_resolved = root.resolve()
    except OSError:
        return ()
    fp: list[tuple[str, int, int]] = []
    files_scanned = 0
    for dirpath, dirnames, filenames in os.walk(root_resolved):
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
                return tuple(sorted(fp))
            try:
                if full.is_symlink():
                    continue
                resolved = full.resolve()
                if not resolved.is_relative_to(root_resolved):
                    continue
                st = resolved.stat()
                rel = resolved.relative_to(root_resolved).as_posix()
            except OSError:
                continue
            fp.append((rel, st.st_mtime_ns, st.st_size))
    return tuple(sorted(fp))


def render_wiki_links(text: str) -> str:
    """Replace wiki links in already-sanitized text with safe anchor HTML."""
    out: list[str] = []
    last = 0
    for m in _WIKI_RE.finditer(text):
        raw = m.group(1).strip()
        parsed = _parse_inner(raw)
        if parsed is None:
            continue
        target, heading, alias = parsed
        display = alias or heading or Path(target).stem or target
        out.append(text[last:m.start()])
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
        last = m.end()
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
    parts = [_safe_filename_part(p) for p in path_part.split("/") if p not in ("", ".", "..")]
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


def _coerce_link(link: WikiLink | str) -> WikiLink | None:
    if isinstance(link, WikiLink):
        return link
    parsed = _parse_inner(str(link).strip())
    if parsed is None:
        return None
    target, heading, alias = parsed
    display = alias or heading or Path(target).stem or target
    return WikiLink(
        raw=str(link).strip(), target=target, heading=heading, alias=alias,
        display=display, line=1, col=1, context="",
    )


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


def _resolve_source(source_path: Path | None, index: LinkIndex) -> Path | None:
    if source_path is None:
        return None
    try:
        resolved = source_path.resolve()
    except OSError:
        return None
    if not resolved.is_relative_to(index.root):
        return None
    return resolved


def _candidate_paths(target: str, source: Path | None, index: LinkIndex) -> list[Path]:
    target = target.strip().replace("\\", "/")
    if not target:
        return []
    candidates: list[Path] = []
    explicit = _looks_path_like(target)
    for base in _candidate_bases(source, index.root):
        for candidate in _with_md_suffixes(base / target):
            resolved = _safe_index_path(candidate, index.root)
            if resolved is not None and resolved in index.files:
                candidates.append(resolved)
    if explicit:
        return _dedupe_paths(candidates)
    folded = target.casefold()
    for entry in index.files.values():
        if entry.stem.casefold() == folded or entry.name.casefold() == folded:
            candidates.append(entry.path)
    return _dedupe_paths(candidates)


def _candidate_bases(source: Path | None, root: Path) -> list[Path]:
    bases = []
    if source is not None:
        bases.append(source.parent)
    bases.append(root)
    return bases


def _with_md_suffixes(path: Path) -> list[Path]:
    if path.suffix.lower() in _MD_SUFFIXES:
        return [path]
    return [path.with_suffix(".md"), path.with_suffix(".markdown")]


def _safe_index_path(path: Path, root: Path) -> Path | None:
    try:
        resolved = path.resolve()
    except OSError:
        return None
    if not resolved.is_relative_to(root):
        return None
    return resolved


def _looks_path_like(target: str) -> bool:
    return "/" in target or "\\" in target or Path(target).suffix.lower() in _MD_SUFFIXES


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def _heading_exists(entry: FileEntry | None, heading: str) -> bool:
    if not heading:
        return True
    if entry is None:
        return False
    folded = heading.casefold()
    return any(h.title.casefold() == folded or h.slug.casefold() == folded for h in entry.headings)


def _display_target(entry: FileEntry, index: LinkIndex, source: Path | None) -> str:
    same_stem = [
        e for e in index.files.values()
        if e.stem.casefold() == entry.stem.casefold()
    ]
    if len(same_stem) == 1:
        return entry.stem
    return source_relative_link(source, entry.path, index.root)


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


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
