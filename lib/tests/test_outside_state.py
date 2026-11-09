"""marvin#1047: a test that checks state outside this repo's code names what it checked, and its failure never makes main red.

At 5b93e994 the Mac mini's main-health failed four portfolio checks and the merge queue held every approved PR, while
GitHub's CI on main was green. Nothing in marvin was wrong. The portfolio dev site was serving the in-progress brand
redesign, and the portfolio checkout held uncommitted re-captures. Same class as #826 (a missing tool is infra, not a
red test). lib/outside_state.py (a pytest plugin the root conftest loads) gives tests `@pytest.mark.outside_state(what)`,
and every failure of a marked test ends the run with one line naming it. main_health reads those lines. When they are
the only failures, main is ok and they are recorded under `outside`. Health turns yellow and names them.
Real pytest runs in a temp folder, the same way as test_tool_requirements.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import main_health as mh  # noqa: E402
import outside_state as osx  # noqa: E402

SUITE = '''
import pytest

@pytest.mark.outside_state("the portfolio dev site")
def test_live_site_matches():
    assert False, "the site serves another design"

@pytest.mark.outside_state("the portfolio dev site")
def test_live_site_passes():
    assert True

def test_plain():
    assert True
'''

CODE_FAILS_TOO = SUITE + '''
def test_code_is_broken():
    assert False
'''


def _pytest(tmp_path: Path, suite: str = SUITE, *extra: str) -> subprocess.CompletedProcess:
    (tmp_path / "test_suite.py").write_text(suite)
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    env["PYTHONPATH"] = str(ROOT / "lib")
    return subprocess.run([sys.executable, "-m", "pytest", "-p", "outside_state", "-p", "no:cacheprovider", "-q",
                           *extra, str(tmp_path / "test_suite.py")], cwd=tmp_path, capture_output=True, text=True,
                          env=env, timeout=120)


def test_a_failing_outside_state_test_still_fails_and_the_run_names_what_it_checked(tmp_path):
    r = _pytest(tmp_path)
    assert r.returncode == 1, r.stdout               # pytest itself still says it failed: nothing is hidden
    assert "OUTSIDE STATE FAILED test_suite.py::test_live_site_matches (the portfolio dev site)" in r.stdout, r.stdout
    assert "test_live_site_passes" not in r.stdout.split("OUTSIDE STATE", 1)[1]


def test_the_lines_survive_parallel_workers(tmp_path):
    r = _pytest(tmp_path, SUITE, "-n", "2")
    assert "OUTSIDE STATE FAILED test_suite.py::test_live_site_matches (the portfolio dev site)" in r.stdout, r.stdout


def test_the_marker_needs_to_say_what_it_checked(tmp_path):
    r = _pytest(tmp_path, "import pytest\n\n@pytest.mark.outside_state()\ndef test_x():\n    assert True\n")
    assert r.returncode != 0 and "outside_state needs to say what" in r.stdout + r.stderr, r.stdout


# ── main_health's verdict ────────────────────────────────────────────────────

def test_only_outside_failures_leave_main_ok_and_are_recorded(tmp_path):
    r = _pytest(tmp_path)
    ok, failed, outside = mh.verdict(r.returncode, r.stdout)
    assert ok is True and failed == []
    assert outside == [{"test": "test_suite.py::test_live_site_matches", "what": "the portfolio dev site"}]


def test_a_code_failure_beside_them_is_still_red(tmp_path):
    r = _pytest(tmp_path, CODE_FAILS_TOO)
    ok, failed, outside = mh.verdict(r.returncode, r.stdout)
    assert ok is False and failed == ["test_suite.py::test_code_is_broken"]
    assert [o["test"] for o in outside] == ["test_suite.py::test_live_site_matches"]


def test_an_error_or_a_crash_is_red_even_with_no_failed_lines():
    assert mh.verdict(2, "ERROR test_x.py - ImportError\n")[0] is False                        # collection error
    assert mh.verdict(1, "ERROR test_x.py::test_y - fixture\n" + osx.line("test_x.py::test_z", "a site"))[0] is False
    assert mh.verdict(-9, "")[0] is False                                                       # killed
    assert mh.verdict(0, "5 passed")[0] is True


def test_refresh_records_outside_failures_and_keeps_main_ok(tmp_path):
    state = tmp_path / "m.json"
    out = [{"test": "t.py::test_site", "what": "the portfolio dev site"}]
    res = mh.refresh(state_path=state, head=lambda: "abc1234", run_suite=lambda: (True, [], "1 failed, 9 passed", out))
    assert res["ok"] is True and res["outside"] == out


# ── Health ───────────────────────────────────────────────────────────────────

def test_health_is_yellow_and_names_them_without_saying_merges_are_refused(tmp_path):
    import json
    from datetime import datetime, timezone
    import health_checks as hc
    now = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)
    p = tmp_path / "main-health.json"
    p.write_text(json.dumps({"sha": "5b93e994", "ok": True, "failed": [], "summary": "4 failed, 3000 passed",
                             "checked_at": now.isoformat(),
                             "outside": [{"test": "a::b", "what": "the portfolio dev site"},
                                         {"test": "a::c", "what": "the portfolio dev site"},
                                         {"test": "d::e", "what": "the portfolio repo's captured elements"}]}))
    r = hc.check_main_health(p, now=now)
    assert r["severity"] == "yellow", r
    assert "the portfolio dev site (2)" in r["detail"] and "the portfolio repo's captured elements (1)" in r["detail"]
    assert "refused" not in r["detail"]


# ── the portfolio checks say so ──────────────────────────────────────────────

def _decorators(path: str, name: str) -> list[str]:
    import ast
    tree = ast.parse((ROOT / path).read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    return [ast.unparse(d) for d in fn.decorator_list]


@pytest.mark.parametrize("path,name", [
    ("lib/tests/test_portfolio_parity.py", "test_the_dashboard_preview_of_every_captured_element_matches_the_live_site"),
    ("lib/tests/test_portfolio_elements.py", "test_the_captured_card_is_one_look_in_one_geometry_everywhere_it_appears"),
    ("lib/tests/test_portfolio_elements.py", "test_the_captured_card_equals_the_one_template_file_so_library_and_source_cannot_disagree"),
    ("lib/tests/test_portfolio_layouts.py", "test_the_captured_layouts_record_which_pages_follow_them"),
])
def test_the_checks_of_captured_or_live_portfolio_state_are_marked(path, name):
    assert any(d.startswith("pytest.mark.outside_state(") for d in _decorators(path, name)), (path, name)


def test_the_root_conftest_loads_the_plugin():
    assert '"outside_state"' in (ROOT / "conftest.py").read_text()
