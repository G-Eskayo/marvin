#!/usr/bin/env python3
"""Shared Ollama API client consolidating duplicated call patterns from 6+ scripts.

Wraps /api/chat (chat()) and /api/embed (embed()) calls with automatic GPU/CPU split
tracking via /api/ps snapshot. Records each call to metrics_registry under
local-model-runs-{model_name} for dashboard visibility.

Replaces hand-rolled ollama_chat() in:
  - skills/paper-dive/scripts/logic_auditor.py
  - skills/paper-dive/scripts/continuity_checker.py
  - skills/paper-dive/scripts/argument_mapper.py
  - skills/paper-dive/scripts/competing_ideas.py
  - lib/intent_classify.py (embed_text)
  - skills/self-improve/scripts/retrieve.py (embed calls)

Design: thin wrapper around urllib (no requests import), silent degradation on
Ollama unreachable (recording skipped, call succeeds), fcntl-locked metrics writes.
"""
from __future__ import annotations
import fcntl
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics_registry as mr  # noqa: E402

OLLAMA_BASE = "http://localhost:11434"


def _post_to_ollama(url: str, payload: dict, timeout: int = 60) -> dict | None:
    """POST to Ollama endpoint, return JSON response or None if unreachable."""
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _get_ollama_ps() -> dict | None:
    """GET /api/ps to query currently-loaded models. Returns {"models": [...]}, or None."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/ps", timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _find_model_in_ps(model_name: str, ps_data: dict) -> dict | None:
    """Find matching model entry in /api/ps by exact name or prefix match (e.g. qwen2.5:7b).

    Prefix match mirrors bench.py's convention: 'qwen2.5:7b' matches 'qwen2.5:7b-q4_K_M'.
    Returns the full model dict from /api/ps, or None if not found.
    """
    if not ps_data or "models" not in ps_data:
        return None

    for entry in ps_data["models"]:
        if entry["name"] == model_name:
            return entry
        # Prefix match on the part before colon
        model_base = model_name.split(":")[0]
        if entry["name"].startswith(model_base):
            return entry

    return None


def _compute_cpu_fraction(size: int, size_vram: int) -> float:
    """Compute CPU fallback fraction: (total_size - vram) / total_size.

    Defensive: returns 1.0 if size==0, clamps result to [0, 1].
    """
    if size <= 0:
        return 1.0  # Treat as 100% CPU if no size info

    cpu_bytes = max(0, size - size_vram)
    fraction = cpu_bytes / size
    return max(0.0, min(1.0, fraction))


def _record_gpu_split(model_name: str, ps_entry: dict) -> None:
    """Record GPU/CPU split to metrics_registry. Silent failure if recording fails."""
    try:
        size = ps_entry.get("size", 0)
        size_vram = ps_entry.get("size_vram", 0)

        cpu_frac = _compute_cpu_fraction(size, size_vram)
        gpu_frac = 1.0 - cpu_frac

        # Subsystem name: local-model-runs-{model_name}, with colons replaced
        subsystem = f"local-model-runs-{model_name.replace(':', '-')}"

        metrics = {
            "gpu_fraction": {"value": round(gpu_frac, 4), "higher_is_better": True},
            "cpu_fallback": {"value": round(cpu_frac, 4), "higher_is_better": False},
        }

        mr.record(subsystem, metrics)
    except Exception:
        # Silent failure — record errors don't propagate to caller
        pass


def chat(model: str, messages: list[dict], caller: str, timeout: int = 60) -> dict:
    """POST /api/chat with message history.

    Returns the full response dict from Ollama (with message, model, eval counts, etc).
    Records GPU/CPU split to metrics_registry if /api/ps is available and model is loaded.

    Args:
        model: Model name (e.g., "qwen2.5:7b")
        messages: List of {"role": "...", "content": "..."} dicts
        caller: Name of calling code (for logging/tracing)
        timeout: HTTP timeout in seconds (default 60)

    Returns:
        The response dict from Ollama (or error dict if the call failed).
    """
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }

    response = _post_to_ollama(f"{OLLAMA_BASE}/api/chat", payload, timeout=timeout)
    if response is None:
        # Upstream error; return empty response
        return {}

    # Attempt to record GPU split, but don't fail the call if recording fails
    ps_data = _get_ollama_ps()
    if ps_data:
        ps_entry = _find_model_in_ps(model, ps_data)
        if ps_entry:
            _record_gpu_split(model, ps_entry)

    return response


def embed(model: str, text: str, task: str, caller: str, timeout: int = 10) -> list[float] | None:
    """POST /api/embed with asymmetric prefix convention (query vs. document).

    Returns the embedding vector, or None if the call failed/model unreachable.
    Records GPU/CPU split to metrics_registry if /api/ps is available.

    Args:
        model: Model name (e.g., "nomic-embed-text")
        text: Text to embed
        task: "query" or "document" — determines asymmetric prefix (nomic-embed convention)
        caller: Name of calling code (for logging/tracing)
        timeout: HTTP timeout in seconds (default 10)

    Returns:
        The embedding vector as a list of floats, or None if unavailable.
    """
    prefix = "search_query: " if task == "query" else "search_document: "
    payload = {"model": model, "input": f"{prefix}{text}"}

    response = _post_to_ollama(f"{OLLAMA_BASE}/api/embed", payload, timeout=timeout)
    if response is None or "embeddings" not in response:
        return None

    embedding = response["embeddings"][0] if response["embeddings"] else None

    # Attempt to record GPU split
    if embedding:
        ps_data = _get_ollama_ps()
        if ps_data:
            ps_entry = _find_model_in_ps(model, ps_data)
            if ps_entry:
                _record_gpu_split(model, ps_entry)

    return embedding
