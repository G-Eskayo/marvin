#!/usr/bin/env python3
"""Tests for the selectable synthesis backend (ticket #1414).

The colony digest can be synthesised by the hosted Claude path (default) or by
a local Ollama model, chosen by the COLONY_SYNTH_BACKEND env var. These tests
pin the selector and the Ollama branch's LaunchResult-shaped contract, and —
adversarially — that a dead Ollama fails gracefully instead of crashing the run.
"""
from __future__ import annotations
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path.home() / ".agents" / "lib"))

import research_digest as rd


class TestBackendSelector:
    def test_defaults_to_claude_when_unset(self, monkeypatch):
        monkeypatch.delenv("COLONY_SYNTH_BACKEND", raising=False)
        assert rd._select_backend() == "claude"

    def test_env_selects_ollama(self, monkeypatch):
        monkeypatch.setenv("COLONY_SYNTH_BACKEND", "ollama")
        assert rd._select_backend() == "ollama"

    def test_env_is_case_insensitive_and_trimmed(self, monkeypatch):
        monkeypatch.setenv("COLONY_SYNTH_BACKEND", "  Ollama ")
        assert rd._select_backend() == "ollama"

    def test_unknown_backend_falls_back_to_claude(self, monkeypatch):
        # A typo in the env must never silently route nowhere — keep the budget path.
        monkeypatch.setenv("COLONY_SYNTH_BACKEND", "gpt5")
        assert rd._select_backend() == "claude"


class TestOllamaSynthesis:
    def test_happy_path_returns_launchresult_shape(self):
        posted = {}

        def poster(url, payload, timeout):
            posted["url"] = url
            posted["payload"] = payload
            return {"response": "## Directly Relevant\n**X** — matters. [link]"}

        result = rd._synthesize_ollama("PROMPT", model="qwen2.5:3b", poster=poster, timeout=120)

        assert result.exit_code == 0
        assert "Directly Relevant" in result.text
        assert result.cost_usd == 0.0  # local run is free — must report zero, not None

    def test_sends_model_prompt_and_disables_streaming(self):
        posted = {}

        def poster(url, payload, timeout):
            posted["url"] = url
            posted["payload"] = payload
            return {"response": "ok"}

        rd._synthesize_ollama("THE PROMPT", model="qwen2.5:7b", poster=poster, timeout=99)

        assert posted["url"].endswith("/api/generate")
        assert posted["payload"]["model"] == "qwen2.5:7b"
        assert posted["payload"]["prompt"] == "THE PROMPT"
        assert posted["payload"]["stream"] is False

    def test_empty_response_is_a_failure(self):
        # An empty body downstream becomes a silent no-digest; make it an explicit non-zero exit.
        def poster(url, payload, timeout):
            return {"response": "   "}

        result = rd._synthesize_ollama("PROMPT", model="qwen2.5:3b", poster=poster, timeout=120)
        assert result.exit_code != 0

    def test_missing_response_key_is_a_failure(self):
        def poster(url, payload, timeout):
            return {"error": "model not found"}

        result = rd._synthesize_ollama("PROMPT", model="qwen2.5:3b", poster=poster, timeout=120)
        assert result.exit_code != 0
        assert "model not found" in result.stderr or result.stderr

    def test_connection_error_is_graceful_not_raised(self):
        # Ollama not running must notify-and-return like the Claude path, never crash the colony.
        def poster(url, payload, timeout):
            raise ConnectionRefusedError("connection refused")

        result = rd._synthesize_ollama("PROMPT", model="qwen2.5:3b", poster=poster, timeout=120)
        assert result.exit_code != 0
        assert "connection refused" in result.stderr.lower()
