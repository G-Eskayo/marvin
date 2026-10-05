"""Tests for tool_usage.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_tool_usage.py -v
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import tool_usage as tu  # noqa: E402

NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)


def ts(days_ago=0.0):
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def use(tid, name, inp=None, days_ago=0.0, sidechain=False, entry="cli"):
    return {"type": "assistant", "timestamp": ts(days_ago), "isSidechain": sidechain, "entrypoint": entry,
            "message": {"content": [{"type": "tool_use", "id": tid, "name": name, "input": inp or {}}]}}


def result(tid, content="ok", is_error=False, days_ago=0.0):
    return {"type": "user", "timestamp": ts(days_ago), "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": content, "is_error": is_error}]}}


def write(tmp_path, *lines, name="s.jsonl"):
    f = tmp_path / name
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return f


def agg(tmp_path, *lines, **kw):
    f = write(tmp_path, *lines)
    return tu.aggregate([f], now=NOW, **kw)


def tool(a, name):
    return next(t for t in a["tools"] if t["name"] == name)


def test_counts_calls_and_pairs_each_with_its_result(tmp_path):
    a = agg(tmp_path, use("1", "Bash"), result("1"), use("2", "Bash"), result("2", "Exit code 1", True), use("3", "Read"), result("3"))
    b = tool(a, "Bash")
    assert (b["calls"], b["ok"], b["error"]) == (2, 1, 1)
    assert tool(a, "Read")["ok"] == 1


def test_classifies_rejected_interrupted_and_invalid_calls_separately_from_plain_errors(tmp_path):
    a = agg(tmp_path,
            use("1", "Bash"), result("1", "The user doesn't want to proceed with this tool use. The tool use was rejected", True),
            use("2", "Edit"), result("2", "[Request interrupted by user for tool use]", True),
            use("3", "mcp__x__y"), result("3", "<tool_use_error>InputValidationError: field required</tool_use_error>", True),
            use("4", "Skill", {"skill": "nope"}), result("4", "Unknown skill: nope", True))
    assert tool(a, "Bash")["rejected"] == 1 and tool(a, "Bash")["error"] == 0
    assert tool(a, "Edit")["interrupted"] == 1
    assert tool(a, "mcp__x__y")["invalid"] == 1
    assert tool(a, "Skill")["invalid"] == 1


def test_a_call_with_no_result_is_counted_but_unresolved(tmp_path):
    a = agg(tmp_path, use("1", "Bash"))
    b = tool(a, "Bash")
    assert b["calls"] == 1 and b["ok"] == 0 and b["unresolved"] == 1


def test_skills_are_counted_by_the_skill_they_name(tmp_path):
    a = agg(tmp_path, use("1", "Skill", {"skill": "diagnose"}), result("1"), use("2", "Skill", {"skill": "diagnose"}), result("2"),
            use("3", "Skill", {"skill": "tdd"}), result("3", "boom", True))
    skills = {s["name"]: s for s in a["skills"]}
    assert skills["diagnose"]["calls"] == 2 and skills["tdd"]["error"] == 1


def test_mcp_tools_roll_up_by_server(tmp_path):
    a = agg(tmp_path, use("1", "mcp__claude-in-chrome__navigate"), result("1"), use("2", "mcp__claude-in-chrome__computer"), result("2"),
            use("3", "mcp__synta-mcp__authenticate"), result("3"))
    servers = {s["server"]: s for s in a["mcp_servers"]}
    assert servers["claude-in-chrome"]["calls"] == 2 and servers["synta-mcp"]["calls"] == 1


def test_subagent_spawns_are_counted_by_type(tmp_path):
    a = agg(tmp_path, use("1", "Agent", {"subagent_type": "Explore"}), result("1"), use("2", "Agent", {"subagent_type": "Explore"}), result("2"))
    assert {x["name"]: x["calls"] for x in a["agents"]} == {"Explore": 2}


def test_splits_by_where_the_call_came_from(tmp_path):
    a = agg(tmp_path, use("1", "Bash"), result("1"), use("2", "Bash", sidechain=True), result("2"), use("3", "Bash", entry="sdk-cli"), result("3"))
    assert tool(a, "Bash")["by_kind"] == {"interactive": 1, "subagent": 1, "headless": 1}


def test_window_keeps_recent_calls_and_buckets_them_by_day(tmp_path):
    a = agg(tmp_path, use("1", "Bash", days_ago=1), result("1", days_ago=1), use("2", "Bash", days_ago=45), result("2", days_ago=45),
            use("3", "Bash", days_ago=0), result("3"), window_days=30)
    b = tool(a, "Bash")
    assert b["calls"] == 2
    assert b["by_day"] == {"2026-10-04": 1, "2026-10-05": 1}
    assert b["last_used"].startswith("2026-10-05")


def test_recent_failures_lists_errors_newest_first_with_a_short_message(tmp_path):
    a = agg(tmp_path, use("1", "Bash", days_ago=2), result("1", "Exit code 2\n" + "x" * 500, True, days_ago=2),
            use("2", "Read", days_ago=1), result("2", "File does not exist", True, days_ago=1))
    f = a["recent_failures"]
    assert [x["tool"] for x in f] == ["Read", "Bash"]
    assert len(f[1]["message"]) <= 200 and f[0]["outcome"] == "error"


def test_inventory_names_our_skills_that_never_fired(tmp_path):
    a = agg(tmp_path, use("1", "Skill", {"skill": "diagnose"}), result("1"), known_skills=["diagnose", "tdd", "zoom-out"])
    inv = a["inventory"]
    assert inv["known"] == 3 and inv["used"] == 1
    assert inv["never_used"] == ["tdd", "zoom-out"]


def test_bad_lines_and_unrelated_records_are_ignored(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text("{not json\n" + json.dumps({"type": "summary", "x": 1}) + "\n" + json.dumps(use("1", "Bash")) + "\n" + json.dumps(result("1")) + "\n")
    assert tool(tu.aggregate([f], now=NOW), "Bash")["ok"] == 1


def test_find_transcripts_skips_files_not_touched_inside_the_window(tmp_path):
    import os
    old, new = tmp_path / "old.jsonl", tmp_path / "new.jsonl"
    old.write_text("{}")
    new.write_text("{}")
    os.utime(old, (NOW.timestamp() - 40 * 86400, NOW.timestamp() - 40 * 86400))
    os.utime(new, (NOW.timestamp(), NOW.timestamp()))
    assert tu.find_transcripts(tmp_path, window_days=30, now=NOW) == [new]


def test_reading_a_skills_SKILL_md_counts_as_using_that_skill(tmp_path):
    p = "/Users/me/.agents/skills/diagnose/SKILL.md"
    a = agg(tmp_path, use("1", "Read", {"file_path": p}), result("1"), use("2", "Skill", {"skill": "diagnose"}), result("2"),
            use("3", "Read", {"file_path": "/Users/me/.agents/skills/diagnose/tests.md"}), result("3"))
    s = {x["name"]: x for x in a["skills"]}["diagnose"]
    assert s["calls"] == 2  # one SKILL.md read + one Skill-tool call; other files in the skill are not a use
    assert s["via"] == {"skill_tool": 1, "read": 1}


def test_inventory_counts_a_skill_loaded_by_reading_as_used(tmp_path):
    a = agg(tmp_path, use("1", "Read", {"file_path": "/h/.agents/skills/tdd/SKILL.md"}), result("1"), known_skills=["tdd", "zoom-out"])
    assert a["inventory"]["never_used"] == ["zoom-out"]
