#!/usr/bin/env python3
"""Chat tabs restart onto a new Claude Code on their own (marvin#1086, PRD #1058).

Claude Code updates itself, but a running chat keeps the old version until it restarts, so long-lived chats show
"restart to update" for days. This resumes each such chat on the installed version, in a new tab of the same window
(`claude --resume <its session>`, so the conversation carries over), then closes the old tab. Only when it is safe:

  - the chat is this Mac's, live, and on an older version than the one installed
  - it is idle on Gil's turn: its hooks say "your-turn" (#1061) AND Claude's title shows its idle mark
  - Gil isn't looking at it (it isn't any WezTerm client's focused pane)
  - it has no background job running: no shell among its children (its MCP servers and caffeinate don't count)
  - and all of that still holds right before the old tab closes; if not, the new tab is closed and the old one kept

Nothing is typed into a chat (anything typed would be Gil's prompt): the note goes to a macOS notification and the log.

Triggers, never a timer: a launchd job watches the installed package (WatchPaths, `install-watch`), and a chat that
becomes idle on an old version starts a sweep from its Stop hook (session_work.py).
    chat_restart.py sweep            restart every safe outdated chat on this Mac
    chat_restart.py check            say, for each chat, whether it would be restarted and why not
    chat_restart.py install-watch    install the launchd watch on this Mac
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import wezterm_cli  # noqa: E402

IDLE_MARK = "✳"
SHELLS = {"bash", "zsh", "sh", "dash", "fish"}
LOG_PATH = Path.home() / ".claude" / "logs" / "chat-restarts.jsonl"
LABEL = "com.marvin.claude-update-watch"


# ── versions ────────────────────────────────────────────────────────────────────────────────

def installed_version(which: Callable[[str], str | None] = shutil.which) -> str | None:
    """The Claude Code version `claude` runs now: from its npm package.json, or a native install's versions/<v>."""
    found = which("claude")
    if not found:
        return None
    try:
        exe = Path(found).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if exe.parent.name == "versions":
        return exe.name
    for d in list(exe.parents)[:6]:
        pkg = d / "package.json"
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text())
            except (OSError, ValueError):
                return None
            if data.get("name") == "@anthropic-ai/claude-code":
                return str(data.get("version") or "") or None
    return None


def _parts(v: str) -> tuple[int, ...] | None:
    return tuple(int(x) for x in v.split(".")) if re.fullmatch(r"\d+(\.\d+)*", v or "") else None


def newer(a: str, b: str) -> bool:
    pa, pb = _parts(a), _parts(b)
    return bool(pa and pb and pa > pb)


# ── safety ──────────────────────────────────────────────────────────────────────────────────

def shell_children(pid: int, run: Callable | None = None) -> list[str]:
    """Shells among the claude process's children: a background job it started. MCP servers and caffeinate aren't."""
    try:
        out = (run or subprocess.run)(["/usr/bin/pgrep", "-lf", "-P", str(int(pid))], capture_output=True, text=True,
                                      timeout=5)
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        return ["(couldn't list its processes)"]
    found = []
    for line in (out.stdout or "").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and Path(parts[1].split()[0]).name in SHELLS:
            found.append(parts[1])
    return found


def why_not(chat: dict, installed: str | None, focused: set[int], shells: list[str]) -> str | None:
    """Why this chat must not be restarted now, or None when it may."""
    if not installed:
        return "can't tell which Claude Code is installed"
    have = chat.get("claude_version")
    if not have:
        return "its Claude Code version wasn't recorded"
    if not newer(installed, have):
        return f"already current ({have})"
    if chat.get("unknown"):
        return "its WezTerm didn't answer"
    if chat.get("state") != "your-turn":
        return f"it's {chat.get('state') or 'busy'}, not idle on your turn"
    if not str(chat.get("title") or "").startswith(IDLE_MARK):
        return "Claude's own title says it's working"
    if chat.get("pane") in focused:
        return "you're looking at it"
    if shells:
        return f"a background job is running in it ({shells[0][:60]})"
    return None


# ── doing it ────────────────────────────────────────────────────────────────────────────────

def _log(entry: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps({"at": time.time(), **entry}) + "\n")
    except OSError:
        pass


def _notify(text: str) -> None:
    try:
        import notify
        notify.notify("MARVIN chats", text)
    except Exception:  # noqa: BLE001
        pass


def restart(chat: dict, installed: str, wez, recheck: Callable[[], str | None],
            log: Callable[[dict], None] = _log, notify: Callable[[str], None] = _notify) -> dict:
    """Resume the chat's session in a new tab of its window, then close the old tab. Keeps the old one on any doubt."""
    import marvin_session
    where = chat.get("ticket") and f"#{chat['ticket']}" or chat.get("cwd") or f"pane {chat.get('pane')}"
    entry = {"id": chat.get("id"), "pane": chat.get("pane"), "from": chat.get("claude_version"), "to": installed}
    session = str(chat.get("session") or "")
    if not session:
        log({**entry, "ok": False, "why": "no session id to resume"})
        return {"ok": False, "why": "no session id to resume"}
    program = ["/bin/zsh", "-c", marvin_session.shell_script(Path(chat.get("cwd") or Path.home()), resume=session)]
    try:
        new = wez.spawn(Path(chat.get("cwd") or Path.home()), program, window_id=chat.get("window_id"))
    except (wezterm_cli.WeztermError, ValueError) as exc:
        log({**entry, "ok": False, "why": f"couldn't open the new tab: {exc}"})
        notify(f"{where}: couldn't restart it onto Claude Code {installed} ({exc}); it's still open as it was")
        return {"ok": False, "why": str(exc)}
    why = recheck()
    try:
        if why:   # Gil came back to it while the new tab opened: keep his tab, drop the new one
            wez.kill_pane(new)
            log({**entry, "ok": False, "why": why})
            return {"ok": False, "why": why}
        wez.kill_pane(chat["pane"])
    except (wezterm_cli.WeztermError, ValueError) as exc:
        log({**entry, "ok": False, "why": f"couldn't close a tab: {exc}", "new_pane": new})
        return {"ok": False, "why": str(exc)}
    log({**entry, "ok": True, "new_pane": new})
    notify(f"{where}: restarted onto Claude Code {installed}, same conversation")
    return {"ok": True, "pane": new}


def sweep(chats: Callable[[], list[dict]], installed: Callable[[], str | None], focused: Callable[[dict], set[int]],
          shells: Callable[[dict], list[str]], do_restart: Callable[[dict, str], dict], here: str) -> list[dict]:
    version = installed()
    if not version:
        return []
    out = []
    for c in chats():
        if c.get("mac") != here:
            continue
        try:
            why = why_not(c, version, focused(c), shells(c))
            res = do_restart(c, version) if why is None else {"ok": False}
        except Exception as exc:  # noqa: BLE001 -- one chat's trouble never stops the rest
            why, res = f"failed: {exc}", {"ok": False}
        out.append({"id": c.get("id"), "pane": c.get("pane"), "why": why, "ok": bool(res.get("ok"))})
    return out


def _defaults():
    import session_work

    def wez(c):
        return wezterm_cli.Wezterm(socket=c.get("socket") or None)

    def focused(c):
        try:
            return wez(c).focused_panes()
        except wezterm_cli.WeztermError:
            return {c.get("pane")}   # can't tell where Gil is looking: assume here, never restart blind

    def shells(c):
        return shell_children(c.get("claude_pid") or 0)

    def do_restart(c, version):
        def recheck():
            now = next((x for x in session_work.list_chats() if x.get("id") == c.get("id")), None)
            return "it closed" if now is None else why_not(now, version, focused(now), shells(now))
        return restart(c, version, wez(c), recheck)
    return dict(chats=session_work.list_chats, installed=installed_version, focused=focused, shells=shells,
                do_restart=do_restart, here=session_work._mac())


# ── the trigger ─────────────────────────────────────────────────────────────────────────────

def _package_json() -> Path | None:
    found = shutil.which("claude")
    try:
        exe = Path(found).resolve(strict=True) if found else None
    except (OSError, RuntimeError):
        return None
    for d in list(exe.parents)[:6] if exe else []:
        if (d / "package.json").exists():
            return d / "package.json"
    return exe.parent if exe and exe.parent.name == "versions" else None


def watch_plist(watched: Path, python: str, home: Path) -> str:
    import plistlib
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [python, str(HERE / "chat_restart.py"), "sweep"],
        "WatchPaths": [str(watched)],
        "ThrottleInterval": 60,   # an update is many writes: look at most once a minute
        "EnvironmentVariables": {"HOME": str(home), "PATH": f"{home}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin"},
        "ProcessType": "Background",
        "StandardOutPath": str(home / ".claude" / "logs" / "claude-update-watch.log"),
        "StandardErrorPath": str(home / ".claude" / "logs" / "claude-update-watch-error.log"),
    }).decode()


def install_watch() -> str:
    watched = _package_json()
    if watched is None:
        return "not installed: can't find the installed Claude Code to watch"
    home = Path.home()
    plist = home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    text = watch_plist(watched, str(home / ".agents" / "venv" / "bin" / "python"), home)
    if plist.exists() and plist.read_text() == text:
        return "already installed"
    plist.write_text(text)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", domain, str(plist)], capture_output=True, text=True)
    return "installed" if r.returncode == 0 else f"written, but launchctl said: {(r.stderr or '').strip()[:200]}"


def main(argv: list[str]) -> int:
    if argv[:1] == ["install-watch"]:
        print(install_watch())
        return 0
    if argv[:1] in (["sweep"], ["check"]):
        d = _defaults()
        if argv[0] == "check":
            d["do_restart"] = lambda c, v: {"ok": False}
        for r in sweep(**d):
            print(f"pane {r['pane']}: {'restarted' if r['ok'] else ('would restart' if r['why'] is None else r['why'])}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
