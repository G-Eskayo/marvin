#!/usr/bin/env python3
"""session_work.py — what each MARVIN session on this Mac is working on, so two sessions don't build the same thing
(#326, ADR 0062, docs/plans/session-awareness-2026-10-09.md).

On 2026-10-08/09 two interactive sessions (two WezTerm tabs) and the mini's pipeline fixed the same problems in
parallel, because nothing said "I'm on this". Hooks now keep a small live list, ~/.claude/logs/sessions-active.json:

  prompt  (UserPromptSubmit)        the session's latest request
  post    (PostToolUse Edit|Write)  a file it edited, keyed by repo + path, so a worktree copy and the shared checkout
                                    are the same file; the first edit in a repo whose request names exactly one ticket
                                    claims that ticket (if it is ready-for-agent and unclaimed), so the pipeline skips it
  pre     (PreToolUse Edit|Write)   before an interactive session edits a file another live session (active in the
                                    last 45 minutes) edited, the edit pauses and asks, naming what the other is doing.
                                    Once per file per pair of sessions.

Runs on every edit, so standard library only, and any failure lets the edit through (it never blocks on its own bugs).
    session_work.py hook prompt|pre|post     (reads the hook payload on stdin)
    session_work.py list                     the live sessions and their files
"""
from __future__ import annotations
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

STATE_PATH = Path.home() / ".claude" / "logs" / "sessions-active.json"
LIVE_S = 45 * 60
KEEP_S = 4 * 3600
CLAIM_LOG = Path.home() / ".claude" / "logs" / "session-claims.log"


# ── which file is this, across worktrees ────────────────────────────────────

def file_key(path: str) -> tuple[str | None, str]:
    """(repository id, path inside it). Every worktree of a repo shares one id (its common .git folder)."""
    p = Path(path).expanduser()
    d = p.parent
    while True:
        g = d / ".git"
        if g.is_dir():
            return str(g.resolve()), str(p.resolve().relative_to(d.resolve())) if p.exists() else os.path.relpath(p, d)
        if g.is_file():
            try:
                gitdir = Path(g.read_text().split("gitdir:", 1)[1].strip())
                gitdir = gitdir if gitdir.is_absolute() else (d / gitdir)
                common = gitdir / "commondir"
                repo = (gitdir / common.read_text().strip()).resolve() if common.exists() else gitdir.resolve()
                return str(repo), os.path.relpath(p, d)
            except (OSError, IndexError):
                return None, str(p)
        if d.parent == d:
            return None, str(p)
        d = d.parent


def _k(key) -> str:
    return f"{key[0] or ''}|{key[1]}"


# ── the list (pure) ─────────────────────────────────────────────────────────

def _session(st: dict, sid: str) -> dict:
    return st.setdefault("sessions", {}).setdefault(sid, {"request": "", "last": 0, "files": {}, "claimed": []})


def record_prompt(st: dict, sid: str, prompt: str, now: float) -> None:
    s = _session(st, sid)
    s["request"] = " ".join((prompt or "").split())[:200]
    s["last"] = now


def record_edit(st: dict, sid: str, key, now: float) -> None:
    s = _session(st, sid)
    s["files"][_k(key)] = now
    s["last"] = now


def overlaps(st: dict, sid: str, key, now: float) -> list[dict]:
    k = _k(key)
    out = []
    for other, s in (st.get("sessions") or {}).items():
        if other == sid or now - s.get("last", 0) > LIVE_S or k not in s.get("files", {}):
            continue
        out.append({"session": other, "request": s.get("request", ""), "file_at": s["files"][k]})
    return out


def pre_edit(st: dict, sid: str, key, now: float) -> str | None:
    """Why this edit should pause, or None. Each (this session, other session, file) is asked about once."""
    asked = st.setdefault("asked", {})
    new = [o for o in overlaps(st, sid, key, now) if f"{sid}|{o['session']}|{_k(key)}" not in asked]
    if not new:
        return None
    for o in new:
        asked[f"{sid}|{o['session']}|{_k(key)}"] = now
    lines = [f"Another MARVIN session on this Mac edited {key[1]} {max(0, int((now - o['file_at']) / 60))} min ago"
             + (f'. It is working on: "{o["request"]}"' if o["request"] else "") for o in new]
    return ("; ".join(lines) + ". Check it isn't building the same thing before going on "
            "(this is asked once per file; ~/.agents/lib/session_work.py list shows every live session).")


def prune(st: dict, now: float) -> None:
    st["sessions"] = {k: v for k, v in (st.get("sessions") or {}).items() if now - v.get("last", 0) <= KEEP_S}
    st["asked"] = {k: v for k, v in (st.get("asked") or {}).items() if now - v <= KEEP_S}


def ticket_in(text: str) -> int | None:
    """The one ticket a request names (#123), or None when it names none or several."""
    found = set(re.findall(r"#(\d+)\b", text or ""))
    return int(found.pop()) if len(found) == 1 else None


def claim_wanted(st: dict, sid: str, repo: str | None) -> int | None:
    """The ticket to claim on this session's first edit in `repo`, once."""
    s = _session(st, sid)
    if repo is None or repo in s["claimed"]:
        return None
    s["claimed"].append(repo)
    return ticket_in(s.get("request", ""))


# ── state file + hook entry points ──────────────────────────────────────────

class _Locked:
    def __enter__(self) -> dict:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.lock = open(STATE_PATH.with_suffix(".lock"), "a+")
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        try:
            self.st = json.loads(STATE_PATH.read_text())
            if not isinstance(self.st, dict):
                raise ValueError
        except (OSError, ValueError):
            self.st = {}
        return self.st

    def __exit__(self, exc_type, *_):
        try:
            if exc_type is None:
                tmp = STATE_PATH.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.st))
                tmp.replace(STATE_PATH)
        finally:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()
        return False


def _repo_top(path: str) -> str | None:
    d = Path(path).expanduser().parent
    while d.parent != d:
        if (d / ".git").exists():
            return str(d)
        d = d.parent
    return None


def _start_claim(top: str, ticket: int) -> None:
    subprocess.Popen([sys.executable, __file__, "claim", top, str(ticket)], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def handle(kind: str, payload: dict, now: float | None = None) -> str | None:
    """Returns what the hook should print (only `pre` ever prints, and only to ask)."""
    now = now if now is not None else time.time()
    sid = str(payload.get("session_id") or "")
    if not sid:
        return None
    try:
        with _Locked() as st:
            prune(st, now)
            if kind == "prompt":
                record_prompt(st, sid, payload.get("prompt", ""), now)
                return None
            path = (payload.get("tool_input") or {}).get("file_path") or (payload.get("tool_input") or {}).get("notebook_path")
            if not path:
                return None
            key = file_key(path)
            if kind == "post":
                record_edit(st, sid, key, now)
                ticket = claim_wanted(st, sid, key[0])
                top = _repo_top(path)
                if ticket and top:
                    _start_claim(top, ticket)
                return None
            if kind == "pre":
                why = pre_edit(st, sid, key, now)
                if why:
                    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                                              "permissionDecisionReason": why}})
    except Exception:  # noqa: BLE001 -- never block an edit on this module's own failure
        return None
    return None


def claim(top: str, ticket: int) -> str:
    """Claim `ticket` in the repo checked out at `top` for this Mac, if it is open, ready-for-agent and unclaimed."""
    try:
        url = subprocess.run(["git", "-C", top, "remote", "get-url", "origin"], capture_output=True, text=True, timeout=10).stdout
        m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?\s*$", url)
        if not m:
            return "no GitHub origin"
        repo = m.group(1)
        env = dict(os.environ)
        tok = Path.home() / ".claude" / ".gh-token"
        if not env.get("GH_TOKEN") and tok.exists():
            env["GH_TOKEN"] = tok.read_text().strip()
        info = json.loads(subprocess.run(["gh", "issue", "view", str(ticket), "--repo", repo, "--json", "state,labels"],
                                         capture_output=True, text=True, timeout=30, env=env).stdout)
        names = {l["name"] for l in info.get("labels", [])}
        if info.get("state") != "OPEN" or "ready-for-agent" not in names or any(n.startswith("claimed:") for n in names):
            return f"{repo}#{ticket}: left alone ({info.get('state')}, labels {sorted(names)})"
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import machine_profile
        label = f"claimed:{machine_profile.machine_label()}"
        done = subprocess.run(["gh", "issue", "edit", str(ticket), "--repo", repo, "--add-label", label],
                              capture_output=True, text=True, timeout=30, env=env)
        return f"{repo}#{ticket}: {'claimed ' + label if done.returncode == 0 else 'claim failed: ' + done.stderr[-200:]}"
    except Exception as e:  # noqa: BLE001
        return f"claim of #{ticket} failed: {e}"


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "hook":
        try:
            payload = json.load(sys.stdin)
        except ValueError:
            return 0
        out = handle(argv[1], payload)
        if out:
            print(out)
        return 0
    if len(argv) == 3 and argv[0] == "claim":
        msg = claim(argv[1], int(argv[2]))
        try:
            with open(CLAIM_LOG, "a") as f:
                f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}\n")
        except OSError:
            pass
        return 0
    if argv[:1] == ["list"]:
        now = time.time()
        with _Locked() as st:
            prune(st, now)
            for sid, s in sorted(st.get("sessions", {}).items(), key=lambda kv: -kv[1].get("last", 0)):
                live = "live" if now - s.get("last", 0) <= LIVE_S else "quiet"
                print(f"{sid[:8]} {live:<5} {int((now - s.get('last', 0)) / 60):>3} min ago  {s.get('request', '')[:80]}")
                for f in sorted(s.get("files", {}), key=lambda f: -s["files"][f])[:6]:
                    print(f"           {f.split('|', 1)[1]}")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
