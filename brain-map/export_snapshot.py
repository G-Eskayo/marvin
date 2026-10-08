#!/usr/bin/env python3
"""
export_snapshot.py — Generate a privacy-filtered public snapshot of the MARVIN brain-map.

Builds a fresh tree from generate.py's functions, then applies privacy filters:
- Locks private projects (no path/openable/code shown)
- Anonymizes machine hostnames to kind + count
- Filters code layers to git-tracked files only (allowlist-based)
- Scans for leaked credentials, paths, IPs, emails

Writes to brain-map/snapshot/{index.html, tree-data.json}.

Usage:
    python export_snapshot.py [--commit HEAD] [--out brain-map/snapshot/]
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent
TEMPLATE_PATH = HERE / "template.html"
SNAPSHOT_DIR = HERE / "snapshot"

import generate  # noqa: E402


def tracked_files_at_commit(commit: str = "HEAD") -> set[str]:
    """Get all git-tracked files at a specific commit (allowlist for code layer)."""
    try:
        output = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", commit],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.PIPE,
        )
        return set(output.strip().split("\n")) if output.strip() else set()
    except subprocess.CalledProcessError as e:
        print(f"Error reading git ls-tree for {commit}: {e.stderr}", file=sys.stderr)
        return set()


def sanitize_code_layer(code: dict, allowlist: set[str]) -> dict:
    """Filter code layer to only files in the allowlist.

    Removes any source_file not in allowlist, and drops edges whose
    source or target no longer exist.
    """
    if not code:
        return code

    out = {}

    # Filter file nodes
    if "files" in code:
        out["files"] = [
            f for f in code["files"]
            if f.get("source_file", "") in allowlist
        ]

    # Filter function nodes
    if "functions" in code:
        out["functions"] = [
            f for f in code["functions"]
            if f.get("source_file", "") in allowlist
        ]

    # Track which node IDs survive filtering
    surviving_ids = set()
    for f in out.get("files", []):
        if "id" in f:
            surviving_ids.add(f["id"])
    for f in out.get("functions", []):
        if "id" in f:
            surviving_ids.add(f["id"])

    # Filter borrowed nodes
    if "borrowed" in code:
        out["borrowed"] = [
            b for b in code["borrowed"]
            if b.get("source_file", "") in allowlist
        ]
        for b in out["borrowed"]:
            if "id" in b:
                surviving_ids.add(b["id"])

    # Filter test nodes
    if "tests" in code:
        out["tests"] = [
            t for t in code["tests"]
            if t.get("source_file", "") in allowlist
        ]
        for t in out["tests"]:
            if "id" in t:
                surviving_ids.add(t["id"])

    # Filter edges: keep only if both ends survive
    if "edges" in code:
        out["edges"] = [
            e for e in code["edges"]
            if e.get("source") in surviving_ids and e.get("target") in surviving_ids
        ]

    return out


def lock_private_projects(tree: dict) -> None:
    """Recursively lock all non-PUBLIC project nodes.

    For nodes with visibility != "PUBLIC", strip path/openable/code and set locked=true.
    Modifies tree in-place.
    """
    def walk(node: dict) -> None:
        if node.get("cat") == "projects" and node.get("visibility") != "PUBLIC":
            node["locked"] = True
            node.pop("path", None)
            node.pop("openable", None)
            node.pop("code", None)

        for child in node.get("children", []):
            walk(child)

    walk(tree)


def anonymize_machines(tree: dict) -> None:
    """Replace device hostnames with capitalized kind + count.

    For cross-machine network device nodes, set name = capitalized kind
    (deduped with " 2", " 3" etc.), and rebuild desc without tailscale_hostname.
    Keeps id unchanged so synapses still work.
    """
    # First pass: collect all device nodes and their kinds
    devices = []

    def collect_devices(node: dict) -> None:
        if node.get("cat") == "cross-machine":
            devices.append(node)
        for child in node.get("children", []):
            collect_devices(child)

    collect_devices(tree)

    # Track names we've used to dedupe
    kind_counts: dict[str, int] = {}

    for device in devices:
        kind = device.get("desc", "").split(" — ")[0] if device.get("desc") else "device"
        # Capitalize: "MacBook Pro" -> "Macbook Pro", or keep "device" as-is
        name = kind.replace("_", " ").title() if kind else "device"

        # Dedupe with count
        count = kind_counts.get(kind, 0) + 1
        kind_counts[kind] = count
        if count > 1:
            name = f"{name} {count}"

        device["name"] = name

        # Rebuild desc: "<kind> — added <date>" (no hostname)
        added_match = re.search(r"added ([^\s—]+)", device.get("desc", ""))
        added_date = added_match.group(1) if added_match else ""
        if added_date:
            device["desc"] = f"{kind} — added {added_date}"
        else:
            device["desc"] = kind


def scan_for_leaks(text: str) -> list[str]:
    """Check text for common privacy leaks: paths, IPs, emails, tokens.

    Returns list of descriptions of found leaks.
    """
    leaks = []

    # Home directory paths (e.g. /Users/gileskayo)
    if re.search(r"/Users/\w+", text):
        leaks.append("Contains /Users/ path (machine hostname)")

    # IPv4 addresses (non-loopback)
    if re.search(r"(?:(?!127\.)(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?!127)(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)", text):
        leaks.append("Contains IPv4 address")

    # Email addresses
    if re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text):
        leaks.append("Contains email address")

    # Known token patterns (based on lib/tests/test_health_checks.py)
    token_patterns = [
        (r"sk-ant-[a-zA-Z0-9]+", "Anthropic API token (sk-ant-)"),
        (r"gh[pousr]_[a-zA-Z0-9]+", "GitHub token (gh*_)"),
        (r"AKIA[0-9A-Z]{16}", "AWS access key (AKIA...)"),
        (r"xox[baprs]-[a-zA-Z0-9]+", "Slack token (xox*)"),
        (r"Bearer\s+[a-zA-Z0-9._\-]{20,}", "Bearer token (20+ chars)"),
    ]

    for pattern, description in token_patterns:
        if re.search(pattern, text):
            leaks.append(description)

    return leaks


def scan_tree_for_leaks(tree: dict, allowlist: set[str]) -> list[str]:
    """Scan tree for structural privacy issues (source files not in allowlist)
    and textual leaks in rendered fields.

    Returns list of descriptions of found issues.
    """
    issues = []

    def walk(node: dict) -> None:
        # Check code layers for files outside allowlist
        if code := node.get("code"):
            for file_node in code.get("files", []) + code.get("functions", []) + code.get("borrowed", []) + code.get("tests", []):
                if (source := file_node.get("source_file")) and source not in allowlist:
                    issues.append(f"Code layer includes untracked file: {source}")

        for child in node.get("children", []):
            walk(child)

    walk(tree)
    # Textual leaks anywhere in the tree, not just name/desc/label: on 2026-10-07 26 home paths sat in
    # scheduled-job nodes' "path" field and passed. Scanning the serialized tree covers every field.
    issues.extend(scan_for_leaks(json.dumps(tree)))
    return issues


HOME_PATH = re.compile(r"/Users/[^/\s\"']+")


def redact_home_paths(node):
    """Every string in the tree with the home folder written as ~ (the username is the private part; the rest
    is MARVIN's public repo layout)."""
    if isinstance(node, dict):
        return {k: redact_home_paths(v) for k, v in node.items()}
    if isinstance(node, list):
        return [redact_home_paths(v) for v in node]
    if isinstance(node, str):
        return HOME_PATH.sub("~", node)
    return node


LOCAL_ASSET = re.compile(r"""(?:src|href)=["']\./([^"'?#]+)["']""")


def local_assets(html: str) -> list[str]:
    """Relative files the page loads with src=/href= (vendor scripts, styles), sorted. The data file is
    fetched, not linked, and is written separately."""
    return sorted({m for m in LOCAL_ASSET.findall(html) if m != "tree-data.json"})


def copy_local_assets(html: str, src_dir: Path, out_dir: Path) -> list[str]:
    """Copy every local asset the page needs next to it; return the ones that don't exist (export must refuse)."""
    import shutil
    missing = []
    for rel in local_assets(html):
        src = src_dir / rel
        if not src.is_file() or ".." in Path(rel).parts:
            missing.append(rel)
            continue
        (out_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out_dir / rel)
    return missing


def export_snapshot(commit: str = "HEAD", out_dir: str | Path = SNAPSHOT_DIR) -> bool:
    """Generate privacy-filtered snapshot.

    Returns True on success, False if privacy scan fails (keeps previous snapshot).
    """
    out_dir = Path(out_dir)

    # Read live data
    manifest = json.loads(generate.MANIFEST_PATH.read_text(encoding="utf-8"))
    enrichment = json.loads(generate.ENRICHMENT_PATH.read_text(encoding="utf-8"))

    # Build fresh tree
    tree = generate.build_tree(manifest, enrichment)
    generate.attach_layout(tree)
    generate.attach_code_layers(tree)
    synapses = generate.all_synapses(manifest, enrichment, tree)  # every thread type, same as the local page

    # Apply privacy filters
    allowlist = tracked_files_at_commit(commit)

    # Sanitize code layers (allowlist-based)
    def apply_allowlist(node: dict) -> None:
        if code := node.get("code"):
            node["code"] = sanitize_code_layer(code, allowlist)
        for child in node.get("children", []):
            apply_allowlist(child)

    apply_allowlist(tree)

    # Lock private projects
    lock_private_projects(tree)

    # Anonymize machines
    anonymize_machines(tree)

    # Home folder → ~ in every field, then scan everything
    tree = redact_home_paths(tree)
    synapses = redact_home_paths(synapses)
    leaks = scan_tree_for_leaks(tree, allowlist)
    leaks.extend(scan_for_leaks(json.dumps(synapses)))
    if leaks:
        print("Privacy scan failed — refusing to export:", file=sys.stderr)
        for leak in leaks:
            print(f"  - {leak}", file=sys.stderr)
        return False

    # Validate known_ids for synapses (same as generate.py)
    known_ids = set()
    generate.collect_ids(tree, known_ids)
    synapses = [s for s in synapses if s["a"] in known_ids and s["b"] in known_ids]

    # Render with SNAPSHOT flag set to true
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    tree_js = "var tree = " + json.dumps(tree, indent=2, ensure_ascii=False) + ";"
    synapses_js = "var synapses = " + json.dumps(synapses, indent=2, ensure_ascii=False) + ";"

    template = re.sub(
        r"/\*__TREE_START__\*/.*?/\*__TREE_END__\*/",
        lambda _m: "/*__TREE_START__*/\n  " + tree_js + "\n  /*__TREE_END__*/",
        template,
        flags=re.DOTALL,
    )
    template = re.sub(
        r"/\*__SYNAPSES_START__\*/.*?/\*__SYNAPSES_END__\*/",
        lambda _m: "/*__SYNAPSES_START__*/\n  " + synapses_js + "\n  /*__SYNAPSES_END__*/",
        template,
        flags=re.DOTALL,
    )
    template = re.sub(
        r"/\*__SNAPSHOT_FLAG__\*/var SNAPSHOT = false;/\*__SNAPSHOT_FLAG__\*/",
        "/*__SNAPSHOT_FLAG__*/var SNAPSHOT = true;/*__SNAPSHOT_FLAG__*/",
        template,
    )

    # Write output
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(template, encoding="utf-8")
    (out_dir / "tree-data.json").write_text(
        json.dumps({"tree": tree, "synapses": synapses}, ensure_ascii=False), encoding="utf-8"
    )

    missing = copy_local_assets(template, TEMPLATE_PATH.parent, out_dir)
    if missing:
        print(f"Snapshot page needs files that don't exist: {missing} — refusing to export", file=sys.stderr)
        return False
    print(f"Generated {out_dir}/index.html (snapshot, {len(allowlist)} tracked files)")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default="HEAD", help="Git commit to export (default: HEAD)")
    parser.add_argument("--out", default=str(SNAPSHOT_DIR), help="Output directory (default: snapshot/)")
    args = parser.parse_args()

    success = export_snapshot(args.commit, args.out)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
