#!/usr/bin/env python3
"""
facts.py — the MARVIN page's numbers, computed from the system so they can't go stale
(docs/plans/living-marvin-page-2026-10-08.md, layer 1; published with the map under ADR 0057's extension).

  skills           entries in the skill index (~/.claude/manifest.json) whose file is a SKILL.md, not the memories it also holds
  tests            sum of tests_pytest + tests_vitest + tests_site (each part's count on its last run; a part left out if its run failed)
  tests_pytest     collected from `pytest --collect-only` in the repo root
  tests_vitest     counted from `npx vitest list` in dashboard/
  tests_site       counted from site/scripts/*.test.mjs files run with `node --test`
  prs_merged       merged pull requests the pipeline wrote ("Implement G-Eskayo/<repo>#N"), from GitHub search
  agents           background jobs MARVIN schedules (lib/health_checks.py JOB_PLACEMENT)
  decisions        architecture decision records (docs/adr/NNNN-*.md files)
  machines         registered machines (~/.claude/marvin-network.json)
  counted_on       the day these were counted
  <field>_counted_on   date that field's count was last updated (per-field timestamps for carry-forward)

A source that can't be read is left out, never written as 0: the page then keeps the number it was written with.
compute_facts() is pure; gather() does the reading; merge_with_previous() carries per-field counts forward when fresh sources fail.
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


def compute_facts(*, manifest: dict, pytest_collected: int | None, vitest_count: int | None, site_count: int | None,
                  merged_prs: int | None, placement: dict, adr_names: list[str], network: dict, today: str) -> dict:
    out: dict = {}
    # The index also holds memories; a skill is an entry whose file is a SKILL.md (type tags vary: agent, library...).
    skills = [e for e in manifest.get("index") or [] if isinstance(e, dict) and str(e.get("path", "")).endswith("/SKILL.md")]
    if skills:
        out["skills"] = len(skills)
    # Assemble tests from whichever parts succeed.
    parts = [v for v in (pytest_collected, vitest_count, site_count) if v is not None]
    if parts:
        out["tests"] = sum(parts)
        if pytest_collected is not None:
            out["tests_pytest"] = pytest_collected
        if vitest_count is not None:
            out["tests_vitest"] = vitest_count
        if site_count is not None:
            out["tests_site"] = site_count
    if merged_prs is not None:
        out["prs_merged"] = int(merged_prs)
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


def _gh_json(path: str, fetch=None) -> dict | None:
    """Paginated GitHub API call. fetch(path) can be overridden for testing."""
    if fetch is not None:
        return fetch(path)
    try:
        p = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=30)
        return json.loads(p.stdout) if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError):
        return None


def _merged_pipeline_prs(repos: list[dict], fetch=None) -> int | None:
    """Sum of merged pipeline PRs per repo. repos is a list of {repo: "owner/name"} dicts from board_registry.
    Returns None if any repo fails to fetch or repos is empty."""
    if not repos:
        return None
    total = 0
    for board in repos:
        repo = board.get("repo", "")
        try:
            page = 1
            while True:
                data = _gh_json(f"repos/{repo}/pulls?state=closed&per_page=100&page={page}", fetch)
                if data is None:
                    return None
                # Handle both array and {items: array} responses
                items = data if isinstance(data, list) else data.get("items", []) if isinstance(data, dict) else []
                if not items:
                    break
                count = sum(1 for pr in items
                           if isinstance(pr, dict) and "Implement G-Eskayo/" in pr.get("title", ""))
                total += count
                # If we got fewer than 100 items, we've reached the last page
                if len(items) < 100:
                    break
                page += 1
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None
    return total


def _pytest_collected(repo_root: Path, run=None) -> int | None:
    """Collected test count from pytest --collect-only. Returns None on failure."""
    run = run or subprocess.run
    try:
        env = os.environ.copy()
        env.pop("MARVIN_SELECTED_TESTS", None)
        p = run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
                cwd=repo_root, capture_output=True, text=True, timeout=60, env=env)
        if p.returncode != 0:
            return None
        # Parse "N tests? collected" and optional ", M errors?"
        m = re.search(r"(\d+)\s+test\w*\s+collected", p.stdout)
        if m:
            return int(m.group(1))
        return None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _vitest_count(repo_root: Path, run=None) -> int | None:
    """Test count from vitest list in dashboard/. Returns None on failure."""
    run = run or subprocess.run
    dashboard = repo_root / "dashboard"
    if not dashboard.is_dir():
        return None
    try:
        p = run(["npx", "--no-install", "vitest", "list"], cwd=dashboard,
                capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            return None
        # Count non-empty lines in output
        lines = [l for l in p.stdout.splitlines() if l.strip()]
        return len(lines) if lines else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _site_test_count(repo_root: Path, run=None) -> int | None:
    """Test count from site/scripts/*.test.mjs. Returns None if no files or no match."""
    run = run or subprocess.run
    site_scripts = repo_root / "site" / "scripts"
    if not site_scripts.is_dir():
        return None
    test_files = list(site_scripts.glob("*.test.mjs"))
    if not test_files:
        return None
    try:
        p = run(["node", "--test", "--test-reporter=tap"] + [str(f) for f in test_files],
                cwd=repo_root / "site", capture_output=True, text=True, timeout=60)
        # Parse "# tests N" from either stdout or stderr
        m = re.search(r"#\s+tests\s+(\d+)", p.stdout + p.stderr)
        if m:
            return int(m.group(1))
        return None
    except (OSError, subprocess.TimeoutExpired):
        return None


def merge_with_previous(fresh: dict, previous: dict) -> dict:
    """Carry forward per-field counts when fresh sources fail.
    Fields to merge: prs_merged, tests_pytest, tests_vitest, tests_site.
    For each field, keep fresh if present, else keep previous + its _counted_on date.
    Legacy bootstrap: if all three test parts are missing (None or not present), carry forward the old flat "tests"."""
    out = {**fresh}
    today_str = fresh.get("counted_on", "")
    for field in ("prs_merged", "tests_pytest", "tests_vitest", "tests_site"):
        if field not in out and field in previous:
            out[field] = previous[field]
            # Preserve the old _counted_on for carry-forward fields
            if f"{field}_counted_on" in previous:
                out[f"{field}_counted_on"] = previous[f"{field}_counted_on"]
            else:
                # Bootstrap from the old "counted_on" if the per-field date is missing
                out[f"{field}_counted_on"] = previous.get("counted_on", today_str)
    # Recalculate tests from parts if any part came from carry-forward
    parts = [out.get(f) for f in ("tests_pytest", "tests_vitest", "tests_site")]
    parts = [v for v in parts if v is not None]
    if parts and "tests" not in fresh:
        out["tests"] = sum(parts)
    elif not parts and "tests" not in out and "tests" in previous:
        # Legacy bootstrap: if all three parts are missing and there's no fresh tests,
        # carry forward the old flat "tests" value from previous (migration from old schema)
        out["tests"] = previous["tests"]
    return out


def gather(today: str | None = None) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import connections  # reads JOB_PLACEMENT without importing the health stack
    sys.path.insert(0, str(REPO / "lib"))
    import board_registry

    def load(p: Path, default):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    # Get repos from board_registry
    repos = board_registry.list_boards()
    return compute_facts(
        manifest=load(Path.home() / ".claude" / "manifest.json", {}),
        pytest_collected=_pytest_collected(REPO),
        vitest_count=_vitest_count(REPO),
        site_count=_site_test_count(REPO),
        merged_prs=_merged_pipeline_prs(repos),
        placement=connections.read_job_placement(REPO / "lib" / "health_checks.py"),
        adr_names=[p.name for p in (REPO / "docs" / "adr").glob("*.md")],
        network=load(Path.home() / ".claude" / "marvin-network.json", {}),
        today=today or date.today().isoformat())


if __name__ == "__main__":
    print(json.dumps(formatted(gather()), indent=2))
