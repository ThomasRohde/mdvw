"""Workspace wiki-link indexing, resolution, and lookup helpers."""

from __future__ import annotations

import os
from pathlib import Path

from .link_support import (
    _MD_SUFFIXES,
    _SKIP_DIRS,
    FileEntry,
    IncomingLink,
    LinkIndex,
    ResolvedLink,
    _coerce_link,
    _safe_relative,
    extract_headings,
    parse_wiki_links,
    source_relative_link,
)


def build_link_index(root: Path) -> LinkIndex:
    """Scan Markdown files under *root* and build a wiki-link index."""
    try:
        root_resolved = root.resolve()
    except OSError:
        return LinkIndex(root=root, files={}, links={})
    files: dict[Path, FileEntry] = {}
    links: dict[Path, tuple] = {}
    files_scanned = 0
    for dirpath, dirnames, filenames in os.walk(root_resolved):
        dirnames[:] = [
            dirname for dirname in dirnames
            if dirname not in _SKIP_DIRS and not dirname.startswith(".")
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
    link,
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
            matches = ", ".join(_safe_relative(path, index.root) for path in resolved.matches[:3])
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
    for entry in sorted(index.files.values(), key=lambda item: item.relative.casefold()):
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
            dirname for dirname in dirnames
            if dirname not in _SKIP_DIRS and not dirname.startswith(".")
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
    return any(
        item.title.casefold() == folded or item.slug.casefold() == folded
        for item in entry.headings
    )


def _display_target(entry: FileEntry, index: LinkIndex, source: Path | None) -> str:
    same_stem = [
        candidate for candidate in index.files.values()
        if candidate.stem.casefold() == entry.stem.casefold()
    ]
    if len(same_stem) == 1:
        return entry.stem
    return source_relative_link(source, entry.path, index.root)
