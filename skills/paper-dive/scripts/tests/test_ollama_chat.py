"""Tests for ollama_chat.py options parameter. Run via:
    ~/.agents/venv/bin/python -m pytest scripts/tests/test_ollama_chat.py -v
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import pytest
from ollama_chat import ollama_chat


def test_ollama_chat_basic():
    """Test basic call without options."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "message": {"content": "test response"}
        }).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = ollama_chat("test-model", [{"role": "user", "content": "hi"}])
        assert result == "test response"


def test_ollama_chat_with_options():
    """Test call with options parameter — options go into nested options dict."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "message": {"content": "test response"}
        }).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = ollama_chat(
            "test-model",
            [{"role": "user", "content": "hi"}],
            options={"temperature": 0.5, "num_predict": 100}
        )
        assert result == "test response"

        # Verify the options were included in the nested options dict
        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]
        payload = json.loads(request_obj.data.decode())
        assert "options" in payload
        assert payload["options"]["temperature"] == 0.5
        assert payload["options"]["num_predict"] == 100
        assert payload["model"] == "test-model"
        assert payload["stream"] is False


def test_ollama_chat_options_none():
    """Test that None options doesn't break anything."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "message": {"content": "test response"}
        }).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = ollama_chat(
            "test-model",
            [{"role": "user", "content": "hi"}],
            options=None
        )
        assert result == "test response"

        # Verify no extra fields in payload
        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]
        payload = json.loads(request_obj.data.decode())
        assert "temperature" not in payload
        assert payload["model"] == "test-model"


def test_ollama_chat_options_nested():
    """Test that custom options go into the nested options dict, not top level."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "message": {"content": "test response"}
        }).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = ollama_chat(
            "test-model",
            [{"role": "user", "content": "hi"}],
            options={"custom_field": "custom_value"}
        )
        assert result == "test response"

        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]
        payload = json.loads(request_obj.data.decode())
        # Custom fields go in nested options dict, not top level
        assert "options" in payload
        assert payload["options"]["custom_field"] == "custom_value"
        assert payload["model"] == "test-model"
        assert payload["stream"] is False
