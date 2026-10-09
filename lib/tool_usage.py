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

OUTCOMES = ("ok", "error", "rejected", "interrupted", "invalid", "unresolved", "expected")
INVALID_MARKERS = ("InputValidationError", "No such tool available", "Unknown skill", "tool_use_error")

# Cause classification rules for failures/invalid calls.
CAUSE_RULES = [
    ("auto-mode classifier denied", r"auto mode classifier|Permission for this action was denied|permission to use .* has been denied|requires approval"),
    ("deferred tool used before schema loaded", r"No such tool available|schema.*not loaded|InputValidationError.*deferred"),
    ("wrong/missing parameters", r"InputValidationError|Invalid input|required parameter|is not of type|Unexpected parameter"),
    ("unknown skill name", r"Unknown skill"),
    ("Edit: old_string not found", r"String to replace not found|old_string.*not found"),
    ("Edit: old_string matches several places", r"Found \d+ matches"),
    ("Edit/Write before Read (or file changed)", r"has not been read yet|modified since read|File has been modified|Read it first"),
    ("file/path doesn't exist", r"does not exist|No such file|ENOENT|not found: /"),
    ("file too large for one read", r"exceeds maximum|too large|token limit"),
    ("is a directory", r"EISDIR|is a directory"),
    ("command timed out", r"timed out|Timeout|timeout after"),
    ("command not found / missing tool", r"command not found|not installed|No module named"),
    ("network / API / rate limit", r"rate limit|429|ECONNREFUSED|Could not resolve|Connection refused|API rate limit|HTTP 5\d\d"),
    ("git error", r"fatal: |CONFLICT|not a git repository"),
    ("tests failed (expected while developing)", r"FAILED|AssertionError|\d+ failed|Test Failed|✘"),
    ("grep/search found nothing (exit 1)", r"^Exit code 1\s*$"),
    ("non-zero exit, other", r"Exit code \d+"),
]
EXPECTED_CAUSES = {"grep/search found nothing (exit 1)", "tests failed (expected while developing)"}

TOOL_PURPOSE = {
    "Bash": "Execute shell commands",
    "Read": "Read file contents",
    "Edit": "Edit file text (find and replace)",
    "Write": "Write or create a file",
    "Glob": "List directory contents",
    "Grep": "Search for text patterns in files",
    "Agent": "Spawn a subagent for complex tasks",
    "Task": "Create or manage tracked tasks",
    "Skill": "Invoke MARVIN's skills or routines",
    "WebFetch": "Fetch web content (HTTP GET)",
    "WebSearch": "Search the web (standard or extended)",
    "NotebookEdit": "Edit Jupyter notebook cells",
    "TodoWrite": "Write to-do lists",
    "ExitPlanMode": "Exit a planning mode",
    "ToolSearch": "Find tools by schema or keywords",
    "ScheduleWakeup": "Schedule work to resume later",
    "Workflow": "Run a multi-agent workflow",
    "SendMessage": "Send messages to other Claude sessions",
    "ListAgents": "List available subagents",
    "Monitor": "Stream output from background processes",
    "CronCreate": "Create a scheduled cron job",
    "CronList": "List scheduled cron jobs",
    "CronDelete": "Delete a scheduled cron job",
}


def _machine_id() -> str:
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


def classify(content, is_error: bool) -> str:
    text = content if isinstance(content, str) else json.dumps(content)
    if "was rejected" in text or "doesn't want to proceed" in text:
        return "rejected"
    if "Request interrupted by user" in text:
        return "interrupted"
    if is_error and any(m in text for m in INVALID_MARKERS):
        return "invalid"
    return "error" if is_error else "ok"


def classify_cause(message: str) -> str:
    """Classify the cause of a failure or invalid call."""
    text = message if isinstance(message, str) else json.dumps(message)
    for cause_name, pattern in CAUSE_RULES:
        if re.search(pattern, text, re.I | re.M):
            return cause_name
    return "other"


_SKILL_MD = re.compile(r"/skills/([^/]+)/SKILL\.md$")


def _blank():
    return {"calls": 0, **{o: 0 for o in OUTCOMES}, "last_used": None, "by_kind": Counter(), "by_day": Counter(), "via": Counter(), "causes": Counter()}


def _bump(rec, outcome, when, kind):
    rec["calls"] += 1
    rec[outcome] += 1
    rec["by_kind"][kind] += 1
    rec["by_day"][when.date().isoformat()] += 1
    if rec["last_used"] is None or when.isoformat() > rec["last_used"]:
        rec["last_used"] = when.isoformat()


def _bump_cause(rec, cause: str):
    """Record a failure cause."""
    rec["causes"][cause] += 1


def _finish(table, key_name, extra=None):
    out = []
    for name, rec in table.items():
        row = {key_name: name, **{k: v for k, v in rec.items() if k not in ("by_kind", "by_day", "via", "causes")},
               "by_kind": {k: rec["by_kind"].get(k, 0) for k in ("interactive", "headless", "subagent")},
               "by_day": dict(sorted(rec["by_day"].items())),
               "via": {"skill_tool": rec["via"].get("skill_tool", 0), "read": rec["via"].get("read", 0)},
               "causes": dict(rec["causes"])}
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


def _extract_input(name: str, inp: dict) -> str:
    """Extract a short summary of what was actually run."""
    if name == "Bash":
        return inp.get("command", "")[:80]
    elif name in ("Read", "Write", "Glob"):
        return inp.get("file_path", "")[:80]
    elif name == "Edit":
        return inp.get("file_path", "")[:80]
    elif name == "Grep":
        return inp.get("pattern", "")[:80]
    elif name == "Skill":
        return inp.get("skill", "")[:80]
    elif isinstance(inp, dict):
        for k, v in inp.items():
            if isinstance(v, str) and v.strip():
                return str(v)[:80]
    return ""


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
                    msg = b.get("content")
                    msg = msg if isinstance(msg, str) else json.dumps(msg)
                    # Classify cause if error or invalid
                    cause = None
                    if outcome in ("error", "invalid"):
                        cause = classify_cause(msg)
                        # Reclassify expected causes
                        if cause in EXPECTED_CAUSES:
                            outcome = "expected"
                    _record(tools, skills, servers, agents, name, inp, outcome, uwhen, ukind, cause=cause)
                    # Add to failures (including expected for auditability)
                    if outcome in ("error", "invalid", "rejected", "interrupted", "expected"):
                        failures.append({
                            "tool": name, "at": uwhen.isoformat(), "outcome": outcome, "kind": ukind,
                            "message": " ".join(msg.split())[:200],
                            "cause": cause or "(unclassified)",
                            "input": _extract_input(name, inp),
                        })
        for name, inp, uwhen, ukind in pending.values():  # called, never answered (session ended / crashed)
            if uwhen >= cutoff:
                _record(tools, skills, servers, agents, name, inp, "unresolved", uwhen, ukind)
    failures.sort(key=lambda x: x["at"], reverse=True)
    # Add purpose to tools and skills
    tool_rows = _finish(tools, "name", extra=lambda n: {"purpose": TOOL_PURPOSE.get(n, "(no description recorded)")})
    skill_rows = _finish(skills, "name", extra=lambda n: {"purpose": skill_purpose(n)})
    used = {s["name"] for s in skill_rows}
    known = list(known_skills)
    return {
        "generated_at": now.isoformat(), "window_days": window_days, "machine": _machine_id(), "files_scanned": len(list(files)),
        "tools": tool_rows, "skills": skill_rows, "agents": _finish(agents, "name"),
        "mcp_servers": _finish(servers, "server"),
        "inventory": {"known": len(known), "used": len([k for k in known if k in used]),
                      "never_used": [k for k in known if k not in used]},
        "recent_failures": failures[:MAX_FAILURES],
    }


def _record(tools, skills, servers, agents, name, inp, outcome, when, kind, cause=None):
    _bump(tools[name], outcome, when, kind)
    if cause:
        _bump_cause(tools[name], cause)
    if name == "Skill" and inp.get("skill"):
        _bump(skills[inp["skill"]], outcome, when, kind)
        skills[inp["skill"]]["via"]["skill_tool"] += 1
        if cause:
            _bump_cause(skills[inp["skill"]], cause)
    elif name == "Read" and _SKILL_MD.search(str(inp.get("file_path", ""))):
        # MARVIN skills are mostly loaded by reading their SKILL.md (CLAUDE.md's routing table), not via the Skill tool
        sk = _SKILL_MD.search(inp["file_path"]).group(1)
        _bump(skills[sk], outcome, when, kind)
        skills[sk]["via"]["read"] += 1
        if cause:
            _bump_cause(skills[sk], cause)
    elif name.startswith("mcp__"):
        _bump(servers[name.split("__")[1]], outcome, when, kind)
        if cause:
            _bump_cause(servers[name.split("__")[1]], cause)
    elif name in ("Agent", "Task") and inp.get("subagent_type"):
        _bump(agents[inp["subagent_type"]], outcome, when, kind)
        if cause:
            _bump_cause(agents[inp["subagent_type"]], cause)


def known_skill_names(manifest: Path = MANIFEST) -> list[str]:
    """MARVIN's own skills (the manifest's skill entries) -- the ones whose firing we want to verify."""
    try:
        idx = json.loads(manifest.read_text()).get("index", [])
    except (OSError, json.JSONDecodeError):
        return []
    return sorted({e["name"] for e in idx if "type:skill" in e.get("tags", [])})


_SKILL_PURPOSE_CACHE = {}


def skill_purpose(name: str, manifest: Path = MANIFEST) -> str:
    """Get the purpose/description of a skill from its SKILL.md frontmatter."""
    if name in _SKILL_PURPOSE_CACHE:
        return _SKILL_PURPOSE_CACHE[name]
    try:
        idx = json.loads(manifest.read_text()).get("index", [])
    except (OSError, json.JSONDecodeError):
        return "(no description recorded)"
    skill = next((e for e in idx if e.get("name") == name and "type:skill" in e.get("tags", [])), None)
    if not skill:
        return "(no description recorded)"
    path = Path(skill["path"].replace("~", str(HOME)))
    try:
        if not path.exists():
            return "(no description recorded)"
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import skill_index
        fm = skill_index.frontmatter(path)
        desc = fm.get("description", "")
        purpose = skill_index.one_line(desc) if desc else "(no description recorded)"
        _SKILL_PURPOSE_CACHE[name] = purpose
        return purpose
    except Exception:  # noqa: BLE001
        return "(no description recorded)"


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
