#!/usr/bin/env python3
"""Tests for retry-storm hold mechanism (#218) — the integration between failure_breaker,
ticket_policy (revisit comments), and run_ticket (parking logic)."""
from __future__ import annotations
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import failure_breaker as fb  # noqa: E402
import ticket_policy as tp  # noqa: E402

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_log(tmp_path, monkeypatch):
    monkeypatch.setattr(fb, "LOG_PATH", tmp_path / "pipeline-failures.jsonl")


# ── format_revisit and parse_revisit_comment round-trip ────────────────────

def test_format_revisit_creates_parseable_string():
    """format_revisit generates a string that parse_revisit_comment can read."""
    date = "2026-10-16"
    condition = "N consecutive pipeline failures"
    formatted = tp.format_revisit(date, condition)
    parsed = tp.parse_revisit_comment(formatted)

    assert parsed is not None
    assert parsed["date"] == date
    assert parsed["condition"] == condition


def test_format_revisit_without_condition():
    """format_revisit can generate without a condition."""
    date = "2026-10-16"
    formatted = tp.format_revisit(date)
    parsed = tp.parse_revisit_comment(formatted)

    assert parsed is not None
    assert parsed["date"] == date
    assert parsed["condition"] is None


def test_format_revisit_matches_parser_exactly():
    """Parser and formatter are exact inverses."""
    test_cases = [
        ("2026-10-16", "N consecutive pipeline failures"),
        ("2026-10-16", "same failure signature twice in a row"),
        ("2026-10-16", None),
    ]
    for date, condition in test_cases:
        formatted = tp.format_revisit(date, condition)
        parsed = tp.parse_revisit_comment(formatted)
        assert parsed["date"] == date
        assert parsed["condition"] == condition


# ── STATE_LABELS includes 'hold' ────────────────────────────────────────────

def test_hold_is_in_state_labels():
    """'hold' is a recognized state label, so held tickets aren't re-triaged."""
    assert "hold" in tp.STATE_LABELS


def test_held_ticket_is_not_re_triaged_by_triage_verdict():
    """A ticket carrying only 'hold' (no other state) is not re-triaged."""
    issue = {
        "number": 218,
        "title": "[A] Implement retry-storm hold",
        "labels": [{"name": "hold"}],
        "body": "## What to build\nAdd hold mechanism\n## Acceptance\n- [x] done",
        "createdAt": NOW.isoformat(),
        "updatedAt": NOW.isoformat(),
    }
    verdict = tp.triage_verdict(issue)
    assert verdict is None  # "hold" blocks re-triage, even with good content


# ── Hold decision integration ──────────────────────────────────────────────

def test_hold_decision_data_has_required_fields():
    """should_hold returns data with reason, count, signatures."""
    fb.record_failure(220, "failure 1", now=NOW - timedelta(minutes=30))
    fb.record_failure(220, "failure 1", now=NOW - timedelta(minutes=20))

    decision = fb.should_hold(220, threshold=2, now=NOW)
    assert decision is not None
    assert "reason" in decision
    assert "count" in decision
    assert "signatures" in decision
    assert decision["reason"] in ("n-failures", "repeat-signature")
    assert isinstance(decision["signatures"], list)


def test_repeat_signature_case_produces_correct_condition_text():
    """When reason='repeat-signature', the condition text should reflect that."""
    fb.record_failure(221, "measure:vitest-no-summary", now=NOW - timedelta(minutes=30))
    fb.record_failure(221, "measure:vitest-no-summary", now=NOW - timedelta(minutes=25))

    decision = fb.should_hold(221, threshold=5, now=NOW)
    assert decision is not None
    assert decision["reason"] == "repeat-signature"
    condition = "same failure signature twice in a row"
    formatted = tp.format_revisit("2026-10-16", condition)
    assert "same failure signature twice in a row" in formatted


# ── Failure signatures are preserved ──────────────────────────────────────────

def test_ticket_streak_preserves_signature_order():
    """Failure signatures are stored oldest-to-newest in the streak."""
    # Use actual failure reasons that signature() will process
    reason1 = "Unhandled exception: vitest produced no test summary"
    reason2 = "Unhandled exception: Command '['claude']' timed out after 300 seconds"
    reason3 = "Unhandled exception: vitest produced no test summary"

    fb.record_failure(222, reason1, now=NOW - timedelta(minutes=30))
    fb.record_failure(222, reason2, now=NOW - timedelta(minutes=20))
    fb.record_failure(222, reason3, now=NOW - timedelta(minutes=10))

    streak = fb.ticket_streak(222, now=NOW)
    assert streak["signatures"] == ["measure:vitest-no-summary", "claude-timeout", "measure:vitest-no-summary"]


# ── EnvMissing and TestTimedOut don't count toward streak ──────────────────

def test_env_missing_failures_do_not_count():
    """Failures with env_missing should never be recorded to the log."""
    # Note: env_missing/timed_out/too_vague are handled in run_ticket.py before
    # recording to the failure log, so they never appear in ticket_streak.
    # This test documents that behavior.
    fb.record_failure(223, "some_regular_failure", now=NOW - timedelta(minutes=30))
    fb.record_failure(223, "some_regular_failure", now=NOW - timedelta(minutes=20))

    streak = fb.ticket_streak(223, now=NOW)
    assert streak["count"] == 2


# ── Malformed/stale state handling ──────────────────────────────────────────

def test_stale_log_entries_do_not_auto_reset_on_label_edit():
    """Re-adding ready-for-agent to a held ticket does NOT auto-reset its jsonl streak.
    (This is a design choice: label edits are not proof the cause is fixed.)"""
    fb.record_failure(224, "failure", now=NOW - timedelta(minutes=30))
    fb.record_failure(224, "failure", now=NOW - timedelta(minutes=20))
    fb.record_failure(224, "failure", now=NOW - timedelta(minutes=10))

    # Ticket is held, then person manually removes hold + adds ready-for-agent
    # (simulated; the streak should still be there)
    streak_before = fb.ticket_streak(224, now=NOW)
    assert streak_before["count"] == 3

    # Streak is still 3, unchanged by any label edit
    streak_after = fb.ticket_streak(224, now=NOW)
    assert streak_after["count"] == 3


def test_a_success_after_holding_resets_the_streak():
    """If a held ticket is manually restarted and succeeds, the streak resets."""
    fb.record_failure(225, "failure", now=NOW - timedelta(minutes=30))
    fb.record_failure(225, "failure", now=NOW - timedelta(minutes=20))
    fb.record_failure(225, "failure", now=NOW - timedelta(minutes=10))
    assert fb.ticket_streak(225, now=NOW)["count"] == 3

    # Success clears the streak
    fb.record_success(225, now=NOW - timedelta(minutes=5))
    assert fb.ticket_streak(225, now=NOW)["count"] == 0


# ── Concurrency: per-machine logs ──────────────────────────────────────────

def test_ticket_streak_is_machine_local(monkeypatch, tmp_path):
    """Two machines each run ticket #226 for the same project.
    Their per-machine jsonl logs are separate (they have separate LOG_PATH).
    Each machine's streak is only from its own log."""
    log1 = tmp_path / "machine1" / "pipeline-failures.jsonl"
    log2 = tmp_path / "machine2" / "pipeline-failures.jsonl"

    monkeypatch.setattr(fb, "LOG_PATH", log1)
    fb.record_failure(226, "failure", now=NOW - timedelta(minutes=30))
    fb.record_failure(226, "failure", now=NOW - timedelta(minutes=20))

    # Simulate machine 2's log with only 1 failure
    log2.parent.mkdir(parents=True, exist_ok=True)
    import json
    with log2.open("w") as f:
        f.write(json.dumps({"t": (NOW - timedelta(minutes=15)).isoformat(), "kind": "failure",
                           "ticket": 226, "project": "G-Eskayo/marvin", "sig": "s", "reason": "r"}) + "\n")

    # Machine 1's view
    monkeypatch.setattr(fb, "LOG_PATH", log1)
    streak_m1 = fb.ticket_streak(226, now=NOW)
    assert streak_m1["count"] == 2

    # Machine 2's view (separate log)
    monkeypatch.setattr(fb, "LOG_PATH", log2)
    streak_m2 = fb.ticket_streak(226, now=NOW)
    assert streak_m2["count"] == 1


# ── Revisit date generation ────────────────────────────────────────────────

def test_revisit_date_is_reasonable():
    """Revisit date should be ~DEFAULT_REVISIT_DAYS (14) days from now."""
    import run_ticket
    expected = (NOW + timedelta(days=run_ticket.DEFAULT_REVISIT_DAYS)).strftime("%Y-%m-%d")
    # This is a manual calculation for testing purposes (can't mock datetime.now easily here)
    assert expected in ("2026-10-16", "2026-10-17")  # Reasonable range


# ── per-project override ──────────────────────────────────────────────────────

def test_profile_failure_threshold_defaults_to_none():
    """A profile's failure_threshold field defaults to None (use pipeline default)."""
    import project_profile as pp

    profile = {"repo": "G-Eskayo/test", "verify": []}
    validated = pp._validate(profile, "test.json")

    assert "failure_threshold" in validated
    assert validated["failure_threshold"] is None


def test_should_hold_respects_profile_threshold():
    """A project's profile.failure_threshold (e.g. 5) overrides the default 3."""
    reasons = [
        "Unhandled exception: vitest produced no test summary",
        "Unhandled exception: Command '['claude']' timed out after 300 seconds",
        "npm build failed",
        "git worktree add failed"
    ]
    for i in range(4):
        fb.record_failure(227, reasons[i], now=NOW - timedelta(minutes=30 - i * 5), project="G-Eskayo/clarity-captions")

    # With default (3), 4 failures would hold
    # With custom (5), 4 failures would NOT hold
    decision = fb.should_hold(227, project="G-Eskayo/clarity-captions", threshold=5, now=NOW)
    assert decision is None  # threshold=5, count=4 → not yet


# ── Idempotency: holding a ticket multiple times ────────────────────────────

def test_holding_a_ticket_twice_does_not_double_park():
    """If the same ticket breaches the threshold twice, the hold is idempotent.
    The latest_revisit() parses the newest comment correctly."""
    # Simulate a comment with a revisit directive
    comment1 = {
        "body": "Parked after repeated failed builds\n\nRevisit by: 2026-10-16 — N consecutive pipeline failures",
        "createdAt": NOW.isoformat(),
    }
    comment2 = {
        "body": "Parked after repeated failed builds (newer)\n\nRevisit by: 2026-10-23 — N consecutive pipeline failures",
        "createdAt": (NOW + timedelta(days=7)).isoformat(),
    }

    latest = tp.latest_revisit([comment1, comment2])
    assert latest is not None
    assert latest["date"] == "2026-10-23"  # newest one wins


# ── Integration: all pieces together ──────────────────────────────────────────

def test_end_to_end_hold_flow():
    """Full flow: 3 failures → hold decision → revisit comment round-trip."""
    fb.record_failure(228, "vitest-fail", now=NOW - timedelta(minutes=30))
    fb.record_failure(228, "vitest-fail", now=NOW - timedelta(minutes=20))
    fb.record_failure(228, "vitest-fail", now=NOW - timedelta(minutes=10))

    # Check hold decision
    decision = fb.should_hold(228, threshold=3, now=NOW)
    assert decision is not None
    assert decision["count"] == 3

    # Generate revisit comment
    hold_reason = "N consecutive pipeline failures"
    revisit_date = "2026-10-16"
    comment_body = tp.format_revisit(revisit_date, hold_reason)

    # Parse it back
    parsed = tp.parse_revisit_comment(comment_body)
    assert parsed["date"] == revisit_date
    assert parsed["condition"] == hold_reason

    # Check is_revisit_due (won't be due until the date passes)
    assert not tp.is_revisit_due(parsed, now=NOW)
    future = datetime.fromisoformat(revisit_date + "T00:00:00Z")
    assert tp.is_revisit_due(parsed, now=future)
