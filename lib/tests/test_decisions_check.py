"""Tests for lib/decisions_check.py, rule I2 (askable questions, ADR 0080, marvin#742). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_decisions_check.py -v

The parser is the dashboard's own (dashboard/webhook-server/decisions.js), run through real node: nothing is mocked
except, in one test, node being absent.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import decisions_check as dc  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "decisions"
needs_node = pytest.mark.skipif(not dc.find_node(), reason="node is not installed")

GOOD = """## Decisions
<!-- marvin:decisions -->
### dance: Which launch animation?
- [ ] A: Clap
- [ ] B: Bubble
"""


# ── which calls carry a body to check ───────────────────────────────────────

@pytest.mark.parametrize("argv,cmd,body,body_file", [
    (["pr", "create", "--title", "t", "--body", "B"], "pr create", "B", None),
    (["pr", "create", "-b", "B", "-t", "t"], "pr create", "B", None),
    (["pr", "create", "--body=B"], "pr create", "B", None),
    (["pr", "edit", "12", "--body-file", "f.md"], "pr edit", None, "f.md"),
    (["pr", "edit", "12", "-F", "f.md"], "pr edit", None, "f.md"),
    (["pr", "comment", "12", "--body-file=f.md"], "pr comment", None, "f.md"),
    (["issue", "create", "-R", "o/r", "--title", "t", "--body-file", "f.md"], "issue create", None, "f.md"),
    (["issue", "edit", "3", "-b", "B"], "issue edit", "B", None),
    (["issue", "comment", "3", "--repo", "o/r", "-b", "B"], "issue comment", "B", None),
])
def test_finds_the_body_wherever_the_flag_puts_it(argv, cmd, body, body_file):
    assert dc.body_call(argv) == {"cmd": cmd, "body": body, "body_file": body_file}


@pytest.mark.parametrize("argv", [
    ["pr", "list"], ["issue", "view", "3"], ["pr", "merge", "3"], ["api", "repos/o/r/issues/3/comments", "-f", "body=## Decisions"],
    ["pr", "edit", "3", "--add-label", "x"],          # no new body: nothing to check
    ["pr", "create", "--fill"],                       # gh writes the body from commits
    ["pr", "create", "--help", "--body", "## Decisions"],
    ["issue", "comment", "3", "--body-file", "-"],    # stdin belongs to gh
    ["pr"], [],
])
def test_other_calls_are_not_checked(argv):
    assert dc.body_call(argv) is None


def test_a_title_that_mentions_decisions_is_not_the_body():
    assert dc.body_call(["issue", "create", "--title", "## Decisions", "--body", "hello"])["body"] == "hello"


# ── what is refused: the live cases ─────────────────────────────────────────

@needs_node
@pytest.mark.parametrize("name", ["cc179_prose.md", "cc181_prose.md"])
def test_prose_decisions_from_live_prs_are_refused(name):
    msg = dc.refusal((FIX / name).read_text())
    assert msg and msg.startswith("DECISIONS_NOT_ASKABLE")
    assert "<!-- marvin:decisions -->" in msg and "docs/agents/decisions-format.md" in msg
    assert '"## Decisions"' in msg  # says which heading tripped it


@needs_node
@pytest.mark.parametrize("name", ["cc174_block.md", "cc171_block.md"])
def test_machine_readable_decisions_from_live_prs_pass(name):
    assert dc.refusal((FIX / name).read_text()) is None


# ── what is refused: trying to break it ─────────────────────────────────────

@needs_node
@pytest.mark.parametrize("body,says", [
    ("## Decisions\n<!-- marvin:decisions -->\n### Which animation?\n- [ ] A\n- [ ] B\n", "needs an id"),
    ("## Decisions\n<!-- marvin:decisions -->\n### dance: Which?\n- [ ] A only\n", "at least two"),
    ("## Decisions\n<!-- marvin:decisions -->\nPlease pick A or B.\n", "no questions"),
    ("## Decisions\n<!-- marvin:decisions -->\n### a: X?\n- [ ] 1\n- [ ] 2\n### a: Y?\n- [ ] 1\n- [ ] 2\n", "used twice"),
    ("## Decisions\n<!-- marvin:decisions -->\n### a: X?\n- [x] 1\n- [x] 2\n", "several ticked"),
])
def test_a_block_that_does_not_parse_is_refused_with_the_parsers_own_words(body, says):
    msg = dc.refusal(body)
    assert msg and msg.startswith("DECISIONS_UNPARSED") and says in msg
    assert "docs/agents/decisions-format.md" in msg


@needs_node
@pytest.mark.parametrize("heading", ["## Decisions", "### Decisions", "## Open questions", "## Questions for you",
                                     "## Choose", "## decisions:", "# Decide"])
def test_any_heading_that_asks_without_a_block_is_refused(heading):
    assert dc.refusal(f"Intro.\n\n{heading}\n\n1. A or B?\n")


@needs_node
@pytest.mark.parametrize("body", [
    "", "Fixes the build.\n\n## Tests\n- [x] passes\n",
    "## Decisions recorded\n- went with A\n",           # a report, not an ask
    "### Decisions from the owner\n\n- **Pick?** A\n",  # the dashboard's own record
    "How to write one:\n\n```markdown\n## Decisions\n1. A or B?\n```\n",  # an example in a fence
    GOOD,
    GOOD + "\n## Checks\n- [x] ok\n",
])
def test_bodies_that_ask_nothing_or_ask_properly_pass(body):
    assert dc.refusal(body) is None


@needs_node
def test_a_proper_block_with_an_unrelated_questions_heading_elsewhere_passes():
    # Only one machine-readable section is read; a second heading that asks is the author's to fix, and the dashboard
    # shows the block, so the owner is asked properly.
    assert dc.refusal(GOOD + "\n## Open questions\n1. Anything else?\n") is None


@needs_node
def test_unicode_and_huge_bodies_are_read_whole():
    body = "é" * 200_000 + "\n\n## Decisions\n\n1. A or B?\n"
    assert dc.refusal(body)


# ── the parser is the dashboard's, not a copy ───────────────────────────────

def test_there_is_no_python_copy_of_the_parser():
    src = (Path(dc.__file__)).read_text()
    assert "decisions.js" in src
    for copy_sign in ("QUESTION_RE", "OPTION_RE", "pick any", "re.compile"):
        assert copy_sign not in src


# ── failing open when the check can't run ───────────────────────────────────

def test_no_node_lets_the_call_through_with_a_note():
    said = []
    assert dc.refusal("## Decisions\n1. A or B?\n", node=None, say=said.append) is None
    assert said and "node" in said[0]


def test_a_broken_parser_lets_the_call_through_with_a_note(tmp_path):
    bad = tmp_path / "decisions_cli.js"
    bad.write_text("process.exit(3)\n")
    said = []
    assert dc.refusal("## Decisions\n1. A or B?\n", cli=bad, say=said.append) is None
    assert said and "couldn't check" in said[0]


def test_find_node_prefers_path_then_known_places(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    (a / "node").write_text("#!/bin/sh\n")
    (a / "node").chmod(0o755)
    assert dc.find_node(str(a), extra=()) == str(a / "node")
    assert dc.find_node(str(tmp_path / "nowhere"), extra=(str(a / "node"),)) == str(a / "node")
    assert dc.find_node(str(tmp_path / "nowhere"), extra=()) is None


# ── gate: what bin/gh calls ─────────────────────────────────────────────────

@needs_node
def test_gate_refuses_logs_and_says_how_to_fix(tmp_path):
    f = tmp_path / "b.md"
    f.write_text((FIX / "cc179_prose.md").read_text())
    said, logged = [], []
    rc = dc.gate(["issue", "comment", "3", "--body-file", str(f)], said.append, logged.append, env={})
    assert rc == 1
    assert any("DECISIONS_NOT_ASKABLE" in s for s in said) and any(dc.OVERRIDE in s for s in said)
    assert logged == [{"cmd": "issue comment", "rc": 1, "decisions": logged[0]["decisions"]}]
    assert logged[0]["decisions"].startswith("DECISIONS_NOT_ASKABLE")


@needs_node
def test_gate_passes_a_good_body_silently():
    said, logged = [], []
    assert dc.gate(["pr", "create", "--body", GOOD], said.append, logged.append, env={}) is None
    assert said == [] and logged == []


def test_gate_override_lets_one_call_through_and_logs_why():
    said, logged = [], []
    rc = dc.gate(["pr", "edit", "3", "--body", "## Decisions\n1. A or B?"], said.append, logged.append,
                 env={dc.OVERRIDE: "owner asked for prose here"})
    assert rc is None
    assert logged == [{"cmd": "pr edit", "decisions_override": "owner asked for prose here"}]


def test_gate_blank_override_is_no_override():
    assert dc.gate(["pr", "edit", "3", "--body", "x"], [].append, [].append, env={dc.OVERRIDE: "  "}) is None


def test_gate_unreadable_body_file_is_left_to_gh(tmp_path):
    said = []
    assert dc.gate(["pr", "edit", "3", "-F", str(tmp_path / "missing.md")], said.append, [].append, env={}) is None
