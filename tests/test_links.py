from __future__ import annotations

import os
from pathlib import Path

import pytest

from mdvw.links import (
    build_graph_payload,
    build_link_index,
    diagnose_wiki_links,
    incoming_links,
    normalize_note_name,
    parse_wiki_links,
    resolve_wiki_link,
    search_wiki_targets,
)


def _make_files(root: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def test_parse_wiki_links_core_shapes():
    links = parse_wiki_links(
        "[[Note]]\n[[Note|Label]]\n[[Note#Heading|Alias]]\n[[#Local]]\n"
    )

    assert [(link.target, link.heading, link.alias, link.display) for link in links] == [
        ("Note", "", "", "Note"),
        ("Note", "", "Label", "Label"),
        ("Note", "Heading", "Alias", "Alias"),
        ("", "Local", "", "Local"),
    ]


def test_parse_skips_fenced_and_inline_code():
    links = parse_wiki_links("`[[Nope]]`\n```\n[[Nope]]\n```\n[[Yep]]")

    assert [link.target for link in links] == ["Yep"]


def test_resolve_unique_stem_and_heading(tmp_path):
    root = _make_files(tmp_path, {
        "Index.md": "[[Note#Details]]",
        "Note.md": "# Title\n## Details\n",
    })
    index = build_link_index(root)
    source = root / "Index.md"

    resolved = resolve_wiki_link("Note#Details", source, index)

    assert resolved.status == "ok"
    assert resolved.target_path == (root / "Note.md").resolve()
    assert resolved.heading == "Details"


def test_resolve_current_file_heading(tmp_path):
    root = _make_files(tmp_path, {"Index.md": "# Local\n[[#Local]]"})
    index = build_link_index(root)

    resolved = resolve_wiki_link("#Local", root / "Index.md", index)

    assert resolved.status == "ok"
    assert resolved.target_path == (root / "Index.md").resolve()


def test_ambiguous_stem_warns_instead_of_guessing(tmp_path):
    root = _make_files(tmp_path, {
        "A/Note.md": "# A",
        "B/Note.md": "# B",
        "Index.md": "[[Note]]",
    })
    index = build_link_index(root)

    resolved = resolve_wiki_link("Note", root / "Index.md", index)
    issues = diagnose_wiki_links((root / "Index.md").read_text(), root / "Index.md", index)

    assert resolved.status == "ambiguous"
    assert any("Ambiguous wiki link" in issue["message"] for issue in issues)


def test_missing_heading_diagnostic(tmp_path):
    root = _make_files(tmp_path, {
        "Index.md": "[[Note#Missing]]",
        "Note.md": "# Existing",
    })
    index = build_link_index(root)

    issues = diagnose_wiki_links((root / "Index.md").read_text(), root / "Index.md", index)

    assert any("Missing wiki heading" in issue["message"] for issue in issues)


def test_incoming_links_returns_resolved_backlinks(tmp_path):
    root = _make_files(tmp_path, {
        "A.md": "[[Target]]",
        "B.md": "[[Target#H]]",
        "Target.md": "# H",
    })
    index = build_link_index(root)

    incoming = incoming_links(index, (root / "Target.md").resolve())

    assert [item.source_relative for item in incoming] == ["A.md", "B.md"]


def test_graph_payload_includes_resolved_unresolved_and_missing_heading(tmp_path):
    root = _make_files(tmp_path, {
        "Index.md": "[[Note]]\n[[Ghost]]\n[[Note#Missing]]",
        "Note.md": "# Note",
        "Orphan.md": "# Orphan",
    })
    index = build_link_index(root)

    payload = build_graph_payload(index, mode="workspace", include_orphans=False)

    node_ids = {node["id"] for node in payload["nodes"]}
    edge_statuses = {(edge["target"], edge["status"]) for edge in payload["edges"]}
    assert "Index.md" in node_ids
    assert "Note.md" in node_ids
    assert "Orphan.md" not in node_ids
    assert any(
        node["type"] == "unresolved" and node["label"] == "Ghost"
        for node in payload["nodes"]
    )
    assert ("Note.md", "ok") in edge_statuses
    assert ("Note.md", "missing_heading") in edge_statuses
    assert any(status == "missing" for _target, status in edge_statuses)


def test_graph_payload_can_hide_unresolved_nodes(tmp_path):
    root = _make_files(tmp_path, {
        "Index.md": "[[Note]]\n[[Ghost]]",
        "Note.md": "# Note",
    })
    index = build_link_index(root)

    payload = build_graph_payload(index, include_unresolved=False, include_orphans=False)

    assert {node["id"] for node in payload["nodes"]} == {"Index.md", "Note.md"}
    assert {edge["status"] for edge in payload["edges"]} == {"ok"}


def test_graph_payload_local_depth_expands_bidirectionally(tmp_path):
    root = _make_files(tmp_path, {
        "A.md": "[[B]]",
        "B.md": "[[C]]",
        "C.md": "[[D]]",
        "D.md": "",
    })
    index = build_link_index(root)

    depth_1 = build_graph_payload(index, root / "A.md", mode="local", depth=1)
    depth_2 = build_graph_payload(index, root / "A.md", mode="local", depth=2)

    assert {node["id"] for node in depth_1["nodes"]} == {"A.md", "B.md"}
    assert {node["id"] for node in depth_2["nodes"]} == {"A.md", "B.md", "C.md"}
    assert any(node["id"] == "A.md" and node["current"] for node in depth_2["nodes"])


def test_search_wiki_targets_prefers_stem_when_unique(tmp_path):
    root = _make_files(tmp_path, {
        "Index.md": "",
        "Note.md": "# Details",
    })
    index = build_link_index(root)

    results = search_wiki_targets(index, "det", root / "Index.md")

    assert any(r["type"] == "heading" and r["insert"] == "Note#Details" for r in results)


def test_search_wiki_targets_uses_relative_path_for_ambiguous_stems(tmp_path):
    root = _make_files(tmp_path, {
        "Index.md": "",
        "A/Note.md": "# A",
        "B/Note.md": "# B",
    })
    index = build_link_index(root)

    results = search_wiki_targets(index, "note", root / "Index.md")
    inserts = {r["insert"] for r in results if r["type"] == "file"}

    assert "A/Note" in inserts
    assert "B/Note" in inserts


def test_symlink_to_outside_root_is_ignored(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "Secret.md"
    secret.write_text("# Secret", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    (root / "Index.md").write_text("[[Secret]]", encoding="utf-8")
    link = root / "Secret.md"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this platform")

    index = build_link_index(root)

    assert resolve_wiki_link("Secret", root / "Index.md", index).status == "missing"


def test_normalize_note_name_sanitizes_and_adds_suffix():
    assert normalize_note_name("Folder/New Note#Part") == "Folder/New Note.md"
    assert normalize_note_name("../Secret") == "Secret.md"
