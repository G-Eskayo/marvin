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

Run standalone: ~/.agents/venv/bin/python background_architecture_review.py
"""
from __future__ import annotations
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
from hook_errors import log_hook_error  # noqa: E402

AGENTS_DIR = Path.home() / ".agents"
CLAUDE_DIR = Path.home() / ".claude"
CLAUDE_MD = CLAUDE_DIR / "CLAUDE.md"
SUGGESTIONS_FILE = CLAUDE_DIR / "suggestions.md"
SORT_SCRIPT = Path(__file__).parent / "sort_suggestions.py"
STATE_DIR = CLAUDE_DIR / "architecture-review"
CURSOR_FILE = STATE_DIR / "chunk-cursor.json"
LOCK_FILE = STATE_DIR / ".last-run"
LOG_FILE = STATE_DIR / "background-review.log"

LINE_THRESHOLD = 80
ROUTING_ENTRY_THRESHOLD = 20
COOLDOWN_SECONDS = 20 * 60 * 60  # don't double-run same day even if re-triggered
CLAUDE_CALL_TIMEOUT = 300  # generous for ONE bounded chunk, not the whole system


def _resolve_claude_bin() -> str:
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (
        Path.home() / ".local" / "bin" / "claude",
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
    ):
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError("claude CLI not found on PATH or in common install locations")


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


# ── review execution ────────────────────────────────────────────────────────────

REVIEW_PROMPT_TEMPLATE = """You are MARVIN's background architecture reviewer, running unattended with Read, Write, and Edit only — no Bash, no other tools. This is deliberate: the only file you should write to is ~/.claude/suggestions.md, and you physically cannot do anything else, so it's safe to run without anyone watching.

Read ~/.agents/skills/architecture-review/SKILL.md in full and follow its process exactly: the review checklist (tokens, speed, reliability, organization, robustness, maintenance burden), the suggestion bar, and the entry format including the Priority field and its scoring guidance. Do not improvise a different framework.

This run is scoped to ONE chunk of the whole system, not everything — chunked reviews cycle through the full system over time rather than one unbounded pass. Review ONLY:
{chunk_paths}

Trigger reason for this run: {trigger_reason}

Append your findings to ~/.claude/suggestions.md using the exact entry format from SKILL.md. Only queue suggestions that pass the Suggestion Bar (concrete, measurable, net positive). If you find nothing that passes the bar in this chunk, write nothing — do not force suggestions to justify the run.
"""


def run_review(chunk: dict, trigger_reason: str, is_threshold_trigger: bool) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        claude_bin = _resolve_claude_bin()
    except FileNotFoundError as exc:
        with LOG_FILE.open("a") as log:
            log.write(f"\n=== run {datetime.now(timezone.utc).isoformat()} ===\n")
            log.write(f"START_FAILED: {exc}\n")
        return

    chunk_paths = "\n".join(f"- {p}" for p in chunk["paths"])
    prompt = REVIEW_PROMPT_TEMPLATE.format(chunk_paths=chunk_paths, trigger_reason=trigger_reason)
    before = SUGGESTIONS_FILE.read_text() if SUGGESTIONS_FILE.exists() else ""

    with LOG_FILE.open("a") as log:
        log.write(f"\n=== run {datetime.now(timezone.utc).isoformat()} — chunk: {chunk['name']} — trigger: {trigger_reason} ===\n")
        log.flush()
        try:
            proc = subprocess.run(
                [
                    claude_bin, "-p", prompt,
                    "--tools", "Read,Write,Edit",
                    "--permission-mode", "bypassPermissions",
                    "--output-format", "text",
                ],
                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                timeout=CLAUDE_CALL_TIMEOUT,
            )
            log.write(f"=== claude exit {proc.returncode} ===\n")
        except subprocess.TimeoutExpired:
            log.write(f"=== TIMED OUT after {CLAUDE_CALL_TIMEOUT}s — chunk may be too large, consider splitting it further ===\n")
            log.flush()
            return  # don't advance cursor or sort on a failed run

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


def main() -> None:
    if _cooldown_active():
        print("[architecture-review] skipped: ran within the last 20h", file=sys.stderr)
        return

    try:
        chunk, reason, is_threshold_trigger = pick_chunk()
    except Exception as e:
        log_hook_error("background_architecture_review", "picking chunk", e)
        return

    print(f"[architecture-review] reviewing chunk '{chunk['name']}': {reason}", file=sys.stderr)
    try:
        run_review(chunk, reason, is_threshold_trigger)
    except Exception as e:
        log_hook_error("background_architecture_review", "running review", e)


if __name__ == "__main__":
    main()
