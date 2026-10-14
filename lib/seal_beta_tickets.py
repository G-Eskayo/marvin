#!/usr/bin/env python3
"""File GitHub tickets when Seal Speak beta metrics breach thresholds (marvin#409).

When the summary.json crosses a threshold, files or updates **one** ticket per (device model, problem)
on G-Eskayo/clarity-captions. Privacy hard rule: the ticket text never holds a note, a tester name,
timestamps precise enough to identify a person, or any other PII.

Starting thresholds (tune once real data arrives):
- lag p95 > 2.0 s on a device model
- any `stuck` ending
- median rating ≤ 4 on a device model from ≥ 2 reports

Design: clarity-captions ADR 0024 + docs/beta/metrics-schema.md.

    ~/.agents/venv/bin/python seal_beta_tickets.py run [--store ...]
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_catalog  # noqa: E402

REPO = "G-Eskayo/clarity-captions"
LAG_P95_THRESHOLD_S = 2.0
LOW_RATING_THRESHOLD = 4
LOW_RATING_MIN_REPORTS = 2
STUCK_ENDING = "stuck"
STORE_DIR = Path.home() / ".claude" / "seal-beta"
STATE_PATH = STORE_DIR / "tickets.json"

# Decision flag: scope
# Options: "by-device" (analyze all ratings/lag for each device),
# or "by-build" (analyze per-device's latest build only)
SCOPE = "by-device"


def _sanitize(text: str, limit: int = 256) -> str:
    """Strip control chars, collapse HTML comments, cap length."""
    if text is None:
        return ""
    # Remove control characters (below space, except newline/tab)
    text = "".join(c for c in text if ord(c) >= 32 or c in "\n\t")
    # Collapse HTML comments and --> markers
    text = re.sub(r"<!--.*?-->", "", text)
    text = text.replace("-->", "")
    # Cap length (accounting for the ellipsis character)
    if len(text) > limit:
        text = text[:limit - 1].rstrip() + "…"
    return text


def breaches(summary: dict) -> Generator[dict, None, None]:
    """Yield {device, model_ids, problem, measurements} for each breach in summary["by_device"].

    Pure function over summary data. Tolerant of missing/None fields and non-dict entries.
    """
    if not isinstance(summary, dict) or "by_device" not in summary:
        return

    for device_entry in summary.get("by_device") or []:
        # Tolerate non-dict device entries
        if not isinstance(device_entry, dict):
            continue
        device = device_entry.get("device", "Unknown")
        model_ids = device_entry.get("model_ids", [])

        # Decide scope: by-device or latest-build
        if SCOPE == "by-build" and device_entry.get("builds"):
            builds = device_entry.get("builds", [])
            # Filter to dict entries only
            builds = [b for b in builds if isinstance(b, dict)]
            if builds:
                # Pick the build with highest numeric build number
                max_build = max(builds, key=lambda b: _build_sort_key(b.get("build")))
                entries_to_check = [max_build]
            else:
                entries_to_check = []
        else:
            # by-device: analyze the whole device's aggregated metrics
            entries_to_check = [device_entry]

        for entry in entries_to_check:
            if not isinstance(entry, dict):
                continue

            # Check lag p95 breach
            lag_p95 = entry.get("lag_p95")
            if lag_p95 is not None and isinstance(lag_p95, (int, float)) and lag_p95 > LAG_P95_THRESHOLD_S:
                yield {
                    "device": device,
                    "model_ids": model_ids,
                    "problem": "lag_p95",
                    "measurements": {
                        "lag_p95": lag_p95,
                        "threshold": LAG_P95_THRESHOLD_S,
                        "conversations": entry.get("conversations"),
                        "os_versions": entry.get("os_versions"),
                        "builds": entry.get("builds"),
                    },
                }

            # Check stuck ending breach
            endings = entry.get("endings")
            if isinstance(endings, dict):
                stuck_count = endings.get(STUCK_ENDING, 0)
                if stuck_count and isinstance(stuck_count, (int, float)) and stuck_count > 0:
                    yield {
                        "device": device,
                        "model_ids": model_ids,
                        "problem": "stuck",
                        "measurements": {
                            "stuck_count": stuck_count,
                            "endings": endings,
                            "conversations": entry.get("conversations"),
                            "os_versions": entry.get("os_versions"),
                            "builds": entry.get("builds"),
                        },
                    }

            # Check low rating breach: median_rating <= 4 from >= 2 reports
            median_rating = entry.get("median_rating")
            rated_reports = entry.get("rated_reports")
            # Fail closed: only use rated_reports if it's a list; otherwise 0
            if isinstance(rated_reports, list):
                num_rated_reports = len(rated_reports)
            else:
                num_rated_reports = 0

            if (median_rating is not None and isinstance(median_rating, (int, float))
                    and median_rating <= LOW_RATING_THRESHOLD
                    and num_rated_reports >= LOW_RATING_MIN_REPORTS):
                yield {
                    "device": device,
                    "model_ids": model_ids,
                    "problem": "low_rating",
                    "measurements": {
                        "median_rating": median_rating,
                        "threshold": LOW_RATING_THRESHOLD,
                        "rated_reports": num_rated_reports,
                        "os_versions": entry.get("os_versions"),
                        "builds": entry.get("builds"),
                    },
                }


def _build_sort_key(b) -> tuple:
    """Sort key for build numbers: numeric builds first (by value), then string builds."""
    try:
        return (0, int(b))
    except (TypeError, ValueError):
        return (-1, str(b))


def render(breach: dict) -> tuple[str, str, str]:
    """Convert breach dict to (key, title, body) for GitHub issue.

    key: derived from model_ids, not device name (avoids non-unique keys from display names)
    title: human-readable title (sanitized)
    body: GitHub issue body, starting with the marvin:seal-ticket marker
          containing only allow-listed fields, never notes, never timestamps
    """
    device = breach.get("device", "Unknown")
    problem = breach.get("problem", "unknown")
    model_ids = breach.get("model_ids", [])
    measurements = breach.get("measurements", {})

    # Create the key from model_ids for uniqueness, not the display device name
    if model_ids and isinstance(model_ids, list):
        key_source = f"{','.join(str(m) for m in model_ids)}-{problem}"
    else:
        key_source = f"{device}-{problem}"
    key = project_catalog.slug(key_source)

    # Create title (sanitize to prevent injection)
    sanitized_device = _sanitize(device, limit=64)
    if problem == "lag_p95":
        lag = measurements.get("lag_p95")
        title = f"Seal: {sanitized_device} - high lag (p95 {lag:.1f}s)" if lag else f"Seal: {sanitized_device} - lag breach"
    elif problem == "stuck":
        stuck = measurements.get("stuck_count", 0)
        title = f"Seal: {sanitized_device} - sessions stuck ({stuck} reports)"
    elif problem == "low_rating":
        rating = measurements.get("median_rating")
        title = f"Seal: {sanitized_device} - low rating (median {rating})" if rating else f"Seal: {sanitized_device} - rating breach"
    else:
        title = f"Seal: {sanitized_device} - {problem}"

    # Build body: privacy-conscious, allow-listed fields only
    lines = [f"<!-- marvin:seal-ticket:{key} -->"]
    lines.append("")
    lines.append(f"**Device:** {sanitized_device}")
    if model_ids and isinstance(model_ids, list):
        lines.append(f"**Model IDs:** {', '.join(_sanitize(str(m), limit=32) for m in model_ids)}")

    # iOS versions
    os_versions = measurements.get("os_versions")
    if os_versions and isinstance(os_versions, list):
        os_str = ", ".join(_sanitize(str(v), limit=32) for v in os_versions)
        lines.append(f"**iOS versions:** {os_str}")

    # Measurements (vary by problem type)
    if problem == "lag_p95":
        lag = measurements.get("lag_p95")
        threshold = measurements.get("threshold")
        if lag is not None and threshold is not None:
            lines.append(f"**Lag p95:** {lag:.2f}s (threshold: {threshold}s)")
        convs = measurements.get("conversations")
        if convs is not None:
            lines.append(f"**Conversations:** {convs}")

    elif problem == "stuck":
        stuck = measurements.get("stuck_count")
        if stuck is not None:
            lines.append(f"**Stuck reports:** {stuck}")
        endings = measurements.get("endings")
        if endings and isinstance(endings, dict):
            endings_str = ", ".join(f"{_sanitize(str(k), limit=16)}: {v}" for k, v in sorted(endings.items()))
            lines.append(f"**Ending breakdown:** {endings_str}")
        convs = measurements.get("conversations")
        if convs is not None:
            lines.append(f"**Conversations:** {convs}")

    elif problem == "low_rating":
        rating = measurements.get("median_rating")
        threshold = measurements.get("threshold")
        if rating is not None and threshold is not None:
            lines.append(f"**Median rating:** {rating} (threshold: ≤ {threshold})")
        rated = measurements.get("rated_reports")
        if rated is not None:
            lines.append(f"**Rated reports:** {rated}")

    # Build breakdown
    builds = measurements.get("builds")
    if builds and isinstance(builds, list):
        build_lines = []
        for b in builds:
            if isinstance(b, dict):
                build_num = _sanitize(str(b.get("build", "?")), limit=16)
                convs = b.get("conversations")
                if convs is not None:
                    build_lines.append(f"  build {build_num}: {convs} conv")
        if build_lines:
            lines.append("")
            lines.append("**Build breakdown:**")
            lines.extend(build_lines)

    lines.append("")
    lines.append("---")
    lines.append("*Auto-filed by Seal Beta Ingest Job (marvin#409). Metrics from ~/.claude/seal-beta/summary.json.*")

    body = "\n".join(lines)
    return key, title, body


def _gh(args: list[str], env=None) -> str | None:
    """Call gh CLI with error tolerance. Returns stdout or None on failure (including exit 75).

    args: list of command arguments (no shell=True, no shlex needed)
    env: optional environment dict (from project_catalog.run_env if not provided)
    """
    # Use ~/.agents/bin/gh if available, else fallback to bare gh
    gh_path = Path.home() / ".agents" / "bin" / "gh"
    if not gh_path.exists():
        gh_path = Path("gh")

    # Default to project_catalog.run_env() if env not provided (ensures Homebrew PATH in launchd)
    if env is None:
        env = project_catalog.run_env()

    try:
        result = subprocess.run(
            [str(gh_path), *args],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        # Exit 75 (API rate limit) or any other error returns None
        return None
    except (subprocess.TimeoutExpired, OSError):
        return None


def _find_issue(key: str, marker: str, state: dict, gh=None) -> int | None:
    """Find a GitHub issue by marker (HTML comment with key), or None if not found/gh failed.

    Checks state file first, then gh issue list, and backfills state if found.
    gh: optional callable for testing. If None, uses _gh().
    """
    # Check state file first
    if key in state:
        return state[key]

    # Query gh for existing issue
    if gh is None:
        gh = _gh

    search_args = ["issue", "list", "--search", f"{marker} in:body", "--state", "all", "--json", "number", "--repo", REPO]
    output = gh(search_args)
    if output is None:
        return None

    try:
        issues = json.loads(output)
        if not issues:
            return None
        # Return the lowest number (oldest)
        nums = [i.get("number") for i in issues if isinstance(i, dict) and "number" in i and isinstance(i["number"], int)]
        if not nums:
            return None
        num = min(nums)
        state[key] = num
        return num
    except (ValueError, TypeError):
        return None


def check_and_file(store_dir: Path | None = None, gh=None, now: datetime | None = None) -> dict:
    """Main orchestrator: load summary, find breaches, file/update tickets.

    Holds the store/.lock flock. Returns a status dict per breach (filed/updated/gh-failed/skipped).
    Never raises; gh failures are logged in the return value.
    gh: optional callable for testing. If None, uses _gh().
    """
    store = Path(store_dir or STORE_DIR)
    now = now or datetime.now(timezone.utc)
    result = {"generated_at": now.isoformat(), "breaches": []}

    if gh is None:
        gh = _gh

    # Ensure store exists
    store.mkdir(parents=True, exist_ok=True)

    # Acquire file lock
    lock_path = store / ".lock"
    try:
        with os.fdopen(os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)

            # Load existing state, validate it's a dict
            state = {}
            state_path = store / "tickets.json"
            if state_path.exists():
                try:
                    loaded = json.loads(state_path.read_text())
                    state = loaded if isinstance(loaded, dict) else {}
                except (ValueError, OSError):
                    state = {}

            # Load summary
            summary_path = store / "summary.json"
            if not summary_path.exists():
                result["status"] = "no_summary"
                return result

            try:
                summary = json.loads(summary_path.read_text())
            except (ValueError, OSError):
                result["status"] = "summary_read_failed"
                return result

            # Track confirmed state changes (only write if successful)
            confirmed_state = {}

            # Process breaches
            for breach in breaches(summary):
                try:
                    key, title, body = render(breach)
                    marker = f"<!-- marvin:seal-ticket:{key} -->"

                    # Find or create issue
                    issue_num = _find_issue(key, marker, state, gh=gh)
                    if issue_num is None:
                        # Try to create a new issue
                        create_args = ["issue", "create", "--repo", REPO, "--title", title, "--body", body]
                        output = gh(create_args)
                        if output is None:
                            result["breaches"].append({"problem": breach["problem"], "status": "gh-failed", "key": key})
                            continue

                        # Parse the issue number from the output (should be a URL)
                        try:
                            # gh returns: "https://github.com/owner/repo/issues/NNN"
                            issue_num = int(output.rstrip("/").split("/")[-1])
                            confirmed_state[key] = issue_num
                            result["breaches"].append({"problem": breach["problem"], "status": "filed", "number": issue_num})
                        except (ValueError, IndexError):
                            result["breaches"].append({"problem": breach["problem"], "status": "gh-failed", "key": key})
                            continue
                    else:
                        # Check if issue is closed, reopen it
                        view_args = ["issue", "view", str(issue_num), "--repo", REPO, "--json", "state,body"]
                        view_output = gh(view_args)
                        if view_output is not None:
                            try:
                                issue_data = json.loads(view_output)
                                issue_state = issue_data.get("state")
                                # Tolerate null body or non-dict issue_data
                                issue_body = (issue_data.get("body") if isinstance(issue_data, dict) else None) or ""

                                # Check if body already matches (skip edit if unchanged)
                                if issue_body.strip() == body.strip():
                                    result["breaches"].append({"problem": breach["problem"], "status": "unchanged", "number": issue_num})
                                    confirmed_state[key] = issue_num
                                    continue

                                # Reopen if closed
                                if issue_state == "CLOSED":
                                    reopen_args = ["issue", "reopen", str(issue_num), "--repo", REPO]
                                    reopen_output = gh(reopen_args)
                                    if reopen_output is None:
                                        result["breaches"].append({"problem": breach["problem"], "status": "gh-failed", "key": key})
                                        continue
                            except (ValueError, TypeError):
                                pass

                        # Update the issue body
                        edit_args = ["issue", "edit", str(issue_num), "--repo", REPO, "--body", body]
                        output = gh(edit_args)
                        if output is None:
                            result["breaches"].append({"problem": breach["problem"], "status": "gh-failed", "key": key})
                            continue
                        confirmed_state[key] = issue_num
                        result["breaches"].append({"problem": breach["problem"], "status": "updated", "number": issue_num})

                except Exception as e:
                    # Record per-breach error and continue
                    result["breaches"].append({
                        "problem": breach.get("problem", "unknown"),
                        "status": "error",
                        "error": str(e),
                        "key": key if "key" in locals() else None
                    })

            # Atomically write state file: merge old state with confirmed keys
            tmp = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                merged_state = {**state, **confirmed_state}
                json.dump(merged_state, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, state_path)
            result["status"] = "ok"

    except (OSError, IOError) as e:
        result["status"] = f"error: {e}"
        return result

    return result


def main(argv: list[str] | None = None, check_and_file=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="check summary and file/update tickets")
    r.add_argument("--store", type=Path, default=None)
    a = ap.parse_args(argv)

    # Support injection of check_and_file for testing
    if check_and_file is None:
        from seal_beta_tickets import check_and_file as default_check_and_file
        check_and_file = default_check_and_file

    result = check_and_file(store_dir=a.store)
    print(f"seal-beta-tickets: {result.get('status', 'unknown')}")
    for breach in result.get("breaches", []):
        print(f"  {breach.get('problem')}: {breach.get('status')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
