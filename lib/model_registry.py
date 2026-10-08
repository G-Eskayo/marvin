"""Shared model registry: the static list of models, their capabilities, usage tracking, and consistency checking.

Mirrors dispatch_concurrency.py's shape with tolerant defaults: a missing or malformed registry
falls back to safe defaults, never to an error. Usage logging is best-effort, never fatal.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "config" / "models.json"

DEFAULTS = {
    "models": [],
    "capabilities": {},
}


def load(path: Path | None = None) -> dict:
    """Load the model registry, falling back to safe defaults on missing or invalid files."""
    try:
        raw = json.loads(Path(path or PATH).read_text())
    except (OSError, ValueError):
        return DEFAULTS.copy()
    if not isinstance(raw, dict):
        return DEFAULTS.copy()
    return {
        "models": raw.get("models", []),
        "capabilities": raw.get("capabilities", {}),
    }


def save(registry: dict, path: Path | None = None) -> None:
    """Write the registry atomically."""
    target = Path(path or PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(registry, f, indent=2)
        f.write("\n")
    os.replace(tmp, target)


def resolve_capability(capability: str, config: dict | None = None) -> str:
    """Resolve a capability name to a model name. Raises KeyError if not found — a programming error."""
    cfg = config or load()
    if capability not in cfg.get("capabilities", {}):
        raise KeyError(f"capability '{capability}' not in capabilities map")
    return cfg["capabilities"][capability]


def is_heavy(model: str, config: dict | None = None) -> bool:
    """Check if a model is marked as heavy (requires queue gating)."""
    cfg = config or load()
    for m in cfg.get("models", []):
        if m.get("name") == model:
            return m.get("heavy", False)
    return False


def record_usage(model: str, caller: str, machine: str | None = None, log_dir: Path | None = None) -> None:
    """Best-effort append to model-usage.jsonl and atomic rewrite of model-last-used.json. Never raises."""
    try:
        log_dir = log_dir or (Path.home() / ".claude" / "logs")
        log_dir.mkdir(parents=True, exist_ok=True)

        usage_file = log_dir / "model-usage.jsonl"
        record = {
            "model": model,
            "caller": caller,
            "machine": machine,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with open(usage_file, "a") as f:
            f.write(json.dumps(record) + "\n")

        last_used_file = log_dir / "model-last-used.json"
        try:
            last_used = json.loads(last_used_file.read_text()) if last_used_file.exists() else {}
        except (OSError, ValueError):
            last_used = {}
        last_used[model] = datetime.now(timezone.utc).isoformat()

        fd, tmp = tempfile.mkstemp(dir=log_dir, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(last_used, f)
            f.write("\n")
        os.replace(tmp, last_used_file)
    except Exception:
        pass


def check_consistency(config: dict, code_literals: set[str] | None = None,
                      code_capabilities: set[str] | None = None) -> list[str]:
    """
    Two-severity consistency check:
    - Hard fail (RuntimeError): a known model literal or unresolvable capability not in registry.
    - Soft warning (returns list): unused entries or entries without reasons.
    """
    code_literals = code_literals or set()
    code_capabilities = code_capabilities or set()

    model_names = {m["name"] for m in config.get("models", [])}
    capability_names = set(config.get("capabilities", {}).keys())

    for literal in code_literals:
        if literal not in model_names:
            raise RuntimeError(f"model '{literal}' found in code but not in models.json")

    for cap in code_capabilities:
        if cap not in capability_names:
            raise RuntimeError(f"capability '{cap}' found in code but not in capabilities map")

    warnings = []
    for model in config.get("models", []):
        if not model.get("used_by") and not model.get("reason"):
            warnings.append(f"model '{model['name']}' is unused and has no reason — candidate for removal")

    return warnings


def installed_models(machine: str | None = None, config: dict | None = None) -> dict[str, dict]:
    """
    Merge static registry with live snapshot: currently loaded (Ollama) and real disk sizes.
    Returns {model_name: {size_gb, runtime, last_used, machine, ...}}.
    Unreachable Ollama/remote → falls back to static data, never errors.
    """
    cfg = config or load()
    result = {}

    for model_info in cfg.get("models", []):
        model_name = model_info["name"]
        result[model_name] = {
            "name": model_name,
            "runtime": model_info.get("runtime", "unknown"),
            "used_by": model_info.get("used_by", []),
            "heavy": model_info.get("heavy", False),
            "size_gb": None,
            "last_used": None,
            "machine": machine,
        }

    try:
        log_dir = Path.home() / ".claude" / "logs"
        last_used_file = log_dir / "model-last-used.json"
        if last_used_file.exists():
            last_used = json.loads(last_used_file.read_text())
            for model_name, ts in last_used.items():
                if model_name in result:
                    result[model_name]["last_used"] = ts
    except Exception:
        pass

    if machine is None or machine == "mac-mini":
        result.update(_installed_models_ollama())

    return result


def _installed_models_ollama() -> dict[str, dict]:
    """Query Ollama for currently loaded and installed models via API. Returns partial updates."""
    try:
        ps_resp = subprocess.run(
            ["curl", "-s", "http://localhost:11434/api/ps"],
            capture_output=True, text=True, timeout=5,
        )
        if ps_resp.returncode != 0:
            return {}

        ps_data = json.loads(ps_resp.text)
        running = {m["name"] for m in ps_data.get("models", [])}

        tags_resp = subprocess.run(
            ["curl", "-s", "http://localhost:11434/api/tags"],
            capture_output=True, text=True, timeout=5,
        )
        tags_data = json.loads(tags_resp.text) if tags_resp.returncode == 0 else {}

        result = {}
        for model_info in tags_data.get("models", []):
            name = model_info["name"]
            size_bytes = model_info.get("size", 0)
            size_gb = size_bytes / (1024 ** 3)
            result[name] = {
                "size_gb": round(size_gb, 2),
                "loaded": name in running,
            }
        return result
    except Exception:
        return {}


def _cli(argv: list[str]) -> int:
    """`model_registry.py get` prints the registry; `set '<json>'` validates and saves.
    `resolve <capability>` prints the resolved model. `check` runs consistency check.
    `record-usage <model> <caller> [--machine <id>]` logs a usage event."""
    import sys
    if argv[:1] == ["get"]:
        print(json.dumps(load()))
        return 0
    if argv[:1] == ["set"] and len(argv) == 2:
        try:
            registry = json.loads(argv[1])
            save(registry)
            print(json.dumps(registry))
            return 0
        except (ValueError, TypeError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if argv[:1] == ["resolve"] and len(argv) == 2:
        try:
            cfg = load()
            model = resolve_capability(argv[1], config=cfg)
            print(model)
            return 0
        except KeyError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if argv[:1] == ["check"]:
        cfg = load()
        warnings = check_consistency(cfg)
        for w in warnings:
            print(w)
        return 0
    if argv[:1] == ["record-usage"] and len(argv) >= 3:
        model = argv[1]
        caller = argv[2]
        machine = None
        if len(argv) >= 5 and argv[3] == "--machine":
            machine = argv[4]
        record_usage(model, caller, machine=machine)
        return 0
    print("usage: model_registry.py get | set '<json>' | resolve <capability> | check | record-usage <model> <caller> [--machine <id>]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
