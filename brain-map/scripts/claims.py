#!/usr/bin/env python3
"""
claims.py — verification ledger for claims made on the MARVIN page.

Reads system state (machines, test gates, repo visibility, job health) and
checks whether key claims (it runs on two Macs, it's open source, etc.) are true.
Surfaces them to the dashboard and flags any that fail for human review.

Layer 4 of the living MARVIN page (docs/plans/living-marvin-page-2026-10-08.md);
Layer 2 (#268) and Layer 3 (#269) will be wired in later via flag_for_redraft().
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


CLAIMS = [
    {
        "id": "two-machines",
        "section": "introduction",
        "text": "it runs on two Macs",
        "checker": "check_two_machines",
    },
    {
        "id": "merge-gate",
        "section": "reliability",
        "text": "it proves every change with tests before I see it",
        "checker": "check_merge_gate",
    },
    {
        "id": "repo-public",
        "section": "openness",
        "text": "it's open source",
        "checker": "check_repo_public",
    },
    {
        "id": "jobs-recent",
        "section": "reliability",
        "text": "it keeps working while I'm away",
        "checker": "check_jobs_recent",
    },
]


def check_two_machines(network: dict) -> dict:
    """Checks whether network has two devices registered."""
    devices = network.get("devices") or {}
    count = len(devices)
    if count >= 2:
        return {"ok": True, "detail": f"Two machines registered: {', '.join(sorted(devices.keys()))}"}
    return {"ok": False, "detail": f"Only {count} machine(s) found, need 2"}


def check_merge_gate(stages: list[dict]) -> dict:
    """Checks whether the verifying stage has recently passed."""
    if not stages:
        return {"ok": False, "detail": "No stage events found"}

    verifying_events = [e for e in stages if e.get("stage") == "verifying"]
    if not verifying_events:
        return {"ok": False, "detail": "No verifying stage events found"}

    latest = max(verifying_events, key=lambda e: e.get("timestamp", ""))
    if latest.get("status") == "passed":
        timestamp = latest.get("timestamp")
        try:
            event_time = datetime.fromisoformat(timestamp)
            now = datetime.now(timezone.utc)
            hours_ago = (now - event_time).total_seconds() / 3600
            if hours_ago < 24:
                return {"ok": True, "detail": f"Recent verifying pass ({hours_ago:.1f} hours ago)"}
            return {"ok": False, "detail": f"Last verifying pass was {hours_ago:.1f} hours ago"}
        except (ValueError, TypeError):
            return {"ok": False, "detail": "Could not parse timestamp"}
    return {"ok": False, "detail": f"Last verifying stage status: {latest.get('status', 'unknown')}"}


def check_repo_public(visibility: str | None) -> dict:
    """Checks whether the MARVIN repo is public."""
    if not visibility:
        return {"ok": False, "detail": "Could not determine repo visibility"}
    if visibility.upper() == "PUBLIC":
        return {"ok": True, "detail": "Repository is public"}
    return {"ok": False, "detail": f"Repository is {visibility}"}


def check_jobs_recent(job_runs: list[dict]) -> dict:
    """Checks whether scheduled jobs have run recently."""
    if not job_runs:
        return {"ok": False, "detail": "No job runs recorded"}

    recent_runs = []
    now = datetime.now(timezone.utc)
    for run in job_runs:
        finished = run.get("finished_at")
        if not finished:
            continue
        try:
            finish_time = datetime.fromisoformat(finished)
            hours_ago = (now - finish_time).total_seconds() / 3600
            if hours_ago < 24:
                recent_runs.append((run.get("status", "unknown"), hours_ago))
        except (ValueError, TypeError):
            pass

    if recent_runs:
        statuses = [s for s, _ in recent_runs]
        if all(s == "success" for s in statuses):
            hours = recent_runs[0][1]
            return {"ok": True, "detail": f"Jobs running successfully (last {hours:.1f} hours ago)"}
        failed = sum(1 for s in statuses if s != "success")
        return {"ok": False, "detail": f"{failed}/{len(statuses)} recent job runs failed"}
    return {"ok": False, "detail": "No successful runs in the last 24 hours — most recent run is stale"}


def _read_stage_events() -> list[dict]:
    """Reads the most recent ticket's verifying stage events."""
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib"))
    import ticket_stages  # noqa: E402

    tickets = ticket_stages.list_tracked_tickets()
    if not tickets:
        return []
    recent_ticket = max(tickets)
    return ticket_stages.read_stages(recent_ticket)


def _read_repo_visibility() -> str | None:
    """Queries gh for repo visibility."""
    try:
        p = subprocess.run(
            ["gh", "repo", "view", "G-Eskayo/marvin", "--json", "visibility"],
            capture_output=True, text=True, timeout=30
        )
        if p.returncode == 0:
            data = json.loads(p.stdout)
            return data.get("visibility")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return None


def _read_page_html() -> str:
    """Reads the MARVIN page's HTML content from its longform file."""
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib"))
    import project_catalog  # noqa: E402
    import portfolio_content  # noqa: E402

    try:
        portfolio_path = project_catalog.portfolio_repo_path()
        content_file = Path(portfolio_path) / "content" / "longform" / "marvin.json"
        if content_file.exists():
            content = json.loads(content_file.read_text(encoding="utf-8"))
            return portfolio_content._page_html(content)
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return ""


def _read_job_logs() -> list[dict]:
    """Reads the claims-ledger job's recent runs, or a fallback job if not yet created."""
    jobs_dir = Path.home() / ".claude" / "logs" / "jobs"
    if not jobs_dir.exists():
        return []

    job_name = "claims-ledger-nightly"
    job_file = jobs_dir / f"{job_name}.json"

    if not job_file.exists():
        job_name = "health-check"
        job_file = jobs_dir / f"{job_name}.json"

    if not job_file.exists():
        return []

    try:
        data = json.loads(job_file.read_text())
        runs = data.get("runs", [])
        return sorted(runs, key=lambda r: r.get("finished_at", ""), reverse=True)[:5]
    except (OSError, json.JSONDecodeError):
        return []


def gather(today: str | None = None) -> dict:
    """Reads all system state needed for claim checks."""
    def load(p: Path, default):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    return {
        "network": load(Path.home() / ".claude" / "marvin-network.json", {}),
        "stages": _read_stage_events(),
        "visibility": _read_repo_visibility(),
        "jobs_recent": _read_job_logs(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def collect(gather=None) -> dict:
    """Runs all checkers and returns {claim_id: {ok, detail, section, text, checked_at}}."""
    if gather is None:
        gather = globals()["gather"]

    data = gather()
    checked_at = datetime.now(timezone.utc).isoformat()
    result = {}

    for claim in CLAIMS:
        claim_id = claim["id"]
        checker_name = claim["checker"]
        checker = globals()[checker_name]

        if claim_id == "two-machines":
            check_result = checker(data["network"])
        elif claim_id == "merge-gate":
            check_result = checker(data["stages"])
        elif claim_id == "repo-public":
            check_result = checker(data["visibility"])
        elif claim_id == "jobs-recent":
            check_result = checker(data["jobs_recent"])
        else:
            check_result = {"ok": False, "detail": "Unknown checker"}

        result[claim_id] = {
            "ok": check_result["ok"],
            "detail": check_result["detail"],
            "section": claim["section"],
            "text": claim["text"],
            "checked_at": checked_at,
        }

    return result


def scan_for_unchecked_claims(html: str, claims_list: list[dict] | None = None) -> list[str]:
    """Extract visible text, find numeric claims not in the registered list."""
    if claims_list is None:
        claims_list = CLAIMS

    html = re.sub(r"<(code|pre|script|style)\b.*?</\1>", " ", html or "", flags=re.S | re.I)
    visible = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()

    registered = {claim["text"].lower() for claim in claims_list}

    sentences = re.split(r"[.!?]+", visible)
    unchecked = []

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        lower = sentence.lower()
        if any(registered_text in lower for registered_text in registered):
            continue

        numbers = re.findall(r"\d{2,}", sentence)
        if numbers:
            unchecked.append(sentence)

    return unchecked


def flag_for_redraft(claim: dict) -> str:
    """Indicates that a failing claim needs redrafting (stub for #269)."""
    claim_id = claim["id"]
    section = claim.get("section", "unknown")
    return f"#269: redraft {section} claim ({claim_id})"


if __name__ == "__main__":
    import argparse
    sys.path.insert(0, str(REPO / "lib"))
    import job_events  # noqa: E402

    parser = argparse.ArgumentParser(description="MARVIN claims ledger")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--nightly", action="store_true", help="Nightly job mode (no output, side effects only)")
    args = parser.parse_args()

    data = collect()
    page_html = _read_page_html()

    if args.nightly:
        with job_events.job_run("claims-ledger-nightly", "Claims ledger nightly check") as run:
            ok_count = sum(1 for c in data.values() if c["ok"])
            failed_count = sum(1 for c in data.values() if not c["ok"])
            run.step("Verification", f"{ok_count} ok, {failed_count} failed")
            unchecked = scan_for_unchecked_claims(page_html)
            if unchecked:
                run.step("Unchecked claims", f"{len(unchecked)} found")
            logs_dir = Path.home() / ".claude" / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (logs_dir / "claims-ledger.json").write_text(json.dumps(data, indent=2))
            for claim_id, claim_data in data.items():
                if not claim_data["ok"]:
                    run.step("Flagged for redraft", flag_for_redraft(claim_data))
            run.summary(f"All {len(data)} claims checked")
    elif args.json:
        print(json.dumps({
            "claims": data,
            "unchecked": scan_for_unchecked_claims(page_html),
        }, indent=2))
    else:
        for claim_id, claim_data in data.items():
            status = "✓" if claim_data["ok"] else "✗"
            print(f"{status} {claim_data['text']}: {claim_data['detail']}")
