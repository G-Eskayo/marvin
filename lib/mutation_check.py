#!/usr/bin/env python3
"""Mutation testing in the merge gate: measure test quality by killing mutants.

One small Python module for stdlib-only mutation operators, applied in-process to each test's mapped source file.
Deterministically sampled for large PRs; time-boxed to 10 minutes total.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generated_paths as gp  # noqa: E402


def _git(cwd, *args, check=True):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check
    )


def _changed_lines(cwd: str, base: str, head: str) -> dict[str, set[int]]:
    """Return {filepath: {line_numbers}} of added/modified lines from base to head."""
    result = _git(cwd, "diff", "-U0", base, head, check=False)
    changed = {}
    current_file = None
    for line in result.stdout.split("\n"):
        if line.startswith("diff --git"):
            current_file = None
        elif line.startswith("+++ "):
            # The new side's path, unambiguously: "+++ b/<path>" (or "+++ /dev/null" for a deleted file). Reading it
            # from "diff --git a/x b/x" with the first "b/" garbled every lib/ path ("lib/" contains "b/"), which
            # meant no mutants and a perfect score for untested code (2026-10-09 review).
            current_file = line[6:].rstrip("\t") if line.startswith("+++ b/") else None  # git adds a tab after names with spaces
            if current_file and current_file.startswith('"'):
                current_file = None  # a quoted (escaped) path: skip rather than guess
            if current_file is not None and current_file not in changed:
                changed[current_file] = set()
        elif current_file and line.startswith("@@"):
            # Extract line numbers from "@@ -start,count +start,count @@"
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2) or 1)
                for i in range(count):
                    changed[current_file].add(start + i)
    return changed


def _is_test_file(path: str) -> bool:
    """Return True if path is a test file."""
    return bool(re.search(r"(^|/)(test_.*\.py|.*\.test\.js)$", path))


# ── the engine (rewritten in review, 2026-10-09: it never planted a bug and ran tests with a bare `python`) ──
#
# Python only for now: each mutant is a real change to the parsed code on a line the PR changed, written to the file,
# then the tests that belong to that file are run with MARVIN's Python. A failing (or hanging) test = caught. The file
# is restored after every mutant. JS files are reported as unmeasured, never scored, until a JS engine exists.

_CMP_SWAP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt, ast.Gt: ast.LtE, ast.LtE: ast.Gt,
             ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}
_BIN_SWAP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv}


def _mutation_sites(tree: ast.AST, lines: set[int], source_lines: list[str]) -> list[dict]:
    """Every (node, operator) pair on a changed line, in a stable order."""
    sites = []

    def keep(node) -> bool:
        ln = getattr(node, "lineno", None)
        return ln in lines and "no-mutate" not in source_lines[ln - 1] if ln and ln <= len(source_lines) else False

    for i, node in enumerate(ast.walk(tree)):
        if not keep(node):
            continue
        if isinstance(node, ast.Compare) and type(node.ops[0]) in _CMP_SWAP:
            sites.append({"node": i, "operator": "flip-comparison", "line": node.lineno})
        elif isinstance(node, ast.BoolOp):
            sites.append({"node": i, "operator": "swap-and-or", "line": node.lineno})
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            sites.append({"node": i, "operator": "drop-not", "line": node.lineno})
        elif isinstance(node, (ast.If, ast.While, ast.IfExp)):
            sites.append({"node": i, "operator": "negate-condition", "line": node.lineno})
        elif isinstance(node, ast.Return) and node.value is not None and not (isinstance(node.value, ast.Constant) and node.value.value is None):
            sites.append({"node": i, "operator": "return-none", "line": node.lineno})
        elif isinstance(node, ast.BinOp) and type(node.op) in _BIN_SWAP:
            sites.append({"node": i, "operator": "swap-arithmetic", "line": node.lineno})
        elif isinstance(node, ast.Constant) and type(node.value) in (int, float) and not isinstance(node.value, bool):
            sites.append({"node": i, "operator": "change-number", "line": node.lineno})
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            sites.append({"node": i, "operator": "flip-bool", "line": node.lineno})
    return sites


def _apply(source: str, site: dict) -> str | None:
    """The source with one mutation applied, or None if it can't be."""
    tree = ast.parse(source)
    node = next((n for i, n in enumerate(ast.walk(tree)) if i == site["node"]), None)
    if node is None:
        return None
    op = site["operator"]
    if op == "flip-comparison":
        node.ops[0] = _CMP_SWAP[type(node.ops[0])]()
    elif op == "swap-and-or":
        node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
    elif op == "drop-not":
        replacement = node.operand
        for parent in ast.walk(tree):
            for field, value in ast.iter_fields(parent):
                if value is node:
                    setattr(parent, field, replacement)
                elif isinstance(value, list):
                    for k, item in enumerate(value):
                        if item is node:
                            value[k] = replacement
    elif op == "negate-condition":
        node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)
    elif op == "return-none":
        node.value = ast.Constant(value=None)
    elif op == "swap-arithmetic":
        node.op = _BIN_SWAP[type(node.op)]()
    elif op == "change-number":
        node.value = node.value + 1
    elif op == "flip-bool":
        node.value = not node.value
    try:
        return ast.unparse(ast.fix_missing_locations(tree))
    except Exception:  # noqa: BLE001
        return None


def _tests_for(source_path: str, cwd: str, changed_tests: list[str]) -> list[str]:
    """The tests that belong to a source file: test_<name>.py anywhere in the repo, plus the PR's own changed tests."""
    stem = Path(source_path).stem
    found = sorted(str(p.relative_to(cwd)) for p in Path(cwd).rglob(f"test_{stem}.py")
                   if ".git" not in p.parts and "node_modules" not in p.parts)
    return list(dict.fromkeys(found + [t for t in changed_tests if t.endswith(".py")]))


def _run_tests(cwd: str, tests: list[str], timeout: int) -> str:
    """'pass' | 'fail' | 'timeout' — with MARVIN's own Python (the one running this), never a bare `python`."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "MARVIN_MERGE_GATE": "1"}
    try:
        p = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *tests],
                           cwd=cwd, capture_output=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return "timeout"
    return "pass" if p.returncode == 0 else "fail"


def _sample(items: list, limit: int, salt: str) -> list:
    """A deterministic sample: the same PR always gets the same mutants."""
    if len(items) <= limit:
        return items
    keyed = sorted(items, key=lambda m: zlib.crc32(f"{salt}|{m['file']}|{m['line']}|{m['operator']}|{m['node']}".encode()))
    return sorted(keyed[:limit], key=lambda m: (m["file"], m["line"], m["node"]))


def run_mutation_check(
    cwd: str,
    head_ref: str,
    base_ref: str = "main",
    base_sha: str | None = None,
    max_mutants_per_pr: int = 60,
    max_mutants_per_file: int = 8,
    per_mutant_timeout_sec: int = 60,
    wall_clock_budget_sec: int = 600,
    repo: str = "G-Eskayo/marvin"
) -> dict:
    """Plant bugs in the PR's changed Python lines (cwd is a checkout of the PR head) and count how many its tests catch.

    {"status": "ok" | "unknown", "score": 0.0-1.0 | None, "mutants_total", "killed", "survived": [...],
     "unmeasured": [...], "reason"}. "unknown" (score None) whenever nothing could be scored: never a made-up number.
    """
    start = time.time()
    cwd = str(cwd)
    if not base_sha:
        r = _git(cwd, "merge-base", base_ref, "HEAD", check=False)
        if r.returncode != 0:
            return {"status": "unknown", "score": None, "mutants_total": 0, "killed": 0, "survived": [],
                    "unmeasured": [], "reason": "could not find merge base"}
        base_sha = r.stdout.strip()
    changed = _changed_lines(cwd, base_sha, "HEAD")
    rules = gp.rules_for(repo)
    changed_tests = [p for p in changed if _is_test_file(p)]
    code = {p: l for p, l in changed.items() if l and not _is_test_file(p) and not gp.is_generated(p, rules)
            and p.endswith((".py", ".js", ".jsx", ".mjs", ".ts", ".tsx"))}

    unmeasured, candidates = [], []
    for path in sorted(code):
        if not path.endswith(".py"):
            unmeasured.append({"file": path, "line": min(code[path]), "operator": "-", "snippet": "JS isn't mutation-tested yet"})
            continue
        try:
            source = (Path(cwd) / path).read_text()
            sites = _mutation_sites(ast.parse(source), code[path], source.splitlines())
        except (OSError, SyntaxError, ValueError):
            unmeasured.append({"file": path, "line": min(code[path]), "operator": "-", "snippet": "couldn't parse the file"})
            continue
        for site in _sample([{**s, "file": path} for s in sites], max_mutants_per_file, head_ref):
            candidates.append(site)
    candidates = _sample(candidates, max_mutants_per_pr, head_ref)
    if not candidates and not unmeasured:
        return {"status": "ok", "score": 1.0, "mutants_total": 0, "killed": 0, "survived": [], "unmeasured": [],
                "reason": None}

    killed, killed_lines, survived = 0, [], []
    baseline: dict[str, bool] = {}
    for m in candidates:
        tests = _tests_for(m["file"], cwd, changed_tests)
        entry = {"file": m["file"], "line": m["line"], "operator": m["operator"], "snippet": ""}
        if not tests:
            unmeasured.append({**entry, "snippet": "no test file for it"})
            continue
        key = "|".join(tests)
        if key not in baseline:
            baseline[key] = _run_tests(cwd, tests, per_mutant_timeout_sec * 2) == "pass"
        if not baseline[key]:
            unmeasured.append({**entry, "snippet": "its tests already fail without any planted bug"})
            continue
        if time.time() - start > wall_clock_budget_sec:
            unmeasured.append({**entry, "snippet": "out of time"})
            continue
        path = Path(cwd) / m["file"]
        original = path.read_text()
        mutated = _apply(original, m)
        if mutated is None or mutated == original:
            unmeasured.append({**entry, "snippet": "couldn't apply"})
            continue
        try:
            # the ORIGINAL line (the mutated source is re-formatted, so its line numbers don't match)
            src_lines = original.splitlines()
            entry["snippet"] = src_lines[m["line"] - 1].strip()[:120] if m["line"] <= len(src_lines) else ""
            path.write_text(mutated)
            outcome = _run_tests(cwd, tests, per_mutant_timeout_sec)
        finally:
            path.write_text(original)
        if outcome in ("fail", "timeout"):
            killed += 1
            killed_lines.append(m["line"])
        else:
            survived.append(entry)
    scored = killed + len(survived)
    if scored == 0:
        return {"status": "unknown", "score": None, "mutants_total": len(candidates), "killed": 0, "survived": [],
                "unmeasured": unmeasured, "killed_lines": [], "reason": "nothing could be scored (see unmeasured)"}
    return {"status": "ok", "score": killed / scored, "mutants_total": len(candidates), "killed": killed,
            "survived": survived, "unmeasured": unmeasured, "killed_lines": killed_lines, "reason": None}


def render_section(result: dict) -> str:
    """The PR-body section, in the one format every reader parses: the MR Review card ("NN% (k/n)") and auto-merge's
    shadow mode ("**Score:** NN%"). A score is only ever written when one was measured."""
    head = "## Mutation Score\n\n"
    if result.get("status") != "ok" or result.get("score") is None:
        why = result.get("reason") or "nothing could be scored"
        lines = [f"Score: unknown ({why}). Auto-merge waits for a measured score."]
        for u in (result.get("unmeasured") or [])[:5]:
            lines.append(f"- not measured: `{u.get('file')}` line {u.get('line')}: {u.get('snippet', '')}")
        return head + "\n".join(lines) + "\n"
    if not result.get("mutants_total"):
        return head + "**Score:** 100% (0/0): no mutable lines (docs, config or tests only).\n"
    killed, total = result["killed"], result["killed"] + len(result.get("survived") or [])
    pct = round(result["score"] * 100)
    md = head + f"**Score:** {pct}% ({killed}/{total}) of planted bugs caught by this PR's tests.\n"
    if result.get("survived"):
        md += "\n### Planted bugs the tests missed\n\n"
        for s in result["survived"][:10]:
            md += f"- `{s['file']}` line {s['line']} ({s['operator']}): `{s.get('snippet', '')}`\n"
    if result.get("unmeasured"):
        md += f"\n{len(result['unmeasured'])} change(s) couldn't be measured.\n"
    return md


def merge_bodies(current_body: str, new_section: str) -> str:
    """Merge a mutation section into a PR body, replacing if it exists."""
    start_marker = "<!-- marvin:mutation-check -->"
    end_marker = "<!-- /marvin:mutation-check -->"

    if start_marker in current_body and end_marker in current_body:
        # Replace existing section
        before = current_body.split(start_marker)[0]
        after = current_body.split(end_marker)[1] if end_marker in current_body else ""
        return f"{before}{start_marker}\n{new_section}\n{end_marker}{after}"
    else:
        # Append new section
        return f"{current_body.rstrip()}\n\n{start_marker}\n{new_section}\n{end_marker}\n"


def main():
    if len(sys.argv) < 5 or sys.argv[1] != "run":
        sys.exit("usage: mutation_check.py run <repo> <scratch_dir> <base_sha> [head_ref]")

    repo = sys.argv[2]
    scratch_dir = sys.argv[3]
    base_sha = sys.argv[4]
    head_ref = sys.argv[5] if len(sys.argv) > 5 else "HEAD"

    result = run_mutation_check(scratch_dir, head_ref, base_sha=base_sha, repo=repo)
    print(json.dumps(result))
    sys.exit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
