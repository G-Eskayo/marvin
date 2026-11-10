"""Stamped copies (marvin#1223): every per-Mac file says which Mac made it and how old it is, and a reader can tell a
live copy from a frozen one. The envelope is the github feed's (flat top-level keys: host, generated_at, alive_at,
tolerance_s), so a reader that predates it keeps working on the other Mac during a rollout.

Tests try to break it (ADR 0063): no file, a legacy file (no host), a future generated_at, exactly at tolerance, a
garbled time, half-written JSON, a renamed Mac (hardware_uuid), the producer's copy older than ours. The shared cases
also run in dashboard/test/stamped.test.js, so the Python and JS readers can't drift. Temp dirs only.

    ~/.agents/venv/bin/python -m pytest lib/tests/test_stamped.py -v
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import stamped  # noqa: E402

CASES = json.loads((LIB.parent / "dashboard" / "test" / "fixtures" / "stamped_cases.json").read_text())
NOW = datetime.fromisoformat(CASES["now"].replace("Z", "+00:00"))


@pytest.mark.parametrize("case", CASES["cases"], ids=lambda c: c["name"])
def test_shared_cases(case, tmp_path):
    p = tmp_path / "f.json"
    p.write_text(json.dumps(case["data"]))
    if "mtime" in case:
        os.utime(p, (case["mtime"], case["mtime"]))
    c = stamped.read(p, now=NOW, default_tolerance_s=case.get("default_tolerance_s", 600))
    for k, v in case["expect"].items():
        if k == "value_x":
            assert c.value["x"] == v
        else:
            assert getattr(c, k) == v, k


def test_no_file_is_missing_and_stale(tmp_path):
    c = stamped.read(tmp_path / "nope.json", now=NOW)
    assert c.missing and c.stale and c.value is None and c.age_s is None


@pytest.mark.parametrize("text", ["{half", "", "[1, 2]", "null", "\x00\x01"])
def test_unreadable_or_not_an_object_is_missing_never_raises(tmp_path, text):
    p = tmp_path / "f.json"
    p.write_text(text)
    c = stamped.read(p, now=NOW)
    assert c.missing and c.stale and c.value is None


def test_stamp_adds_the_envelope_and_keeps_the_data(monkeypatch):
    monkeypatch.setattr(stamped, "_me", lambda: ("macbook-pro-1", "UUID-1"))
    out = stamped.stamp({"checks": [1]}, tolerance_s=1200, now=NOW)
    assert out == {"checks": [1], "host": "macbook-pro-1", "hardware_uuid": "UUID-1",
                   "generated_at": "2026-11-10T12:00:00+00:00", "alive_at": "2026-11-10T12:00:00+00:00",
                   "tolerance_s": 1200}


def test_stamp_keeps_a_writers_own_generated_at(monkeypatch):
    monkeypatch.setattr(stamped, "_me", lambda: ("m", None))
    out = stamped.stamp({"generated_at": "2026-11-10T11:00:00+00:00"}, tolerance_s=60, now=NOW)
    assert out["generated_at"] == "2026-11-10T11:00:00+00:00" and out["alive_at"] == "2026-11-10T12:00:00+00:00"
    assert "hardware_uuid" not in out


def test_stamp_refuses_a_non_object_and_a_bad_tolerance():
    with pytest.raises(TypeError):
        stamped.stamp([1], tolerance_s=60)
    for bad in (0, -5, "60", None):
        with pytest.raises(ValueError):
            stamped.stamp({}, tolerance_s=bad)


def test_write_is_atomic_and_reads_back(tmp_path, monkeypatch):
    monkeypatch.setattr(stamped, "_me", lambda: ("mac-mini-1", "U"))
    p = tmp_path / "logs" / "x.json"
    stamped.write(p, {"busy": False}, tolerance_s=3600, now=NOW)
    assert not list(p.parent.glob("*.tmp"))
    c = stamped.read(p, now=NOW)
    assert c.host == "mac-mini-1" and c.value["busy"] is False and not c.stale and not c.legacy


def test_the_producer_is_known_by_hardware_uuid_after_a_rename():
    registry = {"mac-mini-1": {"label": "Mac mini", "hardware_uuid": "U-MINI"}}
    c = stamped.Copy(value={}, host="old-name", hardware_uuid="U-MINI", age_s=120, tolerance_s=600)
    assert stamped.producer(c, registry) == "mac-mini-1"
    assert stamped.describe(c, registry) == "Mac mini, as of 2 min ago"


@pytest.mark.parametrize("age,text", [(30, "just now"), (120, "2 min ago"), (3 * 3600 + 60, "3 h ago"),
                                      (11 * 86400, "11 days ago"), (None, "age unknown")])
def test_describe_reads_like_a_person(age, text):
    c = stamped.Copy(value={}, host="macbook-pro-1", age_s=age, tolerance_s=600)
    assert stamped.describe(c, {}) == f"macbook-pro-1, as of {text}" if age is not None else text in stamped.describe(c, {})


def test_describe_says_stale_and_legacy():
    c = stamped.Copy(value={}, host=None, age_s=11 * 86400, tolerance_s=1200, stale=True, legacy=True)
    assert stamped.describe(c, {}, this_mac="macbook-pro-1") == "this Mac (unstamped), as of 11 days ago · stale"


def test_newer_uses_the_fresher_copy_and_says_which():
    local = stamped.Copy(value={"a": 1}, host="macbook-pro-1", age_s=11 * 86400, tolerance_s=1200, stale=True)
    peer = stamped.Copy(value={"a": 2}, host="mac-mini-1", age_s=120, tolerance_s=1200)
    assert stamped.newer(local, peer) is peer and stamped.newer(peer, local) is peer
    older_peer = stamped.Copy(value={"a": 3}, host="mac-mini-1", age_s=99999, tolerance_s=1200, stale=True)
    fresh_local = stamped.Copy(value={"a": 4}, host="macbook-pro-1", age_s=10, tolerance_s=1200)
    assert stamped.newer(fresh_local, older_peer) is fresh_local
    missing = stamped.Copy(value=None, missing=True, stale=True)
    assert stamped.newer(missing, older_peer) is older_peer and stamped.newer(missing, missing) is missing
