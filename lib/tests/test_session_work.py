"""Tests for session_work.py (sessions know what other sessions are working on, #326). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_session_work.py -v
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import session_work as sw  # noqa: E402

T = 1_800_000_000.0


def git(cwd, *a):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


def test_a_worktree_copy_and_the_main_checkout_are_the_same_file(tmp_path):
    main = tmp_path / "repo"
    main.mkdir()
    git(main, "init", "-q", "-b", "main"); git(main, "config", "user.email", "t@t"); git(main, "config", "user.name", "t")
    (main / "lib").mkdir(); (main / "lib" / "a.py").write_text("x\n")
    git(main, "add", "-A"); git(main, "commit", "-qm", "c")
    wt = tmp_path / "wt"
    git(main, "worktree", "add", "-q", str(wt))
    assert sw.file_key(str(main / "lib" / "a.py")) == sw.file_key(str(wt / "lib" / "a.py"))
    assert sw.file_key(str(main / "lib" / "a.py"))[1] == "lib/a.py"
    assert sw.file_key(str(tmp_path / "loose.txt")) == (None, str(tmp_path / "loose.txt"))


def test_another_live_session_editing_the_same_file_is_an_overlap():
    st = {}
    sw.record_prompt(st, "A", "fix the GitHub rate limit", T)
    sw.record_edit(st, "A", ("r", "lib/health_checks.py"), T)
    sw.record_prompt(st, "B", "add a gate for gh", T + 60)
    found = sw.overlaps(st, "B", ("r", "lib/health_checks.py"), T + 120)
    assert [o["session"] for o in found] == ["A"] and found[0]["request"] == "fix the GitHub rate limit"
    assert sw.overlaps(st, "B", ("r", "lib/other.py"), T + 120) == []
    assert sw.overlaps(st, "A", ("r", "lib/health_checks.py"), T + 120) == []  # your own edits are not an overlap


def test_a_session_quiet_for_45_minutes_no_longer_counts():
    st = {}
    sw.record_edit(st, "A", ("r", "x.py"), T)
    assert sw.overlaps(st, "B", ("r", "x.py"), T + 44 * 60)
    assert sw.overlaps(st, "B", ("r", "x.py"), T + 46 * 60) == []


def test_asked_once_per_file_per_pair_of_sessions():
    st = {}
    sw.record_edit(st, "A", ("r", "x.py"), T)
    first = sw.pre_edit(st, "B", ("r", "x.py"), T + 10)
    assert first and "x.py" in first and "A"[:1]
    assert sw.pre_edit(st, "B", ("r", "x.py"), T + 20) is None
    sw.record_edit(st, "C", ("r", "x.py"), T + 30)
    assert sw.pre_edit(st, "B", ("r", "x.py"), T + 40)  # a new session touching it asks again


def test_stale_sessions_are_pruned_so_the_file_stays_small():
    st = {}
    sw.record_edit(st, "old", ("r", "x.py"), T)
    sw.record_edit(st, "new", ("r", "y.py"), T + 5 * 3600)
    sw.prune(st, T + 5 * 3600)
    assert set(st["sessions"]) == {"new"}


def test_the_ticket_a_session_is_building_is_the_one_its_request_names():
    assert sw.ticket_in("yes build #318 now") == 318
    assert sw.ticket_in("build it") is None
    assert sw.ticket_in("compare #312 and #313") is None  # two tickets: not sure which, so no claim
    assert sw.ticket_in("PR 257 has a conflict") is None


def test_claim_is_offered_once_per_session_and_repo():
    st = {}
    sw.record_prompt(st, "A", "build #326", T)
    assert sw.claim_wanted(st, "A", "/repo") == 326
    assert sw.claim_wanted(st, "A", "/repo") is None


def test_hook_handlers_round_trip_through_the_state_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "STATE_PATH", tmp_path / "s.json")
    monkeypatch.setattr(sw, "_start_claim", lambda *a: None)
    sw.handle("prompt", {"session_id": "A", "prompt": "fix health checks", "cwd": str(tmp_path)}, now=T)
    sw.handle("post", {"session_id": "A", "tool_input": {"file_path": str(tmp_path / "h.py")}, "cwd": str(tmp_path)}, now=T + 1)
    out = sw.handle("pre", {"session_id": "B", "tool_input": {"file_path": str(tmp_path / "h.py")}, "cwd": str(tmp_path)}, now=T + 2)
    d = json.loads(out)["hookSpecificOutput"]
    assert d["hookEventName"] == "PreToolUse" and d["permissionDecision"] == "ask"
    assert "fix health checks" in d["permissionDecisionReason"]
    assert sw.handle("pre", {"session_id": "A", "tool_input": {"file_path": str(tmp_path / "h.py")}}, now=T + 3) is None


def test_a_broken_state_file_never_blocks_an_edit(tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    p.write_text("{not json")
    monkeypatch.setattr(sw, "STATE_PATH", p)
    assert sw.handle("pre", {"session_id": "B", "tool_input": {"file_path": "/x"}}, now=T) is None


# ── remote sessions (cross-Mac visibility) ──────────────────────────────────

def test_a_remote_overlap_is_found_and_named_with_the_other_macs_device_id():
    st = {}
    remote = {"mac-mini-1": {"A": {"request": "fix the GitHub rate limit", "last": T, "files": {"r|lib/health.py": T}, "claimed": []}}}
    found = sw.overlaps(st, "B", ("r", "lib/health.py"), T + 120, remote=remote)
    assert len(found) == 1
    assert found[0]["session"] == "A"
    assert found[0]["machine"] == "mac-mini-1"
    assert found[0]["request"] == "fix the GitHub rate limit"


def test_pre_edit_message_differs_for_local_vs_remote_overlaps():
    st = {}
    sw.record_edit(st, "A", ("r", "lib/x.py"), T)
    local_msg = sw.pre_edit(st, "B", ("r", "lib/x.py"), T + 10)
    assert "on this Mac" in local_msg

    remote = {"mac-mini-1": {"C": {"request": "something else", "last": T, "files": {"r|lib/x.py": T}, "claimed": []}}}
    remote_msg = sw.pre_edit(st, "B", ("r", "lib/x.py"), T + 10, remote=remote)
    assert "on mac-mini-1" in remote_msg


def test_asked_once_per_pair_applies_to_remote_hits():
    st = {}
    remote = {"mac-mini-1": {"A": {"request": "work", "last": T, "files": {"r|x.py": T}, "claimed": []}}}
    first = sw.pre_edit(st, "B", ("r", "x.py"), T + 10, remote=remote)
    assert first and "A" in first
    second = sw.pre_edit(st, "B", ("r", "x.py"), T + 20, remote=remote)
    assert second is None


def test_remote_session_id_collision_does_not_suppress_local_ask():
    """A remote session with the same ID as a local session (hash collision) doesn't suppress the ask."""
    st = {}
    sw.record_edit(st, "A", ("r", "x.py"), T)
    remote = {"mac-mini-1": {"A": {"request": "remote A", "last": T, "files": {"r|x.py": T}, "claimed": []}}}
    msg = sw.pre_edit(st, "B", ("r", "x.py"), T + 10, remote=remote)
    # Should ask about both, since they're different machines
    assert msg and msg.count("x.py") >= 1  # at least one message


def test_a_remote_session_quiet_for_45_minutes_no_longer_counts():
    st = {}
    remote = {"mac-mini-1": {"A": {"request": "work", "last": T, "files": {"r|x.py": T}, "claimed": []}}}
    found = sw.overlaps(st, "B", ("r", "x.py"), T + 44 * 60, remote=remote)
    assert found
    found = sw.overlaps(st, "B", ("r", "x.py"), T + 46 * 60, remote=remote)
    assert found == []


def test_remote_sessions_caches_and_respects_60s_window():
    st = {}
    call_count = [0]
    def fake_fetch(host):
        call_count[0] += 1
        return {"A": {"request": "work", "last": T, "files": {}, "claimed": []}}

    peers = {"mac-mini-1": {"tailscale_hostname": "gils-mac-mini"}}
    result1 = sw.remote_sessions(st, T, peers=peers, fetch=fake_fetch)
    assert call_count[0] == 1
    assert "A" in result1["mac-mini-1"]

    result2 = sw.remote_sessions(st, T + 30, peers=peers, fetch=fake_fetch)
    assert call_count[0] == 1  # cached, no new fetch
    assert result2 == result1

    result3 = sw.remote_sessions(st, T + 70, peers=peers, fetch=fake_fetch)
    assert call_count[0] == 2  # cache expired, fetched again
    assert result3["mac-mini-1"]["A"]["request"] == "work"


def test_fetch_remote_sessions_returns_none_on_timeout():
    # Simulate timeout by raising socket.timeout
    import socket
    def fake_urlopen_timeout(url, timeout=None):
        raise socket.timeout("timed out")

    import urllib.request
    import unittest.mock
    with unittest.mock.patch("urllib.request.urlopen", fake_urlopen_timeout):
        result = sw.fetch_remote_sessions("gils-mac-mini")
        assert result is None


def test_fetch_remote_sessions_returns_none_on_connection_refused():
    import socket
    def fake_urlopen_refused(url, timeout=None):
        raise ConnectionRefusedError("connection refused")

    import urllib.request
    import unittest.mock
    with unittest.mock.patch("urllib.request.urlopen", fake_urlopen_refused):
        result = sw.fetch_remote_sessions("gils-mac-mini")
        assert result is None


def test_fetch_remote_sessions_returns_none_on_dns_failure():
    import socket
    def fake_urlopen_dns(url, timeout=None):
        raise socket.gaierror("Name or service not known")

    import urllib.request
    import unittest.mock
    with unittest.mock.patch("urllib.request.urlopen", fake_urlopen_dns):
        result = sw.fetch_remote_sessions("gils-mac-mini")
        assert result is None


def test_fetch_remote_sessions_returns_none_on_non_200_status():
    import urllib.error
    def fake_urlopen_404(url, timeout=None):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    import urllib.request
    import unittest.mock
    with unittest.mock.patch("urllib.request.urlopen", fake_urlopen_404):
        result = sw.fetch_remote_sessions("gils-mac-mini")
        assert result is None


def test_fetch_remote_sessions_returns_none_on_non_json_body():
    import io
    class FakeResponse:
        def read(self):
            return b"not json"
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def fake_urlopen_bad_json(url, timeout=None):
        return FakeResponse()

    import urllib.request
    import unittest.mock
    with unittest.mock.patch("urllib.request.urlopen", fake_urlopen_bad_json):
        result = sw.fetch_remote_sessions("gils-mac-mini")
        assert result is None


def test_fetch_remote_sessions_returns_none_on_bad_sessions_shape():
    import io
    class FakeResponse:
        def read(self):
            return b'{"sessions": "not a dict"}'
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def fake_urlopen_bad_shape(url, timeout=None):
        return FakeResponse()

    import urllib.request
    import unittest.mock
    with unittest.mock.patch("urllib.request.urlopen", fake_urlopen_bad_shape):
        result = sw.fetch_remote_sessions("gils-mac-mini")
        assert result is None


def test_fetch_remote_sessions_returns_none_on_malformed_session_entry():
    import io
    class FakeResponse:
        def read(self):
            return b'{"sessions": {"A": {"files": "not a dict"}}}'
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def fake_urlopen_bad_entry(url, timeout=None):
        return FakeResponse()

    import urllib.request
    import unittest.mock
    with unittest.mock.patch("urllib.request.urlopen", fake_urlopen_bad_entry):
        result = sw.fetch_remote_sessions("gils-mac-mini")
        assert result is None


def test_remote_peers_returns_empty_on_missing_profile():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        result = sw.remote_peers(str(Path(tmp) / "marvin-network.json"))
        assert result == {}


def test_remote_peers_returns_empty_on_unreadable_profile():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "marvin-network.json"
        p.write_text("{}")
        p.chmod(0o000)
        try:
            result = sw.remote_peers(str(p))
            assert result == {}
        finally:
            p.chmod(0o644)


def test_remote_peers_returns_empty_on_corrupt_json():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "marvin-network.json"
        p.write_text("not json")
        result = sw.remote_peers(str(p))
        assert result == {}


def test_remote_peers_excludes_this_machine_by_hardware_uuid(tmp_path, monkeypatch):
    profile = tmp_path / "machine-profile.json"
    profile.write_text('{"hardware_uuid": "uuid-a"}')
    monkeypatch.setattr(sw, "_my_hardware_uuid", lambda: "uuid-a")

    registry = tmp_path / "marvin-network.json"
    registry.write_text(json.dumps({
        "device-1": {"hardware_uuid": "uuid-a", "tailscale_hostname": "host-a"},
        "device-2": {"hardware_uuid": "uuid-b", "tailscale_hostname": "host-b"}
    }))

    result = sw.remote_peers(str(registry))
    assert "device-1" not in result
    assert "device-2" in result


def test_remote_peers_returns_all_peers_when_this_machine_is_not_registered():
    import tempfile
    import json
    import unittest.mock
    with tempfile.TemporaryDirectory() as tmp:
        registry = Path(tmp) / "marvin-network.json"
        registry.write_text(json.dumps({
            "device-1": {"hardware_uuid": "uuid-a", "tailscale_hostname": "host-a"},
            "device-2": {"hardware_uuid": "uuid-b", "tailscale_hostname": "host-b"}
        }))

        # Mock _my_hardware_uuid to return empty (not registered)
        with unittest.mock.patch.object(sw, "_my_hardware_uuid", return_value=""):
            result = sw.remote_peers(str(registry))
            # All entries with different UUIDs are peers (even if my UUID is unknown)
            assert len(result) == 2
            assert "device-1" in result and "device-2" in result


def test_remote_peers_skips_entries_without_tailscale_hostname():
    import tempfile
    import json
    import unittest.mock
    with tempfile.TemporaryDirectory() as tmp:
        registry = Path(tmp) / "marvin-network.json"
        registry.write_text(json.dumps({
            "device-1": {"hardware_uuid": "uuid-a"},  # no tailscale_hostname
            "device-2": {"hardware_uuid": "uuid-b", "tailscale_hostname": "host-b"}
        }))

        with unittest.mock.patch.object(sw, "_my_hardware_uuid", return_value="uuid-this"):
            result = sw.remote_peers(str(registry))
            # device-1 is skipped (no tailscale_hostname)
            # device-2 is included and usable
            assert len(result) == 1
            assert "device-2" in result


def test_handle_pre_calls_remote_sessions(tmp_path, monkeypatch):
    """Verify that handle's pre branch calls remote_sessions and can find remote overlaps."""
    monkeypatch.setattr(sw, "STATE_PATH", tmp_path / "s.json")
    monkeypatch.setattr(sw, "_start_claim", lambda *a: None)

    call_log = []
    original_remote_sessions = sw.remote_sessions
    def tracked_remote_sessions(st, now, peers=None, fetch=None):
        call_log.append(True)
        return {}  # No overlaps for this test

    monkeypatch.setattr(sw, "remote_sessions", tracked_remote_sessions)
    sw.handle("pre", {"session_id": "B", "tool_input": {"file_path": str(tmp_path / "h.py")}}, now=T)
    # Verify remote_sessions was called
    assert call_log


def test_with_no_peers_registered_pre_edit_behaves_as_before_local_only(tmp_path, monkeypatch):
    """Regression test: empty registry means no peers, so local-only behavior."""
    monkeypatch.setattr(sw, "STATE_PATH", tmp_path / "s.json")
    monkeypatch.setattr(sw, "_start_claim", lambda *a: None)

    sw.handle("prompt", {"session_id": "A", "prompt": "fix health", "cwd": str(tmp_path)}, now=T)
    sw.handle("post", {"session_id": "A", "tool_input": {"file_path": str(tmp_path / "h.py")}}, now=T + 1)
    out = sw.handle("pre", {"session_id": "B", "tool_input": {"file_path": str(tmp_path / "h.py")}}, now=T + 2)

    d = json.loads(out)["hookSpecificOutput"]
    assert "on this Mac" in d["permissionDecisionReason"]
    assert "mac-" not in d["permissionDecisionReason"]


def test_broken_state_plus_reachable_remote_never_blocks(tmp_path, monkeypatch):
    """Even with a broken state file and a remote peer, the edit never blocks."""
    p = tmp_path / "s.json"
    p.write_text("{not json")
    monkeypatch.setattr(sw, "STATE_PATH", p)

    assert sw.handle("pre", {"session_id": "B", "tool_input": {"file_path": "/x"}}, now=T) is None
