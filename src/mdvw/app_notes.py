from __future__ import annotations

import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .app_document import _atomic_write_text
from .links import normalize_note_name

if TYPE_CHECKING:
    from .app import JsApi


_BROWSE_SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".git", ".hg", ".svn", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
})
_MD_SUFFIXES = (".md", ".markdown")
_TEMPLATE_DIR = "Templates"
_DAILY_DIR = "Daily"
_TOKEN_RE = re.compile(r"{{\s*([a-z_]+)\s*}}")


def _create_note(api: JsApi, raw_target: str, template_path: str = "") -> dict:
    root = _workspace_root(api)
    if root is None or not isinstance(raw_target, str):
        return {"status": "error", "message": "No workspace"}
    target = _resolve_note_target(api, root, raw_target)
    if target is None:
        return {"status": "error", "message": "Cannot create this note"}
    template = _resolve_template(root, template_path)
    if template_path and template is None:
        return {"status": "error", "message": "Template not found"}
    return _open_or_create_note(api, root, target, template_path=template)


def _create_wiki_note(api: JsApi, raw_target: str) -> dict:
    root = _workspace_root(api)
    if root is None or not isinstance(raw_target, str):
        return {"status": "error", "message": "No workspace"}
    target = _resolve_note_target(api, root, raw_target)
    if target is None:
        return {"status": "error", "message": "Cannot create this wiki link"}
    return _open_or_create_note(api, root, target)


def _get_note_templates(api: JsApi) -> list[dict]:
    root = _workspace_root(api)
    if root is None:
        return []
    templates_root = root / _TEMPLATE_DIR
    if not templates_root.is_dir():
        return []
    try:
        templates_root_resolved = templates_root.resolve()
    except OSError:
        return []
    results: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(templates_root_resolved):
        dirnames[:] = [
            dirname for dirname in dirnames
            if dirname not in _BROWSE_SKIP_DIRS and not dirname.startswith(".")
        ]
        for name in filenames:
            if name.startswith(".") or Path(name).suffix.lower() not in _MD_SUFFIXES:
                continue
            full = Path(dirpath) / name
            try:
                if full.is_symlink():
                    continue
                resolved = full.resolve()
            except OSError:
                continue
            if not resolved.is_relative_to(templates_root_resolved) or not resolved.is_file():
                continue
            relative = resolved.relative_to(templates_root_resolved).as_posix()
            results.append({
                "name": resolved.stem,
                "relative": relative,
                "path": str(resolved),
            })
    results.sort(key=lambda item: item["relative"].casefold())
    return results


def _open_daily_note(api: JsApi, date_str: str = "") -> dict:
    root = _workspace_root(api)
    if root is None:
        return {"status": "error", "message": "No workspace"}
    note_date = _coerce_note_date(date_str)
    if note_date is None:
        return {"status": "error", "message": "Invalid date"}
    try:
        target = (root / _DAILY_DIR / f"{note_date.isoformat()}.md").resolve()
    except OSError as exc:
        return {"status": "error", "message": str(exc)}
    if not target.is_relative_to(root):
        return {"status": "error", "message": "Path traversal rejected"}
    return _open_or_create_note(
        api,
        root,
        target,
        template_path=_default_daily_template(root),
        title=note_date.isoformat(),
        note_date=note_date,
    )


def _open_or_create_note(
    api: JsApi,
    root: Path,
    target: Path,
    *,
    template_path: Path | None = None,
    title: str | None = None,
    note_date: date | None = None,
) -> dict:
    try:
        created = not target.exists()
        if created:
            target.parent.mkdir(parents=True, exist_ok=True)
            content = _render_note_content(
                root,
                target,
                title=title,
                template_path=template_path,
                note_date=note_date,
            )
            _atomic_write_text(target, content)
            _invalidate_note_indexes(api)
        elif not target.is_file():
            return {"status": "error", "message": "Target is not a file"}
        api._load(target)
    except OSError as exc:
        return {"status": "error", "message": str(exc)}
    return {
        "status": "created" if created else "ok",
        "path": str(target),
        "relative": str(target.relative_to(root)),
        "name": target.name,
        "new_file": created,
    }


def _render_note_content(
    root: Path,
    target: Path,
    *,
    title: str | None = None,
    template_path: Path | None = None,
    note_date: date | None = None,
) -> str:
    note_title = title or _pretty_title(target)
    note_date = note_date or datetime.now().astimezone().date()
    if template_path is None:
        return f"# {note_title}\n"
    template = template_path.read_text(encoding="utf-8")
    values = {
        "date": note_date.isoformat(),
        "filename": target.name,
        "path": target.relative_to(root).as_posix(),
        "slug": _slugify(note_title),
        "stem": target.stem,
        "title": note_title,
    }
    return _TOKEN_RE.sub(lambda match: values.get(match.group(1), match.group(0)), template)


def _workspace_root(api: JsApi) -> Path | None:
    if api._browse_root is None:
        return None
    try:
        root = api._browse_root.resolve()
    except OSError:
        return None
    return root if root.is_dir() else None


def _resolve_note_target(api: JsApi, root: Path, raw_target: str) -> Path | None:
    rel_name = normalize_note_name(raw_target)
    if not rel_name:
        return None
    base = _default_note_base(api, root)
    try:
        target = (base / rel_name).resolve()
    except OSError:
        return None
    if not target.is_relative_to(root):
        return None
    if target.suffix.lower() not in _MD_SUFFIXES:
        target = target.with_name(target.name + ".md")
    return target


def _default_note_base(api: JsApi, root: Path) -> Path:
    if api._current_path is None:
        return root
    try:
        current = api._current_path.resolve()
    except OSError:
        return root
    if current.is_relative_to(root):
        return current.parent
    return root


def _resolve_template(root: Path, template_path: str) -> Path | None:
    if not isinstance(template_path, str) or not template_path.strip():
        return None
    templates_root = root / _TEMPLATE_DIR
    try:
        templates_root_resolved = templates_root.resolve()
        candidate = (templates_root_resolved / template_path).resolve()
    except OSError:
        return None
    if not candidate.is_relative_to(templates_root_resolved):
        return None
    if candidate.suffix.lower() not in _MD_SUFFIXES or not candidate.is_file():
        return None
    return candidate


def _default_daily_template(root: Path) -> Path | None:
    for name in ("Daily.md", "Daily.markdown", "daily.md", "daily.markdown"):
        candidate = _resolve_template(root, name)
        if candidate is not None:
            return candidate
    return None


def _coerce_note_date(date_str: str) -> date | None:
    if isinstance(date_str, str) and date_str.strip():
        try:
            return date.fromisoformat(date_str.strip())
        except ValueError:
            return None
    return datetime.now().astimezone().date()


def _invalidate_note_indexes(api: JsApi) -> None:
    api._link_index = None
    api._link_index_fp = None
    api._link_index_root = None


def _pretty_title(target: Path) -> str:
    return target.stem.replace("_", " ").replace("-", " ").strip() or target.stem


def _slugify(text: str) -> str:
    slug = text.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug, flags=re.ASCII)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug or "note"
