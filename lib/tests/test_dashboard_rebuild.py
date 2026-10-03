"""Auto-rebuild of the installed dashboard app when it falls behind the code.

2026-10-02: the laptop's app was a month stale because it only ever rebuilt on the
machine where a merge happened, so Approve there routed to the wrong webhook. Health
now reports staleness; this makes the fix automatic so nobody (human or model) has
to notice and spend effort/tokens rebuilding by hand.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dashboard_rebuild as dr  # noqa: E402

H = 3600
NOW = 1_800_000_000


def d(**kw):
    base = dict(app_built_ts=NOW - 10 * H, dashboard_commit_ts=NOW - 6 * H, app_running=False,
                last_attempt_ts=None, now=NOW)
    base.update(kw)
    return dr.decide(**base)


def test_rebuilds_when_the_app_is_behind_and_not_running():
    assert d()[0] == "rebuild"


def test_skips_when_the_app_is_already_current():
    assert d(app_built_ts=NOW - 1 * H, dashboard_commit_ts=NOW - 3 * H)[0] == "skip"
    assert d(app_built_ts=NOW - 3 * H, dashboard_commit_ts=NOW - 3 * H)[0] == "skip"


def test_waits_for_a_fresh_change_to_settle_before_rebuilding():
    assert d(app_built_ts=NOW - 10 * H, dashboard_commit_ts=NOW - 5 * 60)[0] == "skip"


def test_a_change_that_has_settled_for_a_quarter_hour_rebuilds():
    assert d(app_built_ts=NOW - 10 * H, dashboard_commit_ts=NOW - 20 * 60)[0] == "rebuild"


def test_does_not_interrupt_a_running_app_for_a_small_gap():
    assert d(app_running=True, app_built_ts=NOW - 30 * 60, dashboard_commit_ts=NOW - 20 * 60)[0] == "skip"


def test_but_a_running_app_an_hour_or_more_behind_gets_rebuilt_anyway():
    assert d(app_running=True, app_built_ts=NOW - 3 * H, dashboard_commit_ts=NOW - 30 * 60)[0] == "rebuild"


def test_backs_off_after_a_recent_attempt_so_a_broken_build_cannot_loop():
    assert d(last_attempt_ts=NOW - 1 * H)[0] == "skip"
    assert d(last_attempt_ts=NOW - 7 * H)[0] == "rebuild"


def test_rebuilds_when_no_app_is_installed_at_all():
    assert d(app_built_ts=None)[0] == "rebuild"


def test_skips_when_there_is_no_dashboard_commit_to_compare_against():
    assert d(dashboard_commit_ts=None)[0] == "skip"


def test_every_decision_carries_a_human_readable_reason():
    for kw in ({}, {"app_running": True}, {"app_built_ts": NOW}):
        assert d(**kw)[1]


def test_only_files_that_go_into_the_app_count_as_a_dashboard_change():
    # webhook-server/ (a separate launchd node process) and test/ never change the
    # installed app, so editing them must not trigger a rebuild or read as stale.
    paths = " ".join(dr.APP_SOURCE_PATHS)
    assert "dashboard/src" in paths and "dashboard/electron" in paths and "package.json" in paths
    assert "webhook-server" not in paths and "dashboard/test" not in paths
