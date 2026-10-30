#!/usr/bin/env python3
"""box_memory_items.py — the one shape of a box item (ADR 0082), shared by the box (box_memory_export.py) and the Macs
(box_memory_review.py).

A box item is one change a Claude session on mac-mini-2012 made to memory or handoffs. Everything here treats it as
untrusted data: `check()` says why an item must be refused, or None. Its id is a hash of what it does, so the Mac
recomputes it and a forged or altered item never matches.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata

KINDS = ("memory-new", "memory-edit", "memory-delete", "handoff", "handoff-delete", "index-line")
MEMORY_KINDS = {"memory-new", "memory-edit", "memory-delete"}
HANDOFF_KINDS = {"handoff", "handoff-delete"}
DELETES = {"memory-delete", "handoff-delete"}
INDEX = "MEMORY.md"

# A plain file name: no folder, no "..", no leading dot or dash, .md only.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.md$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[0-9a-f]{16}$")

MEMORY_CAP = 64_000        # bytes of one memory file
HANDOFF_CAP = 256_000      # bytes of one handoff
LINE_CAP = 1_000           # characters of one MEMORY.md index line
BUNDLE_CAP = 4_000_000     # bytes of one export, all items together
MAX_ITEMS = 200


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def item_id(item: dict) -> str:
    content = item.get("content")
    key = [item.get("kind"), item.get("name"), item.get("base"),
           sha(content) if isinstance(content, str) else None, item.get("op")]
    return hashlib.sha256(json.dumps(key).encode("utf-8")).hexdigest()[:16]


def make(kind: str, name: str, *, base: str | None = None, content: str | None = None, op: str | None = None) -> dict:
    item = {"kind": kind, "name": name, "base": base, "content": content, "op": op}
    item["id"] = item_id(item)
    return item


def bad_char(text: str) -> str | None:
    """The first character no memory needs and that can hide or restructure text: control characters (other than
    newline and tab), format characters (bidi overrides, zero-width), and Unicode line/paragraph separators, which
    Python's splitlines() treats as line ends and markdown doesn't."""
    for ch in text:
        if ch in "\n\t":
            continue
        if unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp", "Cs", "Co", "Cn"):
            return f"U+{ord(ch):04X}"
    return None


def cap(kind: str) -> int:
    return HANDOFF_CAP if kind in HANDOFF_KINDS else LINE_CAP if kind == "index-line" else MEMORY_CAP


def check(item) -> str | None:
    """Why this item is refused, or None. Fields other than the six known ones are never read."""
    if not isinstance(item, dict):
        return "not an object"
    kind, name, base, content, op = (item.get(k) for k in ("kind", "name", "base", "content", "op"))
    if kind not in KINDS:
        return "unknown kind"
    if not isinstance(name, str):
        return "bad name"
    if kind == "index-line":
        if name != INDEX:
            return "bad name"
    elif not NAME_RE.match(name) or name == INDEX:
        return "bad name"
    if base is not None and (not isinstance(base, str) or not SHA_RE.match(base)):
        return "bad base"
    if kind == "index-line":
        if op not in ("add", "remove"):
            return "bad op"
    elif op is not None:
        return "bad op"
    if kind in DELETES:
        if content is not None or base is None:
            return "bad delete"
    else:
        if not isinstance(content, str):
            return "no content"
        if kind == "memory-new" and base is not None:
            return "bad base"
        if kind == "memory-edit" and base is None:
            return "bad base"
        if kind == "index-line":
            if base is not None or "\n" in content or not content.strip():
                return "bad index line"
            if len(content) > LINE_CAP:
                return "too big"
        elif len(content.encode("utf-8")) > cap(kind):
            return "too big"
        why = bad_char(content)
        if why:
            return f"hidden character {why}"
    if item.get("id") != item_id(item):
        return "id does not match"
    return None
