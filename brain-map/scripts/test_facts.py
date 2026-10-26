#!/usr/bin/env python3
"""facts.py: the MARVIN page's numbers, computed from the system (docs/plans/living-marvin-page-2026-10-08.md)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import facts  # noqa: E402


def test_compute_facts_counts_from_each_source():
    out = facts.compute_facts(
        manifest={"index": [{"name": n, "path": f"~/.agents/skills/{n}/SKILL.md"} for n in "abc"]},
        test_runs=[[{"timestamp": "2026-10-08T10:00:00+00:00", "metrics": {"tests_passed": {"value": 2000}}}],
                   [{"timestamp": "2026-10-08T17:27:40+00:00", "metrics": {"tests_passed": {"value": 2780}}},
                    {"timestamp": "2026-10-07T09:00:00+00:00", "metrics": {"tests_passed": {"value": 9999}}}]],
        merged_prs=58, placement={"x": "both", "y": "mini", "z": "laptop"},
        adr_names=["0001-a.md", "0056-b.md", "0056-c.md", "README.md"], network={"devices": {"m": {}, "l": {}}},
        today="2026-10-08")
    assert out["skills"] == 3
    assert out["tests"] == 2780           # the newest run, not the biggest number
    assert out["prs_merged"] == 58
    assert out["agents"] == 3
    assert out["decisions"] == 3          # files, not numbers: two ADRs share 0056
    assert out["machines"] == 2
    assert out["counted_on"] == "8 October 2026"


def test_a_source_that_failed_is_left_out_not_zero():
    out = facts.compute_facts(manifest={"index": [{"name": "a", "path": "~/.agents/skills/a/SKILL.md"}]}, test_runs=[], merged_prs=None, placement={},
                              adr_names=[], network={}, today="2026-10-08")
    assert "tests" not in out and "prs_merged" not in out and "agents" not in out and "machines" not in out
    assert out["skills"] == 1  # the page keeps its typed number for anything missing


def test_formatted_numbers_use_thousands_separators():
    assert facts.formatted({"tests": 2780, "skills": 35, "counted_on": "8 October 2026"}) == {
        "tests": "2,780", "skills": "35", "counted_on": "8 October 2026"}


def _skills(index):
    return facts.compute_facts(manifest={"index": index}, test_runs=[], merged_prs=None, placement={},
                               adr_names=[], network={}, today="2026-10-22").get("skills")


def test_skills_counts_entries_that_are_a_skill_file_not_the_memories_the_index_also_holds():
    # The real index (2026-10-22) held 33 skills and 2 memories; the page said 35. The type tag can't decide it:
    # improve, qa-agent, research-colony and safety-monitor are skills tagged system/agent/library.
    mem = "~/.claude/projects/-Users-gileskayo/memory/"
    index = [{"name": "tdd", "path": "~/.agents/skills/tdd/SKILL.md", "tags": ["type:skill"]},
             {"name": "qa-agent", "path": "~/.agents/skills/qa-agent/SKILL.md", "tags": ["type:agent"]},
             {"name": "safety-monitor", "path": "~/.agents/skills/safety-monitor/SKILL.md", "tags": ["type:library"]},
             {"name": "reference-mcp", "path": mem + "reference-mcp.md", "tags": ["type:knowledge"]},
             {"name": "fake", "path": mem + "type-skill.md", "tags": ["type:skill"]},  # tagged, but a memory file
             {"name": "near", "path": "~/.agents/skills/near/SKILL.md.bak"},           # not the skill file itself
             {"name": "nopath"},
             "not-a-dict"]
    assert _skills(index) == 3


def test_an_index_with_no_skills_leaves_the_number_out_rather_than_writing_zero():
    assert _skills([{"name": "m", "path": "~/.claude/projects/x/memory/m.md"}]) is None
