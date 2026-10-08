#!/usr/bin/env python3
"""Shared registry of AI models across MARVIN, tracking location, size, usage, and last access.

Seeded with the inventory from the image-maker plan (2026-10-08). New models are registered
before download, so the dashboard always knows what's where and how big it is."""
from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "models.json"


class ModelRegistry:
    def __init__(self, path: Path = REGISTRY_PATH):
        self.path = Path(path)
        self._ensure_exists()

    def _ensure_exists(self) -> None:
        if not self.path.exists():
            initial = {
                "qwen2.5:14b": {
                    "size_gb": 9.0,
                    "location": "~/.ollama/models",
                    "used_by": ["paper-dive"],
                    "reason": "logic auditing, competing ideas, argument mapper",
                    "last_used": None,
                    "runtime": "ollama",
                    "machine": "both",
                    "capability": "local-classify-large",
                    "heavy": True,
                },
                "qwen2.5:7b": {
                    "size_gb": 4.7,
                    "location": "~/.ollama/models",
                    "used_by": ["paper-dive"],
                    "reason": "logic auditing, competing ideas, argument mapper",
                    "last_used": None,
                    "runtime": "ollama",
                    "machine": "both",
                    "capability": "local-classify-medium",
                    "heavy": False,
                },
                "qwen2.5:3b": {
                    "size_gb": 1.9,
                    "location": "~/.ollama/models",
                    "used_by": ["paper-dive"],
                    "reason": "logic auditing, competing ideas, argument mapper",
                    "last_used": None,
                    "runtime": "ollama",
                    "machine": "both",
                    "capability": "local-classify-small",
                    "heavy": False,
                },
                "nomic-embed-text": {
                    "size_gb": 0.27,
                    "location": "~/.ollama/models",
                    "used_by": ["core"],
                    "reason": "memory search, routing, embeddings",
                    "last_used": None,
                    "runtime": "ollama",
                    "machine": "both",
                    "capability": "local-embed",
                    "heavy": False,
                },
                "specter2": {
                    "size_gb": 0.84,
                    "location": "~/.cache/huggingface/models",
                    "used_by": ["paper-dive"],
                    "reason": "citation graph analysis",
                    "last_used": None,
                    "runtime": "hf",
                    "machine": "both",
                    "capability": "citation-embed",
                    "heavy": False,
                },
                "MiniLM": {
                    "size_gb": 0.17,
                    "location": "~/.cache/chroma",
                    "used_by": ["core"],
                    "reason": "vector search (Chroma default)",
                    "last_used": None,
                    "runtime": "hf",
                    "machine": "both",
                    "capability": "local-embed",
                    "heavy": False,
                },
                "llama-3.2-3b-mlx-4bit": {
                    "size_gb": 1.9,
                    "location": "~/.cache/huggingface",
                    "used_by": ["exo-test"],
                    "reason": "leftover from exo testing",
                    "last_used": None,
                    "runtime": "mlx",
                    "machine": "both",
                    "capability": "local-classify-small",
                    "heavy": False,
                },
                "qwen2.5:3b-mlx-4bit": {
                    "size_gb": 1.6,
                    "location": "~/.cache/huggingface",
                    "used_by": ["exo-test"],
                    "reason": "leftover from exo testing",
                    "last_used": None,
                    "runtime": "mlx",
                    "machine": "both",
                    "capability": "local-classify-small",
                    "heavy": False,
                },
                "llama-3.2-1b-mlx-4bit": {
                    "size_gb": 0.02,
                    "location": "~/.cache/huggingface",
                    "used_by": ["exo-test"],
                    "reason": "leftover from exo testing",
                    "last_used": None,
                    "runtime": "mlx",
                    "machine": "both",
                    "capability": "local-classify-small",
                    "heavy": False,
                },
                "FLUX.1-schnell-4bit": {
                    "size_gb": 6.5,
                    "location": "~/.cache/huggingface",
                    "used_by": ["portfolio-flux"],
                    "reason": "high-quality image generation for portfolio projects",
                    "last_used": None,
                    "runtime": "mflux",
                    "machine": "macbook-pro",
                    "capability": "image-gen",
                    "heavy": True,
                },
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._write(initial)

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        os.replace(tmp, self.path)

    def register(
        self,
        name: str,
        location: str,
        size_gb: float,
        used_by: list[str] | str,
        reason: str,
        runtime: str = "ollama",
        machine: str = "both",
        capability: str = "",
        heavy: bool = False,
    ) -> None:
        """Register a model with its metadata. Writes atomically.

        Args:
            name: Model name (e.g., "qwen2.5:14b")
            location: Where model is stored
            size_gb: Model size in GB
            used_by: List of consumers or single consumer string
            reason: Why this model is registered
            runtime: Runtime type (ollama/hf/mlx/mflux)
            machine: Target machine (mac-mini/macbook-pro/both)
            capability: Capability name (e.g., local-classify-large)
            heavy: Whether this model requires exclusive resource access
        """
        lock_path = self.path.parent / f".{self.path.name}.lock"
        with open(lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                data = self._read()
                # Ensure used_by is always a list
                if isinstance(used_by, str):
                    used_by = [used_by]
                data[name] = {
                    "size_gb": size_gb,
                    "location": location,
                    "used_by": used_by,
                    "reason": reason,
                    "last_used": None,
                    "runtime": runtime,
                    "machine": machine,
                    "capability": capability,
                    "heavy": heavy,
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
                if name in data:
                    data[name]["last_used"] = datetime.now(timezone.utc).isoformat()
                    self._write(data)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def get(self, name: str) -> dict | None:
        """Get model metadata by name."""
        data = self._read()
        return data.get(name)

    def all(self) -> dict:
        """Get all registered models."""
        return self._read()

    def by_capability(self, capability: str) -> list[str]:
        """Get model names with a given capability.

        Args:
            capability: Capability name (e.g., "local-classify-medium")

        Returns:
            List of model names with this capability (newest/largest first)
        """
        data = self._read()
        models = [name for name, entry in data.items() if entry.get("capability") == capability]
        # Sort by size descending (prefer larger models for quality)
        return sorted(models, key=lambda m: data[m].get("size_gb", 0), reverse=True)

    def heavy_models(self) -> dict[str, dict]:
        """Get all models marked as heavy (exclusive-resource).

        Returns:
            Dict of {model_name: metadata} for heavy models
        """
        data = self._read()
        return {name: entry for name, entry in data.items() if entry.get("heavy", False)}

    def resolve_capability(self, capability: str) -> str | None:
        """Resolve a capability name to the best available model.

        Prefers larger models when multiple are available for the same capability.

        Args:
            capability: Capability name (e.g., "local-classify-medium")

        Returns:
            Model name with this capability, or None if not found
        """
        data = self._read()
        models = [
            name
            for name, entry in data.items()
            if entry.get("capability") == capability
        ]
        if not models:
            return None
        # Sort by size descending (prefer larger models for quality)
        return sorted(models, key=lambda m: data[m].get("size_gb", 0), reverse=True)[0]

    def is_heavy(self, name: str) -> bool:
        """Check if a model requires exclusive resource access.

        Args:
            name: Model name

        Returns:
            True if model is heavy, False otherwise
        """
        data = self._read()
        return data.get(name, {}).get("heavy", False)

    def by_machine(self, machine: str) -> list[str]:
        """Get models available for a specific machine.

        Args:
            machine: Machine name (mac-mini/macbook-pro/both)

        Returns:
            List of model names available for this machine
        """
        data = self._read()
        return [
            name
            for name, entry in data.items()
            if entry.get("machine") in (machine, "both")
        ]

    def sync_ollama_models(self, ollama_url: str = "http://localhost:11434") -> None:
        """Update last_used timestamps for models currently loaded in Ollama.

        Calls Ollama's /api/ps endpoint to get currently running models,
        then touches last_used for each one found in the registry.

        Args:
            ollama_url: Base URL for Ollama API (default: localhost:11434)
        """
        try:
            import json as json_module
            import urllib.request

            ps_url = f"{ollama_url}/api/ps"
            req = urllib.request.Request(ps_url, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json_module.loads(resp.read())

            # data format: {"models": [{"name": "qwen2.5:14b", ...}, ...]}
            if "models" in data:
                for model_info in data["models"]:
                    model_name = model_info.get("name")
                    if model_name and model_name in self._read():
                        self.touch_last_used(model_name)
        except Exception:
            # Ollama not running or unreachable - silently skip
            pass


if __name__ == "__main__":
    import sys
    reg = ModelRegistry()
    if len(sys.argv) > 1:
        if sys.argv[1] == "list":
            print(json.dumps(reg.all(), indent=2))
        elif sys.argv[1] == "by-capability" and len(sys.argv) > 2:
            cap = sys.argv[2]
            models = reg.by_capability(cap)
            print(json.dumps(models, indent=2))
        elif sys.argv[1] == "heavy":
            print(json.dumps(reg.heavy_models(), indent=2))
    else:
        print(f"Registry at {reg.path}")
