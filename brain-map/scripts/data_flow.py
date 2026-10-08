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


def extract_js_reader_paths(source: str) -> list[str]:
    """Every data path and lib script a dashboard main-process file uses, whatever the constant is called.

    - join(homedir(), 'a', 'b') anywhere -> "~/a/b" (the venv interpreter is skipped: it isn't data)
    - a 'lib', 'x.py' pair in any join(...) -> "lib/x.py": the tab runs that script, so the script's owner feeds it
    Order kept, duplicates dropped."""
    out: list[str] = []
    for m in re.finditer(r"join\(\s*homedir\(\)\s*((?:,\s*['\"][^'\"]+['\"])+)\s*\)", source):
        parts = re.findall(r"['\"]([^'\"]+)['\"]", m.group(1))
        if parts and "venv" not in parts and not (len(parts) >= 2 and parts[-2] == "lib" and parts[-1].endswith(".py")):
            out.append("~/" + "/".join(parts))
    for m in re.finditer(r"['\"]lib['\"]\s*,\s*['\"](\w+\.py)['\"]", source):
        out.append("lib/" + m.group(1))
    return list(dict.fromkeys(out))


def discover_writers(
    lib_dir: Path, owner_overrides: dict[str, str], tree: dict,
    helpers: list[str] | None = None, repo_root: Path | None = None,
) -> list[WriterRecord]:
    """What each map node produces, from lib/*.py, as {node_id, path, source_file} records.

    A lib script is attributed to a node by (1) the node's `path` (repo-relative) or (2) owner_overrides[module stem];
    unattributed scripts are skipped. For an attributed script it records:
      - the script itself ("lib/x.py"): a dashboard tab that runs it is fed by that node;
      - its own *_PATH/*_DIR constants;
      - the constants of each helper module it calls (e.g. job_events.job_run writes ~/.claude/logs/jobs for it).
    """
    repo_root = repo_root or Path.home() / ".agents"
    writers: list[WriterRecord] = []
    script_to_node: dict[str, str] = {}

    def index_nodes(node: dict) -> None:
        if path := node.get("path"):
            script_to_node[path] = node.get("id", "")
        for child in node.get("children", []):
            index_nodes(child)
    index_nodes(tree)

    if not lib_dir.is_dir():
        return writers

    def read(f: Path) -> str:
        try:
            return f.read_text(encoding="utf-8")
        except Exception:
            return ""

    helper_paths = {h: extract_py_path_constants(read(lib_dir / f"{h}.py")) for h in (helpers or [])}

    for py_file in sorted(lib_dir.glob("*.py")):
        if "test" in py_file.name or py_file.name.startswith("_"):
            continue
        try:
            repo_rel = str(py_file.relative_to(repo_root))
        except ValueError:
            repo_rel = f"lib/{py_file.name}"
        node_id = script_to_node.get(repo_rel) or owner_overrides.get(py_file.stem)
        if not node_id:
            continue
        source = read(py_file)
        found = {repo_rel: None}
        found.update({v: None for v in extract_py_path_constants(source).values()})
        for helper, consts in helper_paths.items():
            if py_file.stem != helper and re.search(rf"\b{re.escape(helper)}\.", source):
                found.update({v: None for v in consts.values()})
        for path_value in found:
            writers.append(WriterRecord(node_id=node_id, path=path_value, source_file=repo_rel))

    return writers


def discover_readers(tab_readers: dict[str, list[str]], dashboard_dir: Path,
                     warnings: list[str] | None = None) -> list[ReaderRecord]:
    """What each dashboard tab reads or runs, from the main-process files listed per tab node id (enrichment.json
    `dashboard_tab_readers`, paths relative to dashboard/electron/main). A listed file that doesn't exist is a
    warning, never a silent skip: that silence hid a wrong folder for weeks (2026-10-08)."""
    readers: list[ReaderRecord] = []
    for tab_id, file_list in tab_readers.items():
        for file_name in file_list:
            file_path = (dashboard_dir / file_name).resolve()
            try:
                source = file_path.read_text(encoding="utf-8")
            except OSError:
                if warnings is not None:
                    warnings.append(f"{tab_id}: reader file not found: {file_name} (in {dashboard_dir})")
                continue
            if file_path.suffix in (".js", ".jsx", ".mjs"):
                paths = extract_js_reader_paths(source)
            elif file_path.suffix == ".py":
                paths = list(extract_py_path_constants(source).values())
            else:
                continue
            try:
                rel = str(file_path.relative_to(Path.home() / ".agents"))
            except ValueError:
                rel = file_name
            readers.extend(ReaderRecord(tab_id=tab_id, path=p, source_file=rel) for p in paths)
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

    by_pair: dict[tuple[str, str], FeedsThread] = {}
    shared: dict[tuple[str, str], list[str]] = {}
    for path in sorted(all_paths):
        ws = writers_by_path.get(path, [])
        rs = readers_by_path.get(path, [])

        for w in ws:
            for r in rs:
                key = (w["node_id"], r["tab_id"])
                if key not in by_pair:
                    by_pair[key] = FeedsThread(a=key[0], b=key[1], label="", type="feeds")
                    threads.append(by_pair[key])
                    shared[key] = []
                if path not in shared[key]:
                    shared[key].append(path)
                matched_writers.add((w["path"], w["source_file"], w["node_id"]))
                matched_readers.add((r["path"], r["source_file"], r["tab_id"]))

    for key, t in by_pair.items():
        runs = [p for p in shared[key] if p.startswith("lib/")]
        data = [p for p in shared[key] if not p.startswith("lib/")]
        t["label"] = "; ".join(filter(None, [
            ("the tab runs " + ", ".join(runs)) if runs else "",
            ("the tab reads " + ", ".join(data)) if data else "",
        ]))

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
