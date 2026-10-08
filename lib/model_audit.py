#!/usr/bin/env python3
"""Model registry audit and consistency checks (ADR 0061).

Verify:
- No stale entries (last_used too old or null)
- All model references in code are registered
- used_by field references something real
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

HOME = Path.home()


class ModelAudit:
    """Audit model registry for consistency and staleness."""

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

    def check_stale_models(self, days_threshold: int = 365) -> list[dict]:
        """Find models not used in the last N days or never used.

        Returns:
            List of stale model entries: [{"name": ..., "last_used": ..., "days_ago": ...}]
        """
        stale = []
        now = datetime.now(timezone.utc)
        threshold = now - timedelta(days=days_threshold)

        for name, entry in self.registry.items():
            last_used = entry.get("last_used")
            if last_used is None:
                stale.append({
                    "name": name,
                    "last_used": None,
                    "days_ago": None,
                    "reason": "never used"
                })
            else:
                try:
                    last_used_dt = datetime.fromisoformat(last_used.replace("Z", "+00:00"))
                    if last_used_dt < threshold:
                        days_ago = (now - last_used_dt).days
                        stale.append({
                            "name": name,
                            "last_used": last_used,
                            "days_ago": days_ago,
                            "reason": f"unused for {days_ago} days"
                        })
                except (ValueError, AttributeError):
                    pass

        return sorted(stale, key=lambda x: x.get("days_ago") or 999999, reverse=True)

    def check_unregistered_references(self, search_dir: Path = None, skip_comments: bool = False) -> list[dict]:
        """Find model identifiers in code not in registry.

        Searches for patterns like:
        - ollama.pull("model-name")
        - model = "model-name"
        - HuggingFace repo IDs

        Args:
            search_dir: Directory to search (default: repo root)
            skip_comments: Whether to exclude references in comments

        Returns:
            List of unregistered references: [{"model": ..., "file": ..., "line": ...}]
        """
        if search_dir is None:
            search_dir = Path(__file__).resolve().parents[1]

        unregistered = []
        registered_names = set(self.registry.keys())

        # Common patterns for model references
        patterns = [
            r'ollama\.pull\(["\']([^"\']+)["\']',
            r'ollama\.generate\(["\']([^"\']+)["\']',
            r'model\s*=\s*["\']([^"\']+)["\']',
            r'from_pretrained\(["\']([^"\']+)["\']',
            r'"model":\s*["\']([^"\']+)["\']',
        ]

        for py_file in search_dir.rglob("*.py"):
            try:
                content = py_file.read_text()
                lines = content.split("\n")

                for line_no, line in enumerate(lines, 1):
                    # Skip comments if requested
                    if skip_comments:
                        line = line.split("#")[0]

                    for pattern in patterns:
                        for match in re.finditer(pattern, line):
                            model_name = match.group(1)
                            if model_name and model_name not in registered_names:
                                unregistered.append({
                                    "model": model_name,
                                    "file": str(py_file.relative_to(search_dir)),
                                    "line": line_no,
                                    "context": line.strip()[:100]
                                })
            except (OSError, UnicodeDecodeError):
                pass

        # Deduplicate by model name
        return sorted(
            {(u["model"], u["file"], u["line"]): u for u in unregistered}.values(),
            key=lambda x: (x["file"], x["line"])
        )

    def check_used_by_field(self, search_dir: Path = None) -> list[dict]:
        """Verify used_by field references something that actually uses the model.

        Returns:
            List of suspicious entries: [{"model": ..., "used_by": ..., "found": bool}]
        """
        if search_dir is None:
            search_dir = Path(__file__).resolve().parents[1]

        results = []

        for name, entry in self.registry.items():
            used_by_field = entry.get("used_by", [])
            if isinstance(used_by_field, str):
                used_by_list = [used_by_field] if used_by_field.strip() else []
            else:
                used_by_list = used_by_field if isinstance(used_by_field, list) else []

            for used_by in used_by_list:
                if not used_by or not isinstance(used_by, str):
                    continue

                # Simple heuristic: look for files/directories matching the used_by name
                found = False
                for py_file in search_dir.rglob("*.py"):
                    if used_by in py_file.name or used_by in str(py_file):
                        found = True
                        break

                # Also check for directory
                if not found and (search_dir / used_by).exists():
                    found = True

                if not found:
                    results.append({
                        "model": name,
                        "used_by": used_by,
                        "found": False
                    })

        return results

    def all_issues(self, search_dir: Path = None, days_threshold: int = 365) -> dict:
        """Run all checks and return aggregated results."""
        return {
            "stale": self.check_stale_models(days_threshold),
            "unregistered": self.check_unregistered_references(search_dir),
            "invalid_used_by": self.check_used_by_field(search_dir)
        }


if __name__ == "__main__":
    import sys
    audit = ModelAudit()
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "stale":
            threshold = int(sys.argv[2]) if len(sys.argv) > 2 else 365
            stale = audit.check_stale_models(threshold)
            print(json.dumps(stale, indent=2))
        elif cmd == "unregistered":
            search_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
            unregistered = audit.check_unregistered_references(search_dir)
            print(json.dumps(unregistered, indent=2))
        elif cmd == "used-by":
            search_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
            results = audit.check_used_by_field(search_dir)
            print(json.dumps(results, indent=2))
        else:
            all_issues = audit.all_issues()
            print(json.dumps(all_issues, indent=2))
