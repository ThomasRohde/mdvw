"""Workspace wiki-link helpers for mdvw.

This module is intentionally a small facade. The implementation lives in
focused helpers:

- ``link_support.py`` for parsing/rendering primitives
- ``link_index.py`` for indexing and resolution
- ``link_graph.py`` for graph payload construction
"""

from __future__ import annotations

from .link_graph import build_graph_payload
from .link_index import (
    build_link_index,
    diagnose_wiki_links,
    fingerprint_root,
    incoming_links,
    resolve_wiki_link,
    search_wiki_targets,
)
from .link_support import (
    FileEntry,
    Heading,
    IncomingLink,
    LinkIndex,
    ResolvedLink,
    WikiLink,
    extract_headings,
    normalize_note_name,
    parse_wiki_inner,
    parse_wiki_links,
    render_wiki_links,
    source_relative_link,
    uri_fragment_for_heading,
)

__all__ = [
    "FileEntry",
    "Heading",
    "IncomingLink",
    "LinkIndex",
    "ResolvedLink",
    "WikiLink",
    "build_graph_payload",
    "build_link_index",
    "diagnose_wiki_links",
    "extract_headings",
    "fingerprint_root",
    "incoming_links",
    "normalize_note_name",
    "parse_wiki_inner",
    "parse_wiki_links",
    "render_wiki_links",
    "resolve_wiki_link",
    "search_wiki_targets",
    "source_relative_link",
    "uri_fragment_for_heading",
]
