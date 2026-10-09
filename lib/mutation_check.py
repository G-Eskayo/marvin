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
            # Extract filename from "diff --git a/file b/file"
            m = re.search(r"b/(.+)$", line)
            if m:
                current_file = m.group(1)
                if current_file not in changed:
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


def _get_python_mutants(source_path: str, changed_lines: set[int]) -> list[dict]:
    """Generate mutation operators for a Python file on changed lines."""
    try:
        source = Path(source_path).read_text()
    except Exception:
        return []

    mutants = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines = source.split("\n")

    # Operators: flip comparison, flip boolean, negate if/while, drop call, flip return, nudge constant
    for node in ast.walk(tree):
        line_no = getattr(node, "lineno", None)
        if not line_no or line_no not in changed_lines:
            continue

        # Skip pragmas
        if line_no <= len(lines) and "no-mutate" in lines[line_no - 1]:
            continue

        if isinstance(node, ast.Compare):
            # Flip comparison operators
            for i, op in enumerate(node.ops):
                old_op = type(op).__name__
                if old_op == "Lt":
                    mutants.append({"file": source_path, "line": line_no, "operator": "Lt->Gt", "snippet": ast.unparse(node)[:50]})
                elif old_op == "Gt":
                    mutants.append({"file": source_path, "line": line_no, "operator": "Gt->Lt", "snippet": ast.unparse(node)[:50]})
                elif old_op == "Eq":
                    mutants.append({"file": source_path, "line": line_no, "operator": "Eq->NotEq", "snippet": ast.unparse(node)[:50]})
                elif old_op == "NotEq":
                    mutants.append({"file": source_path, "line": line_no, "operator": "NotEq->Eq", "snippet": ast.unparse(node)[:50]})
        elif isinstance(node, ast.BoolOp):
            # Flip and/or
            old_op = type(node.op).__name__
            if old_op == "And":
                mutants.append({"file": source_path, "line": line_no, "operator": "And->Or", "snippet": ast.unparse(node)[:50]})
            elif old_op == "Or":
                mutants.append({"file": source_path, "line": line_no, "operator": "Or->And", "snippet": ast.unparse(node)[:50]})
        elif isinstance(node, (ast.If, ast.While)):
            # Negate condition
            mutants.append({"file": source_path, "line": line_no, "operator": "negate-condition", "snippet": "negate condition"})
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            # Nudge numeric constant
            if node.value != 0:
                mutants.append({"file": source_path, "line": line_no, "operator": "constant+1", "snippet": str(node.value)})

    return mutants[:8]  # Cap per file


def _get_js_mutants(source_path: str, changed_lines: set[int]) -> list[dict]:
    """Generate mutation operators for a JavaScript file on changed lines."""
    try:
        source = Path(source_path).read_text()
        lines = source.split("\n")
    except Exception:
        return []

    mutants = []
    for line_no in changed_lines:
        if line_no > len(lines):
            continue
        line = lines[line_no - 1]

        # Skip pragmas
        if "no-mutate" in line:
            continue

        # Flip comparison operators
        for op_from, op_to in [("===", "!=="), ("!==", "==="), ("==", "!="), ("!=", "=="),
                               ("<", ">"), (">", "<"), ("<=", ">="), (">=", "<=")]:
            if op_from in line:
                mutants.append({
                    "file": source_path,
                    "line": line_no,
                    "operator": f"{op_from}->{op_to}",
                    "snippet": line[:50]
                })

        # Flip boolean operators
        for op_from, op_to in [("&&", "||"), ("||", "&&")]:
            if op_from in line:
                mutants.append({
                    "file": source_path,
                    "line": line_no,
                    "operator": f"{op_from}->{op_to}",
                    "snippet": line[:50]
                })

        # Return statement mutations
        if re.search(r"\breturn\s+\S", line):
            mutants.append({
                "file": source_path,
                "line": line_no,
                "operator": "return->null",
                "snippet": line[:50]
            })

        # Bare call statement (drop it)
        if re.match(r"^\s*\w+\(.*\)\s*;?\s*$", line):
            mutants.append({
                "file": source_path,
                "line": line_no,
                "operator": "drop-call",
                "snippet": line[:50]
            })

    return mutants[:8]  # Cap per file


def run_mutation_check(
    cwd: str,
    head_ref: str,
    base_ref: str = "main",
    base_sha: str | None = None,
    max_mutants_per_pr: int = 60,
    max_mutants_per_file: int = 8,
    per_mutant_timeout_sec: int = 20,
    wall_clock_budget_sec: int = 600,
    repo: str = "G-Eskayo/marvin"
) -> dict:
    """Run mutation check on a PR.

    Returns:
    {
        "status": "ok" | "unknown",
        "score": 0.0-1.0 (only if status=="ok"),
        "mutants_total": int,
        "killed": int,
        "survived": [{"file": str, "line": int, "operator": str, "snippet": str}],
        "unmeasured": [...],
        "reason": str (if status=="unknown")
    }
    """
    start_time = time.time()

    if not base_sha:
        result = _git(cwd, "merge-base", base_ref, head_ref, check=False)
        if result.returncode != 0:
            return {
                "status": "unknown",
                "mutants_total": 0,
                "score": None,
                "killed": 0,
                "survived": [],
                "unmeasured": [],
                "reason": "could not find merge base"
            }
        base_sha = result.stdout.strip()

    # Get changed files and lines
    changed = _changed_lines(cwd, base_sha, f"origin/{head_ref}")

    # Filter to mutable files only (not test files, not generated)
    generated_rules = gp.rules_for(repo)
    mutable_files = {
        path: lines for path, lines in changed.items()
        if not _is_test_file(path)
        and not gp.is_generated(path, generated_rules)
        and (path.endswith(".py") or path.endswith(".js"))
    }

    if not mutable_files:
        return {
            "status": "ok",
            "score": 1.0,
            "mutants_total": 0,
            "killed": 0,
            "survived": [],
            "unmeasured": [],
            "reason": None
        }

    # Collect all potential mutants
    all_mutants = []
    for filepath, lines in mutable_files.items():
        if filepath.endswith(".py"):
            all_mutants.extend(_get_python_mutants(str(Path(cwd) / filepath), lines))
        elif filepath.endswith(".js"):
            all_mutants.extend(_get_js_mutants(str(Path(cwd) / filepath), lines))

    if not all_mutants:
        return {
            "status": "ok",
            "score": 1.0,
            "mutants_total": 0,
            "killed": 0,
            "survived": [],
            "unmeasured": [],
            "reason": None
        }

    # Cap mutants deterministically (stable hash so sampling is consistent across retries)
    if len(all_mutants) > max_mutants_per_pr:
        seed = zlib.crc32(head_ref.encode()) % 2**31
        import random
        rng = random.Random(seed)
        all_mutants = rng.sample(all_mutants, min(max_mutants_per_pr, len(all_mutants)))

    # Map each mutant to its test file and check baseline
    unmeasured = []
    killable_mutants = []

    for mutant in all_mutants:
        test_file = None
        source_path = mutant["file"]

        # Try to find the test file
        if source_path.endswith(".py"):
            m = re.match(r"^(.*/)([^/]+)\.py$", source_path)
            if m:
                test_file = f"{m.group(1)}tests/test_{m.group(2)}.py"
                if not Path(cwd, test_file).exists():
                    test_file = None
        elif source_path.endswith(".js"):
            # Try test/ dir or co-located
            base_name = source_path.rsplit("/", 1)[-1].replace(".js", "")
            test_candidates = [
                f"{'/'.join(source_path.rsplit('/', 1)[:-1])}/test/{base_name}.test.js",
                f"{source_path.rsplit('.', 1)[0]}.test.js"
            ]
            for candidate in test_candidates:
                if Path(cwd, candidate).exists():
                    test_file = candidate
                    break

        if not test_file:
            unmeasured.append(mutant)
        else:
            killable_mutants.append((mutant, test_file))

    # Check baseline: which test files are already red on the PR's merge base?
    baseline_red_tests = set()
    for mutant, test_file in killable_mutants:
        if test_file in baseline_red_tests:
            continue

        # Run test on clean merge-base
        worktree_dir = None
        try:
            worktree_dir = tempfile.mkdtemp(prefix="mutation-baseline-")
            _git(cwd, "worktree", "add", "--detach", worktree_dir, base_sha, check=False)

            try:
                if test_file.endswith(".py"):
                    result = subprocess.run(
                        ["python", "-m", "pytest", "-xvs", test_file],
                        cwd=worktree_dir,
                        capture_output=True,
                        timeout=per_mutant_timeout_sec
                    )
                else:
                    result = subprocess.run(
                        ["npx", "vitest", "run", test_file],
                        cwd=worktree_dir,
                        capture_output=True,
                        timeout=per_mutant_timeout_sec
                    )

                if result.returncode != 0:
                    baseline_red_tests.add(test_file)
            except subprocess.TimeoutExpired:
                # Timeout on baseline counts as the test being red
                baseline_red_tests.add(test_file)
            except (FileNotFoundError, OSError):
                # Missing tool (python, npx, etc) means we can't test; don't exclude
                pass
        finally:
            if worktree_dir:
                _git(cwd, "worktree", "remove", "--force", worktree_dir, check=False)
                import shutil
                shutil.rmtree(worktree_dir, ignore_errors=True)

    # Run mutants, skipping ones with red baseline tests
    killed = 0
    survived = []

    for mutant, test_file in killable_mutants:
        if test_file in baseline_red_tests:
            unmeasured.append(mutant)
            continue

        if time.time() - start_time > wall_clock_budget_sec:
            break

        # Apply mutant and run test
        worktree_dir = None
        try:
            worktree_dir = tempfile.mkdtemp(prefix="mutation-")
            _git(cwd, "worktree", "add", "--detach", worktree_dir, f"origin/{head_ref}", check=False)

            # Apply mutation by modifying the file
            source_file = Path(worktree_dir) / mutant["file"]
            if not source_file.exists():
                unmeasured.append(mutant)
                continue

            try:
                original = source_file.read_text()
                lines = original.split("\n")
                mutant_line_no = mutant["line"]

                if mutant_line_no > len(lines):
                    unmeasured.append(mutant)
                    continue

                # Textual mutation: find and replace the snippet on the target line
                line_text = lines[mutant_line_no - 1]
                operator = mutant["operator"]
                mutated_line = line_text

                # Apply the specific mutation based on operator type
                if "->" in operator:
                    old_op, new_op = operator.split("->")
                    if old_op in line_text and new_op not in line_text:
                        mutated_line = line_text.replace(old_op, new_op, 1)
                elif operator == "constant+1":
                    # Try to find the constant in the snippet and increment it
                    try:
                        const_val = float(mutant["snippet"])
                        const_str = str(int(const_val) if const_val == int(const_val) else const_val)
                        if const_str in line_text:
                            new_val = str(int(const_val) + 1)
                            mutated_line = line_text.replace(const_str, new_val, 1)
                    except (ValueError, TypeError):
                        unmeasured.append(mutant)
                        continue
                elif operator == "negate-condition":
                    # Wrap condition in `not (...)`
                    if "if " in line_text or "while " in line_text:
                        # Simple heuristic: find the condition part and negate it
                        mutated_line = re.sub(r'(if|while)\s+', r'\1 not ', line_text, count=1)

                # If mutation didn't change anything, skip
                if mutated_line == line_text:
                    unmeasured.append(mutant)
                    continue

                # Write mutated file
                lines[mutant_line_no - 1] = mutated_line
                source_file.write_text("\n".join(lines))

                # Run the test twice to catch flaky tests
                for attempt in range(2):
                    try:
                        if test_file.endswith(".py"):
                            result = subprocess.run(
                                ["python", "-m", "pytest", "-xvs", test_file],
                                cwd=worktree_dir,
                                capture_output=True,
                                timeout=per_mutant_timeout_sec
                            )
                        else:
                            result = subprocess.run(
                                ["npx", "vitest", "run", test_file],
                                cwd=worktree_dir,
                                capture_output=True,
                                timeout=per_mutant_timeout_sec
                            )

                        if result.returncode != 0:
                            killed += 1
                            break  # Mutant killed
                        elif attempt == 0:
                            # Test passed on first run; retry to check for flakiness
                            continue
                        else:
                            # Test passed on both runs; mutant survived
                            survived.append(mutant)
                    except subprocess.TimeoutExpired:
                        # Timeout counts as killed
                        killed += 1
                        break
            except (FileNotFoundError, OSError):
                # Can't apply mutation (file missing tool, etc.)
                unmeasured.append(mutant)
            except Exception:
                unmeasured.append(mutant)
        finally:
            if worktree_dir:
                _git(cwd, "worktree", "remove", "--force", worktree_dir, check=False)
                import shutil
                shutil.rmtree(worktree_dir, ignore_errors=True)

    total_scored = len(killable_mutants) - len([m for _, t in killable_mutants if t in baseline_red_tests])

    # Determine status and score
    if not all_mutants:
        # No mutable lines (all docs/config/tests)
        status = "ok"
        score = 1.0
    elif total_scored == 0:
        # Mutable lines exist but nothing could be scored (all baseline-red or no mapped tests)
        status = "unknown"
        score = None
    else:
        # Scored at least one mutant
        status = "ok"
        score = killed / total_scored if total_scored > 0 else None

    return {
        "status": status,
        "score": score,
        "mutants_total": len(all_mutants),
        "killed": killed,
        "survived": survived,
        "unmeasured": unmeasured,
        "reason": None if status == "ok" else "could not score any mutants"
    }


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
