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

import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

import pytest

_missing: Counter = Counter()

# Accumulators for pytest collection (tool requirements catalog)
_declared_tools: set[str] = set()
_declared_paths: set[str] = set()

# What decides "is this a Mac". A test suite may pin it (test_tool_requirements does, from its own conftest); there is
# deliberately no environment knob, so nothing can make a Mac skip its own Mac-only tests.
PLATFORM = sys.platform
_MAC_PREFIX = "needs macOS: "


def missing(tools, path: str | None = None) -> list[str]:
    return [t for t in tools if not shutil.which(t, path=path)]


def _infra(what: str) -> str:
    return f"INFRA: this machine is missing {what}"


def require_path(path, why: str = "") -> None:
    """Skip (as infra) when a file or folder outside the repo isn't on this machine.

    Branch: when MARVIN_CATALOG_TOOLS=1, record the path instead of skipping."""
    path_str = str(path)
    if os.getenv("MARVIN_CATALOG_TOOLS") == "1":
        _declared_paths.add(os.path.expanduser(path_str))
        return
    if not os.path.exists(os.path.expanduser(path_str)):
        home = os.path.expanduser("~")
        shown = "~" + path_str[len(home):] if path_str.startswith(home + os.sep) else path_str  # a test HOME too
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
        # Record all requires_tool markers from collected tests
        for m in item.iter_markers("requires_tool"):
            if m.args:
                _declared_tools.update(m.args)


def pytest_collection_finish(session):
    """After collection, print the accumulated catalog if MARVIN_CATALOG_TOOLS=1."""
    if os.getenv("MARVIN_CATALOG_TOOLS") != "1":
        return

    catalog = {
        "tools": sorted(_declared_tools),
        "paths": sorted(_declared_paths),
    }
    # Print one JSON line for the parent process to parse
    print(json.dumps(catalog))


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


# ─── Tool requirements catalog and health checking ─────────────────────────

class ToolHealth(NamedTuple):
    """Result of a tool or path health check."""
    available: dict[str, bool]  # tool/path name -> True if found
    unavailable: list[str]       # list of missing tools/paths


def health(test_root: Path | None = None) -> ToolHealth:
    """Check that all tools and paths declared by tests in this repo are available on this machine.

    Args:
        test_root: directory to glob for test files (default: current directory's tests/)

    Returns:
        ToolHealth with available dict and unavailable list
    """
    if test_root is None:
        test_root = Path.cwd() / "tests"

    if not test_root.exists():
        return ToolHealth(available={}, unavailable=[])

    # Collect test files explicitly (not a bare directory)
    test_files = list(test_root.glob("test_*.py"))

    if not test_files:
        return ToolHealth(available={}, unavailable=[])

    # Run pytest collection to gather the catalog
    env = {**os.environ, "MARVIN_CATALOG_TOOLS": "1"}
    env.pop("MARVIN_SELECTED_TESTS", None)  # Explicitly unset

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        *[str(f) for f in test_files],
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
    except subprocess.TimeoutExpired:
        return ToolHealth(available={}, unavailable=["(collection timed out)"])
    except Exception as exc:
        return ToolHealth(available={}, unavailable=[f"(collection failed: {exc})"])

    # Parse the JSON catalog line from stderr or stdout
    catalog = {"tools": [], "paths": []}
    for line in (result.stderr + result.stdout).split("\n"):
        line = line.strip()
        if line.startswith("{"):
            try:
                catalog = json.loads(line)
                break
            except json.JSONDecodeError:
                pass

    # Check each tool and path
    available = {}
    unavailable = []

    for tool in catalog.get("tools", []):
        if shutil.which(tool):
            available[tool] = True
        else:
            available[tool] = False
            unavailable.append(tool)

    for path_str in catalog.get("paths", []):
        expanded = os.path.expanduser(path_str)
        if os.path.exists(expanded):
            available[path_str] = True
        else:
            available[path_str] = False
            unavailable.append(path_str)

    return ToolHealth(available=available, unavailable=unavailable)


def main():
    """CLI entrypoint: `python tool_requirements.py health`"""
    if len(sys.argv) > 1 and sys.argv[1] == "health":
        result = health()
        output = {
            "available": result.available,
            "unavailable": result.unavailable,
        }
        print(json.dumps(output, indent=2))
        return 0 if not result.unavailable else 1
    else:
        print("Usage: python tool_requirements.py health")
        return 1


if __name__ == "__main__":
    sys.exit(main())
