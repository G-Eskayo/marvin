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


def test_skips_when_a_merge_is_in_flight_to_avoid_cutting_it_off():
    # A merge is running; restarting the webhook-server now could cut it off.
    assert d(merge_inflight=True)[0] == "skip"
    assert "merge is in flight" in d(merge_inflight=True)[1].lower()


def test_does_not_skip_for_merge_inflight_if_the_server_is_already_current():
    # Even with a merge in flight, if the server is current, don't skip for other reasons.
    assert d(server_start_ts=NOW - 1 * H, webhook_commit_ts=NOW - 3 * H, merge_inflight=True)[0] == "skip"
    assert "current" in d(server_start_ts=NOW - 1 * H, webhook_commit_ts=NOW - 3 * H, merge_inflight=True)[1].lower()


def test_does_not_skip_for_merge_inflight_if_the_server_is_not_running():
    # A crashed server has nothing to cut off; merge-inflight must not block recovery.
    assert d(server_start_ts=None, merge_inflight=True)[0] == "restart"


def test_merge_inflight_returns_false_when_the_file_does_not_exist(tmp_path):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        nonexistent = Path(tmp) / "merge-inflight.json"
        assert wr._merge_inflight.__globals__['INFLIGHT_FILE'] == wr.INFLIGHT_FILE
        # Test by monkey-patching INFLIGHT_FILE temporarily
        original = wr.INFLIGHT_FILE
        try:
            wr.INFLIGHT_FILE = nonexistent
            assert wr._merge_inflight() is False
        finally:
            wr.INFLIGHT_FILE = original


def test_merge_inflight_returns_false_when_the_file_is_empty_dict():
    import tempfile
    import json
    with tempfile.TemporaryDirectory() as tmp:
        inflight_file = Path(tmp) / "merge-inflight.json"
        inflight_file.write_text(json.dumps({}))
        original = wr.INFLIGHT_FILE
        try:
            wr.INFLIGHT_FILE = inflight_file
            assert wr._merge_inflight() is False
        finally:
            wr.INFLIGHT_FILE = original


def test_merge_inflight_returns_true_when_the_file_has_a_merge_entry():
    import tempfile
    import json
    with tempfile.TemporaryDirectory() as tmp:
        inflight_file = Path(tmp) / "merge-inflight.json"
        inflight_file.write_text(json.dumps({"https://github.com/G-Eskayo/marvin/pull/123": {"started": NOW}}))
        original = wr.INFLIGHT_FILE
        try:
            wr.INFLIGHT_FILE = inflight_file
            assert wr._merge_inflight() is True
        finally:
            wr.INFLIGHT_FILE = original


def test_merge_inflight_fails_closed_on_malformed_json():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        inflight_file = Path(tmp) / "merge-inflight.json"
        inflight_file.write_text('{not valid json')
        original = wr.INFLIGHT_FILE
        try:
            wr.INFLIGHT_FILE = inflight_file
            assert wr._merge_inflight() is True
        finally:
            wr.INFLIGHT_FILE = original


def test_merge_inflight_fails_closed_on_non_dict_json():
    import tempfile
    import json
    with tempfile.TemporaryDirectory() as tmp:
        inflight_file = Path(tmp) / "merge-inflight.json"
        inflight_file.write_text(json.dumps([]))
        original = wr.INFLIGHT_FILE
        try:
            wr.INFLIGHT_FILE = inflight_file
            assert wr._merge_inflight() is True
        finally:
            wr.INFLIGHT_FILE = original


def test_merge_inflight_fails_closed_on_unreadable_file():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        inflight_file = Path(tmp) / "merge-inflight.json"
        # Create a directory with the same name instead of a file
        inflight_file.mkdir()
        original = wr.INFLIGHT_FILE
        try:
            wr.INFLIGHT_FILE = inflight_file
            assert wr._merge_inflight() is True
        finally:
            wr.INFLIGHT_FILE = original


def test_every_decision_includes_merge_inflight_case():
    # Extend existing test to verify merge_inflight case also carries a reason
    assert d(merge_inflight=True)[1]


def test_settle_window_allows_restart_after_waiting():
    """Verify a fresh webhook change is skipped, but after settle window it can restart.

    This test catches the defect where the settle check blocked both fast paths:
    - code_sync_check pulls → spawns webhook_restart
    - webhook_restart sees the change is fresh (< 60s) and skips
    - code-sync is debounced, so nothing re-triggers after settle window

    A fresh change (30s) should skip; the same change later (120s) should restart.
    This ensures the settle window is a gate, not a permanent block.
    """
    fresh = d(server_start_ts=NOW - 10 * H, webhook_commit_ts=NOW - 30)
    assert fresh[0] == "skip"
    assert "fresh" in fresh[1].lower()

    settled = d(server_start_ts=NOW - 10 * H, webhook_commit_ts=NOW - 2 * 60)
    assert settled[0] == "restart"
    assert fresh != settled  # Different decisions at different times


def test_merge_inflight_blocks_fast_restart_paths():
    """Verify merge_inflight blocks the immediate restart paths but not crash recovery.

    When a code-sync pull happens during a merge, webhook_restart.py could restart
    while the merge is writing, cutting it off. The merge_inflight flag should block
    restart decisions when appropriate, but not when the server is down.
    """
    # Fast restart path: server behind, but a merge is in flight → skip
    assert d(server_start_ts=NOW - 10 * H, webhook_commit_ts=NOW - 2 * 60, merge_inflight=True)[0] == "skip"

    # Crash recovery path: server down, even with merge in flight → restart (nothing to cut off)
    assert d(server_start_ts=None, merge_inflight=True)[0] == "restart"

    # When merge is not in flight, both should restart
    assert d(server_start_ts=NOW - 10 * H, webhook_commit_ts=NOW - 2 * 60, merge_inflight=False)[0] == "restart"
    assert d(server_start_ts=None, merge_inflight=False)[0] == "restart"
