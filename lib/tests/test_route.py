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
