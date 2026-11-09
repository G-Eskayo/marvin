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


# ── fast path: keyword-only first pass, skips embed when confident ───────────

def test_fast_path_skips_embed_when_keyword_hits_meet_threshold(monkeypatch):
    """A prompt with many keyword hits must return the message without calling resolve_intent."""
    sys.path.insert(0, str(Path.home() / ".agents" / "skills" / "route" / "scripts"))
    import route  # noqa: E402

    def should_not_call(prompt):
        raise AssertionError("resolve_intent should not be called when fast path is confident")

    monkeypatch.setattr(arh, "_resolve_intent", should_not_call)
    prompt = "fix the bug in utils.py and refactor the code and debug the error"
    result = arh.classify(prompt)
    assert result is not None
    assert "coding" in result.lower()


def test_slow_path_falls_through_to_embed_when_keyword_hits_below_threshold(monkeypatch):
    """A prompt with <threshold keyword hits must call resolve_intent (embed path)."""
    sys.path.insert(0, str(Path.home() / ".agents" / "skills" / "route" / "scripts"))
    import route  # noqa: E402

    called = {}

    def track_call(prompt):
        called["embed"] = True
        return "architecture"  # Default intent is silent

    monkeypatch.setattr(arh, "_resolve_intent", track_call)
    prompt = "should we redesign this module"
    result = arh.classify(prompt)
    assert called.get("embed") is True
    assert result is None


def test_fast_path_threshold_boundary(monkeypatch):
    """Off-by-one guard: hits == threshold-1 goes slow, hits == threshold goes fast."""
    sys.path.insert(0, str(Path.home() / ".agents" / "skills" / "route" / "scripts"))
    import route  # noqa: E402

    embed_called = {}

    def track_call(prompt):
        embed_called["called"] = True
        return "architecture"

    monkeypatch.setattr(arh, "_resolve_intent", track_call)

    # Below threshold: should call embed
    prompt_below = "fix this"  # Only 1 "fix" keyword, below threshold
    result = arh.classify(prompt_below)
    assert embed_called.get("called") is True

    # At/above threshold: should not call embed
    embed_called.clear()

    def no_call(prompt):
        raise AssertionError("embed should not be called")

    monkeypatch.setattr(arh, "_resolve_intent", no_call)
    prompt_above = "fix the bug and refactor the code and debug it"
    result = arh.classify(prompt_above)
    assert result is not None


def test_fast_path_stays_silent_for_confident_architecture_without_calling_embed(monkeypatch):
    """Fast path recognizes architecture intent and stays silent without embed cost."""
    sys.path.insert(0, str(Path.home() / ".agents" / "skills" / "route" / "scripts"))
    import route  # noqa: E402

    def no_call(prompt):
        raise AssertionError("embed should not be called for confident architecture")

    monkeypatch.setattr(arh, "_resolve_intent", no_call)
    # Craft a prompt with multiple architecture keywords to hit threshold
    prompt = "should we redesign the architecture and restructure the approach considering the strategy and trade-offs"
    result = arh.classify(prompt)
    assert result is None


def test_fast_path_message_comes_from_same_messages_table(monkeypatch):
    """Fast-pathed message is identical to route.py's INTENTS mapping."""
    sys.path.insert(0, str(Path.home() / ".agents" / "skills" / "route" / "scripts"))
    import route  # noqa: E402

    def no_call(prompt):
        raise AssertionError("embed should not be called")

    monkeypatch.setattr(arh, "_resolve_intent", no_call)
    prompt = "fix the bug and refactor the code and debug the error"
    result = arh.classify(prompt)
    # Should match the message for coding intent
    assert result == arh.MESSAGES.get("coding")


def test_fast_path_truncates_before_keyword_scoring(monkeypatch):
    """A 6MB prompt with keywords only past truncation point must NOT fast-path."""
    sys.path.insert(0, str(Path.home() / ".agents" / "skills" / "route" / "scripts"))
    import route  # noqa: E402

    embed_called = {}

    def track_call(prompt):
        embed_called["called"] = True
        return "coding"

    monkeypatch.setattr(arh, "_resolve_intent", track_call)

    # Create a huge prompt where only keywords beyond MAX_PROMPT_CHARS exist
    junk = "a" * 25000
    prompt = junk + " fix the bug refactor debug"
    result = arh.classify(prompt)
    # Should have called resolve_intent because truncated prompt lacks keywords
    assert embed_called.get("called") is True


def test_fast_path_min_hits_is_not_below_route_min_hits(monkeypatch):
    """Regression guard: FAST_PATH_MIN_HITS >= route.MIN_HITS."""
    sys.path.insert(0, str(Path.home() / ".agents" / "skills" / "route" / "scripts"))
    import route  # noqa: E402

    assert arh.FAST_PATH_MIN_HITS >= route.MIN_HITS


def test_fast_path_bypasses_ollama_when_confident(monkeypatch):
    """Confident prompt returns message without touching requests/embed."""
    sys.path.insert(0, str(Path.home() / ".agents" / "skills" / "route" / "scripts"))
    import route  # noqa: E402

    def no_requests(url, json, timeout):
        raise AssertionError("requests.post should not be called in fast path")

    monkeypatch.setattr("requests.post", no_requests)

    prompt = "fix the bug in utils.py and refactor and debug the error"
    result = arh.classify(prompt)
    assert result is not None
    assert "coding" in result.lower()


def test_slow_path_still_keyword_falls_back_when_ollama_down_and_keyword_unconfident(monkeypatch):
    """Unconfident prompt still reaches keyword-fallback path unchanged."""
    sys.path.insert(0, str(Path.home() / ".agents" / "skills" / "route" / "scripts"))
    import route  # noqa: E402

    fallback_called = {}

    def track_fallback(prompt):
        fallback_called["called"] = True
        return "architecture"

    monkeypatch.setattr(arh, "_resolve_intent", track_fallback)

    prompt = "hello world"  # No strong keyword signal
    result = arh.classify(prompt)
    assert fallback_called.get("called") is True
    assert result is None
