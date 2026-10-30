"""The work loop, end to end (ADR 0080, marvin#737): each rule checked through the real bin/gh, in a temp HOME, against
a fake GitHub that records every call that reaches it. A rule holds only if a call that breaks it never gets there.
Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_work_loop_e2e.py -v

Each rule adds its own section. I2 (askable questions, marvin#742) is below.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "bin" / "gh"
FIX = Path(__file__).resolve().parent / "fixtures" / "decisions"

sys.path.insert(0, str(ROOT / "lib"))
import decisions_check as dc  # noqa: E402


@pytest.fixture
def github(tmp_path):
    """A fake real gh: records each call's argv (and body file contents) to $HOME/github-calls.jsonl, prints {}."""
    d = tmp_path / "realbin"
    d.mkdir()
    gh = d / "gh"
    gh.write_text(
        "#!/usr/bin/python3\n"
        "import json, os, sys\n"
        "a = sys.argv[1:]\n"
        "f = next((a[i + 1] for i, x in enumerate(a[:-1]) if x in ('--body-file', '-F')), None)\n"
        "rec = {'argv': a, 'body_file': open(f).read() if f and f != '-' else None}\n"
        "open(os.path.join(os.environ['HOME'], 'github-calls.jsonl'), 'a').write(json.dumps(rec) + '\\n')\n"
        "print('{}')\n")
    gh.chmod(0o755)
    return d


def _gh(tmp_path, realbin, *args, env_extra=None):
    env = {"PATH": f"{GATE.parent}:{realbin}:/usr/bin:/bin", "HOME": str(tmp_path), "GH_GATE_NO_BUDGET": "1",
           "MARVIN_INSTANCE_DIR": str(tmp_path / "instance"), **(env_extra or {})}
    return subprocess.run([str(GATE), *args], capture_output=True, text=True, env=env, timeout=60)


def _reached(tmp_path):
    f = tmp_path / "github-calls.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []


def _gate_log(tmp_path):
    f = tmp_path / ".claude" / "logs" / "gh-calls.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []


def _body_file(tmp_path, name):
    f = tmp_path / name
    shutil.copy(FIX / name, f)
    return str(f)


# ── I2 askable questions: every question to the owner is machine-readable ───

i2 = pytest.mark.skipif(not dc.find_node(), reason="node is not installed (the dashboard's parser needs it)")


@i2
@pytest.mark.parametrize("name", ["cc179_prose.md", "cc181_prose.md"])
@pytest.mark.parametrize("cmd", [["pr", "create", "--title", "t", "--head", "x"], ["pr", "edit", "179"],
                                 ["issue", "create", "--title", "t"], ["issue", "edit", "5"], ["issue", "comment", "5"],
                                 ["pr", "comment", "179"]])
def test_i2_prose_decisions_never_reach_github(tmp_path, github, cmd, name):
    p = _gh(tmp_path, github, *cmd, "-R", "o/clarity-captions", "--body-file", _body_file(tmp_path, name))
    assert p.returncode == 1, p.stderr
    assert "DECISIONS_NOT_ASKABLE" in p.stderr and "docs/agents/decisions-format.md" in p.stderr
    assert dc.OVERRIDE in p.stderr
    assert _reached(tmp_path) == []
    assert [e.get("decisions", "")[:21] for e in _gate_log(tmp_path)] == ["DECISIONS_NOT_ASKABLE"]


@i2
def test_i2_prose_decisions_in_an_inline_body_are_refused_too(tmp_path, github):
    p = _gh(tmp_path, github, "issue", "comment", "5", "-R", "o/r", "-b", (FIX / "cc181_prose.md").read_text())
    assert p.returncode == 1 and _reached(tmp_path) == []


@i2
def test_i2_a_block_that_does_not_parse_never_reaches_github(tmp_path, github):
    body = "## Decisions\n<!-- marvin:decisions -->\n### Which look?\n- [ ] A\n- [ ] B\n"
    p = _gh(tmp_path, github, "issue", "edit", "5", "-R", "o/r", "--body", body)
    assert p.returncode == 1 and "DECISIONS_UNPARSED" in p.stderr and "needs an id" in p.stderr
    assert _reached(tmp_path) == []


@i2
@pytest.mark.parametrize("name", ["cc174_block.md", "cc171_block.md"])
def test_i2_machine_readable_decisions_reach_github_unchanged(tmp_path, github, name):
    p = _gh(tmp_path, github, "issue", "comment", "5", "-R", "o/r", "--body-file", _body_file(tmp_path, name))
    assert p.returncode == 0, p.stderr
    (call,) = _reached(tmp_path)
    assert call["argv"][:2] == ["issue", "comment"] and call["body_file"] == (FIX / name).read_text()


@i2
def test_i2_a_good_pr_create_goes_on_to_the_images_rule(tmp_path, github):
    # The order of the rules: I2 lets it through, then I1 asks GitHub about the PR (here a fake that knows nothing,
    # so I1 fails open). Both rules run on one call.
    p = _gh(tmp_path, github, "pr", "create", "-R", "o/r", "--head", "x", "--base", "main", "--title", "t",
            "--body-file", _body_file(tmp_path, "cc174_block.md"))
    assert p.returncode == 0, p.stderr
    assert _reached(tmp_path)[-1]["argv"][:2] == ["pr", "create"]


@i2
def test_i2_override_lets_one_call_through_and_is_logged(tmp_path, github):
    p = _gh(tmp_path, github, "issue", "comment", "5", "-R", "o/r", "--body-file", _body_file(tmp_path, "cc179_prose.md"),
            env_extra={dc.OVERRIDE: "quoting an old PR in a write-up"})
    assert p.returncode == 0, p.stderr
    assert len(_reached(tmp_path)) == 1
    assert any(e.get("decisions_override") == "quoting an old PR in a write-up" for e in _gate_log(tmp_path))
    again = _gh(tmp_path, github, "issue", "comment", "5", "-R", "o/r", "--body-file", _body_file(tmp_path, "cc179_prose.md"))
    assert again.returncode == 1  # one call, not a setting that sticks


@i2
def test_i2_calls_with_no_body_are_untouched(tmp_path, github):
    assert _gh(tmp_path, github, "issue", "list").returncode == 0
    assert _gh(tmp_path, github, "pr", "edit", "3", "--add-label", "x").returncode == 0
    assert len(_reached(tmp_path)) == 2


def test_i2_without_node_the_call_goes_through_with_a_note(tmp_path, github):
    # The gate's PATH has no node and the known places are hidden: a broken check must not stop all GitHub work.
    p = _gh(tmp_path, github, "issue", "comment", "5", "-R", "o/r", "-b", "## Decisions\n1. A or B?",
            env_extra={"MARVIN_NODE": str(tmp_path / "no-node")})
    assert p.returncode == 0
    assert "node" in p.stderr and len(_reached(tmp_path)) == 1
