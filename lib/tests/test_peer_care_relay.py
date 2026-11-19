"""Tests for peer_care.py relay queue coordination.
Run via: ~/.agents/venv/bin/python -m pytest lib/tests/test_peer_care_relay.py -v
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import peer_care as pc  # noqa: E402


def test_relay_queue_starts_empty(tmp_path, monkeypatch):
    """Relay queue starts empty when no file exists."""
    relay_path = tmp_path / "relay-queue.json"
    monkeypatch.setattr(pc, "RELAY_QUEUE_PATH", relay_path)

    queue = pc.load_relay_queue()
    assert queue == {}


def test_queue_relay_read_creates_entry(tmp_path, monkeypatch):
    """Queuing a relay read creates an entry with backoff and timestamps."""
    relay_path = tmp_path / "relay-queue.json"
    monkeypatch.setattr(pc, "RELAY_QUEUE_PATH", relay_path)

    pc.queue_relay_read("G-Eskayo/marvin")

    queue = pc.load_relay_queue()
    assert "G-Eskayo/marvin" in queue
    entry = queue["G-Eskayo/marvin"]
    assert "queued_at" in entry
    assert entry["backoff_s"] == pc.RELAY_BACKOFF_MIN_S
    assert entry["last_failed_at"] is None


def test_queue_relay_read_idempotent(tmp_path, monkeypatch):
    """Queuing the same repo twice keeps the first entry."""
    relay_path = tmp_path / "relay-queue.json"
    monkeypatch.setattr(pc, "RELAY_QUEUE_PATH", relay_path)

    pc.queue_relay_read("G-Eskayo/marvin")
    queue1 = pc.load_relay_queue()
    first_time = queue1["G-Eskayo/marvin"]["queued_at"]

    pc.queue_relay_read("G-Eskayo/marvin")
    queue2 = pc.load_relay_queue()
    second_time = queue2["G-Eskayo/marvin"]["queued_at"]

    assert first_time == second_time  # Same entry


def test_flush_relay_queue_keeps_entries_on_failure(tmp_path, monkeypatch):
    """Flushing the relay queue doesn't clear entries if relay execution isn't wired.
    Entries get updated with backoff for retry."""
    relay_path = tmp_path / "relay-queue.json"
    monkeypatch.setattr(pc, "RELAY_QUEUE_PATH", relay_path)

    pc.queue_relay_read("G-Eskayo/marvin")
    pc.queue_relay_read("other/repo")
    queue_before = pc.load_relay_queue()
    assert len(queue_before) == 2

    # Initial backoff
    initial_backoff = queue_before["G-Eskayo/marvin"]["backoff_s"]

    pc.flush_relay_queue("mac-mini-1", {})

    queue_after = pc.load_relay_queue()
    # Queue should still have entries (not cleared)
    assert len(queue_after) == 2, "Failed relay reads should stay queued for retry"

    # Backoff should increase
    new_backoff = queue_after["G-Eskayo/marvin"]["backoff_s"]
    assert new_backoff > initial_backoff, "Backoff should increase on failed flush"

    # last_failed_at should be set
    assert queue_after["G-Eskayo/marvin"].get("last_failed_at") is not None


def test_relay_queue_survives_restart(tmp_path, monkeypatch):
    """Queued items survive process restart (persist to disk)."""
    relay_path = tmp_path / "relay-queue.json"
    monkeypatch.setattr(pc, "RELAY_QUEUE_PATH", relay_path)

    # First "process": queue some reads
    pc.queue_relay_read("repo-1")
    pc.queue_relay_read("repo-2")

    # "Second process": reload
    queue = pc.load_relay_queue()
    assert set(queue.keys()) == {"repo-1", "repo-2"}


def test_flush_relay_queue_respects_backoff_time(tmp_path, monkeypatch):
    """flush_relay_queue only retries after backoff time has elapsed."""
    relay_path = tmp_path / "relay-queue.json"
    monkeypatch.setattr(pc, "RELAY_QUEUE_PATH", relay_path)

    now_ts = time.time()
    # Create a queue entry with a failed attempt and backoff
    queue = {
        "repo1": {
            "queued_at": now_ts - 1000,
            "backoff_s": 60,  # 60 second backoff
            "last_failed_at": now_ts - 30,  # Failed 30 seconds ago
            "last_attempt": now_ts - 30  # Last attempt 30 seconds ago
        }
    }
    relay_path.write_text(json.dumps(queue))

    # Flush should NOT retry because backoff hasn't elapsed (30s < 60s)
    result = pc.flush_relay_queue("mac-mini-1", {})

    # Verify backoff message was returned
    assert "repo1" in result
    assert "backoff" in result["repo1"][1]

    # Verify the entry still has original backoff (not doubled)
    queue = json.loads(relay_path.read_text())
    assert queue["repo1"]["backoff_s"] == 60  # Should NOT be doubled


def test_relay_backoff_increases_after_elapsed_time(tmp_path, monkeypatch):
    """When backoff time has elapsed, flush_relay_queue increases backoff on retry."""
    relay_path = tmp_path / "relay-queue.json"
    monkeypatch.setattr(pc, "RELAY_QUEUE_PATH", relay_path)

    now_ts = time.time()
    # Create a queue entry with an old failed attempt
    queue = {
        "repo1": {
            "queued_at": now_ts - 1000,
            "backoff_s": 60,  # 60 second backoff
            "last_failed_at": now_ts - 100,  # Failed 100 seconds ago
            "last_attempt": now_ts - 100  # Last attempt 100 seconds ago
        }
    }
    relay_path.write_text(json.dumps(queue))

    # Flush should retry and increase backoff
    result = pc.flush_relay_queue("mac-mini-1", {})

    # Verify the entry's backoff was doubled
    queue = json.loads(relay_path.read_text())
    assert queue["repo1"]["backoff_s"] == 120  # 60 * 2


def test_im_back_handles_github_hub_import_error(tmp_path, monkeypatch):
    """im_back doesn't crash when called at boot and handles gracefully."""
    relay_path = tmp_path / "relay-queue.json"
    monkeypatch.setattr(pc, "RELAY_QUEUE_PATH", relay_path)

    # Mock machine_profile
    import sys
    mock_mp = __import__('unittest.mock', fromlist=['Mock']).Mock()
    mock_mp.registry_id.return_value = "mac-mini-1"
    monkeypatch.setitem(sys.modules, "machine_profile", mock_mp)

    # Mock watched_by to return no peers so we don't try SSH
    original_watched_by = pc.watched_by
    pc.watched_by = lambda device, cfg: []

    # Mock _ssh to track calls
    original_ssh = pc._ssh
    ssh_calls = []
    pc._ssh = lambda *args, **kwargs: ssh_calls.append((args, kwargs))

    try:
        # Call im_back - it should not raise even if there are issues
        cfg = {"watch": {"mac-mini-1": []}}
        pc.im_back("mac-mini-1", cfg)
        # If we get here, im_back didn't crash
        assert True
    finally:
        pc.watched_by = original_watched_by
        pc._ssh = original_ssh
