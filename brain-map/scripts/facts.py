#!/usr/bin/env python3
"""
facts.py — the MARVIN page's numbers, computed from the system so they can't go stale
(docs/plans/living-marvin-page-2026-10-08.md, layer 1; published with the map under ADR 0057's extension).

  skills       entries in the skill index (~/.claude/manifest.json)
  tests        tests_passed in the newest pipeline run (bench/metrics/ticket-*.json): what runs on every change
  prs_merged   merged pull requests the pipeline wrote ("Implement G-Eskayo/<repo>#N"), from GitHub search
  agents       background jobs MARVIN schedules (lib/health_checks.py JOB_PLACEMENT)
  decisions    architecture decision records (docs/adr/NNNN-*.md files)
  machines     registered machines (~/.claude/marvin-network.json)
  counted_on   the day these were counted

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


def compute_facts(*, manifest: dict, test_runs: list[list[dict]], merged_prs: int | None, placement: dict,
                  adr_names: list[str], network: dict, today: str) -> dict:
    out: dict = {}
    if manifest.get("index"):
        out["skills"] = len(manifest["index"])
    entries = [e for run in test_runs for e in run if isinstance(e, dict) and "tests_passed" in e.get("metrics", {})]
    if entries:
        newest = max(entries, key=lambda e: e.get("timestamp", ""))
        out["tests"] = int(newest["metrics"]["tests_passed"]["value"])
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


def _merged_pipeline_prs() -> int | None:
    """REST search (its own rate limit, not the GraphQL budget the pipeline lives on)."""
    try:
        p = subprocess.run(["gh", "api", "-X", "GET", "search/issues", "-f",
                            'q=user:G-Eskayo is:pr is:merged "Implement G-Eskayo/" in:title', "-q", ".total_count"],
                           capture_output=True, text=True, timeout=30)
        return int(p.stdout.strip()) if p.returncode == 0 and p.stdout.strip().isdigit() else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def gather(today: str | None = None) -> dict:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import connections  # reads JOB_PLACEMENT without importing the health stack

    def load(p: Path, default):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    runs = [load(f, []) for f in sorted((REPO / "bench" / "metrics").glob("ticket-*.json"))]
    return compute_facts(
        manifest=load(Path.home() / ".claude" / "manifest.json", {}),
        test_runs=[r for r in runs if isinstance(r, list)],
        merged_prs=_merged_pipeline_prs(),
        placement=connections.read_job_placement(REPO / "lib" / "health_checks.py"),
        adr_names=[p.name for p in (REPO / "docs" / "adr").glob("*.md")],
        network=load(Path.home() / ".claude" / "marvin-network.json", {}),
        today=today or date.today().isoformat())


if __name__ == "__main__":
    print(json.dumps(formatted(gather()), indent=2))
