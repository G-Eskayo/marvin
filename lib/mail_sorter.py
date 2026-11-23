#!/usr/bin/env python3
"""MARVIN's own mail sorter, slice 1 (#1405, part of #1357): Gmail over IMAP IDLE, a watch list, and rule sorting.

Trigger-based: one IMAP connection sits in IDLE and the server pushes each new message. There's no schedule and no
polling. The only timer is IDLE's own refresh (RFC 2177: re-issue before 29 min). Each refresh also runs a catch-up, so
a missed push waits at most one refresh.

For each new message in the Inbox, cheapest decision first:
  1. watch list  -> star it + mark it important on the server, leave it in the Inbox, and tell the owner (notify.notify:
                    desktop banner + dashboard row, and the phone once MARVIN Mobile has push).
  2. personal    -> a person's address (gmail.com, icloud.com ...): leave it in the Inbox.
  3. rules       -> sender-domain (+ optional subject regex) -> folder. Add the folder's Gmail label and remove \\Inbox
                    (X-GM-LABELS). This is a real server-side move, unlike Mail.app's label-only "move" (2026-11-16).
  4. otherwise   -> leave it in the Inbox. The local model for unknown senders is #1406.

Containment (north star 1): one account, read + label only, never send or delete. The app password lives in Keychain
(service from the account file, account = address), never in a file. Every owner-specific value (address, rules,
watch list) lives in the private instance at instance/config/mail/; the engine holds none.
  gmail.json  {"address": "...", "keychain_service": "marvin-mail-gmail", "host": "imap.gmail.com"}
  rules.json  {"personal": [domains], "rules": [{"folder", "domains": [...], "subject": "regex"?}]}  first match wins
  watch.json  [{"name", "domains"?, "addresses"?, "mentions"?, "mentions_from"?}]
              mentions match the display name or subject; with mentions_from, only from those domains (so a newsletter
              headline or a spoofed display name doesn't fire the alert).
The config is re-read on every catch-up, so edits apply without a restart.

State: {uidvalidity, last_uid} per account, written atomically after every message. A restart resumes where it
stopped. A first run starts at UIDNEXT, so the backlog is never re-sorted. A UIDVALIDITY change resets to the new
UIDNEXT. Every action is appended to a JSONL log (the undo record, like the clean-up's moves_<acct>.log).

Complexity: decide is O(R + W) over rules and watch entries, catch-up is O(new messages) with one FETCH and at most
two STOREs each, and the state write is O(1). Idle costs nothing: one blocked socket.

CLI:
  mail_sorter.py run   [--config DIR] [--account gmail]     the daemon (launchd: com.marvin.mail-sorter)
  mail_sorter.py check [--config DIR] "<From header>" "<subject>"   dry-run decision as JSON
  mail_sorter.py status [--account gmail]                   state + the last few log entries
"""
from __future__ import annotations

import argparse
import email.header
import email.parser
import email.utils
import imaplib
import json
import os
import re
import select
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

IDLE_REFRESH_S = 25 * 60          # RFC 2177: servers may drop an IDLE after 30 min
BACKOFF_START_S, BACKOFF_MAX_S = 5, 300
STATE_DIR = Path.home() / ".claude" / "mail-sorting"


class ConfigError(ValueError):
    pass


class ImapError(RuntimeError):
    pass


# ---------- pure core ----------

@dataclass(frozen=True)
class Sender:
    display: str
    address: str
    host: str
    domain: str     # last two labels, for display and logs; matching uses host suffixes


def parse_sender(header: str) -> Sender:
    display, address = email.utils.parseaddr(header or "")
    address = address.strip().lower()
    if "@" not in address:
        return Sender(display, "", "", "")
    host = address.rsplit("@", 1)[1].strip(".")
    return Sender(display, address, host, ".".join(host.split(".")[-2:]))


def _host_matches(host: str, domains) -> bool:
    return bool(host) and any(host == d or host.endswith("." + d) for d in domains)


@dataclass(frozen=True)
class Message:
    uid: int
    sender: str
    subject: str
    message_id: str = ""


@dataclass(frozen=True)
class Decision:
    kind: str                 # "watch" | "sort" | "keep"
    folder: str | None
    reason: str
    watch: str | None = None


@dataclass
class Rule:
    folder: str
    domains: list[str]
    subject: re.Pattern | None = None


@dataclass
class Watch:
    name: str
    domains: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    mentions_from: list[str] = field(default_factory=list)


def _domains(xs) -> list[str]:
    return [str(x).strip().lower().strip(".") for x in (xs or []) if str(x).strip()]


@dataclass
class Config:
    rules: list[Rule]
    personal: list[str]
    watch: list[Watch]

    @classmethod
    def from_dicts(cls, rules: dict, watch: list) -> "Config":
        if not isinstance(rules, dict) or not isinstance(rules.get("rules", []), list):
            raise ConfigError("rules.json must be an object with a 'rules' list")
        parsed = []
        for i, r in enumerate(rules.get("rules", [])):
            if not isinstance(r, dict) or not str(r.get("folder") or "").strip():
                raise ConfigError(f"rule {i} has no folder")
            try:
                pat = re.compile(r["subject"], re.I) if r.get("subject") else None
            except re.error as exc:
                raise ConfigError(f"rule {i} ({r['folder']}): bad subject regex: {exc}") from exc
            parsed.append(Rule(str(r["folder"]).strip(), _domains(r.get("domains")), pat))
        if not isinstance(watch, list):
            raise ConfigError("watch.json must be a list")
        ws = []
        for i, w in enumerate(watch):
            if not isinstance(w, dict) or not str(w.get("name") or "").strip():
                raise ConfigError(f"watch entry {i} has no name")
            ws.append(Watch(str(w["name"]).strip(), _domains(w.get("domains")), _domains(w.get("addresses")),
                            [str(m).lower() for m in w.get("mentions") or [] if str(m).strip()],
                            _domains(w.get("mentions_from"))))
        return cls(parsed, _domains(rules.get("personal")), ws)


def load_config(directory: Path) -> Config:
    directory = Path(directory)
    rules_path, watch_path = directory / "rules.json", directory / "watch.json"
    if not rules_path.is_file():
        raise ConfigError(f"no rules file at {rules_path}")
    try:
        rules = json.loads(rules_path.read_text())
        watch = json.loads(watch_path.read_text()) if watch_path.is_file() else []
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"unreadable mail config: {exc}") from exc
    return Config.from_dicts(rules, watch)


def _watch_hit(w: Watch, s: Sender, subject: str) -> bool:
    if s.address and s.address in w.addresses:
        return True
    if _host_matches(s.host, w.domains):
        return True
    if w.mentions and (not w.mentions_from or _host_matches(s.host, w.mentions_from)):
        text = f"{s.display} {subject}".lower()
        return any(m in text for m in w.mentions)
    return False


def decide(m: Message, c: Config) -> Decision:
    s = parse_sender(m.sender)
    subject = m.subject or ""
    for w in c.watch:
        if _watch_hit(w, s, subject):
            return Decision("watch", None, f"watch: {w.name}", w.name)
    if not s.host:
        return Decision("keep", None, "no sender address")
    if _host_matches(s.host, c.personal):
        return Decision("keep", None, "from a person")
    for r in c.rules:
        if _host_matches(s.host, r.domains) and (r.subject is None or r.subject.search(subject)):
            return Decision("sort", r.folder, f"rule: {s.domain}" + (" + subject" if r.subject else ""))
    return Decision("keep", None, "unknown sender")


def _decode(value: str) -> str:
    try:
        return str(email.header.make_header(email.header.decode_header(value or "")))
    except Exception:  # noqa: BLE001 - a malformed encoded-word shouldn't drop the message
        return value or ""


def _header_msg(raw: bytes):
    return email.parser.BytesParser().parsebytes(raw or b"", headersonly=True)


def parse_headers(raw: bytes) -> tuple[str, str]:
    h = _header_msg(raw)
    return _decode(h.get("From", "")), _decode(h.get("Subject", ""))


def parse_message_id(raw: bytes) -> str:
    return (_header_msg(raw).get("Message-ID", "") or "").strip().strip("<>")


def imap_quote(s: str) -> str:
    if "\r" in s or "\n" in s:
        raise ValueError("IMAP string can't contain a line break")
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def classify_idle_line(line: bytes) -> str:
    if not line or line.startswith(b"* BYE"):
        return "bye"
    return "new" if re.match(rb"\* \d+ EXISTS", line) else "other"


# ---------- server actions ----------

def _ok(typ, data, what: str):
    if typ != "OK":
        raise ImapError(f"{what}: {typ} {data!r}"[:300])
    return data


def apply(imap, uid: int, d: Decision) -> None:
    u = str(uid)
    if d.kind == "watch":
        _ok(*imap.uid("STORE", u, "+FLAGS", "(\\Flagged)"), what="star")
        _ok(*imap.uid("STORE", u, "+X-GM-LABELS", "(\\Important)"), what="important")
    elif d.kind == "sort":
        _ok(*imap.uid("STORE", u, "+X-GM-LABELS", f"({imap_quote(d.folder)})"), what="label")
        _ok(*imap.uid("STORE", u, "-X-GM-LABELS", "(\\Inbox)"), what="unInbox")


def fetch_message(imap, uid: int) -> Message:
    data = _ok(*imap.uid("FETCH", str(uid), "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)])"), what="fetch")
    raw = next((part[1] for part in data or [] if isinstance(part, tuple) and len(part) > 1), b"")
    sender, subject = parse_headers(raw)
    return Message(uid, sender, subject, parse_message_id(raw))


class State:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict | None:
        try:
            v = json.loads(self.path.read_text())
            return {"uidvalidity": int(v["uidvalidity"]), "last_uid": int(v["last_uid"])}
        except Exception:  # noqa: BLE001 - missing or corrupt reads as a fresh start
            return None

    def save(self, uidvalidity: int, last_uid: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"uidvalidity": uidvalidity, "last_uid": last_uid}))
        os.replace(tmp, self.path)


def _log(path: Path, m: Message, d: Decision) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        s = parse_sender(m.sender)
        entry = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "uid": m.uid, "kind": d.kind,
                 "folder": d.folder, "watch": d.watch, "reason": d.reason, "from": s.address,
                 "subject": (m.subject or "")[:120], "message_id": m.message_id}
        with path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def catch_up(imap, config: Config, state: State, alert: Callable[[Decision, Message], None], log_path: Path) -> int:
    """Handle every Inbox message newer than the saved UID. Returns how many were handled. A connection error
    propagates (the caller reconnects) and progress up to the last finished message is kept."""
    uidvalidity, uidnext = imap.status_values()
    saved = state.load()
    if saved is None or saved["uidvalidity"] != uidvalidity:
        state.save(uidvalidity, max(uidnext - 1, 0))
        return 0
    last = saved["last_uid"]
    data = _ok(*imap.uid("SEARCH", "UID", f"{last + 1}:*"), what="search")
    uids = sorted(int(x) for x in b" ".join(data or [b""]).split() if int(x) > last)  # `N:*` returns the max even if < N
    for uid in uids:
        m = fetch_message(imap, uid)
        d = decide(m, config)
        apply(imap, uid, d)
        _log(log_path, m, d)
        if d.kind == "watch":
            try:
                alert(d, m)
            except Exception as exc:  # noqa: BLE001 - telling must never stop sorting
                _record("alert failed", exc)
        state.save(uidvalidity, uid)
    return len(uids)


# ---------- the live connection ----------

def _record(message: str, exc: BaseException | str = "") -> None:
    try:
        import error_log
        error_log.record("mail_sorter", message, raw=str(exc)[:500])
    except Exception:  # noqa: BLE001
        pass


def keychain_password(service: str, account: str) -> str:
    out = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
                         capture_output=True, text=True, timeout=15)
    if out.returncode != 0 or not out.stdout.strip():
        raise ConfigError(f"no Keychain password for service {service!r}, account {account!r}")
    return out.stdout.strip()


class GmailConnection:
    """imaplib with the two things it lacks on Python 3.12: IDLE, and UIDVALIDITY/UIDNEXT read after SELECT."""

    def __init__(self, host: str, address: str, password: str):
        self.M = imaplib.IMAP4_SSL(host, timeout=60)
        self.M.login(address, password)
        self._select()

    def _select(self):
        _ok(*self.M.select("INBOX"), what="select")
        self.M.sock.settimeout(None)  # blocking reads; IDLE waits with select() instead

    def uid(self, command, *args):
        return self.M.uid(command, *args)

    def status_values(self) -> tuple[int, int]:
        typ, data = self.M.status("INBOX", "(UIDVALIDITY UIDNEXT)")
        _ok(typ, data, "status")
        text = b" ".join(d for d in data if isinstance(d, bytes)).decode(errors="replace")
        v, n = re.search(r"UIDVALIDITY (\d+)", text), re.search(r"UIDNEXT (\d+)", text)
        if not (v and n):
            raise ImapError(f"status without UIDVALIDITY/UIDNEXT: {text[:200]}")
        return int(v.group(1)), int(n.group(1))

    def idle(self, timeout: float) -> str:
        """Wait in IDLE. Returns "activity" (anything the server pushed, so the caller catches up), "timeout"
        (refresh), or "bye" (reconnect)."""
        tag = self.M._new_tag().decode()
        self.M.send(f"{tag} IDLE\r\n".encode())
        first = self.M.readline()
        if not first.startswith(b"+"):
            raise ImapError(f"IDLE refused: {first[:200]!r}")
        deadline, result = time.monotonic() + timeout, "timeout"
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ready = self.M.sock.pending() if hasattr(self.M.sock, "pending") else 0
            if not ready:
                ready = bool(select.select([self.M.sock], [], [], remaining)[0])
            if not ready:
                break
            kind = classify_idle_line(self.M.readline())
            if kind == "bye":
                return "bye"
            result = "activity"   # any push (EXISTS, EXPUNGE, FETCH): leave IDLE and catch up
            break
        self.M.send(b"DONE\r\n")
        while True:
            line = self.M.readline()
            if not line:
                return "bye"
            if line.startswith(tag.encode()):
                if b" OK" not in line[:len(tag) + 4]:
                    raise ImapError(f"IDLE ended badly: {line[:200]!r}")
                return result

    def close(self):
        try:
            self.M.logout()
        except Exception:  # noqa: BLE001
            pass


def _alert(d: Decision, m: Message) -> None:
    import notify
    s = parse_sender(m.sender)
    who = s.display or s.address
    link = ("https://mail.google.com/mail/u/0/#search/" + quote(f"rfc822msgid:{m.message_id}")
            if m.message_id else "https://mail.google.com/mail/u/0/#inbox")
    notify.notify(f"Mail from {d.watch}", f"{who}: {m.subject or '(no subject)'}"[:200], link)


def _is_auth_failure(exc: BaseException) -> bool:
    return isinstance(exc, imaplib.IMAP4.error) and re.search(r"AUTHENTICATIONFAILED|Invalid credentials|"
                                                              r"Application-specific password", str(exc), re.I)


def run(config_dir: Path, account: str = "gmail", *, once: bool = False) -> int:
    acct_path = Path(config_dir) / f"{account}.json"
    try:
        acct = json.loads(acct_path.read_text())
        address, service = acct["address"], acct.get("keychain_service", f"marvin-mail-{account}")
        host = acct.get("host", "imap.gmail.com")
        load_config(config_dir)   # refuse to start on a broken config
    except (OSError, KeyError, json.JSONDecodeError, ConfigError) as exc:
        _record(f"{account}: not started, config problem", exc)
        print(f"mail_sorter: config problem: {exc}", file=sys.stderr)
        return 2
    state = State(STATE_DIR / f"state-{account}.json")
    log_path = STATE_DIR / f"live_moves_{account}.jsonl"
    backoff = BACKOFF_START_S
    while True:
        conn = None
        try:
            conn = GmailConnection(host, address, keychain_password(service, address))
            backoff = BACKOFF_START_S
            while True:
                n = catch_up(conn, load_config(config_dir), state, _alert, log_path)
                if n:
                    print(f"{datetime.now().isoformat(timespec='seconds')} handled {n}", flush=True)
                if once:
                    return 0
                if conn.idle(IDLE_REFRESH_S) == "bye":
                    break
        except ConfigError as exc:
            _record(f"{account}: stopped, config problem", exc)
            _tell_once(f"Mail sorter stopped: {exc}")
            return 0   # exit 0 so launchd doesn't restart into the same error
        except Exception as exc:  # noqa: BLE001 - any connection failure: log, back off, reconnect
            if _is_auth_failure(exc):
                _record(f"{account}: sign-in refused", exc)
                _tell_once("Mail sorter can't sign in to Gmail. The app password may have been revoked.")
                return 0
            _record(f"{account}: connection lost, reconnecting in {backoff}s", f"{type(exc).__name__}: {exc}")
            if once:
                return 1
            time.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)
        finally:
            if conn:
                conn.close()


def _tell_once(message: str) -> None:
    try:
        import notify
        notify.notify("MARVIN mail sorter", message)
    except Exception:  # noqa: BLE001
        pass


def _default_config_dir() -> Path:
    import instance
    return instance.path("config", "mail")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mail_sorter.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--config")
    r.add_argument("--account", default="gmail")
    r.add_argument("--once", action="store_true", help="one catch-up, then exit (a live check)")
    c = sub.add_parser("check")
    c.add_argument("--config")
    c.add_argument("sender")
    c.add_argument("subject", nargs="?", default="")
    s = sub.add_parser("status")
    s.add_argument("--account", default="gmail")
    a = p.parse_args(argv)
    if a.cmd == "run":
        return run(Path(a.config) if a.config else _default_config_dir(), a.account, once=a.once)
    if a.cmd == "check":
        try:
            d = decide(Message(0, a.sender, a.subject), load_config(Path(a.config) if a.config else _default_config_dir()))
        except ConfigError as exc:
            print(json.dumps({"error": str(exc)}))
            return 1
        print(json.dumps(d.__dict__))
        return 0
    state = State(STATE_DIR / f"state-{a.account}.json").load()
    log = STATE_DIR / f"live_moves_{a.account}.jsonl"
    tail = log.read_text().splitlines()[-10:] if log.is_file() else []
    print(json.dumps({"state": state, "recent": [json.loads(x) for x in tail]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
