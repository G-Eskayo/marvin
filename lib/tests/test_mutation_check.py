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


# 2026-10-09 review: '_changed_lines' read the path with the first "b/" in "diff --git a/lib/x.py b/lib/x.py" -- and
# "lib/" contains "b/" -- so every lib/ file got a garbled name, no mutants, and a perfect score.
def test_changed_lines_names_every_file_correctly_including_lib_paths_new_files_and_spaces(repo):
    base = git(repo, "rev-parse", "HEAD")
    (repo / "lib" / "math_utils.py").write_text("def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n")
    (repo / "lib" / "new_mod.py").write_text("X = 1\n")
    (repo / "lib" / "with space.py").write_text("Y = 2\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "work")
    changed = mc._changed_lines(str(repo), base, "HEAD")
    assert set(changed) == {"lib/math_utils.py", "lib/new_mod.py", "lib/with space.py"}
    assert changed["lib/math_utils.py"] == {3, 4, 5}
    assert changed["lib/new_mod.py"] == {1}


def test_a_deleted_file_has_no_lines_to_mutate(repo):
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "rm", "-q", "lib/math_utils.py"); git(repo, "commit", "-qm", "gone")
    assert mc._changed_lines(str(repo), base, "HEAD") == {}


# ── 2026-10-09 review: the engine has to really plant bugs and really run the tests ─────────────────────────────

def _branch_with(repo, files: dict, msg="work"):
    git(repo, "checkout", "-q", "-b", "feature")
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", msg)
    return git(repo, "merge-base", "main", "feature")


_IMPORT = "import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
SIGN = "def sign(x):\n    if x > 0:\n        return 1\n    if x < 0:\n        return -1\n    return 0\n"


def test_weak_tests_let_planted_bugs_survive_and_the_score_says_so(repo):
    base = _branch_with(repo, {"lib/signs.py": SIGN,
                               "lib/tests/test_signs.py": _IMPORT + "import signs\ndef test_pos():\n    assert signs.sign(5) == 1\n"})
    r = mc.run_mutation_check(repo, "feature", "main", base)
    assert r["status"] == "ok" and r["mutants_total"] > 0
    assert r["survived"] and 0 <= r["score"] < 1
    assert all(s["file"] == "lib/signs.py" for s in r["survived"])


def test_thorough_tests_catch_every_planted_bug(repo):
    tests = _IMPORT + ("import signs\ndef test_all():\n    assert signs.sign(5) == 1\n    assert signs.sign(-5) == -1\n"
                       "    assert signs.sign(0) == 0\n    assert signs.sign(1) == 1\n    assert signs.sign(-1) == -1\n")
    base = _branch_with(repo, {"lib/signs.py": SIGN, "lib/tests/test_signs.py": tests})
    r = mc.run_mutation_check(repo, "feature", "main", base)
    assert r["status"] == "ok" and r["mutants_total"] > 0 and r["score"] == 1.0 and not r["survived"]


def test_the_checkout_is_left_exactly_as_it_was(repo):
    base = _branch_with(repo, {"lib/signs.py": SIGN,
                               "lib/tests/test_signs.py": _IMPORT + "import signs\ndef test_pos():\n    assert signs.sign(5) == 1\n"})
    mc.run_mutation_check(repo, "feature", "main", base)
    assert git(repo, "status", "--porcelain") == ""
    assert (repo / "lib" / "signs.py").read_text() == SIGN


def test_a_planted_bug_that_hangs_times_out_and_counts_as_caught(repo, monkeypatch):
    base = _branch_with(repo, {"lib/signs.py": SIGN,
                               "lib/tests/test_signs.py": _IMPORT + "import signs\ndef test_pos():\n    assert signs.sign(5) == 1\n"})
    calls = {"n": 0}

    def fake(cwd, tests, timeout):
        calls["n"] += 1
        return "pass" if calls["n"] == 1 else "timeout"      # the clean baseline passes; every mutant hangs
    monkeypatch.setattr(mc, "_run_tests", fake)
    r = mc.run_mutation_check(repo, "feature", "main", base)
    assert r["status"] == "ok" and r["score"] == 1.0 and r["killed"] == r["mutants_total"] > 0


def test_a_real_timeout_is_reported_as_timeout(repo):
    (repo / "lib" / "tests" / "test_hang.py").write_text("import time\ndef test_h():\n    time.sleep(30)\n")
    assert mc._run_tests(str(repo), ["lib/tests/test_hang.py"], timeout=2) == "timeout"


def test_code_with_no_test_to_run_is_unknown_not_a_score(repo):
    base = _branch_with(repo, {"lib/orphan.py": "def f(x):\n    return x > 1\n"})
    r = mc.run_mutation_check(repo, "feature", "main", base)
    assert r["status"] == "unknown" and r["score"] is None and r["unmeasured"]


def test_js_changes_are_unmeasured_for_now_never_scored(repo):
    base = _branch_with(repo, {"dashboard/src/x.js": "export const f = (a) => a > 1\n"})
    r = mc.run_mutation_check(repo, "feature", "main", base)
    assert r["status"] == "unknown" and r["score"] is None


def test_a_mutant_counts_only_on_changed_lines(repo):
    base = _branch_with(repo, {"lib/math_utils.py": "def add(a, b):\n    return a + b\n\ndef big(x):\n    return x > 100\n",
                               "lib/tests/test_math_utils.py": _IMPORT + "import math_utils\ndef test_big():\n    assert math_utils.big(101)\n    assert not math_utils.big(100)\n"})
    r = mc.run_mutation_check(repo, "feature", "main", base)
    lines = {m["line"] for m in r["survived"] + r["unmeasured"]} | set(r.get("killed_lines", []))
    assert lines and all(l >= 4 for l in lines)          # add() on lines 1-2 was unchanged


def test_the_no_mutate_pragma_is_honoured(repo):
    base = _branch_with(repo, {"lib/critical.py": "def validate(x):\n    return x != 0  # no-mutate\n",
                               "lib/tests/test_critical.py": _IMPORT + "import critical\ndef test_v():\n    assert critical.validate(5)\n"})
    r = mc.run_mutation_check(repo, "feature", "main", base)
    assert r["mutants_total"] == 0 and r["status"] == "ok"


def test_a_survivor_shows_the_original_line(repo):
    base = _branch_with(repo, {"lib/signs.py": SIGN,
                               "lib/tests/test_signs.py": _IMPORT + "import signs\ndef test_pos():\n    assert signs.sign(5) == 1\n"})
    r = mc.run_mutation_check(repo, "feature", "main", base)
    src = SIGN.splitlines()
    assert r["survived"] and all(s["snippet"] == src[s["line"] - 1].strip() for s in r["survived"])


# One writer for the PR-body section (review 2026-10-09): the card (mr_review.js parseMutationSection) reads
# "NN% (k/n)" and the shadow mode (auto_merge_shadow.mutation_score) reads "**Score:** NN%".
def test_the_section_reads_back_in_both_readers():
    import re
    md = mc.render_section({"status": "ok", "score": 0.75, "mutants_total": 8, "killed": 6,
                            "survived": [{"file": "lib/x.py", "line": 3, "operator": "flip-comparison", "snippet": "if a > b:"},
                                         {"file": "lib/x.py", "line": 7, "operator": "return-none", "snippet": "return out"}],
                            "unmeasured": []})
    assert md.startswith("## Mutation Score")
    assert re.search(r"(\d+(?:\.\d+)?)%\s*\((\d+)/(\d+)\)", md).groups() == ("75", "6", "8")
    assert re.search(r"\*\*score:\*\*\s*(\d{1,3})\s*%", md, re.I).group(1) == "75"
    assert "lib/x.py" in md and "if a > b:" in md


def test_unknown_and_nothing_to_mutate_read_back_too():
    import re
    unknown = mc.render_section({"status": "unknown", "score": None, "reason": "no test file for it", "mutants_total": 2,
                                 "killed": 0, "survived": [], "unmeasured": [{"file": "lib/y.py", "line": 1}]})
    assert re.search(r"unknown\s*\(([^)]+)\)", unknown) and "%" not in unknown.split("\n", 2)[2].split("\n")[0]
    nothing = mc.render_section({"status": "ok", "score": 1.0, "mutants_total": 0, "killed": 0, "survived": [], "unmeasured": []})
    assert re.search(r"no mutable lines", nothing, re.I)


# Found by running the check on itself (50% at first): four behaviours no test exercised.
def test_or_and_and_are_really_swapped(repo):
    either = "def either(a, b):\n    return a or b\n"
    tests = _IMPORT + ("import either\ndef test_e():\n    assert either.either(True, False) is True\n"
                       "    assert either.either(False, False) is False\n    assert either.either(False, True) is True\n")
    base = _branch_with(repo, {"lib/either.py": either, "lib/tests/test_either.py": tests})
    r = mc.run_mutation_check(repo, "feature", "main", base)
    assert r["mutants_total"] > 0 and not r["unmeasured"] and r["score"] == 1.0


def test_a_not_inside_a_list_is_really_dropped(repo):
    src = "def none_of(a, b):\n    return all([not a, not b])\n"
    tests = _IMPORT + ("import none_of\ndef test_n():\n    assert none_of.none_of(False, False) is True\n"
                       "    assert none_of.none_of(True, False) is False\n    assert none_of.none_of(False, True) is False\n")
    base = _branch_with(repo, {"lib/none_of.py": src, "lib/tests/test_none_of.py": tests})
    r = mc.run_mutation_check(repo, "feature", "main", base)
    assert r["mutants_total"] > 0 and not r["unmeasured"] and r["score"] == 1.0


def test_unknown_reports_nothing_killed(repo):
    base = _branch_with(repo, {"lib/orphan.py": "def f(x):\n    return x > 1\n"})
    r = mc.run_mutation_check(repo, "feature", "main", base)
    assert r["status"] == "unknown" and r["killed"] == 0 and r["survived"] == []


def test_the_command_line_prints_json_and_exits_nonzero_when_unknown(repo):
    base = _branch_with(repo, {"lib/orphan.py": "def f(x):\n    return x > 1\n"})
    script = str(Path(mc.__file__))
    p = subprocess.run([sys.executable, script, "run", "G-Eskayo/marvin", str(repo), base], capture_output=True, text=True)
    assert p.returncode == 1 and json.loads(p.stdout.strip().splitlines()[-1])["status"] == "unknown"
    git(repo, "checkout", "-q", "main")
    p2 = subprocess.run([sys.executable, script, "run", "G-Eskayo/marvin", str(repo), base, "main"], capture_output=True, text=True)
    assert p2.returncode == 0 and json.loads(p2.stdout.strip().splitlines()[-1])["mutants_total"] == 0
