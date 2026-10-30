"""marvin#826 step 5: a test says what tools it needs, and a machine without one is an infra problem, not a red test.
Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_tool_requirements.py -v

The same commit passed on one Mac and failed on the other: ripgrep was on the MacBook and missing on the Mini, so two
search tests failed only there and the gate refused every PR as MAIN_RED. lib/tool_requirements.py (a pytest plugin
the root conftest loads) gives tests `@pytest.mark.requires_tool("rg")` and `require_path()`: missing means the test
is skipped with "INFRA: this machine is missing rg" and the run ends with one line per missing tool, except under
$MARVIN_REQUIRE_TOOLS=1 (CI, which must have every tool), where a missing tool fails so the required list can't quietly shrink.
Real pytest runs in a temp folder; PATH is what decides, never a mock of shutil.which.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import tool_requirements as tr  # noqa: E402

SUITE = '''
import pytest
import tool_requirements as tr

@pytest.mark.requires_tool("sh")
def test_has_sh():
    assert True

@pytest.mark.requires_tool("no-such-tool-826", "sh")
def test_needs_a_missing_tool():
    assert False, "must never run"

@pytest.mark.requires_tool("no-such-tool-826")
def test_needs_it_too():
    assert False, "must never run"

def test_needs_a_file():
    tr.require_path("/no/such/organize/find_file.py", "the file finder lives in ~/.claude/organize")
    assert False, "must never run"
'''


def _pytest(tmp_path: Path, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    (tmp_path / "test_suite.py").write_text(SUITE)
    env = {k: v for k, v in os.environ.items() if k not in ("MARVIN_REQUIRE_TOOLS", "PYTEST_ADDOPTS")}
    env.update({"PYTHONPATH": str(ROOT / "lib"), **(env_extra or {})})
    return subprocess.run([sys.executable, "-m", "pytest", "-p", "tool_requirements", "-p", "no:cacheprovider",
                           "-rs", "-q", str(tmp_path / "test_suite.py")], cwd=tmp_path, capture_output=True, text=True,
                          env=env, timeout=120)


def test_a_missing_tool_skips_as_infra_and_the_run_stays_green(tmp_path):
    r = _pytest(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "1 passed, 3 skipped" in r.stdout
    assert "INFRA: this machine is missing no-such-tool-826" in r.stdout


def test_the_run_ends_with_one_line_per_missing_tool_and_how_many_tests_it_stopped(tmp_path):
    out = _pytest(tmp_path).stdout
    assert "INFRA: this machine is missing no-such-tool-826 (2 tests did not run)" in out
    assert "INFRA: this machine is missing /no/such/organize/find_file.py (1 test did not run)" in out


def test_under_ci_a_missing_tool_fails_so_the_required_list_cannot_quietly_shrink(tmp_path):
    # A tool CI can install fails there; a path outside the repo (the owner's ~/.claude) can't exist in CI: it skips.
    r = _pytest(tmp_path, {"MARVIN_REQUIRE_TOOLS": "1"})
    assert r.returncode == 1
    assert "1 passed, 1 skipped, 2 errors" in r.stdout and "INFRA" in r.stdout  # setup failures: red either way


def test_the_summary_survives_parallel_workers(tmp_path):
    # Under xdist the workers count, but the controller prints the summary: it must count from the skip reports.
    (tmp_path / "test_suite.py").write_text(SUITE)
    env = {k: v for k, v in os.environ.items() if k not in ("MARVIN_REQUIRE_TOOLS", "PYTEST_ADDOPTS")}
    r = subprocess.run([sys.executable, "-m", "pytest", "-p", "tool_requirements", "-p", "no:cacheprovider", "-q",
                        "-n", "2", str(tmp_path / "test_suite.py")], cwd=tmp_path, capture_output=True, text=True,
                       env={**env, "PYTHONPATH": str(ROOT / "lib")}, timeout=120)
    assert "INFRA: this machine is missing no-such-tool-826 (2 tests did not run)" in r.stdout, r.stdout


def test_missing_reports_only_what_is_not_on_path():
    assert tr.missing(["sh", "no-such-tool-826"]) == ["no-such-tool-826"]
    assert tr.missing(["sh"], path="/nowhere") == ["sh"]


# ── the tests that needed a tool now say so ─────────────────────────────────

def _marked(path: str, name: str) -> list[str]:
    import ast
    tree = ast.parse((ROOT / path).read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    return [ast.unparse(d) for d in fn.decorator_list]


@pytest.mark.parametrize("name", ["test_rg_ranks_the_file_matching_most_distinct_keywords",
                                  "test_rg_searches_the_folder_even_when_stdin_is_an_open_pipe"])
def test_the_ripgrep_tests_declare_rg(name):
    assert "pytest.mark.requires_tool('rg')" in _marked("bench/tests/test_retrieval_eval.py", name)


def test_the_find_file_tests_say_they_need_the_organize_folder():
    src = (ROOT / "lib" / "tests" / "test_find_file.py").read_text()
    assert "require_path(" in src and src.index("require_path(") < src.index("import find_file")


def test_the_root_conftest_loads_the_plugin():
    assert '"tool_requirements"' in (ROOT / "conftest.py").read_text()


def test_ci_runs_the_python_suite_strict():
    import yaml
    jobs = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())["jobs"]
    assert jobs["python-tests"]["env"]["MARVIN_REQUIRE_TOOLS"] == "1"
