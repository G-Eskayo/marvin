"""Whose MARVIN is this? The one place engine code asks (ADR 0071).

The engine (this repo) is public and shared; each person's state lives in a private instance repo nested at
~/.agents/instance/ and ignored by the engine. Engine code never hard-codes an owner, account or machine: a friend's
clone must file tickets against their own fork, not the upstream.

Derived, not stored, wherever possible:
  engine_repo()   the clone's own `origin` on GitHub (a fork for a friend, G-Eskayo/marvin for the upstream owner)
  owner()         instance.json "owner", else the owner part of engine_repo()
  tickets_repo()  instance.json "tickets_repo", else engine_repo()
Stored in instance/instance.json, because nothing can derive them:
  features        {"portfolio": true, ...}: everything optional is off until turned on

A missing, corrupt or wrong-shaped instance.json reads as a blank instance, never a crash. Each value is computed once
per process (O(1) after the first call; engine code calls these in loops). MARVIN_INSTANCE_DIR overrides the
instance location (tests, a second checkout).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
UPSTREAM = "G-Eskayo/marvin"
_GITHUB = re.compile(r"github\.com[:/]+([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")


def instance_dir() -> Path:
    # ~/.agents/instance, not ENGINE_DIR/instance: code run from a worktree (tests, the ticket pipeline) must find the
    # one real instance, not an empty folder inside the worktree. Resolved per call, so a test's temp HOME is honoured.
    return Path(os.environ.get("MARVIN_INSTANCE_DIR") or Path.home() / ".agents" / "instance")


def path(*parts: str) -> Path:
    return instance_dir().joinpath(*parts)


@lru_cache(maxsize=1)
def _config() -> dict:
    try:
        data = json.loads((instance_dir() / "instance.json").read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _str(key: str) -> str | None:
    v = _config().get(key)
    return v if isinstance(v, str) and v.strip() else None


@lru_cache(maxsize=1)
def _origin_repo() -> str | None:
    try:
        url = subprocess.run(["git", "-C", str(ENGINE_DIR), "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    m = _GITHUB.search(url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def engine_repo() -> str:
    return _origin_repo() or _str("engine_repo") or UPSTREAM


def owner() -> str:
    return _str("owner") or engine_repo().split("/")[0]


def tickets_repo() -> str:
    return _str("tickets_repo") or engine_repo()


def feature_enabled(name: str) -> bool:
    features = _config().get("features")
    return isinstance(features, dict) and features.get(name) is True


def reset() -> None:
    """Forget cached values (tests; a long-running process after the instance changes)."""
    _config.cache_clear()
    _origin_repo.cache_clear()
