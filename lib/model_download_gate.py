#!/usr/bin/env python3
"""Download gate: enforce that all models are registered before pulling (ADR 0061).

Prevents silent introduction of undeclared models and ensures every download has
a documented reason. Call sites wrap ollama.pull()/HF snapshot_download with
gate.can_download(model_name) before proceeding.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

HOME = Path.home()


class UnregisteredModelError(Exception):
    """Model not in registry."""
    pass


class NoDownloadReasonError(Exception):
    """Model in registry but reason field is empty."""
    pass


class ModelDownloadGate:
    """Gate that enforces registry checks before any model download."""

    def __init__(self, registry_path: Path = None):
        if registry_path is None:
            registry_path = Path(__file__).resolve().parents[1] / "config" / "models.json"
        self.registry_path = Path(registry_path)
        self._load_registry()

    def _load_registry(self) -> None:
        try:
            self.registry = json.loads(self.registry_path.read_text())
        except (OSError, ValueError):
            self.registry = {}

    def can_download(self, model: str) -> bool:
        """Check if a model is allowed to download.

        Args:
            model: Model name/identifier

        Returns:
            True if allowed (always, for convenience)

        Raises:
            UnregisteredModelError: Model not in registry
            NoDownloadReasonError: Model registered but reason is empty
        """
        if model not in self.registry:
            raise UnregisteredModelError(
                f"Model '{model}' is not in config/models.json. "
                "Register it first with a reason (e.g., 'logic auditing, competing ideas')."
            )

        entry = self.registry[model]
        reason = entry.get("reason", "").strip()
        if not reason:
            raise NoDownloadReasonError(
                f"Model '{model}' is in registry but has no reason. "
                "Add a reason explaining why this model is needed."
            )

        return True

    def download(self, model: str, download_fn: Callable = None, *args, **kwargs) -> bool:
        """Gated download: check registry, then call download function.

        Args:
            model: Model name
            download_fn: Function to call to perform the download
            *args, **kwargs: Passed to download_fn

        Returns:
            Result of download_fn

        Raises:
            UnregisteredModelError or NoDownloadReasonError on gate failure
        """
        self.can_download(model)  # Raises on failure
        if download_fn is None:
            return True
        return download_fn(model, *args, **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


if __name__ == "__main__":
    import sys
    gate = ModelDownloadGate()
    if len(sys.argv) > 1:
        model = sys.argv[1]
        try:
            gate.can_download(model)
            print(f"OK: {model} is registered and allowed to download")
        except (UnregisteredModelError, NoDownloadReasonError) as e:
            print(f"BLOCKED: {e}")
            sys.exit(1)
