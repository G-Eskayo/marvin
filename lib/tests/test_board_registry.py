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
