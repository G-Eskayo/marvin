"""Cross-ticket circuit breaker for the ticket pipeline.

Found 2026-10-01: the 3-strike guard is per-ticket, so a SYSTEMIC failure (a broken
environment, not a bad ticket) failed every ticket in the queue in sequence, each
burning its own strikes, and nothing noticed -- the Activity tab showed the cascade
but no automated consumer reacted to it. Every systemic bug that day was found by
hand. The breaker recognises "the same failure across DIFFERENT tickets" and stops
dispatch.
"""
from __future__ import annotations
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
