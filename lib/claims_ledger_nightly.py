#!/usr/bin/env python3
"""Nightly claims ledger check: verify all facts on the MARVIN page are still true.
Runs via launchd com.marvin.claims-ledger-nightly, publishes status to ~/.claude/portfolio/.

Seeds claims from a static registry (decided separately per PR #268/#269), runs all checks,
writes status atomically, and queues redraft requests for sections with failed claims.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parent
sys.path.insert(0, str(LIB))

import claims_ledger as cl
import job_events
import readable_guard

HOME = Path.home()
STATUS_DIR = HOME / ".claude" / "portfolio"
PORTFOLIO_PAGE_URL = "https://gileskayo.me/"


def _load_seed_registry() -> cl.ClaimsRegistry:
    """Load the initial claim registry using Gil's literal claim texts."""
    claims = [
        cl.Claim(
            id="machines-count",
            text="MARVIN runs on two Macs",
            check_fn="check_machine_registry",
            section="story"
        ),
        cl.Claim(
            id="repo-public",
            text="MARVIN is open source",
            check_fn="check_repo_visibility",
            section="story"
        ),
        cl.Claim(
            id="jobs-recent",
            text="MARVIN keeps working while you're away",
            check_fn="check_scheduled_jobs",
            section="story"
        ),
        cl.Claim(
            id="merge-gate-active",
            text="MARVIN proves every change with tests before merge",
            check_fn="check_merge_gate",
            section="story"
        ),
    ]
    return cl.ClaimsRegistry(claims=claims)


@job_events.reported("claims-ledger-nightly", label="Claims Ledger Nightly")
def main():
    """Run all claim checks and publish results."""
    job_events.step("Loading claim registry")
    registry = _load_seed_registry()
    validation_issues = cl.validate_registry(registry)
    if validation_issues:
        for issue in validation_issues:
            job_events.step("Validation error", issue)
        sys.exit(1)
    job_events.step(f"Loaded {len(registry.claims)} claims")

    job_events.step("Running checks")
    results = cl.run_all(registry, claims_args={})
    passed_count = sum(1 for r in results if r.status == "true")
    failed_count = sum(1 for r in results if r.status == "untrue")
    unknown_count = sum(1 for r in results if r.status == "unknown")
    job_events.step(
        "Checks complete",
        f"{passed_count} passed, {failed_count} failed, {unknown_count} unknown"
    )

    job_events.step("Writing status")
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    status_file = STATUS_DIR / "marvin-page-claims.json"
    cl.write_status_atomic(status_file, results)

    job_events.step("Building redraft queue")
    queue_file = STATUS_DIR / "claims-redraft-queue.json"
    redraft_queue = cl.build_redraft_queue(results)

    # Write redraft queue every run (never conditionally unlink)
    queue_data = {
        "checked_at": cl._now().isoformat(),
        "sections": {
            q["section"]: {
                "failed_claims": q["failed_claims"],
                "checked_at": q["checked_at"]
            }
            for q in redraft_queue
        }
    }
    cl._write_json_atomic(queue_file, queue_data)
    if redraft_queue:
        job_events.step("Queued redrafts", f"{len(redraft_queue)} sections need review")
    else:
        job_events.step("No redrafts needed")

    job_events.step("Scanning for unbacked claims")
    try:
        from project_catalog import portfolio_repo_path
        portfolio_path = portfolio_repo_path()
        content_dir = portfolio_path / "content" / "longform"

        if readable_guard.readable_within(content_dir, timeout_secs=5):
            try:
                marvin_file = content_dir / "marvin.json"
                if marvin_file.exists():
                    marvin_content = marvin_file.read_text()
                    unbacked = cl.scan_unbacked_claims(marvin_content, registry)
                    if unbacked:
                        job_events.step(f"Found {len(unbacked)} unbacked claim(s)", ", ".join(unbacked[:2]))
                    else:
                        job_events.step("Unbacked scan complete", "all facts have claims")
            except Exception as e:
                job_events.step("Unbacked scan failed", str(e)[:100])
        else:
            job_events.step("Unbacked scan skipped", "content dir inaccessible (iCloud hang)")
    except Exception as e:
        job_events.step("Unbacked scan error", str(e)[:100])

    job_events.summary(
        f"Checked {len(results)} claims: {passed_count} OK, {failed_count} failed, {unknown_count} unknown"
    )


if __name__ == "__main__":
    main()
