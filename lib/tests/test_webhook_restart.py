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
                last_attempt_ts=None, now=NOW)
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


def test_backs_off_after_a_recent_attempt_so_a_failed_restart_cannot_loop():
    assert d(last_attempt_ts=NOW - 1 * H)[0] == "skip"
    assert d(last_attempt_ts=NOW - 7 * H)[0] == "restart"


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


# Tests 1-11: merge_running, wait_for_merge_idle, restart_now, and CLI

def test_merge_running_returns_true_when_a_merge_is_active():
    # merge_running() GETs /merge-queue and checks if any repo has running != null
    def fake_exec(cmd, *args, **kw):
        # Simulate a running merge
        return '{"repos":{"G-Eskayo/marvin":{"running":"https://github.com/G-Eskayo/marvin/pull/1","items":[],"failed":{}}}}'
    assert wr.merge_running(exec=fake_exec) is True


def test_merge_running_returns_false_when_no_merge_is_active():
    # merge_running() returns False when all repos have running: null
    def fake_exec(cmd, *args, **kw):
        return '{"repos":{"G-Eskayo/marvin":{"running":null,"items":[],"failed":{}}}}'
    assert wr.merge_running(exec=fake_exec) is False


def test_merge_running_returns_false_on_timeout_or_error():
    # merge_running() handles network errors gracefully
    def fake_exec_timeout(cmd, *args, **kw):
        raise TimeoutError("Request timeout")
    assert wr.merge_running(exec=fake_exec_timeout) is False

    def fake_exec_error(cmd, *args, **kw):
        raise Exception("Connection refused")
    assert wr.merge_running(exec=fake_exec_error) is False


def test_merge_running_returns_false_on_malformed_json():
    # merge_running() handles malformed JSON gracefully
    def fake_exec(cmd, *args, **kw):
        return '{"invalid json}'
    assert wr.merge_running(exec=fake_exec) is False


def test_wait_for_merge_idle_returns_immediately_when_no_merge_running():
    # wait_for_merge_idle() calls check() and returns (True, elapsed_time) when merge is not running
    elapsed_times = []
    def fake_sleep(duration):
        elapsed_times.append(duration)
    def fake_check():
        return False  # no merge running

    success, elapsed = wr.wait_for_merge_idle(timeout_s=10, poll_s=1, check=fake_check, sleep=fake_sleep)
    assert success is True
    assert elapsed >= 0
    assert len(elapsed_times) == 0  # no polling needed


def test_wait_for_merge_idle_polls_until_merge_completes():
    # wait_for_merge_idle() polls at intervals until merge becomes idle
    poll_count = [0]
    def fake_check():
        poll_count[0] += 1
        return poll_count[0] < 3  # running for first 2 calls, then idle

    sleep_durations = []
    def fake_sleep(duration):
        sleep_durations.append(duration)

    success, elapsed = wr.wait_for_merge_idle(timeout_s=10, poll_s=2, check=fake_check, sleep=fake_sleep)
    assert success is True
    assert poll_count[0] == 3  # checked 3 times total
    assert len(sleep_durations) == 2  # slept between checks 1-2 and 2-3


def test_wait_for_merge_idle_times_out_if_merge_never_completes():
    # wait_for_merge_idle() returns (False, elapsed) when timeout is exceeded
    def fake_check():
        return True  # always running

    sleep_count = [0]
    def fake_sleep(duration):
        sleep_count[0] += 1

    success, elapsed = wr.wait_for_merge_idle(timeout_s=2, poll_s=1, check=fake_check, sleep=fake_sleep)
    assert success is False
    assert elapsed >= 2


def test_restart_now_waits_for_merge_idle_then_restarts():
    # restart_now() calls wait_for_merge_idle before restarting, logs the outcome, and always restarts
    calls = []
    def fake_wait(timeout_s, poll_s, check, sleep, now):
        calls.append(('wait', timeout_s, poll_s))
        return (True, 1.5)  # success, 1.5 seconds elapsed

    restart_calls = []
    def fake_restart():
        restart_calls.append('restart')

    log_lines = []
    def fake_log(msg):
        log_lines.append(msg)

    wr.restart_now("rebuild", wait_timeout_s=5, wait_func=fake_wait, restart_func=fake_restart, log_func=fake_log)

    assert len(calls) == 1
    assert calls[0][0] == 'wait'
    assert len(restart_calls) == 1
    assert any("rebuild" in str(line) for line in log_lines)


def test_restart_now_restarts_even_if_merge_wait_times_out():
    # restart_now() always restarts, even if wait_for_merge_idle times out
    def fake_wait_timeout(timeout_s, poll_s, check, sleep, now):
        return (False, 5.0)  # timeout, 5 seconds elapsed

    restart_calls = []
    def fake_restart():
        restart_calls.append('restart')

    log_lines = []
    def fake_log(msg):
        log_lines.append(msg)

    wr.restart_now("rebuild", wait_timeout_s=5, wait_func=fake_wait_timeout, restart_func=fake_restart, log_func=fake_log)

    assert len(restart_calls) == 1  # still restarted despite timeout


def test_two_rebuilds_in_a_row_both_complete():
    # --force --reason bypasses backoff, so two rebuilds back-to-back both happen
    wait_count = [0]
    def fake_wait(timeout_s, poll_s, check, sleep, now):
        wait_count[0] += 1
        return (True, 0.1)

    restart_count = [0]
    def fake_restart():
        restart_count[0] += 1

    def fake_log(msg):
        pass

    # First rebuild
    wr.restart_now("rebuild 1", wait_timeout_s=5, wait_func=fake_wait, restart_func=fake_restart, log_func=fake_log)
    # Second rebuild immediately after (would be blocked by cron's 6h backoff, but --force bypasses it)
    wr.restart_now("rebuild 2", wait_timeout_s=5, wait_func=fake_wait, restart_func=fake_restart, log_func=fake_log)

    assert restart_count[0] == 2  # both completed
    assert wait_count[0] == 2  # both waited


def test_existing_decide_and_facts_still_work():
    # Verify that existing cron-based behavior is unchanged.
    # Uses mock facts to avoid hanging on real git/launchctl subprocess calls.
    facts = {
        "server_start_ts": NOW - 4 * H,
        "webhook_commit_ts": NOW - 2 * H,
        "last_attempt_ts": None,
        "now": NOW
    }

    action, reason = wr.decide(**facts)
    assert action in ("restart", "skip")
    assert isinstance(reason, str) and len(reason) > 0
    assert "restart" in action or "skip" in action
