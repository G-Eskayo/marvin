#!/usr/bin/env python3
"""stale-relay: caught vs leaked stale claims, per Mac, per week (marvin#1224; piece 4 of
instance/docs/plans/data-freshness-2026-11-09.md). The measure that says whether the freshness pieces work.

  caught   distinct (handoff, item) pairs the resume check (#1221) found changed since a handoff was written, from
           ~/.agents/var/resume-checks.jsonl. Above zero means the check is stopping stale claims before Gil sees them.
  leaked   a stale claim that reached the owner anyway: question-log entries with kind=stale (`question_log.py add --kind
           stale`, whenever the owner corrects an "already fixed" claim), plus the owner's own interactive replies that say so
           ("that's already fixed", "this is old"). Target: 0 for two weeks running.

The reply scan is deliberately narrow (precision over recall; the question log catches what it misses): only
interactive (`entrypoint: cli`) user text, not subagents, tool results or system text; a reply of at most MAX_REPLY
characters (a pasted prompt or document isn't a reply); quoted lines (`>`) and quoted strings dropped; and only the
claim shape "that/this/it ... already fixed/done/merged/restored" or "that's old/out of date". "I've already done the
design" (the owner reporting his own work) doesn't match. Over the 30 days to 2026-11-09 it found two, both real.

Transcripts are this Mac's own (they don't sync), deduplicated by message uuid, and cached per file by size and
mtime (~450 MB a week here), so a sweep rereads only what changed. A week with no sessions, no checks and no log
entries is **unknown**, never 0. Each Mac counts itself; another Mac is asked over ssh with one fixed command.

    stale_relay.py week [--local]    # this Mac's week as JSON (--local), or every Mac's
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

HOME = Path(os.environ.get("HOME", str(Path.home())))
TRANSCRIPTS = HOME / ".claude" / "projects"
VAR = HOME / ".agents" / "var"
RESUME_LOG = VAR / "resume-checks.jsonl"
CACHE = VAR / "stale-relay-cache.json"
WINDOW_DAYS = 7
MAX_REPLY = 800
CHECK_ID, CHECK_LABEL = "freshness:stale-relay", "Stale claims: caught vs leaked (this week)"
UTC = timezone.utc

_DONE = r"(?:fixed|done|merged|restored|closed|solved|resolved|shipped|handled|finished)"
CORRECTION = re.compile(
    r"\b(?:that|this|it|which|those|these|they)(?:'s|’s| is| was| were| are| has been| have been| had been| got)?"
    r"\s+already\s+(?:been\s+)?" + _DONE + r"\b"
    r"|\b(?:that|this)(?:'s|’s| is| was)\s+(?:old|out of date|outdated|stale|old news)\b"
    r"|\balready (?:fixed|merged|restored|resolved) (?:that|this|it)\b", re.IGNORECASE)
_QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”|`[^`]*`')
_KEYS = ("caught", "leaked", "logged", "said", "sessions")


def _time(value) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def is_correction(text: str) -> bool:
    """The owner's reply says a relayed claim was already done or out of date."""
    if not isinstance(text, str) or len(text) > MAX_REPLY or text.lstrip().startswith(("<", "Caveat:", "[Request")):
        return False
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(">")]
    return bool(CORRECTION.search(_QUOTED.sub(" ", "\n".join(lines))))


def _user_text(d: dict) -> str | None:
    """The text the owner typed in an interactive session, or None for anything else."""
    if d.get("type") != "user" or d.get("entrypoint") != "cli" or d.get("isSidechain") or d.get("isMeta"):
        return None
    content = (d.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text") or None
    return None


def _scan(path: Path) -> dict:
    """One transcript: its last interactive user message time and its corrections [[uuid, time]]."""
    last, found = None, []
    try:
        with path.open(errors="ignore") as f:
            for line in f:
                if '"user"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                text = _user_text(d) if isinstance(d, dict) else None
                if text is None:
                    continue
                t = d.get("timestamp")
                if _time(t) and (last is None or _time(t) > _time(last)):
                    last = t
                if is_correction(text):
                    found.append([str(d.get("uuid") or f"{path.name}:{t}"), t])
    except OSError:
        pass
    return {"last_user": last, "corrections": found}


def _transcripts(root: Path, cut: datetime, cache_path: Path) -> list[dict]:
    try:
        cache = json.loads(cache_path.read_text())
        cache = cache if isinstance(cache, dict) else {}
    except (OSError, ValueError):
        cache = {}
    fresh, out = {}, []
    for p in (root.rglob("*.jsonl") if root.is_dir() else []):
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_mtime < cut.timestamp():
            continue
        key, sig = str(p), [st.st_size, st.st_mtime]
        hit = cache.get(key)
        entry = hit if isinstance(hit, dict) and hit.get("sig") == sig else {"sig": sig, **_scan(p)}
        fresh[key] = entry
        out.append(entry)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(fresh))
    except OSError:
        pass
    return out


def _rows(path: Path):
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            yield row


def week(now: datetime | None = None, days: float = WINDOW_DAYS, *, machine: str | None = None,
         transcripts: Path = TRANSCRIPTS, resume_log: Path = RESUME_LOG, question_log: Path | None = None,
         cache: Path = CACHE) -> dict:
    """This Mac's numbers for the `days` before `now`."""
    import question_log as ql
    now = now or datetime.now(UTC)
    cut = now - timedelta(days=days)
    if machine is None:
        import machine_profile
        machine = machine_profile.registry_id()

    caught = set()
    for row in _rows(resume_log):
        t = _time(row.get("at"))
        keys = row.get("changed_keys")
        if t and cut <= t <= now and isinstance(keys, list):
            caught |= {(str(row.get("handoff")), str(k)) for k in keys}
    logged = sum(1 for row in _rows(Path(question_log) if question_log else ql.default_path())
                 if row.get("kind") == "stale" and (t := _time(row.get("ts"))) and cut <= t <= now)
    said, sessions = set(), 0
    for entry in _transcripts(transcripts, cut, cache):
        last = _time(entry.get("last_user"))
        if last and last >= cut:
            sessions += 1
        for uuid, t in entry.get("corrections") or []:
            when = _time(t)
            if when and cut <= when <= now:
                said.add(uuid)
    out = {"machine": machine, "caught": len(caught), "logged": logged, "said": len(said)}
    out["leaked"] = out["logged"] + out["said"]
    out["sessions"] = sessions
    out["known"] = bool(sessions or caught or logged or said)
    return out


def _remote(host: str) -> str:
    """One fixed command on another Mac: nothing from data reaches the shell."""
    cmd = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", host,
           "~/.agents/venv/bin/python ~/.agents/lib/stale_relay.py week --local"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise OSError(f"exit {p.returncode}")
    return p.stdout


def everywhere(now: datetime | None = None, *, macs=None, remote=_remote, local=None) -> list[dict]:
    """This Mac's week, then each other Mac's; a Mac that can't answer is unknown, never 0 and never a crash."""
    per = [local() if local else week(now)]
    if macs is None:
        import purpose_metrics
        macs = list(purpose_metrics._macs())
    for device_id, host in macs:
        try:
            raw = remote(host)
        except (subprocess.SubprocessError, OSError) as e:
            per.append({"machine": device_id, "known": False, "error": f"unreachable ({e.__class__.__name__})"})
            continue
        try:
            got = json.loads(raw.strip().splitlines()[-1])
            if not isinstance(got, dict) or not all(isinstance(got.get(k), int) for k in _KEYS):
                raise ValueError
            per.append({**{k: got[k] for k in _KEYS}, "known": bool(got.get("known")), "machine": device_id})
        except (ValueError, IndexError):
            per.append({"machine": device_id, "known": False, "error": "unreadable reply"})
    return per


def row(per: list[dict], now: datetime | None = None) -> dict:
    """The Vitals row: caught vs leaked this week, every Mac named."""
    now = now or datetime.now(UTC)
    known = [p for p in per if p.get("known")]
    parts = []
    for p in per:
        if p.get("known"):
            said = f" ({p['said']} said in a reply)" if p.get("said") else ""
            parts.append(f"{p['machine']}: caught {p['caught']}, leaked {p['leaked']}{said}")
        else:
            parts.append(f"{p['machine']}: unknown ({p.get('error') or 'no sessions'})")
    caught, leaked = sum(p["caught"] for p in known), sum(p["leaked"] for p in known)
    sev = "unknown" if not known else ("yellow" if leaked else "green")
    head = "no Mac had a session to measure this week" if not known else f"caught {caught}, leaked {leaked}"
    return {"id": CHECK_ID, "label": CHECK_LABEL, "severity": sev, "detail": f"{head} · " + "; ".join(parts),
            "checked_at": now.isoformat(), "value": leaked if known else None}


def main(argv: list[str]) -> int:
    if argv[:1] != ["week"]:
        print("usage: stale_relay.py week [--local]", file=sys.stderr)
        return 2
    print(json.dumps(week() if "--local" in argv else everywhere()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
