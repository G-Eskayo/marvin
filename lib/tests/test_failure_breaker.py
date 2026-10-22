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


def _fail(ticket, reason, minutes_ago=5, project="G-Eskayo/marvin"):
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


# ── ticket_streak: per-ticket failure count ────────────────────────────────

def test_ticket_streak_counts_consecutive_failures():
    """ticket_streak returns consecutive failures after the last success/clear."""
    for i in range(3):
        _fail(42, VITEST, minutes_ago=10-i)
    streak = fb.ticket_streak(42)
    assert streak["count"] == 3
    assert streak["signatures"] == ["measure:vitest-no-summary"] * 3


def test_ticket_streak_is_reset_by_success():
    """Failures after a success don't count toward the streak."""
    _fail(42, VITEST, minutes_ago=30)
    fb.record_success(42, now=NOW - timedelta(minutes=20))
    _fail(42, VITEST, minutes_ago=5)
    streak = fb.ticket_streak(42)
    assert streak["count"] == 1


def test_ticket_streak_is_reset_by_clear():
    """Failures after a manual clear don't count."""
    for i in range(3):
        _fail(42, VITEST, minutes_ago=30-i)
    fb.clear(now=NOW - timedelta(minutes=10))
    _fail(42, VITEST, minutes_ago=5)
    streak = fb.ticket_streak(42)
    assert streak["count"] == 1


def test_ticket_streak_ignores_other_tickets():
    """A ticket's streak only counts its own failures."""
    for i in range(3):
        _fail(42, VITEST, minutes_ago=10-i)
    for i in range(5):
        _fail(43, VITEST, minutes_ago=10-i)
    assert fb.ticket_streak(42)["count"] == 3
    assert fb.ticket_streak(43)["count"] == 5


def test_ticket_streak_ignores_other_projects():
    """ticket_streak is per-ticket+project."""
    for i in range(3):
        fb.record_failure(42, VITEST, now=NOW - timedelta(minutes=10-i), project="G-Eskayo/marvin")
    for i in range(2):
        fb.record_failure(42, VITEST, now=NOW - timedelta(minutes=10-i), project="G-Eskayo/clarity-captions")
    assert fb.ticket_streak(42, project="G-Eskayo/marvin")["count"] == 3
    assert fb.ticket_streak(42, project="G-Eskayo/clarity-captions")["count"] == 2


def test_ticket_streak_preserves_signature_list():
    """signatures list contains the actual signatures of failures in order."""
    fb.record_failure(42, VITEST, now=NOW - timedelta(minutes=10))
    fb.record_failure(42, "Did not reach a passing comparison ... Final verdict: unchanged.", now=NOW - timedelta(minutes=5))
    fb.record_failure(42, VITEST, now=NOW - timedelta(minutes=1))
    streak = fb.ticket_streak(42)
    assert streak["signatures"] == ["measure:vitest-no-summary", "verdict:unchanged", "measure:vitest-no-summary"]


# ── should_hold: retry-storm hold decision ─────────────────────────────────

def test_should_hold_returns_none_when_count_below_threshold():
    """A ticket with 2 different failures and threshold 3 is not held."""
    _fail(42, VITEST, minutes_ago=10)
    _fail(42, "Did not reach a passing comparison ... Final verdict: unchanged.", minutes_ago=5)
    hold = fb.should_hold(42, threshold=3)
    assert hold is None


def test_should_hold_holds_on_threshold():
    """A ticket with 3+ different failures is held when count >= threshold."""
    # Use three different signatures to avoid triggering repeat-signature check
    fb.record_failure(42, VITEST, now=NOW - timedelta(minutes=10))
    fb.record_failure(42, "Did not reach a passing comparison ... Final verdict: unchanged.", now=NOW - timedelta(minutes=5))
    fb.record_failure(42, "Unhandled exception: Command '['npm', 'run', 'build']' returned non-zero exit status 1.", now=NOW - timedelta(minutes=1))
    hold = fb.should_hold(42, threshold=3)
    assert hold is not None
    assert hold["reason"] == "consecutive-failures"
    assert hold["count"] == 3


def test_should_hold_detects_repeat_signature():
    """Same signature twice in a row triggers hold regardless of count."""
    _fail(42, VITEST, minutes_ago=10)
    _fail(42, VITEST, minutes_ago=5)
    hold = fb.should_hold(42, threshold=999)  # threshold high, so count alone wouldn't hold
    assert hold is not None
    assert hold["reason"] == "repeat-signature"
    assert hold["count"] == 2


def test_should_hold_ignores_repeat_if_signatures_different():
    """Two different signatures do not trigger repeat-check hold."""
    _fail(42, VITEST, minutes_ago=10)
    _fail(42, "Did not reach a passing comparison ... Final verdict: unchanged.", minutes_ago=5)
    hold = fb.should_hold(42, threshold=999)  # threshold high
    assert hold is None  # no repeat, and count < threshold


# ── record_hold: parking records for the hold decision ──────────────────────

def test_record_hold_appends_a_hold_record_with_ticket_and_project():
    """record_hold() mirrors record_success(): one line per hold, with ticket, project, and timestamp."""
    fb.record_hold(42, project="G-Eskayo/marvin", now=NOW)
    records = fb._read()
    assert any(r.get("kind") == "hold" and r.get("ticket") == 42 and r.get("project") == "G-Eskayo/marvin" for r in records)


def test_record_hold_defaults_to_marvin():
    """record_hold without a project defaults to G-Eskayo/marvin."""
    fb.record_hold(42, now=NOW)
    records = fb._read()
    assert any(r.get("kind") == "hold" and r.get("project") == "G-Eskayo/marvin" for r in records)


def test_ticket_streak_treats_hold_as_reset():
    """A hold record acts as a reset point, clearing the count like success or clear."""
    _fail(42, VITEST, minutes_ago=30)
    _fail(42, VITEST, minutes_ago=20)
    fb.record_hold(42, now=NOW - timedelta(minutes=10))
    _fail(42, VITEST, minutes_ago=5)
    streak = fb.ticket_streak(42)
    assert streak["count"] == 1  # only the failure after the hold


def test_ticket_streak_filters_model_unavailable_from_both_count_and_signatures():
    """model-unavailable failures don't contribute to count or signature list."""
    fb.record_failure(42, "the x model run failed", now=NOW - timedelta(minutes=10))
    _fail(42, VITEST, minutes_ago=5)
    streak = fb.ticket_streak(42)
    # Only the vitest failure counts; the model-unavailable is filtered out
    assert streak["count"] == 1
    assert streak["signatures"] == ["measure:vitest-no-summary"]


def test_ticket_streak_mixed_failures_and_model_unavailable():
    """Model-unavailable signatures are filtered out even among mixed failures."""
    fb.record_failure(42, "the x model run failed", now=NOW - timedelta(minutes=15))
    fb.record_failure(42, VITEST, now=NOW - timedelta(minutes=10))
    fb.record_failure(42, "the x model run failed", now=NOW - timedelta(minutes=5))
    streak = fb.ticket_streak(42)
    assert streak["count"] == 1
    assert streak["signatures"] == ["measure:vitest-no-summary"]


def test_should_hold_with_precomputed_streak():
    """should_hold accepts an optional precomputed streak dict for efficiency."""
    _fail(42, VITEST, minutes_ago=10)
    _fail(42, VITEST, minutes_ago=5)
    streak = fb.ticket_streak(42)
    hold = fb.should_hold(42, threshold=999, streak=streak)
    assert hold is not None
    assert hold["reason"] == "repeat-signature"


def test_should_hold_ignores_empty_signatures_for_repeat_check():
    """If all signatures are filtered out (e.g., all model-unavailable), repeat-check doesn't trigger."""
    fb.record_failure(42, "the x model run failed", now=NOW - timedelta(minutes=10))
    fb.record_failure(42, "the x model run failed", now=NOW - timedelta(minutes=5))
    hold = fb.should_hold(42, threshold=999)
    assert hold is None  # count is 0 after filtering, no repeat


def test_model_unavailable_signature_constant():
    """MODEL_UNAVAILABLE_SIG constant is defined and used in signature()."""
    assert hasattr(fb, "MODEL_UNAVAILABLE_SIG")
    assert fb.MODEL_UNAVAILABLE_SIG == "model-unavailable"
    reason = "the x model run failed unexpectedly"
    sig = fb.signature(reason)
    assert sig == "model-unavailable"


def test_ticket_streak_project_scoped_holds():
    """ticket_streak treats hold as reset only for the same project."""
    fb.record_hold(42, project="G-Eskayo/marvin", now=NOW - timedelta(minutes=10))
    _fail(42, VITEST, minutes_ago=5, project="G-Eskayo/marvin")
    _fail(42, VITEST, minutes_ago=5, project="G-Eskayo/clarity-captions")
    assert fb.ticket_streak(42, project="G-Eskayo/marvin")["count"] == 1
    assert fb.ticket_streak(42, project="G-Eskayo/clarity-captions")["count"] == 1


def test_hold_record_and_holds_reset_resets_correctly():
    """A hold does reset the streak, and is still itself included in the log."""
    _fail(42, VITEST, minutes_ago=30)
    fb.record_hold(42, now=NOW - timedelta(minutes=20))
    _fail(42, VITEST, minutes_ago=10)
    records = fb._read()
    # Verify hold record exists
    assert any(r.get("kind") == "hold" and r.get("ticket") == 42 for r in records)
    # Verify streak only counts after the hold
    streak = fb.ticket_streak(42)
    assert streak["count"] == 1
