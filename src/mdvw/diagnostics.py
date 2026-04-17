"""Document diagnostics for mdvw.

Checks for common issues in Markdown documents: invalid frontmatter,
broken relative links/images, and blocked remote references.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

from .frontmatter import parse_frontmatter


def check_document(source: str, doc_dir: str | None = None) -> list[dict]:
    """Analyse *source* for common issues.

    Returns a list of ``{severity, message, line}`` dicts where
    severity is ``"error"``, ``"warning"``, or ``"info"``.
    """
    issues: list[dict] = []
    _check_frontmatter(source, issues)
    _check_links(source, doc_dir, issues)
    return issues


def _check_frontmatter(source: str, issues: list[dict]) -> None:
    _meta, _body, err = parse_frontmatter(source)
    if err:
        issues.append({
            "severity": "error",
            "message": f"Invalid YAML frontmatter: {err}",
            "line": 1,
        })


# Regex to find markdown image/link references: ![alt](path) or [text](path)
_LINK_RE = re.compile(r"!?\[([^\]]*)\]\(([^)]+)\)")

_REMOTE_SCHEMES = {"http:", "https:", "ftp:", "//"}
_BLOCKED_SCHEMES = {"file:", "javascript:", "data:"}


def _check_links(source: str, doc_dir: str | None, issues: list[dict]) -> None:
    for lineno, line_text in enumerate(source.splitlines(), start=1):
        for m in _LINK_RE.finditer(line_text):
            href = m.group(2).strip()
            is_image = m.group(0).startswith("!")

            # Skip anchors
            if href.startswith("#"):
                continue

            # Flag remote references
            lower = href.lower()
            if any(lower.startswith(s) for s in _REMOTE_SCHEMES):
                issues.append({
                    "severity": "info",
                    "message": f"Remote {'image' if is_image else 'link'}: {_trunc(href)}",
                    "line": lineno,
                })
                continue

            # Flag blocked schemes
            if any(lower.startswith(s) for s in _BLOCKED_SCHEMES):
                issues.append({
                    "severity": "warning",
                    "message": f"Blocked scheme in "
                    f"{'image' if is_image else 'link'}: {_trunc(href)}",
                    "line": lineno,
                })
                continue

            # Check relative paths exist on disk. Diagnostics run
            # automatically on every document, so we must not let a
            # hostile markdown file probe arbitrary local/UNC paths:
            # constrain resolution to inside doc_dir and skip anything
            # outside that envelope.
            if doc_dir:
                # Strip fragment and query, then decode percent-escapes
                # BEFORE the safety check — otherwise `%5C%5Cserver…` or
                # `C%3A%5CWindows` sneak past ``_is_safe_relative`` (which
                # sees no literal slash/backslash/colon) and reach
                # ``Path.resolve()`` on a hostile absolute/UNC path.
                path_part = href.split("#")[0].split("?")[0]
                if not path_part:
                    continue
                decoded = unquote(path_part)
                if not _is_safe_relative(decoded):
                    continue
                try:
                    doc_dir_resolved = Path(doc_dir).resolve()
                    target = (doc_dir_resolved / decoded).resolve()
                except OSError:
                    continue
                if not target.is_relative_to(doc_dir_resolved):
                    continue
                try:
                    exists = target.exists()
                except OSError:
                    continue
                if not exists:
                    kind = "image" if is_image else "link"
                    issues.append({
                        "severity": "warning",
                        "message": f"Broken {kind}: {_trunc(href)}",
                        "line": lineno,
                    })


def _is_safe_relative(path_part: str) -> bool:
    """Return True only for strictly-relative, in-tree paths.

    Rejects absolute / drive-letter / UNC / authority-style paths before
    we hand anything to ``Path.resolve()``. A final containment check
    still runs afterwards; this is defense in depth so obviously bad
    inputs never hit the filesystem at all.
    """
    if not path_part:
        return False
    # Authority / scheme / absolute / UNC markers.
    if path_part.startswith(("/", "\\", "//", "\\\\")):
        return False
    # Any scheme (e.g. ``mailto:x``, ``something:path``): first ``:`` before
    # any separator means a URI scheme, not a relative path.
    first_slash = min(
        (i for i in (path_part.find("/"), path_part.find("\\")) if i != -1),
        default=-1,
    )
    first_colon = path_part.find(":")
    if first_colon != -1 and (first_slash == -1 or first_colon < first_slash):
        return False
    # Windows drive-letter paths like ``C:\x`` already fail the scheme
    # check above; this extra guard catches ``C:x`` with no separator.
    return not (len(path_part) >= 2 and path_part[1] == ":" and path_part[0].isalpha())


def _trunc(s: str, max_len: int = 60) -> str:
    return s if len(s) <= max_len else s[:max_len - 1] + "…"
