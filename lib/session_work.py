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
  stop|notify|ask|tool|end          a chat tab's state: working, waiting (permission or question), your-turn, done
                                    (marvin#1061; the order is explained above STATE_EVENTS)
  start   (SessionStart)            a chat tab (marvin#1060, PRD #1058): an interactive session in a WezTerm pane is
                                    recorded under "chats", keyed by (Mac, WezTerm GUI socket, pane) and checked
                                    against the pane's tty. The pane owns the record: /clear or a resume in the same
                                    pane just updates its session id. Chats are never pruned by age; `chats` lists
                                    only those WezTerm and the claude process say are alive, and drops the rest.

Runs on every edit, so standard library only, and any failure lets the edit through (it never blocks on its own bugs).
    session_work.py hook prompt|pre|post     (reads the hook payload on stdin)
    session_work.py list                     the live sessions and their files
    session_work.py chats [--json]           the live chat tabs on this Mac (bin/marvin-chats)
"""
from __future__ import annotations
import fcntl
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

STATE_PATH = Path.home() / ".claude" / "logs" / "sessions-active.json"
LIVE_S = 45 * 60
KEEP_S = 4 * 3600
CLAIM_LOG = Path.home() / ".claude" / "logs" / "session-claims.log"
REMOTE_PORT = 7878
REMOTE_TIMEOUT_S = 0.3
REMOTE_CACHE_S = 60


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


# ── remote peers (cross-Mac visibility) ─────────────────────────────────────

def _my_hardware_uuid() -> str:
    """This machine's hardware UUID from cache, "" on any error (never blocks)."""
    try:
        p = Path.home() / ".claude" / "machine-profile.json"
        if p.exists():
            return json.loads(p.read_text()).get("hardware_uuid", "")
    except (OSError, ValueError):
        pass
    return ""


def remote_peers(registry_path: str | None = None) -> dict[str, dict]:
    """Map of {device_id: info} for every peer (other hardware_uuid in the registry), never a crash."""
    registry_path = registry_path or str(Path.home() / ".claude" / "marvin-network.json")
    my_uuid = _my_hardware_uuid()
    try:
        with open(registry_path) as f:
            registry = json.load(f)
        if not isinstance(registry, dict):
            return {}
        return {
            device_id: info
            for device_id, info in registry.items()
            if isinstance(info, dict) and info.get("hardware_uuid") != my_uuid and info.get("hardware_uuid")
            and info.get("tailscale_hostname")
        }
    except (OSError, ValueError):
        return {}


def fetch_remote_sessions(host: str, port: int = REMOTE_PORT, timeout: float = REMOTE_TIMEOUT_S) -> dict | None:
    """Fetch live sessions from a remote machine's webhook server, return None on any failure (never raises)."""
    try:
        url = f"http://{host}:{port}/sessions"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read())
            sessions = data.get("sessions")
            if not isinstance(sessions, dict):
                return None
            for s in sessions.values():
                if not isinstance(s, dict) or not isinstance(s.get("files", {}), dict):
                    return None
            return sessions
    except (OSError, urllib.error.URLError, socket.timeout, socket.gaierror, json.JSONDecodeError, ValueError):
        return None


def remote_sessions(st: dict, now: float, peers: dict | None = None,
                   fetch: callable | None = None) -> dict[str, dict]:
    """Cached remote sessions by device_id, re-fetching at most once per REMOTE_CACHE_S across all callers."""
    peers = peers or remote_peers()
    fetch = fetch or fetch_remote_sessions
    remote = st.setdefault("remote", {})
    out = {}
    for device_id, info in peers.items():
        host = info.get("tailscale_hostname")
        if not host:
            continue
        cached = remote.get(device_id, {})
        fetched_at = cached.get("fetched_at", 0)
        if now - fetched_at < REMOTE_CACHE_S:
            sessions = cached.get("sessions", {})
        else:
            sessions = fetch(host) or {}
            remote[device_id] = {"fetched_at": now, "sessions": sessions}
        out[device_id] = sessions
    return out


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


def overlaps(st: dict, sid: str, key, now: float, remote: dict | None = None) -> list[dict]:
    k = _k(key)
    out = []
    for other, s in (st.get("sessions") or {}).items():
        if other == sid or now - s.get("last", 0) > LIVE_S or k not in s.get("files", {}):
            continue
        out.append({"session": other, "request": s.get("request", ""), "file_at": s["files"][k]})
    if remote:
        for device_id, sessions in remote.items():
            for other, s in (sessions or {}).items():
                if now - s.get("last", 0) > LIVE_S or k not in s.get("files", {}):
                    continue
                out.append({"session": other, "request": s.get("request", ""), "file_at": s["files"][k], "machine": device_id})
    return out


def live_edits_for(repo_id: str, paths: list[str], now: float) -> list[dict]:
    """Sessions with a live (<= LIVE_S) edit to repo_id+path, for any path in `paths` — the
    lease code_sync waits on before committing. Fails open per session: a malformed entry is
    skipped, never raised, so one broken session can't hide a real lease held by a well-formed
    sibling, and can't crash the caller either."""
    try:
        with _Locked() as st:
            prune(st, now)
            out = []
            for sid, s in (st.get("sessions") or {}).items():
                try:
                    if not isinstance(s, dict):
                        continue
                    last = s.get("last", 0)
                    if not isinstance(last, (int, float)) or now - last > LIVE_S:
                        continue
                    files = s.get("files")
                    if not isinstance(files, dict):
                        continue
                    for p in paths:
                        ts = files.get(_k((repo_id, p)))
                        if not isinstance(ts, (int, float)) or now - ts > LIVE_S:
                            continue
                        req = s.get("request", "")
                        out.append({"session": sid, "path": p, "edited_at": ts,
                                    "request": req if isinstance(req, str) else ""})
                except Exception:
                    continue
            return out
    except Exception:
        return []


def pre_edit(st: dict, sid: str, key, now: float, remote: dict | None = None) -> str | None:
    """Why this edit should pause, or None. Each (this session, other session, file) is asked about once."""
    asked = st.setdefault("asked", {})
    all_overlaps = overlaps(st, sid, key, now, remote)
    new = [o for o in all_overlaps if f"{sid}|{o.get('machine') or ''}|{o['session']}|{_k(key)}" not in asked]
    if not new:
        return None
    for o in new:
        asked[f"{sid}|{o.get('machine') or ''}|{o['session']}|{_k(key)}"] = now
    lines = []
    for o in new:
        machine = o.get("machine")
        location = f"on {machine}" if machine else "on this Mac"
        lines.append(f"Another MARVIN session {location} edited {key[1]} {max(0, int((now - o['file_at']) / 60))} min ago"
                     + (f'. It is working on: "{o["request"]}"' if o["request"] else ""))
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


# ── chat tabs (marvin#1060) ─────────────────────────────────────────────────

BRANCH_TICKET_RE = re.compile(r"#(\d+)$|^ticket/(\d+)(?:-|$)")   # the cleanup sweep's ISSUE_NUMBER_RE (#226)
PS_FIELDS = ["/bin/ps", "-o", "pid=,ppid=,tty=,lstart=,command="]


@dataclass(frozen=True)
class Proc:
    pid: int
    started: str          # ps lstart, single-spaced: with the pid it tells a reused pid apart
    tty: str              # e.g. "ttys004"; hooks have none of their own, the claude process does
    interactive: bool     # False for `claude -p` / `--print` one-off runs


def _ps_row(pid: int, run=None) -> tuple[int, str, str, list[str]] | None:
    """(ppid, tty, lstart, command words) for one process, None if ps can't tell."""
    run = run or subprocess.run
    try:
        out = run([*PS_FIELDS, "-p", str(pid)], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return None
    words = (out.stdout or "").split() if out.returncode == 0 else []
    if len(words) < 9 or not words[0].isdigit() or not words[1].isdigit():
        return None
    return int(words[1]), words[2], " ".join(words[3:8]), words[8:]


def _is_claude(words: list[str]) -> bool:
    return any(Path(w).name == "claude" for w in words[:2])


def claude_proc(start_pid: int | None = None, run=None, depth: int = 12) -> Proc | None:
    """The claude process this hook runs under, found by walking up the parents; None if there isn't one."""
    pid, seen = (start_pid or os.getppid()), set()
    for _ in range(depth):
        if pid in seen or pid <= 1:
            return None
        seen.add(pid)
        row = _ps_row(pid, run)
        if row is None:
            return None
        ppid, tty, started, words = row
        if _is_claude(words):
            return Proc(pid, started, tty, interactive=not any(w in ("-p", "--print") for w in words))
        pid = ppid
    return None


def proc_alive(pid, started: str, run=None) -> bool:
    """The process is still running and is the same one (same start time), not a reused pid."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        return False
    row = _ps_row(pid, run)
    return row is not None and " ".join(row[2].split()) == " ".join(str(started).split())


def ticket_from_branch(branch: str | None) -> int | None:
    m = BRANCH_TICKET_RE.search(branch or "")
    return int(m.group(1) or m.group(2)) if m else None


def _git_info(cwd: str) -> tuple[str | None, str | None]:
    """(owner/name of origin, current branch) for a folder, Nones when it isn't a GitHub checkout."""
    def git(*a):
        try:
            r = subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True, timeout=2)
            return r.stdout.strip() if r.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None
    url = git("remote", "get-url", "origin") or ""
    m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?$", url)
    return (m.group(1) if m else None), git("rev-parse", "--abbrev-ref", "HEAD")


def _mac() -> str:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import machine_profile
        return machine_profile.machine_label()
    except Exception:  # noqa: BLE001
        return socket.gethostname().split(".")[0]


def chat_from_env(payload: dict, env, proc: Proc | None, mac: str, git, version: str | None = None) -> dict | None:
    """The chat-tab record for this session, None when it isn't a person's chat in a WezTerm pane (no pane, a helper
    tab, a one-off `claude -p`, or no claude process found)."""
    pane = str(env.get("WEZTERM_PANE") or "")
    if not pane.isdigit() or env.get("MARVIN_HELPER_TAB") == "1" or proc is None or not proc.interactive:
        return None
    cwd = str(payload.get("cwd") or os.getcwd())
    repo, branch = git(cwd)
    return {"mac": mac, "socket": env.get("WEZTERM_UNIX_SOCKET") or "", "pane": int(pane), "tty": proc.tty,
            "claude_pid": proc.pid, "claude_started": proc.started, "session": str(payload.get("session_id") or ""),
            "cwd": cwd, "repo": repo, "branch": branch, "ticket": ticket_from_branch(branch),
            "claude_version": version}   # the Claude Code it started on, so an update can be noticed (#1086)


def chat_id(key: str) -> str:
    """The opaque id the dashboard holds for a chat (marvin#1067): never its socket or tty."""
    import hashlib
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def chat_key(rec: dict) -> str:
    return f"{rec['mac']}|{rec['socket']}|{rec['pane']}"


def register_chat(st: dict, rec: dict, now: float) -> None:
    """The pane owns the record: same pane and tty is the same tab (newest session wins); another tty in that pane
    is a new tab that reused the pane id, so it starts fresh."""
    chats = st.setdefault("chats", {})
    old = chats.get(chat_key(rec))
    same_tab = isinstance(old, dict) and old.get("tty") == rec["tty"]
    chats[chat_key(rec)] = {"state": "your-turn", **(old if same_tab else {}), **rec,
                            "started_at": old.get("started_at", now) if same_tab else now, "seen_at": now}


# A chat tab's state (marvin#1061). Claude Code's own hook order decides it:
#   prompt (UserPromptSubmit)        -> working
#   stop   (Stop)                    -> your-turn: Claude finished; not urgent
#   notify (Notification)            -> waiting for "permission" only when the message asks for it; the idle reminder
#                                       ("waiting for your input") changes nothing, it is already your turn
#   ask    (PreToolUse AskUserQuestion) -> waiting for a "question"
#   tool   (PostToolUse, any tool)   -> working again, but only if it was waiting: the permission was granted or the
#                                       question answered. PreToolUse can't clear it: it fires before the prompt shows.
#   end    (SessionEnd)              -> done, except reason "clear" (a SessionStart follows in the same pane)
# A denied permission runs no tool, so it settles when Claude stops (your-turn).
STATE_EVENTS = {"stop": ("your-turn", None), "ask": ("waiting", "question"), "tool": ("working", None),
                "end": ("done", None), "notify": ("waiting", "permission")}


def env_chat_key(env) -> str | None:
    pane = str(env.get("WEZTERM_PANE") or "")
    return f"{_mac()}|{env.get('WEZTERM_UNIX_SOCKET') or ''}|{pane}" if pane.isdigit() else None


def set_state(st: dict, key: str, state: str, waiting_for: str | None, event: str, now: float) -> bool:
    rec = (st.get("chats") or {}).get(key)
    if not isinstance(rec, dict):
        return False
    rec.update(state=state, waiting_for=waiting_for, state_at=now, last_event=event)
    return True


def state_event(kind: str, payload: dict, env, now: float) -> None:
    key = env_chat_key(env)
    if key is None:
        return
    if kind == "notify" and "permission" not in str(payload.get("message") or "").lower():
        return
    if kind == "end" and payload.get("reason") == "clear":
        return
    if kind == "tool":   # runs after every tool call: read without the lock, write only when it was waiting
        try:
            cur = (json.loads(STATE_PATH.read_text()).get("chats") or {}).get(key)
        except (OSError, ValueError, AttributeError):
            return
        if not isinstance(cur, dict) or cur.get("state") != "waiting":
            return
    state, waiting_for = STATE_EVENTS[kind]
    with _Locked() as st:
        cur = (st.get("chats") or {}).get(key)
        if kind == "tool" and not (isinstance(cur, dict) and cur.get("state") == "waiting"):
            return
        set_state(st, key, state, waiting_for, kind, now)
        version = (cur or {}).get("claude_version") if isinstance(cur, dict) else None
    if kind == "stop" and version and _installed_claude() not in (None, version):
        _start_detached("sweep")   # this chat just became idle on an old Claude Code: let the restarter look (#1086)


def _installed_claude() -> str | None:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import chat_restart
        return chat_restart.installed_version()
    except Exception:  # noqa: BLE001
        return None


def _start_detached(*args: str) -> None:
    subprocess.Popen([sys.executable, str(Path(__file__).resolve().parent / "chat_restart.py"), *args],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def _valid(rec) -> bool:
    return (isinstance(rec, dict) and isinstance(rec.get("pane"), int) and not isinstance(rec.get("pane"), bool)
            and isinstance(rec.get("socket"), str) and isinstance(rec.get("tty"), str))


def live_chats(st: dict, panes: dict, alive=proc_alive) -> list[dict]:
    """Chats still alive, joined with their WezTerm pane; dead ones are removed from `st`.
    panes: GUI socket -> that GUI's pane list, or None when that GUI has gone. A socket missing from `panes` didn't
    answer: its chats are kept and marked unknown, never declared dead on a guess."""
    out, keep = [], {}
    for key, rec in (st.get("chats") or {}).items():
        if not _valid(rec) or not alive(rec.get("claude_pid"), rec.get("claude_started", "")):
            continue
        if rec["socket"] not in panes:
            keep[key] = rec
            out.append({**rec, "id": chat_id(key), "unknown": True})
            continue
        rows = panes[rec["socket"]]
        row = next((r for r in rows or [] if r.get("pane_id") == rec["pane"]), None)
        if row is None or not str(row.get("tty_name") or "").endswith("/" + rec["tty"]):
            continue
        keep[key] = rec
        out.append({**rec, "id": chat_id(key), "unknown": False, "title": row.get("title", ""),
                    "window_id": row.get("window_id"), "tab_id": row.get("tab_id")})
    st["chats"] = keep
    return sorted(out, key=lambda c: (c["mac"], c["socket"], c["pane"]))


def _panes_by_socket(sockets) -> dict:
    """Each GUI's panes through the one WezTerm wrapper (marvin#1059); a GUI that errors is left out (unknown)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import wezterm_cli
    out = {}
    for sock in sorted(set(sockets)):
        try:
            out[sock] = wezterm_cli.Wezterm(socket=sock or None, timeout=5).list()
        except wezterm_cli.WeztermError:
            continue
    return out


def wezterm_running() -> bool:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import wezterm_cli
        return bool(wezterm_cli.guis())
    except Exception:  # noqa: BLE001
        return False


def list_chats(now: float | None = None) -> list[dict]:
    now = now if now is not None else time.time()
    with _Locked() as st:
        recs = [r for r in (st.get("chats") or {}).values() if _valid(r)]
    panes = _panes_by_socket(r["socket"] for r in recs)     # outside the lock: WezTerm may be slow
    with _Locked() as st:
        return live_chats(st, panes)


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


def handle(kind: str, payload: dict, now: float | None = None, env=None) -> str | None:
    """Returns what the hook should print (only `pre` ever prints, and only to ask)."""
    now = now if now is not None else time.time()
    sid = str(payload.get("session_id") or "")
    if not sid:
        return None
    try:
        if kind in STATE_EVENTS:
            state_event(kind, payload, os.environ if env is None else env, now)
            return None
        if kind == "start":   # the slow lookups (ps, git) happen before the lock
            rec = chat_from_env(payload, os.environ if env is None else env, proc=claude_proc(), mac=_mac(),
                                git=_git_info, version=_installed_claude())
            if rec:
                with _Locked() as st:
                    register_chat(st, rec, now)
            return None
        with _Locked() as st:
            prune(st, now)
            if kind == "prompt":
                record_prompt(st, sid, payload.get("prompt", ""), now)
                key = env_chat_key(os.environ if env is None else env)
                if key:
                    set_state(st, key, "working", None, "prompt", now)
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
                remote = remote_sessions(st, now)
                why = pre_edit(st, sid, key, now, remote)
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
    if argv[:1] == ["chats"]:
        chats = list_chats()
        if "--json" in argv:   # "wezterm": is any WezTerm GUI running here, so an empty list is never ambiguous
            print(json.dumps({"chats": chats, "wezterm": wezterm_running()}))
            return 0
        if not chats:
            print("No MARVIN chat tabs open on this Mac.")
        for c in chats:
            where = f"#{c['ticket']}" if c.get("ticket") else (c.get("repo") or c.get("cwd") or "")
            state = "?" if c.get("unknown") else "live"
            print(f"pane {c['pane']:<4} {state:<4} {where:<24} {c.get('title', '')[:60]}")
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
