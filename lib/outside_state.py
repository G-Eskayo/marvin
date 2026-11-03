"""outside_state.py: tests that check state outside this repo's code say what they check (marvin#1047).

Some tests compare against something marvin's code doesn't own: data captured from a running local service and kept in
another repo's working copy, or that service itself (the portfolio dev site). When that state moves, for example when
another session deploys a redesign branch to the dev site, the test fails while main's code is fine. At 5b93e994 four
such failures made the Mac mini's main-health red and held every approved PR, while GitHub's CI on main was green.

    @pytest.mark.outside_state("the portfolio dev site")

A marked test runs and fails as usual (nothing is hidden). Each failure also ends the run with one line:

    OUTSIDE STATE FAILED <test id> (<what>)

lib/main_health.py reads these lines. When they are the only failures, main is ok, they are recorded under `outside`,
and Health shows them yellow by name. The merge gate already leaves these files out (MARVIN_MERGE_GATE, readable_guard).
Same class as tool_requirements (#826): the machine's state is not main's code.
"""
from __future__ import annotations

import re

import pytest

PREFIX = "OUTSIDE STATE FAILED"
_LINE = re.compile(rf"^{PREFIX} (\S+) \((.*)\)$", re.M)
_KEY = "outside_state"


def line(test_id: str, what: str) -> str:
    return f"{PREFIX} {test_id} ({what})\n"


def parse(output: str) -> list[dict]:
    """[{test, what}] for every outside-state failure a run printed, in order, each test once."""
    seen, out = set(), []
    for m in _LINE.finditer(output or ""):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            out.append({"test": m.group(1), "what": m.group(2)})
    return out


def pytest_configure(config):
    config.addinivalue_line("markers", "outside_state(what): checks state outside this repo's code (another repo's "
                                       "working copy, a running local service); its failure never makes main red (#1047)")


def pytest_collection_modifyitems(config, items):
    for item in items:
        for m in item.iter_markers(_KEY):
            if not (m.args and str(m.args[0]).strip()):
                raise pytest.UsageError(f"{item.nodeid}: outside_state needs to say what it checks, "
                                        f'e.g. @pytest.mark.outside_state("the portfolio dev site")')
        what = [str(m.args[0]) for m in item.iter_markers(_KEY)]
        if what:
            # user_properties travel with the report, so the controller sees them under pytest-xdist too
            item.user_properties.append((_KEY, "; ".join(what)))


def pytest_terminal_summary(terminalreporter):
    for rep in terminalreporter.stats.get("failed", []):
        what = dict(getattr(rep, "user_properties", []) or []).get(_KEY)
        if what:
            terminalreporter.write(line(rep.nodeid, what))
