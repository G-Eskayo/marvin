"""Repo-wide test isolation.

1. No test touches the real ~/.claude (pipeline review 2026-10-21, F10; lib/real_home_guard.py). Before any test module
   is imported, HOME points at a temp copy of the real home (symlinks to everything except .claude*, which starts
   empty apart from links to read-only inputs: settings, memory, manifest), so module-level ``Path.home()`` constants and every subprocess land there. An audit hook refuses any write
   under the real ~/.claude that still gets through and fails the test that tried, by name.
2. No test reaches real GitHub. A suite run was editing a real ticket's labels (marvin#20) and the merge gate's retests
   on the Mini made about 1,000 real gh calls an hour while PRs were being approved, on the one allowance both Macs and
   the dashboard share (found 2026-10-08). A `gh` that refuses everything comes first on PATH for every test; tests
   that need gh behaviour mock it.
3. Only the selected tests are collected when $MARVIN_SELECTED_TESTS names a file (marvin#826, lib/affected_tests.py):
   a PR runs what its change can affect, and files it can't are never imported.
"""
import atexit
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import real_home_guard  # noqa: E402  (pure: reads no HOME-derived constants)

import pytest  # noqa: E402

# Tests declare the tools they need (@pytest.mark.requires_tool("rg")); a missing one is infra, not a red test (#826).
pytest_plugins = ["tool_requirements"]

REAL_HOME = real_home_guard.real_home()

# The portfolio tests (main-health only) find that repo through the real catalog under ~/.claude; resolve it once,
# before HOME moves, and hand it on through the variable project_catalog already honours. Workers inherit it.
if not os.environ.get("MARVIN_MERGE_GATE") and not os.environ.get("MARVIN_PORTFOLIO_PATH"):
    try:
        _p = subprocess.run([sys.executable, "-c", "import project_catalog as c; print(c.portfolio_repo_path())"],
                            cwd=str(Path(__file__).resolve().parent / "lib"), env={**os.environ, "HOME": str(REAL_HOME)},
                            capture_output=True, text=True, timeout=30).stdout.strip()
        if _p:
            os.environ["MARVIN_PORTFOLIO_PATH"] = _p
    except (OSError, subprocess.SubprocessError):
        pass

TEST_HOME = real_home_guard.make_test_home(REAL_HOME)
os.environ["HOME"] = str(TEST_HOME)
# marvin#845: the memory guard reads this Mac's live pressure before heavy work starts. Pinned to normal so no test
# passes or fails with the machine's memory (the Mini runs the suite while it is busy); test_memory_guard unpins it.
os.environ["MARVIN_MEMORY_PRESSURE_LEVEL"] = "normal"
atexit.register(shutil.rmtree, TEST_HOME, True)  # removes the links, never what they point to
WRITE_GUARD = real_home_guard.install_write_guard(real_home_guard.protected_roots(REAL_HOME),
                                                  resolve_under=(str(TEST_HOME / ".claude"),))


_ROOT = Path(__file__).resolve().parent
_selected: set[str] | None = None


def pytest_ignore_collect(collection_path, config):
    """Only the files lib/affected_tests.py selected for this change, when it selected (marvin#826)."""
    global _selected
    listing = os.environ.get("MARVIN_SELECTED_TESTS")
    name = collection_path.name
    if not listing or collection_path.suffix != ".py" or not (name.startswith("test_") or name.endswith("_test.py")):
        return None
    if _selected is None:
        _selected = {str((_ROOT / p).resolve()) for p in Path(listing).read_text().split()}
    return None if str(collection_path.resolve()) in _selected else True


# marvin#940: one test run at a time on this machine, merges first (lib/test_slot.py). A whole-suite or parallel run
# waits here for the slot before collecting anything and holds it to the end; one file or one test never waits. The
# controller decides once; xdist workers, the tests and anything they start inherit MARVIN_TEST_SLOT and pass through,
# so no test ever queues on the machine's real slot. Inside the merge gate the slot is already held.
_TEST_SLOT = None


def pytest_configure(config):
    global _TEST_SLOT
    import test_slot
    if hasattr(config, "workerinput"):
        return
    if os.environ.get(test_slot.HELD_ENV):
        os.environ[test_slot.DIR_ENV] = str(TEST_HOME / ".cache" / "marvin" / "test-slot")
        return
    n = getattr(config.option, "numprocesses", None)
    if test_slot.is_heavy(list(config.args), n not in (None, 0), cwd=config.invocation_params.dir):
        _TEST_SLOT = test_slot.slot("pytest " + " ".join(config.args)[:60],
                                    say=lambda t: print(f"test-slot: {t}", file=sys.stderr, flush=True))
        _TEST_SLOT.__enter__()
    else:
        os.environ[test_slot.HELD_ENV] = "pytest (small run, not queued)"
    # From here on the tests see a slot of their own: no test waits on, or reads, the machine's real merges and runs.
    os.environ[test_slot.DIR_ENV] = str(TEST_HOME / ".cache" / "marvin" / "test-slot")


def pytest_unconfigure(config):
    global _TEST_SLOT
    if _TEST_SLOT is not None:
        _TEST_SLOT.__exit__(None, None, None)
        _TEST_SLOT = None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    hits = [v for v in WRITE_GUARD.violations if v[0] == item.nodeid]
    if not hits:
        return
    rep = outcome.get_result()
    WRITE_GUARD.violations[:] = [v for v in WRITE_GUARD.violations if v[0] != item.nodeid]
    if rep.passed or rep.skipped:
        rep.outcome = "failed"
        rep.longrepr = ("tests must not write the real ~/.claude (lib/real_home_guard.py): "
                        + "; ".join(f"{e} {p}" for _, e, p in hits[:5])
                        + ". Use tmp_path, or monkeypatch the module's path constant.")


def pytest_terminal_summary(terminalreporter):
    stray = [v for v in WRITE_GUARD.violations if v[0] == "(outside a test)"]
    if stray:
        terminalreporter.write_line(f"refused {len(stray)} write(s) to the real ~/.claude outside any test: "
                                    + "; ".join(f"{e} {p}" for _, e, p in stray[:5]), red=True)


@pytest.fixture(autouse=True)
def _no_real_github(tmp_path_factory, monkeypatch):
    bin_dir = tmp_path_factory.mktemp("no-gh")
    fake = bin_dir / "gh"
    fake.write_text("#!/bin/sh\necho 'gh is disabled in tests' >&2\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")


@pytest.fixture(autouse=True)
def _no_real_claude(tmp_path_factory, monkeypatch):
    """No test starts Claude Code (#826): code that only looks the binary up finds this one, on a runner without
    Claude Code too, and anything that runs it gets a refusal instead of spending tokens. Its own name, so the
    folders' conftests that redefine _no_real_github don't drop it."""
    no_claude = tmp_path_factory.mktemp("no-claude")
    (no_claude / "claude").write_text("#!/bin/sh\necho 'claude is disabled in tests' >&2\nexit 1\n")
    (no_claude / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{no_claude}{os.pathsep}{os.environ.get('PATH', '')}")
