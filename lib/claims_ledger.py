#!/usr/bin/env python3
"""Layer 4: Claims ledger — verify that factual statements on the MARVIN page are still true.
Runs nightly via job_events.reported() decorator; publishes results to ~/.claude/portfolio/
for the dashboard to display on the Portfolio tab.

Each claim is a factual sentence with an associated check function (machine registry, repo visibility,
job recency, merge gate status). The ledger registers all claims, runs all checks nightly, and flags
any section whose claims have failed so it can be redrafted.

Per ADR 0061: facts.json and use-cases.json auto-publish; narrative sections are drafted on
architecture triggers and promoted by Gil. This layer ensures narrative claims stay true, so
redraft triggers fire only when the system state actually changed.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal

HOME = Path.home()
AGENTS_DIR = HOME / ".agents"
JOBS_DIR = HOME / ".claude" / "logs" / "jobs"
MACHINES_FILE = AGENTS_DIR / "config" / "machines.json"
MAIN_HEALTH_PATH = HOME / ".claude" / "logs" / "main-health.json"
STATUS_DIR = HOME / ".claude" / "portfolio"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Claim:
    """A factual statement on the MARVIN page, with a check function to verify it."""
    id: str
    text: str
    check_fn: str
    section: str


@dataclass
class CheckResult:
    """Outcome of running a single claim's check function."""
    claim_id: str
    status: Literal["true", "untrue", "unknown"]  # never collapses unknown into true/false
    detail: str
    checked_at: datetime
    section: str = ""  # populated by run_all() from the claim


@dataclass
class ClaimsRegistry:
    """The set of all claims currently being checked."""
    claims: list[Claim]


def registry_to_json(registry: ClaimsRegistry) -> str:
    """Serialize a registry to JSON."""
    data = {
        "claims": [asdict(c) for c in registry.claims]
    }
    return json.dumps(data, indent=2)


def registry_from_json(json_str: str) -> ClaimsRegistry:
    """Deserialize a registry from JSON."""
    data = json.loads(json_str)
    claims = [Claim(**c) for c in data.get("claims", [])]
    return ClaimsRegistry(claims=claims)


def validate_registry(registry: ClaimsRegistry) -> list[str]:
    """Validate that a registry is well-formed. Returns list of issues found."""
    issues = []
    seen_ids = set()
    check_fns = {
        "check_machine_registry",
        "check_repo_visibility",
        "check_scheduled_jobs",
        "check_merge_gate",
    }
    for claim in registry.claims:
        if claim.id in seen_ids:
            issues.append(f"Duplicate claim ID: {claim.id}")
        seen_ids.add(claim.id)
        if claim.check_fn not in check_fns:
            issues.append(f"Unknown check function for claim {claim.id}: {claim.check_fn}")
    return issues


# ── Individual check functions ──────────────────────────────────────

def check_machine_registry() -> CheckResult:
    """Verify that the machine registry lists at least two machines.
    Reads machine_profile.NETWORK_PATH fresh each call."""
    try:
        from machine_profile import NETWORK_PATH
        data = json.loads(NETWORK_PATH.read_text())
        if not isinstance(data, dict) or "devices" not in data:
            return CheckResult(
                claim_id="machines-registry",
                status="unknown",
                detail=f"marvin-network.json is missing 'devices' key",
                checked_at=_now()
            )
        devices = data.get("devices", {})
        if not isinstance(devices, dict):
            return CheckResult(
                claim_id="machines-registry",
                status="unknown",
                detail=f"devices is not a dict",
                checked_at=_now()
            )
        count = len([k for k, v in devices.items() if v is True])
        if count < 2:
            return CheckResult(
                claim_id="machines-registry",
                status="untrue",
                detail=f"Found {count} machine(s), expected at least 2",
                checked_at=_now()
            )
        return CheckResult(
            claim_id="machines-registry",
            status="true",
            detail=f"{count} machines registered",
            checked_at=_now()
        )
    except FileNotFoundError:
        return CheckResult(
            claim_id="machines-registry",
            status="unknown",
            detail=f"marvin-network.json not found",
            checked_at=_now()
        )
    except Exception as e:
        return CheckResult(
            claim_id="machines-registry",
            status="unknown",
            detail=f"Error reading marvin-network.json: {e}",
            checked_at=_now()
        )


def check_repo_visibility(repo: str = "G-Eskayo/marvin", run: Callable = subprocess.run) -> CheckResult:
    """Verify that the repo is public via GitHub API (injected run callable).
    Missing isPrivate key returns unknown, not default-private."""
    try:
        result = run(
            ["gh", "repo", "view", repo, "--json", "isPrivate"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return CheckResult(
                claim_id="repo-visibility",
                status="unknown",
                detail=f"Failed to query repo: {result.stderr[:100]}",
                checked_at=_now()
            )
        data = json.loads(result.stdout)
        if "isPrivate" not in data:
            return CheckResult(
                claim_id="repo-visibility",
                status="unknown",
                detail=f"isPrivate key missing from response",
                checked_at=_now()
            )
        is_private = data["isPrivate"]
        return CheckResult(
            claim_id="repo-visibility",
            status="true" if not is_private else "untrue",
            detail="Repo is public" if not is_private else "Repo is private",
            checked_at=_now()
        )
    except Exception as e:
        return CheckResult(
            claim_id="repo-visibility",
            status="unknown",
            detail=f"Error checking visibility: {e}",
            checked_at=_now()
        )


def check_scheduled_jobs(
    claim_args: dict | None = None,
    jobs_dir: Path | None = None,
    required_jobs: list[str] | None = None,
    max_age_hours: int = 48
) -> CheckResult:
    """Verify that scheduled jobs have run recently using job_events.status_of().
    Looks at prior run when newest is still running; checks for failed/crashed.
    Stale-checks finished_at timestamp (normalizing naive datetimes to UTC)."""
    claim_args = claim_args or {}
    jobs_dir = jobs_dir or JOBS_DIR
    max_age_hours = claim_args.get("max_age_hours", max_age_hours)
    required_jobs = required_jobs or ["snapshot-deploy-nightly"]

    try:
        import job_events

        failed = []
        stale = []
        for job_name in required_jobs:
            job_file = jobs_dir / f"{job_name}.json"
            if not job_file.exists():
                failed.append(f"{job_name} (not found)")
                continue
            data = json.loads(job_file.read_text())
            status = job_events.status_of(data)

            # "never" and "failed" and "crashed" all mean untrue
            if status == "never":
                failed.append(f"{job_name} (never run)")
                continue
            if status in ("failed", "crashed"):
                failed.append(f"{job_name} ({status})")
                continue

            # "running": check the prior run for staleness
            if status == "running":
                runs = data.get("runs", [])
                if len(runs) < 2:
                    failed.append(f"{job_name} (only running run exists)")
                    continue
                run_to_check = runs[-2]
            else:
                # "idle": check the last run
                runs = data.get("runs", [])
                if not runs:
                    failed.append(f"{job_name} (no runs)")
                    continue
                run_to_check = runs[-1]

            finished_at_str = run_to_check.get("finished_at")
            if not finished_at_str:
                failed.append(f"{job_name} (no finished_at)")
                continue

            # Normalize naive timestamps to UTC if needed
            try:
                finished_at = datetime.fromisoformat(finished_at_str)
                if finished_at.tzinfo is None:
                    finished_at = finished_at.replace(tzinfo=timezone.utc)
            except ValueError:
                failed.append(f"{job_name} (bad timestamp)")
                continue

            age = _now() - finished_at
            if age > timedelta(hours=max_age_hours):
                stale.append(f"{job_name} ({int(age.total_seconds() / 3600)}h old)")

        # Report issues
        all_issues = failed + stale
        if all_issues:
            return CheckResult(
                claim_id="scheduled-jobs",
                status="untrue",
                detail=", ".join(all_issues),
                checked_at=_now()
            )
        return CheckResult(
            claim_id="scheduled-jobs",
            status="true",
            detail=f"{len(required_jobs)} job(s) recent and healthy",
            checked_at=_now()
        )
    except Exception as e:
        return CheckResult(
            claim_id="scheduled-jobs",
            status="unknown",
            detail=f"Error checking jobs: {e}",
            checked_at=_now()
        )


def check_merge_gate(path: Path | None = None, now: datetime | None = None, stale_hours: int = 24) -> CheckResult:
    """Verify merge gate: reads ok/failed/checked_at/sha/summary from main-health.json.
    Reports untrue if ok is false, or if checked_at is stale."""
    path = path or MAIN_HEALTH_PATH
    try:
        if not path.exists():
            return CheckResult(
                claim_id="merge-gate",
                status="unknown",
                detail=f"main-health.json not found",
                checked_at=_now()
            )
        data = json.loads(path.read_text())

        # Check if ok is false
        if data.get("ok") is False:
            failed_tests = data.get("failed", [])
            failed_str = ", ".join(failed_tests[:3]) if failed_tests else "tests failed"
            return CheckResult(
                claim_id="merge-gate",
                status="untrue",
                detail=f"Merge gate failed: {failed_str}",
                checked_at=_now()
            )

        # Check staleness of checked_at
        checked_at_str = data.get("checked_at")
        if checked_at_str:
            try:
                checked_at = datetime.fromisoformat(checked_at_str)
                if checked_at.tzinfo is None:
                    checked_at = checked_at.replace(tzinfo=timezone.utc)
                age = (now or _now()) - checked_at
                if age > timedelta(hours=stale_hours):
                    return CheckResult(
                        claim_id="merge-gate",
                        status="untrue",
                        detail=f"Merge gate check is stale ({int(age.total_seconds() / 3600)}h old)",
                        checked_at=_now()
                    )
            except ValueError:
                pass  # ignore bad timestamp, fall through to "true" if ok is true

        # ok is true and fresh
        if data.get("ok") is True:
            return CheckResult(
                claim_id="merge-gate",
                status="true",
                detail="Merge gate is healthy",
                checked_at=_now()
            )

        # ok is missing or unclear
        return CheckResult(
            claim_id="merge-gate",
            status="unknown",
            detail="Merge gate status unclear (ok field missing)",
            checked_at=_now()
        )
    except Exception as e:
        return CheckResult(
            claim_id="merge-gate",
            status="unknown",
            detail=f"Error checking merge gate: {e}",
            checked_at=_now()
        )


# ── Orchestrator ────────────────────────────────────────────────────

def run_all(
    registry: ClaimsRegistry,
    claims_args: dict[str, dict] | None = None,
    status_dir: Path | None = None
) -> list[CheckResult]:
    """Run all checks for all claims in the registry. Returns list of CheckResult.
    Does not create status_dir."""
    claims_args = claims_args or {}
    check_funcs: dict[str, Callable] = {
        "check_machine_registry": check_machine_registry,
        "check_repo_visibility": check_repo_visibility,
        "check_scheduled_jobs": check_scheduled_jobs,
        "check_merge_gate": check_merge_gate,
    }
    results = []
    for claim in registry.claims:
        check_fn = check_funcs.get(claim.check_fn)
        if not check_fn:
            results.append(CheckResult(
                claim_id=claim.id,
                status="unknown",
                detail=f"Unknown check function: {claim.check_fn}",
                checked_at=_now(),
                section=claim.section
            ))
            continue
        try:
            # Get per-claim kwargs, pass as kwargs to the check function
            kwargs = claims_args.get(claim.id, {})
            result = check_fn(**kwargs)
            result.claim_id = claim.id
            result.section = claim.section
            results.append(result)
        except Exception as e:
            results.append(CheckResult(
                claim_id=claim.id,
                status="unknown",
                detail=f"Exception: {e}",
                checked_at=_now(),
                section=claim.section
            ))
    return results


# ── Output ──────────────────────────────────────────────────────────

def _write_json_atomic(path: Path, data: Any) -> None:
    """Write JSON atomically using fcntl.flock on a sibling .lock file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = path.with_suffix(".lock")
    tmp_file = path.with_suffix(".tmp")

    with open(lock_file, "a") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            tmp_file.write_text(json.dumps(data, indent=2) + "\n")
            tmp_file.replace(path)
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def write_status_atomic(status_file: Path, results: list[CheckResult]) -> None:
    """Write status results atomically."""
    data = {
        "checked_at": _now().isoformat(),
        "results": [
            {
                "claim_id": r.claim_id,
                "status": r.status,
                "detail": r.detail,
                "checked_at": r.checked_at.isoformat(),
                "section": r.section,
            }
            for r in results
        ]
    }
    _write_json_atomic(status_file, data)


def build_redraft_queue(results: list[CheckResult]) -> list[dict[str, Any]]:
    """Build a queue of sections that need redrafting due to failed claims.
    Recomputed from scratch every run, never includes 'unknown' status.
    One entry per section with failing claims (status == "untrue")."""

    # Group failed claims by section (only "untrue", not "unknown")
    failed_by_section = {}
    for r in results:
        if r.status == "untrue":
            if r.section not in failed_by_section:
                failed_by_section[r.section] = []
            failed_by_section[r.section].append(r.claim_id)

    # Build queue: one entry per section with failures
    queue = []
    for section, failed_claims in failed_by_section.items():
        queue.append({
            "section": section,
            "failed_claims": failed_claims,
            "checked_at": _now().isoformat()
        })

    return queue


# ── Unbacked claims scanner ────────────────────────────────────────

def scan_unbacked_claims(page_text: str, registry: ClaimsRegistry) -> list[str]:
    """Find factual sentences in page_text that aren't covered by a claim in the registry.
    Uses word-boundary regex to avoid false positives like 'two' in 'network'.
    Strips HTML via portfolio_content._visible_text if available.
    Keyword patterns include inflections (runs, ran, running, etc.)."""
    try:
        from portfolio_content import _visible_text
        visible = _visible_text(page_text)
    except ImportError:
        visible = page_text

    backed_texts = {c.text.lower() for c in registry.claims}
    unbacked = []
    sentences = re.split(r'[.!?]\s+', visible)

    for sentence in sentences:
        sentence_lower = sentence.lower().strip()
        if not sentence_lower:
            continue

        # Check if any backed text appears as a word boundary match
        is_backed = False
        for backed_text in backed_texts:
            # Use word boundaries to avoid "two" in "network"
            pattern = r'\b' + re.escape(backed_text) + r'\b'
            if re.search(pattern, sentence_lower, re.IGNORECASE):
                is_backed = True
                break

        if not is_backed:
            # Look for keywords that suggest a fact, with inflection patterns
            keywords = [
                r'\brun(s|ning|n|ned)?\b',
                r'\bprove(s|n)?\b',
                r'\bwork(s|ing)?\b',
                r'\bcheck(s|ed|ing)?\b',
                r'\btest(s|ed|ing|ing)?\b',
                r'\bopen\b',
                r'\btwo\b',
                r'\bmacs?\b',
                r'\bmachines?\b',
            ]
            if any(re.search(kw, sentence_lower) for kw in keywords):
                unbacked.append(sentence.strip())

    return unbacked
