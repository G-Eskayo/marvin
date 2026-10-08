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
                "qwen2.5-14b": {
                    "size_gb": 9.0,
                    "location": "~/.ollama/models",
                    "used_by": "paper-dive",
                    "reason": "logic auditing, competing ideas, argument mapper",
                    "last_used": None,
                },
                "qwen2.5-7b": {
                    "size_gb": 4.7,
                    "location": "~/.ollama/models",
                    "used_by": "paper-dive",
                    "reason": "logic auditing, competing ideas, argument mapper",
                    "last_used": None,
                },
                "qwen2.5-3b": {
                    "size_gb": 1.9,
                    "location": "~/.ollama/models",
                    "used_by": "paper-dive",
                    "reason": "logic auditing, competing ideas, argument mapper",
                    "last_used": None,
                },
                "nomic-embed-text": {
                    "size_gb": 0.27,
                    "location": "~/.ollama/models",
                    "used_by": "core",
                    "reason": "memory search, routing, embeddings",
                    "last_used": None,
                },
                "specter2": {
                    "size_gb": 0.84,
                    "location": "~/.cache/huggingface/models",
                    "used_by": "paper-dive",
                    "reason": "citation graph analysis",
                    "last_used": None,
                },
                "MiniLM": {
                    "size_gb": 0.17,
                    "location": "~/.cache/chroma",
                    "used_by": "core",
                    "reason": "vector search (Chroma default)",
                    "last_used": None,
                },
                "llama-3.2-3b-mlx-4bit": {
                    "size_gb": 1.9,
                    "location": "~/.cache/huggingface",
                    "used_by": "exo-test",
                    "reason": "leftover from exo testing",
                    "last_used": None,
                },
                "qwen2.5-3b-mlx-4bit": {
                    "size_gb": 1.6,
                    "location": "~/.cache/huggingface",
                    "used_by": "exo-test",
                    "reason": "leftover from exo testing",
                    "last_used": None,
                },
                "llama-3.2-1b-mlx-4bit": {
                    "size_gb": 0.02,
                    "location": "~/.cache/huggingface",
                    "used_by": "exo-test",
                    "reason": "leftover from exo testing",
                    "last_used": None,
                },
                "FLUX.1-schnell-4bit": {
                    "size_gb": 6.5,
                    "location": "~/.cache/huggingface",
                    "used_by": "portfolio-flux",
                    "reason": "high-quality image generation for portfolio projects",
                    "last_used": None,
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

    def register(self, name: str, location: str, size_gb: float, used_by: str, reason: str) -> None:
        """Register a model with its metadata. Writes atomically."""
        lock_path = self.path.parent / f".{self.path.name}.lock"
        with open(lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                data = self._read()
                data[name] = {
                    "size_gb": size_gb,
                    "location": location,
                    "used_by": used_by,
                    "reason": reason,
                    "last_used": None,
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


if __name__ == "__main__":
    import sys
    reg = ModelRegistry()
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        print(json.dumps(reg.all(), indent=2))
    else:
        print(f"Registry at {reg.path}")
