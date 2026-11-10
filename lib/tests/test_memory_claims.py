"""Memory claims checked (marvin#1225): a note that asserts open state ("OPEN", "QUEUED", "URGENT", "awaiting")
about work that's finished gets flagged once a day, with an `invalid_at` suggestion, and its MEMORY.md index line
shows "(closed <date>)". It reuses the resume check's reference checker (lib/resume_check.py, #1221): the same
relations.js parser through node, the same one-call GitHub fetch. It never edits a note.

Tests try to break it (ADR 0063): a closed ticket in a still-valid rule (feedback: never flagged on that alone),
a ref in a code fence, a PR in a private repo the gate can't read, a note half done, GitHub down, a second run the
same day, an index line shared by several notes, and an annotation already there. Temp dirs only.

    ~/.agents/venv/bin/python -m pytest lib/tests/test_memory_claims.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(LIB / "tests"))

import memory_lint as ml  # noqa: E402
from test_resume_check import FakeGitHub, issue, pr  # noqa: E402  (the fake that answers the real query)

pytestmark = pytest.mark.requires_tool("node")
NOW = datetime(2026, 11, 9, 22, 0, tzinfo=timezone.utc)
REPOS = {"marvin": "G-Eskayo/marvin"}


def note(d: Path, stem: str, body: str, type_: str = "project", desc: str = "a note", extra: str = "") -> Path:
    p = d / f"{stem}.md"
    p.write_text(f"---\nname: {stem}\ndescription: {desc}\nmetadata:\n  type: {type_}\n{extra}---\n\n{body}\n")
    return p


def closed(at="2026-11-04T10:00:00Z", title="t"):
    return issue(title, events=[("ClosedEvent", at)], state="CLOSED")


@pytest.fixture
def mem(tmp_path):
    d = tmp_path / "memory"
    d.mkdir()
    return d


def run(mem, items=None, gh=None, **kw):
    kw.setdefault("repos", REPOS)
    kw.setdefault("now", NOW)
    return ml.claims(mem, run=gh or FakeGitHub(items), **kw)


def test_an_open_note_about_closed_work_is_flagged_with_an_invalid_at_suggestion(mem):
    note(mem, "project-docs-tab", "QUEUED: the Docs tab live view, ticket 715.", desc="QUEUED behind the spike")
    r = run(mem, {"G-Eskayo/marvin#715": closed("2026-11-09T08:00:00Z")})
    assert r["status"] == "checked"
    [f] = r["flagged"]
    assert f["note"] == "project-docs-tab" and f["closed"] == "2026-11-09"
    assert f["suggest"] == "invalid_at: 2026-11-09" and f["refs"] == ["G-Eskayo/marvin#715"]


def test_a_ref_elsewhere_in_the_note_is_not_the_open_claim(mem):
    # the real false positive of 2026-11-09: "OPEN ... awaiting go-ahead" in the description, and the PR that *found*
    # the problem cited lines later. That PR merged; the problem is still open.
    note(mem, "project-webhook", "Found by the sweep.\n\n**How to apply:** `skills/security-sweep` (PR #1161) found it.",
         desc='"OPEN 2026-11-06: webhook has no auth; awaiting go-ahead"')
    gh = FakeGitHub({"G-Eskayo/marvin#1161": pr(merged_at="2026-11-09T18:30:00Z", state="MERGED")})
    assert run(mem, gh=gh)["flagged"] == [] and gh.calls == []


def test_bare_refs_belong_to_the_one_repo_the_line_names_not_the_tickets_repo(mem):
    # the real case: a marvin-voice note saying "G-Eskayo/marvin-voice#21 ... #3, #4 awaiting" means marvin-voice's #3
    note(mem, "project-voice", "OPEN: G-Eskayo/marvin-voice#21 then #3 and #4")
    items = {"G-Eskayo/marvin-voice#21": closed(), "G-Eskayo/marvin-voice#3": closed(), "G-Eskayo/marvin-voice#4": closed(),
             "G-Eskayo/marvin#3": issue(), "G-Eskayo/marvin#4": issue()}
    [f] = run(mem, items)["flagged"]
    assert sorted(f["refs"]) == ["G-Eskayo/marvin-voice#21", "G-Eskayo/marvin-voice#3", "G-Eskayo/marvin-voice#4"]


def test_bare_refs_go_to_the_tickets_repo_when_a_line_names_two_repos(mem):
    note(mem, "project-two", "OPEN: G-Eskayo/a#1 and G-Eskayo/b#2 and #3")
    gh = FakeGitHub({"G-Eskayo/a#1": closed(), "G-Eskayo/b#2": closed(), "G-Eskayo/marvin#3": closed()})
    assert sorted(run(mem, gh=gh)["flagged"][0]["refs"]) == ["G-Eskayo/a#1", "G-Eskayo/b#2", "G-Eskayo/marvin#3"]


def test_the_latest_close_date_is_suggested_when_several_refs_closed(mem):
    note(mem, "project-x", "OPEN: #1 and #2")
    r = run(mem, {"G-Eskayo/marvin#1": closed("2026-11-01T00:00:00Z"),
                  "G-Eskayo/marvin#2": pr(merged_at="2026-11-06T00:00:00Z", state="MERGED",
                                          events=[("MergedEvent", "2026-11-06T00:00:00Z")])})
    assert r["flagged"][0]["closed"] == "2026-11-06"


def test_a_feedback_note_about_a_closed_ticket_is_a_still_valid_rule_and_never_flagged(mem):
    note(mem, "feedback-rule", "URGENT lesson from #5: always check main first.", type_="feedback")
    note(mem, "user-me", "OPEN to new roles; see #5", type_="user")
    r = run(mem, {"G-Eskayo/marvin#5": closed()})
    assert r["flagged"] == []


def test_a_note_with_some_work_still_open_is_not_flagged(mem):
    note(mem, "project-half", "OPEN: #1 done, #2 still going")
    r = run(mem, {"G-Eskayo/marvin#1": closed(), "G-Eskayo/marvin#2": issue()})
    assert r["flagged"] == []


def test_refs_and_open_words_inside_code_are_ignored(mem):
    note(mem, "project-code", "Example:\n```\nOPEN #9\n```\nand `QUEUED #10` inline. Nothing open here: #11.")
    gh = FakeGitHub({"G-Eskayo/marvin#11": closed()})
    r = run(mem, gh=gh)
    assert r["flagged"] == [] and gh.calls == [], "no open-state word outside code, so nothing to check"


def test_a_ref_in_a_code_fence_does_not_count_as_the_notes_claim(mem):
    note(mem, "project-fence", "OPEN: waiting on #3.\n```\nsee #4\n```")
    r = run(mem, {"G-Eskayo/marvin#3": issue(), "G-Eskayo/marvin#4": closed()})
    assert r["flagged"] == []


def test_a_pr_in_a_private_repo_the_gate_cant_read_is_unverified_not_stale(mem):
    note(mem, "project-private", "OPEN: G-Eskayo/secret#3")
    r = run(mem, {})
    assert r["flagged"] == [] and r["unreadable"] == ["G-Eskayo/secret#3"]


def test_a_note_already_invalid_or_superseded_is_skipped(mem):
    note(mem, "project-done", "OPEN #1", extra="  invalid_at: 2026-11-05\n")
    note(mem, "project-new", "replacement")
    note(mem, "project-old", "OPEN #1", extra="  superseded_by: project-new\n")
    gh = FakeGitHub({"G-Eskayo/marvin#1": closed()})
    r = run(mem, gh=gh)
    assert r["flagged"] == [] and gh.calls == []


def test_github_down_says_so_and_flags_nothing(mem):
    note(mem, "project-x", "OPEN #1")
    r = run(mem, gh=FakeGitHub(rc=1, stdout="", stderr="error connecting to api.github.com"))
    assert r["status"] == "unverified" and "unreachable" in r["reason"] and r["flagged"] == []


def test_lowercase_open_is_not_an_open_state_word(mem):
    note(mem, "project-x", "open the dashboard and see #1")
    gh = FakeGitHub({"G-Eskayo/marvin#1": closed()})
    assert run(mem, gh=gh)["flagged"] == [] and gh.calls == []


def test_awaiting_counts_in_any_case(mem):
    note(mem, "project-x", "Awaiting Gil's go-ahead on #1")
    assert len(run(mem, {"G-Eskayo/marvin#1": closed()})["flagged"]) == 1


def test_every_note_is_checked_in_one_github_call(mem):
    for n in range(1, 6):
        note(mem, f"project-{n}", f"OPEN #{n}")
    gh = FakeGitHub({f"G-Eskayo/marvin#{n}": closed() for n in range(1, 6)})
    r = run(mem, gh=gh)
    assert len(gh.calls) == 1 and len(r["flagged"]) == 5


# ── the index line ───────────────────────────────────────────────────────────

INDEX = """# Memory Index
- **Dashboard:** [File browser](project-a.md), [Docs tab live view (QUEUED)](project-docs-tab.md), [Other](project-b.md)
- [OPEN: webhook open on LAN](project-webhook.md) — no auth; awaiting go-ahead
"""


def test_the_index_line_gains_closed_date_after_the_right_link_only():
    out = ml.annotate_index(INDEX, {"project-docs-tab": "2026-11-09"})
    assert "[Docs tab live view (QUEUED)](project-docs-tab.md) (closed 2026-11-09), [Other](project-b.md)" in out
    assert "[File browser](project-a.md), " in out and "(project-webhook.md) — no auth" in out


def test_annotating_twice_changes_nothing_and_a_new_date_replaces_the_old():
    once = ml.annotate_index(INDEX, {"project-webhook": "2026-11-07"})
    assert ml.annotate_index(once, {"project-webhook": "2026-11-07"}) == once
    later = ml.annotate_index(once, {"project-webhook": "2026-11-08"})
    assert "(closed 2026-11-08)" in later and "(closed 2026-11-07)" not in later


def test_a_note_missing_from_the_index_is_no_error():
    assert ml.annotate_index(INDEX, {"project-nowhere": "2026-11-09"}) == INDEX


# ── the daily health check ───────────────────────────────────────────────────

def test_the_check_runs_once_a_day_and_writes_only_the_index(mem, tmp_path):
    p = note(mem, "project-docs-tab", "QUEUED: ticket 715")
    before = p.read_text()
    (mem / "MEMORY.md").write_text(INDEX)
    state = tmp_path / "var" / "memory-claims.json"
    gh = FakeGitHub({"G-Eskayo/marvin#715": closed("2026-11-09T08:00:00Z")})
    c = ml.check_claims(mem, run=gh, now=NOW, state_path=state, repos=REPOS)
    assert c["id"] == "memory:claims" and c["severity"] == "yellow"
    assert "project-docs-tab" in c["detail"] and "invalid_at: 2026-11-09" in c["detail"]
    assert "(project-docs-tab.md) (closed 2026-11-09)" in (mem / "MEMORY.md").read_text()
    assert p.read_text() == before, "a note is never edited"
    again = ml.check_claims(mem, run=gh, now=NOW.replace(hour=23), state_path=state, repos=REPOS)
    assert len(gh.calls) == 1 and again["detail"] == c["detail"], "the same day reuses the day's result"
    ml.check_claims(mem, run=gh, now=NOW.replace(day=10), state_path=state, repos=REPOS)
    assert len(gh.calls) == 2, "the next day checks again"


def test_a_clean_day_is_green(mem, tmp_path):
    note(mem, "project-x", "OPEN #1")
    c = ml.check_claims(mem, run=FakeGitHub({"G-Eskayo/marvin#1": issue()}), now=NOW,
                        state_path=tmp_path / "s.json", repos=REPOS)
    assert c["severity"] == "green"


def test_an_unverified_day_is_never_green_and_is_retried(mem, tmp_path):
    note(mem, "project-x", "OPEN #1")
    gh = FakeGitHub(raises=subprocess.TimeoutExpired("gh", 5))
    c = ml.check_claims(mem, run=gh, now=NOW, state_path=tmp_path / "s.json", repos=REPOS)
    assert c["severity"] == "yellow" and "couldn't" in c["detail"]
    ml.check_claims(mem, run=gh, now=NOW.replace(hour=23), state_path=tmp_path / "s.json", repos=REPOS)
    assert len(gh.calls) == 2, "a day that couldn't be checked isn't cached"


def test_a_garbled_state_file_just_runs_the_check(mem, tmp_path):
    note(mem, "project-x", "OPEN #1")
    s = tmp_path / "s.json"
    s.write_text("{not json")
    c = ml.check_claims(mem, run=FakeGitHub({"G-Eskayo/marvin#1": issue()}), now=NOW, state_path=s, repos=REPOS)
    assert c["severity"] == "green" and json.loads(s.read_text())["day"] == "2026-11-09"
