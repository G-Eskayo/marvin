#!/usr/bin/env python3
"""Background context-sweep runner. Mirrors background_architecture_review.py
structure: fork-to-review subprocess, chunk-cursor state, cooldown-gated,
never implement without approval. Reuses the shared suggestions.md bucket.

Found: context-sweep/scripts/context_sweep.py is the core logic; this is
the subprocess wrapper and state machine.

Run standalone: ~/.agents/venv/bin/python background_context_sweep.py
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
from hook_errors import log_hook_error  # noqa: E402
from claude_bin import resolve_claude_bin as _resolve_claude_bin  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from context_sweep import enumerate_context_files, next_chunk  # noqa: E402

CLAUDE_DIR = Path.home() / ".claude"
SUGGESTIONS_FILE = CLAUDE_DIR / "suggestions.md"
SORT_SCRIPT = Path(__file__).parent.parent.parent / "architecture-review" / "scripts" / "sort_suggestions.py"
STATE_DIR = CLAUDE_DIR / "context-sweep"
CURSOR_FILE = STATE_DIR / "chunk-cursor.json"
LOCK_FILE = STATE_DIR / ".last-run"
LOG_FILE = STATE_DIR / "sweep.log"

COOLDOWN_SECONDS = 20 * 60 * 60  # 20 hours, matching architecture-review
CLAUDE_CALL_TIMEOUT = 300
CHUNK_SIZE = 5


def _load_state() -> dict:
    """Load cursor position from state file."""
    if not CURSOR_FILE.exists():
        return {"index": 0}
    try:
        state = json.loads(CURSOR_FILE.read_text())
    except Exception:
        state = {}
    state.setdefault("index", 0)
    return state


def _save_state(**updates) -> None:
    """Persist cursor to state file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = _load_state()
    state.update(updates)
    CURSOR_FILE.write_text(json.dumps(state))


def _cooldown_active() -> bool:
    """Check if we've run within the cooldown period."""
    if not LOCK_FILE.exists():
        return False
    return (time.time() - LOCK_FILE.stat().st_mtime) < COOLDOWN_SECONDS


def _render_chunk_paths(paths: list[Path]) -> str:
    """Convert Path objects to bullet list. Reuse logic from
    architecture-review (already proven correct for Read-only case)."""
    lines = []
    for path in paths:
        lines.append(f"- {path}")
    return "\n".join(lines)


REVIEW_PROMPT_TEMPLATE = """You are MARVIN's background context reviewer, running unattended with Read, Write, and Edit only — no Bash, no other tools. This is deliberate: the only file you should write to is ~/.claude/suggestions.md, and you physically cannot do anything else, so it's safe to run without anyone watching.

Read ~/.agents-pipeline-worktrees/pipeline-g-eskayo-marvin-38/skills/context-sweep/SKILL.md in full and follow its process exactly: the review checklist (contradictions, redundancy, QA gaps, clarity, currency), the suggestion bar, and the entry format including the Priority field and the **Source: context-sweep** tag for provenance.

This run is scoped to ONE chunk of all context files — chunked reviews cycle through the full system over time rather than one unbounded pass. Review ONLY:
{chunk_paths}

Never edit the files you're reviewing. Append your findings to ~/.claude/suggestions.md using the exact entry format from SKILL.md, including the **Source: context-sweep** tag. Only queue suggestions that pass the Suggestion Bar (concrete, measurable, net positive). If you find nothing that passes the bar in this chunk, write nothing — do not force suggestions to justify the run.
"""


def run_review(chunk: list[Path], chunk_num: int, total_chunks: int) -> None:
    """Execute one review pass on a chunk of context files."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        claude_bin = _resolve_claude_bin()
    except FileNotFoundError as exc:
        with LOG_FILE.open("a") as log:
            log.write(f"\n=== run {datetime.now(timezone.utc).isoformat()} ===\n")
            log.write(f"START_FAILED: {exc}\n")
        return

    chunk_paths = _render_chunk_paths(chunk)
    trigger_reason = f"chunk {chunk_num}/{total_chunks}"
    prompt = REVIEW_PROMPT_TEMPLATE.format(chunk_paths=chunk_paths)
    before = SUGGESTIONS_FILE.read_text() if SUGGESTIONS_FILE.exists() else ""

    with LOG_FILE.open("a") as log:
        log.write(f"\n=== run {datetime.now(timezone.utc).isoformat()} — {trigger_reason} ===\n")
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
            if proc.returncode != 0:
                log.flush()
                return  # don't advance cursor or sort on a failed run
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
    _save_state(index=(chunk_num % total_chunks))


def main() -> None:
    if _cooldown_active():
        print("[context-sweep] skipped: ran within the last 20h", file=sys.stderr)
        return

    try:
        all_files = enumerate_context_files()
        if not all_files:
            print("[context-sweep] no context files found to review", file=sys.stderr)
            return

        state = _load_state()
        chunk, new_index = next_chunk(all_files, state["index"], chunk_size=CHUNK_SIZE)
        total_chunks = (len(all_files) + CHUNK_SIZE - 1) // CHUNK_SIZE
        chunk_num = (state["index"] // CHUNK_SIZE) + 1

    except Exception as e:
        log_hook_error("background_context_sweep", "picking chunk", e)
        return

    print(f"[context-sweep] reviewing chunk {chunk_num}/{total_chunks}: {len(chunk)} file(s)", file=sys.stderr)
    try:
        run_review(chunk, chunk_num, total_chunks)
    except Exception as e:
        log_hook_error("background_context_sweep", "running review", e)


if __name__ == "__main__":
    main()
