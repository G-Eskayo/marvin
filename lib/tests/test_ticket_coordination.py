"""Tests for ticket_coordination.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_ticket_coordination.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import ticket_coordination as coord  # noqa: E402


# ── resolve_collision: the actual race -- both machines' add_claim_label ───
# ── calls can succeed, since GitHub labels are a set, not a compare-and-swap

def test_no_collision_when_only_one_machine_claimed():
    result = coord.resolve_collision(
        7, "mac-mini",
        list_claim_labels=lambda n: ["claimed:mac-mini"],
        release=lambda n, m: (_ for _ in ()).throw(AssertionError("should not release")),
    )
    assert result["collision"] is False
    assert result["winner"] == "mac-mini"
    assert result["released"] is False


def test_collision_detected_when_two_machines_both_claimed():
    result = coord.resolve_collision(
        7, "mac-mini",
        list_claim_labels=lambda n: ["claimed:mac-mini", "claimed:macbook-pro"],
        release=lambda n, m: None,
    )
    assert result["collision"] is True


def test_alphabetically_earlier_hostname_wins():
    # "mac-mini" < "macbook-pro" alphabetically
    result = coord.resolve_collision(
        7, "mac-mini",
        list_claim_labels=lambda n: ["claimed:mac-mini", "claimed:macbook-pro"],
        release=lambda n, m: None,
    )
    assert result["winner"] == "mac-mini"


def test_loser_releases_its_own_claim():
    released = []
    result = coord.resolve_collision(
        7, "macbook-pro",  # the loser in this collision
        list_claim_labels=lambda n: ["claimed:mac-mini", "claimed:macbook-pro"],
        release=lambda n, m: released.append((n, m)),
    )
    assert result["released"] is True
    assert released == [(7, "macbook-pro")]


def test_winner_does_not_release():
    released = []
    result = coord.resolve_collision(
        7, "mac-mini",  # the winner in this collision
        list_claim_labels=lambda n: ["claimed:mac-mini", "claimed:macbook-pro"],
        release=lambda n, m: released.append((n, m)),
    )
    assert result["released"] is False
    assert released == []


def test_loser_uses_ticket_claims_existing_release_not_new_mechanism(monkeypatch):
    # resolve_collision's default release hook should literally be
    # ticket_claim.release, not a reimplementation.
    import ticket_claim
    calls = []
    monkeypatch.setattr(ticket_claim, "release", lambda n, m, **kw: calls.append((n, m)))
    coord.resolve_collision(7, "macbook-pro", list_claim_labels=lambda n: ["claimed:mac-mini", "claimed:macbook-pro"])
    assert calls == [(7, "macbook-pro")]


# ── claim_with_coordination: full flow, #7's claim behavior unchanged ──────

def test_claim_with_coordination_returns_ticket_when_no_collision():
    result = coord.claim_with_coordination(
        "mac-mini",
        claim=lambda machine_id: 7,
        resolve=lambda issue, machine_id: {"collision": False, "winner": machine_id, "released": False},
    )
    assert result == 7


def test_claim_with_coordination_returns_none_when_lost_tiebreak():
    result = coord.claim_with_coordination(
        "macbook-pro",
        claim=lambda machine_id: 7,
        resolve=lambda issue, machine_id: {"collision": True, "winner": "mac-mini", "released": True},
    )
    assert result is None


def test_claim_with_coordination_returns_ticket_when_won_tiebreak():
    result = coord.claim_with_coordination(
        "mac-mini",
        claim=lambda machine_id: 7,
        resolve=lambda issue, machine_id: {"collision": True, "winner": "mac-mini", "released": False},
    )
    assert result == 7


def test_claim_with_coordination_does_not_call_resolve_when_nothing_claimed():
    resolve_calls = []
    result = coord.claim_with_coordination(
        "mac-mini",
        claim=lambda machine_id: None,
        resolve=lambda issue, machine_id: resolve_calls.append((issue, machine_id)),
    )
    assert result is None
    assert resolve_calls == []


def test_claim_with_coordination_uses_ticket_claims_claim_next_ticket_by_default(monkeypatch):
    import ticket_claim
    calls = []
    monkeypatch.setattr(ticket_claim, "claim_next_ticket", lambda machine_id, **kw: calls.append(machine_id) or None)
    coord.claim_with_coordination("mac-mini")
    assert calls == ["mac-mini"]


# ── default list_claim_labels (mocked subprocess) ───────────────────────────

def test_default_list_claim_labels_filters_to_claimed_prefix(monkeypatch):
    def fake_run(cmd, **kwargs):
        class R:
            stdout = '{"labels": [{"name": "ready-for-agent"}, {"name": "claimed:mac-mini"}]}'
            returncode = 0
        return R()
    monkeypatch.setattr(coord.subprocess, "run", fake_run)
    result = coord._default_list_claim_labels(7)
    assert result == ["claimed:mac-mini"]
