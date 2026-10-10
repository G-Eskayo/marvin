"""Cross-ticket circuit breaker for the ticket pipeline.

Found 2026-10-01: the 3-strike guard is per-ticket, so a SYSTEMIC failure (a broken
environment, not a bad ticket) failed every ticket in the queue in sequence, each
burning its own strikes, and nothing noticed -- the Activity tab showed the cascade
but no automated consumer reacted to it. Every systemic bug that day was found by
hand. The breaker recognises "the same failure across DIFFERENT tickets" and stops
dispatch.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import failure_breaker as fb  # noqa: E402

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_log(tmp_path, monkeypatch):
    monkeypatch.setattr(fb, "LOG_PATH", tmp_path / "pipeline-failures.jsonl")


def _fail(ticket, reason, minutes_ago=5):
    fb.record_failure(ticket, reason, now=NOW - timedelta(minutes=minutes_ago))


VITEST = "Unhandled exception: vitest produced no test summary (crashed or never ran): ...vite-node/dist/server.mjs:504:17"


# ── signature: collapse the many spellings of one failure ──────────────────

@pytest.mark.parametrize("reason,expected", [
    (VITEST, "measure:vitest-no-summary"),
    ("Unhandled exception: pytest produced no test summary (crashed or never ran): OSError", "measure:pytest-no-summary"),
    ("Did not reach a passing comparison after 3 iterations (max_iterations). Final verdict: unchanged.", "verdict:unchanged"),
    ("Did not reach a passing comparison after 3 iterations (max_iterations). Final verdict: regressed.", "verdict:regressed"),
    ("Unhandled exception: Command '['claude', '-p', 'x', '--model', 'm']' timed out after 300 seconds", "claude-timeout"),
    ("Unhandled exception: Command '['npm', 'run', 'build']' returned non-zero exit status 1.", "npm-build-failed"),
    ("Unhandled exception: [Errno 2] No such file or directory: 'claude'", "claude-not-found"),
    ("Unhandled exception: Command '['git', 'worktree', 'add', '-b', 'x']' returned non-zero exit status 128.", "git-worktree-add-failed"),
])
def test_signature_collapses_known_failures(reason, expected):
    assert fb.signature(reason) == expected


def test_signature_of_an_unknown_failure_ignores_digits_and_paths_so_it_still_groups():
    a = fb.signature("Unhandled exception: weird thing at /Users/x/wt-12/file.py line 41")
    b = fb.signature("Unhandled exception: weird thing at /Users/x/wt-99/file.py line 77")
    assert a == b


# ── tripping ────────────────────────────────────────────────────────────────

def test_same_failure_across_three_different_tickets_trips_the_breaker():
    for t in (32, 35, 37):
        _fail(t, VITEST)
    [trip] = fb.tripped(now=NOW)
    assert trip["signature"] == "measure:vitest-no-summary"
    assert sorted(trip["tickets"]) == [32, 35, 37]


def test_two_tickets_is_not_enough():
    for t in (32, 35):
        _fail(t, VITEST)
    assert fb.tripped(now=NOW) == []


def test_one_ticket_failing_repeatedly_does_not_trip_it_that_is_the_per_ticket_guards_job():
    for _ in range(6):
        _fail(94, VITEST)
    assert fb.tripped(now=NOW) == []


def test_different_failures_do_not_pool_into_one_trip():
    _fail(1, VITEST); _fail(2, "Did not reach a passing comparison ... Final verdict: unchanged."); _fail(3, "Unhandled exception: Command '['claude', '-p']' timed out after 300 seconds")
    assert fb.tripped(now=NOW) == []


def test_failures_older_than_the_window_do_not_count():
    for t in (32, 35, 37):
        _fail(t, VITEST, minutes_ago=60 * 5)
    assert fb.tripped(now=NOW) == []


def test_any_success_after_the_failures_clears_the_breaker():
    for t in (32, 35, 37):
        _fail(t, VITEST, minutes_ago=30)
    fb.record_success(41, now=NOW - timedelta(minutes=10))
    assert fb.tripped(now=NOW) == []


def test_a_success_BEFORE_the_failures_does_not_clear_it():
    fb.record_success(41, now=NOW - timedelta(minutes=50))
    for t in (32, 35, 37):
        _fail(t, VITEST, minutes_ago=30)
    assert len(fb.tripped(now=NOW)) == 1


def test_manual_clear_resets_it_and_new_failures_can_trip_it_again():
    for t in (32, 35, 37):
        _fail(t, VITEST, minutes_ago=30)
    fb.clear(now=NOW - timedelta(minutes=20))
    assert fb.tripped(now=NOW) == []
    for t in (40, 41, 42):
        _fail(t, VITEST, minutes_ago=5)
    assert len(fb.tripped(now=NOW)) == 1


def test_a_corrupt_log_line_never_crashes_the_breaker():
    fb.LOG_PATH.write_text("not json\n")
    for t in (32, 35, 37):
        _fail(t, VITEST)
    assert len(fb.tripped(now=NOW)) == 1


def test_a_failure_line_written_by_the_node_webhook_is_read_and_grouped():
    # dashboard/webhook-server/failure_log.js writes approve/merge failures into this
    # same log. Cross-language contract: an ISO time with a trailing 'Z' (JS
    # toISOString), kind "failure", an int ticket, and a "merge:<CODE>" signature.
    import json
    lines = [json.dumps({"t": (NOW - timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                         "kind": "failure", "ticket": t, "sig": "merge:GH_AUTH_INVALID",
                         "reason": "GH_AUTH_INVALID: Bad credentials"})
             for m, t in ((9, 123), (6, 124), (3, 125))]
    fb.LOG_PATH.write_text("\n".join(lines) + "\n")
    [trip] = fb.tripped(now=NOW)
    assert trip["signature"] == "merge:GH_AUTH_INVALID"
    assert sorted(trip["tickets"]) == [123, 124, 125]


# ── one project's broken environment must not pause the others ──────────────

def test_the_same_failure_in_three_tickets_of_one_other_project_trips_only_that_project(monkeypatch, tmp_path):
    monkeypatch.setattr(fb, "LOG_PATH", tmp_path / "f.jsonl")
    for n in (7, 11, 17):
        fb.record_failure(n, "swift test: no such module 'XCTest'", project="G-Eskayo/clarity-captions")
    trips = fb.tripped()
    assert [t["project"] for t in trips] == ["G-Eskayo/clarity-captions"]
    assert fb.tripped(project="G-Eskayo/marvin") == []
    assert len(fb.tripped(project="G-Eskayo/clarity-captions")) == 1


def test_ticket_7_in_two_projects_counts_as_two_tickets_not_one(monkeypatch, tmp_path):
    monkeypatch.setattr(fb, "LOG_PATH", tmp_path / "f.jsonl")
    fb.record_failure(7, "boom the same way", project="G-Eskayo/marvin")
    fb.record_failure(7, "boom the same way", project="G-Eskayo/clarity-captions")
    fb.record_failure(8, "boom the same way", project="G-Eskayo/marvin")
    fb.record_failure(9, "boom the same way", project="G-Eskayo/marvin")
    assert [t["project"] for t in fb.tripped()] == ["G-Eskayo/marvin"]  # marvin has 3 distinct, clarity only 1


def test_a_success_in_one_project_does_not_clear_another_projects_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(fb, "LOG_PATH", tmp_path / "f.jsonl")
    for n in (1, 2, 3):
        fb.record_failure(n, "xcode exploded", project="G-Eskayo/clarity-captions")
    fb.record_success(99, project="G-Eskayo/marvin")
    assert len(fb.tripped(project="G-Eskayo/clarity-captions")) == 1
    fb.record_success(4, project="G-Eskayo/clarity-captions")
    assert fb.tripped(project="G-Eskayo/clarity-captions") == []


def test_old_log_lines_without_a_project_are_marvins(monkeypatch, tmp_path):
    p = tmp_path / "f.jsonl"
    monkeypatch.setattr(fb, "LOG_PATH", p)
    import json as _j
    now = fb._now().isoformat()
    p.write_text("\n".join(_j.dumps({"t": now, "kind": "failure", "ticket": n, "sig": "s", "reason": "r"}) for n in (1, 2, 3)) + "\n")
    assert [t["project"] for t in fb.tripped()] == ["G-Eskayo/marvin"]


def test_a_manual_clear_resets_every_projects_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(fb, "LOG_PATH", tmp_path / "f.jsonl")
    for n in (1, 2, 3):
        fb.record_failure(n, "xcode exploded", project="G-Eskayo/clarity-captions")
    assert fb.tripped()
    fb.clear()
    assert fb.tripped() == []


def test_merge_refusals_never_trip_the_breaker(tmp_path, monkeypatch):
    # #215: the dashboard records refused Approve clicks (wrong order, sent back) as kind "refusal". Three of them
    # on different tickets are the review screen doing its job, not a broken environment.
    log = tmp_path / "f.jsonl"
    monkeypatch.setattr(fb, "LOG_PATH", log)
    now = fb._now()
    with log.open("w") as f:
        for ticket in (208, 209, 210):
            f.write(json.dumps({"t": now.isoformat(), "kind": "refusal", "ticket": ticket, "sig": "merge:OUT_OF_ORDER"}) + "\n")
    assert fb.tripped(now=now) == []


# ── ticket streak (per-ticket failure counter) ──────────────────────────────

def test_ticket_streak_counts_trailing_failures_for_one_ticket():
    """N mixed failures → streak N with distinct signatures."""
    for i in range(3):
        _fail(95, VITEST if i < 2 else "other failure", minutes_ago=30 - i * 5)

    streak = fb.ticket_streak(95, now=NOW)
    assert streak["count"] == 3
    assert len(streak["signatures"]) == 3
    assert streak["signatures"][0] == "measure:vitest-no-summary"  # oldest first


def test_ticket_streak_resets_on_success():
    """A success in between resets the count."""
    _fail(96, VITEST, minutes_ago=30)
    _fail(96, VITEST, minutes_ago=25)
    fb.record_success(96, now=NOW - timedelta(minutes=20))
    _fail(96, VITEST, minutes_ago=15)
    _fail(96, VITEST, minutes_ago=10)

    streak = fb.ticket_streak(96, now=NOW)
    assert streak["count"] == 2  # only the failures after the success


def test_ticket_streak_empty_for_new_ticket():
    """No log entries → streak 0."""
    streak = fb.ticket_streak(9999, now=NOW)
    assert streak["count"] == 0
    assert streak["signatures"] == []


def test_ticket_streak_ignores_corrupt_lines():
    """Bad/malformed lines in the log must never crash the streak count."""
    fb.LOG_PATH.write_text("not json\n")
    _fail(97, VITEST)
    _fail(97, VITEST)

    streak = fb.ticket_streak(97, now=NOW)
    assert streak["count"] == 2


def test_ticket_streak_two_different_tickets_are_separate():
    """ticket_7 failing in marvin and ticket_7 failing in another project count as two."""
    _fail(7, VITEST, minutes_ago=10)
    fb.record_failure(7, VITEST, project="G-Eskayo/clarity-captions", now=NOW - timedelta(minutes=5))

    streak_marvin = fb.ticket_streak(7, project="G-Eskayo/marvin", now=NOW)
    streak_clarity = fb.ticket_streak(7, project="G-Eskayo/clarity-captions", now=NOW)
    assert streak_marvin["count"] == 1
    assert streak_clarity["count"] == 1


def test_should_hold_n_consecutive_failures():
    """N consecutive failures at threshold → hold with reason='n-failures'."""
    # Use different signatures to avoid triggering repeat-signature case
    _fail(98, VITEST, minutes_ago=30)
    _fail(98, "Unhandled exception: Command '['claude']' timed out", minutes_ago=25)
    _fail(98, "npm build failed", minutes_ago=20)

    decision = fb.should_hold(98, threshold=3, now=NOW)
    assert decision is not None
    assert decision["reason"] == "n-failures"
    assert decision["count"] == 3


def test_should_hold_below_threshold_returns_none():
    """Below threshold (with different signatures) → None."""
    _fail(99, VITEST, minutes_ago=30)
    _fail(99, "claude-timeout", minutes_ago=25)

    decision = fb.should_hold(99, threshold=3, now=NOW)
    assert decision is None


def test_should_hold_repeat_signature_before_threshold():
    """Last two failures have same signature → hold even if count < threshold."""
    _fail(100, VITEST, minutes_ago=30)
    _fail(100, VITEST, minutes_ago=25)

    decision = fb.should_hold(100, threshold=5, now=NOW)  # threshold is 5, count is 2
    assert decision is not None
    assert decision["reason"] == "repeat-signature"
    assert decision["count"] == 2


def test_should_hold_different_signatures_do_not_trigger_repeat():
    """Last two failures have different signatures → no hold via repeat."""
    _fail(101, VITEST, minutes_ago=30)
    _fail(101, "other failure", minutes_ago=25)

    decision = fb.should_hold(101, threshold=5, now=NOW)
    assert decision is None


def test_should_hold_honors_profile_threshold():
    """A profile's failure_threshold (e.g. 5) is honored instead of default 3."""
    sigs = [VITEST, "claude-timeout", "npm-build-failed", "git-worktree-add-failed"]
    for i in range(4):
        _fail(102, sigs[i], minutes_ago=30 - i * 5)

    # threshold=5, count=4 → should NOT hold
    decision = fb.should_hold(102, threshold=5, now=NOW)
    assert decision is None

    # threshold=4, count=4 → should hold
    decision = fb.should_hold(102, threshold=4, now=NOW)
    assert decision is not None


def test_should_hold_none_threshold_uses_default():
    """threshold=None falls back to default (3) gracefully."""
    sigs = [VITEST, "claude-timeout", "npm-build-failed"]
    for i in range(3):
        _fail(103, sigs[i], minutes_ago=30 - i * 5)

    decision = fb.should_hold(103, threshold=None, now=NOW)
    assert decision is not None  # 3 failures with default threshold 3


def test_should_hold_zero_threshold_never_holds():
    """Defensive: threshold=0 or negative should not produce nonsensical behavior."""
    _fail(104, VITEST, minutes_ago=30)

    decision = fb.should_hold(104, threshold=0, now=NOW)
    assert decision is None


def test_per_project_hold_decision():
    """should_hold respects project parameter."""
    fb.record_failure(105, VITEST, project="G-Eskayo/marvin", now=NOW - timedelta(minutes=30))
    fb.record_failure(105, VITEST, project="G-Eskayo/marvin", now=NOW - timedelta(minutes=25))
    fb.record_failure(105, VITEST, project="G-Eskayo/marvin", now=NOW - timedelta(minutes=20))

    fb.record_failure(105, VITEST, project="G-Eskayo/clarity-captions", now=NOW - timedelta(minutes=15))

    hold_marvin = fb.should_hold(105, project="G-Eskayo/marvin", threshold=3, now=NOW)
    hold_clarity = fb.should_hold(105, project="G-Eskayo/clarity-captions", threshold=3, now=NOW)

    assert hold_marvin is not None  # 3 failures in marvin
    assert hold_clarity is None  # only 1 failure in clarity
