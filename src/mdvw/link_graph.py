"""Wiki-link graph payload construction for mdvw."""

from __future__ import annotations

from pathlib import Path

from .link_index import _resolve_source, resolve_wiki_link
from .link_support import FileEntry, LinkIndex, _safe_relative, normalize_note_name


def build_graph_payload(
    index: LinkIndex,
    current_path: Path | None = None,
    *,
    mode: str = "workspace",
    depth: int = 1,
    include_unresolved: bool = True,
    include_orphans: bool = True,
    max_nodes: int = 500,
    max_edges: int = 2_000,
) -> dict:
    """Return a JSON-serializable wiki-link graph for the workspace."""
    mode = "local" if mode == "local" else "workspace"
    depth = min(2, max(1, int(depth)))
    max_nodes = min(5_000, max(1, int(max_nodes)))
    max_edges = min(20_000, max(1, int(max_edges)))

    all_nodes = _graph_note_nodes(index)
    all_edges, unresolved_nodes = _graph_edges(index)
    all_nodes.update(unresolved_nodes)

    filtered_edges = [
        edge
        for edge in all_edges
        if include_unresolved or all_nodes.get(edge["target"], {}).get("type") != "unresolved"
    ]

    local_distances: dict[str, int] = {}
    if mode == "local":
        local_distances = _local_graph_node_distances(index, current_path, filtered_edges, depth)
        if not local_distances:
            return _graph_payload(
                nodes=[],
                edges=[],
                mode=mode,
                depth=depth,
                total_nodes=len(all_nodes),
                total_edges=len(filtered_edges),
                max_nodes=max_nodes,
                max_edges=max_edges,
                message="No current note",
            )
        visible_node_ids = set(local_distances)
    else:
        visible_node_ids = {node_id for node_id, node in all_nodes.items() if _node_visible(node)}
        if not include_orphans:
            connected = set()
            for edge in filtered_edges:
                connected.add(edge["source"])
                connected.add(edge["target"])
            visible_node_ids = {node_id for node_id in visible_node_ids if node_id in connected}

    visible_edges = [
        edge
        for edge in filtered_edges
        if edge["source"] in visible_node_ids and edge["target"] in visible_node_ids
    ]

    truncated = False
    ordered_node_ids = sorted(
        visible_node_ids,
        key=lambda node_id: _graph_node_sort_key(
            all_nodes[node_id],
            local_distances.get(node_id) if mode == "local" else None,
        ),
    )
    if len(ordered_node_ids) > max_nodes:
        truncated = True
        keep = set(ordered_node_ids[:max_nodes])
        visible_node_ids = keep
        ordered_node_ids = ordered_node_ids[:max_nodes]
        visible_edges = [
            edge
            for edge in visible_edges
            if edge["source"] in visible_node_ids and edge["target"] in visible_node_ids
        ]
    if len(visible_edges) > max_edges:
        truncated = True
        visible_edges = visible_edges[:max_edges]

    nodes = [
        dict(all_nodes[node_id])
        for node_id in ordered_node_ids
        if node_id in visible_node_ids
    ]
    _annotate_graph_degrees(nodes, visible_edges, current_path, index)
    return _graph_payload(
        nodes=nodes,
        edges=visible_edges,
        mode=mode,
        depth=depth,
        total_nodes=len(all_nodes),
        total_edges=len(filtered_edges),
        max_nodes=max_nodes,
        max_edges=max_edges,
        truncated=truncated,
    )


def _graph_note_nodes(index: LinkIndex) -> dict[str, dict]:
    nodes: dict[str, dict] = {}
    for entry in sorted(index.files.values(), key=lambda item: item.relative.casefold()):
        nodes[entry.relative] = {
            "id": entry.relative,
            "type": "note",
            "label": entry.stem,
            "path": str(entry.path),
            "relative": entry.relative,
            "heading_count": len(entry.headings),
        }
    return nodes


def _graph_edges(index: LinkIndex) -> tuple[list[dict], dict[str, dict]]:
    edges: list[dict] = []
    unresolved_nodes: dict[str, dict] = {}
    edge_seen: set[str] = set()
    for source, links in sorted(
        index.links.items(),
        key=lambda item: index.files.get(item[0], FileEntry(item[0], "", "", "", ())).relative,
    ):
        source_entry = index.files.get(source)
        if source_entry is None:
            continue
        for link in links:
            resolved = resolve_wiki_link(link, source, index)
            if resolved.status == "invalid":
                continue
            target_id = ""
            target_relative = ""
            target_path = ""
            if resolved.target_path is not None and resolved.target_path in index.files:
                target_entry = index.files[resolved.target_path]
                target_id = target_entry.relative
                target_relative = target_entry.relative
                target_path = str(target_entry.path)
            elif resolved.status in {"missing", "ambiguous"}:
                target_id = _graph_unresolved_id(link)
                unresolved_nodes.setdefault(
                    target_id,
                    _graph_unresolved_node(target_id, link, resolved, index),
                )
            if not target_id or target_id == source_entry.relative:
                continue
            edge_id = f"{source_entry.relative}:{link.line}:{link.col}:{target_id}:{link.raw}"
            if edge_id in edge_seen:
                continue
            edge_seen.add(edge_id)
            edges.append({
                "id": edge_id,
                "source": source_entry.relative,
                "target": target_id,
                "status": resolved.status,
                "raw": link.raw,
                "display": link.display,
                "heading": resolved.heading,
                "line": link.line,
                "col": link.col,
                "message": resolved.message,
                "source_path": str(source_entry.path),
                "source_relative": source_entry.relative,
                "target_path": target_path,
                "target_relative": target_relative,
            })
    return edges, unresolved_nodes


def _graph_unresolved_id(link) -> str:
    target = (link.target or link.raw).split("#", 1)[0].strip().replace("\\", "/")
    normalized = normalize_note_name(target)
    key = normalized or target or link.raw
    return f"unresolved:{Path(key).with_suffix('').as_posix().casefold()}"


def _graph_unresolved_node(
    node_id: str,
    link,
    resolved,
    index: LinkIndex,
) -> dict:
    target = (link.target or link.raw).split("#", 1)[0].strip()
    label = Path(target).stem if target else link.display
    matches = [
        {"path": str(path), "relative": _safe_relative(path, index.root)}
        for path in resolved.matches
    ]
    return {
        "id": node_id,
        "type": "unresolved",
        "label": label or "Unresolved",
        "target": target or link.raw,
        "status": resolved.status,
        "message": resolved.message,
        "matches": matches,
    }


def _local_graph_node_distances(
    index: LinkIndex,
    current_path: Path | None,
    edges: list[dict],
    depth: int,
) -> dict[str, int]:
    source = _resolve_source(current_path, index)
    if source is None or source not in index.files:
        return {}
    center = index.files[source].relative
    adjacency: dict[str, set[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge["source"], set()).add(edge["target"])
        adjacency.setdefault(edge["target"], set()).add(edge["source"])

    distances = {center: 0}
    frontier = {center}
    for hop in range(1, depth + 1):
        next_frontier: set[str] = set()
        for node_id in frontier:
            next_frontier.update(adjacency.get(node_id, set()) - distances.keys())
        if not next_frontier:
            break
        for node_id in next_frontier:
            distances[node_id] = hop
        frontier = next_frontier
    return distances


def _node_visible(node: dict) -> bool:
    return node.get("type") in {"note", "unresolved"}


def _graph_node_sort_key(node: dict, local_distance: int | None = None) -> tuple[int, int, str]:
    distance_rank = local_distance if local_distance is not None else 0
    type_rank = 0 if node.get("type") == "note" else 1
    return (
        distance_rank,
        type_rank,
        str(node.get("relative") or node.get("label") or node.get("id")).casefold(),
    )


def _annotate_graph_degrees(
    nodes: list[dict],
    edges: list[dict],
    current_path: Path | None,
    index: LinkIndex,
) -> None:
    in_counts = {node["id"]: 0 for node in nodes}
    out_counts = {node["id"]: 0 for node in nodes}
    for edge in edges:
        if edge["source"] in out_counts:
            out_counts[edge["source"]] += 1
        if edge["target"] in in_counts:
            in_counts[edge["target"]] += 1
    current_id = ""
    source = _resolve_source(current_path, index)
    if source is not None and source in index.files:
        current_id = index.files[source].relative
    for node in nodes:
        node["in"] = in_counts.get(node["id"], 0)
        node["out"] = out_counts.get(node["id"], 0)
        node["degree"] = node["in"] + node["out"]
        node["current"] = node["id"] == current_id


def _graph_payload(
    *,
    nodes: list[dict],
    edges: list[dict],
    mode: str,
    depth: int,
    total_nodes: int,
    total_edges: int,
    max_nodes: int,
    max_edges: int,
    truncated: bool = False,
    message: str = "",
) -> dict:
    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "mode": mode,
            "depth": depth,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "max_nodes": max_nodes,
            "max_edges": max_edges,
            "truncated": truncated,
            "message": message,
        },
    }
