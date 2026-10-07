"""running_tickets: which tickets are actually being worked on right now, from each machine's process table.

A claim label is not that: it stays on a ticket until its PR merges, so the tickets waiting in review looked "running"
(found 2026-10-07, when 7 claimed tickets made the scan believe parallel dispatch was already full)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import running_tickets as rt  # noqa: E402

PS = """/usr/bin/some other process
/opt/homebrew/Python.app/Contents/MacOS/Python /Users/g/.agents/lib/run_ticket.py 193
/opt/homebrew/Python.app/Contents/MacOS/Python /Users/g/.agents/lib/run_ticket.py G-Eskayo/clarity-captions#48
grep run_ticket.py
/Users/g/.agents/venv/bin/python /Users/g/.agents/lib/run_ticket.py 193
"""


def test_parses_marvin_and_other_project_tickets_and_ignores_the_rest():
    assert rt.parse(PS, "G-Eskayo/marvin") == [("G-Eskayo/marvin", 193), ("G-Eskayo/clarity-captions", 48)]   # one ticket, one row


def test_nothing_running_is_an_empty_list():
    assert rt.parse("", "o/m") == []


def test_all_running_tags_each_ticket_with_its_machine():
    got = rt.all_running(
        machines={"mac-mini-1": None, "macbook-pro-1": "mbp-host"},
        local_ps=lambda: "x run_ticket.py 193\n",
        remote_ps=lambda host: "x run_ticket.py o/r#7\n",
        marvin="G-Eskayo/marvin")
    assert got == [{"machine": "mac-mini-1", "repo": "G-Eskayo/marvin", "number": 193},
                   {"machine": "macbook-pro-1", "repo": "o/r", "number": 7}]


def test_an_unreachable_machine_is_skipped_not_guessed():
    def remote(host):
        raise OSError("timed out")
    got = rt.all_running({"mac-mini-1": None, "macbook-pro-1": "h"}, lambda: "x run_ticket.py 5\n", remote, "G-Eskayo/marvin")
    assert [r["machine"] for r in got] == ["mac-mini-1"]
