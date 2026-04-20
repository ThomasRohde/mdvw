from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .frontmatter import split_frontmatter
from .links import resolve_wiki_link
from .note_excerpt import clip_excerpt, heading_excerpt, leading_excerpt, preview_title
from .render import render_markdown

if TYPE_CHECKING:
    from .app import JsApi
    from .links import LinkIndex

def _preview_wiki_link(api: JsApi, raw_target: str) -> dict:
    if not isinstance(raw_target, str):
        return {"status": "error", "message": "Invalid wiki link"}

    index = api._get_link_index()
    if index is None:
        return {"status": "error", "message": "No workspace"}

    resolved = resolve_wiki_link(raw_target, api._current_path, index)
    if resolved.status != "ok" or resolved.target_path is None:
        return {
            "status": "error",
            "message": resolved.message or "Wiki link not resolved",
        }

    target = resolved.target_path
    try:
        source = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"status": "error", "message": str(exc)}

    _meta, body = split_frontmatter(source)
    excerpt = (
        heading_excerpt(body, resolved.heading)
        if resolved.heading
        else leading_excerpt(body)
    )
    excerpt = excerpt.strip() or f"# {target.stem}\n"
    doc_base = target.parent.resolve().as_uri() + "/"
    title = resolved.heading or preview_title(body, target)
    entry = index.files.get(target)
    relative = entry.relative if entry is not None else _safe_relative(target, index)
    return {
        "status": "ok",
        "title": title,
        "path": str(target),
        "relative": relative,
        "heading": resolved.heading,
        "html": render_markdown(
            clip_excerpt(excerpt),
            doc_base=doc_base,
            current_path=target,
            browse_root=index.root,
        ),
    }


def _safe_relative(path: Path, index: LinkIndex) -> str:
    try:
        return path.resolve().relative_to(index.root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)
