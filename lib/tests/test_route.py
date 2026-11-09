"""Tests for route.py's --embed flag and keyword-classifier fallback. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_route.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

ROUTE_SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "route" / "scripts"
sys.path.insert(0, str(ROUTE_SCRIPTS))

import route  # noqa: E402


# ── resolve_intent: default behavior is unchanged (no --embed) ─────────────

def test_resolve_intent_uses_keyword_classifier_by_default(monkeypatch):
    monkeypatch.setattr(route, "classify", lambda desc: ("research", 3))

    def _should_not_be_called(desc):
        raise AssertionError("intent_classify.classify must not run without --embed")

    monkeypatch.setattr(route.intent_classify, "classify", _should_not_be_called)

    result = route.resolve_intent("what is the state of the art in RAG", use_embed=False)
    assert result == ("research", 3, "keyword")


# ── resolve_intent: --embed wiring ──────────────────────────────────────────

def test_resolve_intent_uses_embedding_classifier_when_flag_set(monkeypatch):
    monkeypatch.setattr(
        route.intent_classify, "classify",
        lambda desc: {"status": "ok", "intent": "coding", "score": 0.71},
    )
    result = route.resolve_intent("fix the bug in the parser", use_embed=True)
    assert result == ("coding", 0.71, "embed")


def test_resolve_intent_falls_back_to_keyword_when_embedding_unavailable(monkeypatch):
    monkeypatch.setattr(
        route.intent_classify, "classify",
        lambda desc: {"status": "unavailable", "intent": None, "score": None},
    )
    monkeypatch.setattr(route, "classify", lambda desc: ("research", 3))

    result = route.resolve_intent("what is the state of the art in RAG", use_embed=True)
    assert result == ("research", 3, "keyword-fallback")


def test_resolve_intent_falls_back_to_default_intent_on_no_match(monkeypatch):
    monkeypatch.setattr(
        route.intent_classify, "classify",
        lambda desc: {"status": "no_match", "intent": None, "score": 0.1},
    )
    result = route.resolve_intent("uh, hello", use_embed=True)
    assert result == (route.DEFAULT_INTENT, 0, "embed")


# ── CLI wiring: embedding classifier is now the default (ADR 0023 flip,
# 2026-08-13, validated by bench/RESULTS.md Run 21's 70% held-out result);
# --keyword opts back into the old keyword classifier. ──────────────────────

def test_keyword_flag_is_registered_and_defaults_to_false():
    ap = route._build_arg_parser()
    args = ap.parse_args(["fix the bug"])
    assert args.keyword is False

    args = ap.parse_args(["fix the bug", "--keyword"])
    assert args.keyword is True


def test_use_embed_defaults_to_true_without_the_keyword_flag():
    ap = route._build_arg_parser()
    args = ap.parse_args(["fix the bug"])
    assert route._use_embed(args) is True


def test_use_embed_is_false_when_keyword_flag_is_set():
    ap = route._build_arg_parser()
    args = ap.parse_args(["fix the bug", "--keyword"])
    assert route._use_embed(args) is False


# ── skill_allowed: model-scope checking ────────────────────────────────────────

def test_skill_allowed_with_no_manifest_returns_true():
    """Unknown skill (no manifest) returns True (fail open)."""
    result = route.skill_allowed("unknown-skill", "haiku", manifest={})
    assert result is True


def test_skill_allowed_checks_model_scope_field():
    """skill_allowed checks model-scope field for a skill."""
    manifest = {
        "index": [
            {"name": "skill1", "model-scope": "sonnet+"},
            {"name": "skill2", "model-scope": "haiku,sonnet"},
            {"name": "skill3", "model-scope": ""},
        ]
    }

    # skill1 (sonnet+) allowed on sonnet and opus, not haiku
    assert route.skill_allowed("skill1", "haiku", manifest) is False
    assert route.skill_allowed("skill1", "sonnet", manifest) is True
    assert route.skill_allowed("skill1", "opus", manifest) is True

    # skill2 (haiku,sonnet) allowed on haiku and sonnet, not opus
    assert route.skill_allowed("skill2", "haiku", manifest) is True
    assert route.skill_allowed("skill2", "sonnet", manifest) is True
    assert route.skill_allowed("skill2", "opus", manifest) is False

    # skill3 (no scope) allowed on all
    assert route.skill_allowed("skill3", "haiku", manifest) is True
    assert route.skill_allowed("skill3", "sonnet", manifest) is True
    assert route.skill_allowed("skill3", "opus", manifest) is True


def test_check_skill_cli_flag_is_registered():
    ap = route._build_arg_parser()
    args = ap.parse_args(["--check-skill", "grill-with-docs", "--model", "haiku"])
    assert args.check_skill == "grill-with-docs"
    assert args.model == "haiku"


# ── recall stays on the session model (PR #1125 decision recall-model) ─────────
# Run 31: Haiku went 0/3 on the knowledge-base question because it never invoked the skill.

def test_recall_routes_to_the_session_model_not_haiku():
    assert route.INTENTS["recall"]["model"] is None
    assert "--model" not in route._launch_cmd("recall")


def test_research_still_routes_to_haiku():
    assert "haiku" in route.INTENTS["research"]["model"]


# ── launch_model: route at launch, confident cases only (PR #1125 decision routing A) ──

def _embed(monkeypatch, result):
    calls = []

    def fake(desc):
        calls.append(desc)
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(route.intent_classify, "classify", fake)
    return calls


def test_launch_model_goes_through_the_lazy_loader(monkeypatch):
    """#1185: launch_model called the bare global `intent_classify`, which only the module __getattr__ serves
    (outside access, never a lookup inside the module). The NameError was swallowed and nothing ever routed.
    Patch the loader itself, not `route.intent_classify`, so a bare-global call fails here."""
    class Fake:
        @staticmethod
        def classify(desc):
            return {"status": "ok", "intent": "research", "score": 0.9}
    monkeypatch.setattr(route, "_intent_classify", lambda: Fake)
    assert route.launch_model("explain how prompt caching works") == ("research", route.INTENTS["research"]["model"])


def test_launch_model_sends_a_confident_research_prompt_to_haiku(monkeypatch):
    _embed(monkeypatch, {"status": "ok", "intent": "research", "score": 0.8})
    intent, model = route.launch_model("explain how prompt caching works")
    assert intent == "research" and model == route.INTENTS["research"]["model"]


def test_launch_model_keeps_recall_on_the_session_model(monkeypatch):
    _embed(monkeypatch, {"status": "ok", "intent": "recall", "score": 0.9})
    assert route.launch_model("what did we decide last session") == ("recall", None)


def test_launch_model_keeps_coding_and_architecture_on_the_session_model(monkeypatch):
    for intent in ("coding", "architecture"):
        _embed(monkeypatch, {"status": "ok", "intent": intent, "score": 0.9})
        assert route.launch_model("anything") == (intent, None)


def test_launch_model_does_not_route_on_the_keyword_fallback(monkeypatch):
    """Keyword scored 25% held-out (Run 21): not confident enough to change a model."""
    _embed(monkeypatch, {"status": "unavailable", "intent": None, "score": None})
    intent, model = route.launch_model("research the state of the art, explain the literature overview")
    assert model is None


def test_launch_model_does_not_route_on_no_match(monkeypatch):
    _embed(monkeypatch, {"status": "no_match", "intent": None, "score": 0.1})
    assert route.launch_model("uh, hello")[1] is None


def test_launch_model_fails_safe_when_the_classifier_crashes(monkeypatch):
    _embed(monkeypatch, RuntimeError("chroma is down"))
    assert route.launch_model("explain RAG") == (route.DEFAULT_INTENT, None)


def test_launch_model_fails_safe_on_malformed_classifier_output(monkeypatch):
    for bad in (None, "research", {"status": "ok", "intent": "not-an-intent", "score": 1}, {"status": "ok"}):
        _embed(monkeypatch, bad)
        assert route.launch_model("explain RAG")[1] is None


def test_launch_model_ignores_empty_and_non_text_prompts(monkeypatch):
    calls = _embed(monkeypatch, {"status": "ok", "intent": "research", "score": 0.9})
    for bad in ("", "   \n", None, 42):
        assert route.launch_model(bad) == (route.DEFAULT_INTENT, None)
    assert calls == []


def test_launch_model_classifies_only_the_opening_of_a_huge_paste(monkeypatch):
    calls = _embed(monkeypatch, {"status": "ok", "intent": "research", "score": 0.9})
    route.launch_model("explain " + "x" * 1_000_000)
    assert len(calls[0]) <= route.MAX_ROUTE_CHARS


# ── ask_command: the argv `marvin-ask` execs ─────────────────────────────────

def test_ask_command_adds_the_routed_model(monkeypatch):
    monkeypatch.setattr(route, "launch_model", lambda p: ("research", "claude-haiku-x"))
    cmd = route.ask_command("explain RAG", claude="claude")
    assert cmd[:3] == ["claude", "--model", "claude-haiku-x"]
    assert cmd[-1] == "explain RAG"


def test_ask_command_leaves_the_model_alone_when_not_routed(monkeypatch):
    monkeypatch.setattr(route, "launch_model", lambda p: ("recall", None))
    assert "--model" not in route.ask_command("what did we decide", claude="claude")


def test_ask_command_passes_a_hostile_prompt_as_one_argument_never_a_flag(monkeypatch):
    monkeypatch.setattr(route, "launch_model", lambda p: ("architecture", None))
    prompt = "--dangerously-skip-permissions\n$(rm -rf ~) 'quoted' \"x\""
    cmd = route.ask_command(prompt, claude="claude")
    assert cmd[-1] == prompt and cmd[-2] == "--"
    assert cmd.count(prompt) == 1


def test_ask_command_refuses_an_empty_question():
    import pytest
    with pytest.raises(ValueError):
        route.ask_command("  ", claude="claude")


def test_ask_cli_flag_is_registered():
    args = route._build_arg_parser().parse_args(["--ask", "explain RAG"])
    assert args.ask is True and args.task == "explain RAG"


def test_marvin_ask_wrapper_exists_and_calls_route_ask():
    wrapper = Path(__file__).resolve().parents[2] / "bin" / "marvin-ask"
    text = wrapper.read_text()
    assert wrapper.stat().st_mode & 0o111
    assert "route.py" in text and "--ask" in text and '"$*"' in text
