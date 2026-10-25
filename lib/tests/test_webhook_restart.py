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


# --- settle_seconds parameter (on-merge fast path vs. cron default path) ---


def d_with_settle(**kw):
    """Helper that accepts settle_seconds and wraps decide()."""
    settle = kw.pop('settle_seconds', None)
    base = dict(server_start_ts=NOW - 10 * H, webhook_commit_ts=NOW - 6 * H,
                last_attempt_ts=None, now=NOW)
    base.update(kw)
    if settle is not None:
        return wr.decide(settle_seconds=settle, **base)
    return wr.decide(**base)


def test_settle_seconds_parameter_shortens_default_settle_time():
    # With settle_seconds=120 (2 min), a 90s-old commit should skip but 150s should restart.
    assert d_with_settle(webhook_commit_ts=NOW - 90, settle_seconds=120)[0] == "skip"
    assert d_with_settle(webhook_commit_ts=NOW - 150, settle_seconds=120)[0] == "restart"


def test_settle_seconds_none_uses_default_constant():
    # With settle_seconds=None (or omitted), should use the default 60s logic.
    result = d_with_settle(webhook_commit_ts=NOW - 30, settle_seconds=None)
    assert result[0] == "skip"  # 30s is less than default 60s


def test_settle_seconds_zero_does_not_crash():
    # Edge case: settle_seconds=0 should restart immediately without negative-sleep errors.
    result = d_with_settle(server_start_ts=NOW - 10 * H, webhook_commit_ts=NOW - 1, settle_seconds=0)
    assert result[0] == "restart"
