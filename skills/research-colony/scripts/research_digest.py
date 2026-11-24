#!/usr/bin/env python3
"""Synthesise today's correlated research finds into ~/.claude/research-digest/YYYY-MM-DD.md."""
import json
import os
import subprocess
import sys
import urllib.request
from datetime import date
from pathlib import Path

DIGEST_DIR = Path.home() / ".claude" / "research-digest"
CACHE_DIR = Path.home() / ".claude" / "research-feed"
CHROMA_PATH = Path.home() / ".claude" / "chroma"
SAFETY_MONITOR_SCRIPTS = Path.home() / ".agents" / "skills" / "safety-monitor" / "scripts"

# Synthesis backend (ticket #1414). Default "claude" keeps the hosted path; set
# COLONY_SYNTH_BACKEND=ollama to synthesise the digest on-device so it survives
# usage limits and session interruptions. The safety-monitor quarantine gate
# below guards whichever backend produces the text.
OLLAMA_BASE = "http://localhost:11434"  # same endpoint as bench/lib/memory_rag.py
OLLAMA_MODEL = os.environ.get("COLONY_OLLAMA_MODEL", "qwen2.5:3b")
# Local generation is slower than a hosted call; give it room. Claude path keeps its own 120s.
OLLAMA_TIMEOUT = int(os.environ.get("COLONY_OLLAMA_TIMEOUT", "300"))

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
from notify import notify  # noqa: E402
import marvin_launcher  # noqa: E402
import brief_fallback  # noqa: E402

sys.path.insert(0, str(SAFETY_MONITOR_SCRIPTS))
try:
    from verify import pass_or_quarantine
    _SAFETY_MONITOR_AVAILABLE = True
except ImportError:
    _SAFETY_MONITOR_AVAILABLE = False

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


def _select_backend() -> str:
    """Which synthesis backend to use: "ollama" only when explicitly asked, else "claude".

    An unknown value (typo) falls back to "claude" so a misconfigured env never routes
    the digest nowhere — it keeps the working hosted path."""
    val = os.environ.get("COLONY_SYNTH_BACKEND", "claude").strip().lower()
    return "ollama" if val == "ollama" else "claude"


def _ollama_post(url: str, payload: dict, timeout: float) -> dict:
    """Default poster: POST JSON to Ollama, return the parsed JSON body. Stdlib only."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (localhost only)
        return json.loads(resp.read().decode("utf-8"))


def _synthesize_ollama(prompt: str, *, model: str, poster=_ollama_post,
                       base: str = OLLAMA_BASE, timeout: float = OLLAMA_TIMEOUT):
    """Synthesise the digest with a local Ollama model, returning a LaunchResult-shaped
    object so the caller's error handling is identical to the Claude path.

    Never raises: a dead or wrong Ollama becomes a non-zero exit with a message in
    stderr, which the caller surfaces via notify() exactly like a failed hosted call."""
    url = f"{base}/api/generate"
    try:
        body = poster(url, {"model": model, "prompt": prompt, "stream": False}, timeout)
    except Exception as exc:  # noqa: BLE001 — any transport/decoding failure is a graceful miss
        return marvin_launcher.LaunchResult(text="", cost_usd=0.0, exit_code=1,
                                            stderr=f"ollama error: {exc}")
    text = body.get("response") or ""
    if not text.strip():
        err = body.get("error") or "empty response from ollama"
        return marvin_launcher.LaunchResult(text="", cost_usd=0.0, exit_code=1, stderr=str(err))
    return marvin_launcher.LaunchResult(text=text, cost_usd=0.0, exit_code=0, stderr="")


def _run_synthesis(prompt: str):
    """Dispatch the digest synthesis to the selected backend, returning a LaunchResult.

    The Claude path may raise (preflight, subprocess) — the caller already catches that.
    The Ollama path never raises; it reports failure through the LaunchResult."""
    if _select_backend() == "ollama":
        print(f"[colony] synthesising digest locally via ollama ({OLLAMA_MODEL})", file=sys.stderr)
        return _synthesize_ollama(prompt, model=OLLAMA_MODEL, timeout=OLLAMA_TIMEOUT)
    return marvin_launcher.launch(
        "background-analyst", prompt,
        # Write/Edit blocked: same bug as daily_digest.py (found 2026-07-06) — without
        # this, the model tries to persist the digest itself via the Write tool, gets
        # silently denied (no TTY to approve a permission prompt), and narrates that
        # failure into the digest body instead of returning plain text. This script's
        # own file write below is the only thing that should ever write the file.
        permission_mode=None, disallowed_tools="Write,Edit", timeout=120,
    )


def generate(correlated: list[dict] | None = None) -> Path | None:
    today = date.today().isoformat()
    out_path = DIGEST_DIR / f"{today}.md"

    if brief_fallback.produced(out_path):
        print(f"[colony] research digest already exists for {today}", file=sys.stderr)
        return out_path

    all_items = load_today_cache()
    if not all_items:
        print("[colony] no items in today's cache — run source_monitor first", file=sys.stderr)
        notify("MARVIN research-colony failed", "no items fetched (all sources failed?)", open_target=str(Path.home() / ".claude" / "logs" / "research-colony-error.log"))
        return None

    if correlated is None:
        correlated = load_correlated_from_chroma()

    correlated_text = "\n".join(_fmt_item(i) for i in correlated) if correlated else "  (none matched today)"
    all_text = "\n".join(_fmt_item(i) for i in all_items[:30])

    prompt = DIGEST_PROMPT.format(correlated=correlated_text, all_items=all_text)

    try:
        result = _run_synthesis(prompt)
    except Exception as exc:
        print(f"[colony] synthesis call failed: {exc}", file=sys.stderr)
        notify("MARVIN research-colony failed", f"synthesis call failed: {str(exc)[:120]}", open_target=str(Path.home() / ".claude" / "logs" / "research-colony-error.log"))
        return None
    if result.exit_code != 0 or not result.text.strip():
        print(f"[colony] synthesis call failed: {(result.stderr or result.text)[:200]}", file=sys.stderr)
        notify("MARVIN research-colony failed", f"synthesis call failed: {(result.stderr or result.text)[:120]}", open_target=str(Path.home() / ".claude" / "logs" / "research-colony-error.log"))
        return None

    body = result.text.strip()

    # Score the synthesised digest before it ships — the actual failure mode
    # this guards is a relevance claim that doesn't survive reading the
    # summary carefully (e.g. a training technique claimed to transfer to a
    # system that only orchestrates a hosted model over an API).
    if _SAFETY_MONITOR_AVAILABLE and not pass_or_quarantine(body, loop_name="research_colony", source_context=prompt):
        print(f"[colony] digest quarantined by safety-monitor — see ~/.claude/quarantine.md",
              file=sys.stderr)
        notify("MARVIN research-colony quarantined", "Today's research digest was flagged for review — check ~/.claude/quarantine.md",
               open_target=str(Path.home() / ".claude" / "quarantine.md"))
        body = (
            "_Quarantined by safety-monitor before shipping — flagged as risky "
            "against the research_colony rubric. See `~/.claude/quarantine.md` "
            "for the full text and to approve/modify/deny._"
        )

    DIGEST_DIR.mkdir(parents=True, exist_ok=True)

    # Close TOCTOU window: final check before write (another process may have built it while we were generating)
    if brief_fallback.produced(out_path):
        print(f"[colony] Another process built the digest while we were working; skipping write", file=sys.stderr)
        return out_path

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
