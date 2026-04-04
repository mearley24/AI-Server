#!/usr/bin/env python3
"""Lightweight local knowledge graph utility (API-3 compatibility)."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass
class Node:
    id: str
    node_type: str
    parent: str = ""
    meta: dict[str, Any] | None = None


@dataclass
class Edge:
    source: str
    relation: str
    target: str


class KnowledgeGraph:
    def __init__(self, db_path: str | Path = "data/knowledge_graph.json"):
        self.db_path = Path(db_path)
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self._load()

    def _load(self) -> None:
        if not self.db_path.exists():
            return
        data = json.loads(self.db_path.read_text(encoding="utf-8"))
        self.nodes = {n["id"]: Node(**n) for n in data.get("nodes", [])}
        self.edges = [Edge(**e) for e in data.get("edges", [])]

    def _save(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "nodes": [asdict(n) for n in self.nodes.values()],
            "edges": [asdict(e) for e in self.edges],
        }
        self.db_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def add(self, node_id: str, node_type: str, parent: str = "") -> None:
        self.nodes[node_id] = Node(node_id, node_type, parent=parent, meta={})
        self._save()

    def connect(self, source: str, relation: str, target: str) -> None:
        self.edges.append(Edge(source, relation, target))
        self._save()

    def stats(self) -> dict[str, int]:
        return {"nodes": len(self.nodes), "edges": len(self.edges)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Knowledge graph helper")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--add", nargs=2, metavar=("NODE", "TYPE"))
    ap.add_argument("--parent", default="")
    ap.add_argument("--connect", nargs=3, metavar=("SRC", "REL", "DST"))
    ap.add_argument("--db", default="data/knowledge_graph.json")
    args = ap.parse_args()
    kg = KnowledgeGraph(args.db)
    if args.add:
        kg.add(args.add[0], args.add[1], parent=args.parent)
    if args.connect:
        kg.connect(args.connect[0], args.connect[1], args.connect[2])
    if args.stats or (not args.add and not args.connect):
        print(json.dumps(kg.stats(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
