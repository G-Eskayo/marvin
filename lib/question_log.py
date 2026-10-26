#!/usr/bin/env python3
"""The question log (blind-spots note, test A; automatic, Gil 2026-10-26).

Whenever Gil asks something MARVIN can't answer from data ("where is it running?", "what did #600 cost?"), the
question goes here, with why it couldn't be answered and the signal that would have answered it. Asking again counts
it instead of adding a duplicate, so after two weeks `top` is the real list of missing signals.

One append-only JSONL file per Mac under ~/.agents/var (MARVIN-owned, gitignored); it moves into marvin.db with the
other streams. Each append is one write under an flock, so concurrent sessions never interleave.

    question_log.py add "<question>" [--why "<why it couldn't be answered>"] [--want "<signal that would answer it>"]
    question_log.py top [--limit N]
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

MAX_LEN = 500


def default_path() -> Path:
    return Path(os.environ.get("HOME", str(Path.home()))) / ".agents" / "var" / "question-log.jsonl"


def _key(q: str) -> str:
    return re.sub(r"[^\w#]+", " ", q.lower()).strip()


def add(question, why: str | None = None, want: str | None = None, path: Path | None = None,
        machine: str | None = None) -> dict:
    if not isinstance(question, str) or not question.strip():
        raise ValueError("an empty question can't be logged")
    path = Path(path) if path else default_path()
    row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "machine": machine or socket.gethostname().split(".")[0],
           "question": " ".join(question.split())[:MAX_LEN],
           "why": (why or "").strip()[:MAX_LEN] or None,
           "want": (want or "").strip()[:MAX_LEN] or None}
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(row, ensure_ascii=False) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, line)
    finally:
        os.close(fd)
    return row


def top(path: Path | None = None, limit: int = 20) -> list[dict]:
    """Questions grouped by their normalised text, most asked first: O(lines)."""
    path = Path(path) if path else default_path()
    if not path.exists():
        return []
    groups: dict[str, dict] = {}
    for raw in path.read_text(errors="replace").splitlines():
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(row, dict) or not isinstance(row.get("question"), str) or not row["question"].strip():
            continue
        g = groups.setdefault(_key(row["question"]), {"question": row["question"], "count": 0, "want": [],
                                                      "why": [], "last": None})
        g["count"] += 1
        g["last"] = row.get("ts")
        for k in ("want", "why"):
            v = row.get(k)
            if isinstance(v, str) and v and v not in g[k]:
                g[k].append(v)
    return sorted(groups.values(), key=lambda g: (-g["count"], g["question"]))[:limit]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="question_log.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("question")
    a.add_argument("--why")
    a.add_argument("--want")
    t = sub.add_parser("top")
    t.add_argument("--limit", type=int, default=20)
    args = ap.parse_args(argv)
    if args.cmd == "add":
        try:
            add(args.question, why=args.why, want=args.want)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 1
        return 0
    rows = top(limit=args.limit)
    if not rows:
        print("No questions logged yet.")
    for r in rows:
        want = f"  → wanted: {'; '.join(r['want'])}" if r["want"] else ""
        print(f"{r['count']}× {r['question']}{want}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
