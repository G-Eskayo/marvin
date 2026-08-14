"""Tests for auto_route_hook.py. Run via:
    ~/.agents/venv/bin/python -m pytest skills/route/scripts/tests/test_auto_route_hook.py -v
"""
from __future__ import annotations
import io
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import auto_route_hook as arh  # noqa: E402


# ── session state: fire at most once per session ────────────────────────────

def test_not_already_fired_when_state_file_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")
    assert arh._already_fired("session-1") is False


def test_mark_fired_then_already_fired_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")
    arh._mark_fired("session-1")
    assert arh._already_fired("session-1") is True


def test_mark_fired_is_scoped_per_session(tmp_path, monkeypatch):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")
    arh._mark_fired("session-1")
    assert arh._already_fired("session-2") is False


def test_already_fired_survives_corrupt_state_file(tmp_path, monkeypatch):
    state_file = tmp_path / "auto-route-state.json"
    state_file.write_text("{not valid json")
    monkeypatch.setattr(arh, "STATE_FILE", state_file)
    assert arh._already_fired("session-1") is False


# ── classify: maps route.py's intent to a message, silent on architecture ──

def test_classify_returns_message_for_recall(monkeypatch):
    monkeypatch.setattr(arh, "_resolve_intent", lambda prompt: "recall")
    assert "recall" in arh.classify("what did we decide last session").lower()


def test_classify_returns_message_for_coding(monkeypatch):
    monkeypatch.setattr(arh, "_resolve_intent", lambda prompt: "coding")
    assert "coding" in arh.classify("fix the bug in utils.py").lower()


def test_classify_returns_message_for_research(monkeypatch):
    monkeypatch.setattr(arh, "_resolve_intent", lambda prompt: "research")
    assert "research" in arh.classify("what's new in RAG").lower()


def test_classify_is_silent_for_architecture(monkeypatch):
    monkeypatch.setattr(arh, "_resolve_intent", lambda prompt: "architecture")
    assert arh.classify("should we redesign this") is None


# ── main: end-to-end stdin/stdout wiring ────────────────────────────────────

def _run_main(monkeypatch, payload, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    arh.main()
    return capsys.readouterr().out


def test_main_prints_message_on_first_fire(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")
    monkeypatch.setattr(arh, "classify", lambda prompt: "This looks like a **coding** task.")
    out = _run_main(monkeypatch, {"session_id": "s1", "user_prompt": "fix the bug"}, capsys)
    assert "coding" in out
    assert arh._already_fired("s1") is True


def test_main_is_silent_on_second_message_same_session(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")
    monkeypatch.setattr(arh, "classify", lambda prompt: "This looks like a **coding** task.")
    _run_main(monkeypatch, {"session_id": "s1", "user_prompt": "fix the bug"}, capsys)
    out = _run_main(monkeypatch, {"session_id": "s1", "user_prompt": "now also do this"}, capsys)
    assert out == ""


def test_main_marks_fired_even_when_classify_is_silent(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")
    monkeypatch.setattr(arh, "classify", lambda prompt: None)
    out = _run_main(monkeypatch, {"session_id": "s1", "user_prompt": "should we redesign this"}, capsys)
    assert out == ""
    assert arh._already_fired("s1") is True


def test_main_is_silent_and_does_not_crash_when_classify_raises(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")

    def raise_err(prompt):
        raise RuntimeError("ollama unreachable")

    monkeypatch.setattr(arh, "classify", raise_err)
    out = _run_main(monkeypatch, {"session_id": "s1", "user_prompt": "fix the bug"}, capsys)
    assert out == ""
    # still marked fired -- a transient failure shouldn't retry every message
    assert arh._already_fired("s1") is True


def test_main_no_ops_on_missing_session_id_or_prompt(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")
    out = _run_main(monkeypatch, {"session_id": "s1"}, capsys)
    assert out == ""
    assert arh._already_fired("s1") is False


def test_main_no_ops_on_invalid_stdin_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    arh.main()
    assert capsys.readouterr().out == ""
