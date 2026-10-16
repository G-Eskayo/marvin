"""Tests for proposals.py (the Proposals store, #531 / #102, ADR 0068). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_proposals.py -v

Every test uses a temp store root (and a temp HOME for the CLI): never the real ~/.claude.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import proposals as p  # noqa: E402

TODAY = date(2026, 10, 15)


def idea(**over):
    base = {
        "title": "Hand small jobs to the local model",
        "problem": "Every job uses a full Claude call.",
        "fix": "Send simple jobs to the local model on the Mini.",
        "why": "Same quality for fewer tokens.",
        "size": "Large", "area": "Cost", "north_star": 1, "source": "Research colony",
        "technical": "Route classifier + Ollama on mac-mini-1.",
    }
    base.update(over)
    return base


class FakeGh:
    def __init__(self, rc=0, out="https://github.com/G-Eskayo/marvin/issues/777\n", err=""):
        self.rc, self.out, self.err, self.calls = rc, out, err, []

    def __call__(self, args, body):
        self.calls.append((args, body))
        return self.rc, self.out, self.err


@pytest.fixture
def root(tmp_path):
    return tmp_path / "proposals"


# --- adding ---------------------------------------------------------------------------------------------------------

def test_add_then_list_round_trip(root):
    added = p.add(root, idea(), today=TODAY)
    listed = p.load_all(root, today=TODAY)
    assert [x["id"] for x in listed["proposals"]] == [added["id"]]
    got = listed["proposals"][0]
    assert got["status"] == {"state": "open"} and got["added"] == "2026-10-15"
    assert got["north_star_name"] == "Minimise resources"


@pytest.mark.parametrize("field", ["title", "problem", "fix", "why", "north_star"])
def test_add_rejects_a_proposal_missing_a_required_field(root, field):
    bad = idea()
    del bad[field]
    with pytest.raises(p.ProposalError):
        p.add(root, bad, today=TODAY)
    assert not root.exists() or not list(root.glob("*.json"))


@pytest.mark.parametrize("over", [
    {"north_star": 0}, {"north_star": 5}, {"north_star": "1"}, {"north_star": True},
    {"size": "Huge"}, {"title": "   "}, {"problem": "x" * 601}, {"title": "t" * 141},
    {"technical": "x" * 5001}, {"area": 7},
])
def test_add_rejects_invalid_values(root, over):
    with pytest.raises(p.ProposalError):
        p.add(root, idea(**over), today=TODAY)


def test_same_title_twice_gets_distinct_ids(root):
    a = p.add(root, idea(), today=TODAY)
    b = p.add(root, idea(), today=TODAY)
    assert a["id"] != b["id"]
    assert len(p.load_all(root, today=TODAY)["proposals"]) == 2


def test_hostile_title_makes_a_safe_id(root):
    a = p.add(root, idea(title="../../etc/passwd; rm -rf ~ `x`"), today=TODAY)
    assert p.ID_RE.fullmatch(a["id"])
    assert (root / f"{a['id']}.json").exists()


def test_title_with_no_usable_characters_still_gets_an_id(root):
    a = p.add(root, idea(title="✨✨✨"), today=TODAY)
    assert p.ID_RE.fullmatch(a["id"])


# --- reading a damaged store ------------------------------------------------------------------------------------------

def test_missing_store_is_empty_not_an_error(root):
    assert p.load_all(root, today=TODAY) == {"proposals": [], "problems": []}


def test_malformed_and_non_object_files_are_reported_not_hidden(root):
    p.add(root, idea(), today=TODAY)
    (root / "broken.json").write_text("{not json")
    (root / "list.json").write_text("[1, 2]")
    (root / "invalid.json").write_text(json.dumps({"id": "invalid", "title": "x"}))
    out = p.load_all(root, today=TODAY)
    assert len(out["proposals"]) == 1
    assert sorted(x["file"] for x in out["problems"]) == ["broken.json", "invalid.json", "list.json"]


def test_huge_file_is_skipped_and_reported(root):
    root.mkdir(parents=True)
    (root / "huge.json").write_text("x" * (p.MAX_FILE_BYTES + 1))
    out = p.load_all(root, today=TODAY)
    assert out["proposals"] == [] and out["problems"][0]["file"] == "huge.json"


def test_symlink_out_of_the_store_is_ignored(root, tmp_path):
    root.mkdir(parents=True)
    outside = tmp_path / "secret.json"
    outside.write_text(json.dumps({**idea(id="secret"), "added": "2026-10-01", "status": {"state": "open"}}))
    (root / "secret.json").symlink_to(outside)
    out = p.load_all(root, today=TODAY)
    assert out["proposals"] == []
    assert out["problems"][0]["file"] == "secret.json"


def test_newest_first(root):
    a = p.add(root, idea(title="old one"), today=date(2026, 10, 1))
    b = p.add(root, idea(title="new one"), today=date(2026, 10, 14))
    assert [x["id"] for x in p.load_all(root, today=TODAY)["proposals"]] == [b["id"], a["id"]]


# --- actions ---------------------------------------------------------------------------------------------------------

def test_make_ticket_files_issue_and_marks_ticketed(root):
    a = p.add(root, idea(), today=TODAY)
    gh = FakeGh()
    out = p.act(root, a["id"], "ticket", {}, gh=gh, today=TODAY)
    assert out["status"]["state"] == "ticketed" and out["status"]["ticket"] == 777
    args, body = gh.calls[0]
    assert "needs-triage" in args and "project:marvin" in args
    assert "Every job uses a full Claude call." in body and a["id"] in body
    assert p.load_all(root, today=TODAY)["proposals"] == []  # ticketed leaves the list


def test_gh_failure_leaves_proposal_untouched(root):
    a = p.add(root, idea(), today=TODAY)
    with pytest.raises(p.ProposalError, match="gh"):
        p.act(root, a["id"], "ticket", {}, gh=FakeGh(rc=1, out="https://github.com/G-Eskayo/marvin/issues/5\n", err="HTTP 502"), today=TODAY)
    assert p.load_all(root, today=TODAY)["proposals"][0]["status"] == {"state": "open"}


def test_gh_success_with_unparseable_output_is_an_error_not_a_fake_ticket(root):
    a = p.add(root, idea(), today=TODAY)
    with pytest.raises(p.ProposalError):
        p.act(root, a["id"], "ticket", {}, gh=FakeGh(out="something odd"), today=TODAY)
    assert p.load_all(root, today=TODAY)["proposals"][0]["status"] == {"state": "open"}


def test_snooze_hides_until_the_date_then_returns_with_a_reason(root):
    a = p.add(root, idea(), today=TODAY)
    p.act(root, a["id"], "snooze", {"days": 7}, today=TODAY)
    assert p.load_all(root, today=date(2026, 10, 21))["proposals"] == []
    back = p.load_all(root, today=date(2026, 10, 22))["proposals"]
    assert back[0]["id"] == a["id"] and "snooze" in back[0]["returned"].lower()


@pytest.mark.parametrize("days", [0, -1, 366, "7", 1.5, None, True])
def test_snooze_rejects_bad_days(root, days):
    a = p.add(root, idea(), today=TODAY)
    with pytest.raises(p.ProposalError):
        p.act(root, a["id"], "snooze", {"days": days}, today=TODAY)


def test_dismiss_needs_a_real_reason_and_keeps_it(root):
    a = p.add(root, idea(), today=TODAY)
    for bad in ["", "   ", None, "x" * 1001]:
        with pytest.raises(p.ProposalError):
            p.act(root, a["id"], "dismiss", {"reason": bad}, today=TODAY)
    out = p.act(root, a["id"], "dismiss", {"reason": "Already covered by the Mini migration"}, today=TODAY)
    assert out["status"] == {"state": "dismissed", "reason": "Already covered by the Mini migration", "on": "2026-10-15"}
    assert p.load_all(root, today=date(2030, 1, 1))["proposals"] == []  # dismissed for good


def test_until_ticket_then_backup_date_brings_it_back(root):
    a = p.add(root, idea(), today=TODAY)
    p.act(root, a["id"], "until", {"ticket": 123, "backup": "2027-01-15"}, today=TODAY)
    assert p.load_all(root, today=date(2027, 1, 14))["proposals"] == []
    back = p.load_all(root, today=date(2027, 1, 15))["proposals"][0]
    assert "2027-01-15" in back["returned"]


def test_until_text_is_stored(root):
    a = p.add(root, idea(), today=TODAY)
    out = p.act(root, a["id"], "until", {"text": "the local model runs on both Macs", "backup": "2027-01-15"}, today=TODAY)
    assert out["status"]["text"] == "the local model runs on both Macs" and "ticket" not in out["status"]


def test_until_create_ticket_files_the_prerequisite_and_links_it(root):
    a = p.add(root, idea(), today=TODAY)
    gh = FakeGh(out="https://github.com/G-Eskayo/marvin/issues/900\n")
    out = p.act(root, a["id"], "until", {"create_ticket": "Run Ollama on both Macs", "backup": "2027-01-15"}, gh=gh, today=TODAY)
    assert out["status"]["ticket"] == 900
    assert "Run Ollama on both Macs" in gh.calls[0][0]


@pytest.mark.parametrize("args", [
    {"backup": "2027-01-15"},                                        # neither ticket nor text
    {"ticket": 1, "text": "x", "backup": "2027-01-15"},              # both
    {"ticket": 0, "backup": "2027-01-15"}, {"ticket": "12", "backup": "2027-01-15"},
    {"text": "  ", "backup": "2027-01-15"}, {"text": "x" * 501, "backup": "2027-01-15"},
    {"ticket": 5},                                                   # no backup
    {"ticket": 5, "backup": "2026-10-15"},                           # not in the future
    {"ticket": 5, "backup": "2029-01-01"},                           # more than 2 years out
    {"ticket": 5, "backup": "15/01/2027"}, {"ticket": 5, "backup": "2027-02-30"},
])
def test_until_rejects_bad_input(root, args):
    a = p.add(root, idea(), today=TODAY)
    with pytest.raises(p.ProposalError):
        p.act(root, a["id"], "until", args, gh=FakeGh(), today=TODAY)
    assert p.load_all(root, today=TODAY)["proposals"][0]["status"] == {"state": "open"}


@pytest.mark.parametrize("pid", ["../x", "nope", "", "a/b", "A B", "x" * 200])
def test_act_on_unknown_or_hostile_id_fails_safely(root, pid):
    p.add(root, idea(), today=TODAY)
    with pytest.raises(p.ProposalError):
        p.act(root, pid, "dismiss", {"reason": "r"}, today=TODAY)


def test_unknown_action_rejected(root):
    a = p.add(root, idea(), today=TODAY)
    with pytest.raises(p.ProposalError):
        p.act(root, a["id"], "delete", {}, today=TODAY)


def test_cannot_act_twice_on_a_closed_proposal(root):
    a = p.add(root, idea(), today=TODAY)
    p.act(root, a["id"], "dismiss", {"reason": "no"}, today=TODAY)
    with pytest.raises(p.ProposalError, match="isn't open"):
        p.act(root, a["id"], "ticket", {}, gh=FakeGh(), today=TODAY)


def test_returned_snooze_can_be_acted_on_again(root):
    a = p.add(root, idea(), today=TODAY)
    p.act(root, a["id"], "snooze", {"days": 1}, today=TODAY)
    out = p.act(root, a["id"], "dismiss", {"reason": "later no"}, today=date(2026, 10, 20))
    assert out["status"]["state"] == "dismissed"


def test_every_action_is_kept_in_history(root):
    a = p.add(root, idea(), today=TODAY)
    p.act(root, a["id"], "snooze", {"days": 1}, today=TODAY)
    p.act(root, a["id"], "dismiss", {"reason": "nah"}, today=date(2026, 10, 20))
    raw = json.loads((root / f"{a['id']}.json").read_text())
    assert [h["state"] for h in raw["history"]] == ["snoozed", "dismissed"]


def test_concurrent_actions_never_corrupt_the_file(root):
    a = p.add(root, idea(), today=TODAY)
    results = []

    def go(i):
        try:
            p.act(root, a["id"], "dismiss", {"reason": f"r{i}"}, today=TODAY)
            results.append("ok")
        except p.ProposalError:
            results.append("refused")

    threads = [threading.Thread(target=go, args=(i,)) for i in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1  # exactly one wins, the rest see it isn't open
    json.loads((root / f"{a['id']}.json").read_text())  # still valid JSON
    assert not list(root.glob("*.tmp"))


# --- CLI (what the dashboard calls) ----------------------------------------------------------------------------------

def run_cli(home, *args):
    env = {**os.environ, "HOME": str(home)}
    out = subprocess.run([sys.executable, str(LIB / "proposals.py"), *args], capture_output=True, text=True, env=env)
    return out.returncode, json.loads(out.stdout)


def test_cli_list_and_act_use_home_store(tmp_path):
    root = tmp_path / ".claude" / "proposals"
    a = p.add(root, idea(), today=date.today())
    rc, out = run_cli(tmp_path, "list")
    assert rc == 0 and out["proposals"][0]["id"] == a["id"]
    rc, out = run_cli(tmp_path, "act", a["id"], "snooze", "--json", json.dumps({"days": 7}))
    assert rc == 0 and out["ok"] and out["proposal"]["status"]["state"] == "snoozed"


def test_cli_errors_are_json_with_nonzero_exit(tmp_path):
    rc, out = run_cli(tmp_path, "act", "../evil", "dismiss", "--json", json.dumps({"reason": "x"}))
    assert rc == 1 and out["ok"] is False and out["error"]
    rc, out = run_cli(tmp_path, "act", "x", "dismiss", "--json", "{not json")
    assert rc == 1 and out["ok"] is False


def test_cli_add_from_json(tmp_path):
    rc, out = run_cli(tmp_path, "add", "--json", json.dumps(idea()))
    assert rc == 0 and out["ok"] and (tmp_path / ".claude" / "proposals" / f"{out['proposal']['id']}.json").exists()
