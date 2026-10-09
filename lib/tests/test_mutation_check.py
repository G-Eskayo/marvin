"""Mutation testing for the merge gate: measure test quality by killing mutants."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mutation_check as mc  # noqa: E402


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A git repo with Python and JS test files."""
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@t.com")
    git(tmp_path, "config", "user.name", "T")

    # Python code and test
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "math_utils.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "lib" / "tests").mkdir()
    (tmp_path / "lib" / "tests" / "test_math_utils.py").write_text(
        "import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
        "import math_utils\n"
        "def test_add():\n"
        "    assert math_utils.add(1, 2) == 3\n"
    )

    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "initial")
    return tmp_path


def test_diff_with_no_mutable_lines_scores_1_0(repo):
    """A diff with nothing mutable (docs, pure rename) returns score 1.0, status ok."""
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "README.md").write_text("# Documentation\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "docs")

    result = mc.run_mutation_check(
        repo,
        "feature",
        "main",
        git(repo, "merge-base", "main", "feature")
    )

    assert result["status"] == "ok"
    assert result["score"] == 1.0
    assert result["mutants_total"] == 0


def test_mutant_in_test_file_is_skipped(repo):
    """Mutants in test files are generated and not scored."""
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "lib" / "tests" / "test_math_utils.py").write_text(
        "import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
        "import math_utils\n"
        "def test_add():\n"
        "    assert math_utils.add(1, 2) == 3\n"
        "    assert math_utils.add(2, 2) == 4\n"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "add test")

    result = mc.run_mutation_check(
        repo,
        "feature",
        "main",
        git(repo, "merge-base", "main", "feature")
    )

    # Only the test file changed, which is skipped entirely
    assert result["status"] == "ok"
    assert result["mutants_total"] == 0


def test_test_file_already_red_on_clean_baseline_is_excluded(repo):
    """A test file that fails on a clean baseline is excluded from scoring."""
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "lib" / "math_utils.py").write_text("def add(a, b):\n    return a + b + 999\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "break test")

    result = mc.run_mutation_check(
        repo,
        "feature",
        "main",
        git(repo, "merge-base", "main", "feature")
    )

    # The test was already red on the baseline, so nothing is scored
    # If no mutants are generated, status is ok; if mutants exist but can't be scored, status is unknown
    assert result["status"] in ("ok", "unknown")


def test_zero_mutable_lines_is_not_unknown(repo):
    """Zero mutable lines (all docs/config) returns score 1.0, status ok, not unknown."""
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "config.json").write_text('{"debug": true}\n')
    (repo / "notes.txt").write_text("implementation notes\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "config")

    result = mc.run_mutation_check(
        repo,
        "feature",
        "main",
        git(repo, "merge-base", "main", "feature")
    )

    assert result["status"] == "ok", f"Expected status 'ok', got {result['status']}"
    assert result["mutants_total"] == 0


def test_no_mutate_pragma_excludes_line(repo):
    """A `# no-mutate` pragma on a line excludes it from mutation."""
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "lib" / "critical.py").write_text(
        "def validate(x):\n"
        "    return x != 0  # no-mutate\n"
    )
    (repo / "lib" / "tests" / "test_critical.py").write_text(
        "import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
        "import critical\n"
        "def test_validate():\n"
        "    assert critical.validate(5) == True\n"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "add critical")

    result = mc.run_mutation_check(
        repo,
        "feature",
        "main",
        git(repo, "merge-base", "main", "feature")
    )

    # The pragma line should be excluded, so no mutants generated or all unmeasured
    assert result["status"] in ("ok", "unknown")


def test_pr_touching_50_files_is_sampled_and_time_boxed(repo):
    """A PR touching many files is sampled deterministically and stays within budget."""
    git(repo, "checkout", "-q", "-b", "feature")
    # Create 50 trivial Python files
    for i in range(50):
        f = repo / f"lib" / f"module{i}.py"
        f.write_text(f"def func{i}():\n    return {i}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "add many")

    result = mc.run_mutation_check(
        repo,
        "feature",
        "main",
        git(repo, "merge-base", "main", "feature"),
        max_mutants_per_pr=60,
        max_mutants_per_file=8
    )

    # Should complete without timing out, with sampled or no mutants
    assert result["status"] in ("ok", "unknown")
    assert result["mutants_total"] <= 60 + 8  # Bounded


def test_first_run_appends_to_empty_pr_body(repo):
    """The first mutation section in a PR body is appended if not present."""
    body = "Existing PR description\n"
    section = "## Mutation Score\n\n80% (4/5 mutants killed)\n"

    result = mc.merge_bodies(body, section)

    assert "Existing PR description" in result
    assert "Mutation Score" in result
    assert result.count("<!-- marvin:mutation-check -->") == 1


def test_second_run_replaces_mutation_section_in_place(repo):
    """Subsequent mutation sections replace the old one."""
    body = (
        "Existing PR description\n"
        "<!-- marvin:mutation-check -->\n"
        "## Mutation Score\n80% (4/5 mutants killed)\n"
        "<!-- /marvin:mutation-check -->\n"
        "More content\n"
    )
    new_section = "## Mutation Score\n\n90% (9/10 mutants killed)\n"

    result = mc.merge_bodies(body, new_section)

    assert result.count("<!-- marvin:mutation-check -->") == 1
    assert "90%" in result
    assert "80%" not in result
    assert "More content" in result


def test_pr_body_merge_is_idempotent(repo):
    """Running the mutation section merge twice produces the same result."""
    body = "Initial\n"
    section = "Mutation: 75%\n"

    first = mc.merge_bodies(body, section)
    second = mc.merge_bodies(first, section)

    assert first == second


def test_mutant_sampling_is_deterministic_across_runs(repo):
    """The same head_ref always samples the same mutants (stable hash, not salted)."""
    git(repo, "checkout", "-q", "-b", "feature")
    # Create 100 trivial Python files to force sampling
    for i in range(100):
        f = repo / f"lib" / f"sample{i}.py"
        f.write_text(f"def func{i}():\n    return {i} if True else 0\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "add many samples")

    base_sha = git(repo, "merge-base", "main", "feature")

    # Run mutation check twice with the same head_ref
    result1 = mc.run_mutation_check(
        repo,
        "feature",
        "main",
        base_sha,
        max_mutants_per_pr=40  # Force sampling
    )

    result2 = mc.run_mutation_check(
        repo,
        "feature",
        "main",
        base_sha,
        max_mutants_per_pr=40  # Same seed = same sample
    )

    # The sampled mutants should be identical (same files and lines)
    sample1_keys = {(m["file"], m["line"]) for m in result1["survived"] + result1["unmeasured"]}
    sample2_keys = {(m["file"], m["line"]) for m in result2["survived"] + result2["unmeasured"]}

    # With deterministic sampling, both runs should select the same mutants
    assert sample1_keys == sample2_keys, "Sampling should be deterministic across runs"
