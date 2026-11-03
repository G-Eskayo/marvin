#!/usr/bin/env python3
"""Send a message from the dashboard into a chat tab, only when that is safe (marvin#1067, PRD #1058).

Typed text plus Enter on a Claude Code permission prompt picks the highlighted option, usually "Yes", so this refuses
unless every check below passes at the moment of sending:

  1. the text: escape sequences (ESC, C1) are refused outright (an end-of-paste sequence would turn the rest into raw
     keys); other control characters and carriage returns are stripped; newlines stay; empty or over MAX_CHARS refused
  2. the chat is this Mac's and live (not unknown, not the other Mac's)
  3. two independent idle signals agree: its hooks say "your-turn" (#1061) AND Claude's own title shows its idle mark
  4. the screen's last lines show no permission dialog or question menu
  5. 2 and 3 are read again right before typing, so a chat that started working in between is caught

Then the text goes in as one paste, prefixed with a visible "[from the MARVIN dashboard]" note, and Enter is sent
separately. Every send and every refusal is logged (pane, socket, both signals, the text).

The dashboard calls it with JSON on stdin (never on a command line):
    chat_send.py send   < {"id": "<chat id from marvin:listChats>", "text": "..."}
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import wezterm_cli  # noqa: E402

NOTE = "[from the MARVIN dashboard] "
MAX_CHARS = 4000
IDLE_MARK = "✳"                       # Claude Code's tab title while it waits for the person
SCREEN_TAIL = 20                      # how many of the last screen lines to check for a dialog
DIALOG = re.compile(r"Do you want to |❯\s*\d+\.\s|Yes, and don't ask again|No, and tell Claude")
LOG_PATH = Path.home() / ".claude" / "logs" / "chat-sends.jsonl"
ESCAPES = re.compile(r"[\x1b\x80-\x9f]")
STRIP = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")   # every C0 control except \t (\x09) and \n (\x0a); \r goes too


def clean(text) -> tuple[str | None, str | None]:
    """(cleaned text, None) or (None, why it can't be sent)."""
    if not isinstance(text, str) or not text.strip():
        return None, "there's nothing to send"
    if ESCAPES.search(text):
        return None, "the text contains an escape sequence, which could act as keys in the chat"
    if len(text) > MAX_CHARS:
        return None, f"the text is too long ({len(text)} characters, the limit is {MAX_CHARS})"
    return STRIP.sub("", text), None


def unsafe(chat: dict | None) -> str | None:
    """Why this chat can't take a message right now, or None."""
    if not chat:
        return "that chat isn't open on this Mac any more"
    if chat.get("unknown") or chat.get("here") is False:
        return "that chat can't be reached from here"
    if chat.get("state") != "your-turn":
        return f"the chat is {chat.get('state') or 'busy'}, so it isn't waiting for you"
    if not str(chat.get("title") or "").startswith(IDLE_MARK):
        return "the chat's own title says it's working"
    return None


def on_screen_prompt(screen: str) -> bool:
    lines = screen.rstrip().splitlines()                 # the screen's real bottom: trailing blanks don't count
    tail = "\n".join(lines[-SCREEN_TAIL:])
    return bool(DIALOG.search(tail))


def _append_log(entry: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def _find(cid: str) -> dict | None:
    import session_work
    return next((c for c in session_work.list_chats() if c.get("id") == cid and c.get("mac") == session_work._mac()),
                None)


def send(cid: str, text, find: Callable[[str], dict | None] = _find,
         wezterm_for: Callable[[dict], "wezterm_cli.Wezterm"] = lambda c: wezterm_cli.Wezterm(socket=c.get("socket") or None),
         log: Callable[[dict], None] = _append_log) -> dict:
    chat = None

    def result(ok: bool, why: str | None = None, sent: str | None = None) -> dict:
        log({"at": time.time(), "ok": ok, "why": why, "id": cid, "pane": (chat or {}).get("pane"),
             "socket": (chat or {}).get("socket"), "state": (chat or {}).get("state"),
             "title": (chat or {}).get("title"), "text": sent if sent is not None else text if isinstance(text, str) else None})
        return {"ok": ok, **({"why": why} if why else {})}

    body, why = clean(text)
    if why:
        return result(False, why)
    chat = find(cid)
    why = unsafe(chat)
    if why:
        return result(False, why)
    wez = wezterm_for(chat)
    try:
        if on_screen_prompt(wez.get_text(chat["pane"])):
            return result(False, "a permission or question prompt is on the chat's screen")
        again = find(cid)                                      # right before typing: still the same idle chat?
        why = unsafe(again) or (None if again and again.get("pane") == chat["pane"] else "that chat changed")
        if why:
            return result(False, why)
        message = NOTE + body
        wez.send_text(chat["pane"], message, paste=True)
        wez.send_text(chat["pane"], "\r", paste=False)
    except (wezterm_cli.WeztermError, ValueError, KeyError) as exc:
        return result(False, f"WezTerm refused: {exc}")
    return result(True, sent=message)


def main(argv: list[str]) -> int:
    if argv[:1] != ["send"]:
        print(__doc__)
        return 2
    try:
        req = json.load(sys.stdin)
        cid, text = str(req["id"]), req["text"]
    except (ValueError, KeyError, TypeError):
        print(json.dumps({"ok": False, "why": "the request wasn't {\"id\", \"text\"} JSON"}))
        return 1
    out = send(cid, text)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
