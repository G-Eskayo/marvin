#!/usr/bin/env python3
"""The Proposals store (#531, #102, ADR 0068): big north-star ideas, one JSON file each.

Location: ~/.claude/proposals/<id>.json. One file per proposal, so the two Macs' git sync merges by file and
never conflicts on an append (the ADR 0067 lesson). This module is the only reader and writer. The dashboard
calls its CLI, and the feeds (#532, #533) call add(). There is no second parser anywhere.

A proposal is visible in MR Review when it's open, or when its snooze or "dismiss until" backup date has passed.
In those cases it carries `returned` to say why it came back. A linked ticket closing is checked by #534, not here.

Complexity: list is O(N) small files (N = proposals ever made, tens to low hundreds; each capped at 256 KB);
an action is O(1): one file read, locked, rewritten atomically.

CLI (always prints JSON; exit 0 ok / 1 error):
  proposals.py list
  proposals.py add --json '<proposal>'
  proposals.py act <id> ticket|snooze|dismiss|until --json '<args>'
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import instance  # noqa: E402

ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
MAX_FILE_BYTES = 256 * 1024
NORTH_STARS = {1: "Minimise resources", 2: "Phone OS", 3: "Raise the human experience", 4: "Best tool for making tools"}
SIZES = ("Small", "Medium", "Large")
LIMITS = {"title": 140, "problem": 600, "fix": 600, "why": 600, "area": 40, "source": 60, "technical": 5000}
REQUIRED = ("title", "problem", "fix", "why")
GH = Path.home() / ".agents" / "bin" / "gh"


class ProposalError(Exception):
    pass


def default_root() -> Path:
    return Path.home() / ".claude" / "proposals"


# --- validation -----------------------------------------------------------------------------------------------------

def _text(proposal: dict, key: str, required: bool) -> str | None:
    v = proposal.get(key)
    if v is None and not required:
        return None
    if not isinstance(v, str) or not v.strip():
        raise ProposalError(f"{key} must be non-empty text")
    if len(v) > LIMITS[key]:
        raise ProposalError(f"{key} is longer than {LIMITS[key]} characters")
    return v.strip()


def _validate(proposal: object) -> dict:
    if not isinstance(proposal, dict):
        raise ProposalError("a proposal must be a JSON object")
    out = {k: _text(proposal, k, True) for k in REQUIRED}
    for k in ("area", "source", "technical"):
        v = _text(proposal, k, False)
        if v is not None:
            out[k] = v
    star = proposal.get("north_star")
    if type(star) is not int or star not in NORTH_STARS:
        raise ProposalError("north_star must be 1, 2, 3 or 4 (docs/north-stars.md)")
    out["north_star"] = star
    size = proposal.get("size")
    if size is not None and size not in SIZES:
        raise ProposalError(f"size must be one of {', '.join(SIZES)}")
    if size:
        out["size"] = size
    return out


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60].strip("-")
    return s or "proposal"


# --- files ----------------------------------------------------------------------------------------------------------

def _path(root: Path, pid: object) -> Path:
    if not isinstance(pid, str) or not ID_RE.fullmatch(pid):
        raise ProposalError(f"not a proposal id: {str(pid)[:60]!r}")
    return root / f"{pid}.json"


def _write_atomic(path: Path, record: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@contextmanager
def _locked(root: Path, pid: str):
    lock_dir = root / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    with open(lock_dir / f"{pid}.lock", "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def _read(path: Path) -> dict:
    if path.is_symlink():
        raise ProposalError("symlinks aren't read")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ProposalError(f"bigger than {MAX_FILE_BYTES // 1024} KB")
    data = json.loads(path.read_text())
    clean = _validate(data)
    if data.get("id") != path.stem:
        raise ProposalError("id doesn't match the file name")
    status = data.get("status")
    if not isinstance(status, dict) or not isinstance(status.get("state"), str):
        raise ProposalError("missing status")
    return {**data, **clean}


# --- public API -----------------------------------------------------------------------------------------------------

def add(root: Path, data: object, today: date | None = None) -> dict:
    clean = _validate(data)
    today = today or date.today()
    root.mkdir(parents=True, exist_ok=True)
    base = _slug(clean["title"])
    for n in range(1, 1000):
        pid = base if n == 1 else f"{base[:75]}-{n}"
        path = root / f"{pid}.json"
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)  # claim the name atomically
        except FileExistsError:
            continue
        os.close(fd)
        record = {"id": pid, **clean, "added": today.isoformat(), "status": {"state": "open"}, "history": []}
        _write_atomic(path, record)
        return record
    raise ProposalError("too many proposals with this title")


def _visible(rec: dict, today: date) -> dict | None:
    st = rec["status"]
    state = st["state"]
    if state == "open":
        return rec
    try:
        if state == "snoozed" and date.fromisoformat(st["until"]) <= today:
            return {**rec, "returned": f"Snooze ended {st['until']}"}
        if state == "dismissed_until" and date.fromisoformat(st["backup"]) <= today:
            return {**rec, "returned": f"Backup date {st['backup']} reached"}
    except (KeyError, TypeError, ValueError):
        return {**rec, "returned": "Its snooze or dismiss date couldn't be read, so it's back"}
    return None


def load_all(root: Path, today: date | None = None) -> dict:
    today = today or date.today()
    proposals, problems = [], []
    if not root.is_dir():
        return {"proposals": [], "problems": []}
    for path in sorted(root.glob("*.json")):
        try:
            rec = _read(path)
        except (ProposalError, ValueError, OSError) as exc:
            problems.append({"file": path.name, "error": str(exc)[:200]})
            continue
        shown = _visible(rec, today)
        if shown is not None:
            shown = {k: v for k, v in shown.items() if k != "history"}
            shown["north_star_name"] = NORTH_STARS[shown["north_star"]]
            proposals.append(shown)
    proposals.sort(key=lambda r: (r.get("added", ""), r["id"]), reverse=True)
    return {"proposals": proposals, "problems": problems}


def run_gh(args: list[str], body: str) -> tuple[int, str, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(body)
        body_file = f.name
    try:
        out = subprocess.run([str(GH), *args, "--body-file", body_file], capture_output=True, text=True, timeout=60)
        return out.returncode, out.stdout, out.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    finally:
        Path(body_file).unlink(missing_ok=True)


def _create_issue(gh: Callable, title: str, body: str) -> int:
    args = ["issue", "create", "-R", instance.tickets_repo(), "--title", title[:120], "--label", "needs-triage", "--label", "project:marvin"]
    rc, out, err = gh(args, body)
    if rc != 0:
        raise ProposalError(f"gh couldn't create the ticket: {(err or out).strip()[:200]}")
    m = re.search(r"/issues/(\d+)\s*$", out.strip())
    if not m:
        raise ProposalError(f"gh said it worked but returned no issue link: {out.strip()[:120]!r}")
    return int(m.group(1))


def _ticket_body(rec: dict) -> str:
    parts = [
        f"## Problem\n\n{rec['problem']}", f"## Fix\n\n{rec['fix']}", f"## Why it matters\n\n{rec['why']}",
        f"**North star:** {NORTH_STARS[rec['north_star']]}" + (f" · **Size:** {rec['size']}" if rec.get("size") else "")
        + (f" · **Area:** {rec['area']}" if rec.get("area") else ""),
    ]
    if rec.get("technical"):
        parts.append(f"## Technical details\n\n{rec['technical']}")
    parts.append(f"From proposal `{rec['id']}` (source: {rec.get('source', 'unknown')}, added {rec.get('added')}), "
                 "made a ticket from MR Review → Proposals (ADR 0068).")
    return "\n\n".join(parts) + "\n"


def _backup(value: object, today: date) -> str:
    if not isinstance(value, str):
        raise ProposalError("a backup date (YYYY-MM-DD) is required")
    try:
        d = date.fromisoformat(value)
    except ValueError:
        raise ProposalError(f"not a date: {value[:20]!r} (use YYYY-MM-DD)")
    if d <= today:
        raise ProposalError("the backup date has to be in the future")
    if d > today + timedelta(days=730):
        raise ProposalError("the backup date can be at most 2 years out")
    return d.isoformat()


def _new_status(rec: dict, action: str, args: dict, gh: Callable, today: date) -> dict:
    on = today.isoformat()
    if action == "ticket":
        return {"state": "ticketed", "ticket": _create_issue(gh, rec["title"], _ticket_body(rec)), "on": on}
    if action == "snooze":
        days = args.get("days")
        if type(days) is not int or not 1 <= days <= 365:
            raise ProposalError("snooze days must be a whole number from 1 to 365")
        return {"state": "snoozed", "until": (today + timedelta(days=days)).isoformat(), "on": on}
    if action == "dismiss":
        reason = args.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            raise ProposalError("a dismiss reason is required (up to 1000 characters)")
        return {"state": "dismissed", "reason": reason.strip(), "on": on}
    if action == "until":
        backup = _backup(args.get("backup"), today)
        kinds = [k for k in ("ticket", "text", "create_ticket") if args.get(k) is not None]
        if len(kinds) != 1:
            raise ProposalError("choose exactly one: a ticket number, a ticket to create, or a description")
        kind = kinds[0]
        status = {"state": "dismissed_until", "backup": backup, "on": on}
        if kind == "ticket":
            t = args["ticket"]
            if type(t) is not int or t <= 0:
                raise ProposalError("the ticket must be a number like 123")
            return {**status, "ticket": t}
        text = args[kind]
        if not isinstance(text, str) or not text.strip() or len(text) > 500:
            raise ProposalError("describe it in 1 to 500 characters")
        if kind == "text":
            return {**status, "text": text.strip()}
        body = (f"Prerequisite for proposal `{rec['id']}` (\"{rec['title']}\"). When this ticket closes, the proposal "
                "returns to MR Review → Proposals (ADR 0068).\n")
        return {**status, "ticket": _create_issue(gh, text.strip(), body)}
    raise ProposalError(f"unknown action: {str(action)[:30]!r}")


def act(root: Path, pid: object, action: str, args: dict | None = None, gh: Callable = run_gh,
        today: date | None = None) -> dict:
    today = today or date.today()
    args = args if isinstance(args, dict) else {}
    path = _path(root, pid)
    if not path.exists():
        raise ProposalError(f"no proposal {pid}")
    with _locked(root, pid):
        try:
            rec = _read(path)
        except (ValueError, OSError) as exc:
            raise ProposalError(f"proposal {pid} couldn't be read: {exc}")
        if _visible(rec, today) is None:
            raise ProposalError(f"proposal {pid} isn't open (it's {rec['status']['state']})")
        status = _new_status(rec, action, args, gh, today)  # may call gh; raises before anything is written
        history = rec.get("history") if isinstance(rec.get("history"), list) else []
        rec = {**rec, "status": status, "history": [*history, status]}
        _write_atomic(path, rec)
    out = {k: v for k, v in rec.items() if k != "history"}
    out["north_star_name"] = NORTH_STARS[rec["north_star"]]
    return out


# --- CLI ------------------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Proposals store (ADR 0068)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    a = sub.add_parser("add")
    a.add_argument("--json", required=True)
    c = sub.add_parser("act")
    c.add_argument("id")
    c.add_argument("action")
    c.add_argument("--json", default="{}")
    args = parser.parse_args(argv)
    root = default_root()
    try:
        if args.cmd == "list":
            print(json.dumps(load_all(root), ensure_ascii=False))
            return 0
        payload = json.loads(args.json)
        if args.cmd == "add":
            result = add(root, payload)
        else:
            result = act(root, args.id, args.action, payload)
        print(json.dumps({"ok": True, "proposal": result}, ensure_ascii=False))
        return 0
    except (ProposalError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:300]}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
