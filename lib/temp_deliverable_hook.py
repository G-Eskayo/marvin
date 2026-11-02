#!/usr/bin/env python3
"""Temp deliverables: a reminder when a session points Gil at a file that lives only in temp (marvin#715).

Gil, 2026-11-02: a session made portfolio screenshots under /private/tmp and sent them as a file card his client
didn't show; he had no idea where they were. The rule ("show Gil things with marvin-show, never a file card or a
temp path") was memory-only. This hook makes it mechanical, gently:

  post   PostToolUse (Write | Bash): a Write of an image, PDF or HTML file under /tmp, /private/tmp or /var/folders is
         noted for this session, with a one-line reminder in context; a Bash command that runs marvin-show on it, or
         copies it into ~/.claude/outbox, marks it shown. Bash commands that name a temp deliverable (a screenshot
         tool's output path) are noted quietly.
  stop   Stop | SubagentStop: the reply that just ended is read from the transcript. If it mentions a noted temp
         deliverable that was never shown (or any temp image/PDF/HTML path), the session is reminded.

How strict (config/show_rule.json "mode", a Decision on the PR):
  note   the reminder is shown to Gil only; the session ends its turn as it wanted.
  nudge  (default) the session is reminded once and continues to fix it (Stop "block" with a reason); a second stop
         is never held (stop_hook_active), so it can't loop.
  hold   the session is held until it shows it, at most 3 times per path.

State is per session in ~/.agents/var/temp-deliverables/<session>.json. Fails open on its own bugs (hook_errors).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

STATE_DIR = HERE.parent / "var" / "temp-deliverables"
CONFIG = HERE.parent / "config" / "show_rule.json"
MODES = ("note", "nudge", "hold")
HOLD_LIMIT = 3
EXT = ("png", "jpg", "jpeg", "gif", "webp", "svg", "pdf", "html", "htm", "mov", "mp4")
TEMP = r"(?:/private)?/(?:tmp|var/folders)/"
TEMP_PATH = re.compile(rf"""({TEMP}[^\s'"`<>|;&()]*?\.(?:{'|'.join(EXT)}))(?![A-Za-z0-9])""", re.I)
SHOW_CMD = re.compile(r"(?:^|[\s/;&|(])(?:marvin-show|marvin_show\.py)\b")
OUTBOX_COPY = re.compile(r"\b(?:cp|mv|rsync|ditto)\b[^\n]*\.claude/outbox")


def mode(path: Path = CONFIG) -> str:
    try:
        m = json.loads(Path(path).read_text()).get("mode")
        return m if m in MODES else "nudge"
    except (OSError, ValueError, AttributeError):
        return "nudge"


def _norm(p: str) -> str:
    p = os.path.normpath(p)
    return p[len("/private"):] if p.startswith("/private/") else p


def is_temp_deliverable(p: str) -> bool:
    return bool(isinstance(p, str) and TEMP_PATH.fullmatch(os.path.normpath(p)))


def paths_in(text: str) -> list[str]:
    seen: list[str] = []
    for m in TEMP_PATH.finditer(text or ""):
        p = m.group(1).rstrip(".,:")
        if p not in seen:
            seen.append(p)
    return seen


def _state_path(session: str, state_dir: Path) -> Path:
    return state_dir / f"{re.sub(r'[^A-Za-z0-9_-]', '_', session or 'unknown')[:80]}.json"


def load(session: str, state_dir: Path = STATE_DIR) -> dict:
    try:
        d = json.loads(_state_path(session, state_dir).read_text())
        return d if isinstance(d, dict) and isinstance(d.get("files"), dict) else {"files": {}}
    except (OSError, ValueError):
        return {"files": {}}


def save(session: str, state: dict, state_dir: Path = STATE_DIR) -> None:
    p = _state_path(session, state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(p)


def reminder(paths: list[str]) -> str:
    shown = paths[:3]
    cmds = "; ".join(f"marvin-show {p}" for p in shown)
    return (f"Gil can't open a temp path or a file card: {', '.join(shown)} lives only in a temp folder. Show it with "
            f"`{cmds}` (it copies the file into ~/.claude/outbox/<project>-<date>-<topic>/ and opens it in that "
            "project's MARVIN window), and put that command in your reply. (docs/agents/showing-things.md, temp_deliverable_hook.py)")


def on_post(event: dict, state_dir: Path = STATE_DIR, now: float | None = None) -> dict | None:
    """PostToolUse: note temp deliverables, mark shown ones. Returns hook output (a reminder in context) or None."""
    tool = str(event.get("tool_name") or "")
    ti = event.get("tool_input") or {}
    session = str(event.get("session_id") or "")
    state = load(session, state_dir)
    files = state["files"]
    new: list[str] = []
    if tool in ("Write", "Edit", "MultiEdit"):
        p = ti.get("file_path")
        if is_temp_deliverable(p) and _norm(p) not in files:
            files[_norm(p)] = {"at": now or time.time(), "shown": False}
            new.append(p)
    elif tool == "Bash":
        cmd = str(ti.get("command") or "")
        named = [_norm(p) for p in paths_in(cmd)]
        if named and (SHOW_CMD.search(cmd) or OUTBOX_COPY.search(cmd)):
            for p in named:
                files.setdefault(p, {"at": now or time.time()})["shown"] = True
        else:
            # Noted quietly: a command naming a temp file isn't always making one (ls, rm); the reply is what counts.
            for p in named:
                if p not in files:
                    files[p] = {"at": now or time.time(), "shown": False}
    else:
        return None
    save(session, state, state_dir)
    if not new:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": reminder(new)}}


def last_reply(transcript_path: str) -> str:
    """The text of the last assistant message in a Claude Code transcript (JSONL). Reads only the file's tail."""
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 512 * 1024))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "assistant":
            continue
        content = (d.get("message") or {}).get("content")
        if isinstance(content, str):
            return content
        texts = [c.get("text", "") for c in content or [] if isinstance(c, dict) and c.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    return ""


def unshown_mentions(reply: str, state: dict) -> list[str]:
    """Temp deliverables the reply points Gil at that were never shown: a temp path in the text, or a noted file's
    full path or file name."""
    files = state.get("files") or {}
    out: list[str] = []
    for p in paths_in(reply):
        n = _norm(p)
        if not files.get(n, {}).get("shown") and n not in out:
            out.append(n)
    for p, rec in files.items():
        if rec.get("shown") or p in out:
            continue
        name = os.path.basename(p)
        if re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w-]|\.\w)", reply or ""):
            out.append(p)
    return out


def on_stop(event: dict, state_dir: Path = STATE_DIR, rule: str | None = None) -> dict | None:
    """Stop / SubagentStop: remind the session (per the mode) when its reply points at an unshown temp file."""
    session = str(event.get("session_id") or "")
    transcript = event.get("agent_transcript_path") or event.get("transcript_path") or ""
    reply = last_reply(str(transcript)) if transcript else ""
    if not reply:
        return None
    state = load(session, state_dir)
    found = unshown_mentions(reply, state)
    if not found:
        return None
    rule = rule or mode()
    text = reminder(found)
    if rule == "note":
        return {"systemMessage": f"MARVIN: {text}"}
    holds = state.setdefault("holds", {})
    key = "|".join(sorted(found))
    if rule == "nudge" and (event.get("stop_hook_active") or holds.get(key)):
        return {"systemMessage": f"MARVIN: {text}"}
    if rule == "hold" and holds.get(key, 0) >= HOLD_LIMIT:
        return {"systemMessage": f"MARVIN: {text}"}
    holds[key] = holds.get(key, 0) + 1
    save(session, state, state_dir)
    return {"decision": "block", "reason": text}


def main(argv: list[str]) -> int:
    step = argv[0] if argv else ""
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
        out = on_post(event) if step == "post" else on_stop(event) if step == "stop" else None
        if out:
            sys.stdout.write(json.dumps(out, ensure_ascii=False))
    except Exception as exc:  # a hook bug must never block work
        try:
            from hook_errors import log_hook_error
            log_hook_error("temp_deliverable_hook", step or "main", exc)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
