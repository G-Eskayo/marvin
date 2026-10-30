"""Repo-wide test isolation.

1. No test touches the real ~/.claude (pipeline review 2026-10-21, F10; lib/real_home_guard.py). Before any test module
   is imported, HOME points at a temp copy of the real home (symlinks to everything except .claude*, which starts
   empty apart from links to read-only inputs: settings, memory, manifest), so module-level ``Path.home()`` constants and every subprocess land there. An audit hook refuses any write
   under the real ~/.claude that still gets through and fails the test that tried, by name.
2. No test reaches real GitHub. A suite run was editing a real ticket's labels (marvin#20) and the merge gate's retests
   on the Mini made about 1,000 real gh calls an hour while PRs were being approved, on the one allowance both Macs and
   the dashboard share (found 2026-10-08). A `gh` that refuses everything comes first on PATH for every test; tests
   that need gh behaviour mock it.
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
