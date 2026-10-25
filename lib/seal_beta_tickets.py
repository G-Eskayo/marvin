#!/usr/bin/env python3
"""Seal Speak beta alert filing (marvin#409; ADR 0024 thresholds).

Reads the per-device summary from seal_beta_ingest.py, detects when metrics cross thresholds
(high lag, poor rating, stuck endings), and files/updates tickets on clarity-captions for each
breach. Runs on the Mac Mini after ingest completes, controlled by launchd.

Thresholds (from ADR 0024):
- High lag: p95 > 2.0 seconds
- Poor rating: median_rating ≤ 4 (on 1-10 scale), AND >= 2 reports
- Stuck endings: any literal "stuck" ending (not a percentage threshold)

    ~/.agents/venv/bin/python seal_beta_tickets.py run [--mode propose|act] [--repo clarity-captions] [--store ~/.claude/seal-beta]
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

STORE_DIR = Path.home() / ".claude" / "seal-beta"
CLARITY_CAPTIONS_REPO = "G-Eskayo/clarity-captions"
CONFIG_PATH = Path.home() / ".agents" / "config" / "seal_beta_tickets.json"
PROPOSALS_PATH = Path.home() / ".claude" / "logs" / "seal-beta-tickets-proposals.json"
MAX_TICKETS_PER_RUN = 10

THRESHOLDS = {
    "lag_p95": 2.0,
    "median_rating": 4,
}

MIN_REPORTS_FOR_RATING = 2

# Config file at ~/.agents/config/seal_beta_tickets.json, optional.
# Example:
# {
#   "mode": "act"
# }
# If absent or invalid, defaults to propose mode (safe, logs what would happen).


def load_config(path: Path = CONFIG_PATH) -> dict:
    try:
        cfg = json.loads(path.read_text())
        if isinstance(cfg, dict) and cfg.get("mode") in ("propose", "act"):
            return cfg
    except (OSError, json.JSONDecodeError):
        pass
    return {"mode": "propose"}


def slugify(s: str) -> str:
    """Sanitize a string to safe markdown/URL slug: alphanumeric, hyphen, lowercase."""
    if not isinstance(s, str):
        s = str(s)
    s = s.lower()
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:50] or "unknown"


def device_label(device_name: str) -> str:
    """Safe device label for marker and body text: strip special chars that could break markdown."""
    if not isinstance(device_name, str):
        device_name = str(device_name)
    safe = re.sub(r"[`'\"\n\r<>]", "", device_name)
    return safe[:80]


def detect_breaches(summary: dict) -> list[dict]:
    """Pure function: detect all threshold breaches from summary["by_device"].
    Returns a list of {device, problem, measurements: {device_name, os_versions, build, lag_p95, median_rating, stuck_pct, ...}}.
    Skips malformed entries (non-dict device, non-dict endings, non-numeric metrics)."""
    breaches = []
    if not isinstance(summary, dict) or not isinstance(summary.get("by_device"), list):
        return breaches

    for dev in summary["by_device"]:
        if not isinstance(dev, dict):
            continue

        device_name = dev.get("device", "Unknown")
        os_versions = dev.get("os_versions", [])
        build = None
        if isinstance(dev.get("builds"), list) and dev["builds"]:
            build = dev["builds"][0].get("build")

        lag_p95 = dev.get("lag_p95")
        median_rating = dev.get("median_rating")
        endings = dev.get("endings", {})
        conversations = dev.get("conversations", 0)
        reports = dev.get("reports", 0)

        # Type guards: skip if metrics have wrong types
        if not isinstance(lag_p95, (int, float)) and lag_p95 is not None:
            lag_p95 = None
        if not isinstance(median_rating, (int, float)) and median_rating is not None:
            median_rating = None
        if not isinstance(endings, dict):
            continue  # Skip entry if endings is not a dict
        if not isinstance(conversations, (int, float)):
            conversations = 0
        if not isinstance(reports, (int, float)):
            reports = 0

        stuck_count = sum(v for k, v in endings.items() if k != "userStop") if conversations > 0 else 0
        stuck_pct = round(100.0 * stuck_count / conversations, 1) if conversations > 0 else 0

        measurements = {
            "device_name": device_label(device_name),
            "os_versions": os_versions,
            "build": build,
            "lag_p95": lag_p95,
            "median_rating": median_rating,
            "stuck_pct": stuck_pct,
            "conversations": conversations,
            "reports": reports,
        }

        if lag_p95 is not None and lag_p95 > THRESHOLDS["lag_p95"]:
            breaches.append({"device": device_name, "problem": "lag", "measurements": measurements})

        if median_rating is not None and median_rating <= THRESHOLDS["median_rating"] and reports >= MIN_REPORTS_FOR_RATING:
            breaches.append({"device": device_name, "problem": "rating", "measurements": measurements})

        if endings.get("stuck", 0) > 0:
            breaches.append({"device": device_name, "problem": "ending", "measurements": measurements})

    return breaches


def render_title(breach: dict) -> str:
    """Render the GitHub issue title from breach measurements."""
    m = breach["measurements"]
    problem = breach["problem"]
    device = m["device_name"]
    build = m["build"] or "unknown"

    if problem == "lag":
        return f"Seal Speak beta: high latency on {device} (build {build})"
    elif problem == "rating":
        return f"Seal Speak beta: poor rating on {device} (build {build})"
    elif problem == "ending":
        return f"Seal Speak beta: abnormal endings on {device} (build {build})"
    else:
        return f"Seal Speak beta: issue on {device} (build {build})"


def render_body(breach: dict) -> str:
    """Render the GitHub issue body with marker and measurements.
    TODO (Decision: label answered): If label=A (ready-for-human), add ## Your task section."""
    m = breach["measurements"]
    problem = breach["problem"]
    slug = slugify(m["device_name"])
    marker = f"<!-- marvin:seal-beta:{slug}:{problem} -->"

    os_str = ", ".join(m["os_versions"]) if m["os_versions"] else "unknown"

    body_lines = [
        marker,
        "",
        f"**Device:** {m['device_name']}",
        f"**OS:** {os_str}",
        f"**Build:** {m['build'] or 'unknown'}",
        f"**Conversations:** {m['conversations']} ({m['reports']} report(s))",
        "",
    ]

    if problem == "lag":
        body_lines.append(f"**Latency (p95):** {m['lag_p95']:.3f}s (threshold: >{THRESHOLDS['lag_p95']}s)")
    elif problem == "rating":
        body_lines.append(f"**Median rating:** {m['median_rating']:.1f}/10 (threshold: ≤{THRESHOLDS['median_rating']}, min {MIN_REPORTS_FOR_RATING} reports)")
    elif problem == "ending":
        body_lines.append(f"**Abnormal endings:** {m['stuck_pct']:.1f}% (threshold: any literal 'stuck' > 0)")

    body_lines.extend(["", "View the beta dashboard for details."])

    return "\n".join(body_lines)


def render_update_comment(breach: dict) -> str:
    """Render an update comment (without the marker)."""
    m = breach["measurements"]
    problem = breach["problem"]

    update_lines = ["Updated metrics:"]
    if problem == "lag":
        update_lines.append(f"- Latency (p95): {m['lag_p95']:.3f}s")
    elif problem == "rating":
        update_lines.append(f"- Median rating: {m['median_rating']:.1f}/10")
    elif problem == "ending":
        update_lines.append(f"- Abnormal endings: {m['stuck_pct']:.1f}%")

    update_lines.extend([
        f"- Conversations: {m['conversations']} ({m['reports']} report(s))",
        f"- Build: {m['build'] or 'unknown'}",
    ])

    return "\n".join(update_lines)


def find_existing(marker: str, repo: str, gh) -> dict | None:
    """Search clarity-captions for an open issue with this marker in its body.
    Returns the issue dict (with body/title/number) or None if not found.
    Raises on gh errors."""
    issues_json = gh(["issue", "list", "--repo", repo, "--state", "open",
                     "--search", f'"{marker}" in:body', "--json", "number,title,body"])
    issues = json.loads(issues_json)

    for issue in issues:
        body = issue.get("body", "")
        if marker in body:
            return issue

    return None


def file_or_update(breach: dict, repo: str, gh, mode: str = "propose") -> dict:
    """File a new issue or post an update comment to an existing one.
    Returns {status: "created"|"updated"|"deferred"|"failed", ...}.
    TODO (Decision: resolve answered): If resolve=B or C, detect when metrics no longer breach
    (compare current state vs. last known) and post comment and/or close."""
    m = breach["measurements"]
    problem = breach["problem"]
    slug = slugify(m["device_name"])
    marker = f"<!-- marvin:seal-beta:{slug}:{problem} -->"

    title = render_title(breach)
    body = render_body(breach)

    try:
        existing = find_existing(marker, repo, gh)
    except Exception as e:
        if getattr(e, "returncode", None) == 75:
            return {"status": "deferred", "action": "search", "title": title}
        if "rate limit" in f"{e} {getattr(e, 'stderr', '') or ''}".lower():
            return {"status": "deferred", "action": "search", "title": title}
        return {"status": "failed", "action": "search", "title": title, "error": str(e)[:200]}

    if existing:
        if mode != "act":
            return {"status": "deferred", "action": "update", "issue": existing["number"]}
        comment_body = render_update_comment(breach)
        try:
            gh(["issue", "comment", str(existing["number"]), "--repo", repo, "--body", comment_body])
            return {"status": "updated", "issue": existing["number"]}
        except Exception as e:
            if getattr(e, "returncode", None) == 75:
                return {"status": "deferred", "action": "comment", "issue": existing["number"]}
            if "rate limit" in f"{e} {getattr(e, 'stderr', '') or ''}".lower():
                return {"status": "deferred", "action": "comment", "issue": existing["number"]}
            return {"status": "failed", "action": "comment", "issue": existing["number"], "error": str(e)[:200]}
    else:
        if mode != "act":
            return {"status": "deferred", "action": "create", "title": title}
        try:
            url = gh(["issue", "create", "--repo", repo, "--title", title, "--body", body])
            m = re.search(r"/issues/(\d+)\s*$", url or "")
            issue_num = int(m.group(1)) if m else None
            if issue_num is None:
                return {"status": "failed", "action": "create", "title": title, "error": "could not parse issue number from URL"}
            return {"status": "created", "issue": issue_num}
        except Exception as e:
            if getattr(e, "returncode", None) == 75:
                return {"status": "deferred", "action": "create", "title": title}
            if "rate limit" in f"{e} {getattr(e, 'stderr', '') or ''}".lower():
                return {"status": "deferred", "action": "create", "title": title}
            return {"status": "failed", "action": "create", "title": title, "error": str(e)[:200]}


def _gh(args):
    from project_catalog import run_env
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True, timeout=60, env=run_env()).stdout


def run(store_dir: Path | None = None, repo: str = CLARITY_CAPTIONS_REPO, mode: str | None = None,
        gh=_gh, now: datetime | None = None) -> dict:
    """Main job: load summary, detect breaches, file/update tickets.
    Returns {processed: int, created: int, updated: int, failed: int, deferred: int, ...}."""
    store = Path(store_dir or STORE_DIR)
    now = now or datetime.now(timezone.utc)

    cfg = load_config()
    if mode:
        cfg["mode"] = mode
    mode = cfg.get("mode", "propose")

    summary_path = store / "summary.json"
    if not summary_path.exists():
        return {"processed": 0, "created": 0, "updated": 0, "failed": 0, "deferred": 0,
                "breaches": 0, "ok": True, "error": None, "mode": mode}

    try:
        summary = json.loads(summary_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return {"processed": 0, "created": 0, "updated": 0, "failed": 0, "deferred": 0,
                "breaches": 0, "ok": False, "error": str(e)[:200], "mode": mode}

    lock_path = store / ".tickets-lock"
    try:
        lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
    except OSError as e:
        return {"processed": 0, "created": 0, "updated": 0, "failed": 0, "deferred": 0,
                "breaches": 0, "ok": False, "error": f"lock failed: {e}", "mode": mode}

    try:
        with os.fdopen(lock_fd, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)

            breaches = detect_breaches(summary)
            results = {"processed": 0, "created": 0, "updated": 0, "failed": 0, "deferred": 0,
                      "breaches": len(breaches), "ok": True, "error": None, "mode": mode}

            proposals = []
            for i, breach in enumerate(breaches):
                if results["processed"] >= MAX_TICKETS_PER_RUN:
                    results["deferred"] += len(breaches) - i
                    break

                try:
                    outcome = file_or_update(breach, repo, gh, mode=mode)
                    results["processed"] += 1

                    status = outcome["status"]
                    if status == "created":
                        results["created"] += 1
                    elif status == "updated":
                        results["updated"] += 1
                    elif status == "deferred":
                        results["deferred"] += 1
                    elif status == "failed":
                        results["failed"] += 1

                    proposal = {
                        "device": breach["device"],
                        "problem": breach["problem"],
                        "outcome": outcome,
                    }
                    proposals.append(proposal)

                except Exception as e:
                    results["processed"] += 1
                    results["failed"] += 1
                    proposal = {
                        "device": breach["device"],
                        "problem": breach["problem"],
                        "outcome": {"status": "failed", "error": str(e)[:200]},
                    }
                    proposals.append(proposal)

            _write_proposals(proposals, now)

            return results
    except Exception:
        raise


def _write_proposals(proposals: list[dict], now: datetime) -> None:
    """Write proposals log (overwrite, like ticket_agents)."""
    try:
        PROPOSALS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PROPOSALS_PATH.with_stem(PROPOSALS_PATH.stem + ".tmp")
        data = {
            "generated_at": now.isoformat(),
            "proposals": proposals,
        }
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        tmp.replace(PROPOSALS_PATH)
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="detect breaches and file/update tickets")
    r.add_argument("--mode", choices=["propose", "act"], default=None)
    r.add_argument("--repo", default=CLARITY_CAPTIONS_REPO)
    r.add_argument("--store", type=Path, default=None)
    a = ap.parse_args(argv)

    result = run(store_dir=a.store, repo=a.repo, mode=a.mode)
    print(f"seal-beta-tickets: {result['breaches']} breach(es), {result['processed']} processed, "
          f"{result['created']} created, {result['updated']} updated, {result['failed']} failed, "
          f"{result['deferred']} deferred, mode={result['mode']}")

    if not result["ok"]:
        print(f"seal-beta-tickets: error: {result['error']}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
