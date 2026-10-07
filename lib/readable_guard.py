"""Can this process actually read a file, without risking a hang?

Some tests read another repo on disk (the portfolio repo). On the mac-mini that repo sits in ~/Documents,
an iCloud File Provider folder: a launchd process (the merge gate, the pipeline) sees the files exist but
open() blocks forever. Checking `exists()` isn't enough, and checking with a plain open() is the hang
itself, so the read is tried in a child process that is killed after a time limit (found 2026-10-06:
pytest hung at collection for hours and every merge queued behind it).
"""
from __future__ import annotations
import re
import subprocess
import sys
from pathlib import Path

PORTFOLIO_REPO = Path.home() / "Documents" / "Projects" / "portfolio-website-updater"
# The file the real-repo tests read first; readable means the repo is usable from this process.
PORTFOLIO_PROBE = PORTFOLIO_REPO / "templates" / "templates.json"

_PORTFOLIO_IMPORT = re.compile(r"^\s*(?:import|from)\s+portfolio_\w+", re.M)
_PORTFOLIO_PATH = re.compile(r'"Projects"\s*/\s*"portfolio-website-updater"')


def readable_within(path: Path, seconds: float = 5) -> bool:
    try:
        subprocess.run([sys.executable, "-c", "import sys; open(sys.argv[1], 'rb').read(1)", str(path)],
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=seconds, check=True)
        return True
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError):
        return False


def reads_portfolio_repo(source: str) -> bool:
    """A test file that imports a portfolio_* module or builds the repo's path. Naming the repo (as sample
    data) doesn't count."""
    return bool(_PORTFOLIO_IMPORT.search(source) or _PORTFOLIO_PATH.search(source))


def portfolio_repo_blocked(seconds: float = 5) -> bool:
    """True when the repo is on this machine but can't be read from this process. Missing is not
    blocked: those tests already skip themselves when the repo isn't there."""
    return PORTFOLIO_PROBE.exists() and not readable_within(PORTFOLIO_PROBE, seconds)


def exclude_portfolio_tests(environ=None, blocked: bool | None = None) -> bool:
    """Leave the tests that read the portfolio repo out of this run? Yes when the repo cannot be read from this process
    (the iCloud hang), and ALSO always inside the merge gate (MARVIN_MERGE_GATE=1): a PR to marvin must not be judged on
    another repo's files. Those tests still run everywhere else, including the main-branch health check."""
    import os
    environ = os.environ if environ is None else environ
    if environ.get("MARVIN_MERGE_GATE") == "1":
        return True
    return portfolio_repo_blocked() if blocked is None else blocked
