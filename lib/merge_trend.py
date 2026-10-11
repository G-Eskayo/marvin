#!/usr/bin/env python3
"""merge_trend.py — record merge events with mutation scores and area classification (ADR 0063, #339; ADR 0064, #341).

Fetches PR body for mutation score, fetches files to classify the area (core/dashboard/other),
scores the change via auto_merge_shadow.mutation_score(), and appends one JSONL line to the log.
Best effort: any failure returns None and logs are never corrupted (append-only).

    record_merge_event(repo: str, pr_url: str, log_path: Path) -> dict | None
        Records a single merge event. Returns the recorded entry or None on error.

    main(argv) -> None
        CLI entry point: repo pr_url
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auto_merge_shadow as ams  # noqa: E402
import auto_merge_policy as amp  # noqa: E402

MERGE_TREND_LOG = Path.home() / ".claude" / "logs" / "merge-mutation-trend.jsonl"


def _gh(args: list[str]) -> str:
    """Call gh with args, return stdout. Raises CalledProcessError on error."""
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True, timeout=60).stdout


_AREA_PRIORITY = {"core": 0, "dependency": 1, "ui": 2, "new-top-level": 3, "odd": 4, "owned": 5}


def _classify_area(repo: str, files: list[str], clone: Path | None = None) -> str:
    """Classify a PR by the highest-priority area touched. Calls amp.area() for each file
    and reduces to one area via priority: core > dependency > ui > new-top-level > odd > owned."""
    clone = clone or (Path.home() / ".agents")
    rules = amp.load_rules()

    # Fetch existing top-level directories from origin/main
    try:
        result = subprocess.run(
            ["git", "ls-tree", "--name-only", "-d", "origin/main"],
            cwd=clone,
            capture_output=True,
            text=True,
            timeout=30,
            check=False
        )
        existing_top_level = {line.strip() for line in result.stdout.split() if line.strip()}
    except Exception:  # noqa: BLE001
        existing_top_level = set()

    # Classify each file and find the highest-priority area
    areas = []
    for f in files:
        area = amp.area(f, rules, existing_top_level)
        areas.append(area)

    # Return the highest-priority area found
    if not areas:
        return "owned"
    return min(areas, key=lambda a: _AREA_PRIORITY.get(a, 999))


def record_merge_event(repo: str, pr_url: str, log_path: Path = MERGE_TREND_LOG) -> dict | None:
    """Record a merge event to the trend log. Returns the entry or None on error (best effort)."""
    try:
        # Extract PR number from URL
        m = re.search(r'/pull/(\d+)', pr_url)
        if not m:
            return None
        pr_num = m.group(1)

        # Fetch PR body for mutation score
        body_json = _gh(["pr", "view", pr_url, "--json", "body"])
        body_data = json.loads(body_json)
        body = body_data.get("body") or ""

        # Extract mutation score
        score = ams.mutation_score(body)
        if score is None:
            return None  # No score yet; best effort = skip

        # Fetch files to classify area
        files_json = _gh(["pr", "view", pr_url, "--json", "files"])
        files_data = json.loads(files_json)
        files = [f.get("path", "") for f in (files_data.get("files") or [])]

        # Classify area
        area = _classify_area(repo, files)

        # Build entry
        now = datetime.now(timezone.utc)
        entry = {
            "pr_url": pr_url,
            "pr_number": int(pr_num),
            "repo": repo,
            "score": score,
            "area": area,
            "recorded_at": now.isoformat(),
        }

        # Append to log (best effort: create parent if needed, ignore lock errors)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            return None  # Log write failed; best effort = skip

        return entry
    except Exception:  # noqa: BLE001
        return None  # Any error: best effort = skip


def main(argv: list[str]) -> None:
    """CLI: repo pr_url"""
    if len(argv) < 2:
        print("usage: merge_trend.py REPO PR_URL")
        sys.exit(1)

    repo, pr_url = argv[0], argv[1]
    result = record_merge_event(repo, pr_url)
    if result:
        print(json.dumps(result))
    else:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
