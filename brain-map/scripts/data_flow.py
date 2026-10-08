#!/usr/bin/env python3
"""
data_flow.py — detect "feeds" data-flow threads by matching writer and reader path constants.

Reads path constants from Python (HOME / "x" / "y", Path.home() chains, string literals)
and JavaScript (path.join(homedir(), ...) patterns) assigned to names matching *_PATH/*_DIR.

Writers: discovered from lib/*.py, attributed to nodes by (a) direct script_path match
in the tree, or (b) owner_overrides from enrichment.json.

Readers: discovered from hand-listed files per dashboard tab (enrichment.json), with
paths extracted live via regex for every *_PATH/*_DIR constant in that file.

Threading: matches writer and reader by resolved path equality (e.g., ~/.agents/bench/metrics),
emits {a: writer_node_id, b: tab_id, label, type: "feeds"} synapses, and reports unmatched
writers/readers as gaps.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
from typing import TypedDict

HERE = Path(__file__).parent.parent
LIB_DIR = Path.home() / ".agents" / "lib"
ENRICHMENT_PATH = HERE / "enrichment.json"


class WriterRecord(TypedDict):
    node_id: str
    path: str
    source_file: str


class ReaderRecord(TypedDict):
    tab_id: str
    path: str
    source_file: str


class FeedsThread(TypedDict):
    a: str
    b: str
    label: str
    type: str


def extract_py_path_constants(source: str) -> dict[str, str]:
    """Extract *_PATH/*_DIR constants from Python source.

    Handles:
      - Path.home() / "x" / "y" chains (aliased HOME = Path.home() earlier)
      - home / "x" (if home is an alias)
      - String literals
      - Resolves to ~ formatted paths under home directory

    Returns {name: "~/resolved/path"} for matches, empty dict for non-resolvable.
    """
    constants = {}

    # Find HOME alias if present: HOME = Path.home()
    home_alias_match = re.search(r"^\s*(\w+)\s*=\s*Path\.home\(\)", source, re.MULTILINE)
    home_alias = home_alias_match.group(1) if home_alias_match else "Path"

    # Pattern 1: NAME = HOME / "a" / "b" / ...  or  NAME = home / "x"
    # (home_alias could be HOME, home, or anything else)
    pattern_chain = rf"^(\w+(?:_PATH|_DIR))\s*=\s*({home_alias})\s*(?:\.resolve\(\))?\s*((?:\s*/\s*['\"][\w.\-]+['\"])+)"
    for match in re.finditer(pattern_chain, source, re.MULTILINE):
        name, alias, segments_str = match.groups()
        # segments_str is like " / "x" / "y"" — extract quoted strings
        parts = re.findall(r"['\"]([^'\"]+)['\"]", segments_str)
        if parts:
            resolved = str(Path.home() / Path(*parts))
            if resolved.startswith(str(Path.home())):
                constants[name] = resolved.replace(str(Path.home()), "~")

    # Pattern 2: NAME = Path.home() / "x" / "y" (inline, not aliased)
    pattern_inline = r"^(\w+(?:_PATH|_DIR))\s*=\s*Path\.home\(\)\s*(?:\.resolve\(\))?\s*((?:\s*/\s*['\"][\w.\-]+['\"])+)"
    for match in re.finditer(pattern_inline, source, re.MULTILINE):
        name, segments_str = match.groups()
        parts = re.findall(r"['\"]([^'\"]+)['\"]", segments_str)
        if parts:
            resolved = str(Path.home() / Path(*parts))
            if resolved.startswith(str(Path.home())):
                constants[name] = resolved.replace(str(Path.home()), "~")

    # Pattern 3: NAME = "~/x/y" (direct string literal)
    pattern_literal = r"^(\w+(?:_PATH|_DIR))\s*=\s*['\"]([~/][^'\"]*)['\"]"
    for match in re.finditer(pattern_literal, source, re.MULTILINE):
        name, path_str = match.groups()
        if path_str.startswith("~/"):
            constants[name] = path_str
        else:
            # Resolve relative to home
            resolved = str(Path.home() / path_str)
            if resolved.startswith(str(Path.home())):
                constants[name] = resolved.replace(str(Path.home()), "~")

    return constants


def extract_js_path_constants(source: str) -> dict[str, str]:
    """Extract *_PATH/*_DIR constants from JavaScript source.

    Handles: path.join(homedir(), 'a', 'b', ...) patterns.
    Returns {name: "~/resolved/path"}.
    """
    constants = {}

    # Pattern: NAME = path.join(homedir(), 'a', 'b', ...)
    pattern = r"const\s+(\w+(?:_PATH|_DIR))\s*=\s*(?:path\.)?join\(\s*homedir\(\)\s*((?:,\s*['\"][^'\"]+['\"])*)"
    for match in re.finditer(pattern, source):
        name, args_str = match.groups()
        # args_str is like ", 'a', 'b'" — extract all quoted strings
        parts = re.findall(r"['\"]([^'\"]+)['\"]", args_str)
        if parts:
            resolved = str(Path.home() / Path(*parts))
            if resolved.startswith(str(Path.home())):
                constants[name] = resolved.replace(str(Path.home()), "~")

    return constants


def discover_writers(
    lib_dir: Path, owner_overrides: dict[str, str], tree: dict
) -> list[WriterRecord]:
    """Discover path constants in lib/*.py files, attributed to node ids.

    Attribution:
      1. If script_path in tree matches the source file → node_id from tree
      2. Else if module stem in owner_overrides → use override node_id
      3. Else skip (no attribution found)

    Returns list of {node_id, path, source_file} for each matched constant.
    """
    writers = []

    # Build a map of script_path -> node_id from the tree
    script_to_node = {}
    def index_nodes(node: dict) -> None:
        if path := node.get("path"):
            script_to_node[path] = node.get("id", "")
        for child in node.get("children", []):
            index_nodes(child)
    index_nodes(tree)

    if not lib_dir.is_dir():
        return writers

    for py_file in sorted(lib_dir.glob("*.py")):
        # Skip tests
        if "test" in py_file.name or py_file.name.startswith("_"):
            continue

        try:
            source = py_file.read_text(encoding="utf-8")
        except Exception:
            continue

        constants = extract_py_path_constants(source)
        if not constants:
            continue

        # Try to attribute this file to a node
        node_id = None

        # Check direct script_path match (repo-relative)
        try:
            repo_rel = str(py_file.relative_to(Path.home() / ".agents"))
            if repo_rel in script_to_node:
                node_id = script_to_node[repo_rel]
        except (ValueError, OSError):
            pass

        # Check module stem in overrides
        if not node_id:
            module_stem = py_file.stem
            if module_stem in owner_overrides:
                node_id = owner_overrides[module_stem]

        if not node_id:
            continue

        repo_rel = str(py_file.relative_to(Path.home() / ".agents"))
        for const_name, path_value in constants.items():
            writers.append(
                WriterRecord(node_id=node_id, path=path_value, source_file=repo_rel)
            )

    return writers


def discover_readers(tab_readers: dict[str, list[str]], dashboard_dir: Path) -> list[ReaderRecord]:
    """Discover path constants in hand-listed dashboard reader files.

    For each tab and its file list, scrape constants from that file.
    Returns list of {tab_id, path, source_file} for each matched constant.
    """
    readers = []

    for tab_id, file_list in tab_readers.items():
        for file_name in file_list:
            file_path = dashboard_dir / file_name

            # Try to read the file
            try:
                source = file_path.read_text(encoding="utf-8")
            except Exception:
                continue

            # Choose parser based on extension
            if file_path.suffix == ".js" or file_path.suffix == ".jsx":
                constants = extract_js_path_constants(source)
            elif file_path.suffix == ".py":
                constants = extract_py_path_constants(source)
            else:
                continue

            if not constants:
                continue

            # Resolve file_name to repo-relative (from dashboard root)
            try:
                file_repo_rel = str(file_path.relative_to(Path.home() / ".agents"))
            except (ValueError, OSError):
                file_repo_rel = file_name

            for const_name, path_value in constants.items():
                readers.append(
                    ReaderRecord(tab_id=tab_id, path=path_value, source_file=file_repo_rel)
                )

    return readers


def match_threads(
    writers: list[WriterRecord], readers: list[ReaderRecord]
) -> tuple[list[FeedsThread], list[dict]]:
    """Match writers and readers by path equality, emit synapses and gaps.

    Returns (threads, gaps) where:
      - threads: list of {a: writer_node_id, b: tab_id, label, type: "feeds"}
      - gaps: list of {kind: "unmatched_writer"|"unmatched_reader", path, source_file}
    """
    threads: list[FeedsThread] = []
    gaps: list[dict] = []

    # Index writers and readers by path
    writers_by_path: dict[str, list[WriterRecord]] = {}
    for w in writers:
        writers_by_path.setdefault(w["path"], []).append(w)

    readers_by_path: dict[str, list[ReaderRecord]] = {}
    for r in readers:
        readers_by_path.setdefault(r["path"], []).append(r)

    # Match: for each unique path, connect all writers to all readers
    all_paths = set(writers_by_path.keys()) | set(readers_by_path.keys())
    matched_writers: set[tuple[str, str, str]] = set()  # (path, source_file, node_id)
    matched_readers: set[tuple[str, str, str]] = set()  # (path, source_file, tab_id)

    for path in sorted(all_paths):
        ws = writers_by_path.get(path, [])
        rs = readers_by_path.get(path, [])

        for w in ws:
            for r in rs:
                label = f"Writer path: {path} ← {w['source_file']}"
                threads.append(
                    FeedsThread(
                        a=w["node_id"],
                        b=r["tab_id"],
                        label=label,
                        type="feeds",
                    )
                )
                matched_writers.add((w["path"], w["source_file"], w["node_id"]))
                matched_readers.add((r["path"], r["source_file"], r["tab_id"]))

    # Report unmatched writers and readers
    for w in writers:
        if (w["path"], w["source_file"], w["node_id"]) not in matched_writers:
            gaps.append(
                {
                    "kind": "unmatched_writer",
                    "path": w["path"],
                    "source_file": w["source_file"],
                    "node_id": w["node_id"],
                }
            )

    for r in readers:
        if (r["path"], r["source_file"], r["tab_id"]) not in matched_readers:
            gaps.append(
                {
                    "kind": "unmatched_reader",
                    "path": r["path"],
                    "source_file": r["source_file"],
                    "tab_id": r["tab_id"],
                }
            )

    return threads, gaps


def discover_dashboard_readers(enrichment: dict) -> dict[str, list[str]]:
    """Extract dashboard_tab_readers from enrichment.json.

    Returns {tab_id: [file1, file2, ...]} relative to dashboard dir.
    """
    return enrichment.get("dashboard_tab_readers", {})


def main() -> None:
    """Standalone entry point for testing/debugging."""
    enrichment = json.loads(ENRICHMENT_PATH.read_text(encoding="utf-8"))

    # Minimal tree stub for writer attribution
    tree = {
        "id": "root",
        "path": None,
        "children": [
            {
                "id": "ticket-pipeline",
                "path": "lib/agents/ticket_pipeline.py",
                "children": [],
            },
            {
                "id": "usage-scan",
                "path": "lib/agents/usage_scan.py",
                "children": [],
            },
        ],
    }

    owner_overrides = enrichment.get("writer_module_owners", {})
    writers = discover_writers(LIB_DIR, owner_overrides, tree)

    dashboard_dir = Path.home() / ".agents" / "dashboard"
    tab_readers = discover_dashboard_readers(enrichment)
    readers = discover_readers(tab_readers, dashboard_dir)

    threads, gaps = match_threads(writers, readers)

    print(f"Found {len(writers)} writer(s), {len(readers)} reader(s)")
    print(f"Matched {len(threads)} thread(s), {len(gaps)} gap(s)")

    # Report gaps
    for gap in gaps:
        if gap["kind"] == "unmatched_writer":
            print(
                f"  UNMATCHED WRITER: {gap['node_id']} / {gap['path']} (from {gap['source_file']})"
            )
        else:
            print(
                f"  UNMATCHED READER: {gap['tab_id']} / {gap['path']} (from {gap['source_file']})"
            )


if __name__ == "__main__":
    main()
