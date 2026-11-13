#!/usr/bin/env python3
"""Real trigger automation for architecture-review, finally built 2026-07-09.

Found the same day: "Auto every 3-5 sessions or when CLAUDE.md >80 lines /
routing table >20 entries" (CLAUDE.md's own routing table description) was
pure prose — no session counter, no launchd job, no hook, ever existed.
suggestions.md sat at 0 lines the whole time. Exact same bug shape as
calibrate.py's dead record_label() (ADR 0015).

First real run tried to review the *whole system* in one claude -p call and
timed out at 300s with zero output — "whole system" means the agent reads
dozens of real files itself via tools, not a pre-assembled context in one
shot like daily_digest.py's narrower calls. Gil's fix, better than just
raising the timeout: chunk it. Each run reviews exactly one bounded chunk
(one skill directory, or one of a few named meta-clusters), cheap and fast
regardless of how large the system grows, cycling through everything over
time — closer to the original "every 3-5 sessions" per-area intent than one
giant sweep ever was, and immune to the growing-system problem a fixed
timeout would keep hitting.

Reuses background_review.py's fork-to-review structure (Read/Write/Edit-
only claude -p, bypassPermissions) per the same-day composability
principle. sort_suggestions.py runs in the wrapper script itself, not
granted to the LLM as a tool — keeps "never implement without approval"
intact (the LLM can propose, a deterministic post-step can format, but only
the wrapper decides what's safe to run non-interactively).

Suggestions moved into the inbox (lib/inbox.py, ADR 0083). Once the inbox's suggestions pile exists, the reviewer
reads a snapshot of it (STATE_DIR/suggestions-now.md, for duplicates) and writes its new entries, in the same entry
format, to STATE_DIR/new-suggestions.md; this script then adds them through inbox.import_text (keyed by content, so
nothing is added twice) and deletes that file. The old suggestions.md stays a read-only backup. Until the pile exists
it works as before: the reviewer appends to suggestions.md and sort_suggestions.py re-sorts it.

Run standalone: ~/.agents/venv/bin/python background_architecture_review.py
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))  # this checkout's lib: a worktree runs its own code
from hook_errors import log_hook_error  # noqa: E402
import inbox  # noqa: E402
from claude_bin import resolve_claude_bin as _resolve_claude_bin  # noqa: E402
import marvin_launcher  # noqa: E402

AGENTS_DIR = Path.home() / ".agents"
CLAUDE_DIR = Path.home() / ".claude"
CLAUDE_MD = CLAUDE_DIR / "CLAUDE.md"
SUGGESTIONS_FILE = CLAUDE_DIR / "suggestions.md"
SORT_SCRIPT = Path(__file__).parent / "sort_suggestions.py"
STATE_DIR = CLAUDE_DIR / "architecture-review"
CURSOR_FILE = STATE_DIR / "chunk-cursor.json"
LOCK_FILE = STATE_DIR / ".last-run"
LOG_FILE = STATE_DIR / "background-review.log"
SNAPSHOT_FILE = STATE_DIR / "suggestions-now.md"     # the inbox's suggestions, for the reviewer to read (inbox mode)
STAGING_FILE = STATE_DIR / "new-suggestions.md"      # the reviewer's new entries, imported after the run (inbox mode)

LINE_THRESHOLD = 80
ROUTING_ENTRY_THRESHOLD = 20
COOLDOWN_SECONDS = 20 * 60 * 60  # don't double-run same day even if re-triggered
CLAUDE_CALL_TIMEOUT = 300  # generous for ONE bounded chunk, not the whole system


# ── chunk enumeration ─────────────────────────────────────────────────────────

def _enumerate_chunks() -> list[dict]:
    """Recomputed fresh every run, not cached — skills get added/removed
    over time and the rotation should reflect what actually exists now."""
    chunks = [
        {"name": "meta-config", "paths": ["~/.claude/CLAUDE.md", "~/.claude/lexicon.md", "~/.claude/commands/"]},
        {"name": "lib-utilities", "paths": ["~/.agents/lib/"]},
        {"name": "handoffs", "paths": ["~/.claude/handoffs/"]},
    ]
    for skill_dir in sorted((AGENTS_DIR / "skills").iterdir()):
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
            chunks.append({"name": f"skill:{skill_dir.name}", "paths": [f"~/.agents/skills/{skill_dir.name}/"]})
    return chunks


def _load_state() -> dict:
    if not CURSOR_FILE.exists():
        return {"index": 0, "last_meta_lines": 0, "last_meta_entries": 0}
    try:
        state = json.loads(CURSOR_FILE.read_text())
    except Exception:
        state = {}
    state.setdefault("index", 0)
    state.setdefault("last_meta_lines", 0)
    state.setdefault("last_meta_entries", 0)
    return state


def _save_state(**updates) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = _load_state()
    state.update(updates)
    CURSOR_FILE.write_text(json.dumps(state))


# ── trigger logic ──────────────────────────────────────────────────────────────

def _routing_table_entry_count() -> int:
    if not CLAUDE_MD.exists():
        return 0
    return sum(1 for line in CLAUDE_MD.read_text().splitlines() if line.startswith("| `"))


def _claude_md_line_count() -> int:
    if not CLAUDE_MD.exists():
        return 0
    return len(CLAUDE_MD.read_text().splitlines())


def _cooldown_active() -> bool:
    if not LOCK_FILE.exists():
        return False
    return (time.time() - LOCK_FILE.stat().st_mtime) < COOLDOWN_SECONDS


def pick_chunk() -> tuple[dict, str, bool]:
    """Returns (chunk, reason, is_threshold_trigger). Size thresholds are
    edge-triggered, not level-triggered: MARVIN has permanently outgrown
    ROUTING_ENTRY_THRESHOLD (30 skills vs. a threshold of 20 set when the
    system was much smaller), so "is it still above the line" would pick
    meta-config on literally every run forever and starve the other ~30
    chunks of ever being reviewed. Instead: only jump the queue if the
    metric has gotten *worse* since the last time meta-config was reviewed
    for this reason."""
    chunks = _enumerate_chunks()
    state = _load_state()

    lines = _claude_md_line_count()
    entries = _routing_table_entry_count()
    if lines > LINE_THRESHOLD and lines > state["last_meta_lines"]:
        return chunks[0], f"CLAUDE.md grew to {lines} lines (was {state['last_meta_lines']} at last review, threshold {LINE_THRESHOLD})", True
    if entries > ROUTING_ENTRY_THRESHOLD and entries > state["last_meta_entries"]:
        return chunks[0], f"routing table grew to {entries} entries (was {state['last_meta_entries']} at last review, threshold {ROUTING_ENTRY_THRESHOLD})", True

    cursor = state["index"] % len(chunks)
    return chunks[cursor], f"scheduled rotation (chunk {cursor + 1}/{len(chunks)})", False


def _render_chunk_paths(paths: list[str]) -> str:
    """The reviewer runs with Read/Write/Edit only -- no Glob/LS -- so a bare
    directory string is unreadable to it (Read raises EISDIR). Expand any
    directory path into its real file listing so the reviewer always gets
    paths it can actually open. Falls back to the bare directory bullet when
    there's nothing to enumerate (missing or empty), so the prompt never
    ends up pointing at literally nothing."""
    lines = []
    for raw in paths:
        expanded = Path(raw).expanduser()
        if expanded.is_dir():
            files = sorted(str(f) for f in expanded.rglob("*") if f.is_file())
            if files:
                lines.extend(f"- {f}" for f in files)
                continue
        lines.append(f"- {raw}")
    return "\n".join(lines)


# ── review execution ────────────────────────────────────────────────────────────

REVIEW_PROMPT_TEMPLATE = """You are MARVIN's background architecture reviewer, running unattended with Read, Write, and Edit only — no Bash, no other tools. This is deliberate: the only file you should write to is the one named below, and you physically cannot do anything else, so it's safe to run without anyone watching.

Read ~/.agents/skills/architecture-review/SKILL.md in full and follow its process exactly: the review checklist (tokens, speed, reliability, organization, robustness, maintenance burden), the suggestion bar, and the entry format including the Priority field and its scoring guidance. Do not improvise a different framework.

This run is scoped to ONE chunk of the whole system, not everything — chunked reviews cycle through the full system over time rather than one unbounded pass. Review ONLY:
{chunk_paths}

Trigger reason for this run: {trigger_reason}

{destination} Only queue suggestions that pass the Suggestion Bar (concrete, measurable, net positive). If you find nothing that passes the bar in this chunk, write nothing — do not force suggestions to justify the run.
"""

MD_DESTINATION = "Append your findings to ~/.claude/suggestions.md using the exact entry format from SKILL.md."
INBOX_DESTINATION = """The suggestions backlog now lives in MARVIN's inbox, not in ~/.claude/suggestions.md (that file is a read-only backup: never edit it). Every existing suggestion, in priority order, is in {snapshot}: read it to avoid duplicates. Write your new findings, using the exact entry format from SKILL.md (one `## Title` block each), to {staging} — the only file you write. It is added to the inbox after you finish."""


def _inbox_mode() -> bool:
    return inbox.pile_exists("suggestions")


def _write_snapshot() -> None:
    """Every suggestion in the inbox, rendered in the entry format, in ADR 0017's order."""
    listed = inbox.list_items("suggestions")
    text = "# Suggestions (snapshot of the inbox; read-only)\n\n" + "\n".join(
        inbox.render_suggestion(i) for i in listed["items"])
    SNAPSHOT_FILE.write_text(text)


def _import_staged(before_md: str) -> str:
    """Add the reviewer's new entries to the inbox; a summary for the log. Also picks up anything it appended to the
    old file by habit (keyed by content, so only new entries are added)."""
    notes = []
    if STAGING_FILE.exists() or STAGING_FILE.is_symlink():
        try:
            text = inbox.read_legacy(STAGING_FILE)  # refuses a symlink or an oversized file
            out = inbox.import_text("suggestions", text, source="architecture-review")
            notes.append(f"{out['added']} new suggestion(s) added to the inbox ({out['already_there']} already there)")
        except inbox.InboxError as exc:
            notes.append(f"staged suggestions not imported: {exc}")
        STAGING_FILE.unlink()
    after_md = SUGGESTIONS_FILE.read_text(errors="replace") if SUGGESTIONS_FILE.exists() else ""
    if after_md != before_md:
        out = inbox.import_text("suggestions", after_md, source="architecture-review")
        notes.append(f"the reviewer wrote to the old suggestions.md; {out['added']} entry(ies) from it added")
    return "; ".join(notes) or "no new suggestions from this chunk"


class ReviewFailed(RuntimeError):
    """The run reviewed nothing (claude missing, failed, or timed out). main() turns it into a non-zero exit and a
    hook error: until 2026-11-04 these runs exited 0, so an expired login on the Mini showed green for four days
    (marvin#1123 0.5)."""


def _first_line(*texts: str) -> str:
    for t in texts:
        for line in (t or "").splitlines():
            if line.strip():
                return line.strip()[:300]
    return "no output"


def run_review(chunk: dict, trigger_reason: str, is_threshold_trigger: bool) -> None:
    """Review one chunk. Raises ReviewFailed when nothing was reviewed; the cursor and cooldown are then untouched,
    so the same chunk is tried again next run."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _resolve_claude_bin()  # fail early and log it when claude is missing
    except FileNotFoundError as exc:
        with LOG_FILE.open("a") as log:
            log.write(f"\n=== run {datetime.now(timezone.utc).isoformat()} ===\n")
            log.write(f"START_FAILED: {exc}\n")
        raise ReviewFailed(f"claude not found: {exc}") from exc

    chunk_paths = _render_chunk_paths(chunk["paths"])
    use_inbox = _inbox_mode()
    if use_inbox:
        STAGING_FILE.unlink(missing_ok=True)
        _write_snapshot()
        destination = INBOX_DESTINATION.format(snapshot=SNAPSHOT_FILE, staging=STAGING_FILE)
    else:
        destination = MD_DESTINATION
    prompt = REVIEW_PROMPT_TEMPLATE.format(chunk_paths=chunk_paths, trigger_reason=trigger_reason, destination=destination)
    before = SUGGESTIONS_FILE.read_text() if SUGGESTIONS_FILE.exists() else ""

    with LOG_FILE.open("a") as log:
        log.write(f"\n=== run {datetime.now(timezone.utc).isoformat()} — chunk: {chunk['name']} — trigger: {trigger_reason} ===\n")
        log.flush()
        failed = None
        try:
            result = marvin_launcher.launch("background-analyst", prompt, tools="Read,Write,Edit",
                                            permission_mode="bypassPermissions", timeout=CLAUDE_CALL_TIMEOUT)
            log.write(result.text + (f"\n{result.stderr}" if result.stderr else "") + "\n")
            log.write(f"=== claude exit {result.exit_code} ===\n")
            if result.exit_code != 0:
                failed = ReviewFailed(f"claude exit {result.exit_code}: {_first_line(result.text, result.stderr)}")
        except subprocess.TimeoutExpired as exc:
            log.write(f"=== TIMED OUT after {CLAUDE_CALL_TIMEOUT}s — chunk may be too large, consider splitting it further ===\n")
            failed = ReviewFailed(f"claude timed out after {CLAUDE_CALL_TIMEOUT}s")
            failed.__cause__ = exc
        if use_inbox:
            # Whatever it wrote is kept, as it was when it appended to suggestions.md directly, even on a failed run.
            log.write(f"=== inbox: {_import_staged(before)} ===\n")
        if failed is not None:
            log.flush()  # don't advance cursor or sort on a failed run
            raise failed

        if not use_inbox:
            sort_proc = subprocess.run(
                [sys.executable, str(SORT_SCRIPT)], capture_output=True, text=True, timeout=30,
            )
            log.write(f"=== sort_suggestions: {sort_proc.stderr.strip()} ===\n")
            after = SUGGESTIONS_FILE.read_text() if SUGGESTIONS_FILE.exists() else ""
            log.write("=== new suggestion(s) queued ===\n" if after != before else "=== no new suggestions from this chunk ===\n")

    LOCK_FILE.write_text(str(time.time()))
    if is_threshold_trigger:
        # Record the metric values as of this review so pick_chunk()'s
        # edge-trigger only fires again once things get worse than this,
        # not merely "still above the original threshold" — that would
        # loop on meta-config forever now that the system has permanently
        # outgrown the original threshold values.
        _save_state(last_meta_lines=_claude_md_line_count(), last_meta_entries=_routing_table_entry_count())
    else:
        chunks = _enumerate_chunks()
        current_index = next((i for i, c in enumerate(chunks) if c["name"] == chunk["name"]), _load_state()["index"])
        _save_state(index=(current_index + 1) % len(chunks))


import job_events  # noqa: E402  (run log shown in the dashboard's Health tab)


@job_events.reported("architecture-review", "Architecture review")
def main() -> None:
    if _cooldown_active():
        print("[architecture-review] skipped: ran within the last 20h", file=sys.stderr)
        return

    try:
        chunk, reason, is_threshold_trigger = pick_chunk()
    except Exception as e:
        _fail("picking chunk", e)

    print(f"[architecture-review] reviewing chunk '{chunk['name']}': {reason}", file=sys.stderr)
    try:
        run_review(chunk, reason, is_threshold_trigger)
    except Exception as e:
        _fail("running review", e)


def _fail(context: str, exc: BaseException) -> None:
    """Record why in the hook-error log and this run's job record, then exit 1 so launchd and Health see it."""
    log_hook_error("background_architecture_review", context, exc)
    if job_events._CURRENT:
        job_events._CURRENT[-1].fail(f"{context}: {exc}")
    print(f"[architecture-review] FAILED {context}: {exc}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
