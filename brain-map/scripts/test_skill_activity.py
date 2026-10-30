#!/usr/bin/env python3
"""Tests for skill_activity.py, the PostToolUse hook that feeds the live map (#843).

The map lights a node from real work and a link only from a causal pair in one session, so each line carries the
session, the tool and (for MARVIN's own files) the file touched, relative to the agents folder. Nothing outside
that folder is written, so a project path never reaches the map.
"""
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import skill_activity  # noqa: E402


@pytest.fixture
def agents(tmp_path):
    root = tmp_path / "agents"
    (root / "skills" / "tdd").mkdir(parents=True)
    return root


def test_a_skill_call_names_the_skill_tool_and_session(agents):
    e = skill_activity.entry_for({"tool_name": "Skill", "tool_input": {"skill": "tdd"}, "session_id": "s1"}, agents, 5.0)
    assert e == {"skill": "tdd", "ts": 5.0, "tool": "Skill", "session": "s1"}


def test_a_skill_call_without_a_skill_is_dropped(agents):
    assert skill_activity.entry_for({"tool_name": "Skill", "tool_input": {}}, agents, 1.0) is None
    assert skill_activity.entry_for({"tool_name": ""}, agents, 1.0) is None
    assert skill_activity.entry_for({}, agents, 1.0) is None


def test_an_edit_in_the_agents_folder_names_the_file_relative_to_it(agents):
    f = agents / "skills" / "tdd" / "SKILL.md"
    e = skill_activity.entry_for({"tool_name": "Edit", "tool_input": {"file_path": str(f)}, "session_id": "s"}, agents, 2.0)
    assert e == {"skill": "MARVIN", "ts": 2.0, "tool": "Edit", "session": "s", "file": "skills/tdd/SKILL.md"}


def test_a_notebook_edit_uses_its_notebook_path(agents):
    f = agents / "skills" / "tdd" / "n.ipynb"
    e = skill_activity.entry_for({"tool_name": "NotebookEdit", "tool_input": {"notebook_path": str(f)}}, agents, 2.0)
    assert e["file"] == "skills/tdd/n.ipynb"


def test_files_outside_the_agents_folder_are_never_written(agents, tmp_path):
    outside = [str(tmp_path / "project" / "secret.py"), str(agents / ".." / "elsewhere.py"), "relative/path.py", ""]
    for p in outside:
        e = skill_activity.entry_for({"tool_name": "Read", "tool_input": {"file_path": p}}, agents, 3.0)
        assert "file" not in e, p
        assert e["skill"] == "MARVIN"


def test_a_folder_that_only_shares_a_prefix_is_outside(agents, tmp_path):
    twin = tmp_path / "agents-old" / "x.py"
    e = skill_activity.entry_for({"tool_name": "Read", "tool_input": {"file_path": str(twin)}}, agents, 3.0)
    assert "file" not in e


def test_odd_payloads_never_raise(agents):
    for payload in [{"tool_name": "Read", "tool_input": None}, {"tool_name": "Read", "tool_input": {"file_path": 7}},
                    {"tool_name": "Bash", "session_id": 9}, {"tool_name": "Skill", "tool_input": {"skill": 3}}]:
        skill_activity.entry_for(payload, agents, 1.0)


def test_main_appends_a_line_and_trims_to_the_cap(agents, tmp_path, monkeypatch):
    log = tmp_path / "activity.jsonl"
    log.write_text("".join(json.dumps({"skill": "MARVIN", "ts": i}) + "\n" for i in range(skill_activity.MAX_LINES)))
    monkeypatch.setattr(skill_activity, "ACTIVITY_PATH", log)
    monkeypatch.setattr(skill_activity, "AGENTS_DIR", agents)
    payload = {"tool_name": "Edit", "tool_input": {"file_path": str(agents / "skills" / "tdd" / "SKILL.md")}, "session_id": "s"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    skill_activity.main()
    lines = log.read_text().splitlines()
    assert len(lines) == skill_activity.MAX_LINES
    last = json.loads(lines[-1])
    assert last["file"] == "skills/tdd/SKILL.md" and last["session"] == "s" and last["tool"] == "Edit"
    assert json.loads(lines[0])["ts"] == 1  # the oldest line went


# ── #854: a helper's own tool calls name the helper, so the map's Work half lights that worker ──

def test_a_tool_call_inside_a_helper_names_the_helper(agents):
    e = skill_activity.entry_for({"tool_name": "Read", "tool_input": {"file_path": str(agents / "skills" / "tdd" / "SKILL.md")},
                                  "session_id": "s1", "agent_id": "agent-a8bafa799a8984438"}, agents, 5.0)
    assert e["agent"] == "a8bafa799a8984438"
    assert e["file"] == "skills/tdd/SKILL.md"


@pytest.mark.parametrize("bad", [None, "", 7, "has space", "../../x", "a" * 65])
def test_a_missing_or_odd_agent_id_is_left_out(agents, bad):
    e = skill_activity.entry_for({"tool_name": "Bash", "tool_input": {}, "agent_id": bad}, agents, 5.0)
    assert "agent" not in e


def test_the_main_chat_has_no_agent(agents):
    assert "agent" not in skill_activity.entry_for({"tool_name": "Bash", "tool_input": {}}, agents, 5.0)
