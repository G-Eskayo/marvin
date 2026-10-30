"""marvin#826 step 3: a PR runs the rules plus the tests its change can affect, not all ~7,000. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_affected_tests.py -v

lib/affected_tests.py picks Python test files by what a change touches and what imports it; .github/run-check.sh
skips a whole check (the dashboard's vitest) when no path it covers changed. The proof is on two real past PRs that
went in through the website and turned main red: #767 and #770 each hard-coded the owner's name, which
lib/tests/test_instance.py forbids, so the selection for each must include it. Real temp repos and the real history;
the selection is computed, never mocked.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import affected_tests as at  # noqa: E402

needs_jq = pytest.mark.skipif(not shutil.which("jq"), reason="jq is not installed")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def _write(repo: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    _write(r, {
        "lib/base.py": "X = 1\n",
        "lib/middle.py": "import base\n",
        "lib/top.py": "from middle import thing\n",
        "lib/alone.py": "Y = 2\n",
        "lib/reads_config.py": "PATH = 'config/limits.json'\n",
        "config/limits.json": "{}\n",
        "dashboard/app.js": "export const a = 1\n",
        "lib/tests/test_instance.py": "def test_rule(): pass\n",
        "lib/tests/test_instance_move.py": "def test_rule(): pass\n",
        "lib/tests/test_top.py": "import top\n",
        "lib/tests/test_alone.py": "import alone\n",
        "lib/tests/test_config.py": "import reads_config\n",
        "lib/tests/test_names_js.py": "SRC = 'dashboard/app.js'\n",
        "skills/x/scripts/tests/test_skill.py": "from base import X\n",
        "docs/guide.md": "hi\n",
    })
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "init")
    return r


RULES = {"lib/tests/test_instance.py", "lib/tests/test_instance_move.py"}


def test_a_docs_only_change_runs_just_the_rules(repo):
    assert set(at.select(repo, ["docs/guide.md"])) == RULES


def test_a_module_change_runs_every_test_that_imports_it_however_deep(repo):
    got = set(at.select(repo, ["lib/base.py"]))
    assert got == RULES | {"lib/tests/test_top.py", "skills/x/scripts/tests/test_skill.py"}
    assert "lib/tests/test_alone.py" not in got


def test_a_changed_test_runs_itself(repo):
    assert "lib/tests/test_alone.py" in at.select(repo, ["lib/tests/test_alone.py"])


def test_a_data_file_runs_the_tests_whose_code_names_it(repo):
    assert set(at.select(repo, ["config/limits.json"])) == RULES | {"lib/tests/test_config.py"}
    assert "lib/tests/test_names_js.py" in at.select(repo, ["dashboard/app.js"])


def test_a_name_many_files_share_only_counts_beside_its_folder(repo):
    _write(repo, {"docs/design/a/index.html": "x\n", "docs/design/b/index.html": "y\n",
                  "lib/serves.py": "PAGE = 'index.html'\n", "lib/tests/test_serves.py": "import serves\n",
                  "lib/design_a.py": "PAGE = Path('design') / 'a' / 'index.html'\n",
                  "lib/tests/test_design_a.py": "import design_a\n"})
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "pages")
    got = set(at.select(repo, ["docs/design/a/index.html"]))
    assert "lib/tests/test_design_a.py" in got and "lib/tests/test_serves.py" not in got


def test_a_deleted_module_still_runs_the_tests_that_import_it(repo):
    (repo / "lib" / "alone.py").unlink()
    assert "lib/tests/test_alone.py" in at.select(repo, ["lib/alone.py"])


def test_a_folder_conftest_runs_every_test_under_that_folder(repo):
    _write(repo, {"skills/x/scripts/tests/conftest.py": "import pytest\n"})
    got = set(at.select(repo, ["lib/tests/conftest.py"]))
    assert {"lib/tests/test_alone.py", "lib/tests/test_top.py", "lib/tests/test_config.py"} <= got
    assert "skills/x/scripts/tests/test_skill.py" not in got


@pytest.mark.parametrize("path", ["conftest.py", "pytest.ini", "requirements-ci.txt",
                                  "lib/affected_tests.py", ".github/required-checks.json", ".github/run-check.sh"])
def test_a_change_to_how_tests_run_runs_everything(repo, path):
    assert at.select(repo, [path]) is None


def test_selection_never_returns_a_file_pytest_would_not_collect(repo):
    _write(repo, {"lib/tests/helpers.py": "import base\n"})
    assert all(Path(p).name.startswith("test_") for p in at.select(repo, ["lib/base.py"]))


def test_changed_paths_are_what_the_branch_did_since_it_left_its_base(repo):
    base = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "-q", "-b", "pr")
    _write(repo, {"lib/alone.py": "Y = 3\n"})
    _git(repo, "commit", "-qam", "pr")
    _git(repo, "checkout", "-q", "main")
    _write(repo, {"lib/base.py": "X = 9\n"})  # main moved on: not the PR's change
    _git(repo, "commit", "-qam", "main")
    _git(repo, "checkout", "-q", "pr")
    assert at.changed_paths(repo, "main") == ["lib/alone.py"]
    assert at.changed_paths(repo, base) == ["lib/alone.py"]


# ── the proof: real past PRs that turned main red ───────────────────────────

PAST = {767: "9e1da3c597cd1bb1463531badba1b2a96af2d4ca", 770: "320c0a7f09cf21e3733c3558d54a1aa542d21c36"}


def _pr_paths(merge: str) -> list[str]:
    try:
        return _git(ROOT, "diff", "--name-only", f"{merge}^1", merge).split()
    except subprocess.CalledProcessError:
        pytest.skip(f"{merge[:8]} is not in this clone's history (a shallow clone)")


@pytest.mark.parametrize("pr", sorted(PAST))
def test_the_selection_for_767_and_770_includes_the_rule_they_broke(pr):
    picked = at.select(ROOT, _pr_paths(PAST[pr]))
    assert picked is not None, "these PRs touched no test machinery: they must get a selection, not the full suite"
    assert "lib/tests/test_instance.py" in picked


def test_770_also_runs_the_tests_of_what_it_changed_and_of_what_imports_that():
    picked = set(at.select(ROOT, _pr_paths(PAST[770])))
    # Its own tests, and tests that never named the changed files but import a module that imports them.
    assert {"lib/tests/test_disk_triggers.py", "lib/tests/test_download_cache.py", "lib/tests/test_health_checks.py",
            "lib/tests/test_helper_tab.py"} <= picked
    assert len(picked) < len(at.all_tests(ROOT)), "a selection that is the whole suite selects nothing"


# ── how the Python check runs it ────────────────────────────────────────────

def test_without_a_base_the_whole_suite_runs(repo):
    argv, env = at.plan(repo, None, parallel=[])
    assert argv[-3:] == ["-m", "pytest", "-q"] and "MARVIN_SELECTED_TESTS" not in env


def test_with_a_base_pytest_is_told_which_files_to_collect(repo, tmp_path):
    base = _git(repo, "rev-parse", "HEAD").strip()
    _write(repo, {"lib/alone.py": "Y = 3\n"})
    _git(repo, "commit", "-qam", "change")
    argv, env = at.plan(repo, base, parallel=["-n", "auto"])
    assert argv[-5:] == ["-m", "pytest", "-q", "-n", "auto"]
    assert set(Path(env["MARVIN_SELECTED_TESTS"]).read_text().split()) == RULES | {"lib/tests/test_alone.py"}


def test_parallel_only_where_pytest_xdist_is_installed():
    assert at.parallel_args(have_xdist=True) == ["-n", "auto"]
    assert at.parallel_args(have_xdist=False) == []


def test_the_conftest_collects_only_the_selected_files():
    sel = ROOT / "lib" / "tests" / ".selected-for-test.txt"
    try:
        sel.write_text("lib/tests/test_required_checks.py\n")
        # A folder, as a real run collects (pytest never asks the hook about files named on its command line).
        out = subprocess.run([sys.executable, "-m", "pytest", "--co", "-q", "-p", "no:cacheprovider", "lib/tests"], cwd=ROOT,
                             capture_output=True, text=True, env={**os.environ, "MARVIN_SELECTED_TESTS": str(sel)}).stdout
    finally:
        sel.unlink(missing_ok=True)
    assert "test_required_checks.py::" in out and "test_rule_checks.py::" not in out


# ── the runner skips a check no changed path touches ────────────────────────

def _checks_repo(tmp_path: Path) -> tuple[Path, str]:
    r = tmp_path / "r"
    (r / ".github").mkdir(parents=True)
    shutil.copy(ROOT / ".github" / "run-check.sh", r / ".github" / "run-check.sh")
    (r / ".github" / "required-checks.json").write_text(json.dumps({"checks": [
        {"id": "web", "name": "Web", "paths": ["web/*"], "command": ["echo", "ran web"]},
        {"id": "all", "name": "All", "command": ["echo", "ran all"]},
    ]}))
    _write(r, {"web/a.js": "1\n", "docs/a.md": "x\n"})
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "init")
    return r, _git(r, "rev-parse", "HEAD").strip()


def _run(r: Path, *args: str, base: str | None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "MARVIN_BASE"}
    if base:
        env["MARVIN_BASE"] = base
    return subprocess.run(["bash", ".github/run-check.sh", *args], cwd=r, capture_output=True, text=True, env=env)


@needs_jq
def test_a_check_no_changed_path_touches_passes_without_running(tmp_path):
    r, base = _checks_repo(tmp_path)
    _write(r, {"docs/a.md": "y\n"})
    _git(r, "commit", "-qam", "docs")
    web = _run(r, "web", base=base)
    assert web.returncode == 0 and "ran web" not in web.stdout and "not affected" in web.stdout
    assert "ran all" in _run(r, "all", base=base).stdout  # no paths: every change affects it
    assert _run(r, "web", "--affected", base=base).stdout.strip() == "false"


@needs_jq
def test_a_check_runs_when_its_paths_change_and_always_without_a_base(tmp_path):
    r, base = _checks_repo(tmp_path)
    _write(r, {"web/a.js": "2\n"})
    _git(r, "commit", "-qam", "web")
    assert "ran web" in _run(r, "web", base=base).stdout
    assert _run(r, "web", "--affected", base=base).stdout.strip() == "true"
    _git(r, "reset", "-q", "--hard", base)
    assert "ran web" in _run(r, "web", base=None).stdout  # main, after a merge: everything runs


@needs_jq
def test_a_change_to_the_checks_themselves_runs_every_check(tmp_path):
    r, base = _checks_repo(tmp_path)
    _write(r, {".github/run-check.sh": (r / ".github" / "run-check.sh").read_text() + "\n# touched\n"})
    _git(r, "commit", "-qam", "runner")
    assert "ran web" in _run(r, "web", base=base).stdout


@needs_jq
def test_a_base_the_clone_cannot_find_runs_the_check_instead_of_skipping_it(tmp_path):
    r, _ = _checks_repo(tmp_path)
    out = _run(r, "web", base="no-such-ref")
    assert "ran web" in out.stdout and "cannot tell" in out.stderr


def test_marvins_dashboard_check_covers_the_dashboard_and_python_runs_the_selector():
    import required_checks
    by_id = {c["id"]: c for c in required_checks.load(ROOT)}
    assert by_id["dashboard"]["paths"] == ["dashboard/*"]
    assert by_id["python"]["command"] == ["python", "lib/affected_tests.py"]
