#!/usr/bin/env python3
"""Shared registry of AI models across MARVIN, tracking location, size, usage, and last access.

Seeded with the inventory from the image-maker plan (2026-10-08). New models are registered
before download, so the dashboard always knows what's where and how big it is.

Per-model fields: size_gb, location, used_by, reason, last_used, heavy (bool), machine (str|None).
- heavy: true for models that can't coexist in 16GB (e.g., qwen2.5:14b, FLUX.1-schnell-4bit)
- machine: "macbook-pro"|"mac-mini"|None (None/omitted = shared across machines)
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "models.json"
CAPABILITIES_PATH = Path(__file__).resolve().parents[1] / "config" / "model_capabilities.json"


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
                    "used_by": "paper-dive",
                    "reason": "logic auditing, competing ideas, argument mapper",
                    "heavy": True,
                    "machine": None,
                    "last_used": None,
                },
                "qwen2.5:7b": {
                    "size_gb": 4.7,
                    "location": "~/.ollama/models",
                    "used_by": "paper-dive",
                    "reason": "logic auditing, competing ideas, argument mapper",
                    "heavy": False,
                    "machine": None,
                    "last_used": None,
                },
                "qwen2.5:3b": {
                    "size_gb": 1.9,
                    "location": "~/.ollama/models",
                    "used_by": "paper-dive",
                    "reason": "logic auditing, competing ideas, argument mapper",
                    "heavy": False,
                    "machine": None,
                    "last_used": None,
                },
                "nomic-embed-text": {
                    "size_gb": 0.27,
                    "location": "~/.ollama/models",
                    "used_by": "core",
                    "reason": "memory search, routing, embeddings",
                    "heavy": False,
                    "machine": None,
                    "last_used": None,
                },
                "specter2": {
                    "size_gb": 0.84,
                    "location": "~/.cache/huggingface/models",
                    "used_by": "paper-dive",
                    "reason": "citation graph analysis",
                    "heavy": False,
                    "machine": None,
                    "last_used": None,
                },
                "MiniLM": {
                    "size_gb": 0.17,
                    "location": "~/.cache/chroma",
                    "used_by": "core",
                    "reason": "vector search (Chroma default)",
                    "heavy": False,
                    "machine": None,
                    "last_used": None,
                },
                "llama-3.2-3b-mlx-4bit": {
                    "size_gb": 1.9,
                    "location": "~/.cache/huggingface",
                    "used_by": "exo-test",
                    "reason": "leftover from exo testing",
                    "heavy": False,
                    "machine": None,
                    "last_used": None,
                },
                "qwen2.5-3b-mlx-4bit": {
                    "size_gb": 1.6,
                    "location": "~/.cache/huggingface",
                    "used_by": "exo-test",
                    "reason": "leftover from exo testing",
                    "heavy": False,
                    "machine": None,
                    "last_used": None,
                },
                "llama-3.2-1b-mlx-4bit": {
                    "size_gb": 0.02,
                    "location": "~/.cache/huggingface",
                    "used_by": "exo-test",
                    "reason": "leftover from exo testing",
                    "heavy": False,
                    "machine": None,
                    "last_used": None,
                },
                "FLUX.1-schnell-4bit": {
                    "size_gb": 6.5,
                    "location": "~/.cache/huggingface",
                    "used_by": "portfolio-flux",
                    "reason": "high-quality image generation for portfolio projects",
                    "heavy": True,
                    "machine": None,
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

    def register(self, name: str, location: str, size_gb: float, used_by: str, reason: str,
                  heavy: bool = False, machine: str | None = None) -> None:
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
                    "heavy": heavy,
                    "machine": machine,
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

    def installed_models(self) -> set[str]:
        """Models available locally via ollama (not yet implemented; stub for future use)."""
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                models = set()
                for line in result.stdout.splitlines()[1:]:  # skip header
                    if line.strip():
                        model_name = line.split()[0]
                        models.add(model_name)
                return models
        except Exception:
            pass
        return set()


def _load_capabilities() -> dict:
    """Load capability name → model name mappings. Returns {} if file missing."""
    try:
        return json.loads(CAPABILITIES_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _ensure_capabilities_exist() -> None:
    """Create default capabilities.json if missing."""
    if CAPABILITIES_PATH.exists():
        return
    default = {
        "local-classify-medium": "qwen2.5:14b",
        "local-extract-small": "qwen2.5:3b",
        "local-judge-medium": "qwen2.5:7b",
        "local-judge-large": "qwen2.5:14b",
        "local-infer-large": "qwen2.5:14b",
        "local-stance-medium": "qwen2.5:7b",
        "local-claim-extract": "qwen2.5:3b",
    }
    CAPABILITIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CAPABILITIES_PATH.write_text(json.dumps(default, indent=2))


def resolve_capability(name: str) -> str:
    """Resolve a capability name to a model name. Raises KeyError if unknown."""
    _ensure_capabilities_exist()
    caps = _load_capabilities()
    if name not in caps:
        raise KeyError(f"unknown capability: {name!r}. Known: {sorted(caps.keys())}")
    return caps[name]


def is_heavy(model_name: str) -> bool:
    """Check if a model is marked as heavy (can't coexist in 16GB)."""
    reg = ModelRegistry()
    meta = reg.get(model_name)
    return meta.get("heavy", False) if meta else False


def check_consistency() -> tuple[list[str], list[str]]:
    """Scan code for model literals and capability calls; check against registry.

    Returns (hard_failures, soft_warnings):
    - hard_failures: model literal or capability referenced in code but not in registry
    - soft_warnings: registry entry with empty used_by and no reason (unused model)

    Raises on hard failure; returns soft warnings as a list for review.
    """
    reg = ModelRegistry()
    _ensure_capabilities_exist()
    registry_data = reg.all()
    caps_data = _load_capabilities()

    # Scan code for known model patterns
    lib_dir = Path(__file__).resolve().parent
    skills_dir = lib_dir.parent / "skills"

    model_literals = set()
    capability_refs = set()

    # Pattern: model names in code (qwen2.5:14b, nomic-embed-text, etc.)
    model_patterns = [
        r"qwen2\.5:\d+b",
        r"nomic-embed-text",
        r"specter2",
        r"FLUX\.1-schnell",
        r"MiniLM",
    ]

    # Pattern: resolve_capability("local-xxx-yyy")
    capability_pattern = r'resolve_capability\s*\(\s*["\']([^"\']+)["\']\s*\)'

    def scan_file(path: Path) -> None:
        try:
            content = path.read_text()
        except Exception:
            return

        for pattern in model_patterns:
            for match in re.finditer(pattern, content):
                model_literals.add(match.group(0))

        for match in re.finditer(capability_pattern, content):
            capability_refs.add(match.group(1))

    # Scan lib and skills
    if lib_dir.exists():
        for py_file in lib_dir.glob("**/*.py"):
            scan_file(py_file)

    if skills_dir.exists():
        for py_file in skills_dir.glob("**/*.py"):
            scan_file(py_file)

    # Check hard failures
    hard_failures = []
    for literal in sorted(model_literals):
        if literal not in registry_data:
            hard_failures.append(f"model literal {literal!r} in code but not in registry")

    for cap in sorted(capability_refs):
        if cap not in caps_data:
            hard_failures.append(f"capability {cap!r} in code but not in capabilities.json")

    if hard_failures:
        raise RuntimeError("consistency check failed:\n" + "\n".join(hard_failures))

    # Soft warnings
    soft_warnings = []
    for model_name, meta in sorted(registry_data.items()):
        used_by = meta.get("used_by", "").strip()
        reason = meta.get("reason", "").strip()
        if not used_by and not reason:
            soft_warnings.append(f"model {model_name!r} has no used_by or reason (potentially unused)")

    return hard_failures, soft_warnings


if __name__ == "__main__":
    import sys
    reg = ModelRegistry()
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "list" or cmd == "get":
            print(json.dumps(reg.all(), indent=2))
        elif cmd == "resolve" and len(sys.argv) > 2:
            try:
                model = resolve_capability(sys.argv[2])
                print(json.dumps({"capability": sys.argv[2], "model": model}, indent=2))
            except KeyError as e:
                print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
                sys.exit(1)
        elif cmd == "check":
            try:
                hard, soft = check_consistency()
                if soft:
                    print("Warnings (unused models):", file=sys.stderr)
                    for w in soft:
                        print(f"  - {w}", file=sys.stderr)
                print(json.dumps({"ok": True, "warnings": soft}, indent=2))
            except RuntimeError as e:
                print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
                sys.exit(1)
        else:
            print(f"Registry at {reg.path}")
            print(f"Capabilities at {CAPABILITIES_PATH}")
    else:
        print(f"Registry at {reg.path}")
        print(f"Capabilities at {CAPABILITIES_PATH}")
