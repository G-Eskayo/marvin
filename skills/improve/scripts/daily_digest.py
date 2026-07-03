#!/usr/bin/env python3
"""Daily improvement digest — assembles context from the roadmap, recent handoffs,
QA knowledge base, and bench results, then asks Claude to brainstorm improvements.

Run via launchd daily or manually:
    ~/.agents/venv/bin/python ~/.agents/skills/improve/scripts/daily_digest.py

Output: ~/.claude/daily-digest/YYYY-MM-DD.md
"""
from __future__ import annotations
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────────────────
CLAUDE_DIR   = Path.home() / ".claude"
DIGEST_DIR   = CLAUDE_DIR / "daily-digest"
ROADMAP      = CLAUDE_DIR / "marvin-roadmap.md"
HANDOFFS_DIR = CLAUDE_DIR / "handoffs"


def _resolve_claude_bin() -> str:
    """launchd's environment doesn't source .zshrc/.zprofile, so PATH may not
    include wherever `claude` was actually installed. Found 2026-07-02: every
    digest since this job started had been silently generating
    "(claude call failed: ...)" as its entire content, because call_claude()
    below caught the resulting exception and returned it as if it were real
    output — the job exited 0 (looked healthy) while producing nothing
    useful. Falls back to common install locations if a plain PATH lookup
    fails."""
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
    raise FileNotFoundError(
        "claude CLI not found on PATH or in common install locations "
        "(~/.local/bin, /opt/homebrew/bin, /usr/local/bin)"
    )
RESULTS_MD   = Path.home() / "marvin-bench" / "RESULTS.md"
QA_SCRIPTS   = Path.home() / ".agents" / "skills" / "qa-agent" / "scripts"

sys.path.insert(0, str(QA_SCRIPTS))

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
OUT_FILE = DIGEST_DIR / f"{TODAY}.md"


# ── context assembly ───────────────────────────────────────────────────────────

def roadmap_summary() -> str:
    if not ROADMAP.exists():
        return "(roadmap not found)"
    text = ROADMAP.read_text(errors="ignore")
    # extract lines with status tags — these are the actionable items
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if any(tag in stripped for tag in
               ("`[build]`", "`[done]`", "`[decision]`", "`[research]`", "## ")):
            lines.append(stripped)
    return "\n".join(lines[:80])  # cap at ~80 lines to stay under context budget


def recent_handoffs_summary() -> str:
    if not HANDOFFS_DIR.exists():
        return "(no handoffs)"
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recent = []
    for f in sorted(HANDOFFS_DIR.glob("*.md"), reverse=True)[:5]:
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                continue
            text = f.read_text(errors="ignore")
            # extract first 300 chars of "What we were working on" section
            m = re.search(r"##\s*What we were working on\s*\n(.*?)(?=\n##|\Z)",
                          text, re.DOTALL | re.IGNORECASE)
            snippet = m.group(1).strip()[:300] if m else text[:300]
            recent.append(f"[{f.stem}]\n{snippet}")
        except OSError:
            continue
    return "\n\n".join(recent) if recent else "(no handoffs in last 7 days)"


def bench_summary() -> str:
    if not RESULTS_MD.exists():
        return "(no bench results)"
    text = RESULTS_MD.read_text(errors="ignore")
    lines = text.splitlines()
    # grab the last run section (last ~40 lines)
    return "\n".join(lines[-40:])


def qa_kb_summary() -> str:
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(CLAUDE_DIR / "chroma"))
        col = client.get_or_create_collection("qa-knowledge")
        all_meta = col.get(include=["metadatas"])["metadatas"]
        total = len(all_meta)
        by_cat: dict[str, int] = {}
        by_domain: dict[str, int] = {}
        for m in all_meta:
            cat = m.get("category", "unknown")
            dom = m.get("domain", "")
            by_cat[cat] = by_cat.get(cat, 0) + 1
            if dom:
                by_domain[dom] = by_domain.get(dom, 0) + 1
        cat_str = ", ".join(f"{c}:{n}" for c, n in
                            sorted(by_cat.items(), key=lambda x: -x[1])[:6])
        dom_str = ", ".join(f"{d}:{n}" for d, n in
                            sorted(by_domain.items(), key=lambda x: -x[1])[:5])
        return f"Total entries: {total}\nBy category: {cat_str}\nBy domain: {dom_str}"
    except Exception as exc:
        return f"(KB unavailable: {exc})"


def improvement_queue_summary() -> str:
    queue = CLAUDE_DIR / "improvement-queue.md"
    if not queue.exists():
        return "(no improvement queue)"
    text = queue.read_text(errors="ignore")
    lines = text.splitlines()
    # last 20 lines (most recent entries)
    return "\n".join(lines[-20:])


REVIEWER_LOG = Path.home() / ".agents" / "skills" / "self-improve" / ".background_review.log"
FAILURE_SIGNATURES = (
    "Not logged in", "has not been trusted", "START_FAILED",
    "claude call failed", "Traceback (most recent call last)",
)


def reviewer_health_summary() -> str:
    """Computed directly from the log, not via an LLM guess at "does this
    look healthy" — these hooks are built to fail silently on purpose (so a
    broken one never interrupts an interactive session), which means
    without this, nobody would ever find out. Parses background_review.py's
    "=== run <ts> ===" / "=== end (exit N) ===" markers into individual
    runs and classifies each by real exit status, not vibes."""
    if not REVIEWER_LOG.exists():
        return "No background-reviewer log yet — either no handoff has been written, or the hook has never fired."

    text = REVIEWER_LOG.read_text(errors="ignore")
    runs = re.split(r"\n(?===[ ]run\s)", text)
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    total, failed, failure_details = 0, 0, []
    for run in runs:
        m = re.search(r"=== run (\S+) ===", run)
        if not m:
            continue
        try:
            ts = datetime.fromisoformat(m.group(1))
        except ValueError:
            continue
        if ts < cutoff:
            continue
        total += 1

        end_m = re.search(r"=== end \(exit (-?\d+)\) ===", run)
        exit_code = int(end_m.group(1)) if end_m else None
        hit_signature = next((sig for sig in FAILURE_SIGNATURES if sig in run), None)

        if exit_code is None:
            failed += 1
            failure_details.append(f"{ts.strftime('%m-%d %H:%M')}: never completed (no end marker — killed, crashed, or still running)")
        elif exit_code != 0 or hit_signature:
            failed += 1
            reason = hit_signature or f"exit code {exit_code}"
            failure_details.append(f"{ts.strftime('%m-%d %H:%M')}: {reason}")

    if total == 0:
        return "No background-reviewer runs in the last 7 days."

    summary = f"{total} run(s) in the last 7 days, {total - failed} succeeded, {failed} failed."
    if failure_details:
        summary += "\nFailures:\n" + "\n".join(f"  - {d}" for d in failure_details[:5])
    return summary


# ── claude call ────────────────────────────────────────────────────────────────

DIGEST_PROMPT_TEMPLATE = """You are MARVIN's daily improvement analyst. Your job is to review the state of the MARVIN agent system and generate a focused, actionable daily digest.

North-star goal: MINIMIZE token usage while MAXIMIZING capability and quality.

--- ROADMAP STATUS ---
{roadmap}

--- RECENT SESSION WORK (last 7 days) ---
{handoffs}

--- QA KNOWLEDGE BASE ---
{qa_kb}

--- BENCH RESULTS (latest) ---
{bench}

--- IMPROVEMENT QUEUE (recent) ---
{queue}

--- BACKGROUND REVIEWER HEALTH (last 7 days) ---
{reviewer_health}

Generate today's digest. Be specific — reference actual files, skills, metrics, and roadmap sections where relevant. Keep each item to 2–3 sentences.

## Feature Combinations
Two existing capabilities that would multiply in value if connected or merged. Explain the mechanism, not just the idea.

## Trim Candidates
One or two things currently in the system that may be carrying cost without measurable benefit. Be specific about what to cut and why.

## Wild Idea
One capability that doesn't exist yet but would significantly advance the north-star goal. Creative but grounded — explain the mechanism.

## Quick Win
One specific improvement actionable in under 2 hours with immediate impact. Name the file and the change.
"""


def call_claude(prompt: str) -> str:
    # Runs a full agentic session (CLAUDE.md discovery, tool use), not a scoped
    # completion — it genuinely reads repo files to ground the digest, which is
    # why this routinely takes 90-120s+. Found 2026-07-03: the old 120s cap was
    # tight enough that a normal run timed out; timeout raised to give headroom.
    try:
        claude_bin = _resolve_claude_bin()
        proc = subprocess.run(
            [claude_bin, "-p", prompt, "--output-format", "text"],
            capture_output=True, text=True, timeout=240,
        )
    except Exception as exc:
        return f"(claude call failed: {exc})"
    if proc.returncode != 0 or not proc.stdout.strip():
        return f"(claude call failed: {proc.stderr[:200] or 'empty output, rc=' + str(proc.returncode)})"
    return proc.stdout.strip()


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    DIGEST_DIR.mkdir(parents=True, exist_ok=True)

    if OUT_FILE.exists():
        print(f"[daily-digest] Today's digest already exists: {OUT_FILE}", flush=True)
        return

    print("[daily-digest] Assembling context...", flush=True)

    reviewer_health = reviewer_health_summary()

    prompt = DIGEST_PROMPT_TEMPLATE.format(
        roadmap=roadmap_summary(),
        handoffs=recent_handoffs_summary(),
        qa_kb=qa_kb_summary(),
        bench=bench_summary(),
        queue=improvement_queue_summary(),
        reviewer_health=reviewer_health,
    )

    print("[daily-digest] Calling claude...", flush=True)
    content = call_claude(prompt)

    header = (
        f"# MARVIN Daily Digest — {TODAY}\n\n"
        f"> Generated by `daily_digest.py` at "
        f"{datetime.now(timezone.utc).strftime('%H:%M UTC')}\n\n"
    )

    # Written directly, not through the LLM — the whole point is a number
    # you can trust without wondering if it got paraphrased. This is the
    # part of the digest that actually answers "how would I know if it
    # failed," since these hooks are built to fail silently on purpose.
    health_section = f"## System Health\n\n{reviewer_health}\n\n---\n\n"

    OUT_FILE.write_text(header + health_section + content + "\n")
    print(f"[daily-digest] Written to {OUT_FILE}", flush=True)


if __name__ == "__main__":
    main()
