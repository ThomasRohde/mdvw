from __future__ import annotations

import re
from pathlib import Path

from .link_support import slugify

_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+[ \t]*)?$")
_FENCE_RE = re.compile(r"^\s{0,3}((`{3,})|(~{3,})).*$")


def heading_excerpt(body: str, heading: str) -> str:
    lines = body.splitlines()
    start = None
    level = 0
    fence_char = ""
    fence_len = 0
    used_slugs: set[str] = set()

    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        if fence_char:
            if (
                stripped.startswith(fence_char * fence_len)
                and not stripped[fence_len:].strip(fence_char).strip()
            ):
                fence_char = ""
                fence_len = 0
            continue

        fence_match = _FENCE_RE.match(line)
        if fence_match:
            fence = fence_match.group(1)
            fence_char = fence[0]
            fence_len = len(fence)
            continue

        match = _HEADING_RE.match(line)
        if not match:
            continue

        title = clean_heading(match.group(2))
        slug = slugify(title, used_slugs)
        current_level = len(match.group(1))
        if start is None:
            if title.casefold() == heading.casefold() or slug.casefold() == heading.casefold():
                start = idx
                level = current_level
            continue
        if current_level <= level:
            return "\n".join(lines[start:idx]).strip()

    if start is None:
        return ""
    return "\n".join(lines[start:]).strip()


def leading_excerpt(body: str) -> str:
    lines = body.splitlines()
    picked: list[str] = []
    blanks = 0
    for line in lines:
        picked.append(line)
        if line.strip():
            blanks = 0
        else:
            blanks += 1
            if blanks >= 2 and len("".join(picked)) > 240:
                break
        if len(picked) >= 18 or len("".join(picked)) >= 1_200:
            break
    return "\n".join(picked).strip()


def clip_excerpt(text: str, *, max_lines: int = 18, max_chars: int = 1_200) -> str:
    lines = text.splitlines()
    clipped = lines[:max_lines]
    out = "\n".join(clipped)
    if len(out) > max_chars:
        out = out[:max_chars].rstrip() + "..."
    elif len(lines) > max_lines:
        out = out.rstrip() + "\n\n..."
    return out


def preview_title(body: str, target: Path) -> str:
    used_slugs: set[str] = set()
    for line in body.splitlines():
        match = _HEADING_RE.match(line)
        if not match:
            continue
        title = clean_heading(match.group(2))
        slugify(title, used_slugs)
        return title
    return target.stem


def clean_heading(text: str) -> str:
    text = re.sub(r"\s+#+\s*$", "", text)
    text = re.sub(r"[*_`~\[\]]", "", text)
    return re.sub(r"\s+", " ", text).strip()
