"""tool_requirements.py — tests say what they need from the machine; a missing tool is infra, not a red test (#826).

The same commit passed on one Mac and failed on the other (ripgrep on the MacBook, not on the Mini), and the gate
read the Mini's failures as main being red. A pytest plugin, loaded by the repo's root conftest.py:

    @pytest.mark.requires_tool("rg")            a command the test runs; looked up on PATH
    tool_requirements.require_path(p, why)      a file outside the repo a test module needs (module level is fine)

A missing one skips the test with "INFRA: this machine is missing <x>", and the run ends with one line per missing
thing and how many tests it stopped, so the machine gets fixed instead of the test being blamed. Under
$MARVIN_REQUIRE_TOOLS=1 (CI, which installs every tool) a missing TOOL fails the test instead, so the required list
can't quietly shrink; a missing path still skips there (the owner's ~/.claude can't exist in CI).

A test that only makes sense on a Mac says so (marvin#1117: GitHub runs the suite on Linux, the Macs and the Mini's
merge gate run everything):

    @pytest.mark.macos_only("launchctl loads the plist")     one test (or a class)
    tool_requirements.require_macos("why")                    a whole module (module level is fine)

Off macOS it skips with "needs macOS: <why> (the Mac gate runs it)", ahead of any requires_tool check, so a Mac-only
tool isn't read as missing under $MARVIN_REQUIRE_TOOLS=1. On macOS it never skips: this is the one place Mac-only
tests are skipped (a test in test_tool_requirements.py refuses hand-rolled platform skips), so the gate runs them all.
"""
from __future__ import annotations

import os
import shutil
import sys
from collections import Counter

import pytest

_missing: Counter = Counter()

# What decides "is this a Mac". A test suite may pin it (test_tool_requirements does, from its own conftest); there is
# deliberately no environment knob, so nothing can make a Mac skip its own Mac-only tests.
PLATFORM = sys.platform
_MAC_PREFIX = "needs macOS: "


def missing(tools, path: str | None = None) -> list[str]:
    return [t for t in tools if not shutil.which(t, path=path)]


def _infra(what: str) -> str:
    return f"INFRA: this machine is missing {what}"


def require_path(path, why: str = "") -> None:
    """Skip (as infra) when a file or folder outside the repo isn't on this machine."""
    if not os.path.exists(os.path.expanduser(str(path))):
        home = os.path.expanduser("~")
        shown = "~" + str(path)[len(home):] if str(path).startswith(home + os.sep) else str(path)  # a test HOME too
        _missing[shown] += 1
        pytest.skip(_infra(shown) + (f" ({why})" if why else ""), allow_module_level=True)


def _on_mac() -> bool:
    return PLATFORM == "darwin"


def _mac_reason(why: str) -> str:
    return f"{_MAC_PREFIX}{why} (the Mac gate runs it)"


def require_macos(why: str) -> None:
    """Skip the whole module off macOS; never on a Mac."""
    if not str(why or "").strip():
        raise pytest.UsageError("require_macos needs a reason: what in the module needs macOS")
    if not _on_mac():
        pytest.skip(_mac_reason(why), allow_module_level=True)


def pytest_configure(config):
    config.addinivalue_line("markers", "requires_tool(*names): commands the test runs; missing ones are infra (#826)")
    config.addinivalue_line("markers", "macos_only(why): the test needs macOS; skipped elsewhere, never on a Mac (#1117)")


def pytest_collection_modifyitems(config, items):
    for item in items:
        for m in item.iter_markers("macos_only"):
            if not (m.args and str(m.args[0]).strip()):
                raise pytest.UsageError(f"macos_only needs a reason (what needs macOS): {item.nodeid}")


@pytest.hookimpl(tryfirst=True)  # ahead of skipif and requires_tool, so the reason given is "needs macOS"
def pytest_runtest_setup(item):
    mac = next(item.iter_markers("macos_only"), None)
    if mac is not None and not _on_mac():
        pytest.skip(_mac_reason(mac.args[0]))
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
    mac = 0
    for rep in terminalreporter.stats.get("skipped", []):
        reason = rep.longrepr[2] if isinstance(rep.longrepr, tuple) else str(rep.longrepr or "")
        mac += _MAC_PREFIX in reason
    for what, n in sorted((counts or _missing).items()):
        terminalreporter.write_line(f"{_infra(what)} ({n} test{'s' if n != 1 else ''} did not run)", yellow=True)
    if mac:
        terminalreporter.write_line(f"{_MAC_PREFIX}{mac} test{'s' if mac != 1 else ''} did not run here; "
                                    "the Mac gate runs them", yellow=True)
