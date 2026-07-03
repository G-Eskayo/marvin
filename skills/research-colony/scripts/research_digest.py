#!/usr/bin/env python3
"""Synthesise today's correlated research finds into ~/.claude/research-digest/YYYY-MM-DD.md."""
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

DIGEST_DIR = Path.home() / ".claude" / "research-digest"
CACHE_DIR = Path.home() / ".claude" / "research-feed"
CHROMA_PATH = Path.home() / ".claude" / "chroma"
SAFETY_MONITOR_SCRIPTS = Path.home() / ".agents" / "skills" / "safety-monitor" / "scripts"

sys.path.insert(0, str(SAFETY_MONITOR_SCRIPTS))
try:
    from verify import pass_or_quarantine
    _SAFETY_MONITOR_AVAILABLE = True
except ImportError:
    _SAFETY_MONITOR_AVAILABLE = False


def _resolve_claude_bin() -> str:
    """launchd's environment doesn't source .zshrc/.zprofile, so PATH may not
    include wherever `claude` was actually installed (found 2026-07-02: this
    silently broke both this job and daily_digest.py's identical pattern —
    daily_digest.py masked it by catching the exception and writing the
    error string as if it were digest content). Falls back to common install
    locations if a plain PATH lookup fails, so a misconfiguration surfaces
    once clearly instead of producing silently-broken output indefinitely."""
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

DIGEST_PROMPT = """You are MARVIN's research analyst. Review today's research items and generate a digest.

MARVIN context: AI agent system with ChromaDB memory, skill routing, QA knowledge base, marvin-bench (A/B testing), profile routing (lean/full/base), daily improvement sweep, and a research colony.

NORTH-STAR: Minimize token cost, maximize capability and quality.

CORRELATED ITEMS (semantically or keyword-matched to current work):
{correlated}

ALL TODAY'S ITEMS (raw fetch from arXiv, GitHub, HN):
{all_items}

Write a research digest with exactly these four sections. Be concise — max 3 items per section, link every item. No preamble.

## Directly Relevant
Items that match current MARVIN roadmap or projects. Format: **Title** — why it matters + roadmap section. [link]

## Lateral Finds
Interesting items not directly matched but mechanism or insight may transfer. Format: **Title** — what might transfer. [link]

## Tools & Repos
Specific repos or tools worth evaluating soon. Format: **repo** — one-line pitch. [link]

## Skip
Items fetched but clearly noise — list titles only (no links needed).
"""


def load_today_cache() -> list[dict]:
    today = date.today().isoformat()
    path = CACHE_DIR / f"{today}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def load_correlated_from_chroma() -> list[dict]:
    try:
        import chromadb
    except ImportError:
        return []

    today = date.today().isoformat()
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    try:
        col = client.get_collection("research-feed")
        raw = col.get(
            where={"correlated": "true"},
            include=["documents", "metadatas"],
        )
    except Exception:
        return []

    items = []
    for doc, meta in zip(raw.get("documents") or [], raw.get("metadatas") or []):
        if (meta.get("date") or "") == today:
            items.append({
                "title": meta.get("title", ""),
                "url": meta.get("url", ""),
                "source": meta.get("source", ""),
                "matched": meta.get("matched_topics", ""),
                "document": doc,
            })
    return items


def _fmt_item(item: dict) -> str:
    return f"  [{item.get('source', '?')}] {item.get('title', '')[:80]} <{item.get('url', '')}>"


def generate() -> Path | None:
    today = date.today().isoformat()
    out_path = DIGEST_DIR / f"{today}.md"

    if out_path.exists():
        print(f"[colony] research digest already exists for {today}", file=sys.stderr)
        return out_path

    all_items = load_today_cache()
    if not all_items:
        print("[colony] no items in today's cache — run source_monitor first", file=sys.stderr)
        return None

    correlated = load_correlated_from_chroma()

    correlated_text = "\n".join(_fmt_item(i) for i in correlated) if correlated else "  (none matched today)"
    all_text = "\n".join(_fmt_item(i) for i in all_items[:30])

    prompt = DIGEST_PROMPT.format(correlated=correlated_text, all_items=all_text)

    try:
        claude_bin = _resolve_claude_bin()
        proc = subprocess.run(
            [claude_bin, "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as exc:
        print(f"[colony] claude call failed: {exc}", file=sys.stderr)
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        print(f"[colony] claude call failed: {proc.stderr[:200]}", file=sys.stderr)
        return None

    body = proc.stdout.strip()

    # Score the synthesised digest before it ships — the actual failure mode
    # this guards is a relevance claim that doesn't survive reading the
    # summary carefully (e.g. a training technique claimed to transfer to a
    # system that only orchestrates a hosted model over an API).
    if _SAFETY_MONITOR_AVAILABLE and not pass_or_quarantine(body, loop_name="research_colony"):
        print(f"[colony] digest quarantined by safety-monitor — see ~/.claude/quarantine.md",
              file=sys.stderr)
        body = (
            "_Quarantined by safety-monitor before shipping — flagged as risky "
            "against the research_colony rubric. See `~/.claude/quarantine.md` "
            "for the full text and to approve/modify/deny._"
        )

    DIGEST_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        f"# Research Digest — {today}\n\n"
        f"*{len(all_items)} items fetched · {len(correlated)} correlated*\n\n"
        + body
        + "\n"
    )
    print(f"[colony] research digest written → {out_path}", file=sys.stderr)
    return out_path


if __name__ == "__main__":
    result = generate()
    if result:
        print(result.read_text())
