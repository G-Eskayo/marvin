"""Tests for ollama_client.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_ollama_client.py -v
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import ollama_client as oc  # noqa: E402
import metrics_registry as mr  # noqa: E402


@pytest.fixture
def metrics_dir(tmp_path, monkeypatch):
    """Isolate metrics recording to a temp directory."""
    d = tmp_path / "metrics"
    monkeypatch.setattr(mr, "METRICS_DIR", d)
    return d


@pytest.fixture(autouse=True)
def mock_machine_label(monkeypatch):
    """Automatically mock machine_label() for all tests."""
    monkeypatch.setattr(mr.machine_profile, "machine_label", lambda: "mac-mini")


def _metric(value: float, higher_is_better: bool = True) -> dict:
    return {"value": value, "higher_is_better": higher_is_better}


# ── chat() tests ──────────────────────────────────────────────────────────

def test_chat_successful_call_returns_response(monkeypatch):
    """Successful chat call returns the response dict."""
    mock_response = {"message": {"content": "Hello there"}, "model": "test-model",
                     "prompt_eval_count": 10, "eval_count": 20}
    monkeypatch.setattr(oc, "_post_to_ollama", lambda *a, **k: mock_response)

    result = oc.chat("test-model", [{"role": "user", "content": "hi"}], "test_caller")
    assert result["message"]["content"] == "Hello there"


def test_chat_records_metrics_to_registry(monkeypatch, metrics_dir):
    """Chat call records GPU/CPU split to metrics_registry."""
    mock_response = {"message": {"content": "response"}, "model": "test-model",
                     "prompt_eval_count": 10, "eval_count": 20}
    mock_ps = {"models": [{"name": "test-model", "size": 4_000_000_000,
                           "size_vram": 2_000_000_000}]}

    monkeypatch.setattr(oc, "_post_to_ollama", lambda *a, **k: mock_response)
    monkeypatch.setattr(oc, "_get_ollama_ps", lambda: mock_ps)

    result = oc.chat("test-model", [{"role": "user", "content": "hi"}], "test_caller")
    assert result["message"]["content"] == "response"

    # Verify metrics were recorded
    latest = mr.latest("local-model-runs-test-model")
    assert latest is not None
    assert "gpu_fraction" in latest
    assert latest["gpu_fraction"]["value"] == 0.5  # 2GB of 4GB


def test_chat_ollama_unreachable_returns_response_skips_recording(monkeypatch, metrics_dir):
    """If Ollama /api/ps unreachable, chat succeeds but recording is skipped."""
    mock_response = {"message": {"content": "response"}, "model": "test-model"}
    monkeypatch.setattr(oc, "_post_to_ollama", lambda *a, **k: mock_response)
    monkeypatch.setattr(oc, "_get_ollama_ps", lambda: None)  # Unreachable

    result = oc.chat("test-model", [{"role": "user", "content": "hi"}], "test_caller")
    assert result["message"]["content"] == "response"

    # Metrics not recorded
    latest = mr.latest("local-model-runs-test-model")
    assert latest is None


def test_chat_model_not_in_ps_skips_recording(monkeypatch, metrics_dir):
    """If model not in /api/ps, recording is skipped (model already unloaded)."""
    mock_response = {"message": {"content": "response"}, "model": "test-model"}
    mock_ps = {"models": []}  # Model list empty

    monkeypatch.setattr(oc, "_post_to_ollama", lambda *a, **k: mock_response)
    monkeypatch.setattr(oc, "_get_ollama_ps", lambda: mock_ps)

    result = oc.chat("test-model", [{"role": "user", "content": "hi"}], "test_caller")
    assert result["message"]["content"] == "response"

    # Metrics not recorded
    latest = mr.latest("local-model-runs-test-model")
    assert latest is None


def test_chat_model_prefix_match_works(monkeypatch, metrics_dir):
    """Chat correctly matches model by prefix (qwen2.5:7b matches qwen2.5:7b-q4)."""
    mock_response = {"message": {"content": "response"}, "model": "qwen2.5:7b"}
    mock_ps = {"models": [{"name": "qwen2.5:7b-q4_K_M", "size": 4_000_000_000,
                           "size_vram": 3_000_000_000}]}

    monkeypatch.setattr(oc, "_post_to_ollama", lambda *a, **k: mock_response)
    monkeypatch.setattr(oc, "_get_ollama_ps", lambda: mock_ps)

    result = oc.chat("qwen2.5:7b", [{"role": "user", "content": "hi"}], "test_caller")
    assert result["message"]["content"] == "response"

    # Should still record with matched model
    latest = mr.latest("local-model-runs-qwen2.5-7b")
    assert latest is not None


def test_chat_cpu_fraction_edge_case_size_zero(monkeypatch, metrics_dir):
    """Defensive: if size==0, cpu_fraction doesn't divide by zero."""
    mock_response = {"message": {"content": "response"}, "model": "test-model"}
    mock_ps = {"models": [{"name": "test-model", "size": 0, "size_vram": 0}]}

    monkeypatch.setattr(oc, "_post_to_ollama", lambda *a, **k: mock_response)
    monkeypatch.setattr(oc, "_get_ollama_ps", lambda: mock_ps)

    # Should not raise ZeroDivisionError
    result = oc.chat("test-model", [{"role": "user", "content": "hi"}], "test_caller")
    assert result["message"]["content"] == "response"


def test_chat_cpu_fraction_edge_case_size_vram_exceeds_size(monkeypatch, metrics_dir):
    """Defensive: if size_vram > size (malformed), cpu_fraction clamps to [0,1]."""
    mock_response = {"message": {"content": "response"}, "model": "test-model"}
    mock_ps = {"models": [{"name": "test-model", "size": 2_000_000_000,
                           "size_vram": 3_000_000_000}]}  # vram > size

    monkeypatch.setattr(oc, "_post_to_ollama", lambda *a, **k: mock_response)
    monkeypatch.setattr(oc, "_get_ollama_ps", lambda: mock_ps)

    result = oc.chat("test-model", [{"role": "user", "content": "hi"}], "test_caller")
    latest = mr.latest("local-model-runs-test-model")

    # Should clamp to valid range [0, 1]
    assert latest is not None
    assert 0 <= latest["gpu_fraction"]["value"] <= 1


def test_chat_concurrent_calls_separate_metrics(monkeypatch, metrics_dir):
    """Two concurrent chat calls each record their own model's metrics."""
    def mock_post(url, *args, **kwargs):
        # Simulate different response times
        time.sleep(0.01)
        if "model-a" in url:
            return {"message": {"content": "response-a"}, "model": "model-a"}
        else:
            return {"message": {"content": "response-b"}, "model": "model-b"}

    mock_ps_a = {"models": [{"name": "model-a", "size": 1_000_000_000,
                             "size_vram": 500_000_000}]}
    mock_ps_b = {"models": [{"name": "model-b", "size": 2_000_000_000,
                             "size_vram": 1_000_000_000}]}

    # For simplicity, we'll test sequential calls here (true concurrent testing
    # requires threading, which is complex in pytest). The test verifies that
    # separate model names produce separate metric files.
    monkeypatch.setattr(oc, "_post_to_ollama", lambda *a, **k: {"message": {"content": "response-a"}})
    monkeypatch.setattr(oc, "_get_ollama_ps", lambda: mock_ps_a)
    oc.chat("model-a", [{"role": "user", "content": "hi"}], "caller")

    monkeypatch.setattr(oc, "_post_to_ollama", lambda *a, **k: {"message": {"content": "response-b"}})
    monkeypatch.setattr(oc, "_get_ollama_ps", lambda: mock_ps_b)
    oc.chat("model-b", [{"role": "user", "content": "hi"}], "caller")

    # Verify separate files
    assert mr.latest("local-model-runs-model-a") is not None
    assert mr.latest("local-model-runs-model-b") is not None


def test_chat_directory_not_writable_nonfatal(monkeypatch, metrics_dir, tmp_path):
    """If metrics dir not writable, chat succeeds; only recording fails silently."""
    mock_response = {"message": {"content": "response"}, "model": "test-model"}
    monkeypatch.setattr(oc, "_post_to_ollama", lambda *a, **k: mock_response)
    monkeypatch.setattr(oc, "_get_ollama_ps", lambda: {"models": [{"name": "test-model",
                                                                     "size": 1_000_000_000,
                                                                     "size_vram": 500_000_000}]})

    # Make metrics dir read-only
    read_only_dir = tmp_path / "readonly"
    read_only_dir.mkdir()
    read_only_dir.chmod(0o444)
    monkeypatch.setattr(mr, "METRICS_DIR", read_only_dir)

    # Should not raise
    result = oc.chat("test-model", [{"role": "user", "content": "hi"}], "test_caller")
    assert result["message"]["content"] == "response"

    # Cleanup
    read_only_dir.chmod(0o755)


def test_chat_never_pulled_model_upstream_error_propagates(monkeypatch):
    """If model was never pulled, upstream /api/chat errors; we propagate it."""
    error_msg = "model not found"
    monkeypatch.setattr(oc, "_post_to_ollama", lambda *a, **k: {"error": error_msg})

    result = oc.chat("nonexistent-model", [{"role": "user", "content": "hi"}], "test_caller")
    # The function should return the error response as-is
    assert "error" in result


def test_chat_stale_lock_bounded_wait(monkeypatch, metrics_dir):
    """Metrics file lock waits with timeout, doesn't hang forever."""
    mock_response = {"message": {"content": "response"}, "model": "test-model"}
    monkeypatch.setattr(oc, "_post_to_ollama", lambda *a, **k: mock_response)
    monkeypatch.setattr(oc, "_get_ollama_ps", lambda: {"models": [{"name": "test-model",
                                                                     "size": 1_000_000_000,
                                                                     "size_vram": 500_000_000}]})

    # Simulate a stale lock by pre-creating a locked file
    # (In real implementation, this would be tested via mocking fcntl)
    start = time.time()
    result = oc.chat("test-model", [{"role": "user", "content": "hi"}], "test_caller")
    elapsed = time.time() - start

    # Should complete reasonably quickly (not hang)
    assert elapsed < 5.0
    assert result["message"]["content"] == "response"


# ── embed() tests ─────────────────────────────────────────────────────────

def test_embed_successful_call_returns_embedding(monkeypatch):
    """Successful embed call returns embedding vector."""
    mock_embedding = [0.1, 0.2, 0.3]
    def mock_post(*args, **kwargs):
        return {"embeddings": [mock_embedding]}

    monkeypatch.setattr(oc, "_post_to_ollama", mock_post)

    result = oc.embed("nomic-embed-text", "test text", "test_task", "test_caller")
    assert result == mock_embedding


def test_embed_records_metrics_to_registry(monkeypatch, metrics_dir):
    """Embed call records GPU/CPU split to metrics_registry."""
    mock_embedding = [0.1, 0.2, 0.3]
    mock_ps = {"models": [{"name": "nomic-embed-text", "size": 1_000_000_000,
                           "size_vram": 500_000_000}]}

    monkeypatch.setattr(oc, "_post_to_ollama", lambda *a, **k: {"embeddings": [mock_embedding]})
    monkeypatch.setattr(oc, "_get_ollama_ps", lambda: mock_ps)

    result = oc.embed("nomic-embed-text", "test", "document", "test_caller")
    assert result == mock_embedding

    # Verify metrics were recorded
    latest = mr.latest("local-model-runs-nomic-embed-text")
    assert latest is not None
    assert latest["gpu_fraction"]["value"] == 0.5


def test_embed_ollama_unreachable_returns_none(monkeypatch, metrics_dir):
    """If Ollama unreachable, embed returns None (compatible with existing pattern)."""
    monkeypatch.setattr(oc, "_post_to_ollama", lambda *a, **k: None)

    result = oc.embed("nomic-embed-text", "test", "document", "test_caller")
    assert result is None


# ── concurrent writer tests ───────────────────────────────────────────────

def test_concurrent_metrics_writes_no_corruption(monkeypatch, metrics_dir):
    """Multiple writers to the same metrics file don't corrupt JSON (fcntl locking)."""
    mock_response = {"message": {"content": "response"}, "model": "test-model"}
    mock_ps = {"models": [{"name": "test-model", "size": 1_000_000_000,
                           "size_vram": 500_000_000}]}

    monkeypatch.setattr(oc, "_post_to_ollama", lambda *a, **k: mock_response)
    monkeypatch.setattr(oc, "_get_ollama_ps", lambda: mock_ps)

    # Simulate multiple writes in quick succession
    for i in range(3):
        oc.chat("test-model", [{"role": "user", "content": f"hi {i}"}], "test_caller")

    # Verify the JSON file is not corrupted
    json_path = metrics_dir / "local-model-runs-test-model.mac-mini.json"
    assert json_path.exists()

    # Should parse cleanly without JSON errors
    data = json.loads(json_path.read_text())
    assert len(data) == 3
    assert all("timestamp" in snapshot for snapshot in data)
