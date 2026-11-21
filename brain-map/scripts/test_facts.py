#!/usr/bin/env python3
"""facts.py: the MARVIN page's numbers, computed from the system (docs/plans/living-marvin-page-2026-10-08.md)."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import facts  # noqa: E402


def test_compute_facts_counts_from_each_source():
    out = facts.compute_facts(
        manifest={"index": [{"name": n, "path": f"~/.agents/skills/{n}/SKILL.md"} for n in "abc"]},
        pytest_collected=1200, vitest_count=850, site_count=130,
        merged_prs=58, placement={"x": "both", "y": "mini", "z": "laptop"},
        adr_names=["0001-a.md", "0056-b.md", "0056-c.md", "README.md"], network={"devices": {"m": {}, "l": {}}},
        today="2026-10-08")
    assert out["skills"] == 3
    assert out["tests"] == 2180           # sum of all test parts
    assert out["tests_pytest"] == 1200
    assert out["tests_vitest"] == 850
    assert out["tests_site"] == 130
    assert out["prs_merged"] == 58
    assert out["agents"] == 3
    assert out["decisions"] == 3          # files, not numbers: two ADRs share 0056
    assert out["machines"] == 2
    assert out["counted_on"] == "8 October 2026"


def test_a_source_that_failed_is_left_out_not_zero():
    out = facts.compute_facts(manifest={"index": [{"name": "a", "path": "~/.agents/skills/a/SKILL.md"}]},
                              pytest_collected=None, vitest_count=None, site_count=None,
                              merged_prs=None, placement={},
                              adr_names=[], network={}, today="2026-10-08")
    assert "tests" not in out and "tests_pytest" not in out and "prs_merged" not in out and "agents" not in out and "machines" not in out
    assert out["skills"] == 1  # the page keeps its typed number for anything missing


def test_formatted_numbers_use_thousands_separators():
    assert facts.formatted({"tests": 2780, "skills": 35, "counted_on": "8 October 2026"}) == {
        "tests": "2,780", "skills": "35", "counted_on": "8 October 2026"}


def _skills(index):
    return facts.compute_facts(manifest={"index": index}, pytest_collected=None, vitest_count=None, site_count=None,
                               merged_prs=None, placement={},
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


def test_pytest_collected_parses_output():
    def run_mock(cmd, **kwargs):
        result = subprocess.CompletedProcess(cmd, 0)
        result.stdout = "1234 tests collected in 1.23s"
        result.stderr = ""
        return result
    repo = Path("/fake/repo")
    count = facts._pytest_collected(repo, run=run_mock)
    assert count == 1234


def test_pytest_collected_handles_errors():
    def run_mock(cmd, **kwargs):
        result = subprocess.CompletedProcess(cmd, 1)
        result.stdout = ""
        result.stderr = "error"
        return result
    repo = Path("/fake/repo")
    count = facts._pytest_collected(repo, run=run_mock)
    assert count is None


def test_pytest_collected_timeout():
    def run_mock(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 60)
    repo = Path("/fake/repo")
    count = facts._pytest_collected(repo, run=run_mock)
    assert count is None


def test_vitest_count_parses_list_output(tmp_path):
    def run_mock(cmd, **kwargs):
        result = subprocess.CompletedProcess(cmd, 0)
        result.stdout = "file1.test.ts\nfile2.test.ts\nfile3.test.ts"
        result.stderr = ""
        return result
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "dashboard").mkdir(exist_ok=True)
    count = facts._vitest_count(repo, run=run_mock)
    assert count == 3


def test_vitest_count_missing_dashboard():
    repo = Path("/fake/nonexistent/repo")
    count = facts._vitest_count(repo)
    assert count is None


def test_vitest_count_command_failure(tmp_path):
    def run_mock(cmd, **kwargs):
        result = subprocess.CompletedProcess(cmd, 1)
        result.stdout = ""
        result.stderr = "error"
        return result
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "dashboard").mkdir(exist_ok=True)
    count = facts._vitest_count(repo, run=run_mock)
    assert count is None


def test_site_test_count_parses_tap_output(tmp_path):
    def run_mock(cmd, **kwargs):
        result = subprocess.CompletedProcess(cmd, 0)
        result.stdout = "1..42\n# tests 42"
        result.stderr = ""
        return result
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    site_dir = repo / "site"
    site_dir.mkdir(exist_ok=True)
    scripts_dir = site_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    (scripts_dir / "test1.test.mjs").write_text("")
    count = facts._site_test_count(repo, run=run_mock)
    assert count == 42


def test_site_test_count_no_test_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "site" / "scripts").mkdir(parents=True, exist_ok=True)
    count = facts._site_test_count(repo)
    assert count is None


def test_site_test_count_missing_site_dir():
    repo = Path("/fake/nonexistent/repo")
    count = facts._site_test_count(repo)
    assert count is None


def test_gh_json_calls_gh_api():
    def fetch_mock(path):
        if "pulls" in path:
            return {"items": [{"title": "Implement G-Eskayo/marvin#123"}]}
        return {}
    result = facts._gh_json("repos/owner/name/pulls", fetch=fetch_mock)
    assert result["items"][0]["title"] == "Implement G-Eskayo/marvin#123"


def test_gh_json_returns_none_on_failure():
    def fetch_mock(path):
        return None
    result = facts._gh_json("bad/path", fetch=fetch_mock)
    assert result is None


def test_merged_pipeline_prs_sums_across_repos():
    def fetch_mock(path):
        if "marvin/pulls" in path:
            return {"items": [{"title": "Implement G-Eskayo/marvin#1"}, {"title": "other"}]}
        elif "seal/pulls" in path:
            return {"items": [{"title": "Implement G-Eskayo/seal#2"}, {"title": "Implement G-Eskayo/seal#3"}]}
        return {"items": []}
    repos = [{"repo": "G-Eskayo/marvin"}, {"repo": "G-Eskayo/seal"}]
    count = facts._merged_pipeline_prs(repos, fetch=fetch_mock)
    assert count == 3  # 1 from marvin, 2 from seal


def test_merged_pipeline_prs_empty_repos():
    count = facts._merged_pipeline_prs([])
    assert count is None


def test_merged_pipeline_prs_handles_fetch_failure():
    def fetch_mock(path):
        return None
    repos = [{"repo": "G-Eskayo/marvin"}]
    count = facts._merged_pipeline_prs(repos, fetch=fetch_mock)
    assert count is None


def test_merge_with_previous_keeps_fresh_values():
    fresh = {"tests_pytest": 1200, "prs_merged": 50, "counted_on": "8 October 2026"}
    previous = {"tests_pytest": 800, "tests_vitest": 500, "prs_merged": 40, "counted_on": "7 October 2026"}
    result = facts.merge_with_previous(fresh, previous)
    assert result["tests_pytest"] == 1200  # fresh
    assert result["prs_merged"] == 50  # fresh
    assert result["counted_on"] == "8 October 2026"  # fresh


def test_merge_with_previous_carries_forward_missing_parts():
    fresh = {"tests_pytest": 1200, "counted_on": "8 October 2026"}
    previous = {"tests_pytest": 800, "tests_vitest": 500, "tests_site": 100,
                "tests_vitest_counted_on": "7 October 2026", "tests_site_counted_on": "7 October 2026"}
    result = facts.merge_with_previous(fresh, previous)
    assert result["tests_pytest"] == 1200  # fresh
    assert result["tests_vitest"] == 500  # carried forward
    assert result["tests_site"] == 100  # carried forward
    assert result["tests_vitest_counted_on"] == "7 October 2026"  # preserved
    assert result["tests_site_counted_on"] == "7 October 2026"  # preserved


def test_merge_with_previous_recalculates_tests():
    fresh = {"tests_pytest": 1200, "counted_on": "8 October 2026"}
    previous = {"tests_pytest": 800, "tests_vitest": 500, "tests_site": 100}
    result = facts.merge_with_previous(fresh, previous)
    assert result["tests"] == 1800  # 1200 + 500 + 100


def test_merge_with_previous_no_tests_if_all_failed():
    fresh = {"prs_merged": 50, "counted_on": "8 October 2026"}
    previous = {"tests_pytest": 800}
    result = facts.merge_with_previous(fresh, previous)
    # No tests in fresh, and vitest/site not in previous, so only pytest carried forward
    assert result.get("tests_pytest") == 800
    assert result.get("tests") == 800  # Sum of just pytest


def test_merge_with_previous_bootstraps_counted_on_from_legacy():
    fresh = {"tests_pytest": 1200, "counted_on": "8 October 2026"}
    previous = {"tests_vitest": 500, "counted_on": "7 October 2026"}  # no tests_vitest_counted_on
    result = facts.merge_with_previous(fresh, previous)
    assert result["tests_vitest_counted_on"] == "7 October 2026"  # bootstrapped from counted_on


def test_merge_with_previous_carries_forward_old_flat_tests_when_all_parts_fail():
    """Migration bootstrap: when all three test parts are missing and previous has the old flat 'tests',
    carry that value forward rather than vanishing (pre-feature facts.json compatibility)."""
    fresh = {"prs_merged": 50, "counted_on": "8 October 2026"}
    previous = {"tests": 3820, "counted_on": "7 October 2026"}  # old flat schema, no part-level keys
    result = facts.merge_with_previous(fresh, previous)
    assert result["tests"] == 3820  # old flat value carried forward
    assert result["prs_merged"] == 50  # fresh value kept
    assert "tests_pytest" not in result  # parts not created from missing sources


def test_decisions_with_multiple_adrs_same_number():
    # 0056-a.md and 0056-b.md are the same number, should count as one unique file
    out = facts.compute_facts(
        manifest={"index": []}, pytest_collected=None, vitest_count=None, site_count=None,
        merged_prs=None, placement={}, adr_names=["0001-a.md", "0056-a.md", "0056-b.md", "0057-c.md"],
        network={}, today="2026-10-08")
    assert out["decisions"] == 4  # all 4 are counted by the regex match


def test_agents_empty_placement():
    out = facts.compute_facts(
        manifest={"index": []}, pytest_collected=None, vitest_count=None, site_count=None,
        merged_prs=None, placement={}, adr_names=[],
        network={}, today="2026-10-08")
    assert "agents" not in out


def test_machines_with_empty_devices():
    out = facts.compute_facts(
        manifest={"index": []}, pytest_collected=None, vitest_count=None, site_count=None,
        merged_prs=None, placement={}, adr_names=[],
        network={"devices": {}}, today="2026-10-08")
    assert "machines" not in out


def test_machines_with_devices():
    out = facts.compute_facts(
        manifest={"index": []}, pytest_collected=None, vitest_count=None, site_count=None,
        merged_prs=None, placement={}, adr_names=[],
        network={"devices": {"mini": {}, "laptop": {}, "server": {}}}, today="2026-10-08")
    assert out["machines"] == 3
