#!/usr/bin/env python3
"""chat_helpers.py: background helpers a chat starts show in the Activity tab (#612).

When Claude, inside an interactive chat, starts a helper with the Agent tool, nothing in the dashboard showed it
(2026-10-22: "where is the investigation running?"). Claude Code's hooks now give each helper a run log in the
same format and folder as every background job (`lib/job_events.py`, ~/.claude/logs/jobs/helper-<agent id>.json).
That folder is already watched, so each write is the dashboard's trigger: nothing polls.

  start     (SubagentStart)              the helper exists: running, which chat it came from, which Mac
  launched  (PostToolUse Agent)          the Agent tool's result names it (its `description`)
  report    (PreToolUse SubagentHandback) the helper's final report, held until it stops
  stop      (SubagentStop)               done (a one-line summary, and the tickets/PRs its report names) or
                                         failed (it ended with no result at all)

A helper killed mid-run sends no stop. It is "stale" once its own transcript has been quiet for STALE_S, measured
by whoever reads the log (`state_of`, and the same rule in dashboard/electron/main/jobs.js), never "running" forever.

Cost: one ~2 KB file per helper, the newest KEEP kept per Mac (about 60 KB); each hook is one short read-modify-write
of that one file. Runs inside a person's chat, so: standard library only, a hard ALARM_S cap, no stdout, exit 0 on
anything at all. A failing hook must never block or slow a chat.

    chat_helpers.py hook start|launched|report|stop     (reads the hook payload on stdin)
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import signal
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

PREFIX = "helper-"
KEEP = 30
STALE_S = 15 * 60
SUMMARY_CHARS = 200
MAX_LINKS = 12
LOCK_WAIT_S = 1.0
ALARM_S = 3
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _home() -> Path:
    return Path.home() / ".claude"


def _jobs_dir() -> Path:
    return _home() / "logs" / "jobs"


def _sessions_path() -> Path:
    return _home() / "logs" / "sessions-active.json"


def _machine() -> str:
    try:
        return str(json.loads((_home() / "machine-profile.json").read_text()).get("label") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def _str(v) -> str:
    return v if isinstance(v, str) else ""


def _agent_id(v) -> str | None:
    aid = _str(v)
    aid = aid[len("agent-"):] if aid.startswith("agent-") else aid
    return aid if _ID.match(aid) else None


# ── what the result says ────────────────────────────────────────────────────

_CODE = re.compile(r"```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`")
_URL = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/(issues|pull)/(\d{1,6})")
_QUALIFIED = re.compile(r"\b([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d{1,6})(?![\w-])")
_BARE = re.compile(r"(?<![\w/&#])#(\d{1,6})(?![\w-])")


def links_in(text: str) -> list[dict]:
    """Tickets and PRs a result names, derived from its text (relations are derived, not stored by hand): GitHub
    issue/PR URLs, owner/repo#n, and a bare #n, which belongs to the first repo the text names (left out if none)."""
    clean = _CODE.sub(" ", text or "")
    out: list[dict] = []

    def add(kind, repo, n):
        item = {"kind": kind, "repo": repo, "number": int(n)}
        if item not in out and not any(o["repo"] == repo and o["number"] == int(n) for o in out):
            out.append(item)

    for m in _URL.finditer(clean):
        add("pr" if m.group(2) == "pull" else "ticket", m.group(1), m.group(3))
    rest = _URL.sub(" ", clean)
    for m in _QUALIFIED.finditer(rest):
        add("ticket", m.group(1), m.group(2))
    home_repo = out[0]["repo"] if out else None
    if home_repo:
        for m in _BARE.finditer(_QUALIFIED.sub(" ", rest)):
            add("ticket", home_repo, m.group(1))
    return out[:MAX_LINKS]


def summary_of(text: str) -> str:
    """The result's first line of prose, markdown marks dropped, cut to SUMMARY_CHARS."""
    for line in (text or "").splitlines():
        line = re.sub(r"^\s*(?:#+|>+|[-*+](?=\s))\s*", "", line)
        line = re.sub(r"\*\*|__|`", "", line).strip()
        if line:
            line = " ".join(line.split())
            return line if len(line) <= SUMMARY_CHARS else line[: SUMMARY_CHARS - 1].rstrip() + "…"
    return ""


# ── the run log ─────────────────────────────────────────────────────────────

def _now_iso(now: datetime | None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


def _new_doc(aid: str, payload: dict, sessions_path: Path, machine: str, now: datetime | None) -> dict:
    parent = _str(payload.get("transcript_path"))
    transcript = str(Path(parent).with_suffix("") / "subagents" / f"agent-{aid}.jsonl") if parent else ""
    meta = {}
    if transcript:
        try:
            meta = json.loads(Path(transcript).with_name(f"agent-{aid}.meta.json").read_text()[:20_000])
            meta = meta if isinstance(meta, dict) else {}
        except (OSError, ValueError):
            meta = {}
    session = _str(payload.get("session_id"))
    chat = ""
    try:
        chat = _str(json.loads(sessions_path.read_text())["sessions"][session]["request"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    kind = _str(payload.get("agent_type")) or _str(meta.get("agentType"))
    return {
        "job": PREFIX + aid,
        "label": _str(meta.get("description"))[:120] or kind or "helper",
        "kind": "helper",
        "helper": {"agent_id": aid, "agent_type": kind, "session": session, "chat": chat[:200], "machine": machine,
                   "cwd": _str(payload.get("cwd")), "transcript": transcript, "links": []},
        "runs": [{"id": uuid.uuid4().hex[:8], "status": "running", "started_at": _now_iso(now), "finished_at": None,
                  "steps": [{"step": "working", "detail": "", "at": _now_iso(now)}], "summary": "", "error": ""}],
    }


def _lock(jobs_dir: Path, aid: str):
    f = open(jobs_dir / f".{PREFIX}{aid}.lock", "w")
    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except BlockingIOError:
            if time.monotonic() > deadline:
                f.close()
                raise TimeoutError("lock busy")
            time.sleep(0.01)


def _update(aid: str, payload: dict, fn, *, jobs_dir: Path, sessions_path: Path, machine: str,
            now: datetime | None, create: bool = True) -> bool:
    """Read-modify-write one helper's log under its own lock (helpers never share a file)."""
    jobs_dir.mkdir(parents=True, exist_ok=True)
    path = jobs_dir / f"{PREFIX}{aid}.json"
    lock = _lock(jobs_dir, aid)
    try:
        try:
            doc = json.loads(path.read_text())
            if not (isinstance(doc, dict) and isinstance(doc.get("runs"), list) and doc["runs"]
                    and isinstance(doc.get("helper"), dict)):
                raise ValueError("bad shape")
        except (OSError, ValueError):
            if not create:
                return False
            doc = _new_doc(aid, payload, sessions_path, machine, now)
        fn(doc, doc["runs"][-1])
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(doc))
        os.replace(tmp, path)
        return True
    finally:
        lock.close()


def state_of(doc: dict, now: float | None = None) -> str:
    """running | stale | passed | failed. A running helper whose transcript (or, without one, its start) is older
    than STALE_S was killed without a stop event."""
    run = (doc.get("runs") or [{}])[-1]
    status = run.get("status")
    if status != "running":
        return status or "failed"
    now = time.time() if now is None else now
    beat = 0.0
    try:
        beat = datetime.fromisoformat(run.get("started_at")).timestamp()
    except (TypeError, ValueError):
        pass
    try:
        beat = max(beat, os.stat((doc.get("helper") or {}).get("transcript") or "").st_mtime)
    except (OSError, TypeError, ValueError):
        pass
    return "running" if now - beat <= STALE_S else "stale"


def prune(jobs_dir: Path, keep: int = KEEP, now: float | None = None) -> None:
    """Keep the newest `keep` helper logs (by last write); a helper still running is never removed."""
    try:
        files = sorted(jobs_dir.glob(f"{PREFIX}*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for p in files[keep:]:
        try:
            if state_of(json.loads(p.read_text()), now) == "running":
                continue
        except (OSError, ValueError, AttributeError):
            pass
        for gone in (p, jobs_dir / f".{p.stem}.lock"):
            try:
                gone.unlink()
            except OSError:
                pass


def handle(event: str, raw: str, *, jobs_dir: Path | None = None, sessions_path: Path | None = None,
           machine: str | None = None, now: datetime | None = None) -> None:
    """Apply one hook event. Never raises: anything odd is dropped."""
    try:
        payload = json.loads(raw or "")
    except ValueError:
        return
    if not isinstance(payload, dict):
        return
    jobs_dir = jobs_dir or _jobs_dir()
    kw = {"jobs_dir": jobs_dir, "sessions_path": sessions_path or _sessions_path(),
          "machine": _machine() if machine is None else machine, "now": now}
    try:
        if event == "start":
            aid = _agent_id(payload.get("agent_id"))
            if not aid or not _str(payload.get("agent_type")):
                return  # internal agents (/btw, prompt suggestions) have no type: not a helper
            _update(aid, payload, lambda d, r: None, **kw)
            prune(jobs_dir, now=now.timestamp() if now else None)
        elif event == "launched":
            resp = payload.get("tool_response")
            resp = resp if isinstance(resp, dict) else {}
            aid = _agent_id(resp.get("agentId"))
            tin = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
            desc = (_str(resp.get("description")) or _str(tin.get("description")))[:120]
            if aid and desc:
                _update(aid, payload, lambda d, r: d.update(label=desc), **kw)
        elif event == "report":
            aid = _agent_id(payload.get("agent_id"))
            tin = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
            message = _str(tin.get("message"))[:20_000]
            if aid and message:
                _update(aid, payload, lambda d, r: d["helper"].update(report=message), create=False, **kw)
        elif event == "stop":
            aid = _agent_id(payload.get("agent_id"))
            if not aid:
                return
            exists = (jobs_dir / f"{PREFIX}{aid}.json").exists()
            if not exists and not _str(payload.get("agent_type")):
                return

            def finish(d, r):
                text = d["helper"].pop("report", "") or _str(payload.get("last_assistant_message"))
                summary = summary_of(text)
                d["helper"]["links"] = links_in(text[:20_000])
                r.update(finished_at=_now_iso(now), summary=summary,
                         status="passed" if summary else "failed",
                         error="" if summary else "ended without a result")
            _update(aid, payload, finish, **kw)
    except Exception:  # noqa: BLE001 -- observing a chat must never break it
        return


def _bail(*_):
    os._exit(0)


def main(argv: list[str]) -> int:
    signal.signal(signal.SIGALRM, _bail)
    signal.alarm(ALARM_S)
    try:
        if argv[:1] == ["hook"] and len(argv) >= 2:
            handle(argv[1], sys.stdin.read(200_000))
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
