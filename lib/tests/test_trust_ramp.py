"""Tests for trust_ramp.py (ADR 0064, #340): a project earns auto-merge with 5 clean PRs Gil approved.
Written to break it (ADR 0063): repeats, two events at once, out-of-order and unknown events, manual merges, renamed
repos, a corrupt or missing state file, and a revert of an older PR.

    ~/.agents/venv/bin/python -m pytest lib/tests/test_trust_ramp.py -v
"""
from __future__ import annotations
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import trust_ramp as tr  # noqa: E402

P = "G-Eskayo/portfolio-website-updater"
M = "G-Eskayo/marvin"


def approve(path, repo, pr):
    return tr.record(repo, pr, "approved-merge", path=path)


def test_a_new_project_starts_closed_and_opens_after_five_clean_approvals(tmp_path):
    s = tmp_path / "ramp.json"
    assert not tr.is_open(P, path=s)
    for pr in range(1, 5):
        approve(s, P, pr)
    assert not tr.is_open(P, path=s) and tr.status(path=s)[P]["streak"] == 4
    approve(s, P, 5)
    assert tr.is_open(P, path=s)


def test_marvin_starts_open_and_a_revert_closes_it_until_five_clean(tmp_path):
    s = tmp_path / "ramp.json"
    assert tr.is_open(M, path=s)
    tr.record(M, 300, "revert", path=s, reason="UI looked wrong")
    assert not tr.is_open(M, path=s) and tr.status(path=s)[M]["last_reset"]["reason"] == "UI looked wrong"
    for pr in range(301, 306):
        approve(s, M, pr)
    assert tr.is_open(M, path=s)


def test_any_deny_revert_or_break_resets_to_zero(tmp_path):
    for kind in ("deny", "revert", "break"):
        s = tmp_path / f"{kind}.json"
        for pr in range(1, 6):
            approve(s, P, pr)
        tr.record(P, 9, kind, path=s)
        assert tr.status(path=s)[P]["streak"] == 0 and not tr.is_open(P, path=s), kind


def test_the_same_event_twice_counts_once(tmp_path):
    s = tmp_path / "ramp.json"
    for _ in range(5):
        approve(s, P, 1)
    assert tr.status(path=s)[P]["streak"] == 1


def test_a_revert_of_an_older_pr_still_resets_this_projects_ramp(tmp_path):
    s = tmp_path / "ramp.json"
    for pr in range(10, 16):
        approve(s, P, pr)
    tr.record(P, 10, "revert", path=s)
    assert not tr.is_open(P, path=s)


def test_manual_merges_and_unknown_events_do_not_count(tmp_path):
    s = tmp_path / "ramp.json"
    tr.record(P, 1, "manual-merge", path=s)
    assert tr.status(path=s).get(P, {}).get("streak", 0) == 0
    try:
        tr.record(P, 2, "nonsense", path=s)
        assert False, "an unknown event must be refused"
    except ValueError:
        pass


def test_a_corrupt_or_missing_state_file_means_closed_even_for_marvin(tmp_path):
    s = tmp_path / "ramp.json"
    s.write_text("{not json")
    assert not tr.is_open(M, path=s) and not tr.is_open(P, path=s)
    s.write_text(json.dumps({"repos": "not a dict"}))
    assert not tr.is_open(M, path=s)


def test_a_corrupt_file_is_never_overwritten_by_a_new_event(tmp_path):
    s = tmp_path / "ramp.json"
    s.write_text("{not json")
    try:
        approve(s, P, 1)
        assert False, "recording onto a corrupt file must refuse, not reset history"
    except ValueError:
        pass
    assert s.read_text() == "{not json"


def test_two_events_at_once_both_land(tmp_path):
    s = tmp_path / "ramp.json"
    threads = [threading.Thread(target=approve, args=(s, P, pr)) for pr in range(1, 21)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert tr.status(path=s)[P]["streak"] == 20


def test_repo_names_are_matched_case_insensitively(tmp_path):
    s = tmp_path / "ramp.json"
    for pr in range(1, 6):
        approve(s, "g-eskayo/Portfolio-Website-Updater", pr)
    assert tr.is_open(P, path=s)


def test_a_bad_repo_or_pr_number_is_refused(tmp_path):
    s = tmp_path / "ramp.json"
    for repo, pr in (("", 1), ("noslash", 1), (P, 0), (P, -3), (P, "7")):
        try:
            tr.record(repo, pr, "approved-merge", path=s)
            assert False, (repo, pr)
        except ValueError:
            pass
