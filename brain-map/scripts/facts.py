#!/usr/bin/env python3
"""
facts.py — the MARVIN page's numbers, computed from the system so they can't go stale
(docs/plans/living-marvin-page-2026-10-08.md, layer 1; published with the map under ADR 0057's extension).

  skills           entries in the skill index (~/.claude/manifest.json) whose file is a SKILL.md, not the memories it also holds
  tests            sum of tests_python + tests_js + tests_site (collected live per test suite)
  tests_python     pytest collected tests (lib/)
  tests_js         vitest collected tests (dashboard/)
  tests_site       site tests collected (site/)
  prs_merged       merged pull requests across all board repos (GitHub REST API)
  agents           background jobs MARVIN schedules (lib/health_checks.py JOB_PLACEMENT)
  decisions        architecture decision records (docs/adr/NNNN-*.md files)
  machines         registered machines (~/.claude/marvin-network.json)
  counted_on       the day these were counted
  <figure>_counted_on  timestamp when that figure was last updated (carry-forward tracking)

A source that can't be read is left out, never written as 0: the page then keeps the number it was written with.
compute_facts() is pure; gather() does the reading.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
import sys  # noqa: E402
sys.path.insert(0, str(REPO / "lib"))


def compute_facts(*, manifest: dict, tests_python: int | None = None, tests_js: int | None = None,
                  tests_site: int | None = None, merged_prs: int | None = None, placement: dict,
                  adr_names: list[str], network: dict, today: str) -> dict:
    out: dict = {}
    # The index also holds memories; a skill is an entry whose file is a SKILL.md (type tags vary: agent, library...).
    skills = [e for e in manifest.get("index") or [] if isinstance(e, dict) and str(e.get("path", "")).endswith("/SKILL.md")]
    if skills:
        out["skills"] = len(skills)
    # Collect all present test counts
    test_counts = []
    if tests_python is not None:
        test_counts.append(tests_python)
    if tests_js is not None:
        test_counts.append(tests_js)
    if tests_site is not None:
        test_counts.append(tests_site)
    # Write individual test counts and total only when all three are present
    if tests_python is not None:
        out["tests_python"] = tests_python
    if tests_js is not None:
        out["tests_js"] = tests_js
    if tests_site is not None:
        out["tests_site"] = tests_site
    if test_counts and len(test_counts) == 3:
        out["tests"] = sum(test_counts)
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


def _board_repos() -> list[dict] | None:
    """Read all boards (archived and active) from the board registry."""
    try:
        sys.path.insert(0, str(REPO / "lib"))
        import board_registry
        return board_registry.list_boards(include_archived=True)
    except Exception:  # noqa: BLE001
        return None


def _closed_prs(repo: str) -> int | None:
    """Count merged/closed PRs in a repo via paginated REST /pulls endpoint."""
    try:
        p = subprocess.run(["gh", "api", "--paginate", "-X", "GET", f"repos/{repo}/pulls",
                            "-f", "state=closed", "-q", ".[] | select(.merged_at != null) | .merged_at"],
                           capture_output=True, text=True, timeout=60)
        if p.returncode == 0:
            # Count non-empty lines
            count = sum(1 for line in p.stdout.strip().split("\n") if line)
            return count
        return None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _merged_pipeline_prs_total(repos: list[dict] | None) -> int | None:
    """Sum merged PRs with pipeline/ head ref across all board repos.
    Returns None if any repo fails or repo list is empty; fail-whole for consistency."""
    if not repos:
        return None
    try:
        total = 0
        for board in repos:
            repo_name = board.get("repo", "")
            if not repo_name:
                continue
            # Count merged PRs with head ref matching pipeline/*
            p = subprocess.run(["gh", "api", "--paginate", "-X", "GET", f"repos/{repo_name}/pulls",
                                "-f", "state=closed", "-q",
                                ".[] | select(.merged_at != null and (.head.ref | startswith(\"pipeline/\"))) | .merged_at"],
                               capture_output=True, text=True, timeout=60)
            if p.returncode != 0:
                return None
            total += sum(1 for line in p.stdout.strip().split("\n") if line)
        return total
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _pytest_collected() -> int | None:
    """Collect test count from pytest on the whole lib directory."""
    try:
        p = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", str(REPO / "lib")],
                           capture_output=True, text=True, timeout=60, cwd=str(REPO))
        # Exit code 0 = success, 1 = tests failed (not collection), 2 = collection error (we still extract count)
        if p.returncode in (0, 1, 2):
            # Parse last line: typically "123 test collected" or similar
            lines = [l.strip() for l in p.stdout.strip().split("\n") if l.strip()]
            if lines:
                last = lines[-1]
                m = re.search(r"(\d+)\s+test", last)
                if m:
                    return int(m.group(1))
        return None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _vitest_listed(dashboard_dir: str | Path | None = None) -> int | None:
    """Collect test count from vitest on the dashboard directory."""
    dashboard_dir = Path(dashboard_dir or REPO / "dashboard")
    if not dashboard_dir.exists():
        return None
    try:
        p = subprocess.run(["npm", "run", "test:list"],
                           capture_output=True, text=True, timeout=60, cwd=str(dashboard_dir))
        if p.returncode == 0:
            # Look for the summary line showing test count, skipping npm banner lines
            for line in p.stdout.split("\n"):
                # Skip npm banner and warning lines
                if line.startswith(">") or "npm" in line.lower():
                    continue
                m = re.search(r"(\d+)\s+test", line)
                if m:
                    return int(m.group(1))
        return None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _site_tests_collected(site_dir: str | Path | None = None) -> int | None:
    """Collect test count from site tests."""
    site_dir = Path(site_dir or REPO / "site")
    if not site_dir.exists():
        return None
    try:
        # Try different test runners: Jest first, then Node's built-in test runner
        runners = [
            (["npm", "test", "--", "--listTests"], "jest"),
            (["npm", "run", "test"], "node-test"),
        ]
        for runner_cmd, runner_type in runners:
            try:
                p = subprocess.run(runner_cmd, capture_output=True, text=True, timeout=60, cwd=str(site_dir))
                if p.returncode == 0:
                    if runner_type == "jest":
                        # Count test files matching the pattern
                        count = sum(1 for line in p.stdout.split("\n")
                                    if re.search(r"\.test\.(js|ts|jsx|tsx)$", line))
                    else:
                        # Node's test runner outputs "# tests N" summary line
                        m = re.search(r"#\s+tests?\s+(\d+)", p.stdout)
                        count = int(m.group(1)) if m else 0
                    if count > 0:
                        return count
            except (OSError, subprocess.TimeoutExpired):
                continue
        return None
    except Exception:  # noqa: BLE001
        return None


def merge_with_previous(fresh: dict, previous: dict) -> dict:
    """Merge fresh facts with previous facts, carrying forward figures that couldn't be collected.
    For each figure that was present before but missing in fresh, copy it over and carry forward
    its _counted_on to show when it was actually last updated."""
    out = dict(fresh)
    if not previous:
        return out
    # Carry forward missing figures and mark them as stale
    for key, value in previous.items():
        if key not in out and not key.endswith("_counted_on"):
            # Carry forward missing figure from previous
            out[key] = value
            # Mark when it was last updated — use previous _counted_on or fall back to previous counted_on
            if key in ("tests_python", "tests_js", "tests_site", "tests", "prs_merged", "skills",
                       "agents", "decisions", "machines"):
                counted_key = f"{key}_counted_on"
                # Carry forward the previous _counted_on timestamp (when it was actually last counted)
                out[counted_key] = previous.get(counted_key) or previous.get("counted_on")
    return out


def gather(today: str | None = None) -> dict:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import connections  # reads JOB_PLACEMENT without importing the health stack

    def load(p: Path, default):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    boards = _board_repos()
    return compute_facts(
        manifest=load(Path.home() / ".claude" / "manifest.json", {}),
        tests_python=_pytest_collected(),
        tests_js=_vitest_listed(),
        tests_site=_site_tests_collected(),
        merged_prs=_merged_pipeline_prs_total(boards),
        placement=connections.read_job_placement(REPO / "lib" / "health_checks.py"),
        adr_names=[p.name for p in (REPO / "docs" / "adr").glob("*.md")],
        network=load(Path.home() / ".claude" / "marvin-network.json", {}),
        today=today or date.today().isoformat())


if __name__ == "__main__":
    print(json.dumps(formatted(gather()), indent=2))
