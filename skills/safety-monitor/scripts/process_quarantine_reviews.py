#!/usr/bin/env python3
"""Closes the loop calibrate.py's record_label() was always meant to have.

Found 2026-07-09: quarantine.md has approve/modify/deny checkboxes, and
calibrate.py's record_label() docstring says "Intended caller: the
quarantine review workflow, once built" — but nothing ever read the
checkboxes back into calibration. Zero of 18 boxes had ever been checked,
tau.json didn't exist, and every daily_digest/research_colony run was
getting quarantined at the frozen default threshold forever, with no way
for the system to learn from real review decisions.

Splits quarantine.md on its entry-header pattern (`## YYYY-MM-DD — name
[SAFETY, ...]`), not the plain "---" separator — a bare "---" can appear
inside a quoted entry's own body (found 2026-07-09: a pre-2026-07-08-fix
legacy entry only quoted its first line, leaving a literal unquoted "---"
markdown divider in its body, which broke a first attempt at splitting on
that instead). The header pattern is specific enough not to collide with
real digest content. Finds entries with a checked box, calls
calibrate.record_label() for each (approve/modify -> 0 "was actually fine",
deny -> 1 "was actually bad"), then removes those entries from quarantine.md
so they don't get re-processed and the pending count stays accurate.

Since 2026-10-26 the dashboard's review cards (Health ▸ Safety reviews) read entries with `list` and tick one box
with `answer`, both through this file's parser. Every write here and in verify.quarantine() is locked and atomic,
an answered entry's own lines are removed but its trailing divider stays (so two Macs' answers to adjacent entries
merge in git without a conflict), and nothing else in the file is rewritten or reordered.

Box memory cards (loop `box_memory`, ADR 0082) are the exception to "answered entries are removed here": the primary Mac's
box_memory_review.settle acts on the tick, then records the label and removes the entry. On the primary, every answer
settles at once and every no-argument run also starts a background pull from the Linux box.

Run standalone or via launchd: ~/.agents/venv/bin/python process_quarantine_reviews.py
Dashboard: process_quarantine_reviews.py list | answer --id ID --kind approve|modify|deny [--text NOTE]
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import calibrate  # noqa: E402
import shared_labels  # noqa: E402  (records on the primary host, or queues for it)

QUARANTINE_FILE = Path.home() / ".claude" / "quarantine.md"

HEADER_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2}) — (\S+) \[SAFETY, score ([\d.]+), tau ([\d.]+)\]", re.MULTILINE)
CHECKBOX_RE = re.compile(r"^- \[([ xX])\] (approve|deny|modify)")
KINDS = ("approve", "modify", "deny")
REASON_PREFIX = "Flagged reason:"
BODY_CAP = 50_000      # characters of an entry's text sent to the dashboard (the file itself is never cut)
EXCERPT_CAP = 280
NOTE_CAP = 1_000       # a "modify" note: one line, stored as data
LOCK_TIMEOUT_S = 10.0
SETTLED_ELSEWHERE = {"box_memory"}   # answered entries another step acts on and removes (box_memory_review.py)


def _split_entries(text: str) -> tuple[str, list[str]]:
    """Splits on the entry-header pattern, not "---" (which can appear
    unquoted inside a legacy entry's own body). Returns (preamble, blocks) —
    each block starts right at its own "## date — name [SAFETY..." header."""
    matches = list(HEADER_RE.finditer(text))
    if not matches:
        return text, []
    preamble = text[:matches[0].start()]
    blocks = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append(text[m.start():end])
    return preamble, blocks


def _parse_block(block: str) -> dict | None:
    header_match = HEADER_RE.search(block)
    if not header_match:
        return None
    date, loop_name, score_str, tau_str = header_match.groups()

    checked_kind = None
    note = None
    for line in block.splitlines():
        cb = CHECKBOX_RE.match(line.strip())
        if cb and cb.group(1).strip().lower() == "x":
            checked_kind = cb.group(2)
            if checked_kind == "modify":
                note = line.strip().split("modify", 1)[1].lstrip(":").strip() or None
            break

    return {
        "date": date, "loop_name": loop_name, "score": float(score_str),
        "tau": float(tau_str), "checked": checked_kind, "note": note,
    }


# --- one writer: lock, atomic replace, entry identity ----------------------------------------------------------
#
# quarantine.md syncs between Macs by git, and verify.quarantine() appends to it from background loops. Every write
# goes through locked() + atomic_write(): a sidecar flock (the file itself is replaced, so it cannot hold the lock)
# and a temp file renamed over the original, so no reader, git included, ever sees half a file. A ~/.claude dotfile
# is outside the sync's allow-list, so the lock and temp files never travel.

def _lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


@contextmanager
def locked(path: Path | None = None, timeout: float = LOCK_TIMEOUT_S):
    path = Path(path or QUARANTINE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(_lock_path(path), os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"{path} is locked by another writer")
                time.sleep(0.02)
        yield path
    finally:
        os.close(fd)  # closing releases the flock


def atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, path.stat().st_mode & 0o777)
        except FileNotFoundError:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _is_box(line: str) -> bool:
    return bool(CHECKBOX_RE.match(line.strip()))


def _tail(block: str) -> str:
    """The block's trailing blank and "---" lines. An answered entry leaves these behind so the lines between two
    removed entries never change: git merges two Macs' removals of adjacent entries cleanly (removing the whole
    block made the two deletions touch, which git reports as a conflict)."""
    lines = block.splitlines(keepends=True)
    i = len(lines)
    while i > 0 and lines[i - 1].strip() in ("", "---"):
        i -= 1
    return "".join(lines[i:])


def _content_lines(block: str) -> list[str]:
    lines = block[: len(block) - len(_tail(block))].splitlines()
    return [ln for ln in lines if not _is_box(ln)]


def entry_id(block: str) -> str:
    """The entry's identity: its header and text, without the checkboxes (ticking does not change it) or the
    trailing divider. Matched on every write, never a position: another Mac may have added or removed entries."""
    return hashlib.sha256("\n".join(_content_lines(block)).encode("utf-8")).hexdigest()[:16]


def _boxes(block: str) -> set[str]:
    return {m.group(2) for ln in block.splitlines() if (m := CHECKBOX_RE.match(ln.strip()))}


def _unquote(line: str) -> str:
    return line[2:] if line.startswith("> ") else line[1:] if line.startswith(">") else line


def _view(block: str) -> dict:
    info = _parse_block(block)
    lines = _content_lines(block)[1:]  # drop the header
    reason = ""
    body_lines = []
    for ln in lines:
        if ln.startswith(REASON_PREFIX) and not reason:
            reason = ln[len(REASON_PREFIX):].strip()
        else:
            body_lines.append(_unquote(ln))
    body = "\n".join(body_lines).strip()
    flat = " ".join(body[: EXCERPT_CAP * 4].split())
    excerpt = flat if len(flat) <= EXCERPT_CAP else flat[:EXCERPT_CAP].rstrip() + "…"
    return {
        "id": entry_id(block), "date": info["date"], "loop": info["loop_name"], "score": info["score"],
        "tau": info["tau"], "reason": reason, "excerpt": excerpt, "body": body[:BODY_CAP],
        "truncated": len(body) > BODY_CAP,
    }


def list_pending(path: Path | None = None) -> dict:
    """Unanswered entries, in file order, for the dashboard's review cards. An entry with only some of its three boxes
    (a torn or hand-damaged write) is counted as unreadable, not shown. One with none at all (older entries lost their
    footer in past sync conflicts) is shown: answering it adds the standard footer, ticked, to that entry alone."""
    text = _read(Path(path or QUARANTINE_FILE)) or ""
    entries, unreadable = [], 0
    for block in _split_entries(text)[1]:
        info = _parse_block(block)
        if info is None or info["checked"]:
            continue
        if _boxes(block) not in (set(), set(KINDS)):
            unreadable += 1
            continue
        entries.append(_view(block))
    return {"entries": entries, "pending": len(entries), "unreadable": unreadable}


FOOTER = "- [ ] approve (ships as-is)\n- [ ] modify: ____________\n- [ ] deny\n"


def _tick(block: str, kind: str, note: str) -> str:
    """Ticks the entry's own box for `kind` (its last such line: the footer, never quoted body text). Only that one
    line changes. An entry with no boxes at all first gets the standard footer, inside its own lines."""
    if not _boxes(block):
        tail = _tail(block)
        head = block[: len(block) - len(tail)]
        block = head + ("\n" if head.endswith("\n") else "\n\n") + FOOTER + tail
    lines = block.splitlines(keepends=True)
    for i in range(len(lines) - 1, -1, -1):
        m = CHECKBOX_RE.match(lines[i].strip())
        if m and m.group(2) == kind:
            indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
            end = "\n" if lines[i].endswith("\n") else ""
            if kind == "modify":
                lines[i] = f"{indent}- [x] modify: {note}{end}"
            else:
                lines[i] = indent + lines[i].lstrip().replace("[ ]", "[x]", 1).replace("[X]", "[x]", 1)
            return "".join(lines)
    raise ValueError(f"entry has no {kind} box")


def _clean_note(text) -> str:
    # One line of plain data: whitespace (newlines included) collapses, control characters go. It can never start a
    # new line, so it can never become a header or another box.
    s = "".join(ch for ch in str(text or "") if ch.isprintable() or ch.isspace())
    return " ".join(s.split())


def answer(eid: str, kind: str, text: str | None = None, path: Path | None = None) -> dict:
    """Ticks one entry's box (approve / modify with a note / deny), then records the label right away (process()).
    The entry is found by entry_id() in the file as it is now, under the lock."""
    if kind not in KINDS:
        return {"status": "invalid", "reason": "kind"}
    note = ""
    if kind == "modify":
        note = _clean_note(text)
        if not note:
            return {"status": "invalid", "reason": "empty"}
        if len(note) > NOTE_CAP:
            return {"status": "invalid", "reason": "too-long"}
    path = Path(path or QUARANTINE_FILE)
    res = _answer_locked(eid, kind, note, path)
    if res.get("status") in ("answered", "already-answered"):
        _sync()
        _settle_box_memory(path)
    return res


def _box_memory():
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
    import box_memory_review
    return box_memory_review


def _settle_box_memory(path: Path) -> None:
    """On the primary Mac, act on answered box memory cards at once (ADR 0082). Never fails the review."""
    try:
        if shared_labels.is_primary():
            bmr = _box_memory()
            bmr.settle(bmr.Ctx(quarantine=Path(path)))
    except Exception as e:
        print(f"[process-quarantine-reviews] box memory not settled: {e}", file=sys.stderr)


def _start_box_pull() -> None:
    """On the primary Mac, pull the Linux box's memory changes in the background (ADR 0082): the ssh read and the
    judge calls take time, and this runs at session start."""
    try:
        if not shared_labels.is_primary():
            return
        bmr = _box_memory()
        if not (os.environ.get("MARVIN_BOX_HOST") or bmr._registry_box()):
            return
        log = Path.home() / ".claude" / "logs" / "box-memory.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a") as out:
            subprocess.Popen([sys.executable, bmr.__file__, "pull"], stdin=subprocess.DEVNULL, stdout=out,
                             stderr=out, start_new_session=True)
    except Exception as e:
        print(f"[process-quarantine-reviews] box memory pull not started: {e}", file=sys.stderr)


def _sync() -> None:
    # Outside the quarantine lock: delivery may wait on the network (a few seconds at most when the primary is away).
    try:
        shared_labels.sync()
    except Exception as e:  # never lose the answer over a delivery problem: the outbox keeps it
        print(f"[process-quarantine-reviews] label delivery deferred: {e}", file=sys.stderr)


def _answer_locked(eid: str, kind: str, note: str, path: Path) -> dict:
    with locked(path):
        for _ in range(5):
            current = _read(path)
            if current is None:
                return {"status": "gone"}
            preamble, blocks = _split_entries(current)
            matches = [i for i, b in enumerate(blocks) if entry_id(b) == eid]
            if not matches:
                return {"status": "gone"}
            open_ = [i for i in matches if not _parse_block(blocks[i])["checked"]]
            if not open_:
                done = _parse_block(blocks[matches[0]])["checked"]
                processed, remaining = _process_unlocked(path)
                return {"status": "already-answered", "kind": done, "processed": processed, "remaining": remaining}
            i = open_[0]
            if _boxes(blocks[i]) not in (set(), set(KINDS)):
                return {"status": "invalid", "reason": "no-box"}
            blocks[i] = _tick(blocks[i], kind, note)
            new_text = preamble + "".join(blocks)
            # git (a sync pull) does not take our lock: if it rewrote the file since we read it, start again on its text.
            if _read(path) != current:
                continue
            atomic_write(path, new_text)
            processed, remaining = _process_unlocked(path)
            return {"status": "answered", "processed": processed, "remaining": remaining}
        return {"status": "busy"}


def _process_unlocked(path: Path) -> tuple[int, int]:
    text = _read(path)
    if text is None:
        return 0, 0
    preamble, entry_blocks = _split_entries(text)

    processed = 0
    remaining = 0
    out = [preamble]

    for block in entry_blocks:
        info = _parse_block(block)
        if info is None or info["checked"] is None:
            out.append(block)
            remaining += 1
            continue
        if info["loop_name"] in SETTLED_ELSEWHERE:
            # A box memory card (ADR 0082): the primary Mac acts on the tick itself and then removes the entry
            # (box_memory_review.settle). The tick travels between Macs in this file, which the box cannot write.
            out.append(block)
            continue

        # approve/modify -> the artifact was actually fine (label 0, not a
        # dangerous fabrication, at most needed a tweak); deny -> genuinely
        # bad (label 1).
        label = 1 if info["checked"] == "deny" else 0
        try:
            shared_labels.submit(info["loop_name"], info["score"], label, note=info["note"], entry_id=entry_id(block))
        except ValueError as e:  # a header the calibration can't take (e.g. a loop name it refuses): left for a person
            print(f"[process-quarantine-reviews] not recorded ({e}): {block.splitlines()[0][:80]}", file=sys.stderr)
            out.append(block)
            remaining += 1
            continue
        processed += 1
        # Only the entry's own lines go; its trailing divider stays (_tail). Everything else is kept byte for byte,
        # in order: the old rebuild put an extra "---" before every remaining entry, a whole-file rewrite.
        out.append(_tail(block))
        print(f"[process-quarantine-reviews] recorded {info['loop_name']} "
              f"score={info['score']:.2f} label={label} ({info['checked']})", file=sys.stderr)

    if processed:
        atomic_write(path, "".join(out))

    return processed, remaining


def process(path: Path | None = None) -> tuple[int, int]:
    """Returns (processed_count, remaining_count)."""
    path = Path(path or QUARANTINE_FILE)
    if not path.exists():
        _sync()
        return 0, 0
    with locked(path):
        result = _process_unlocked(path)
    _sync()
    return result


@contextmanager
def _reported_cli():
    # The run log the dashboard's Health tab shows. Found through this file's own repo, not HOME, so a test's temp
    # HOME (or an engine checkout elsewhere) still imports it; a missing one never stops the review being processed.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
    try:
        import job_events  # noqa: E402
    except ImportError:
        job_events = None
    yield job_events


def _cli_process() -> None:
    with _reported_cli() as job_events:
        if job_events is None:
            processed, remaining = process()
        else:
            @job_events.reported("process-quarantine-reviews", "Process quarantine reviews")
            def run():
                p, r = process()
                job_events.step("Reviews processed", f"{p} processed, {r} still pending")
                job_events.step("Thresholds", ", ".join(f"{k}={v:.2f}" for k, v in sorted(calibrate.read_taus().items()))
                                or "default for every loop")
                return p, r
            processed, remaining = run()
    print(f"[process-quarantine-reviews] {processed} review(s) processed, {remaining} still pending", file=sys.stderr)
    _settle_box_memory(QUARANTINE_FILE)
    _start_box_pull()


def main(argv: list[str] | None = None) -> int:
    """No arguments: process ticked entries (session start, launchd). `list` and `answer` are the dashboard's
    review cards; both print one JSON object on stdout."""
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        _cli_process()
        return 0
    ap = argparse.ArgumentParser(prog="process_quarantine_reviews.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    a = sub.add_parser("answer")
    a.add_argument("--id", required=True)
    a.add_argument("--kind", required=True)
    a.add_argument("--text", default=None)
    args = ap.parse_args(argv)
    try:
        out = list_pending() if args.cmd == "list" else answer(args.id, args.kind, args.text)
    except TimeoutError:
        out = {"status": "busy"}
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
