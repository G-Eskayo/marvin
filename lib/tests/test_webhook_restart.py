"""Auto-restart of the webhook-server node process when its code or dependencies change.

The webhook-server (launchd job com.marvin.dashboard-webhook) is a long-running node
process that directly imports from ../electron/main. When #258 moved portfolio.js,
the webhook-server's already-loaded module graph kept the stale path until a manual
launchctl kickstart -k force-restart. This test mirrors dashboard_rebuild.py's pattern:
a pure decide() function (easy to test) + _facts() to gather facts + main() to act.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import webhook_restart as wr  # noqa: E402

H = 3600
NOW = 1_800_000_000


def d(**kw):
    base = dict(server_start_ts=NOW - 10 * H, webhook_commit_ts=NOW - 6 * H,
                restart_running=False, last_failure_ts=None, merge_inflight=False, now=NOW)
    base.update(kw)
    return wr.decide(**base)


def test_restarts_when_the_server_is_behind_the_latest_code():
    assert d()[0] == "restart"


def test_skips_when_the_server_is_already_current():
    assert d(server_start_ts=NOW - 1 * H, webhook_commit_ts=NOW - 3 * H)[0] == "skip"
    assert d(server_start_ts=NOW - 3 * H, webhook_commit_ts=NOW - 3 * H)[0] == "skip"


def test_waits_for_a_fresh_change_to_settle_before_restarting():
    assert d(server_start_ts=NOW - 10 * H, webhook_commit_ts=NOW - 30)[0] == "skip"


def test_a_change_that_has_settled_for_a_minute_restarts():
    assert d(server_start_ts=NOW - 10 * H, webhook_commit_ts=NOW - 2 * 60)[0] == "restart"


def test_backs_off_after_a_failed_restart_so_the_same_code_is_not_retried_immediately():
    assert d(last_failure_ts=NOW - 1 * H)[0] == "skip"
    assert d(last_failure_ts=NOW - 7 * H)[0] == "restart"


def test_restarts_when_the_server_is_not_running():
    assert d(server_start_ts=None)[0] == "restart"


def test_skips_when_there_is_no_webhook_commit_to_compare_against():
    assert d(webhook_commit_ts=None)[0] == "skip"


def test_every_decision_carries_a_human_readable_reason():
    for kw in ({}, {"server_start_ts": None}, {"webhook_commit_ts": None}):
        assert d(**kw)[1]


def test_only_webhook_and_electron_main_changes_count():
    # dashboard/electron/preload and dashboard/src only matter to the Electron app.
    paths = " ".join(wr.WEBHOOK_SOURCE_PATHS)
    assert "dashboard/webhook-server" in paths and "dashboard/electron/main" in paths
    assert "dashboard/electron/preload" not in paths and "dashboard/src" not in paths


def test_waits_when_a_merge_is_in_flight():
    assert d(merge_inflight=True)[0] == "wait"


def test_skips_when_a_restart_is_already_running():
    assert d(restart_running=True)[0] == "skip"


def test_backs_off_after_a_failed_restart_so_the_same_code_is_not_retried_immediately():
    assert d(last_failure_ts=NOW - 1 * H)[0] == "skip"
    assert d(last_failure_ts=NOW - 7 * H)[0] == "restart"


def test_only_backs_off_after_a_failure_when_code_is_the_same():
    # A fresh code change clears the backoff even if the old code had failed.
    newer_code_ts = NOW - 2 * H
    old_failure_ts = NOW - 3 * H  # failure from older code
    assert d(webhook_commit_ts=newer_code_ts, last_failure_ts=old_failure_ts)[0] == "restart"


def test_every_new_decision_carries_a_reason():
    for kw in ({}, {"merge_inflight": True}, {"restart_running": True}, {"last_failure_ts": NOW - 1 * H}):
        assert d(**kw)[1]


def test_waits_for_merge_to_finish_before_pulling():
    # When merge_inflight is true, main() skips pull and waits. The script returns without restarting.
    # _facts will still use the pre-merge webhook_commit_ts (no new fetch), so restart will wait or skip.
    # This test checks that decide() returns "wait" when merge is in flight.
    assert d(merge_inflight=True)[0] == "wait"
    # After merge finishes, the next invocation can pull and decide again.
    assert d(merge_inflight=False)[0] == "restart"
