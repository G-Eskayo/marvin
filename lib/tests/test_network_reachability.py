"""Tests for network_reachability.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_network_reachability.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import network_reachability as nr  # noqa: E402


# ── current_network_id ──────────────────────────────────────────────────────

def test_current_network_id_prefers_gateway_mac(monkeypatch):
    monkeypatch.setattr(nr, "_default_gateway", lambda: "10.54.24.1")
    monkeypatch.setattr(nr, "_arp_mac", lambda ip: "b4:0c:25:e2:80:19")
    assert nr.current_network_id() == "b4:0c:25:e2:80:19"


def test_current_network_id_falls_back_to_gateway_ip_when_no_arp_entry(monkeypatch):
    monkeypatch.setattr(nr, "_default_gateway", lambda: "10.54.24.1")
    monkeypatch.setattr(nr, "_arp_mac", lambda ip: None)
    assert nr.current_network_id() == "10.54.24.1"


def test_current_network_id_is_unknown_when_offline(monkeypatch):
    monkeypatch.setattr(nr, "_default_gateway", lambda: None)
    assert nr.current_network_id() == "unknown"


# ── _arp_mac parsing (real macOS output shapes) ─────────────────────────────

class _FakeCompleted:
    def __init__(self, stdout):
        self.stdout = stdout


def test_arp_mac_parses_non_zero_padded_octets(monkeypatch):
    # Real macOS arp output does NOT zero-pad single-digit octets -- this
    # exact line is what broke the original 17-char-fixed regex live.
    monkeypatch.setattr(
        nr.subprocess, "run",
        lambda *a, **k: _FakeCompleted("? (10.54.24.1) at b4:c:25:e2:80:19 on en0 ifscope [ethernet]\n"),
    )
    assert nr._arp_mac("10.54.24.1") == "b4:c:25:e2:80:19"


def test_arp_mac_parses_zero_padded_octets(monkeypatch):
    monkeypatch.setattr(
        nr.subprocess, "run",
        lambda *a, **k: _FakeCompleted("? (10.54.24.1) at b4:0c:25:e2:80:19 on en0 ifscope [ethernet]\n"),
    )
    assert nr._arp_mac("10.54.24.1") == "b4:0c:25:e2:80:19"


def test_arp_mac_returns_none_when_no_entry(monkeypatch):
    monkeypatch.setattr(
        nr.subprocess, "run",
        lambda *a, **k: _FakeCompleted("? (10.54.24.1) at (incomplete) on en0 ifscope [ethernet]\n"),
    )
    assert nr._arp_mac("10.54.24.1") is None


# ── record / known_status round-trip ────────────────────────────────────────

def test_known_status_is_none_before_anything_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(nr, "STORE_PATH", tmp_path / "network-reachability.json")
    assert nr.known_status("huggingface.co", network_id="work-net") is None


def test_record_then_known_status_round_trips_true_and_false(tmp_path, monkeypatch):
    monkeypatch.setattr(nr, "STORE_PATH", tmp_path / "network-reachability.json")
    nr.record("huggingface.co", False, network_id="work-net")
    nr.record("api.semanticscholar.org", True, network_id="work-net")

    assert nr.known_status("huggingface.co", network_id="work-net") is False
    assert nr.known_status("api.semanticscholar.org", network_id="work-net") is True


def test_record_is_scoped_per_network_not_global(tmp_path, monkeypatch):
    monkeypatch.setattr(nr, "STORE_PATH", tmp_path / "network-reachability.json")
    nr.record("huggingface.co", False, network_id="work-net")
    nr.record("huggingface.co", True, network_id="home-net")

    assert nr.known_status("huggingface.co", network_id="work-net") is False
    assert nr.known_status("huggingface.co", network_id="home-net") is True


def test_record_overwrites_prior_entry_for_same_network_and_domain(tmp_path, monkeypatch):
    monkeypatch.setattr(nr, "STORE_PATH", tmp_path / "network-reachability.json")
    nr.record("huggingface.co", False, network_id="work-net")
    nr.record("huggingface.co", True, network_id="work-net")

    assert nr.known_status("huggingface.co", network_id="work-net") is True


# ── check_domain (real TLS-layer check, mocked at the socket/ssl boundary) ──

def test_check_domain_true_when_handshake_succeeds(monkeypatch):
    class _FakeSSLSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _FakeContext:
        def wrap_socket(self, sock, server_hostname=None):
            return _FakeSSLSock()

    monkeypatch.setattr(nr.socket, "create_connection", lambda *a, **k: _FakeSock())
    monkeypatch.setattr(nr.ssl, "create_default_context", lambda: _FakeContext())

    assert nr.check_domain("api.semanticscholar.org") is True


def test_check_domain_false_when_handshake_is_reset(monkeypatch):
    class _FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _FakeContext:
        def wrap_socket(self, sock, server_hostname=None):
            raise ConnectionResetError("connection reset during TLS handshake")

    monkeypatch.setattr(nr.socket, "create_connection", lambda *a, **k: _FakeSock())
    monkeypatch.setattr(nr.ssl, "create_default_context", lambda: _FakeContext())

    assert nr.check_domain("huggingface.co") is False


def test_check_domain_false_when_connection_cannot_be_established(monkeypatch):
    def raise_timeout(*a, **k):
        raise TimeoutError("no route")

    monkeypatch.setattr(nr.socket, "create_connection", raise_timeout)
    assert nr.check_domain("huggingface.co") is False


# ── check_and_record (the combined entry point) ─────────────────────────────

def test_check_and_record_persists_the_live_result(tmp_path, monkeypatch):
    monkeypatch.setattr(nr, "STORE_PATH", tmp_path / "network-reachability.json")
    monkeypatch.setattr(nr, "check_domain", lambda domain, **k: False)

    result = nr.check_and_record("huggingface.co", network_id="work-net")

    assert result is False
    assert nr.known_status("huggingface.co", network_id="work-net") is False
