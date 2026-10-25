#!/usr/bin/env python3
"""Shared registry of AI models across MARVIN, tracking location, size, usage, and last access.

Schema: config/models.json has two top-level keys:
  - "models": dict[model_name, metadata] with fields: size_gb, location, used_by, reason, last_used, heavy, runtime
  - "capabilities": dict[capability_name, list[model_names]] for grouping by function

New models are registered before download, so the dashboard always knows what's where and how big it is."""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "models.json"


class ModelUnavailableError(Exception):
    """Raised when a capability cannot be resolved to an available model."""
    pass


class ModelRegistry:
    def __init__(self, path: Path = REGISTRY_PATH):
        self.path = Path(path)
        self._ensure_exists()

    def _ensure_exists(self) -> None:
        if not self.path.exists():
            # Load from config/models.json (checked-in source of truth)
            # Falls back to minimal bootstrap only if config file is unavailable
            config_path = Path(__file__).resolve().parents[1] / "config" / "models.json"
            if config_path.exists():
                try:
                    initial = json.loads(config_path.read_text())
                except (OSError, ValueError):
                    initial = self._bootstrap_fallback()
            else:
                initial = self._bootstrap_fallback()

            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._write(initial)

    def _bootstrap_fallback(self) -> dict:
        """Minimal bootstrap if config/models.json is unavailable.

        This should rarely be needed; config/models.json is the source of truth.
        """
        return {
            "models": {
                "qwen2.5:14b": {
                    "size_gb": 9.0,
                    "location": "~/.ollama/models",
                    "used_by": "paper-dive",
                    "reason": "logic auditing, competing ideas, argument mapper",
                    "last_used": None,
                    "heavy": True,
                    "runtime": "ollama",
                },
                "qwen2.5:7b": {
                    "size_gb": 4.7,
                    "location": "~/.ollama/models",
                    "used_by": "paper-dive",
                    "reason": "logic auditing, competing ideas, argument mapper",
                    "last_used": None,
                    "heavy": False,
                    "runtime": "ollama",
                },
                "qwen2.5:3b": {
                    "size_gb": 1.9,
                    "location": "~/.ollama/models",
                    "used_by": "paper-dive",
                    "reason": "logic auditing, competing ideas, argument mapper",
                    "last_used": None,
                    "heavy": False,
                    "runtime": "ollama",
                },
                "nomic-embed-text": {
                    "size_gb": 0.27,
                    "location": "~/.ollama/models",
                    "used_by": "core",
                    "reason": "memory search, routing, embeddings",
                    "last_used": None,
                    "heavy": False,
                    "runtime": "ollama",
                },
                "specter2": {
                    "size_gb": 0.84,
                    "location": "~/.cache/huggingface/models",
                    "used_by": "paper-dive",
                    "reason": "citation graph analysis",
                    "last_used": None,
                    "heavy": False,
                    "runtime": "hf",
                },
                "MiniLM": {
                    "size_gb": 0.17,
                    "location": "~/.cache/chroma",
                    "used_by": "core",
                    "reason": "vector search (Chroma default)",
                    "last_used": None,
                    "heavy": False,
                    "runtime": "hf",
                },
                "llama-3.2-3b-mlx-4bit": {
                    "size_gb": 1.9,
                    "location": "~/.cache/huggingface",
                    "used_by": "exo-test",
                    "reason": "leftover from exo testing",
                    "last_used": None,
                    "heavy": False,
                    "runtime": "mlx",
                },
                "qwen2.5:3b-mlx-4bit": {
                    "size_gb": 1.6,
                    "location": "~/.cache/huggingface",
                    "used_by": "exo-test",
                    "reason": "leftover from exo testing",
                    "last_used": None,
                    "heavy": False,
                    "runtime": "mlx",
                },
                "llama-3.2-1b-mlx-4bit": {
                    "size_gb": 0.02,
                    "location": "~/.cache/huggingface",
                    "used_by": "exo-test",
                    "reason": "leftover from exo testing",
                    "last_used": None,
                    "heavy": False,
                    "runtime": "mlx",
                },
                "FLUX.1-schnell-4bit": {
                    "size_gb": 6.5,
                    "location": "~/.cache/huggingface",
                    "used_by": "portfolio-flux",
                    "reason": "high-quality image generation for portfolio projects",
                    "last_used": None,
                    "heavy": True,
                    "runtime": "flux",
                },
            },
            "capabilities": {
                "local-classify-medium": ["qwen2.5:14b"],
                "local-extract-small": ["qwen2.5:3b"],
                "local-judge-medium": ["qwen2.5:7b"],
                "local-inference-large": ["qwen2.5:14b"],
            },
        }

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def _write(self, registry: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(registry, indent=2, sort_keys=True))
        os.replace(tmp, self.path)

    def register(self, name: str, location: str, size_gb: float, used_by: str, reason: str,
                 heavy: bool = False, runtime: str = "ollama") -> None:
        """Register a model with its metadata. Writes atomically."""
        lock_path = self.path.parent / f".{self.path.name}.lock"
        with open(lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                data = self._read()
                if "models" not in data:
                    data["models"] = {}
                data["models"][name] = {
                    "size_gb": size_gb,
                    "location": location,
                    "used_by": used_by,
                    "reason": reason,
                    "last_used": None,
                    "heavy": heavy,
                    "runtime": runtime,
                }
                self._write(data)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def touch_last_used(self, name: str) -> None:
        """Update the last_used timestamp for a model."""
        lock_path = self.path.parent / f".{self.path.name}.lock"
        with open(lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                data = self._read()
                models = data.get("models", {})
                if name in models:
                    models[name]["last_used"] = datetime.now(timezone.utc).isoformat()
                    self._write(data)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def get(self, name: str) -> dict | None:
        """Get model metadata by name."""
        data = self._read()
        models = data.get("models", {})
        return models.get(name)

    def all(self) -> dict:
        """Get all registered models dict (for backward compat, returns full data structure)."""
        return self._read()


def resolve_capability(name: str, reg: ModelRegistry | None = None) -> list[str]:
    """Look up a capability by name. Returns list of model names.

    Raises KeyError if the capability is unknown (this is intentional —
    programming error, not a runtime recoverable condition).
    """
    if reg is None:
        reg = ModelRegistry()
    data = reg._read()
    capabilities = data.get("capabilities", {})
    if name not in capabilities:
        raise KeyError(f"Unknown capability {name!r}")
    return capabilities[name]


def check_ollama_pulled(model: str, base_url: str = "http://localhost:11434") -> tuple[bool, str]:
    """Check if a model is pulled in Ollama and server is responding.

    Returns (ok, error_message). On success, returns (True, "").
    On failure, returns (False, helpful_error_message).
    """
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=5) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        return False, f"Ollama server not responding ({exc}). Start with: ollama serve"

    if not isinstance(data, dict):
        return False, f"Ollama returned malformed response (not a dict): {type(data)}"

    models_list = data.get("models")
    if not isinstance(models_list, list):
        return False, f"Ollama response 'models' is not a list: {type(models_list)}"

    available = []
    for m in models_list:
        if isinstance(m, dict) and "name" in m:
            available.append(m["name"])

    if not available:
        return False, f"No models available in Ollama. Pull with: ollama pull {model}"

    # Accept exact match or dash-prefixed variant (e.g., "qwen2.5:7b" matches "qwen2.5:7b-instruct-q4_K_M")
    if not any(a == model or a.startswith(f"{model}-") for a in available):
        return False, (f"Model '{model}' not found. Available: {available}\n"
                       f"Pull with: ollama pull {model}")
    return True, ""


def resolve_and_check(
    capability: str,
    confirm_fn=None,
    auto_pull: bool = False,
    reg: ModelRegistry | None = None,
    base_url: str = "http://localhost:11434"
) -> tuple[str, bool]:
    """Lazily resolve a capability to a model, checking if it's available.

    Returns (model_name, is_available).

    If auto_pull=True and model is unavailable:
      - If confirm_fn is provided, calls confirm_fn(prompt) to ask user
      - If confirm_fn returns True, attempts `ollama pull <model>`
      - If confirm_fn is None, auto-skips pulling (confirm_fn must be explicit)

    Raises KeyError if capability is unknown.
    """
    if reg is None:
        reg = ModelRegistry()

    # Resolve the capability to a model name
    models = resolve_capability(capability, reg)
    if not models:
        raise KeyError(f"Capability {capability!r} has no models")

    model = models[0]  # Use first available model

    # Check if model is available
    ok, err = check_ollama_pulled(model, base_url=base_url)
    if ok:
        return model, True

    # Model not available; check if we should pull
    if not auto_pull:
        return model, False

    # auto_pull=True: ask for confirmation if confirm_fn provided
    if confirm_fn is None:
        # No confirmation function, can't pull automatically
        return model, False

    prompt = f"Pull {model}? (will download to ~/.ollama/models)"
    if not confirm_fn(prompt):
        return model, False

    # Attempt to pull the model
    try:
        subprocess.run(
            ["ollama", "pull", model],
            check=True,
            timeout=3600,  # 1 hour timeout for large models
            capture_output=False
        )
        # Re-check availability after pull
        ok, _ = check_ollama_pulled(model, base_url=base_url)
        return model, ok
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return model, False


def resolve_or_raise(
    capability: str,
    confirm_fn=None,
    auto_pull: bool = False,
    reg: ModelRegistry | None = None,
    base_url: str = "http://localhost:11434"
) -> str:
    """Resolve a capability to a model, raising ModelUnavailableError if not available.

    All parameters match resolve_and_check(). Returns just the model name on success.

    Raises:
      - KeyError: if capability is unknown
      - ModelUnavailableError: if model cannot be resolved to an available model
    """
    model, available = resolve_and_check(capability, confirm_fn, auto_pull, reg, base_url)
    if not available:
        raise ModelUnavailableError(f"Model for capability {capability!r} not available: {model}")
    return model


def is_heavy(model_name: str, reg: ModelRegistry | None = None) -> bool:
    """Check if a model is marked as heavy (long-running, needs queue coordination)."""
    if reg is None:
        reg = ModelRegistry()
    meta = reg.get(model_name)
    if meta is None:
        return False
    return meta.get("heavy", False)


def check_consistency(reg: ModelRegistry | None = None) -> dict[str, list[str]]:
    """Validate registry consistency: all capabilities point to registered models,
    all models are well-described. Returns {"hard_errors": [...], "soft_warnings": [...]}."""
    if reg is None:
        reg = ModelRegistry()

    data = reg._read()
    models = data.get("models", {})
    capabilities = data.get("capabilities", {})

    hard_errors = []
    soft_warnings = []

    # Hard error: capability references non-existent model
    for cap_name, model_list in capabilities.items():
        for model_name in model_list:
            if model_name not in models:
                hard_errors.append(f"Capability {cap_name!r} references unknown model {model_name!r}")

    # Soft warning: model with empty used_by or reason
    for model_name, model_data in models.items():
        if not model_data.get("used_by"):
            soft_warnings.append(f"Model {model_name!r} has empty used_by field")
        if not model_data.get("reason"):
            soft_warnings.append(f"Model {model_name!r} has empty reason field")

    return {"hard_errors": hard_errors, "soft_warnings": soft_warnings}


if __name__ == "__main__":
    import sys
    reg = ModelRegistry()
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        print(json.dumps(reg.all(), indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "check":
        result = check_consistency(reg)
        if result["hard_errors"]:
            print("Hard errors found:", file=sys.stderr)
            for err in result["hard_errors"]:
                print(f"  - {err}", file=sys.stderr)
        if result["soft_warnings"]:
            print("Soft warnings:", file=sys.stderr)
            for warn in result["soft_warnings"]:
                print(f"  - {warn}", file=sys.stderr)
        sys.exit(1 if result["hard_errors"] else 0)
    else:
        print(f"Registry at {reg.path}")
