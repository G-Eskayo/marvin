#!/usr/bin/env python3
"""Which tools and skills get called, when, how often, and how often it goes wrong.

Source: the Claude Code session transcripts (~/.claude/projects/**/*.jsonl), which record every tool
call (name, input, timestamp) and its result (with an error flag) for interactive sessions, headless
runs and subagents alike. Output (`~/.claude/logs/tool-usage.json`) feeds the Health tab.

"Correct" here means what the data can honestly say: did the call work (ok), fail (error), get
declined by Gil (rejected), get interrupted, or was it an *invalid call* (wrong parameters, a tool
used before its schema was loaded, an unknown skill) -- the clearest sign a tool was used wrongly.
Whether the RIGHT skill fired for a request is a separate judgement (intent classification), not
attempted here.

    tool_usage.py refresh [--days 30] [--if-older-than SECONDS]
    tool_usage.py show
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

HOME = Path.home()
TRANSCRIPTS = HOME / ".claude" / "projects"
OUT_PATH = HOME / ".claude" / "logs" / "tool-usage.json"
MANIFEST = HOME / ".claude" / "manifest.json"
WINDOW_DAYS = 30
MAX_FAILURES = 40

OUTCOMES = ("ok", "error", "rejected", "interrupted", "invalid", "unresolved")
INVALID_MARKERS = ("InputValidationError", "No such tool available", "Unknown skill", "tool_use_error")


def _parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def classify(content, is_error: bool) -> str:
    text = content if isinstance(content, str) else json.dumps(content)
    if "was rejected" in text or "doesn't want to proceed" in text:
        return "rejected"
    if "Request interrupted by user" in text:
        return "interrupted"
    if is_error and any(m in text for m in INVALID_MARKERS):
        return "invalid"
    return "error" if is_error else "ok"


_SKILL_MD = re.compile(r"/skills/([^/]+)/SKILL\.md$")


def _blank():
    return {"calls": 0, **{o: 0 for o in OUTCOMES}, "last_used": None, "by_kind": Counter(), "by_day": Counter(), "via": Counter()}


def _bump(rec, outcome, when, kind):
    rec["calls"] += 1
    rec[outcome] += 1
    rec["by_kind"][kind] += 1
    rec["by_day"][when.date().isoformat()] += 1
    if rec["last_used"] is None or when.isoformat() > rec["last_used"]:
        rec["last_used"] = when.isoformat()


def _finish(table, key_name, extra=None):
    out = []
    for name, rec in table.items():
        row = {key_name: name, **{k: v for k, v in rec.items() if k not in ("by_kind", "by_day", "via")},
               "by_kind": {k: rec["by_kind"].get(k, 0) for k in ("interactive", "headless", "subagent")},
               "by_day": dict(sorted(rec["by_day"].items())),
               "via": {"skill_tool": rec["via"].get("skill_tool", 0), "read": rec["via"].get("read", 0)}}
        if extra:
            row.update(extra(name))
        out.append(row)
    return sorted(out, key=lambda r: (-r["calls"], str(r[key_name])))


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


def aggregate(files, now: datetime | None = None, window_days: int = WINDOW_DAYS, known_skills=()) -> dict:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    tools, skills, servers, agents = (defaultdict(_blank) for _ in range(4))
    failures = []
    for f in files:
        pending = {}  # tool_use_id -> (name, input, when, kind)
        try:
            lines = f.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        for line in lines:
            if '"tool_use' not in line and '"tool_result"' not in line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = (d.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            when = _parse_ts(d.get("timestamp"))
            kind = "subagent" if d.get("isSidechain") else ("interactive" if d.get("entrypoint") in (None, "cli") else "headless")
            for b in content:
                if b.get("type") == "tool_use" and when:
                    pending[b.get("id")] = (b.get("name", "?"), b.get("input") or {}, when, kind)
                elif b.get("type") == "tool_result":
                    use = pending.pop(b.get("tool_use_id"), None)
                    if use is None or use[2] < cutoff:
                        continue
                    name, inp, uwhen, ukind = use
                    outcome = classify(b.get("content"), bool(b.get("is_error")))
                    _record(tools, skills, servers, agents, name, inp, outcome, uwhen, ukind)
                    if outcome in ("error", "invalid", "rejected", "interrupted"):
                        msg = b.get("content")
                        msg = msg if isinstance(msg, str) else json.dumps(msg)
                        failures.append({"tool": name, "at": uwhen.isoformat(), "outcome": outcome, "kind": ukind,
                                         "message": " ".join(msg.split())[:200]})
        for name, inp, uwhen, ukind in pending.values():  # called, never answered (session ended / crashed)
            if uwhen >= cutoff:
                _record(tools, skills, servers, agents, name, inp, "unresolved", uwhen, ukind)
    failures.sort(key=lambda x: x["at"], reverse=True)
    skill_rows = _finish(skills, "name")
    used = {s["name"] for s in skill_rows}
    known = list(known_skills)
    return {
        "generated_at": now.isoformat(), "window_days": window_days, "files_scanned": len(list(files)),
        "tools": _finish(tools, "name"), "skills": skill_rows, "agents": _finish(agents, "name"),
        "mcp_servers": _finish(servers, "server"),
        "inventory": {"known": len(known), "used": len([k for k in known if k in used]),
                      "never_used": [k for k in known if k not in used]},
        "recent_failures": failures[:MAX_FAILURES],
    }


def _record(tools, skills, servers, agents, name, inp, outcome, when, kind):
    _bump(tools[name], outcome, when, kind)
    if name == "Skill" and inp.get("skill"):
        _bump(skills[inp["skill"]], outcome, when, kind)
        skills[inp["skill"]]["via"]["skill_tool"] += 1
    elif name == "Read" and _SKILL_MD.search(str(inp.get("file_path", ""))):
        # MARVIN skills are mostly loaded by reading their SKILL.md (CLAUDE.md's routing table), not via the Skill tool
        sk = _SKILL_MD.search(inp["file_path"]).group(1)
        _bump(skills[sk], outcome, when, kind)
        skills[sk]["via"]["read"] += 1
    elif name.startswith("mcp__"):
        _bump(servers[name.split("__")[1]], outcome, when, kind)
    elif name in ("Agent", "Task") and inp.get("subagent_type"):
        _bump(agents[inp["subagent_type"]], outcome, when, kind)


def known_skill_names(manifest: Path = MANIFEST) -> list[str]:
    """MARVIN's own skills (the manifest's skill entries) -- the ones whose firing we want to verify."""
    try:
        idx = json.loads(manifest.read_text()).get("index", [])
    except (OSError, json.JSONDecodeError):
        return []
    return sorted({e["name"] for e in idx if "type:skill" in e.get("tags", [])})


def refresh(out_path: Path = OUT_PATH, root: Path = TRANSCRIPTS, window_days: int = WINDOW_DAYS, now=None) -> dict:
    import job_events
    with job_events.job_run("tool-usage", "Tool & skill usage scan") as run:
        run.step("Finding transcripts", f"last {window_days} days")
        files = find_transcripts(root, window_days, now)
        run.step("Finding transcripts", f"{len(files)} files")
        run.step("Reading tool calls and results")
        result = aggregate(files, now=now, window_days=window_days, known_skills=known_skill_names())
        run.step("Writing", out_path.name)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(result))
        tmp.replace(out_path)
        run.summary(f"{sum(t['calls'] for t in result['tools'])} calls across {len(result['tools'])} tools; {len(result['recent_failures'])} recent failures")
        return result


def is_stale(path: Path, max_age_s: float, now: datetime | None = None) -> bool:
    try:
        gen = _parse_ts(json.loads(path.read_text()).get("generated_at"))
    except (OSError, json.JSONDecodeError):
        return True
    return gen is None or ((now or datetime.now(timezone.utc)) - gen).total_seconds() > max_age_s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh")
    r.add_argument("--days", type=int, default=WINDOW_DAYS)
    r.add_argument("--if-older-than", type=float, default=0)
    sub.add_parser("show")
    a = ap.parse_args()
    if a.cmd == "refresh":
        if a.if_older_than and not is_stale(OUT_PATH, a.if_older_than):
            print("tool usage is fresh")
            return 0
        res = refresh(window_days=a.days)
        print(f"{sum(t['calls'] for t in res['tools'])} calls, {len(res['tools'])} tools, {res['inventory']['used']}/{res['inventory']['known']} of our skills used")
        return 0
    res = json.loads(OUT_PATH.read_text())
    for t in res["tools"][:25]:
        bad = t["error"] + t["invalid"]
        print(f"{t['name']:<40} {t['calls']:>6} calls  {bad:>4} failed  last {str(t['last_used'])[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
