#!/usr/bin/env python3
"""Real trigger automation for context-sweep, checking for contradictions,
redundancy, and QA gaps in MARVIN's own knowledge store.

Extends the fork-to-review pattern established by background_architecture_review.py,
with a different review lens: content-vs-content integrity rather than design quality.

Chunks exhaustively through ~/.agents and ~/.claude (not hand-picked), batching
files into fixed-size chunks, rotating through all files over time. Each run is
cheap and fast regardless of how large the system grows.

Reuses background_review.py's structure (Read/Write/Edit-only claude -p) and
sort_suggestions.py's generalized sorting logic for the new findings bucket.

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
import marvin_launcher  # noqa: E402

AGENTS_DIR = Path.home() / ".agents"
CLAUDE_DIR = Path.home() / ".claude"
BUCKET_FILE = CLAUDE_DIR / "context-sweep-findings.md"
SORT_SCRIPT = Path(__file__).parent / "sort_context_sweep_findings.py"
STATE_DIR = CLAUDE_DIR / "context-sweep"
CURSOR_FILE = STATE_DIR / "chunk-cursor.json"
LOCK_FILE = STATE_DIR / ".last-run"
LOG_FILE = STATE_DIR / "background-sweep.log"

CHUNK_SIZE = 10  # files per chunk
COOLDOWN_SECONDS = 7 * 24 * 60 * 60  # Weekly rotation for full coverage
CLAUDE_CALL_TIMEOUT = 300

CANONICAL_INDEX_FILES = [
    "~/.claude/CLAUDE.md",
    "~/.claude/lexicon.md",
    "~/.claude/marvin-roadmap.md",
    "~/.claude/MEMORY.md",
]

DEFAULT_BUCKET_HEADER = """# Context Sweep Findings

Content integrity checks: contradictions, redundancy, QA gaps in MARVIN's own knowledge store.

**Impact types**:
- **contradiction**: A fact stated one way in one file conflicts with another file
- **redundancy**: The same pattern/concept/rule is documented in multiple places (maintenance burden)
- **qa-gap**: A documented process or capability has no verification; or doc vs. actual code mismatch

Highest priority first — kept sorted by `sort_context_sweep_findings.py`.
Distinct from `suggestions.md` (architecture quality) and `audit` (intent-vs-reality).
Check every session; never implement without explicit approval.

"""


# ── chunk enumeration ─────────────────────────────────────────────────────────

def _enumerate_chunks() -> list[dict]:
    """Exhaustive enumeration of all files under ~/.agents and ~/.claude.
    Recomputed fresh every run — files get added/removed over time."""
    all_files = []

    for root_dir in [AGENTS_DIR, CLAUDE_DIR]:
        if not root_dir.exists():
            continue
        try:
            for file_path in root_dir.rglob("*"):
                if file_path.is_file() and _should_include_file(file_path):
                    all_files.append(file_path)
        except (OSError, PermissionError):
            continue

    all_files.sort()

    # Batch into fixed-size chunks
    chunks = []
    for i in range(0, len(all_files), CHUNK_SIZE):
        batch = all_files[i:i + CHUNK_SIZE]
        chunks.append({
            "name": f"chunk-{i // CHUNK_SIZE + 1}",
            "paths": [str(f) for f in batch],
            "batch_index": i // CHUNK_SIZE,
        })

    return chunks


def _should_include_file(path: Path) -> bool:
    """Filter out build artifacts, caches, venvs, and binary files."""
    exclude_patterns = {
        ".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv",
        ".egg-info", "*.pyc", "*.pyo", ".DS_Store", ".idea", ".vscode",
        "*.png", "*.jpg", "*.jpeg", "*.gif", "*.bin", "*.so", "*.o", "*.a",
    }

    # Check path components
    for part in path.parts:
        if part in exclude_patterns or part.startswith("."):
            return False
        if any(part.endswith(pattern.lstrip("*")) for pattern in exclude_patterns if "*" in pattern):
            return False

    # Check file size (skip huge files)
    try:
        if path.stat().st_size > 1024 * 1024:  # > 1MB
            return False
    except (OSError, PermissionError):
        return False

    return True


def _load_state() -> dict:
    if not CURSOR_FILE.exists():
        return {"index": 0}
    try:
        state = json.loads(CURSOR_FILE.read_text())
    except Exception:
        state = {}
    state.setdefault("index", 0)
    return state


def _save_state(**updates) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = _load_state()
    state.update(updates)
    CURSOR_FILE.write_text(json.dumps(state))


# ── trigger logic ──────────────────────────────────────────────────────────────

def _cooldown_active() -> bool:
    if not LOCK_FILE.exists():
        return False
    return (time.time() - LOCK_FILE.stat().st_mtime) < COOLDOWN_SECONDS


def pick_chunk() -> tuple[dict, str]:
    """Returns (chunk, reason). Rotates through all chunks in order."""
    chunks = _enumerate_chunks()
    if not chunks:
        return None, "no files to sweep"

    state = _load_state()
    cursor = state["index"] % len(chunks)
    return chunks[cursor], f"scheduled rotation (chunk {cursor + 1}/{len(chunks)})"


def _render_chunk_paths(paths: list[str]) -> str:
    """Expand directory paths into their file listings for the reviewer."""
    lines = []
    for raw in paths:
        expanded = Path(raw).expanduser()
        if expanded.is_dir():
            try:
                files = sorted(str(f) for f in expanded.rglob("*") if f.is_file() and _should_include_file(f))
                if files:
                    lines.extend(f"- {f}" for f in files)
                    continue
            except (OSError, PermissionError):
                pass
        lines.append(f"- {raw}")
    return "\n".join(lines)


def _ensure_bucket_exists() -> None:
    """Create bucket file with default header if missing."""
    if BUCKET_FILE.exists():
        return

    BUCKET_FILE.parent.mkdir(parents=True, exist_ok=True)
    BUCKET_FILE.write_text(DEFAULT_BUCKET_HEADER)


def _read_canonical_index() -> str:
    """Read canonical reference files for comparison context."""
    parts = []
    for ref_path in CANONICAL_INDEX_FILES:
        expanded = Path(ref_path).expanduser()
        if expanded.exists():
            try:
                content = expanded.read_text(errors="replace")[:2000]  # Truncate long files
                parts.append(f"\n--- {ref_path} ---\n{content}")
            except (OSError, PermissionError):
                parts.append(f"\n--- {ref_path} --- (read error)")
    return "\n".join(parts)


# ── review execution ────────────────────────────────────────────────────────────

REVIEW_PROMPT_TEMPLATE = """You are MARVIN's background context-sweep reviewer, checking for contradictions, redundancy, and QA gaps in MARVIN's own knowledge store. Run unattended with Read, Write, and Edit only — no Bash, no other tools. You physical cannot do anything else, so it is safe to run without anyone watching.

Read ~/.agents/skills/context-sweep/SKILL.md in full and follow its process exactly.

**Canonical reference index** (fixed comparison context for every chunk):
{canonical_index}

This run is scoped to ONE chunk of all files under ~/.agents and ~/.claude, not everything — chunked reviews cycle through the full system over time rather than one unbounded pass. Review ONLY these files:
{chunk_paths}

Within this chunk, check for:
1. **Contradictions**: A fact stated one way conflicts with how it's stated elsewhere
2. **Redundancy**: The same pattern/rule is documented in multiple places (check against canonical index especially)
3. **QA gaps**: A documented process has no verification; or doc claims something the code doesn't do

If you find findings that pass the bar (see SKILL.md), append them to ~/.claude/context-sweep-findings.md using the exact entry format. Status should be 'pending' for new findings. Only queue findings that:
- Are concrete and measurable (not vague)
- Represent net-positive fixes (not just stylistic preferences)
- Won't break something in the fixing

If you find nothing that passes the bar in this chunk, write nothing — do not force findings to justify the run.
"""


def run_review(chunk: dict, trigger_reason: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _resolve_claude_bin()
    except FileNotFoundError as exc:
        with LOG_FILE.open("a") as log:
            log.write(f"\n=== run {datetime.now(timezone.utc).isoformat()} ===\n")
            log.write(f"START_FAILED: {exc}\n")
        return

    _ensure_bucket_exists()

    chunk_paths = _render_chunk_paths(chunk["paths"])
    canonical_index = _read_canonical_index()
    prompt = REVIEW_PROMPT_TEMPLATE.format(
        chunk_paths=chunk_paths,
        canonical_index=canonical_index,
    )
    before = BUCKET_FILE.read_text() if BUCKET_FILE.exists() else ""

    with LOG_FILE.open("a") as log:
        log.write(f"\n=== run {datetime.now(timezone.utc).isoformat()} — chunk: {chunk['name']} — trigger: {trigger_reason} ===\n")
        log.flush()
        try:
            result = marvin_launcher.launch("context-sweep", prompt, tools="Read,Write,Edit",
                                            permission_mode="bypassPermissions", timeout=CLAUDE_CALL_TIMEOUT)
            log.write(result.text + (f"\n{result.stderr}" if result.stderr else "") + "\n")
            log.write(f"=== claude exit {result.exit_code} ===\n")
            if result.exit_code != 0:
                log.flush()
                return
        except subprocess.TimeoutExpired:
            log.write(f"=== TIMED OUT after {CLAUDE_CALL_TIMEOUT}s — chunk may be too large ===\n")
            log.flush()
            return

        # Sort the findings bucket
        try:
            sort_proc = subprocess.run(
                [sys.executable, str(SORT_SCRIPT), "--file", str(BUCKET_FILE)],
                capture_output=True, text=True, timeout=30,
            )
            log.write(f"=== sort_context_sweep_findings: {sort_proc.stderr.strip()} ===\n")
        except Exception as e:
            log.write(f"=== sort_context_sweep_findings failed: {e} ===\n")

        after = BUCKET_FILE.read_text() if BUCKET_FILE.exists() else ""
        log.write("=== new findings(s) queued ===\n" if after != before else "=== no new findings from this chunk ===\n")

    LOCK_FILE.write_text(str(time.time()))
    chunks = _enumerate_chunks()
    if chunks:
        current_index = next((i for i, c in enumerate(chunks) if c["name"] == chunk["name"]), _load_state()["index"])
        _save_state(index=(current_index + 1) % len(chunks))


sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
import job_events  # noqa: E402


@job_events.reported("context-sweep", "Context sweep")
def main() -> None:
    if _cooldown_active():
        print("[context-sweep] skipped: ran within the cooldown window", file=sys.stderr)
        return

    try:
        chunk, reason = pick_chunk()
        if not chunk:
            print("[context-sweep] skipped: no files to sweep", file=sys.stderr)
            return
    except Exception as e:
        log_hook_error("background_context_sweep", "picking chunk", e)
        return

    print(f"[context-sweep] reviewing chunk '{chunk['name']}': {reason}", file=sys.stderr)
    try:
        run_review(chunk, reason)
    except Exception as e:
        log_hook_error("background_context_sweep", "running review", e)


def _find_duplicate_entry(title: str) -> str | None:
    """Check if a finding with this title already exists in the bucket."""
    if not BUCKET_FILE.exists():
        return None

    content = BUCKET_FILE.read_text()
    for line in content.splitlines():
        if line.startswith("## ") and title in line:
            return line
    return None


if __name__ == "__main__":
    main()
