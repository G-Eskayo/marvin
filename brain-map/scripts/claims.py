#!/usr/bin/env python3
"""Claims ledger: track portfolio facts over time, verifiable against job events, ticket stages, and content.

A claim is a structured fact about the MARVIN system that can be checked repeatedly: "the portfolio page
X links to MARVIN" (portfolio_content), "the daily digest runs successfully" (job_events), "ticket #281
reached 'done'" (ticket_stages). Each claim has a check function and a gather_key identifying where its
evidence comes from.

Collect all claims into a timestamped report:
    claims.py --json  # output JSON, run all claims against current state
    claims.py --nightly  # run via job_events.job_run(), intended for launchd

Designed per ADR 0065.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "lib"))

import job_events  # noqa: E402
import portfolio_content as pc  # noqa: E402
import ticket_stages  # noqa: E402

LOGS_DIR = Path.home() / ".claude" / "logs"
CLAIMS_LEDGER = LOGS_DIR / "claims-ledger.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _result(pass_: bool, detail: str = "") -> dict:
    """Structured result from a check: { pass: bool, detail: str, timestamp: str }."""
    return {"pass": pass_, "detail": detail, "timestamp": _now()}


# ── Check functions: portfolio_content ──

def _read_page_html(portfolio: dict) -> str:
    """Extract visible HTML from portfolio content pages for scanning."""
    if not portfolio:
        return ""
    pages = portfolio.get("pages", {})
    html_parts = []
    for page in pages.values():
        html_parts.append(pc._page_html(page))
    return "".join(html_parts)


def check_marvin_link(portfolio: dict, job_events_: dict | None, ticket_stages_: dict | None) -> dict:
    """Portfolio pages built with MARVIN link back to the MARVIN page."""
    try:
        pages = portfolio.get("pages", {})
        marvin_url = "/ai-projects/marvin/"
        built_with_marvin = [
            slug for slug, page in pages.items()
            if slug != "marvin" and page.get("built_with_marvin")
        ]

        issues = []
        for slug in built_with_marvin:
            page = pages[slug]
            # Reuse portfolio_content.py's own marvin-link-missing finding to detect pages missing links
            findings = page.get("findings", [])
            if any(f.get("rule") == "marvin-link-missing" for f in findings):
                issues.append(f"{slug} missing link to MARVIN")

        if not issues:
            return _result(True, f"{len(built_with_marvin)} pages built with MARVIN, all link back")
        else:
            return _result(False, "; ".join(issues))
    except Exception as e:
        return _result(False, f"check failed: {e}")


def check_portfolio_coverage(portfolio: dict, job_events_: dict | None, ticket_stages_: dict | None) -> dict:
    """All portfolio pages meet their template's section and evidence requirements."""
    try:
        pages = portfolio.get("pages", {})
        issues = []

        for slug, page in pages.items():
            coverage = page.get("coverage")
            if coverage is None:
                continue  # Manifest pages without content are allowed

            missing_roles = coverage.get("missing_roles", [])
            missing_evidence = coverage.get("missing_evidence", [])

            if missing_roles:
                issues.append(f"{slug}: missing sections {missing_roles}")
            if missing_evidence:
                for me in missing_evidence:
                    issues.append(f"{slug}/{me['role']}: missing {me['evidence']}")

        if not issues:
            return _result(True, f"all {len(pages)} pages meet template requirements")
        else:
            return _result(False, "; ".join(issues[:3]))  # Limit to first 3 for readability
    except Exception as e:
        return _result(False, f"check failed: {e}")


def check_portfolio_copy(portfolio: dict, job_events_: dict | None, ticket_stages_: dict | None) -> dict:
    """Portfolio pages don't have AI writing indicators (em-dashes, generic phrases)."""
    try:
        pages = portfolio.get("pages", {})
        issues = []

        for slug, page in pages.items():
            findings = page.get("findings", [])
            copy_issues = [f for f in findings if f.get("rule", "").startswith("copy-")]
            if copy_issues:
                issues.append(f"{slug}: {len(copy_issues)} writing issues")

        if not issues:
            return _result(True, f"all {len(pages)} pages pass copy check")
        else:
            return _result(False, "; ".join(issues[:3]))
    except Exception as e:
        return _result(False, f"check failed: {e}")


# ── Check functions: job_events ──

def check_daily_digest_health(portfolio: dict | None, job_events_: dict, ticket_stages_: dict | None) -> dict:
    """The daily-digest job's last run passed."""
    try:
        job_log = job_events_.get("daily-digest", {})
        runs = job_log.get("runs", [])

        if not runs:
            return _result(False, "daily-digest never ran")

        last_run = runs[-1]
        status = last_run.get("status")

        if status == "passed":
            summary = last_run.get("summary", "")
            return _result(True, f"last run passed: {summary}")
        else:
            error = last_run.get("error", "unknown error")
            return _result(False, f"last run {status}: {error}")
    except Exception as e:
        return _result(False, f"check failed: {e}")


def check_research_colony_health(portfolio: dict | None, job_events_: dict, ticket_stages_: dict | None) -> dict:
    """The research-colony job's last run passed."""
    try:
        job_log = job_events_.get("research-colony", {})
        runs = job_log.get("runs", [])

        if not runs:
            return _result(False, "research-colony never ran")

        last_run = runs[-1]
        status = last_run.get("status")

        if status == "passed":
            summary = last_run.get("summary", "")
            return _result(True, f"last run passed: {summary}")
        else:
            error = last_run.get("error", "unknown error")
            return _result(False, f"last run {status}: {error}")
    except Exception as e:
        return _result(False, f"check failed: {e}")


# ── Check functions: ticket_stages ──

def check_claim_ticket_done(portfolio: dict | None, job_events_: dict | None, ticket_stages_: dict) -> dict:
    """This ticket (#281: Claims ledger implementation) reached 'done' stage."""
    try:
        # Look for ticket 281 (this ticket) using parse_stage_key for proper matching
        key = None
        for k in ticket_stages_.keys():
            parsed = ticket_stages.parse_stage_key(k)
            if parsed and parsed[1] == 281 and parsed[0].lower() == ticket_stages.MARVIN_REPO.lower():
                key = k
                break

        if not key:
            return _result(False, "ticket #281 not found in stages")

        stages = ticket_stages_[key].get("stages", [])
        if not stages:
            return _result(False, "ticket #281 has no stage history")

        # Check if last stage is 'done'
        last_stage = stages[-1]
        if last_stage.get("stage") == "done":
            title = last_stage.get("title", "Claims ledger")
            return _result(True, f"ticket #281 ({title}) completed")
        else:
            current_stage = last_stage.get("stage")
            return _result(False, f"ticket #281 still in '{current_stage}' stage")
    except Exception as e:
        return _result(False, f"check failed: {e}")


def check_no_failed_stages(portfolio: dict | None, job_events_: dict | None, ticket_stages_: dict) -> dict:
    """No tickets in the current batch have failed at their latest stage."""
    try:
        failed_tickets = []
        for ticket_key, ticket_data in ticket_stages_.items():
            stages = ticket_data.get("stages", [])
            if stages:
                # Only check the latest stage for each ticket
                latest_stage = stages[-1]
                if latest_stage.get("status") == "failed":
                    failed_tickets.append(ticket_key)

        if not failed_tickets:
            return _result(True, f"{len(ticket_stages_)} tickets tracked, none failed")
        else:
            return _result(False, f"{len(failed_tickets)} tickets with failed latest stage")
    except Exception as e:
        return _result(False, f"check failed: {e}")


# ── CLAIMS ledger: each claim with its check function and evidence source ──

CLAIMS = [
    # Portfolio content checks
    {"name": "portfolio-marvin-link", "gather_key": "portfolio_content", "check": check_marvin_link},
    {"name": "portfolio-coverage", "gather_key": "portfolio_content", "check": check_portfolio_coverage},
    {"name": "portfolio-copy-quality", "gather_key": "portfolio_content", "check": check_portfolio_copy},

    # Job events checks
    {"name": "daily-digest-health", "gather_key": "job_events", "check": check_daily_digest_health},
    {"name": "research-colony-health", "gather_key": "job_events", "check": check_research_colony_health},

    # Ticket stages checks
    {"name": "claim-ticket-281-done", "gather_key": "ticket_stages", "check": check_claim_ticket_done},
    {"name": "no-failed-pipeline-stages", "gather_key": "ticket_stages", "check": check_no_failed_stages},
]


# ── Scanning for unchecked claims in text ──

def scan_for_unchecked_claims(text: str) -> list[str]:
    """Find bare ticket numbers (#123) in visible text that aren't in CLAIMS yet.

    Excludes ADR ##123 and PR ##123 patterns (word-boundary matched).
    Returns list of ticket identifiers like 'marvin-281' that appear but aren't claimed.
    """
    if not text:
        return []

    # Extract visible text (remove HTML tags and code blocks)
    visible = pc._visible_text(text)

    # Find all #123 patterns using word boundaries, but not preceded by ADR or PR
    # Pattern: negative lookbehind for word chars, optional prefix (ADR or PR), then #number, then word boundary
    unchecked_set = set()
    for match in re.finditer(r"(?<!\w)(ADR|PR)?\s*#(\d+)\b", visible, re.IGNORECASE):
        prefix = match.group(1)
        ticket_num = match.group(2)
        # Skip ADR and PR references
        if prefix and prefix.upper() in ("ADR", "PR"):
            continue
        unchecked_set.add(f"marvin-{ticket_num}")

    # Filter to only those not already in CLAIMS
    claimed_tickets = set()
    for claim in CLAIMS:
        if "ticket" in claim["name"].lower():
            # Extract ticket number from claim name
            match = re.search(r"\d+", claim["name"])
            if match:
                claimed_tickets.add(f"marvin-{match.group()}")

    return list(unchecked_set - claimed_tickets)


# ── Gather functions: collect evidence from each source ──

def _gather_portfolio() -> dict | None:
    """Load or compute portfolio_content data."""
    try:
        return pc.evaluate()
    except Exception:
        return None


def _gather_job_events() -> dict | None:
    """Load job_events data from job_events.JOBS_DIR."""
    try:
        jobs_dir = job_events.JOBS_DIR
        if not jobs_dir.exists():
            return {}

        result = {}
        for job_file in jobs_dir.glob("*.json"):
            try:
                result[job_file.stem] = json.loads(job_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return result
    except Exception:
        return None


def _gather_ticket_stages() -> dict | None:
    """Load ticket_stages data from ticket_stages.STAGES_DIR."""
    try:
        stages_dir = ticket_stages.STAGES_DIR
        if not stages_dir.exists():
            return {}

        result = {}
        for stage_file in stages_dir.glob("*.json"):
            try:
                stages_data = json.loads(stage_file.read_text())
                result[stage_file.stem] = {"stages": stages_data}
            except (json.JSONDecodeError, OSError):
                pass
        return result
    except Exception:
        return None


def collect(gather: str | None = None) -> dict:
    """Collect all claims into a timestamped report, optionally filtering by gather_key.

    Args:
        gather: None (all sources), or "portfolio_content", "job_events", "ticket_stages"

    Returns:
        {
            "timestamp": ISO timestamp,
            "claims": [
                {"name": "...", "gather_key": "...", "pass": bool, "detail": "...", "timestamp": "..."},
                ...
            ],
            "unregistered": [list of ticket identifiers found in portfolio but not in CLAIMS]
        }
    """
    report = {
        "timestamp": _now(),
        "claims": []
    }

    # Gather evidence from all sources
    portfolio = _gather_portfolio()
    job_events_data = _gather_job_events()
    ticket_stages_data = _gather_ticket_stages()

    # Run all claims, filtering by gather_key if specified
    for claim in CLAIMS:
        if gather and claim["gather_key"] != gather:
            continue

        # Call the check function with the appropriate data
        if claim["gather_key"] == "portfolio_content":
            result = claim["check"](portfolio, None, None)
        elif claim["gather_key"] == "job_events":
            result = claim["check"](None, job_events_data, None)
        else:  # ticket_stages
            result = claim["check"](None, None, ticket_stages_data)

        # Ensure result is a dict
        if not isinstance(result, dict):
            result = _result(bool(result))

        report["claims"].append({
            "name": claim["name"],
            "gather_key": claim["gather_key"],
            **result
        })

    # Scan portfolio content for unregistered claims (bare ticket numbers)
    if portfolio:
        page_html = _read_page_html(portfolio)
        unregistered = scan_for_unchecked_claims(page_html)
        if unregistered:
            report["unregistered"] = unregistered

    return report


# ── CLI ──

def main() -> None:
    """Run claims collection and output results."""
    nightly = "--nightly" in sys.argv
    json_output = "--json" in sys.argv

    if nightly:
        # Run under job_events.job_run() for dashboard visibility
        with job_events.job_run("claims-ledger-nightly") as run:
            report = collect(gather=None)
            run.step("Claims scanned", f"{len(report['claims'])} checked")

            passed = sum(1 for c in report["claims"] if c.get("pass"))
            failed = len(report["claims"]) - passed
            run.summary(f"{passed} passed, {failed} failed")

            # Write the report atomically
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            tmp_path = CLAIMS_LEDGER.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(report, indent=2))
            tmp_path.replace(CLAIMS_LEDGER)
    else:
        report = collect(gather=None)

        if json_output:
            print(json.dumps(report, indent=2))
        else:
            for claim in report["claims"]:
                status = "✓" if claim.get("pass") else "✗"
                print(f"{status} {claim['name']}: {claim.get('detail', '')}")


if __name__ == "__main__":
    main()
