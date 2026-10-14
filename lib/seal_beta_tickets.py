#!/usr/bin/env python3
"""Auto-file Seal Speak beta tickets by device when thresholds are crossed (marvin#409; design: clarity-captions ADR 0024).

On the Mac Mini, reads ~/.claude/seal-beta/summary.json (produced by seal_beta_ingest.py's run) and files or updates
GitHub tickets on G-Eskayo/clarity-captions when device-level thresholds are crossed:
  - lag_p95 > 2 seconds
  - any "stuck" ending
  - median_rating ≤ 4 on a device (from ≥ 2 reports)

Tickets are never duplicated (one ticket per device model + problem) via hidden-comment markers in the body. Privacy
rule: ticket text holds only device model, build, report count, and measurements—never notes, names, phone numbers,
or timestamps.

    ~/.agents/venv/bin/python seal_beta_tickets.py run         # file/update tickets (what launchd runs)

Idempotent via hidden markers in ticket bodies (GitHub is the source of truth for whether a ticket exists).
Local ~/.claude/seal-beta/ticket-status.json cursor tracks round-robin window position when breaches exceed the
per-run cap, never for deciding existence.
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
from typing import Any, Callable

import project_catalog

REPO_DEFAULT = "G-Eskayo/clarity-captions"
STORE_DIR = Path.home() / ".claude" / "seal-beta"

# Thresholds at device level (matching ADR 0024's phrasing).
LAG_P95_THRESHOLD = 2.0  # seconds
STUCK_ENDING_THRESHOLD = 1  # any occurrence is a problem
MEDIAN_RATING_THRESHOLD = 4
MIN_REPORTS_FOR_RATING = 2

MAX_BREACHES_PER_RUN = 10

# Problem title templates (three distinct problems detected).
PROBLEMS = {
    "lag": "Seal Speak beta: high lag on {device}",
    "stuck": "Seal Speak beta: stuck endings on {device}",
    "rating": "Seal Speak beta: low user rating on {device}",
}


class GhError(Exception):
    """GitHub CLI error with deferred flag for rate-limit handling."""
    def __init__(self, rc: int, stderr: str):
        self.rc = rc
        self.stderr = stderr
        self.deferred = rc == 75  # EX_TEMPFAIL, gate's documented deferred code
        super().__init__(f"gh exited {rc}: {stderr[:200]}")


def _num(v: Any) -> int | float | None:
    """Safe numeric extraction, tolerant of None and non-numeric types."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    return None


def _safe_text(s: Any, max_len: int = 200) -> str:
    """Strip control chars, neutralize HTML comment markers, strip backticks, cap length."""
    if not isinstance(s, str):
        s = str(s) if s is not None else ""
    # Remove control characters (keep newlines/tabs)
    s = "".join(c for c in s if ord(c) >= 32 or c in "\t\n")
    # Neutralize HTML comment markers to a fixed point
    while "<!--" in s or "-->" in s:
        s = s.replace("-->", "--").replace("<!--", "")
    # Strip backticks
    s = s.replace("`", "")
    # Cap length
    if len(s) > max_len:
        s = s[:max_len]
    return s


def detect_breaches(by_device: list[dict]) -> list[dict]:
    """Pure function: given the `by_device` list from summary.json, return a list of breaches.

    Tolerant of malformed entries (missing keys, wrong types, NaN). Each breach is a dict with:
      - device: plain device name string
      - problem: one of "lag", "stuck", "rating"
      - measurements: dict holding only the relevant metric(s) — whitelisted, never raw notes or records
      - builds: list of per-build breakdowns (only the build number and the relevant metric)
    """
    breaches = []
    for dev_entry in by_device:
        if not isinstance(dev_entry, dict):
            continue
        device = dev_entry.get("device")
        if not isinstance(device, str):
            continue

        # ── lag_p95 breach ──────────────────────────────────────────────────
        lag = _num(dev_entry.get("lag_p95"))
        if lag is not None and lag > LAG_P95_THRESHOLD:
            builds_breakdown = []
            for b in dev_entry.get("builds") or []:
                if not isinstance(b, dict):
                    continue
                build = b.get("build")
                build_lag = _num(b.get("lag_p95"))
                if build is not None and build_lag is not None:
                    builds_breakdown.append({"build": str(build), "lag_p95": build_lag})
            breaches.append({
                "device": device,
                "problem": "lag",
                "measurements": {"lag_p95": lag},
                "builds": builds_breakdown,
                "reports": _num(dev_entry.get("reports")) or 0,
            })

        # ── stuck ending breach ─────────────────────────────────────────────
        endings = dev_entry.get("endings")
        stuck_count = _num(endings.get("stuck")) if isinstance(endings, dict) else None
        if stuck_count is not None and stuck_count > 0:
            builds_breakdown = []
            for b in dev_entry.get("builds") or []:
                if not isinstance(b, dict):
                    continue
                build = b.get("build")
                build_endings = b.get("endings")
                if isinstance(build_endings, dict):
                    build_stuck = _num(build_endings.get("stuck"))
                    if build_stuck is not None and build_stuck > 0:
                        builds_breakdown.append({"build": str(build), "stuck_count": build_stuck})
            breaches.append({
                "device": device,
                "problem": "stuck",
                "measurements": {"stuck_count": stuck_count},
                "builds": builds_breakdown,
                "reports": _num(dev_entry.get("reports")) or 0,
            })

        # ── median_rating breach ────────────────────────────────────────────
        reports = _num(dev_entry.get("reports"))
        rating = _num(dev_entry.get("median_rating"))
        if (isinstance(reports, (int, float)) and reports >= MIN_REPORTS_FOR_RATING and
                rating is not None and rating <= MEDIAN_RATING_THRESHOLD):
            builds_breakdown = []
            for b in dev_entry.get("builds") or []:
                if not isinstance(b, dict):
                    continue
                build = b.get("build")
                build_rating = _num(b.get("median_rating"))
                if build is not None and build_rating is not None:
                    builds_breakdown.append({"build": str(build), "median_rating": build_rating})
            breaches.append({
                "device": device,
                "problem": "rating",
                "measurements": {"median_rating": rating},
                "builds": builds_breakdown,
                "reports": _num(dev_entry.get("reports")) or 0,
            })

    return breaches


def _slug(device: str, problem: str) -> str:
    """Deterministic slug for device+problem used in the hidden marker.

    Takes raw device name and applies canonicalization: lowercase, remove control chars
    and backticks, replace non-alphanumeric with dashes.
    """
    # Canonicalize: remove control chars and backticks, then slugify
    device_canonical = _safe_text(device, max_len=200)
    clean_device = re.sub(r"[^a-z0-9]+", "-", device_canonical.lower()).strip("-")
    return f"{clean_device}-{problem}"


def ticket_key(device: str, problem: str) -> str:
    """The key for finding an existing ticket (search, marker comment). Takes raw device."""
    return _slug(device, problem)


def marker(device: str, problem: str) -> str:
    """Hidden HTML comment carrying the device+problem signature, placed in ticket body. Takes raw device."""
    slug = _slug(device, problem)
    return f"<!-- marvin:seal-beta:{slug} -->"


def render_title(device: str, problem: str) -> str:
    """Ticket title. Takes raw device, canonicalizes for display."""
    safe_device = _safe_text(device, max_len=100)
    template = PROBLEMS.get(problem, "Seal Speak beta: {device}")
    return template.format(device=safe_device)


def render_body(breach: dict) -> str:
    """Ticket body from a whitelisted breach dict (no notes, names, timestamps).

    Includes the hidden marker and measurements-only footer. Takes raw device from breach,
    applies display-only canonicalization for visible text.
    """
    raw_device = breach.get("device", "Unknown")
    display_device = _safe_text(raw_device, max_len=100)
    problem = breach.get("problem", "unknown")
    measurements = breach.get("measurements", {})
    builds = breach.get("builds", [])
    reports = breach.get("reports", 0)

    lines = [
        f"**Device:** {display_device}",
        f"**Reports:** {reports}",
        "",
    ]

    # Measurements summary.
    if problem == "lag":
        lag = measurements.get("lag_p95")
        if lag is not None:
            lines.append(f"**Lag (p95):** {lag:.2f}s (threshold: >{LAG_P95_THRESHOLD}s)")
    elif problem == "stuck":
        stuck = measurements.get("stuck_count", 0)
        lines.append(f"**Stuck endings:** {stuck} occurrences")
    elif problem == "rating":
        rating = measurements.get("median_rating")
        if rating is not None:
            lines.append(f"**Median rating:** {rating:.1f}/10 (threshold: ≤{MEDIAN_RATING_THRESHOLD})")

    # Per-build breakdown.
    if builds:
        lines.append("")
        lines.append("**Per-build measurements:**")
        for b in builds:
            build = b.get("build", "?")
            if problem == "lag":
                lag = b.get("lag_p95")
                lines.append(f"  - Build {build}: {lag:.2f}s" if lag is not None else f"  - Build {build}: -")
            elif problem == "stuck":
                stuck = b.get("stuck_count", 0)
                lines.append(f"  - Build {build}: {stuck} stuck")
            elif problem == "rating":
                rating = b.get("median_rating")
                lines.append(f"  - Build {build}: {rating:.1f}/10" if rating is not None else f"  - Build {build}: -")

    # Hidden marker (searchable, never visible to users). Pass raw device.
    lines.append("")
    lines.append(marker(raw_device, problem))

    return "\n".join(lines)


# ── gh-calling layer ───────────────────────────────────────────────────────────────────────

def find_existing(device: str, problem: str, repo: str, run=subprocess.run,
                  env_builder: Callable | None = None) -> dict | None:
    """Search GitHub for an existing ticket with the breach's hidden marker.

    Returns {"number", "body", "state"} dict or None.
    """
    if env_builder is None:
        env_builder = project_catalog.run_env
    search_term = _slug(device, problem)
    marker_text = marker(device, problem)
    try:
        proc = run(["gh", "issue", "list", "--repo", repo, "--search", search_term,
                    "--state", "all", "--limit", "100", "--json", "number,body,state"],
                   capture_output=True, text=True, timeout=20, env=env_builder())
        if proc.returncode == 75:
            raise GhError(75, proc.stderr)
        if proc.returncode != 0:
            raise GhError(proc.returncode, proc.stderr)
        try:
            issues = json.loads(proc.stdout) if proc.stdout else []
        except (json.JSONDecodeError, TypeError) as e:
            raise GhError(1, str(e))
        # Filter for exact marker match in body
        for issue in issues:
            if isinstance(issue, dict) and marker_text in (issue.get("body") or ""):
                return {"number": issue.get("number"), "body": issue.get("body") or "",
                        "state": issue.get("state", "OPEN")}
    except subprocess.TimeoutExpired as e:
        raise GhError(124, str(e))
    return None


def create_ticket(device: str, problem: str, body: str, repo: str, run=subprocess.run,
                  env_builder: Callable | None = None) -> int:
    """Create a new GitHub issue. Returns issue number."""
    if env_builder is None:
        env_builder = project_catalog.run_env
    title = render_title(device, problem)
    try:
        proc = run(["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body],
                   capture_output=True, text=True, timeout=20, env=env_builder())
        if proc.returncode != 0:
            raise GhError(proc.returncode, proc.stderr)
        # Extract issue number from output like "https://github.com/owner/repo/issues/123"
        match = re.search(r"/issues/(\d+)", proc.stdout)
        if match:
            return int(match.group(1))
        raise GhError(1, f"could not parse issue number from: {proc.stdout}")
    except subprocess.TimeoutExpired as e:
        raise GhError(124, str(e))


def update_ticket(number: int, body: str, repo: str, reopen: bool = False, run=subprocess.run,
                  env_builder: Callable | None = None) -> None:
    """Update an existing GitHub issue. Reopens if reopen=True and issue is closed."""
    if env_builder is None:
        env_builder = project_catalog.run_env
    try:
        proc = run(["gh", "issue", "edit", str(number), "--repo", repo, "--body", body],
                   capture_output=True, text=True, timeout=20, env=env_builder())
        if proc.returncode != 0:
            raise GhError(proc.returncode, proc.stderr)
        if reopen:
            proc_reopen = run(["gh", "issue", "reopen", str(number), "--repo", repo],
                              capture_output=True, text=True, timeout=20, env=env_builder())
            if proc_reopen.returncode != 0:
                raise GhError(proc_reopen.returncode, proc_reopen.stderr)
    except subprocess.TimeoutExpired as e:
        raise GhError(124, str(e))


# ── orchestration ──────────────────────────────────────────────────────────────────────────

def _write_json(path: Path, data) -> None:
    """Atomic JSON write (matches seal_beta_ingest.py's pattern)."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def file_or_update_breaches(breaches: list[dict], repo: str, now: datetime, run=subprocess.run,
                             env_builder: Callable | None = None, max_per_run: int = MAX_BREACHES_PER_RUN,
                             cursor: int = 0, dry_run: bool = False) -> dict:
    """File or update tickets for breaches, capped at max_per_run. Round-robin via cursor.

    Sorts breaches by (device, problem) slug; processes max_per_run-wide window starting at
    cursor % len(breaches). Returns status dict with cursor_next for next run.
    """
    if env_builder is None:
        env_builder = project_catalog.run_env

    status = {
        "generated_at": now.isoformat(),
        "breaches_detected": len(breaches),
        "tickets_filed": 0,
        "tickets_updated": 0,
        "tickets_unchanged": 0,
        "tickets_failed": 0,
        "tickets_deferred": 0,
        "cursor_next": cursor,
        "failed": [],
    }

    if not breaches:
        return status

    # Sort by device+problem slug for stable ordering.
    sorted_breaches = sorted(breaches, key=lambda b: _slug(b.get("device", ""), b.get("problem", "")))

    # Compute window: start at cursor % len, up to max_per_run items.
    start_idx = cursor % len(sorted_breaches)
    window_size = min(max_per_run, len(sorted_breaches))

    # On dry_run, return preview without making gh calls.
    if dry_run:
        for offset in range(window_size):
            status["tickets_deferred"] += 1
        status["cursor_next"] = cursor
        return status

    advanced = 0
    for offset in range(window_size):
        idx = (start_idx + offset) % len(sorted_breaches)
        breach = sorted_breaches[idx]
        device = breach.get("device", "?")
        problem = breach.get("problem", "?")

        try:
            body = render_body(breach)
            existing = find_existing(device, problem, repo, run=run, env_builder=env_builder)

            if existing is not None:
                existing_body = existing.get("body") or ""
                existing_state = existing.get("state", "OPEN")
                # Normalize whitespace for comparison.
                body_normalized = "\r\n" in body and body.replace("\r\n", "\n") or body
                existing_normalized = "\r\n" in existing_body and existing_body.replace("\r\n", "\n") or existing_body
                body_normalized = body_normalized.strip()
                existing_normalized = existing_normalized.strip()
                # Skip if already OPEN with identical body.
                if existing_state == "OPEN" and existing_normalized == body_normalized:
                    status["tickets_unchanged"] += 1
                    advanced += 1
                else:
                    # Update and possibly reopen if closed.
                    reopen = existing_state == "CLOSED"
                    update_ticket(existing["number"], body, repo, reopen=reopen, run=run, env_builder=env_builder)
                    status["tickets_updated"] += 1
                    advanced += 1
            else:
                number = create_ticket(device, problem, body, repo, run=run, env_builder=env_builder)
                status["tickets_filed"] += 1
                advanced += 1
        except GhError as e:
            if e.deferred:
                status["tickets_deferred"] += 1
                # Stop immediately on deferred error, don't advance past this point.
                break
            else:
                status["tickets_failed"] += 1
                status["failed"].append({"device": device, "problem": problem, "error": e.stderr[:100]})
                advanced += 1

    # Update cursor for next run: advance by items actually processed.
    status["cursor_next"] = (start_idx + advanced) % len(sorted_breaches) if sorted_breaches else 0
    return status


def run(store_dir: Path | None = None, repo: str = REPO_DEFAULT, now: datetime | None = None,
        run=subprocess.run, env_builder: Callable | None = None, dry_run: bool = False) -> dict:
    """Main entry point: read summary.json, detect breaches, file tickets.

    Returns a status dict with ok/error. Uses its own `.tickets.lock` for concurrency.
    Reads and writes cursor from ticket-status.json for round-robin ordering.
    """
    if env_builder is None:
        env_builder = project_catalog.run_env

    store = Path(store_dir or STORE_DIR)
    now = now or datetime.now(timezone.utc)
    store.mkdir(parents=True, exist_ok=True)

    lock_path = store / ".tickets.lock"
    with os.fdopen(os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)

        status = {"generated_at": now.isoformat(), "ok": True, "error": None,
                  "breaches_detected": 0, "tickets_filed": 0, "tickets_updated": 0,
                  "tickets_unchanged": 0, "tickets_failed": 0, "tickets_deferred": 0, "cursor_next": 0}

        # Read previous cursor for round-robin.
        cursor = 0
        status_path = store / "ticket-status.json"
        if status_path.exists():
            try:
                prev_status = json.loads(status_path.read_text())
                if isinstance(prev_status, dict):
                    prev_cursor = prev_status.get("cursor_next", 0)
                    cursor = prev_cursor if isinstance(prev_cursor, int) else 0
            except (ValueError, OSError):
                pass

        summary_path = store / "summary.json"
        if not summary_path.exists():
            status["cursor_next"] = cursor
            if not dry_run:
                _write_json(status_path, status)
            return status

        try:
            summary = json.loads(summary_path.read_text())
        except (ValueError, OSError):
            status["cursor_next"] = cursor
            if not dry_run:
                _write_json(status_path, status)
            return status

        if not isinstance(summary, dict):
            status["cursor_next"] = cursor
            if not dry_run:
                _write_json(status_path, status)
            return status

        by_device = summary.get("by_device", [])
        if not isinstance(by_device, list):
            status["cursor_next"] = cursor
            if not dry_run:
                _write_json(status_path, status)
            return status

        try:
            breaches = detect_breaches(by_device)
            file_status = file_or_update_breaches(breaches, repo, now, run=run, env_builder=env_builder,
                                                 cursor=cursor, dry_run=dry_run)
            status.update(file_status)
        except Exception as e:
            status["ok"] = False
            status["error"] = str(e)
            status["cursor_next"] = cursor

        if not dry_run:
            _write_json(status_path, status)
        return status


# ── CLI ────────────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="file/update tickets (what launchd runs)")
    r.add_argument("--store", type=Path, default=None)
    r.add_argument("--repo", default=REPO_DEFAULT)
    r.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "run":
        st = run(store_dir=a.store, repo=a.repo, dry_run=a.dry_run)
        if not st["ok"]:
            print(f"seal-beta-tickets: {st['error']}", file=sys.stderr)
            return 1
        filed = st.get("tickets_filed", 0)
        updated = st.get("tickets_updated", 0)
        unchanged = st.get("tickets_unchanged", 0)
        failed = st.get("tickets_failed", 0)
        deferred = st.get("tickets_deferred", 0)
        print(f"seal-beta-tickets: {st['breaches_detected']} breach(es), {filed} filed, {updated} updated, "
              f"{unchanged} unchanged, {failed} failed, {deferred} deferred")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
