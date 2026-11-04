#!/usr/bin/env python3
"""The inbox (marvin#1123 section 3, ADR 0083 decision 5): every pile of things waiting for MARVIN or Gil, one JSON file
per item, one reader and writer.

Location: ~/.claude/inbox/<pile>/<id>.json. One file per item, so the two Macs' git sync merges by file and never
conflicts on an append (the ADR 0067 lesson). The file rules are the Proposals store's (ADR 0068), which now imports
them from here: ids matched by ID_RE and claimed exclusively, atomic writes, a lock per item, a size cap, symlinks
refused, and a bad file reported as a problem, never fatal.

An item: {id, pile, title, body, added, source?, key?, fields{...}, status{state, on, ...}, history[]}. `key` is an
optional dedupe key: adding an item whose key is already in the pile returns the one that's there. A keyed item's id
ends in a hash of its key, so the same item added on both Macs gets the same file name; an unkeyed item's id ends in
random hex, so two different items with one title never collide across machines.

Piles move in one at a time (design doc table, docs/design/1123-loop-kernel.md). Each has a legacy markdown file and a
parser for it here (the only parser): `import <pile>` reads it once and adds every entry, keyed by its content, so
re-running adds nothing. The old file is never changed and stays as a read-only backup. The first write to a pile whose
folder doesn't exist yet imports the legacy file first, so a reader never switches to a half-filled pile.

Complexity: list is O(N) small files (each capped at 256 KB); act is O(1) (one locked read and atomic rewrite); a keyed
add is O(N) under the pile lock (one scan for the key); an import of M entries is O(N + M) under one lock.

CLI (always prints JSON; exit 0 ok / 1 error):
  inbox.py list <pile>
  inbox.py add <pile> --json '<item>'
  inbox.py act <pile> <id> <state> [--json '<extra status fields>']
  inbox.py set <pile> <id> --json '<fields to merge>'
  inbox.py import <pile> [--file <markdown file in the legacy format>]
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Callable, Iterable

ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
PILE_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
STATE_RE = re.compile(r"[a-z][a-z0-9_-]{0,39}")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_FILE_BYTES = 256 * 1024
LIMITS = {"title": 500, "body": 64 * 1024, "source": 200, "key": 200}
PILE_LOCK = "_pile"  # never a valid item id, so it can't collide with an item's lock


class InboxError(Exception):
    pass


def default_root() -> Path:
    return Path.home() / ".claude" / "inbox"


# --- the file rules (shared with proposals.py) ----------------------------------------------------------------------

def check_id(iid: object, error: type[Exception] = InboxError, noun: str = "item") -> str:
    if not isinstance(iid, str) or not ID_RE.fullmatch(iid):
        raise error(f"not {'an' if noun[0] in 'aeiou' else 'a'} {noun} id: {str(iid)[:60]!r}")
    return iid


def slug(title: str, fallback: str = "item", width: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:width].strip("-")
    return s or fallback


def write_atomic(path: Path, record: dict) -> None:
    """Write to a temp file in the same folder and rename it over `path`: a reader sees the old file or the new one,
    never half of one."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def create_exclusive(path: Path, record: dict) -> bool:
    """Claim `path` and fill it in one step: False, touching nothing, if it already exists. The record is written to a
    temp file first and hard-linked into place (link fails with EEXIST exactly as O_EXCL does), so no reader ever sees
    an empty or half-written claim."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
            f.write("\n")
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False
        return True
    finally:
        Path(tmp).unlink(missing_ok=True)


@contextmanager
def locked(root: Path, name: str):
    lock_dir = root / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    with open(lock_dir / f"{name}.lock", "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def read_json(path: Path, error: type[Exception] = InboxError) -> object:
    """A store file's JSON, refusing a symlink (it could point anywhere) and anything over MAX_FILE_BYTES."""
    if path.is_symlink():
        raise error("symlinks aren't read")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise error(f"bigger than {MAX_FILE_BYTES // 1024} KB")
    return json.loads(path.read_text())


# --- piles ----------------------------------------------------------------------------------------------------------

def check_pile(pile: object) -> str:
    if not isinstance(pile, str) or not PILE_RE.fullmatch(pile):
        raise InboxError(f"not a pile name: {str(pile)[:60]!r}")
    return pile


def pile_dir(pile: str, root: Path | None = None) -> Path:
    return (root or default_root()) / check_pile(pile)


def pile_exists(pile: str, root: Path | None = None) -> bool:
    """True once the pile has moved into the inbox: its folder is a real folder (not a symlink). Readers fall back to
    the legacy file until then."""
    d = pile_dir(pile, root)
    return d.is_dir() and not d.is_symlink()


# --- items ----------------------------------------------------------------------------------------------------------

def _text(item: dict, key: str, required: bool) -> str | None:
    v = item.get(key)
    if v is None and not required:
        return None
    if not isinstance(v, str) or (required and not v.strip()):
        raise InboxError(f"{key} must be {'non-empty ' if required else ''}text")
    if len(v) > LIMITS[key]:
        raise InboxError(f"{key} is longer than {LIMITS[key]} characters")
    return v.strip()


def _status(value: object) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("state"), str) or not STATE_RE.fullmatch(value["state"]):
        raise InboxError("status must be an object with a state (lower-case word)")
    on = value.get("on")
    if on is not None and (not isinstance(on, str) or not DATE_RE.fullmatch(on)):
        raise InboxError("status.on must be a YYYY-MM-DD date")
    return value


def _validate(item: object) -> dict:
    """The submitted part of an item (no id, pile or history: the store sets those)."""
    if not isinstance(item, dict):
        raise InboxError("an item must be a JSON object")
    out = {"title": _text(item, "title", True), "body": _text(item, "body", False) or ""}
    for k in ("source", "key"):
        v = _text(item, k, False)
        if v:
            out[k] = v
    added = item.get("added")
    if added is not None and (not isinstance(added, str) or not DATE_RE.fullmatch(added)):
        raise InboxError("added must be a YYYY-MM-DD date")
    out["added"] = added
    fields = item.get("fields", {})
    if not isinstance(fields, dict):
        raise InboxError("fields must be an object")
    out["fields"] = fields
    out["status"] = _status(item.get("status", {"state": "open"}))
    return out


def _check_record(data: object, path: Path, pile: str) -> dict:
    if not isinstance(data, dict):
        raise InboxError("not a JSON object")
    clean = _validate(data)
    if data.get("id") != path.stem:
        raise InboxError("id doesn't match the file name")
    if data.get("pile") != pile:
        raise InboxError("pile doesn't match its folder")
    if not isinstance(data.get("history", []), list):
        raise InboxError("history must be a list")
    return {**data, **clean, "history": data.get("history", [])}


def _read(path: Path, pile: str) -> dict:
    return _check_record(read_json(path), path, pile)


def _scan(d: Path, pile: str) -> tuple[list[dict], list[dict]]:
    items, problems = [], []
    if not d.is_dir():
        return items, problems
    for path in sorted(d.glob("*.json")):
        try:
            items.append(_read(path, pile))
        except (InboxError, ValueError, OSError) as exc:
            problems.append({"file": path.name, "error": str(exc)[:200]})
    return items, problems


def _new_id(d: Path, title: str, key: str | None) -> list[str]:
    """Candidate ids, in order: slug + a hash of the key (the same on every machine), or slug + random hex."""
    base = slug(title, width=60)
    tail = hashlib.sha256(key.encode()).hexdigest()[:8] if key else secrets.token_hex(4)
    first = f"{base}-{tail}"
    return [first] + [f"{first}-{n}" for n in range(2, 100)]


def _fits(record: dict) -> dict:
    """Refuse a record that would be over the size cap: written, it could never be read back."""
    try:
        size = len(json.dumps(record, indent=2, ensure_ascii=False).encode())
    except (TypeError, ValueError) as exc:
        raise InboxError(f"not storable as JSON: {exc}")
    if size > MAX_FILE_BYTES - 1024:
        raise InboxError(f"the item would be bigger than {MAX_FILE_BYTES // 1024} KB")
    return record


def _create(d: Path, pile: str, clean: dict, today: date) -> dict:
    for iid in _new_id(d, clean["title"], clean.get("key")):
        record = _fits({"id": iid, "pile": pile, **clean, "added": clean["added"] or today.isoformat(), "history": []})
        if create_exclusive(d / f"{iid}.json", record):
            return record
    raise InboxError("too many items with this title")


def _add_unlocked(d: Path, pile: str, clean: dict, today: date, keys: dict[str, dict] | None) -> tuple[dict, bool]:
    key = clean.get("key")
    if key and keys is not None and key in keys:
        return keys[key], False
    record = _create(d, pile, clean, today)
    if key and keys is not None:
        keys[key] = record
    return record, True


def _keys(d: Path, pile: str) -> dict[str, dict]:
    items, _ = _scan(d, pile)
    return {i["key"]: i for i in items if i.get("key")}


def add(pile: str, item: object, root: Path | None = None, today: date | None = None) -> tuple[dict, bool]:
    """Add one item; (record, created). A keyed item already in the pile isn't added again: (the existing one, False)."""
    clean = _validate(item)
    today = today or date.today()
    d, _ = _pile_ready(pile, root, today)
    if not clean.get("key"):
        return _create(d, pile, clean, today), True
    with locked(d, PILE_LOCK):
        return _add_unlocked(d, pile, clean, today, _keys(d, pile))


def _add_many_in(d: Path, pile: str, items: Iterable[object], today: date) -> dict:
    added, existing, problems = [], 0, []
    with locked(d, PILE_LOCK):
        keys = _keys(d, pile)
        for n, item in enumerate(items):
            try:
                record, created = _add_unlocked(d, pile, _validate(item), today, keys)
            except InboxError as exc:
                problems.append({"entry": n, "error": str(exc)[:200]})
                continue
            if created:
                added.append(record["id"])
            else:
                existing += 1
    return {"added": len(added), "already_there": existing, "ids": added, "problems": problems}


def add_many(pile: str, items: Iterable[object], root: Path | None = None, today: date | None = None) -> dict:
    """Add several items under one pile lock (one scan for keys). A bad item is reported, never fatal."""
    today = today or date.today()
    d, _ = _pile_ready(pile, root, today)
    return _add_many_in(d, pile, items, today)


def get(pile: str, iid: object, root: Path | None = None) -> dict:
    d = pile_dir(pile, root)
    path = d / f"{check_id(iid)}.json"
    if not path.exists() and not path.is_symlink():
        raise InboxError(f"no item {iid} in {pile}")
    try:
        return _read(path, pile)
    except (ValueError, OSError) as exc:
        raise InboxError(f"item {iid} couldn't be read: {exc}")


def _change(pile: str, iid: object, root: Path | None, edit: Callable[[dict], tuple[dict, dict]]) -> dict:
    d = pile_dir(pile, root)
    check_id(iid)
    if d.is_symlink():
        raise InboxError(f"pile {pile} is a symlink; refusing to write through it")
    if not (d / f"{iid}.json").exists():
        raise InboxError(f"no item {iid} in {pile}")
    with locked(d, iid):
        rec = get(pile, iid, root)
        rec, entry = edit(rec)
        rec["history"] = [*rec["history"], entry]
        write_atomic(d / f"{iid}.json", _fits(rec))
    return rec


def act(pile: str, iid: object, state: str, extra: dict | None = None, root: Path | None = None,
        today: date | None = None) -> dict:
    """Set an item's status to `state` (plus any extra fields, e.g. note, ticket) on today's date, recorded in its
    history."""
    extra = extra if isinstance(extra, dict) else {}
    status = _status({**extra, "state": state, "on": (today or date.today()).isoformat()})
    if len(json.dumps(status)) > 4000:
        raise InboxError("status is too big")
    return _change(pile, iid, root, lambda rec: ({**rec, "status": status}, status))


set_status = act


def update_fields(pile: str, iid: object, fields: object, root: Path | None = None, today: date | None = None) -> dict:
    """Merge `fields` into an item's fields (e.g. a new priority), recorded in its history."""
    if not isinstance(fields, dict) or not fields:
        raise InboxError("fields must be a non-empty object")
    on = (today or date.today()).isoformat()
    return _change(pile, iid, root, lambda rec: ({**rec, "fields": {**rec["fields"], **fields}},
                                                  {"fields": fields, "on": on}))


def list_items(pile: str, root: Path | None = None) -> dict:
    """{"items": [...], "problems": [...]}, in the pile's own order (ORDER) or newest first."""
    items, problems = _scan(pile_dir(pile, root), pile)
    items.sort(key=ORDER.get(pile, _newest_first))
    return {"items": items, "problems": problems}


def open_items(pile: str, root: Path | None = None) -> list[dict]:
    return [i for i in list_items(pile, root)["items"] if i["status"]["state"] == "open"]


def _newest_first(item: dict) -> tuple:
    return (-int((item.get("added") or "0000-00-00").replace("-", "")), item["id"])


# --- pile: suggestions (ADR 0017's backlog) -------------------------------------------------------------------------

IMPACT_RANK = {"token-reduction": 0, "speed": 1, "organization": 2, "pipeline-logic": 3, "reliability": 4, "robustness": 5}
EFFORT_RANK = {"low": 0, "medium": 1, "high": 2}
_HEADER_RE = re.compile(r"^## (.*)$", re.M)
_FIELD_RE = {k: re.compile(rf"^\*\*{k.title()}\*\*:[ \t]*(.*)$", re.M) for k in ("priority", "status", "impact", "effort", "added")}
_STATUS_RE = re.compile(r"(\w+)(?:\s+(\d{4}-\d{2}-\d{2}))?\s*(.*)", re.S)


def suggestion_order(item: dict) -> tuple:
    """ADR 0017's order, applied when read: open first, then priority (high first), impact, effort, oldest."""
    f = item.get("fields") or {}
    prio = f.get("priority")
    return (0 if item["status"]["state"] == "open" else 1, -prio if type(prio) is int else 0,
            IMPACT_RANK.get(f.get("impact"), 99), EFFORT_RANK.get(f.get("effort"), 99), item.get("added") or "", item["id"])


def md_status(text: str, fallback_on: str | None) -> dict:
    """A legacy Status line ("pending", "promoted 2026-10-15 https://…", "declined 2026-11-01 (reason)") as a status."""
    m = _STATUS_RE.fullmatch(text.strip())
    if not m or not m.group(1):
        return {"state": "open"}
    word = m.group(1).lower()
    state = "open" if word in ("pending", "open") else (word if STATE_RE.fullmatch(word) else "other")
    status = {"state": state}
    on = m.group(2) or (fallback_on if state != "open" else None)
    if on:
        status["on"] = on
    note = m.group(3).strip()
    if state == "other":
        note = text.strip()
    if note:
        status["note"] = note[:1000]
    return status


def parse_suggestions(text: str, source: str = "suggestions.md") -> list[dict]:
    """Every `## title` entry as an item. Fields: priority, impact, effort (the first line of each); the rest of the
    entry is the body, verbatim. Keyed by the entry's own text, so the same entry imports once."""
    matches = list(_HEADER_RE.finditer(text))
    out = []
    for i, m in enumerate(matches):
        block = text[m.start():matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip()
        rest = block[len(m.group(0)):]
        found = {k: r.search(rest) for k, r in _FIELD_RE.items()}
        spans = sorted((f.start(), f.end()) for f in found.values() if f)
        kept, at = [], 0
        for a, b in spans:  # the body is the entry minus the first line of each parsed field
            kept.append(rest[at:a])
            at = b + 1 if rest[b:b + 1] == "\n" else b
        kept.append(rest[at:])
        rest = "".join(kept)
        added = found["added"] and DATE_RE.match(found["added"].group(1).strip())
        fields = {}
        if found["priority"] and re.fullmatch(r"\d{1,3}", found["priority"].group(1).strip()):
            fields["priority"] = int(found["priority"].group(1).strip())
        for k in ("impact", "effort"):
            if found[k] and found[k].group(1).strip():
                fields[k] = found[k].group(1).strip().split()[0].lower()[:40]
        added_on = added.group(0) if added else None
        out.append({
            "title": (m.group(1).strip() or "(untitled)")[:LIMITS["title"]],
            "body": rest.strip()[:LIMITS["body"]], "added": added_on, "source": source, "fields": fields,
            "status": md_status(found["status"].group(1), added_on) if found["status"] else {"state": "open"},
            "key": "md:" + hashlib.sha256(block.encode("utf-8", "surrogateescape")).hexdigest()[:32],
        })
    return out


def render_suggestion(item: dict) -> str:
    """An item back in the entry format (what ticket promotion and the reviewer read)."""
    f, st = item.get("fields") or {}, item["status"]
    status = "pending" if st["state"] == "open" else " ".join(x for x in (st["state"], st.get("on"), st.get("note")) if x)
    lines = [f"## {item['title']}"]
    if "priority" in f:
        lines.append(f"**Priority**: {f['priority']}")
    lines.append(f"**Status**: {status}")
    for k in ("impact", "effort"):
        if f.get(k):
            lines.append(f"**{k.title()}**: {f[k]}")
    if item.get("body"):
        lines.append(item["body"])
    if item.get("added"):
        lines.append(f"**Added**: {item['added']}")
    return "\n".join(lines) + "\n"


# --- pile: improvement-queue (the improve sweep's findings, fixed by auto_fix.py) -----------------------------------

QUEUE_SECTION_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2}) — (.+)$")
QUEUE_LINE_RE = re.compile(r"^- (\*\*\[([A-Z]+)\]\*\* (.+?) \(`([^`\n]+)`\))(?: — auto-fix: (.*))?$")
QUEUE_MARK_STATES = (("in PR", "in_pr"), ("done", "done"), ("skipped", "skipped"), ("tried", "tried"))


def queue_status(mark: str | None, on: str | None = None) -> dict:
    """An auto-fix mark ("in PR #712 (2026-10-26)", "done, PR #712 merged", "skipped 2026-10-26, …") as a status;
    the mark text is kept whole in `note`, so auto_fix reads back exactly what it wrote."""
    if not mark:
        return {"state": "open"}
    state = next((s for prefix, s in QUEUE_MARK_STATES if mark.startswith(prefix)), "marked")
    d = DATE_RE.search(mark)
    status = {"state": state, "note": mark[:1000]}
    if d or on:
        status["on"] = d.group(0) if d else on
    return status


def queue_item(entry: str, kind: str | None, message: str, path: str | None, project: str, added: str | None,
               mark: str | None = None, source: str = "improvement-queue.md") -> dict:
    """One finding. `entry` (the bullet without its mark) is its identity: the same finding on a later day is the
    same item, keyed by it."""
    fields = {"entry": entry, "project": project[:80]}
    if kind:
        fields.update(kind=kind, message=message, path=path)
    return {"title": (f"[{kind}] {message}" if kind else message)[:LIMITS["title"]], "body": "", "added": added,
            "source": source, "fields": fields, "status": queue_status(mark, added),
            "key": "entry:" + hashlib.sha256(entry.encode("utf-8", "surrogateescape")).hexdigest()[:32]}


def queue_line_item(line: str, project: str, day: str | None, source: str) -> dict:
    """One `- **[KIND]** message (`path`)[ — auto-fix: mark]` bullet (or any other bullet, untyped) as an item."""
    m = QUEUE_LINE_RE.match(line)
    if m:
        entry, kind, message, path, mark = m.groups()
        return queue_item(entry, kind, message, path.strip(), project, day, mark, source)
    entry = line[2:].strip()[:LIMITS["title"]]
    return queue_item(entry, None, entry, None, project, day, None, source)


def parse_queue(text: str, source: str = "improvement-queue.md") -> list[dict]:
    """Every bullet in a dated `## YYYY-MM-DD — project` section, first-seen (oldest) first, identical bullets folded
    into the first (a later copy's mark is kept if the first had none, as auto_fix.parse_queue does)."""
    seen: dict[str, dict] = {}
    day = project = None
    for line in text.splitlines():
        s = QUEUE_SECTION_RE.match(line)
        if s:
            day, project = s.group(1), s.group(2).strip()
            continue
        if day is None or not line.startswith("- ") or not line[2:].strip():
            continue
        item = queue_line_item(line, project, day, source)
        entry = item["fields"]["entry"]
        first = seen.get(entry)
        if first is None:
            seen[entry] = item
        elif mark_of(item) and not mark_of(first):
            first["status"] = item["status"]
    return list(seen.values())


def mark_of(item: dict) -> str | None:
    st = item["status"]
    return None if st["state"] == "open" else (st.get("note") or st["state"])


# --- legacy files and import ----------------------------------------------------------------------------------------

PARSERS: dict[str, Callable[[str, str], list[dict]]] = {"suggestions": parse_suggestions, "improvement-queue": parse_queue}
ORDER: dict[str, Callable[[dict], tuple]] = {"suggestions": suggestion_order,
                                             "improvement-queue": lambda i: (i.get("added") or "", i["title"], i["id"])}


def legacy_file(pile: str, root: Path | None = None) -> Path:
    """The pile's old markdown file, beside the inbox folder: ~/.claude/<pile>.md."""
    return (root or default_root()).parent / f"{check_pile(pile)}.md"


def read_legacy(path: Path) -> str:
    """A markdown file to import: refused if it's a symlink or over 32 MB; empty if missing."""
    if path.is_symlink():
        raise InboxError(f"{path.name} is a symlink; not imported")
    if not path.exists():
        return ""
    if path.stat().st_size > 32 * 1024 * 1024:
        raise InboxError(f"{path.name} is over 32 MB; not imported")
    return path.read_text(errors="replace")


def _parse(pile: str, text: str, source: str) -> list[dict]:
    if pile not in PARSERS:
        raise InboxError(f"pile {pile} has no markdown importer (only {', '.join(sorted(PARSERS))})")
    return PARSERS[pile](text, source)


def import_text(pile: str, text: str, root: Path | None = None, today: date | None = None,
                source: str | None = None) -> dict:
    """Add every entry of `text` (the pile's legacy markdown format). Idempotent: entries are keyed by content."""
    items = _parse(pile, text, source or f"{pile}.md")
    return add_many(pile, items, root, today)


def import_legacy(pile: str, root: Path | None = None, file: Path | None = None, today: date | None = None) -> dict:
    """The one-time move of a pile's legacy file into the inbox; re-running adds nothing. The file is only read."""
    today = today or date.today()
    path = file or legacy_file(pile, root)
    d, first = _pile_ready(pile, root, today)
    if first is not None and file is None:
        return {**first, "from": str(path)}
    out = _add_many_in(d, pile, _parse(pile, read_legacy(path), path.name), today)
    return {**out, "from": str(path)}


def _pile_ready(pile: str, root: Path | None, today: date) -> tuple[Path, dict | None]:
    """The pile's folder, made on first use. A new pile is built in a hidden staging folder, with the legacy file
    imported into it, and renamed into place in one step: a reader that switches to the inbox when the folder appears
    never sees half a pile, and of two processes making it at once one wins and the other's copy is dropped.
    Returns (folder, the import's counts when this call made the pile, else None)."""
    d = pile_dir(pile, root)
    if d.is_symlink():
        raise InboxError(f"pile {pile} is a symlink; refusing to write through it")
    if d.is_dir():
        return d, None
    d.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(dir=d.parent, prefix=f".{pile}.new-"))
    result = None
    try:
        legacy = legacy_file(pile, root) if pile in PARSERS else None
        if legacy is not None and (legacy.exists() or legacy.is_symlink()):
            result = _add_many_in(stage, pile, _parse(pile, read_legacy(legacy), legacy.name), today)
        try:
            os.rename(stage, d)
        except OSError:
            if not d.is_dir():
                raise
            return d, None  # another process made it first; its copy is complete
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
    return d, result


# --- CLI ------------------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The inbox (ADR 0083)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").add_argument("pile")
    a = sub.add_parser("add")
    a.add_argument("pile")
    a.add_argument("--json", required=True)
    c = sub.add_parser("act")
    c.add_argument("pile")
    c.add_argument("id")
    c.add_argument("state")
    c.add_argument("--json", default="{}")
    s = sub.add_parser("set")
    s.add_argument("pile")
    s.add_argument("id")
    s.add_argument("--json", required=True)
    i = sub.add_parser("import")
    i.add_argument("pile")
    i.add_argument("--file")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        print(json.dumps({"ok": False, "error": "bad arguments (see inbox.py --help)"}))
        return 1 if exc.code else 0
    try:
        if args.cmd == "list":
            print(json.dumps(list_items(args.pile), ensure_ascii=False))
            return 0
        if args.cmd == "import":
            result = import_legacy(args.pile, file=Path(args.file).expanduser() if args.file else None)
            print(json.dumps({"ok": True, **result}, ensure_ascii=False))
            return 0
        payload = json.loads(args.json)
        if args.cmd == "add":
            record, created = add(args.pile, payload)
            print(json.dumps({"ok": True, "created": created, "item": record}, ensure_ascii=False))
        elif args.cmd == "act":
            print(json.dumps({"ok": True, "item": act(args.pile, args.id, args.state, payload)}, ensure_ascii=False))
        else:
            print(json.dumps({"ok": True, "item": update_fields(args.pile, args.id, payload)}, ensure_ascii=False))
        return 0
    except (InboxError, ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:300]}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
