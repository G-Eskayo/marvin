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
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "models.json"


class ModelResolutionError(Exception):
    """Raised when a model cannot be resolved or found."""
    pass


class ModelUnavailableError(ModelResolutionError):
    """Raised when a model is registered but not installed locally."""
    def __init__(self, model: str, size_gb: float | None = None):
        self.model = model
        self.size_gb = size_gb
        if size_gb is None:
            size_str = "unknown size"
        else:
            size_str = f"size: {size_gb} GB"
        msg = f"Model {model} not available locally ({size_str}). Install with: ollama pull {model}"
        super().__init__(msg)


class OllamaUnavailableError(ModelResolutionError):
    """Raised when Ollama is not available to check installed models."""
    def __init__(self, model: str):
        self.model = model
        super().__init__(f"Ollama unavailable; cannot verify {model} is installed")


class ModelRegistry:
    def __init__(self, path: Path = REGISTRY_PATH):
        self.path = Path(path)
        self._ensure_exists()

    def _ensure_exists(self) -> None:
        if not self.path.exists():
            initial = {
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
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._write(initial)

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


def normalize_model_name(model: str) -> str:
    """Normalize a model name for matching. Currently returns as-is; future: strip variants."""
    return model


def model_present(available: list[str], model: str) -> bool:
    """Check if a model is in the available list.

    Returns True if either an exact match is found, or a variant of the model
    (e.g. "qwen2.5:7b-instruct-q4_K_M" for "qwen2.5:7b"), or the model with
    :latest tag appended (Ollama reports untagged pulls as "name:latest").

    Matching rules:
    - Exact match: a == model
    - Tagged variant (model contains ':'): a starts with "{model}-"
      (e.g., "qwen2.5:7b" matches "qwen2.5:7b-instruct")
    - Bare name (model has no ':'): a == "{model}:latest"
      (e.g., "nomic-embed-text" matches "nomic-embed-text:latest")
    """
    for a in available:
        # Exact match
        if a == model:
            return True

        # For models with a tag (contain ':'), check for tag variants
        # e.g., model="qwen2.5:7b", a="qwen2.5:7b-instruct" should match
        if ":" in model and a.startswith(f"{model}-"):
            return True

        # For bare names (no ':'), check for :latest (Ollama convention)
        # e.g., model="nomic-embed-text", a="nomic-embed-text:latest" should match
        if ":" not in model and a == f"{model}:latest":
            return True

    return False


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


def list_installed() -> list[str] | None:
    """Query localhost:11434/api/tags and return list of installed model names.
    Returns None on error (Ollama unavailable or unreachable).

    Tolerant of non-dict responses and entries missing the "name" field."""
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as resp:
            data = json.loads(resp.read())
            if not isinstance(data, dict):
                return None
            models = data.get("models", [])
            if not isinstance(models, list):
                return None
            return [m.get("name") for m in models if isinstance(m, dict) and "name" in m]
    except Exception:
        return None


def ensure_installed(model: str, reg: ModelRegistry | None = None) -> None:
    """Verify that a model is installed locally. Raises OllamaUnavailableError if Ollama
    is unreachable, or ModelUnavailableError if the model is not installed.

    Does not check the registry—only verifies actual installation via /api/tags."""
    installed = list_installed()
    if installed is None:
        raise OllamaUnavailableError(model)

    if not model_present(installed, model):
        if reg is None:
            reg = ModelRegistry()
        meta = reg.get(model)
        size = meta.get("size_gb") if meta else None
        raise ModelUnavailableError(model, size)


def resolve_or_raise(capability: str, reg: ModelRegistry | None = None) -> str:
    """Resolve a capability to a model name and verify it's installed.

    Returns the FIRST (preferred) model for the capability if it's installed.
    Does NOT silently accept later models as fallbacks; the preferred model is
    required. Raises KeyError if the capability is unknown, OllamaUnavailableError
    if Ollama is unreachable, or ModelUnavailableError if the first model for this
    capability is not installed."""
    if reg is None:
        reg = ModelRegistry()

    models = resolve_capability(capability, reg=reg)  # Raises KeyError if unknown

    if not models:
        raise ModelResolutionError(f"Capability {capability!r} has empty model list")

    preferred_model = models[0]

    installed = list_installed()
    if installed is None:
        raise OllamaUnavailableError(preferred_model)

    if model_present(installed, preferred_model):
        return preferred_model

    # Preferred model is not installed
    if reg is None:
        reg = ModelRegistry()
    meta = reg.get(preferred_model)
    size = meta.get("size_gb") if meta else None
    raise ModelUnavailableError(preferred_model, size)


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
