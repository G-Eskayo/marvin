"""marvin#762: Health shows "Merge service reachable" and which machine will merge right now.

On 2026-10-29 the Mini was unreachable and seven approvals failed before anyone knew. The dashboard now fails over to
this Mac's own webhook; Health says which one will take the next approval, and how many saved approvals are waiting.
The probe is a real HTTP server and a real closed port: "reachable" is what the network says, not a mocked flag.
HOME is the suite's temp home (conftest.py).
"""
from __future__ import annotations

import http.server
import json
import socket
import sys
import threading
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import health_checks as hc  # noqa: E402


@pytest.fixture
def webhook():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(404)  # any answer means the service is up (an older webhook has no such route)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


MINI = {"id": "mac-mini-1", "label": "Mac mini", "host": "127.0.0.1"}
BOOK = {"id": "macbook-pro-1", "label": "MacBook Pro", "host": "127.0.0.1", "here": True}


def test_reachable_probe_tells_up_from_down(webhook):
    assert hc.merge_service_reachable("127.0.0.1", webhook, timeout=1) is True
    assert hc.merge_service_reachable("127.0.0.1", closed_port(), timeout=1) is False


def test_mini_up_is_green_and_names_it(webhook):
    r = hc.merge_service_result([dict(MINI, port=webhook), dict(BOOK, port=closed_port())], waiting=0)
    assert r["id"] == "merge:service" and r["label"] == "Merge service reachable"
    assert r["severity"] == "green"
    assert r["detail"] == "The Mac mini will merge approvals."
    assert r["value"] == "mac-mini-1"


def test_mini_down_this_mac_up_is_yellow_and_says_who_merges(webhook):
    r = hc.merge_service_result([dict(MINI, port=closed_port()), dict(BOOK, port=webhook)], waiting=0)
    assert r["severity"] == "yellow"
    assert r["detail"] == "The Mac mini is offline; this MacBook Pro will merge approvals instead."
    assert r["value"] == "macbook-pro-1"


def test_both_down_is_red_and_counts_saved_approvals():
    r = hc.merge_service_result([dict(MINI, port=closed_port()), dict(BOOK, port=closed_port())], waiting=3)
    assert r["severity"] == "red"
    assert r["detail"] == "No Mac can merge: the Mac mini is offline and this MacBook Pro's merge service isn't running. 3 approvals saved, they merge by themselves when one comes back."
    assert r["value"] is None


def test_waiting_approvals_with_a_machine_up_still_shows_them(webhook):
    r = hc.merge_service_result([dict(MINI, port=webhook)], waiting=1)
    assert r["severity"] == "yellow"
    assert "1 approval saved" in r["detail"]


def test_on_the_mini_itself_only_itself_is_checked(webhook):
    r = hc.merge_service_result([dict(MINI, port=webhook, here=True)], waiting=0)
    assert r["detail"] == "This Mac mini will merge approvals."


def test_waiting_count_reads_the_ledger(tmp_path):
    f = tmp_path / "approvals.json"
    assert hc.waiting_approvals(f) == 0
    f.write_text("{nope")
    assert hc.waiting_approvals(f) == 0
    f.write_text(json.dumps({"approvals": [{"url": "a", "outcome": "queued"}, {"url": "b", "outcome": "merged"}, {"url": "c", "outcome": "queued"}]}))
    assert hc.waiting_approvals(f) == 2


def test_machines_follow_the_dashboard_order(monkeypatch):
    registry = {
        "mac-mini-1": {"kind": "desktop", "tailscale_hostname": "gils-mac-mini"},
        "macbook-pro-1": {"kind": "laptop", "tailscale_hostname": "some-macbook"},
    }
    monkeypatch.setattr(hc.machine_profile, "_load_registry", lambda: registry)
    monkeypatch.setattr(hc.machine_profile, "registry_id", lambda: "macbook-pro-1")
    assert [(m["id"], m["host"], bool(m.get("here"))) for m in hc.merge_machines()] == [
        ("mac-mini-1", "gils-mac-mini", False), ("macbook-pro-1", "localhost", True)]
    monkeypatch.setattr(hc.machine_profile, "registry_id", lambda: "mac-mini-1")
    assert [(m["id"], m["host"], bool(m.get("here"))) for m in hc.merge_machines()] == [("mac-mini-1", "localhost", True)]


def test_registered_in_the_sweep():
    assert "merge:service" in [c[0] for c in hc.default_checks()]


def test_waiting_count_includes_interrupted_ones_the_dashboard_will_retry(tmp_path):
    # Same rule as approval_ledger.js isWaiting (owner decision on #766): interrupted on a known Mac, sent fewer than 3 times.
    f = tmp_path / "approvals.json"
    f.write_text(json.dumps({"approvals": [
        {"url": "a", "outcome": "interrupted", "machine": "mac-mini-1", "attempts": 1},
        {"url": "b", "outcome": "interrupted", "machine": "mac-mini-1", "attempts": 3},
        {"url": "c", "outcome": "interrupted", "machine": None, "attempts": 1},
        {"url": "d", "outcome": "queued"},
    ]}))
    assert hc.waiting_approvals(f) == 2
