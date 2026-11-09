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


# ── macOS-only tests (marvin#1117): GitHub runs the suite on Linux, the Macs (the Mini's gate) run everything ────

MAC_SUITE = '''
import pytest
import tool_requirements as tr

@pytest.mark.macos_only("launchctl loads the plist")
def test_needs_a_mac():
    assert True

@pytest.mark.macos_only("plutil reads it")
@pytest.mark.requires_tool("no-such-mac-tool-1117")
def test_a_mac_tool():
    assert False, "never runs on Linux, and fails on a Mac only for the missing tool"

def test_portable():
    assert True
'''

MODULE_SUITE = '''
import tool_requirements as tr
tr.require_macos("the whole module drives Keychain")

def test_keychain():
    assert True
'''


def _run(tmp_path: Path, body: str, platform: str | None, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    # The platform is pinned by a conftest in the temp suite, never by an environment knob (a knob could make a Mac
    # skip its own tests); `None` leaves the real one.
    (tmp_path / "test_suite.py").write_text(body)
    pin = f"import tool_requirements\ntool_requirements.PLATFORM = {platform!r}\n" if platform else ""
    (tmp_path / "conftest.py").write_text(pin)
    env = {k: v for k, v in os.environ.items() if k not in ("MARVIN_REQUIRE_TOOLS", "PYTEST_ADDOPTS")}
    env.update({"PYTHONPATH": str(ROOT / "lib"), **(env_extra or {})})
    return subprocess.run([sys.executable, "-m", "pytest", "-p", "tool_requirements", "-p", "no:cacheprovider",
                           "-rs", "-q", str(tmp_path / "test_suite.py")], cwd=tmp_path, capture_output=True, text=True,
                          env=env, timeout=120)


def test_off_macos_a_mac_only_test_skips_and_says_the_mac_gate_runs_it(tmp_path):
    r = _run(tmp_path, MAC_SUITE, "linux")
    assert r.returncode == 0, r.stdout
    assert "1 passed, 2 skipped" in r.stdout
    assert "needs macOS: launchctl loads the plist (the Mac gate runs it)" in r.stdout


def test_off_macos_it_skips_even_under_ci_strict_tools(tmp_path):
    # MARVIN_REQUIRE_TOOLS=1 fails a missing tool; a Mac-only tool on Linux isn't missing, the test just isn't for here.
    r = _run(tmp_path, MAC_SUITE, "linux", {"MARVIN_REQUIRE_TOOLS": "1"})
    assert r.returncode == 0, r.stdout
    assert "1 passed, 2 skipped" in r.stdout


def test_on_macos_a_mac_only_test_always_runs(tmp_path):
    r = _run(tmp_path, MAC_SUITE, "darwin")
    assert "2 passed, 1 skipped" in r.stdout, r.stdout   # the skip is the missing tool, never "needs macOS"
    assert "needs macOS" not in r.stdout


def test_the_run_ends_with_how_many_tests_need_a_mac(tmp_path):
    assert "needs macOS: 2 tests did not run here; the Mac gate runs them" in _run(tmp_path, MAC_SUITE, "linux").stdout


def test_a_whole_module_can_need_macos(tmp_path):
    assert "1 skipped" in _run(tmp_path, MODULE_SUITE, "linux").stdout
    assert "1 passed" in _run(tmp_path, MODULE_SUITE, "darwin").stdout


def test_a_mac_only_mark_must_say_why(tmp_path):
    r = _run(tmp_path, "import pytest\n@pytest.mark.macos_only()\ndef test_x():\n    pass\n", "linux")
    assert r.returncode != 0 and "macos_only needs a reason" in r.stdout + r.stderr, r.stdout + r.stderr
    r = _run(tmp_path, "import tool_requirements as tr\ntr.require_macos('')\ndef test_x():\n    pass\n", "linux")
    assert r.returncode != 0 and "require_macos needs a reason" in r.stdout + r.stderr, r.stdout + r.stderr


def test_the_real_platform_is_what_decides_by_default():
    assert tr.PLATFORM == sys.platform


def test_mac_only_tests_use_the_one_marker_not_their_own_platform_skips():
    # One place decides, and it provably never skips on a Mac (above), so the Mini's gate runs every Mac-only test.
    # A hand-rolled skipif on the platform would be a second way to skip on a Mac that nothing checks.
    import re
    rolled = re.compile(r"skip(if)?\([^)]*sys\.platform\s*!=\s*[\"']darwin")
    offenders = [str(p.relative_to(ROOT)) for d in ("lib/tests", "bench/tests") for p in (ROOT / d).rglob("test_*.py")
                 if rolled.search(p.read_text())]
    assert offenders == [], f"use @pytest.mark.macos_only('why') instead: {offenders}"


def test_github_runs_the_python_suite_on_linux_where_a_runner_is_always_free():
    # #1117: the macOS job waited for runners (17 min and none on #935); the Mac gate covers the Mac-only tests.
    import yaml
    job = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())["jobs"]["python-tests"]
    assert job["runs-on"] == "ubuntu-latest"
    steps = " ".join(str(s.get("run", "")) for s in job["steps"])
    assert "sha256sum -c" in steps and "gitleaks" in steps and "ripgrep" in steps
