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


def _fail(ticket, reason, minutes_ago=5, project=fb.MARVIN):
    fb.record_failure(ticket, reason, now=NOW - timedelta(minutes=minutes_ago), project=project)


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


# ── ticket_streak: count failures since last success ────────────────────────

def test_ticket_streak_zero_failures_with_no_history():
    """A ticket with no records has zero failures."""
    result = fb.ticket_streak(999, now=NOW)
    assert result == {"count": 0, "signatures": [], "ordered_sigs": []}


def test_ticket_streak_counts_failures_since_last_success():
    """Failures after the most recent success are counted."""
    _fail(42, "error A", minutes_ago=30)
    _fail(42, "error B", minutes_ago=20)
    fb.record_success(42, now=NOW - timedelta(minutes=10))
    _fail(42, "error C", minutes_ago=5)
    _fail(42, "error A", minutes_ago=2)  # repeat of A
    result = fb.ticket_streak(42, now=NOW)
    assert result["count"] == 2  # only the two failures after the success


def test_ticket_streak_returns_unique_signatures_in_order():
    """Signatures are unique and in order of first appearance."""
    _fail(43, "error X", minutes_ago=30)
    _fail(43, "error Y", minutes_ago=20)
    _fail(43, "error X", minutes_ago=10)  # repeat
    _fail(43, "error Z", minutes_ago=5)
    result = fb.ticket_streak(43, now=NOW)
    assert result["count"] == 4
    # Signatures are computed by the signature() function; these all collapse to "other:..."
    assert len(result["signatures"]) == 3  # X, Y, Z (X repeats but we only list unique)
    # First sig appears, then second, third
    assert result["signatures"][0] != result["signatures"][1]  # X != Y
    assert result["signatures"][1] != result["signatures"][2]  # Y != Z


def test_ticket_streak_if_no_success_counts_all_failures():
    """Without a success marker, all failures since the start are counted."""
    _fail(44, VITEST, minutes_ago=40)
    _fail(44, VITEST, minutes_ago=20)
    result = fb.ticket_streak(44, now=NOW)
    assert result["count"] == 2
    assert "vitest-no-summary" in result["signatures"][0]


# ── should_hold: decide if a ticket should be parked ──────────────────────

def test_should_hold_returns_none_with_no_failures():
    """No streak, no hold."""
    result = fb.should_hold(100, "G-Eskayo/marvin", threshold=3, now=NOW)
    assert result is None


def test_should_hold_returns_n_failures_when_threshold_exceeded():
    """Reaching the failure threshold triggers an n-failures hold."""
    for i in range(3):
        _fail(101, VITEST, minutes_ago=30 - i * 5)
    result = fb.should_hold(101, "G-Eskayo/marvin", threshold=3, now=NOW)
    assert result is not None
    assert result["reason"] == "n-failures"
    assert result["count"] == 3


def test_should_hold_returns_repeat_signature_when_same_error_repeats():
    """A signature appearing twice CONSECUTIVELY (the last two) triggers a hold."""
    _fail(102, VITEST, minutes_ago=20)
    _fail(102, VITEST, minutes_ago=10)  # same signature back-to-back (last two entries)
    result = fb.should_hold(102, "G-Eskayo/marvin", threshold=5, now=NOW)
    assert result is not None
    assert result["reason"] == "repeat-signature"


def test_should_hold_repeat_signature_test_8_non_consecutive_does_not_hold():
    """A duplicate signature that is NOT the last two entries does not trigger repeat-signature."""
    _fail(108, "error X", minutes_ago=30)
    _fail(108, "error Y", minutes_ago=20)
    _fail(108, "error X", minutes_ago=10)  # X appears again, but not back-to-back with itself
    result = fb.should_hold(108, "G-Eskayo/marvin", threshold=5, now=NOW)
    assert result is None


def test_should_hold_repeat_signature_test_9_three_same_only_last_two_matter():
    """When the same signature appears three times, only the last two consecutive ones count."""
    _fail(109, "error Z", minutes_ago=30)
    _fail(109, "error Z", minutes_ago=20)
    _fail(109, "error Z", minutes_ago=10)  # last two are definitely the same
    result = fb.should_hold(109, "G-Eskayo/marvin", threshold=10, now=NOW)
    assert result is not None
    assert result["reason"] == "repeat-signature"


def test_should_hold_repeat_signature_test_10_last_entry_alone_no_hold():
    """A single failure at the end (even if earlier failures matched) does not trigger repeat-signature."""
    _fail(110, "error A", minutes_ago=20)
    _fail(110, "error A", minutes_ago=15)
    _fail(110, "error B", minutes_ago=5)  # last entry is different
    result = fb.should_hold(110, "G-Eskayo/marvin", threshold=10, now=NOW)
    assert result is None


def test_should_hold_repeat_signature_test_11_only_two_different_errors_no_repeat():
    """Two different errors in sequence are never a repeat-signature."""
    _fail(111, "error P", minutes_ago=20)
    _fail(111, "error Q", minutes_ago=10)
    result = fb.should_hold(111, "G-Eskayo/marvin", threshold=5, now=NOW)
    assert result is None


def test_should_hold_empty_ticket_holds_at_threshold_2_not_3():
    """Threshold comparison uses >= not >."""
    _fail(103, VITEST, minutes_ago=20)
    _fail(103, VITEST, minutes_ago=10)
    result = fb.should_hold(103, "G-Eskayo/marvin", threshold=2, now=NOW)
    assert result["reason"] == "n-failures"


def test_should_hold_per_project_separation():
    """Streaks are per-project; marvin and another project don't share count."""
    _fail(105, "error A", project="G-Eskayo/marvin", minutes_ago=20)
    _fail(105, "error B", project="G-Eskayo/clarity-captions", minutes_ago=15)
    _fail(105, "error C", project="G-Eskayo/marvin", minutes_ago=10)
    result_marvin = fb.should_hold(105, "G-Eskayo/marvin", threshold=3, now=NOW)
    result_clarity = fb.should_hold(105, "G-Eskayo/clarity-captions", threshold=3, now=NOW)
    # Marvin has 2 failures, clarity has 1. With threshold 3, neither should hold.
    assert result_marvin is None
    assert result_clarity is None


# ── Bug 1 fix: ticket_streak must be defensively filtered ─────────────────────

def test_ticket_streak_survives_a_clear_record_in_the_log(monkeypatch, tmp_path):
    """Bug 1: ticket_streak crashed on clear() records missing the 'ticket' field.
    The filter must use .get() defensively."""
    monkeypatch.setattr(fb, "LOG_PATH", tmp_path / "pipeline-failures.jsonl")
    _fail(50, "error 1", minutes_ago=20)
    fb.clear(now=NOW - timedelta(minutes=15))  # clear record has no 'ticket' field
    _fail(50, "error 2", minutes_ago=5)
    # This should not crash even though the clear record breaks a naive filter
    result = fb.ticket_streak(50, now=NOW)
    assert result["count"] == 1  # only the failure after the clear
    assert len(result["signatures"]) == 1


def test_should_hold_detects_repeat_signature_only_on_consecutive_pair():
    """Bug 4 fix: repeat-signature means the LAST TWO entries match, not any duplicate anywhere.
    With failures A, B, A: the last is A, second-last is B, so not a repeat of the last.
    With failures A, B, B: the last is B, second-last is B, so repeat-signature holds."""
    # Case 1: A, B, A (distinct last two) - should NOT hold
    _fail(201, "error A", minutes_ago=30)
    _fail(201, "error B", minutes_ago=20)
    _fail(201, "error A", minutes_ago=10)  # same as first, but not consecutive with itself
    result = fb.should_hold(201, "G-Eskayo/marvin", threshold=10, now=NOW)
    assert result is None, "A-B-A should not trigger repeat-signature (last two are distinct)"

    # Case 2: A, B, B (last two match) - should hold
    _fail(202, "error X", minutes_ago=30)
    _fail(202, "error Y", minutes_ago=20)
    _fail(202, "error Y", minutes_ago=10)  # same as previous
    result = fb.should_hold(202, "G-Eskayo/marvin", threshold=10, now=NOW)
    assert result is not None
    assert result["reason"] == "repeat-signature", "Y-Y (last two) should trigger repeat-signature"
