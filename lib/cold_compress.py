#!/usr/bin/env python3
"""Lossless, transparent compression of files nobody is writing any more (ADR 0065, storage plan F5).

APFS compression (via afsctool) keeps every file at the same path with the same bytes and the same mtime, so every
reader (claude --resume, session_usage, tool_usage) works unchanged; only the space on disk shrinks. Measured
2026-10-14 on a 29 MB transcript: 28.4 -> 17.0 MB with LZFSE, reads instant. A zstd archive would save more (3x) but
would hide the file from those readers, so it was ruled out. Writing to a compressed file quietly decompresses it,
which is why only cold files are touched.

Each file is hashed before and after: if the bytes read back differ, it's reported as failed, never trusted. Nothing is
ever deleted, symlinks are never followed, and a missing afsctool skips the whole run with one line saying so.

Usage: cold_compress.py [root] [pattern] [min_age_days]   (default: ~/.claude/projects *.jsonl 7)
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

AFSCTOOL = "/opt/homebrew/bin/afsctool"  # launchd's PATH has no /opt/homebrew/bin
TRANSCRIPTS = Path.home() / ".claude" / "projects"
TRANSCRIPT_MIN_AGE_DAYS = 7


def _tool() -> str | None:
    return AFSCTOOL if Path(AFSCTOOL).exists() else shutil.which("afsctool")


def _afsctool_compress(path: Path) -> bool:
    return subprocess.run([_tool(), "-c", "-T", "LZFSE", str(path)], capture_output=True, timeout=600).returncode == 0


def _is_compressed(path: Path) -> bool:
    return bool(os.stat(path).st_flags & stat.UF_COMPRESSED)


def _disk_kb(path: Path) -> int:
    return os.stat(path).st_blocks * 512 // 1024


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def compress_cold(root: Path, pattern: str, min_age_days: float,
                  compress: Callable[[Path], bool] | None = None, now: float | None = None) -> dict:
    """Compress every regular file under root matching pattern, unchanged for min_age_days.
    Returns {"compressed": [{path, saved_kb}], "already": n, "failed": [{path, reason}], "saved_kb": n, "skipped": str|None}."""
    out = {"compressed": [], "already": 0, "failed": [], "saved_kb": 0, "skipped": None}
    if compress is None:
        if _tool() is None:
            out["skipped"] = "afsctool not installed"
            return out
        compress = _afsctool_compress
    if not root.is_dir():
        return out
    cutoff = (now or time.time()) - min_age_days * 86400

    for path in sorted(root.rglob(pattern)):
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_mtime > cutoff:
                continue
            if _is_compressed(path):
                out["already"] += 1
                continue
            st = path.stat()
            before_kb, before_hash = _disk_kb(path), _sha256(path)
            if not compress(path):
                out["failed"].append({"path": path, "reason": "afsctool refused"})
                continue
            os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))  # afsctool drops sub-microsecond precision
            if _sha256(path) != before_hash:
                out["failed"].append({"path": path, "reason": "content changed after compression"})
                continue
            saved = max(0, before_kb - _disk_kb(path))
            out["compressed"].append({"path": path, "saved_kb": saved})
            out["saved_kb"] += saved
        except Exception as exc:  # noqa: BLE001 -- one bad file (gone, unreadable) never stops the rest
            out["failed"].append({"path": path, "reason": f"{type(exc).__name__}: {str(exc)[:120]}"})
    return out


def compress_transcripts() -> dict:
    """Nightly entry point (cleanup_sweep): Claude Code transcripts a week or more old. Kept forever since
    2026-10-14 (cleanupPeriodDays 36500), so compressing the cold ones is what keeps that affordable."""
    return compress_cold(TRANSCRIPTS, "*.jsonl", TRANSCRIPT_MIN_AGE_DAYS)


if __name__ == "__main__":
    args = sys.argv[1:]
    root = Path(args[0]).expanduser() if args else TRANSCRIPTS
    result = compress_cold(root, args[1] if len(args) > 1 else "*.jsonl",
                           float(args[2]) if len(args) > 2 else TRANSCRIPT_MIN_AGE_DAYS)
    print(json.dumps({**result, "compressed": len(result["compressed"]),
                      "failed": [{"path": str(f["path"]), "reason": f["reason"]} for f in result["failed"]]}, indent=2))
