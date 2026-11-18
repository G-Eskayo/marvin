#!/usr/bin/env python3
"""
facts.py — the MARVIN page's numbers, computed from the system so they can't go stale
(docs/plans/living-marvin-page-2026-10-08.md, layer 1; published with the map under ADR 0057's extension).

  skills           entries in the skill index (~/.claude/manifest.json) whose file is a SKILL.md, not the memories it also holds
  tests            tests_passed in the newest pipeline run (bench/metrics/ticket-*.json): what runs on every change
  tests_python     pytest --collect-only -q on the whole repo (rest API, all-or-nothing on any repo failure)
  tests_js         vitest list in dashboard/
  tests_site       node --test --test-reporter=tap over site/scripts/*.test.mjs, parsed from TAP summary
  prs_merged       merged pull requests with head.ref starting with "pipeline/", from REST pagination over board repos
  agents           background jobs MARVIN schedules (lib/health_checks.py JOB_PLACEMENT)
  decisions        architecture decision records (docs/adr/NNNN-*.md files)
  machines         registered machines (~/.claude/marvin-network.json)
  counted_on       the day these were counted
  <key>_counted_on date each metric was last updated (preserves previous value when source fails)

A source that can't be read is left out, never written as 0: the page then keeps the number it was written with
(via _resolve() fallback to previous snapshot). compute_facts() is pure; gather() does the reading.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "lib"))
import instance  # noqa: E402


def _resolve(key: str, fresh: int | None, previous: dict | None, today: str) -> dict:
    """Fallback logic: use fresh if present, else keep previous value.

    Returns a dict with key and key_counted_on (or empty dict if both fresh and previous are missing).
    """
    out = {}
    if fresh is not None:
        out[key] = fresh
        d = date.fromisoformat(today)
        out[f"{key}_counted_on"] = f"{d.day} {d.strftime('%B')} {d.year}"
    elif previous and key in previous:
        out[key] = previous[key]
        if f"{key}_counted_on" in previous:
            out[f"{key}_counted_on"] = previous[f"{key}_counted_on"]
    return out


def _previous() -> dict:
    """Read the previous snapshot facts (for fallback when sources fail).

    Tolerates missing or corrupt file, returns empty dict on any error.
    """
    try:
        path = instance.path("brain-map", "snapshot") / "facts.json"
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _py_tests_collected() -> int | None:
    """Collect test count from pytest --collect-only -q on the whole repo."""
    try:
        env = dict(os.environ)
        env.pop("MARVIN_SELECTED_TESTS", None)
        p = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                          cwd=REPO, capture_output=True, text=True, timeout=60, env=env)
        # pytest --collect-only -q outputs lines like "<number> test collected" or similar
        # Parse regardless of exit code (exit code 2 means collection error but count is still printed)
        lines = p.stdout.strip().split("\n")
        for line in lines:
            match = re.search(r"(\d+)\s+test", line)
            if match:
                return int(match.group(1))
        return None
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        return None


def _js_tests_listed() -> int | None:
    """Count JavaScript tests via npx vitest list in dashboard/."""
    try:
        dashboard = REPO / "dashboard"
        if not dashboard.is_dir():
            return None
        p = subprocess.run(["npx", "vitest", "list"],
                          cwd=dashboard, capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            return None
        # Count the number of tests in vitest list output
        return len([line for line in p.stdout.strip().split("\n") if line.strip()])
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        return None


def _site_tests_run() -> int | None:
    """Count Node.js tests in site/scripts/*.test.mjs via node --test."""
    try:
        site_dir = REPO / "site" / "scripts"
        if not site_dir.is_dir():
            return None
        test_files = list(site_dir.glob("*.test.mjs"))
        if not test_files:
            return None
        total = 0
        for test_file in test_files:
            p = subprocess.run(["node", "--test", "--test-reporter=tap", str(test_file)],
                             capture_output=True, text=True, timeout=60)
            # Parse TAP output for "# tests N" summary line
            for line in p.stdout.split("\n"):
                match = re.search(r"# tests\s+(\d+)", line)
                if match:
                    total += int(match.group(1))
        return total if total > 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        return None


def _repo_pipeline_prs(repo: str) -> int | None:
    """REST paginated query for merged pipeline PRs in one repo.

    Counts merged PRs with head.ref starting with "pipeline/" via REST pagination on repos/{repo}/pulls.
    Returns count on success, None on failure.
    """
    try:
        p = subprocess.run(
            ["gh", "api", "--paginate", f"repos/{repo}/pulls",
             "-f", "state=closed", "-f", "per_page=100", "-q", ".[] | select(.merged_at != null and .head.ref | startswith(\"pipeline/\")) | .number"],
            capture_output=True, text=True, timeout=30)
        if p.returncode != 0:
            return None
        # Count the number of PR numbers returned
        lines = [line.strip() for line in p.stdout.strip().split("\n") if line.strip()]
        return len(lines) if lines else 0
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _merged_pipeline_prs(repos: list[str]) -> int | None:
    """Sum pipeline PR counts across multiple repos via REST.

    Returns None if any repo query fails (all-or-nothing semantic).
    """
    if not repos:
        return None
    total = 0
    for repo in repos:
        count = _repo_pipeline_prs(repo)
        if count is None:
            return None
        total += count
    return total


def compute_facts(*, manifest: dict, test_runs: list[list[dict]], merged_prs: int | None, placement: dict,
                  adr_names: list[str], network: dict, today: str, previous: dict | None = None,
                  tests_python: int | None = None, tests_js: int | None = None, tests_site: int | None = None) -> dict:
    out: dict = {}
    # The index also holds memories; a skill is an entry whose file is a SKILL.md (type tags vary: agent, library...).
    skills = [e for e in manifest.get("index") or [] if isinstance(e, dict) and str(e.get("path", "")).endswith("/SKILL.md")]
    if skills:
        out["skills"] = len(skills)
    entries = [e for run in test_runs for e in run if isinstance(e, dict) and "tests_passed" in e.get("metrics", {})]
    if entries:
        newest = max(entries, key=lambda e: e.get("timestamp", ""))
        fresh_tests = int(newest["metrics"]["tests_passed"]["value"])
    else:
        fresh_tests = None
    out.update(_resolve("tests", fresh_tests, previous, today))
    out.update(_resolve("tests_python", tests_python, previous, today))
    out.update(_resolve("tests_js", tests_js, previous, today))
    out.update(_resolve("tests_site", tests_site, previous, today))
    out.update(_resolve("prs_merged", merged_prs, previous, today))
    if placement:
        out["agents"] = len(placement)
    adrs = [n for n in adr_names if re.match(r"^\d{4}-.+\.md$", n)]
    if adrs:
        out["decisions"] = len(adrs)
    if network.get("devices"):
        out["machines"] = len(network["devices"])
    d = date.fromisoformat(today)
    out["counted_on"] = f"{d.day} {d.strftime('%B')} {d.year}"
    return out


def formatted(facts: dict) -> dict:
    """What the page shows: numbers with thousands separators, text as is."""
    return {k: (f"{v:,}" if isinstance(v, int) else v) for k, v in facts.items()}


def gather(today: str | None = None) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import connections  # reads JOB_PLACEMENT without importing the health stack
    import ticket_agents  # for board_repos()

    def load(p: Path, default):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    runs = [load(f, []) for f in sorted(instance.path("bench", "metrics").glob("ticket-*.json"))]

    # Get board repos; if board registry is corrupt, blank the PR figure
    try:
        board_repos_list = ticket_agents.board_repos()
    except Exception:
        board_repos_list = []

    merged_prs = _merged_pipeline_prs(board_repos_list) if board_repos_list else None

    return compute_facts(
        manifest=load(Path.home() / ".claude" / "manifest.json", {}),
        test_runs=[r for r in runs if isinstance(r, list)],
        merged_prs=merged_prs,
        placement=connections.read_job_placement(REPO / "lib" / "health_checks.py"),
        adr_names=[p.name for p in (REPO / "docs" / "adr").glob("*.md")],
        network=load(Path.home() / ".claude" / "marvin-network.json", {}),
        today=today or date.today().isoformat(),
        previous=_previous(),
        tests_python=_py_tests_collected(),
        tests_js=_js_tests_listed(),
        tests_site=_site_tests_run())


if __name__ == "__main__":
    print(json.dumps(formatted(gather()), indent=2))
