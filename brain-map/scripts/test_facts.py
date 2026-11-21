#!/usr/bin/env python3
"""facts.py: the MARVIN page's numbers, computed from the system (docs/plans/living-marvin-page-2026-10-08.md)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import facts  # noqa: E402


def test_compute_facts_with_separate_test_counts():
    out = facts.compute_facts(
        manifest={"index": [{"name": n, "path": f"~/.agents/skills/{n}/SKILL.md"} for n in "abc"]},
        tests_python=1200, tests_js=400, tests_site=180,
        merged_prs=58, placement={"x": "both", "y": "mini", "z": "laptop"},
        adr_names=["0001-a.md", "0056-b.md", "0056-c.md", "README.md"], network={"devices": {"m": {}, "l": {}}},
        today="2026-10-08")
    assert out["skills"] == 3
    assert out["tests_python"] == 1200
    assert out["tests_js"] == 400
    assert out["tests_site"] == 180
    assert out["tests"] == 1780  # sum of all three
    assert out["prs_merged"] == 58
    assert out["agents"] == 3
    assert out["decisions"] == 3
    assert out["machines"] == 2
    assert out["counted_on"] == "8 October 2026"


def test_tests_total_only_written_when_all_three_present():
    out = facts.compute_facts(
        manifest={"index": []}, tests_python=100, tests_js=50, tests_site=None,
        merged_prs=None, placement={}, adr_names=[], network={}, today="2026-10-08")
    assert "tests" not in out  # not all three present
    assert out["tests_python"] == 100
    assert out["tests_js"] == 50
    assert "tests_site" not in out


def test_a_source_that_failed_is_left_out_not_zero():
    out = facts.compute_facts(manifest={"index": [{"name": "a", "path": "~/.agents/skills/a/SKILL.md"}]},
                              tests_python=None, tests_js=None, tests_site=None,
                              merged_prs=None, placement={}, adr_names=[], network={}, today="2026-10-08")
    assert "tests" not in out and "tests_python" not in out and "prs_merged" not in out and "agents" not in out
    assert out["skills"] == 1


def test_formatted_numbers_use_thousands_separators():
    assert facts.formatted({"tests": 2780, "skills": 35, "counted_on": "8 October 2026"}) == {
        "tests": "2,780", "skills": "35", "counted_on": "8 October 2026"}


def _skills(index):
    return facts.compute_facts(manifest={"index": index}, tests_python=None, tests_js=None, tests_site=None,
                               merged_prs=None, placement={}, adr_names=[], network={}, today="2026-10-22").get("skills")


def test_skills_counts_entries_that_are_a_skill_file_not_the_memories_the_index_also_holds():
    mem = "~/.claude/projects/-Users-gileskayo/memory/"
    index = [{"name": "tdd", "path": "~/.agents/skills/tdd/SKILL.md", "tags": ["type:skill"]},
             {"name": "qa-agent", "path": "~/.agents/skills/qa-agent/SKILL.md", "tags": ["type:agent"]},
             {"name": "safety-monitor", "path": "~/.agents/skills/safety-monitor/SKILL.md", "tags": ["type:library"]},
             {"name": "reference-mcp", "path": mem + "reference-mcp.md", "tags": ["type:knowledge"]},
             {"name": "fake", "path": mem + "type-skill.md", "tags": ["type:skill"]},
             {"name": "near", "path": "~/.agents/skills/near/SKILL.md.bak"},
             {"name": "nopath"},
             "not-a-dict"]
    assert _skills(index) == 3


def test_an_index_with_no_skills_leaves_the_number_out_rather_than_writing_zero():
    assert _skills([{"name": "m", "path": "~/.claude/projects/x/memory/m.md"}]) is None


def test_merge_with_previous_carries_forward_missing_figures():
    fresh = {"skills": 35, "agents": 5, "counted_on": "15 November 2026"}
    previous = {"tests": 2780, "prs_merged": 58, "machines": 2, "counted_on": "14 November 2026"}
    result = facts.merge_with_previous(fresh, previous)
    assert result["skills"] == 35  # from fresh
    assert result["agents"] == 5  # from fresh
    assert result["tests"] == 2780  # carried forward
    assert result["prs_merged"] == 58  # carried forward
    assert result["machines"] == 2  # carried forward
    assert result["counted_on"] == "15 November 2026"  # fresh overwrites


def test_merge_with_previous_empty_previous():
    fresh = {"skills": 35, "tests": 2000}
    result = facts.merge_with_previous(fresh, {})
    assert result == fresh


def test_merge_with_previous_empty_fresh():
    fresh = {}
    previous = {"skills": 35, "tests": 2000}
    result = facts.merge_with_previous(fresh, previous)
    assert result["skills"] == 35
    assert result["tests"] == 2000


def test_merge_with_previous_stamps_counted_on_on_stale():
    """When a figure is carried forward, its _counted_on is carried from previous to show when it was actually last counted."""
    fresh = {"skills": 36, "counted_on": "15 November 2026"}
    previous = {"tests": 2780, "tests_counted_on": "14 November 2026", "skills": 35, "counted_on": "14 November 2026"}
    result = facts.merge_with_previous(fresh, previous)
    assert result["tests"] == 2780  # carried forward
    assert result["tests_counted_on"] == "14 November 2026"  # carried from previous, shows when it was last counted
    assert result["skills"] == 36  # fresh overwrites


def test_merge_with_previous_first_stale_gets_counted_on():
    """First time a figure goes stale, it gets stamped with previous overall counted_on."""
    fresh = {"skills": 35, "agents": 5, "counted_on": "16 November 2026"}
    previous = {"tests": 2780, "skills": 34, "agents": 4, "counted_on": "15 November 2026"}
    result = facts.merge_with_previous(fresh, previous)
    assert result["tests"] == 2780  # carried forward
    assert result["tests_counted_on"] == "15 November 2026"  # stamped with previous overall counted_on


def test_pytest_collected_accepts_exit_code_2():
    """pytest collection error (exit 2) still extracts test count if output is available."""
    import subprocess
    # Mock subprocess to return exit code 2 with collected count
    original_run = subprocess.run

    def mock_run(cmd, **kwargs):
        if "-m" in cmd and "pytest" in cmd:
            class Result:
                returncode = 2
                stdout = "5 test collected in 0.5s\n"
                stderr = "ERROR: some collection error"
            return Result()
        return original_run(cmd, **kwargs)

    subprocess.run = mock_run
    try:
        count = facts._pytest_collected()
        assert count == 5  # Should extract despite exit code 2
    finally:
        subprocess.run = original_run


def test_vitest_uses_summary_line_not_banner():
    """vitest counting looks for summary line, not banner lines with 'test' in them."""
    import subprocess
    original_run = subprocess.run

    def mock_run(cmd, **kwargs):
        if "test:list" in cmd:
            class Result:
                returncode = 0
                stdout = "npm warn some banner\n42 test\nmore output\n"
                stderr = ""
            return Result()
        return original_run(cmd, **kwargs)

    subprocess.run = mock_run
    try:
        count = facts._vitest_listed()
        assert count == 42  # Should extract from summary
    finally:
        subprocess.run = original_run


def test_site_tests_tries_multiple_runners():
    """site tests tries Jest first, then Node's --test runner."""
    import subprocess
    import tempfile
    from pathlib import Path as PathlibPath

    original_run = subprocess.run
    call_count = [0]

    def mock_run(cmd, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call (Jest) fails
            class Result:
                returncode = 1
                stdout = ""
                stderr = "not a jest project"
            return Result()
        else:
            # Second call (Node --test) succeeds
            class Result:
                returncode = 0
                stdout = "ok 1 - test suite\n# tests 25\n"
                stderr = ""
            return Result()

    subprocess.run = mock_run
    try:
        with tempfile.TemporaryDirectory() as tmp:
            site_dir = PathlibPath(tmp)
            # Create site_dir so it exists check passes
            count = facts._site_tests_collected(site_dir)
            # Should extract 25 from "# tests 25" summary line
            assert count == 25
    finally:
        subprocess.run = original_run


def test_merged_pipeline_prs_uses_head_ref_not_title():
    """PR counting uses pipeline/* head ref, not title regex matching."""
    import subprocess
    original_run = subprocess.run

    def mock_run(cmd, **kwargs):
        if "/pulls" in " ".join(cmd):
            # Check that the query filters by head.ref
            if "startswith" in " ".join(cmd) and "pipeline/" in " ".join(cmd):
                class Result:
                    returncode = 0
                    stdout = "2026-10-15T10:30:00Z\n2026-10-14T09:20:00Z\n"
                    stderr = ""
                return Result()
        return subprocess.CompletedProcess(cmd, 1, "", "")

    subprocess.run = mock_run
    try:
        repos = [{"repo": "G-Eskayo/marvin"}]
        count = facts._merged_pipeline_prs_total(repos)
        assert count == 2  # Should count both merged PRs
    finally:
        subprocess.run = original_run


def test_closed_prs_uses_pagination():
    """closed PRs fetch uses --paginate to get more than 30 results."""
    import subprocess
    original_run = subprocess.run

    def mock_run(cmd, **kwargs):
        # Check that --paginate is in the command
        if "--paginate" in cmd:
            class Result:
                returncode = 0
                stdout = "\n".join([f"2026-10-{i:02d}T10:00:00Z" for i in range(1, 31)])
                stderr = ""
            return Result()
        return subprocess.CompletedProcess(cmd, 1, "", "")

    subprocess.run = mock_run
    try:
        count = facts._closed_prs("G-Eskayo/marvin")
        assert count == 30
    finally:
        subprocess.run = original_run
