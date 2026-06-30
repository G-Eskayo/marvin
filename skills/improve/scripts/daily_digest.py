#!/usr/bin/env python3
"""Daily improvement digest — assembles context from the roadmap, recent handoffs,
QA knowledge base, and bench results, then asks Claude to brainstorm improvements.

Run via launchd daily or manually:
    ~/.agents/venv/bin/python ~/.agents/skills/improve/scripts/daily_digest.py

Output: ~/.claude/daily-digest/YYYY-MM-DD.md
"""
from __future__ import annotations
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────────────────
CLAUDE_DIR   = Path.home() / ".claude"
DIGEST_DIR   = CLAUDE_DIR / "daily-digest"
ROADMAP      = CLAUDE_DIR / "marvin-roadmap.md"
HANDOFFS_DIR = CLAUDE_DIR / "handoffs"
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
            import re
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
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True, text=True, timeout=120,
        )
        return proc.stdout.strip()
    except Exception as exc:
        return f"(claude call failed: {exc})"


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    DIGEST_DIR.mkdir(parents=True, exist_ok=True)

    if OUT_FILE.exists():
        print(f"[daily-digest] Today's digest already exists: {OUT_FILE}", flush=True)
        return

    print("[daily-digest] Assembling context...", flush=True)

    prompt = DIGEST_PROMPT_TEMPLATE.format(
        roadmap=roadmap_summary(),
        handoffs=recent_handoffs_summary(),
        qa_kb=qa_kb_summary(),
        bench=bench_summary(),
        queue=improvement_queue_summary(),
    )

    print("[daily-digest] Calling claude...", flush=True)
    content = call_claude(prompt)

    header = (
        f"# MARVIN Daily Digest — {TODAY}\n\n"
        f"> Generated by `daily_digest.py` at "
        f"{datetime.now(timezone.utc).strftime('%H:%M UTC')}\n\n"
    )

    OUT_FILE.write_text(header + content + "\n")
    print(f"[daily-digest] Written to {OUT_FILE}", flush=True)


if __name__ == "__main__":
    main()
