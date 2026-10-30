#!/usr/bin/env python3
"""The environment for a gh call made outside an interactive login (marvin#866).

In an ssh or launchd shell the macOS keychain is locked, so `gh` has no login and answers `HTTP 401: Requires
authentication`. The builders' wrapper (task_dispatch._build_wrapper_script) has long exported GH_TOKEN from
~/.claude/.gh-token for this; the disk cleanup never did, so after every merge each worktree was kept as "could not
check GitHub" (31 on the Mac mini, 90 on the MacBook, 2026-10-30) and the disk filled.

    env()                 os.environ plus GH_TOKEN from the token file when it exists and isn't empty; an explicit
                          GH_TOKEN is never overridden, and with no file the environment is returned unchanged.
    run(args, check=...)  subprocess.run with that env; a failure raises GhError with a plain reason: no token at all,
                          GitHub refusing the saved token (expired or revoked), or gh's own message.

The token itself is never logged, printed or put in a reason: anything gh echoes back is redacted.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

DEFAULT_TOKEN_FILE = Path.home() / ".claude" / ".gh-token"
TOKEN_FILE = DEFAULT_TOKEN_FILE   # the seam tests point at a temp file (lib/tests/conftest.py)
DEFAULT_TIMEOUT_S = 60
_REFUSED = ("401", "bad credentials", "requires authentication", "authentication failed")


class GhError(RuntimeError):
    """A gh call that failed, with a reason a person can act on (never the token)."""


def _read_token(token_file: Path | None) -> str:
    try:
        return Path(token_file or TOKEN_FILE).read_text().strip()
    except (OSError, UnicodeDecodeError):
        return ""


def env(token_file: Path | None = None, base: dict | None = None) -> dict:
    e = dict(os.environ if base is None else base)
    if e.get("GH_TOKEN"):
        return e
    tok = _read_token(token_file)
    if tok:
        e["GH_TOKEN"] = tok
    return e


def _redact(text: str, e: dict) -> str:
    tok = e.get("GH_TOKEN")
    return text.replace(tok, "[token]") if tok else text


def explain(stderr: str, e: dict) -> str:
    """Why a gh call failed, in plain words, for a log line or a "kept" reason."""
    said = _redact(" ".join(str(stderr or "").split()), e)[:200] or "no output"
    if not e.get("GH_TOKEN"):
        return (f"no GitHub token for this shell (the keychain is locked outside an interactive login and "
                f"~/.claude/.gh-token is missing or empty), so nothing was checked: {said}")
    if any(k in said.lower() for k in _REFUSED):
        return (f"GitHub refused the saved token (GH_TOKEN / ~/.claude/.gh-token; expired or revoked?), so nothing "
                f"was checked; replace the token: {said}")
    return said


def run(args: list[str], *, check: bool = True, timeout: float = DEFAULT_TIMEOUT_S,
        token_file: Path | None = None) -> subprocess.CompletedProcess:
    e = env(token_file)
    try:
        r = subprocess.run(args, capture_output=True, text=True, env=e, timeout=timeout)
    except FileNotFoundError as exc:
        raise GhError(f"gh is not installed or not on PATH ({args[0]}): {exc.strerror}") from None
    except subprocess.TimeoutExpired:
        raise GhError(f"gh did not answer within {int(timeout)} s") from None
    if check and r.returncode != 0:
        raise GhError(explain(r.stderr or r.stdout, e))
    if r.returncode != 0:
        r.stderr = _redact(r.stderr or "", e)
    return r
