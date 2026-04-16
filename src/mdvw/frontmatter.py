"""YAML frontmatter extraction.

The fence must be on the very first line of the document. A closing fence
(``---`` or ``...``) on its own line terminates the block; everything after
it is the markdown body. Missing close → treat the whole document as body
(no frontmatter), matching what most static-site generators do.
"""
from __future__ import annotations

import re

import yaml

# Closing line is exactly `---` or `...`, optionally followed by CR/LF.
_CLOSE_RE = re.compile(r"(?m)^(?:---|\.\.\.)\r?\n")


def split_frontmatter(source: str) -> tuple[str | None, str]:
    """Return (raw_yaml_without_fences, body).

    ``(None, source)`` if the document does not start with a ``---`` fence
    or has no matching close.
    """
    if not source.startswith("---"):
        return None, source
    # The opening fence line must be exactly '---' — not '----', not '--- foo'.
    nl = source.find("\n")
    if nl == -1:
        return None, source
    first_line = source[: nl].rstrip("\r")
    if first_line != "---":
        return None, source
    rest = source[nl + 1 :]
    m = _CLOSE_RE.search(rest)
    if m is None:
        return None, source
    yaml_block = rest[: m.start()]
    body = rest[m.end() :]
    return yaml_block, body


def parse_frontmatter(source: str) -> tuple[dict | None, str, str | None]:
    """Return ``(meta, body, error)``.

    - No frontmatter: ``(None, source, None)``.
    - Parsed as mapping: ``(dict, body, None)``.
    - Parsed as non-mapping (scalar/list): ``(None, body, error)``.
    - Parse failure: ``(None, body, error_message)``.
    """
    raw, body = split_frontmatter(source)
    if raw is None:
        return None, source, None
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return None, body, str(exc)
    if data is None:
        return {}, body, None
    if not isinstance(data, dict):
        return None, body, f"frontmatter must be a mapping, got {type(data).__name__}"
    return data, body, None
