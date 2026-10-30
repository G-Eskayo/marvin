"""tool_requirements.py — tests say what they need from the machine; a missing tool is infra, not a red test (#826).

The same commit passed on one Mac and failed on the other (ripgrep on the MacBook, not on the Mini), and the gate
read the Mini's failures as main being red. A pytest plugin, loaded by the repo's root conftest.py:

    @pytest.mark.requires_tool("rg")            a command the test runs; looked up on PATH
    tool_requirements.require_path(p, why)      a file outside the repo a test module needs (module level is fine)

A missing one skips the test with "INFRA: this machine is missing <x>", and the run ends with one line per missing
thing and how many tests it stopped, so the machine gets fixed instead of the test being blamed. Under
$MARVIN_REQUIRE_TOOLS=1 (CI, which installs every tool) a missing TOOL fails the test instead, so the required list
can't quietly shrink; a missing path still skips there (the owner's ~/.claude can't exist in CI).
"""
from __future__ import annotations

import os
import shutil
from collections import Counter

import pytest

_missing: Counter = Counter()


def missing(tools, path: str | None = None) -> list[str]:
    return [t for t in tools if not shutil.which(t, path=path)]


def _infra(what: str) -> str:
    return f"INFRA: this machine is missing {what}"


def require_path(path, why: str = "") -> None:
    """Skip (as infra) when a file or folder outside the repo isn't on this machine."""
    if not os.path.exists(os.path.expanduser(str(path))):
        _missing[str(path)] += 1
        pytest.skip(_infra(str(path)) + (f" ({why})" if why else ""), allow_module_level=True)


def pytest_configure(config):
    config.addinivalue_line("markers", "requires_tool(*names): commands the test runs; missing ones are infra (#826)")


def pytest_runtest_setup(item):
    names = [n for m in item.iter_markers("requires_tool") for n in m.args]
    gone = missing(names)
    if not gone:
        return
    for t in gone:
        _missing[t] += 1
    message = _infra(", ".join(gone))
    if os.environ.get("MARVIN_REQUIRE_TOOLS") == "1":
        pytest.fail(f"{message}, and this run requires every tool (MARVIN_REQUIRE_TOOLS=1): install it", pytrace=False)
    pytest.skip(message)


def pytest_terminal_summary(terminalreporter):
    # Counted from the skip reports, which reach the controller under pytest-xdist; a worker's own counter doesn't.
    counts: Counter = Counter()
    prefix = _infra("")
    for rep in terminalreporter.stats.get("skipped", []):
        reason = rep.longrepr[2] if isinstance(rep.longrepr, tuple) else str(rep.longrepr or "")
        if prefix in reason:
            what = reason.split(prefix, 1)[1].split(" (")[0]
            for t in what.split(", "):
                counts[t] += 1
    for what, n in sorted((counts or _missing).items()):
        terminalreporter.write_line(f"{_infra(what)} ({n} test{'s' if n != 1 else ''} did not run)", yellow=True)
