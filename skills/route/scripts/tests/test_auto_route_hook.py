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
    out = _run_main(monkeypatch, {"session_id": "s1", "prompt": "fix the bug"}, capsys)
    assert "coding" in out
    assert arh._already_fired("s1") is True


def test_main_is_silent_on_second_message_same_session(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")
    monkeypatch.setattr(arh, "classify", lambda prompt: "This looks like a **coding** task.")
    _run_main(monkeypatch, {"session_id": "s1", "prompt": "fix the bug"}, capsys)
    out = _run_main(monkeypatch, {"session_id": "s1", "prompt": "now also do this"}, capsys)
    assert out == ""


def test_main_marks_fired_even_when_classify_is_silent(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")
    monkeypatch.setattr(arh, "classify", lambda prompt: None)
    out = _run_main(monkeypatch, {"session_id": "s1", "prompt": "should we redesign this"}, capsys)
    assert out == ""
    assert arh._already_fired("s1") is True


def test_main_is_silent_and_does_not_crash_when_classify_raises(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")

    def raise_err(prompt):
        raise RuntimeError("ollama unreachable")

    monkeypatch.setattr(arh, "classify", raise_err)
    out = _run_main(monkeypatch, {"session_id": "s1", "prompt": "fix the bug"}, capsys)
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


# ── #560: the real UserPromptSubmit payload shape ──────────────────────────
# Claude Code sends the text as "prompt" (code.claude.com/docs/en/hooks,
# UserPromptSubmit input). The hook read "user_prompt" and so returned before
# classifying on every real prompt since 2026-08-13.

def _real_payload(prompt, session_id="0b9f3c1e-real-session"):
    return {
        "session_id": session_id,
        "prompt_id": "6f1d2a7c-0000-4000-8000-000000000000",
        "transcript_path": "/Users/x/.claude/projects/-Users-x/0b9f3c1e.jsonl",
        "cwd": "/Users/x",
        "permission_mode": "default",
        "hook_event_name": "UserPromptSubmit",
        "prompt": prompt,
    }


def _offline_classifier(monkeypatch):
    """Use the real route.py, with the embedding service reported down so the
    real keyword classifier answers: deterministic, no Ollama needed."""
    import route
    monkeypatch.setattr(route.intent_classify, "classify",
                        lambda text: {"status": "unavailable", "intent": None, "score": None})


def test_real_payload_produces_a_suggestion_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")
    _offline_classifier(monkeypatch)
    out = _run_main(monkeypatch, _real_payload(
        "do you remember what we decided last session about the handoff?"), capsys)
    assert "claude-recall" in out
    assert arh._already_fired("0b9f3c1e-real-session") is True


def test_legacy_user_prompt_key_is_still_read(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")
    monkeypatch.setattr(arh, "classify", lambda prompt: "msg for " + prompt)
    out = _run_main(monkeypatch, {"session_id": "s1", "user_prompt": "hello"}, capsys)
    assert "msg for hello" in out


def test_prompt_key_wins_over_legacy_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")
    monkeypatch.setattr(arh, "classify", lambda prompt: "msg for " + prompt)
    out = _run_main(monkeypatch, {"session_id": "s1", "prompt": "new", "user_prompt": "old"}, capsys)
    assert "msg for new" in out


def test_empty_prompt_is_silent_and_not_marked(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")
    monkeypatch.setattr(arh, "classify", lambda prompt: "should not appear")
    for empty in ("", "   \n\t "):
        assert _run_main(monkeypatch, _real_payload(empty), capsys) == ""
    # an empty first prompt must not use up the session's one suggestion
    assert arh._already_fired("0b9f3c1e-real-session") is False


def test_non_string_prompt_is_silent(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")
    monkeypatch.setattr(arh, "classify", lambda prompt: "should not appear")
    for bad in (None, 42, ["a"], {"text": "x"}):
        assert _run_main(monkeypatch, _real_payload(bad), capsys) == ""


def test_payload_that_is_not_an_object_is_silent(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")
    for raw in ("[1, 2]", "\"prompt\"", "null", "", "{\"session_id\": "):
        monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
        arh.main()
        assert capsys.readouterr().out == ""


def test_huge_prompt_is_capped_before_classifying(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")
    seen = []
    monkeypatch.setattr(arh, "_resolve_intent", lambda prompt: seen.append(prompt) or "recall")
    huge = "fix the bug " * 500_000  # ~6 MB
    out = _run_main(monkeypatch, _real_payload(huge), capsys)
    assert "claude-recall" in out
    assert len(seen[0]) <= arh.MAX_PROMPT_CHARS


def test_huge_prompt_real_classifier(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(arh, "STATE_FILE", tmp_path / "auto-route-state.json")
    _offline_classifier(monkeypatch)
    out = _run_main(monkeypatch, _real_payload("do you remember what we decided last session " * 200_000), capsys)
    assert "claude-recall" in out


def test_unwritable_state_file_still_fails_open(tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "a-file"
    blocker.write_text("")
    monkeypatch.setattr(arh, "STATE_FILE", blocker / "sub" / "state.json")  # parent is a file
    monkeypatch.setattr(arh, "classify", lambda prompt: "still suggested")
    out = _run_main(monkeypatch, _real_payload("anything"), capsys)
    assert "still suggested" in out


# ── messages come from route.py, the one routing table ─────────────────────

def test_messages_are_derived_from_route_intents():
    import route
    for intent in ("recall", "coding", "research"):
        cfg = route.INTENTS[intent]
        assert cfg["alias"] in arh.messages()[intent]
        assert cfg["savings"] in arh.messages()[intent]
    assert "architecture" not in arh.messages()


# ── state file: bounded and safe across concurrent sessions ────────────────

def test_old_entries_are_pruned_on_write(tmp_path, monkeypatch):
    state = tmp_path / "auto-route-state.json"
    monkeypatch.setattr(arh, "STATE_FILE", state)
    now = 1_800_000_000.0
    state.write_text(json.dumps({"stale": now - 2 * 86400, "fresh": now - 60}))
    arh._mark_fired("new", now=now)
    data = json.loads(state.read_text())
    assert set(data) == {"fresh", "new"}


def test_legacy_true_values_are_pruned_not_kept_forever(tmp_path, monkeypatch):
    state = tmp_path / "auto-route-state.json"
    monkeypatch.setattr(arh, "STATE_FILE", state)
    state.write_text(json.dumps({"old-format": True, "junk": "x"}))
    arh._mark_fired("new", now=1_800_000_000.0)
    assert set(json.loads(state.read_text())) == {"new"}


def test_non_dict_state_file_counts_as_not_fired_and_is_repaired(tmp_path, monkeypatch):
    state = tmp_path / "auto-route-state.json"
    state.write_text("[1, 2, 3]")
    monkeypatch.setattr(arh, "STATE_FILE", state)
    assert arh._already_fired("s1") is False
    arh._mark_fired("s1")
    assert arh._already_fired("s1") is True


def test_concurrent_sessions_do_not_lose_each_others_marks(tmp_path, monkeypatch):
    import multiprocessing as mp
    state = tmp_path / "auto-route-state.json"
    ctx = mp.get_context("fork")
    procs = [ctx.Process(target=_mark_in_child, args=(str(state), f"s{i}")) for i in range(24)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
    data = json.loads(state.read_text())
    assert set(data) == {f"s{i}" for i in range(24)}


def _mark_in_child(path, sid):
    arh.STATE_FILE = Path(path)
    arh._mark_fired(sid)


def test_hook_script_exits_zero_on_garbage_stdin(tmp_path):
    import subprocess
    script = SCRIPTS / "auto_route_hook.py"
    for raw in (b"", b"not json", b"\xff\xfe\x00", b"[]"):
        r = subprocess.run([sys.executable, str(script)], input=raw, capture_output=True,
                           env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}, timeout=60)
        assert r.returncode == 0, r.stderr
        assert r.stdout == b""
