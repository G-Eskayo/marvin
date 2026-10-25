#!/usr/bin/env python3
"""Real trigger automation for context-sweep bootstrap, 2026-10-01.

Systematic rotation through entire context database (~/.agents + ~/.claude),
scanning each chunk for contradictions, redundancies, and QA gaps. Reuses
background_architecture_review.py's proven chunk/cursor/cooldown pattern.

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

AGENTS_DIR = Path.home() / ".agents"
CLAUDE_DIR = Path.home() / ".claude"
FINDINGS_FILE = CLAUDE_DIR / "context-sweep-findings.md"
STATE_DIR = CLAUDE_DIR / "context-sweep"
CURSOR_FILE = STATE_DIR / "chunk-cursor.json"
LOCK_FILE = STATE_DIR / ".last-run"
LOG_FILE = STATE_DIR / "background-sweep.log"
COVERAGE_LOG = STATE_DIR / "coverage-log.md"

CHUNK_SIZE = 8
COOLDOWN_SECONDS = 20 * 60 * 60
CLAUDE_CALL_TIMEOUT = 300

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache", "chroma"}
SKIP_EXT = {".pyc", ".pyo", ".so", ".dll", ".exe", ".bin", ".png", ".jpg", ".jpeg", ".gif", ".zip"}


def _enumerate_all_files() -> list[Path]:
    """Fresh enumeration of all real files under ~/.agents and ~/.claude,
    excluding binaries and generated directories. Sorted for reproducibility."""
    files = []
    for root_dir in [AGENTS_DIR, CLAUDE_DIR]:
        if not root_dir.exists():
            continue
        for path in root_dir.rglob("*"):
            if not path.is_file():
                continue
            # Skip if in any excluded directory
            if any(skip_dir in path.parts for skip_dir in SKIP_DIRS):
                continue
            # Skip if has excluded extension
            if path.suffix in SKIP_EXT:
                continue
            files.append(path)
    return sorted(files)


def _load_state() -> dict:
    if not CURSOR_FILE.exists():
        return {"index": 0, "cycle": 0, "total_files": len(_enumerate_all_files())}
    try:
        state = json.loads(CURSOR_FILE.read_text())
    except Exception:
        state = {}
    state.setdefault("index", 0)
    state.setdefault("cycle", 0)
    state.setdefault("total_files", len(_enumerate_all_files()))
    return state


def _save_state(**updates) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = _load_state()
    state.update(updates)
    CURSOR_FILE.write_text(json.dumps(state))


def _cooldown_active() -> bool:
    if not LOCK_FILE.exists():
        return False
    return (time.time() - LOCK_FILE.stat().st_mtime) < COOLDOWN_SECONDS


def pick_chunk() -> tuple[list[Path], str]:
    """Returns (chunk_files, reason). Rotates through all files in sorted order,
    CHUNK_SIZE files per run. When cursor wraps (index >= total), increment
    cycle and append to coverage log."""
    all_files = _enumerate_all_files()
    state = _load_state()

    start_index = state["index"]
    end_index = min(start_index + CHUNK_SIZE, len(all_files))
    chunk_files = all_files[start_index:end_index]

    wraps = end_index >= len(all_files)
    reason = f"files {start_index + 1}-{end_index} of {len(all_files)}"
    if wraps:
        reason += " (cycle wraps)"

    return chunk_files, reason


def _render_chunk_paths(files: list[Path]) -> str:
    """Format file paths for the prompt. The reviewer has Read/Edit/Write only,
    so every path must be a real file it can actually open."""
    return "\n".join(f"- {f}" for f in files)


# ── review execution ────────────────────────────────────────────────────────────

REVIEW_PROMPT_TEMPLATE = """You are MARVIN's background context-sweep reviewer, running unattended with Read, Write, and Edit only — no Bash, no other tools. This is deliberate: the only files you should write to are ~/.claude/context-sweep-findings.md and the files themselves (to inject pointer lines), and you physically cannot do anything else, so it's safe to run without anyone watching.

Read ~/.agents/skills/context-sweep/SKILL.md in full and follow its process exactly: the three finding categories (contradiction, redundancy, QA gap), the self-poisoning guard (which things to never flag even if superficially similar), and the entry format.

This run is scoped to a small chunk of files, not the entire database. Review ONLY these files for contradictions, redundancy, and QA gaps:

{chunk_paths}

Trigger reason: {trigger_reason}

For each real finding that passes the bar (would confuse future readers or cause maintenance problems):
1. Append a full entry to ~/.claude/context-sweep-findings.md using the exact format from architecture-review (## [title], **Category**: contradiction|redundancy|qa-gap, **Files**:, **Status**: pending, **Why**/**What**/**How**)
2. Edit the offending file(s) to inject a pointer line (one short line) referencing the finding entry

Example pointer line to add to a source file:
```
# POINTER: See ~/.claude/context-sweep-findings.md § Contradiction: X vs Y
```

If you find nothing that passes the bar in this chunk, write nothing — do not force findings to justify the run.
"""


def run_review(chunk_files: list[Path], trigger_reason: str) -> bool:
    """Run the forked reviewer. Returns True if successful, False otherwise."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        claude_bin = _resolve_claude_bin()
    except FileNotFoundError as exc:
        with LOG_FILE.open("a") as log:
            log.write(f"\n=== run {datetime.now(timezone.utc).isoformat()} ===\n")
            log.write(f"START_FAILED: {exc}\n")
        return False

    chunk_paths = _render_chunk_paths(chunk_files)
    prompt = REVIEW_PROMPT_TEMPLATE.format(chunk_paths=chunk_paths, trigger_reason=trigger_reason)
    before = FINDINGS_FILE.read_text() if FINDINGS_FILE.exists() else ""

    with LOG_FILE.open("a") as log:
        log.write(f"\n=== run {datetime.now(timezone.utc).isoformat()} — {len(chunk_files)} files — trigger: {trigger_reason} ===\n")
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
                return False  # don't advance cursor on a failed run
        except subprocess.TimeoutExpired:
            log.write(f"=== TIMED OUT after {CLAUDE_CALL_TIMEOUT}s ===\n")
            log.flush()
            return False

        after = FINDINGS_FILE.read_text() if FINDINGS_FILE.exists() else ""
        log.write("=== new finding(s) queued ===\n" if after != before else "=== no new findings from this chunk ===\n")

    return True


def main() -> None:
    if _cooldown_active():
        print("[context-sweep] skipped: ran within the last 20h", file=sys.stderr)
        return

    try:
        chunk_files, reason = pick_chunk()
    except Exception as e:
        log_hook_error("background_context_sweep", "picking chunk", e)
        return

    if not chunk_files:
        print("[context-sweep] no files to review", file=sys.stderr)
        return

    print(f"[context-sweep] reviewing chunk: {reason}", file=sys.stderr)
    try:
        success = run_review(chunk_files, reason)
    except Exception as e:
        log_hook_error("background_context_sweep", "running review", e)
        return

    if not success:
        return  # don't advance cursor on failure

    # Advance cursor
    all_files = _enumerate_all_files()
    state = _load_state()
    new_index = state["index"] + CHUNK_SIZE

    if new_index >= len(all_files):
        # Cycle complete: append to coverage log and reset index
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        log_entry = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')} | cycle {state['cycle'] + 1} complete | {len(all_files)} files\n"
        with COVERAGE_LOG.open("a") as log:
            log.write(log_entry)
        _save_state(index=0, cycle=state["cycle"] + 1)
        print(f"[context-sweep] cycle {state['cycle'] + 1} complete", file=sys.stderr)
    else:
        _save_state(index=new_index)

    LOCK_FILE.write_text(str(time.time()))


if __name__ == "__main__":
    main()
