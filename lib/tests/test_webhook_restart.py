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
                last_attempt_ts=None, merge_inflight_flag=False, immediate=False, now=NOW)
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


def test_skips_when_a_merge_is_in_flight():
    assert d(merge_inflight_flag=True)[0] == "skip"
    assert "merge is in flight" in d(merge_inflight_flag=True)[1]


def test_merge_inflight_blocks_even_when_backoff_window_has_passed():
    assert d(last_attempt_ts=NOW - 7 * H, merge_inflight_flag=True)[0] == "skip"


def test_restarts_once_merge_is_no_longer_in_flight():
    # With merge_inflight_flag=False and an otherwise-stale server
    assert d(merge_inflight_flag=False, server_start_ts=NOW - 10 * H, webhook_commit_ts=NOW - 6 * H)[0] == "restart"


def test_merge_inflight_reads_the_real_file_as_empty_means_no_merge(tmp_path):
    empty_file = tmp_path / "merge-inflight.json"
    empty_file.write_text("{}")
    assert wr.merge_inflight(path=empty_file) is False


def test_merge_inflight_reads_the_real_file_nonempty_dict_means_a_merge_is_running(tmp_path):
    file_with_merge = tmp_path / "merge-inflight.json"
    file_with_merge.write_text('{"https://github.com/G-Eskayo/marvin/pull/123": {}}')
    assert wr.merge_inflight(path=file_with_merge) is True


def test_merge_inflight_fails_open_on_missing_file():
    assert wr.merge_inflight(path=Path("/nonexistent/file.json")) is False


def test_merge_inflight_fails_open_on_malformed_json(tmp_path):
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not valid json}")
    assert wr.merge_inflight(path=bad_json) is False


def test_merge_inflight_fails_open_on_non_dict_value(tmp_path):
    non_dict = tmp_path / "non-dict.json"
    non_dict.write_text('[]')
    assert wr.merge_inflight(path=non_dict) is False


def test_bypass_settle_check_when_immediate_flag_is_true():
    # With immediate=True, even a very fresh change (30 seconds old) restarts
    assert d(immediate=True, server_start_ts=NOW - 10 * H, webhook_commit_ts=NOW - 30)[0] == "restart"


def test_settle_check_applies_when_immediate_is_false():
    # Default behavior: very fresh change is skipped
    assert d(immediate=False, server_start_ts=NOW - 10 * H, webhook_commit_ts=NOW - 30)[0] == "skip"


def test_restarts_dead_server_even_if_merge_is_in_flight():
    # If the server crashed mid-merge, it should restart regardless of merge status.
    # This is the fix for Issue 1: server_start_ts check comes before merge_inflight check.
    action, reason = d(server_start_ts=None, merge_inflight_flag=True)
    assert action == "restart"
    assert "not running" in reason


def test_merge_inflight_ignores_stale_entries_older_than_30_minutes(tmp_path):
    # Issue 1 fix: stale entries from crashed servers should not block restarts.
    file_with_stale = tmp_path / "merge-inflight.json"
    import json
    import time
    now_ms = int(time.time() * 1000)
    stale_entry = {
        "https://github.com/G-Eskayo/marvin/pull/123": {
            "id": "old-merge",
            "stage": "tests",
            "startedAt": now_ms - 40 * 60 * 1000  # 40 minutes ago
        }
    }
    file_with_stale.write_text(json.dumps(stale_entry))
    # Should be ignored because it's older than 30 min
    assert wr.merge_inflight(path=file_with_stale, max_age_ms=30 * 60 * 1000) is False


def test_merge_inflight_considers_recent_entries_as_active(tmp_path):
    # Recent entries (less than 30 min old) are active merges and should block restart.
    file_with_recent = tmp_path / "merge-inflight.json"
    import json
    import time
    now_ms = int(time.time() * 1000)
    recent_entry = {
        "https://github.com/G-Eskayo/marvin/pull/456": {
            "id": "recent-merge",
            "stage": "tests",
            "startedAt": now_ms - 5 * 60 * 1000  # 5 minutes ago
        }
    }
    file_with_recent.write_text(json.dumps(recent_entry))
    # Should be considered active because it's less than 30 min old
    assert wr.merge_inflight(path=file_with_recent, max_age_ms=30 * 60 * 1000) is True


def test_merge_inflight_ignores_done_merges(tmp_path):
    # Issue 2 fix: merges marked 'done' should not block restart
    # (in-flight file removal is pending).
    file_with_done = tmp_path / "merge-inflight.json"
    import json
    import time
    now_ms = int(time.time() * 1000)
    done_entry = {
        "https://github.com/G-Eskayo/marvin/pull/789": {
            "id": "just-finished",
            "stage": "done",
            "startedAt": now_ms - 5 * 60 * 1000  # 5 minutes ago (recent, but done)
        }
    }
    file_with_done.write_text(json.dumps(done_entry))
    # Should be ignored because stage is 'done'
    assert wr.merge_inflight(path=file_with_done, max_age_ms=30 * 60 * 1000) is False


def test_merge_inflight_with_mixed_entries(tmp_path):
    # Some entries are stale, some are done, one is active.
    # Only the active one should cause a skip.
    file_with_mixed = tmp_path / "merge-inflight.json"
    import json
    import time
    now_ms = int(time.time() * 1000)
    mixed = {
        "https://github.com/G-Eskayo/marvin/pull/old": {
            "id": "very-old",
            "stage": "tests",
            "startedAt": now_ms - 40 * 60 * 1000  # 40 min ago, stale
        },
        "https://github.com/G-Eskayo/marvin/pull/done": {
            "id": "just-done",
            "stage": "done",
            "startedAt": now_ms - 5 * 60 * 1000  # 5 min ago, but done
        },
        "https://github.com/G-Eskayo/marvin/pull/active": {
            "id": "active-merge",
            "stage": "tests",
            "startedAt": now_ms - 2 * 60 * 1000  # 2 min ago, active
        }
    }
    file_with_mixed.write_text(json.dumps(mixed))
    # Should be True because there's one active recent merge
    assert wr.merge_inflight(path=file_with_mixed, max_age_ms=30 * 60 * 1000) is True


def test_merge_inflight_entry_without_startedAt_is_treated_as_active(tmp_path):
    # If an entry doesn't have startedAt, treat it as active (fail-open).
    # We can't tell when it started, so assume a merge is in progress.
    file_with_no_timestamp = tmp_path / "merge-inflight.json"
    import json
    no_timestamp_entry = {
        "https://github.com/G-Eskayo/marvin/pull/notimestamp": {
            "id": "no-timestamp",
            "stage": "tests"
            # Missing startedAt
        }
    }
    file_with_no_timestamp.write_text(json.dumps(no_timestamp_entry))
    # Should be True because we can't determine age, so assume merge is active
    assert wr.merge_inflight(path=file_with_no_timestamp, max_age_ms=30 * 60 * 1000) is True
