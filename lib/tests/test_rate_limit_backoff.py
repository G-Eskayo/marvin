"""Tests for rate_limit_backoff.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_rate_limit_backoff.py -v
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import rate_limit_backoff as rlb  # noqa: E402

MSG = "You've hit your session limit · resets 4:50pm (America/Denver)"


def test_is_rate_limit_text_detects_the_real_message():
    assert rlb.is_rate_limit_text(MSG) is True


def test_is_rate_limit_text_false_for_a_real_plan():
    assert rlb.is_rate_limit_text("1. Add a new field to the model\n2. Update the tests") is False


def test_parse_reset_time_resolves_today_when_still_ahead(monkeypatch):
    now = datetime(2026, 9, 1, 15, 0, tzinfo=ZoneInfo("America/Denver")).astimezone(timezone.utc)
    reset_at = rlb.parse_reset_time(MSG, now=now)
    local = reset_at.astimezone(ZoneInfo("America/Denver"))
    assert (local.year, local.month, local.day) == (2026, 9, 1)
    assert (local.hour, local.minute) == (16, 50)


def test_parse_reset_time_rolls_to_tomorrow_when_already_past(monkeypatch):
    now = datetime(2026, 9, 1, 18, 0, tzinfo=ZoneInfo("America/Denver")).astimezone(timezone.utc)
    reset_at = rlb.parse_reset_time(MSG, now=now)
    local = reset_at.astimezone(ZoneInfo("America/Denver"))
    assert (local.year, local.month, local.day) == (2026, 9, 2)
    assert (local.hour, local.minute) == (16, 50)


def test_parse_reset_time_none_for_non_matching_text():
    assert rlb.parse_reset_time("a normal implementation plan with no limit talk") is None


def test_parse_reset_time_handles_am():
    now = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
    reset_at = rlb.parse_reset_time("session limit -- resets 9:15am (UTC)", now=now)
    assert reset_at.hour == 9 and reset_at.minute == 15


def test_record_backoff_writes_state_and_returns_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(rlb, "STATE_PATH", tmp_path / "rate-limit-backoff.json")
    now = datetime(2026, 9, 1, 20, 0, tzinfo=ZoneInfo("America/Denver")).astimezone(timezone.utc)
    backoff_until = rlb.record_backoff(MSG, now=now)

    assert backoff_until is not None
    assert rlb.STATE_PATH.exists()
    assert rlb.active_backoff(now=now) == backoff_until


def test_record_backoff_is_a_noop_for_non_limit_text(tmp_path, monkeypatch):
    monkeypatch.setattr(rlb, "STATE_PATH", tmp_path / "rate-limit-backoff.json")
    result = rlb.record_backoff("a real implementation plan")
    assert result is None
    assert not rlb.STATE_PATH.exists()


def test_record_backoff_adds_a_buffer_past_the_exact_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(rlb, "STATE_PATH", tmp_path / "rate-limit-backoff.json")
    now = datetime(2026, 9, 1, 20, 0, tzinfo=ZoneInfo("America/Denver")).astimezone(timezone.utc)
    backoff_until = rlb.record_backoff(MSG, now=now)
    reset_at = rlb.parse_reset_time(MSG, now=now)
    assert backoff_until > reset_at


def test_active_backoff_none_when_no_state_file(tmp_path, monkeypatch):
    monkeypatch.setattr(rlb, "STATE_PATH", tmp_path / "rate-limit-backoff.json")
    assert rlb.active_backoff() is None


def test_active_backoff_none_and_self_cleans_when_expired(tmp_path, monkeypatch):
    monkeypatch.setattr(rlb, "STATE_PATH", tmp_path / "rate-limit-backoff.json")
    past = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    future_check = datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc)
    rlb.record_backoff("session limit -- resets 12:00pm (UTC)", now=past - rlb._RESET_BUFFER)

    assert rlb.STATE_PATH.exists()
    assert rlb.active_backoff(now=future_check) is None
    assert not rlb.STATE_PATH.exists()


def test_active_backoff_ignores_a_corrupt_state_file(tmp_path, monkeypatch):
    state_path = tmp_path / "rate-limit-backoff.json"
    monkeypatch.setattr(rlb, "STATE_PATH", state_path)
    state_path.write_text("not json")
    assert rlb.active_backoff() is None


def test_rate_limited_exception_carries_backoff_until_and_text():
    now = datetime(2026, 9, 1, 20, 0, tzinfo=ZoneInfo("America/Denver")).astimezone(timezone.utc)
    reset_at = rlb.parse_reset_time(MSG, now=now)
    exc = rlb.RateLimited(reset_at, MSG)
    assert exc.backoff_until == reset_at
    assert "session limit" in str(exc).lower()
