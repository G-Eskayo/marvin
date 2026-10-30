#!/usr/bin/env python3
"""box_memory_export.py — runs ON the Linux box (mac-mini-2012): what its Claude sessions changed in memory and
handoffs, as box items for a Mac to pull (ADR 0082). The box never pushes; a Mac runs `export` over ssh and reads stdout.

The box's ~/.claude is a pull-only mirror (`code_sync.py mirror`, ADR 0069): an edit to a tracked file is reset away on
its next run. So changes are first captured into the box outbox (~/.claude/box-outbox/, outside the synced allow-list),
by `code_sync.mirror` right before it resets and by every export. An outbox item is pruned once the mirror brings the
same content back (it was approved on a Mac) or after 30 days.

    box_memory_export.py export     capture, prune, then print {"version", "items", "skipped"} as JSON
    box_memory_export.py capture    capture only

Cost: O(files in the memory folder + handoffs) per run, each read once.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import box_memory_items as bi  # noqa: E402

CLAUDE = Path.home() / ".claude"
OUTBOX = CLAUDE / "box-outbox"
HANDOFFS = "handoffs"
KEEP_DAYS = 30


def _git(repo: Path, args: list[str]) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def _head_text(repo: Path, rel: str) -> str | None:
    r = subprocess.run(["git", "-C", str(repo), "show", f"HEAD:{rel}"], capture_output=True)
    if r.returncode != 0:
        return None
    try:
        return r.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def memory_dir(repo: Path) -> str | None:
    """The Macs' shared memory folder as the mirror holds it: the one tracked projects/<slug>/memory with a MEMORY.md."""
    try:
        tracked = _git(repo, ["ls-tree", "-r", "--name-only", "HEAD", "projects"]).splitlines()
    except subprocess.CalledProcessError:
        return None
    found = sorted({p[: -len("/MEMORY.md")] for p in tracked if p.count("/") == 3 and p.endswith("/memory/MEMORY.md")})
    return found[0] if len(found) == 1 else None


def _head_names(repo: Path, rel: str) -> set[str]:
    try:
        out = _git(repo, ["ls-tree", "--name-only", "HEAD", f"{rel}/"])
    except subprocess.CalledProcessError:
        return set()
    return {p.rsplit("/", 1)[-1] for p in out.splitlines()}


def _tree_texts(folder: Path, skipped: list) -> dict[str, str]:
    """name -> text of the regular .md files directly in `folder`. A symlink is never followed (it could point at any
    file on the box), nor is a file too big, not UTF-8 or with an odd name: those are reported as skipped."""
    out: dict[str, str] = {}
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return out
    for e in entries:
        if not e.name.endswith(".md"):
            continue
        if e.is_symlink() or not e.is_file(follow_symlinks=False):
            skipped.append({"name": e.name[:200], "reason": "not a plain file"})
            continue
        if not bi.NAME_RE.match(e.name):
            skipped.append({"name": e.name[:200], "reason": "bad name"})
            continue
        try:
            if e.stat(follow_symlinks=False).st_size > bi.HANDOFF_CAP:
                skipped.append({"name": e.name, "reason": "too big"})
                continue
            out[e.name] = Path(e.path).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            skipped.append({"name": e.name, "reason": "unreadable"})
    return out


def _folder_items(repo: Path, rel: str, new_kind: str, edit_kind: str, delete_kind: str, skipped: list) -> list[dict]:
    items = []
    wt = _tree_texts(repo / rel, skipped)
    head_names = {n for n in _head_names(repo, rel) if n.endswith(".md")}
    for name in sorted(set(wt) | head_names):
        if name == bi.INDEX and new_kind == "memory-new":
            continue
        before = _head_text(repo, f"{rel}/{name}") if name in head_names else None
        now = wt.get(name)
        if name in head_names and before is None:
            continue   # tracked but unreadable at HEAD: nothing safe to say about it
        if now is None:
            if (repo / rel / name).exists() or (repo / rel / name).is_symlink():
                continue   # present but skipped above
            items.append(bi.make(delete_kind, name, base=bi.sha(before)))
        elif before is None:
            items.append(bi.make(new_kind, name, content=now))
        elif now != before:
            items.append(bi.make(edit_kind, name, base=bi.sha(before), content=now))
    return items


def _index_items(repo: Path, rel: str) -> list[dict]:
    path = repo / rel / bi.INDEX
    if path.is_symlink():
        return []
    try:
        now = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    before = (_head_text(repo, f"{rel}/{bi.INDEX}") or "").splitlines()
    added = Counter(now) - Counter(before)
    removed = Counter(before) - Counter(now)
    items = [bi.make("index-line", bi.INDEX, content=line, op="add") for line in added if line.strip()]
    items += [bi.make("index-line", bi.INDEX, content=line, op="remove") for line in removed if line.strip()]
    return items


def changes(repo: Path) -> tuple[list[dict], list[dict]]:
    """(items, skipped): every change in the working tree against the mirror's HEAD, in memory and handoffs."""
    repo = Path(repo)
    skipped: list = []
    items: list[dict] = []
    mem = memory_dir(repo)
    if mem:
        items += _folder_items(repo, mem, "memory-new", "memory-edit", "memory-delete", skipped)
        items += _index_items(repo, mem)
    items += _folder_items(repo, HANDOFFS, "handoff", "handoff", "handoff-delete", skipped)
    ok = []
    for i in items:
        why = bi.check(i)
        if why:
            skipped.append({"name": i["name"], "reason": why})
        else:
            ok.append(i)
    return ok, skipped


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def capture(repo: Path = CLAUDE, outbox: Path = OUTBOX, items: list[dict] | None = None) -> int:
    """Saves every current change into the outbox (one file per item id). Returns how many were new."""
    if items is None:
        items, _ = changes(repo)
    new = 0
    for item in items:
        dest = Path(outbox) / f"{item['id']}.json"
        if not dest.exists():
            _write_json(dest, item)
            new += 1
    return new


def _landed(repo: Path, item: dict) -> bool:
    """True when the mirror's HEAD already shows this item's effect (a Mac approved it and it synced back)."""
    mem = memory_dir(repo)
    folder = HANDOFFS if item["kind"] in bi.HANDOFF_KINDS else mem
    if folder is None:
        return False
    head = _head_text(repo, f"{folder}/{item['name']}")
    if item["kind"] == "index-line":
        lines = (head or "").splitlines()
        return (item["content"] in lines) == (item["op"] == "add")
    if item["kind"] in bi.DELETES:
        return head is None
    return head == item["content"]


def outbox_items(repo: Path = CLAUDE, outbox: Path = OUTBOX, now: float | None = None) -> list[dict]:
    """The outbox's items still worth sending; prunes landed and expired ones."""
    now = time.time() if now is None else now
    out = []
    for f in sorted(Path(outbox).glob("*.json")) if Path(outbox).is_dir() else []:
        try:
            item = json.loads(f.read_text())
        except (OSError, ValueError):
            f.unlink(missing_ok=True)
            continue
        if bi.check(item) is not None or _landed(repo, item) or now - f.stat().st_mtime > KEEP_DAYS * 86400:
            f.unlink(missing_ok=True)
            continue
        out.append(item)
    return out


def export(repo: Path = CLAUDE, outbox: Path = OUTBOX) -> dict:
    current, skipped = changes(repo)
    capture(repo, outbox, current)
    items = outbox_items(repo, outbox)[: bi.MAX_ITEMS]
    return {"version": 1, "items": items, "skipped": skipped[:50]}


def main(argv: list[str]) -> int:
    if argv == ["export"]:
        print(json.dumps(export()))
        return 0
    if argv == ["capture"]:
        print(f"captured {capture()} new item(s)", file=sys.stderr)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
