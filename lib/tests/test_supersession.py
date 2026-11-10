"""Decision supersession (marvin#1226, extends ticket 652): when the owner answers a Decision, the follow-up lists the
earlier answers to the same question, found by decision id and by the docs that cite the same ticket, so a later
decision never silently contradicts an earlier one in plans, ADRs, CONTEXT or memory (incident 7: the Workshop plan's
"machines go to Vitals" against the later answer placing the throttle in Workshop ▸ Now).

Tests try to break it (ADR 0063): the same id reused in two plans for different questions, a decision with no id, a
doc that quotes the old answer as history (kept), an earlier answer that agrees, a code-fenced example, an unreadable
file, node missing. The parser is the real decisions.js through node. Temp dirs only.

    ~/.agents/venv/bin/python -m pytest lib/tests/test_supersession.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import supersession as ss  # noqa: E402

pytestmark = pytest.mark.requires_tool("node")


def block(qid, question, chosen, other="Something else"):
    a, b = ("x" if chosen == 0 else " "), ("x" if chosen == 1 else " ")
    return f"## Decisions\n<!-- marvin:decisions -->\n### {qid}: {question}\n- [{a}] Vitals\n- [{b}] {other}\n"


NOW_PR = "Closes #862\n\n" + block("machines-home", "Where do machine controls live?", 1, "Workshop ▸ Now")


@pytest.fixture
def docs(tmp_path):
    (tmp_path / "plans").mkdir()
    (tmp_path / "memory").mkdir()
    return tmp_path


def write(docs, rel, text):
    p = docs / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def run(docs, pr_body=NOW_PR, **kw):
    return ss.earlier_answers(pr_body, roots=[docs], repo="G-Eskayo/marvin", **kw)


def test_incident_7_the_earlier_plan_answer_is_found_and_marked_as_differing(docs):
    write(docs, "plans/workshop.md", "# Workshop plan\n\n" + block("machines-home", "Where do machine controls live?", 0))
    [h] = run(docs)
    assert h["kind"] == "id" and h["id"] == "machines-home" and h["path"].endswith("plans/workshop.md")
    assert h["earlier"] == ["Vitals"] and h["now"] == ["Workshop ▸ Now"] and h["verdict"] == "differs"


def test_an_earlier_answer_that_agrees_is_listed_as_agreeing(docs):
    write(docs, "plans/a.md", block("machines-home", "Where do machine controls live?", 1, "Workshop ▸ Now"))
    assert run(docs)[0]["verdict"] == "agrees"


def test_the_same_id_for_a_different_question_is_marked_probably_unrelated(docs):
    write(docs, "plans/other.md", block("machines-home", "Which machine hosts the merge queue?", 0))
    assert run(docs)[0]["verdict"] == "same id, different question"


def test_a_doc_that_quotes_the_old_answer_as_history_is_kept(docs):
    write(docs, "plans/old.md", "## History\n\nSuperseded on 2026-11-09; kept as history.\n\n"
          + block("machines-home", "Where do machine controls live?", 0))
    assert run(docs)[0]["verdict"] == "history (kept)"


def test_a_decision_with_no_id_is_found_by_relations_only(docs):
    pr = "Closes #862\n\n## Decisions\n<!-- marvin:decisions -->\n### Where do machine controls live?\n- [x] Workshop\n- [ ] Vitals\n"
    write(docs, "plans/workshop.md", "Machines go to Vitals (ticket 862).")
    hits = run(docs, pr_body=pr)
    assert [h["kind"] for h in hits] == ["relation"] and "G-Eskayo/marvin#862" in hits[0]["why"]


def test_a_doc_citing_the_same_ticket_is_listed_once_even_with_an_id_hit(docs):
    write(docs, "plans/workshop.md", "Ticket 862.\n\n" + block("machines-home", "Where do machine controls live?", 0))
    write(docs, "CONTEXT.md", "Workshop ▸ Now (#862) holds the throttle.")
    hits = run(docs)
    assert sorted(h["kind"] for h in hits) == ["id", "relation"]
    assert {Path(h["path"]).name for h in hits} == {"workshop.md", "CONTEXT.md"}


def test_the_prs_own_files_and_code_fenced_examples_are_not_hits(docs):
    write(docs, "plans/example.md", "```\n" + block("machines-home", "Where do machine controls live?", 0) + "```\n")
    own = write(docs, "plans/this-pr.md", block("machines-home", "Where do machine controls live?", 0))
    assert run(docs, exclude={str(own)}) == []


def test_no_answered_question_and_no_ticket_means_nothing_to_search(docs):
    write(docs, "plans/a.md", block("x", "q", 0))
    assert run(docs, pr_body="Just a PR, no decisions.") == []


def test_unreadable_files_are_skipped(docs):
    (docs / "plans" / "bin.md").write_bytes(b"\xff\xfe\x00 ### machines-home: x")
    write(docs, "plans/workshop.md", block("machines-home", "Where do machine controls live?", 0))
    assert len(run(docs)) == 1


def test_node_missing_returns_none_so_the_caller_says_it_couldnt_look(docs):
    assert ss.earlier_answers(NOW_PR, roots=[docs], repo="G-Eskayo/marvin", node=None) is None


def test_the_section_for_the_follow_up_has_one_checkbox_per_hit_and_says_amend_or_keep(docs):
    write(docs, "plans/workshop.md", "# Workshop plan\n\n" + block("machines-home", "Where do machine controls live?", 0))
    text = ss.section(run(docs), home=docs)
    assert text.startswith("## Earlier answers to the same question")
    assert "- [ ] `plans/workshop.md`" in text and "Amendment (" in text and "keep" in text
    assert ss.section([], home=docs) == ""
    assert "couldn't" in ss.section(None, home=docs).lower()


# ── wired into the owner-decisions follow-up ─────────────────────────────────

def _status(**over):
    return {"repo": "G-Eskayo/marvin", "number": 900, "title": "T", "url": "u", "branch": "b", "comment_id": 5,
            "comment_url": "c", "since": "2026-11-09T10:00:00Z", "question": False, "malformed": False, "texts": [],
            "addressed_by": None, "age_hours": 5.0, "committed_since": False, "built_since": False, "overdue": True,
            "body": NOW_PR, **over}


def test_the_follow_up_lists_earlier_answers_and_asks_for_each_to_be_amended_or_kept():
    import owner_decisions as od
    body = od.followup_body(_status(earlier_section="## Earlier answers to the same question\n\n- [ ] `plans/w.md`:3 x\n"))
    assert "## Earlier answers to the same question" in body
    assert body.index("Earlier answers") < body.index("## Acceptance criteria")
    assert "Each earlier answer listed above is amended" in body
    plain = od.followup_body(_status())
    assert "Earlier answers" not in plain and "Each earlier answer" not in plain


def test_filing_computes_the_section_and_a_failure_never_stops_the_follow_up(monkeypatch):
    import owner_decisions as od
    import supersession
    written = []
    monkeypatch.setattr(od, "_list_label", lambda repo, run: [])
    monkeypatch.setattr(od, "_dedupe", lambda *a: [])

    def gh(args, run):
        if args[:2] == ["issue", "create"]:
            written.append(Path(args[args.index("--body-file") + 1]).read_text())
        return type("P", (), {"returncode": 0, "stdout": "https://x/1", "stderr": ""})()

    monkeypatch.setattr(od, "_gh", gh)
    monkeypatch.setattr(supersession, "earlier_answers", lambda body, **k: [
        {"kind": "id", "id": "machines-home", "path": "/x/plans/w.md", "line": 3, "verdict": "differs",
         "earlier": ["Vitals"], "now": ["Workshop"], "question": "q"}])
    assert od._file(_status(), run=None, dry_run=False).startswith("filed")
    assert "machines-home" in written[-1]
    monkeypatch.setattr(supersession, "earlier_answers", lambda body, **k: (_ for _ in ()).throw(OSError("boom")))
    assert od._file(_status(comment_id=6), run=None, dry_run=False).startswith("filed")
    assert "Couldn't look for them" in written[-1]
