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
    base = dict(app_built_ts=NOW - 10 * H, dashboard_commit_ts=NOW - 6 * H, rebuild_running=False,
                last_failure_ts=None, now=NOW)
    base.update(kw)
    return dr.decide(**base)


# #443 (2026-10-14): Gil merged on GitHub and the installed app never updated. The policy is now "within minutes of
# any merge": 2-minute settle, rebuild even if the app is open (the install relaunches it), and back off only after a
# FAILED build -- until newer code lands, so the next merge (usually the fix) retries at once.

def test_rebuilds_when_the_app_is_behind():
    assert d()[0] == "rebuild"


def test_skips_when_the_app_is_already_current():
    assert d(app_built_ts=NOW - 1 * H, dashboard_commit_ts=NOW - 3 * H)[0] == "skip"
    assert d(app_built_ts=NOW - 3 * H, dashboard_commit_ts=NOW - 3 * H)[0] == "skip"


def test_a_merge_settles_for_two_minutes_not_fifteen():
    assert d(dashboard_commit_ts=NOW - 60)[0] == "skip"
    assert d(dashboard_commit_ts=NOW - 3 * 60)[0] == "rebuild"


def test_an_open_app_is_no_longer_a_reason_to_wait():
    # the old rule ("don't interrupt a running app unless an hour behind") is gone: decide() no longer even takes it
    assert d(app_built_ts=NOW - 10 * 60, dashboard_commit_ts=NOW - 5 * 60)[0] == "rebuild"


def test_never_starts_a_second_build_while_one_is_running():
    assert d(rebuild_running=True)[0] == "skip"
    assert d(rebuild_running=True, app_built_ts=None)[0] == "skip"


def test_a_successful_attempt_does_not_block_the_next_merge():
    # there is no "last attempt" any more: only failures back off
    assert "last_attempt_ts" not in dr.decide.__code__.co_varnames


def test_a_failed_build_backs_off_until_newer_code_lands():
    commit = NOW - 1 * H
    assert d(dashboard_commit_ts=commit, last_failure_ts=commit + 60)[0] == "skip"     # failed on this code
    assert d(dashboard_commit_ts=commit, last_failure_ts=commit - 60)[0] == "rebuild"  # newer code since the failure


def test_a_failure_is_retried_on_the_same_code_after_six_hours_in_case_it_was_transient():
    commit = NOW - 8 * H
    assert d(dashboard_commit_ts=commit, last_failure_ts=NOW - 7 * H)[0] == "rebuild"
    assert d(dashboard_commit_ts=commit, last_failure_ts=NOW - 5 * H)[0] == "skip"


def test_rebuilds_when_no_app_is_installed_at_all():
    # also how a machine migrates from "MARVIN Metrics.app" (#442): the new path is absent, so it builds MARVIN.app
    assert d(app_built_ts=None)[0] == "rebuild"


def test_skips_when_there_is_no_dashboard_commit_to_compare_against():
    assert d(dashboard_commit_ts=None)[0] == "skip"


def test_every_decision_carries_a_human_readable_reason():
    for kw in ({}, {"rebuild_running": True}, {"app_built_ts": NOW}, {"dashboard_commit_ts": NOW - 30}):
        assert d(**kw)[1]


def test_the_installed_app_is_MARVIN_app_after_the_rename():
    assert str(dr.APP_ASAR) == "/Applications/MARVIN.app/Contents/Resources/app.asar"


def test_compares_against_github_not_the_local_checkout():
    # a GitHub-side merge is not in the local checkout until code-sync pulls; decide on origin/main after a fetch
    import inspect
    src = inspect.getsource(dr._facts)
    assert "fetch" in src and "origin/main" in src


def test_only_files_that_go_into_the_app_count_as_a_dashboard_change():
    # webhook-server/ (a separate launchd node process) and test/ never change the
    # installed app, so editing them must not trigger a rebuild or read as stale.
    paths = " ".join(dr.APP_SOURCE_PATHS)
    assert "dashboard/src" in paths and "dashboard/electron" in paths and "package.json" in paths
    assert "webhook-server" not in paths and "dashboard/test" not in paths


def test_the_app_icon_counts_as_an_app_change():
    # dashboard/resources/icon.png (#435) ships inside the app
    assert "dashboard/resources" in dr.APP_SOURCE_PATHS
