#!/usr/bin/env python3
"""How many tokens the Claude sessions on this machine used, when, by what kind of run, for which project and ticket.

Source: the Claude Code session transcripts (~/.claude/projects/**/*.jsonl), the same files lib/tool_usage.py reads. Each assistant
message carries `usage` (input, output, cache write, cache read). Output (`~/.claude/logs/token-usage.json`) feeds the Metrics tab's
Usage view; each machine writes its own, and the dashboard reads the other machine's over ssh.

Two things this gets right that a naive sum does not:
- Claude Code writes ONE transcript line PER CONTENT BLOCK, repeating the message's usage on each (53 lines were 19 messages), so
  messages are de-duplicated by message id (the latest line of a message wins, in case its usage grew while streaming).
- Cache reads are cheap and cache writes are not, so the four counts are kept separate; "output" is the one that matters for limits.

    session_usage.py refresh [--days 30]
    session_usage.py show
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

HOME = Path.home()
TRANSCRIPTS = HOME / ".claude" / "projects"
OUT_PATH = HOME / ".claude" / "logs" / "token-usage.json"
WINDOW_DAYS = 30
TOP_TICKETS = 40

_WORKTREE = re.compile(r"pipeline-g-eskayo-(.+?)[-#](\d+)(?=/|$)")  # older worktrees keep the '#' in the directory name
_PROJECT_ROOTS = re.compile(r"/(?:Developer|Documents/Projects(?:/experiments)?)/([^/]+)")
FIELDS = ("input", "output", "cache_write", "cache_read", "messages")


def machine_id() -> str:
    try:
        import machine_profile
        return machine_profile.registry_id()
    except Exception:  # noqa: BLE001
        return "this-machine"


def _parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def attribute(cwd) -> tuple[str, int | None]:
    """(project, ticket) for a session's working directory, including a directory inside a project. Pipeline worktrees are named
    for their ticket."""
    if not cwd:
        return "(unknown)", None
    path = str(cwd)
    m = _WORKTREE.search(path)
    if m:
        return m.group(1), int(m.group(2))
    if re.search(r"/\.(?:agents|claude)(?:/|$)", path):
        return "marvin", None
    m = _PROJECT_ROOTS.search(path)
    if m:
        return m.group(1), None
    if path.rstrip("/") == str(HOME):
        return "(home)", None
    return Path(path).name or "(home)", None


def _kind(d) -> str:
    return "subagent" if d.get("isSidechain") else ("interactive" if d.get("entrypoint") in (None, "cli") else "headless")


def _blank():
    return {f: 0 for f in FIELDS}


def _add(rec, usage):
    rec["input"] += usage["input"]
    rec["output"] += usage["output"]
    rec["cache_write"] += usage["cache_write"]
    rec["cache_read"] += usage["cache_read"]
    rec["messages"] += 1


def find_transcripts(root: Path, window_days: int = WINDOW_DAYS, now: datetime | None = None) -> list[Path]:
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=window_days)).timestamp()
    out = []
    for f in root.rglob("*.jsonl"):
        try:
            if f.stat().st_mtime >= cutoff:
                out.append(f)
        except OSError:
            continue
    return sorted(out)


def aggregate(files, now: datetime | None = None, window_days: int = WINDOW_DAYS) -> dict:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    messages = {}  # message id -> record; the latest line of a message wins
    for f in files:
        try:
            lines = f.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        for raw in lines:
            if '"usage"' not in raw:
                continue
            try:
                d = json.loads(raw)
            except json.JSONDecodeError:
                continue
            msg = d.get("message") or {}
            u = msg.get("usage")
            when = _parse_ts(d.get("timestamp"))
            if d.get("type") != "assistant" or not isinstance(u, dict) or not msg.get("id") or when is None or when < cutoff:
                continue
            project, ticket = attribute(d.get("cwd"))
            messages[msg["id"]] = {
                "day": when.date().isoformat(), "kind": _kind(d), "model": msg.get("model") or "?", "project": project, "ticket": ticket,
                "usage": {"input": u.get("input_tokens", 0) or 0, "output": u.get("output_tokens", 0) or 0,
                          "cache_write": u.get("cache_creation_input_tokens", 0) or 0, "cache_read": u.get("cache_read_input_tokens", 0) or 0}}
    totals, rows, projects, tickets = _blank(), defaultdict(_blank), defaultdict(_blank), defaultdict(_blank)
    for m in messages.values():
        _add(totals, m["usage"])
        _add(rows[(m["day"], m["kind"], m["model"])], m["usage"])
        _add(projects[(m["project"], m["kind"])], m["usage"])
        if m["ticket"] is not None:
            _add(tickets[(m["project"], m["ticket"])], m["usage"])
    by_project: dict = {}
    for (project, kind), rec in projects.items():
        p = by_project.setdefault(project, {"project": project, **_blank(), "by_kind": {}})
        for f_ in FIELDS:
            p[f_] += rec[f_]
        p["by_kind"][kind] = rec["output"]
    return {
        "generated_at": now.isoformat(), "window_days": window_days, "machine": machine_id(), "files_scanned": len(list(files)),
        "totals": totals,
        "rows": [{"day": d, "kind": k, "model": mo, **rec} for (d, k, mo), rec in sorted(rows.items())],
        "by_project": sorted(by_project.values(), key=lambda p: -p["output"]),
        "by_ticket": sorted(({"project": p, "ticket": t, **rec} for (p, t), rec in tickets.items()), key=lambda x: -x["output"])[:TOP_TICKETS],
    }


def refresh(out_path: Path = OUT_PATH, root: Path = TRANSCRIPTS, window_days: int = WINDOW_DAYS, now=None) -> dict:
    import job_events
    with job_events.job_run("token-usage", "Token usage scan") as run:
        run.step("Finding transcripts", f"last {window_days} days")
        files = find_transcripts(root, window_days, now)
        run.step("Counting tokens", f"{len(files)} files")
        result = aggregate(files, now=now, window_days=window_days)
        run.step("Writing", out_path.name)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(result))
        tmp.replace(out_path)
        t = result["totals"]
        run.summary(f"{t['messages']:,} messages, {t['output']:,} output tokens in {window_days} days")
        return result


def _cli() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh")
    r.add_argument("--days", type=int, default=WINDOW_DAYS)
    sub.add_parser("show")
    a = ap.parse_args()
    if a.cmd == "refresh":
        res = refresh(window_days=a.days)
        print(json.dumps(res["totals"]))
    else:
        data = json.loads(OUT_PATH.read_text())
        print(json.dumps({k: data[k] for k in ("generated_at", "machine", "totals")}, indent=1))
        for p in data["by_project"][:10]:
            print(f"{p['project']:<28}{p['output']:>12,} output tokens")


if __name__ == "__main__":
    _cli()
