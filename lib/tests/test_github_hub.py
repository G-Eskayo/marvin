"""GitHub hub claim mechanism (marvin#: TBD). Tests the claim, read, and lock logic.

    ~/.agents/venv/bin/python -m pytest lib/tests/test_github_hub.py -v
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import github_hub  # noqa: E402
import stamped  # noqa: E402

UTC = timezone.utc


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    """Temporary home directory for the test."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(github_hub, "CLAIM_PATH", claude_dir / "github-hub.json")
    monkeypatch.setattr(github_hub, "LOCK_PATH", claude_dir / ".github-hub.lock")
    return tmp_path, claude_dir


def test_claim_and_read_fresh(tmp_home):
    """Write a claim and read it back fresh."""
    tmp_path, claude_dir = tmp_home
    with patch("stamped._me", return_value=("mini", "uuid-mini")):
        with github_hub.claim_lock():
            stamped.write(github_hub.CLAIM_PATH, {"hub": "mini"}, tolerance_s=github_hub.LEASE_S)
        claim = github_hub.read_claim()
        assert not claim.missing
        assert not claim.stale
        assert claim.value["hub"] == "mini"
        assert claim.age_s is not None


def test_read_nonexistent_is_missing(tmp_home):
    """Read when no claim file exists."""
    tmp_home
    claim = github_hub.read_claim()
    assert claim.missing
    assert claim.stale


def test_claim_succeeds_when_none_exists(tmp_home):
    """try_claim succeeds when no claim exists."""
    tmp_home
    with patch("stamped._me", return_value=("mini", "uuid-mini")):
        success, reason = github_hub.try_claim("mini")
        assert success
        assert "claimed" in reason
        claim = github_hub.read_claim()
        assert claim.value["hub"] == "mini"


def test_claim_fails_when_one_exists_and_fresh(tmp_home):
    """try_claim fails when a fresh claim already exists."""
    tmp_home
    with patch("stamped._me", return_value=("mini", "uuid-mini")):
        success1, _ = github_hub.try_claim("mini")
        assert success1
    with patch("stamped._me", return_value=("laptop", "uuid-laptop")):
        success2, reason = github_hub.try_claim("laptop")
        assert not success2
        assert "mini" in reason


def test_claim_succeeds_when_one_is_stale(tmp_home):
    """try_claim succeeds when the existing claim is stale."""
    tmp_home
    now = datetime.now(UTC)
    with patch("stamped._me", return_value=("mini", "uuid-mini")):
        # Write a stale claim
        stale_claim = {"hub": "mini"}
        stamped.write(github_hub.CLAIM_PATH, stale_claim, tolerance_s=600, now=now - timedelta(seconds=700))
    # Now try to claim as laptop
    with patch("stamped._me", return_value=("laptop", "uuid-laptop")):
        success, reason = github_hub.try_claim("laptop")
        assert success
        assert "laptop" in github_hub.read_claim().value["hub"]


def test_force_claim_overwrites_fresh(tmp_home):
    """try_claim with force=True overwrites even a fresh claim."""
    tmp_home
    with patch("stamped._me", return_value=("mini", "uuid-mini")):
        success1, _ = github_hub.try_claim("mini")
        assert success1
    with patch("stamped._me", return_value=("laptop", "uuid-laptop")):
        success2, _ = github_hub.try_claim("laptop", force=True)
        assert success2
        assert github_hub.read_claim().value["hub"] == "laptop"


def test_current_hub_returns_fresh_claim(tmp_home):
    """current_hub returns the hub id if the claim is fresh."""
    tmp_home
    with patch("stamped._me", return_value=("mini", "uuid-mini")):
        github_hub.try_claim("mini")
    hub = github_hub.current_hub()
    assert hub == "mini"


def test_current_hub_returns_none_when_stale(tmp_home):
    """current_hub returns None if the claim is stale."""
    tmp_home
    now = datetime.now(UTC)
    with patch("stamped._me", return_value=("mini", "uuid-mini")):
        stale_claim = {"hub": "mini"}
        stamped.write(github_hub.CLAIM_PATH, stale_claim, tolerance_s=600, now=now - timedelta(seconds=700))
    hub = github_hub.current_hub()
    assert hub is None


def test_current_hub_returns_none_when_missing(tmp_home):
    """current_hub returns None when no claim exists."""
    tmp_home
    hub = github_hub.current_hub()
    assert hub is None


def test_current_hub_checks_registry(tmp_home):
    """current_hub returns None if the hub is not in the registry."""
    tmp_home
    with patch("stamped._me", return_value=("mini", "uuid-mini")):
        github_hub.try_claim("mini")
    registry = {"laptop": {}, "box": {}}  # mini is not registered
    hub = github_hub.current_hub(registry=registry)
    assert hub is None


def test_lease_term_persists(tmp_home):
    """The lease term is written and read back."""
    tmp_home
    with patch("stamped._me", return_value=("mini", "uuid-mini")):
        github_hub.try_claim("mini")
    claim = github_hub.read_claim()
    assert claim.value["lease_s"] == github_hub.LEASE_S
