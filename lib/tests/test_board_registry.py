"""Tests for board_registry.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_board_registry.py -v
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import board_registry as br  # noqa: E402


def test_ensure_board_creates_an_entry_once(tmp_path):
    path = tmp_path / "registry.json"
    first = br.ensure_board("G-Eskayo/clarity-captions", path=path)
    second = br.ensure_board("G-Eskayo/clarity-captions", path=path)
    assert first["created"] is True
    assert second["created"] is False
    boards = json.loads(path.read_text())["boards"]
    assert [b["repo"] for b in boards] == ["G-Eskayo/clarity-captions"]


def test_default_name_is_the_repo_name(tmp_path):
    entry = br.ensure_board("G-Eskayo/killer-sudoku", path=tmp_path / "r.json")["board"]
    assert entry["name"] == "killer-sudoku"
    assert "addedAt" in entry


def test_existing_board_keeps_its_fields_but_accepts_new_due(tmp_path):
    path = tmp_path / "r.json"
    br.ensure_board("o/r", name="Pretty", path=path)
    entry = br.ensure_board("o/r", due="2026-10-25", due_hard=True, path=path)["board"]
    assert entry["name"] == "Pretty"
    assert entry["due"] == "2026-10-25" and entry["dueHard"] is True


def test_rejects_malformed_repo(tmp_path):
    for bad in ("", "noslash", "a/b/c", "a b/c"):
        try:
            br.ensure_board(bad, path=tmp_path / "r.json")
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")


def test_corrupt_registry_is_preserved_not_clobbered(tmp_path):
    path = tmp_path / "r.json"
    path.write_text("{not json")
    try:
        br.ensure_board("o/r", path=path)
    except ValueError:
        pass
    else:
        raise AssertionError("should refuse to overwrite a corrupt registry")
    assert path.read_text() == "{not json"


def test_discover_registers_repos_that_use_the_pipeline_labels(tmp_path):
    labels = {"o/with": ["ready-for-agent", "bug"], "o/without": ["bug"], "o/old": ["ready-for-agent"]}

    def gh(args):
        if args[:2] == ["repo", "list"]:
            return json.dumps([{"nameWithOwner": "o/with", "isArchived": False},
                               {"nameWithOwner": "o/without", "isArchived": False},
                               {"nameWithOwner": "o/old", "isArchived": True}])
        repo = args[args.index("--repo") + 1]
        if args[0] == "issue":
            return "[]"  # these repos have no tickets at all; only the labels decide
        return json.dumps([{"name": n} for n in labels[repo]])

    path = tmp_path / "r.json"
    assert br.discover("o", gh=gh, path=path) == ["o/with"]
    assert br.discover("o", gh=gh, path=path) == []  # already registered: nothing new
    assert [b["repo"] for b in br.list_boards(path)] == ["o/with"]


def test_discover_survives_a_failing_repo_and_a_failing_gh(tmp_path):
    def gh(args):
        raise RuntimeError("offline")

    assert br.discover("o", gh=gh, path=tmp_path / "r.json") == []


def test_discover_also_registers_repos_that_have_tickets_but_no_pipeline_label(tmp_path):
    issues = {"o/tracked": [{"number": 1}], "o/empty": []}

    def gh(args):
        if args[:2] == ["repo", "list"]:
            return json.dumps([{"nameWithOwner": r, "isArchived": False} for r in issues])
        repo = args[args.index("--repo") + 1]
        if args[0] == "label":
            return json.dumps([{"name": "bug"}])  # no ready-for-agent anywhere
        return json.dumps(issues[repo])  # `issue list`

    assert br.discover("o", gh=gh, path=tmp_path / "r.json") == ["o/tracked"]


def test_discover_also_registers_the_extra_repos_it_is_given_even_without_tickets(tmp_path):
    def gh(args):
        if args[:2] == ["repo", "list"]:
            return json.dumps([{"nameWithOwner": "o/quiet", "isArchived": False}, {"nameWithOwner": "o/other", "isArchived": False}])
        if args[0] == "label":
            return json.dumps([{"name": "bug"}])
        return "[]"  # no tickets anywhere

    path = tmp_path / "r.json"
    assert br.discover("o", gh=gh, path=path, extra_repos=["o/quiet"]) == ["o/quiet"]
    assert [b["repo"] for b in br.list_boards(path)] == ["o/quiet"]


def test_extra_repos_are_not_registered_twice_or_when_malformed(tmp_path):
    def gh(args):
        if args[:2] == ["repo", "list"]:
            return json.dumps([])
        return "[]"

    path = tmp_path / "r.json"
    br.discover("o", gh=gh, path=path, extra_repos=["o/a", "not a repo", "o/a"])
    assert [b["repo"] for b in br.list_boards(path)] == ["o/a"]


def test_archiving_a_repo_on_github_retires_its_board(tmp_path):
    """2026-10-08: Personal-Website and Portfolio_Website (old versions of the portfolio site) kept their boards, so the
    hourly onboarding added labels to them. Archiving a repo on GitHub now takes it off the dashboard too."""
    path = tmp_path / "r.json"
    br.ensure_board("o/old-site", path=path)
    br.ensure_board("o/live", path=path)

    def gh(args):
        if args[:2] == ["repo", "list"]:
            return json.dumps([{"nameWithOwner": "o/old-site", "isArchived": True},
                               {"nameWithOwner": "o/live", "isArchived": False}])
        return "[]"
    br.discover("o", gh=gh, path=path)
    assert [b["repo"] for b in br.list_boards(path)] == ["o/live"]


def test_a_failed_repo_list_retires_nothing(tmp_path):
    path = tmp_path / "r.json"
    br.ensure_board("o/live", path=path)
    def gh(args):
        raise RuntimeError("offline")
    br.discover("o", gh=gh, path=path)
    assert [b["repo"] for b in br.list_boards(path)] == ["o/live"]


# ── archive lifecycle (ADR 0060, #299) ──────────────────────────────────────

from datetime import datetime, timedelta, timezone  # noqa: E402

NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)


def _ago(days):
    return (NOW - timedelta(days=days)).isoformat()


def _snap(open_issues=0, open_prs=0):
    return {"issues": [{"number": i} for i in range(open_issues)], "prs": [{"number": i} for i in range(open_prs)]}


def test_a_board_with_nothing_open_and_quiet_for_14_days_is_finished(tmp_path):
    path = tmp_path / "r.json"
    br.ensure_board("o/done", path=path)
    out = br.update_lifecycle({"o/done": _snap()}, last_activity=lambda repo: _ago(15), now=NOW, path=path)
    assert out == {"finished": ["o/done"], "reopened": []}
    assert br.list_boards(path)[0]["finishedAt"] == NOW.isoformat()


def test_not_finished_while_anything_is_open_or_it_was_busy_recently(tmp_path):
    path = tmp_path / "r.json"
    for r in ("o/open", "o/pr", "o/recent", "o/never"):
        br.ensure_board(r, path=path)
    acts = {"o/open": _ago(30), "o/pr": _ago(30), "o/recent": _ago(3), "o/never": None}
    out = br.update_lifecycle({"o/open": _snap(open_issues=1), "o/pr": _snap(open_prs=1), "o/recent": _snap(), "o/never": _snap()},
                              last_activity=acts.get, now=NOW, path=path)
    assert out["finished"] == []  # a board that never had a ticket is empty, not finished


def test_new_work_reopens_a_finished_board(tmp_path):
    path = tmp_path / "r.json"
    br.ensure_board("o/back", path=path)
    br.update_lifecycle({"o/back": _snap()}, last_activity=lambda r: _ago(20), now=NOW, path=path)
    later = NOW + timedelta(days=5)
    out = br.update_lifecycle({"o/back": _snap(open_issues=1)}, last_activity=lambda r: _ago(20), now=later, path=path)
    assert out["reopened"] == ["o/back"] and "finishedAt" not in br.list_boards(path)[0]


def test_a_push_after_finishing_also_reopens(tmp_path):
    path = tmp_path / "r.json"
    br.ensure_board("o/push", path=path)
    br.update_lifecycle({"o/push": _snap()}, last_activity=lambda r: _ago(20), now=NOW, path=path)
    later = NOW + timedelta(days=2)
    out = br.update_lifecycle({"o/push": _snap()}, last_activity=lambda r: (NOW + timedelta(days=1)).isoformat(), now=later, path=path)
    assert out["reopened"] == ["o/push"]


def test_repos_missing_from_the_snapshot_are_left_alone(tmp_path):
    path = tmp_path / "r.json"
    br.ensure_board("o/offline", path=path)
    out = br.update_lifecycle({}, last_activity=lambda r: _ago(99), now=NOW, path=path)
    assert out == {"finished": [], "reopened": []}


# ── check before a new board ────────────────────────────────────────────────

CANDIDATES = [
    {"id": "killer-sudoku", "name": "killer-sudoku", "repo": "o/killer-sudoku", "description": "a sudoku game", "status": "archived"},
    {"id": "finance-os", "name": "finance-os", "repo": "o/finance-os", "description": "budgeting", "status": "active"},
    {"id": "clarity-captions", "name": "clarity-captions", "repo": "o/clarity-captions", "description": "", "status": "active"},
]


def test_a_shared_name_word_is_a_close_match_even_without_embeddings():
    res = br.similar("live captions for my mom", CANDIDATES, embed=lambda text, task: None)
    assert res[0]["id"] == "clarity-captions" and res[0]["close"] is True
    assert "captions" in res[0]["why"]


def test_meaning_counts_only_when_it_clearly_leads():
    vec = {"q": [1.0, 0.0], "killer-sudoku": [0.8, 0.6], "finance-os": [0.3, 0.95], "clarity-captions": [0.2, 0.98]}

    def embed(text, task):
        return vec["q"] if task == "query" else vec[text.split(".")[0]]

    res = br.similar("a puzzle game", CANDIDATES, embed=embed)
    assert res[0]["id"] == "killer-sudoku" and res[0]["close"] is True and res[0]["status"] == "archived"
    tie = {"q": [1.0, 0.0], "killer-sudoku": [0.7, 0.71], "finance-os": [0.69, 0.72], "clarity-captions": [0.0, 1.0]}
    res = br.similar("a chess engine", CANDIDATES, embed=lambda t, k: tie["q"] if k == "query" else tie[t.split(".")[0]])
    assert not any(r["close"] for r in res)


def test_nothing_alike_means_no_close_match_and_at_most_three_shown():
    res = br.similar("weather station", CANDIDATES, embed=lambda t, k: None)
    assert len(res) <= 3 and not any(r["close"] for r in res)


def test_candidates_merge_boards_and_catalog_including_archived_ones():
    boards = [{"repo": "o/killer-sudoku", "name": "killer-sudoku", "finishedAt": "2026-10-01"}, {"repo": "o/new", "name": "new"}]
    catalog = [{"id": "killer-sudoku", "name": "killer-sudoku", "repo": "o/killer-sudoku", "description": "a sudoku game", "status": "recent"},
               {"id": "old-site", "name": "Old Site", "repo": None, "description": "", "status": "archived"}]
    cands = br.candidates(boards, catalog)
    by = {c["id"]: c for c in cands}
    assert by["killer-sudoku"]["status"] == "archived"  # a finished board counts as archived
    assert by["killer-sudoku"]["description"] == "a sudoku game"
    assert set(by) == {"killer-sudoku", "new", "old-site"}
