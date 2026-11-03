"""Tests for trust_ramp.py (ADR 0064, #340): a project earns auto-merge with 5 clean PRs Gil approved.
Written to break it (ADR 0063): repeats, two events at once, out-of-order and unknown events, manual merges, renamed
repos, a corrupt or missing state file, and a revert of an older PR.

    ~/.agents/venv/bin/python -m pytest lib/tests/test_trust_ramp.py -v
"""
from __future__ import annotations
import json
import sys
import threading

import pytest
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


# ── per-author ramps (ADR 0069 rule 5, #952): the box's bot account earns auto-merge like a project does ──────────

BOT = "MARVIN-bot-gil"


def approve_author(path, login, pr, repo=""):
    return tr.record_author(login, pr, "approved-merge", path=path, repo=repo)


def test_an_author_ramp_starts_closed_and_four_approvals_still_leave_it_closed(tmp_path):
    s = tmp_path / "ramp.json"
    assert not tr.author_is_open(BOT, path=s)
    for pr in range(1, 5):
        approve_author(s, BOT, pr)
    assert not tr.author_is_open(BOT, path=s)
    approve_author(s, BOT, 5)
    assert tr.author_is_open(BOT, path=s)


def test_an_author_ramp_never_starts_open_even_for_the_owner(tmp_path):
    s = tmp_path / "ramp.json"
    assert not tr.author_is_open("G-Eskayo", path=s)


def test_a_deny_at_four_resets_the_author_to_zero(tmp_path):
    for kind in ("deny", "revert", "break"):
        s = tmp_path / f"{kind}.json"
        for pr in range(1, 5):
            approve_author(s, BOT, pr)
        tr.record_author(BOT, 9, kind, path=s, reason="wrong file")
        st = tr.status(path=s)["@" + BOT]
        assert st["streak"] == 0 and not st["open"] and st["last_reset"]["event"] == kind, kind
        for pr in range(10, 14):
            approve_author(s, BOT, pr)
        assert not tr.author_is_open(BOT, path=s), kind


def test_author_logins_compare_case_insensitively(tmp_path):
    s = tmp_path / "ramp.json"
    for pr, login in enumerate(["marvin-bot-gil", "MARVIN-BOT-GIL", "Marvin-Bot-Gil", BOT, "mArViN-bOt-GiL"], 1):
        approve_author(s, login, pr)
    assert tr.author_is_open(BOT, path=s) and tr.author_is_open("marvin-bot-gil", path=s)
    assert len([k for k in tr.status(path=s) if k.lower() == "@marvin-bot-gil"]) == 1


def test_the_same_author_event_twice_counts_once_but_other_repos_same_number_count(tmp_path):
    s = tmp_path / "ramp.json"
    for _ in range(5):
        approve_author(s, BOT, 7)
        approve_author(s, BOT.upper(), 7)
    assert tr.status(path=s)["@" + BOT]["streak"] == 1
    approve_author(s, BOT, 7, repo="G-Eskayo/marvin")
    approve_author(s, BOT, 7, repo="G-Eskayo/finance-os")
    approve_author(s, BOT, 7, repo="g-eskayo/MARVIN")            # same repo, other case: a repeat
    assert tr.status(path=s)["@" + BOT]["streak"] == 3


def test_an_out_of_order_approval_after_a_deny_counts_from_zero(tmp_path):
    s = tmp_path / "ramp.json"
    for pr in (5, 3, 4):
        approve_author(s, BOT, pr)
    tr.record_author(BOT, 1, "deny", path=s)                    # an older PR denied late still resets
    approve_author(s, BOT, 2)
    assert tr.status(path=s)["@" + BOT]["streak"] == 1


def test_manual_merges_and_unknown_author_events(tmp_path):
    s = tmp_path / "ramp.json"
    for pr in range(1, 10):
        tr.record_author(BOT, pr, "manual-merge", path=s)
    assert not tr.author_is_open(BOT, path=s) and tr.status(path=s)["@" + BOT]["streak"] == 0
    with pytest.raises(ValueError):
        tr.record_author(BOT, 2, "nonsense", path=s)


@pytest.mark.parametrize("login", ["", "-bot", "bot-", "a--b", "a b", "a/b", "x" * 40, "bøt", " MARVIN-bot-gil",
                                   None, 5, "MARVIN-bot-gil\n"])
def test_a_bad_login_is_refused_and_never_open(tmp_path, login):
    s = tmp_path / "ramp.json"
    with pytest.raises(ValueError):
        tr.record_author(login, 1, "approved-merge", path=s)
    assert not tr.author_is_open(login, path=s)
    assert not s.exists()


def test_a_bot_suffix_login_is_accepted():
    tr._author_key("dependabot[bot]")


@pytest.mark.parametrize("pr", [0, -1, "3", True, 1.0])
def test_a_bad_pr_number_is_refused_for_authors(tmp_path, pr):
    with pytest.raises(ValueError):
        tr.record_author(BOT, pr, "approved-merge", path=tmp_path / "r.json")


def test_a_corrupt_file_closes_every_author_and_is_not_overwritten(tmp_path):
    s = tmp_path / "ramp.json"
    for pr in range(1, 6):
        approve_author(s, BOT, pr)
    assert tr.author_is_open(BOT, path=s)
    for bad in ("{not json", json.dumps({"repos": {}, "authors": "nope"}), json.dumps({"repos": {}, "authors": []}),
                json.dumps([1])):
        s.write_text(bad)
        assert not tr.author_is_open(BOT, path=s), bad
        with pytest.raises(ValueError):
            approve_author(s, BOT, 99)
        assert s.read_text() == bad
        assert tr.status(path=s) == {}


def test_a_missing_file_means_closed_for_authors(tmp_path):
    assert not tr.author_is_open(BOT, path=tmp_path / "nowhere" / "ramp.json")


def test_a_malformed_author_entry_is_closed_not_a_crash(tmp_path):
    s = tmp_path / "ramp.json"
    s.write_text(json.dumps({"repos": {}, "authors": {"marvin-bot-gil": {"streak": "9"}}}))
    assert not tr.author_is_open(BOT, path=s)
    s.write_text(json.dumps({"repos": {}, "authors": {"marvin-bot-gil": {"streak": True}}}))
    assert not tr.author_is_open(BOT, path=s)


def test_author_and_repo_ramps_are_separate_namespaces(tmp_path):
    s = tmp_path / "ramp.json"
    for pr in range(1, 6):
        approve(s, P, pr)
    assert tr.is_open(P, path=s) and not tr.author_is_open(BOT, path=s)
    for pr in range(1, 6):
        approve_author(s, BOT, pr)
    tr.record(P, 50, "deny", path=s)
    assert tr.author_is_open(BOT, path=s) and not tr.is_open(P, path=s)
    data = json.loads(s.read_text())
    assert set(data["authors"]) == {"marvin-bot-gil"} and "marvin-bot-gil" not in data["repos"]


def test_an_old_file_without_authors_still_works_and_keeps_its_repos(tmp_path):
    s = tmp_path / "ramp.json"
    for pr in range(1, 6):
        approve(s, P, pr)
    data = json.loads(s.read_text())
    data.pop("authors", None)
    s.write_text(json.dumps(data))
    approve_author(s, BOT, 1)
    assert tr.is_open(P, path=s) and tr.status(path=s)["@" + BOT]["streak"] == 1


def test_two_writers_at_once_both_land_for_authors_and_repos(tmp_path):
    s = tmp_path / "ramp.json"
    threads = [threading.Thread(target=approve_author, args=(s, BOT, pr)) for pr in range(1, 21)]
    threads += [threading.Thread(target=approve, args=(s, P, pr)) for pr in range(1, 21)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    st = tr.status(path=s)
    assert st["@" + BOT]["streak"] == 20 and st[P]["streak"] == 20


def test_two_processes_at_once_both_land(tmp_path):
    import subprocess
    s = tmp_path / "ramp.json"
    lib = Path(__file__).resolve().parents[1]
    code = ("import sys; sys.path.insert(0, %r); import trust_ramp as tr\n"
            "for pr in range(int(sys.argv[1]), int(sys.argv[1]) + 15): tr.record_author('MARVIN-bot-gil', pr, 'approved-merge', path=%r)")
    procs = [subprocess.Popen([sys.executable, "-c", code % (str(lib), str(s)), str(start)]) for start in (1, 100, 200)]
    assert all(p.wait(60) == 0 for p in procs)
    assert tr.status(path=s)["@" + BOT]["streak"] == 45


def test_status_lists_author_ramps_and_the_cli_prints_them(tmp_path, monkeypatch, capsys):
    s = tmp_path / "ramp.json"
    approve_author(s, BOT, 1)
    monkeypatch.setattr(tr, "STATE_PATH", s)
    tr.main(["status"])
    out = capsys.readouterr().out
    assert "@" + BOT in out and "1/5" in out and "closed" in out
