#!/usr/bin/env python3
"""Stale decision checker: flags when memory notes contradict recently-added repo docs.

Design: docs/design/pipeline-g-eskayo-marvin-652.md. Reuses project_catalog tokens(),
discover_memory(), continuity_checker's Ollama pattern, and output_contracts'
**Status:**/**Added**: block reader.

Scope: live checks on memory notes, CONTEXT.md, docs/adr/*.md (after hook-scope decision
is made). One-off sweep across all memory-vs-memory + memory-vs-project-docs pairs.

    stale_decision_check.py check <path>        # called by PostToolUse hook
    stale_decision_check.py sweep [--output DIR] # one-off discovery + report
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_catalog  # noqa: E402

STALE_DECISIONS = Path.home() / ".claude" / "stale-decisions.md"
MEMORY_DIR = project_catalog.MEMORY_DIR
OLLAMA_URL = "http://localhost:11434/api/chat"
JUDGE_MODEL = "qwen2.5:14b"

STALE_VERDICT = "STALE"  # stands for "contradicts or has gaps from repo docs"
VERDICTS = {"CONSISTENT", "STALE"}  # STALE = CONTRADICTS or GAP from continuity_checker


def ollama_chat(model: str, messages: list[dict], timeout: int = 60) -> str:
    """Call Ollama via local HTTP, with graceful failure."""
    try:
        payload = json.dumps({"model": model, "messages": messages, "stream": False}).encode()
        req = urllib.request.Request(
            OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return data["message"]["content"]
    except Exception as e:
        raise RuntimeError(f"Ollama call failed: {e}") from e


# ── candidate gathering ────────────────────────────────────────────────────────────

def repo_root(from_path: Path | str | None = None) -> Path | None:
    """Find .git from a given path or the current working directory or parents."""
    if from_path is None:
        cwd = Path.cwd()
    else:
        cwd = Path(from_path) if isinstance(from_path, str) else from_path
        # If it's a file, start from its parent directory
        if cwd.is_file():
            cwd = cwd.parent
    for p in [cwd] + list(cwd.parents):
        if (p / ".git").exists():
            return p
    return None


def repo_doc_candidates(repo: Path | None = None) -> list[tuple[str, str]]:
    """Gather (name, text) pairs from repo CONTEXT.md and docs/adr/*.md."""
    root = repo or repo_root()
    if not root:
        return []
    candidates = []
    context = root / "CONTEXT.md"
    if context.exists():
        try:
            text = context.read_text(errors="ignore")[:2000]
            candidates.append((context.name, text))
        except OSError:
            pass
    adr_dir = root / "docs" / "adr"
    if adr_dir.is_dir():
        for f in sorted(adr_dir.glob("*.md")):
            try:
                text = f.read_text(errors="ignore")[:2000]
                candidates.append((f.name, text))
            except OSError:
                pass
    return candidates


def memory_candidates() -> list[tuple[str, str]]:
    """Gather (filename, text) pairs from memory notes (wraps discover_memory)."""
    candidates = []
    for m in project_catalog.discover_memory(MEMORY_DIR):
        candidates.append((m["file"], m["text"]))  # text already truncated to 1500
    return candidates


def gather_candidates(repo: Path | None = None) -> dict[str, list[tuple[str, str]]]:
    """Return {source: [(name, text)]} where source in ["repo", "memory"]."""
    return {
        "repo": repo_doc_candidates(repo),
        "memory": memory_candidates(),
    }


# ── lexical pre-filter ─────────────────────────────────────────────────────────────

def _score_overlap(tokens_a: set[str], tokens_b: set[str]) -> float:
    """Jaccard overlap: intersection / union. Returns 0..1."""
    if not tokens_a or not tokens_b:
        return 0.0
    union = tokens_a | tokens_b
    intersection = tokens_a & tokens_b
    return len(intersection) / len(union) if union else 0.0


def _prefilter_candidates(
    new_text: str,
    repo_docs: list[tuple[str, str]],
    memory_docs: list[tuple[str, str]],
    min_overlap: float = 0.1,
    max_checks: int = 20,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Filter repo_docs and memory_docs by lexical overlap with new_text.
    Returns (filtered_repo, filtered_memory), bounded by max_checks per group."""
    new_tokens = project_catalog.tokens(new_text)
    if not new_tokens:
        return [], []
    repo_filtered, memory_filtered = [], []
    repo_scored = [(name, text, _score_overlap(new_tokens, project_catalog.tokens(text)))
                   for name, text in repo_docs]
    memory_scored = [(name, text, _score_overlap(new_tokens, project_catalog.tokens(text)))
                     for name, text in memory_docs]
    repo_scored.sort(key=lambda x: -x[2])
    memory_scored.sort(key=lambda x: -x[2])
    repo_filtered = [(name, text) for name, text, score in repo_scored
                     if score >= min_overlap][:max_checks]
    memory_filtered = [(name, text) for name, text, score in memory_scored
                       if score >= min_overlap][:max_checks]
    return repo_filtered, memory_filtered


# ── claim classification ───────────────────────────────────────────────────────────

def classify_claim_pair(
    new_claim: str,
    old_claim: str,
    old_source: str,
    chat_fn: Callable[[list[dict]], str] | None = None,
) -> dict[str, str]:
    """Classify relationship between a new fact and an old claim in memory/docs.
    Returns {verdict: CONSISTENT|STALE, rationale: str}."""
    chat_fn = chat_fn or (lambda msgs: ollama_chat(JUDGE_MODEL, msgs))
    prompt = f"""Below are two claims about the same topic.

NEW claim (from recently-added repo docs or memory):
{new_claim}

OLD claim (from {old_source}):
{old_claim}

Are these claims compatible? Judge only the explicit relationship:
- CONSISTENT: The new claim extends, refines, or is compatible with the old claim. Even if critical or correcting, engagement is clear.
- STALE: The new claim contradicts the old claim, or there's a significant gap where the new claim makes an assertion the old one contradicted or left unaddressed. The old claim needs updating.

Respond in this format:
VERDICT: <CONSISTENT or STALE>
RATIONALE: <one sentence>"""
    try:
        response = chat_fn([{"role": "user", "content": prompt}])
        return _parse_classification_result(response)
    except Exception as e:
        return {"verdict": "error", "rationale": f"judge failed: {e}"}


def _parse_classification_result(response: str) -> dict[str, str]:
    """Parse VERDICT and RATIONALE from classification response."""
    result = {}
    for line in response.splitlines():
        if line.strip().upper().startswith("VERDICT:"):
            verdict_text = line.strip()[len("VERDICT:"):].strip().upper()
            found = [v for v in VERDICTS if re.search(r'\b' + re.escape(v) + r'\b', verdict_text)]
            result["verdict"] = found[0] if len(found) == 1 else "unknown"
        elif line.strip().upper().startswith("RATIONALE:"):
            result["rationale"] = line.strip()[len("RATIONALE:"):].strip()
    return result


# ── main check pipeline ────────────────────────────────────────────────────────────

def find_stale_claims(
    new_text: str,
    new_source: str = "new doc",
    chat_fn: Callable[[list[dict]], str] | None = None,
    file_path: Path | str | None = None,
) -> list[dict]:
    """Find stale claims in memory/repo docs that conflict with new_text.
    Returns [{file: str, source: str, old_claim: str, verdict: str, rationale: str}, ...]
    only for STALE verdicts. Excludes the just-written file (file_path) from candidates."""
    if not new_text.strip():
        return []
    # Determine repo from file_path if provided
    repo = None
    exclude_name = None
    if file_path:
        path = Path(file_path) if isinstance(file_path, str) else file_path
        exclude_name = path.name
        repo = repo_root(path)
    candidates = gather_candidates(repo)
    # Filter out the just-written file from candidates to avoid Jaccard 1.0 self-match
    filtered_repo = [(n, t) for n, t in candidates["repo"] if n != exclude_name]
    filtered_memory = [(n, t) for n, t in candidates["memory"] if n != exclude_name]
    repo_docs, memory_docs = _prefilter_candidates(
        new_text, filtered_repo, filtered_memory
    )
    if not repo_docs and not memory_docs:
        return []
    stale = []
    for source, docs in [("repo", repo_docs), ("memory", memory_docs)]:
        for fname, old_text in docs:
            classification = classify_claim_pair(
                new_text, old_text, fname, chat_fn=chat_fn
            )
            if classification.get("verdict") == STALE_VERDICT:
                stale.append({
                    "file": fname,
                    "source": source,
                    "old_claim": old_text[:200],
                    "verdict": classification.get("verdict"),
                    "rationale": classification.get("rationale", ""),
                })
    return stale


# ── entry formatting and dedup ─────────────────────────────────────────────────────

def format_entry(
    new_file: str,
    stale_findings: list[dict],
    now: datetime | None = None,
    file_path: Path | str | None = None,
) -> str:
    """Format a markdown entry for stale-decisions.md."""
    now = now or datetime.now(timezone.utc)
    date_str = now.date().isoformat()
    # Store full path for dedup purposes
    source = str(Path(file_path).resolve()) if file_path else new_file
    L = [
        f"## {date_str} — {new_file}",
        "",
        f"**Status**: pending",
        f"**Added**: {date_str}",
        f"**Source**: {source}",
        f"**Findings**: {len(stale_findings)} potential stale claim(s)",
        "",
    ]
    for i, finding in enumerate(stale_findings, 1):
        L.append(f"### Finding {i}: {finding['file']} ({finding['source']})")
        L.append(f"**Verdict**: {finding['verdict']}")
        L.append(f"**Rationale**: {finding['rationale']}")
        L.append(f"**Old claim excerpt**: {finding['old_claim']}")
        L.append("")
    return "\n".join(L)


def existing_pending_keys() -> set[tuple[str, str]]:
    """Return set of (date, filepath_hash) pairs with **Status**: pending in stale-decisions.md.
    This avoids checking against resolved findings (Status != pending).
    Uses filepath_hash (from Source field) to handle same-named files in different repos."""
    if not STALE_DECISIONS.exists():
        return set()
    text = STALE_DECISIONS.read_text()
    keys = set()
    # Find each entry block and check if **Status**: pending
    for m in re.finditer(r"^## (\d{4}-\d{2}-\d{2}) — (.+?)$\n(.*?)(?=^##|\Z)", text, re.MULTILINE | re.DOTALL):
        date_str, fname, block = m.groups()
        if "**Status**: pending" in block:
            # Extract Source field to get the full path context
            source_match = re.search(r"\*\*Source\*\*: (.+?)(?:\n|$)", block)
            source = source_match.group(1) if source_match else fname
            # Use hash of full source path to deduplicate across repos
            path_hash = hashlib.md5(source.encode()).hexdigest()[:8]
            keys.add((date_str, path_hash))
    return keys


def append_flags(entry_text: str, path: Path | None = None) -> None:
    """Append entry_text to path (or create if missing), using tmp-file-then-replace for atomicity.
    Resolves path at call time to support patching in tests."""
    if path is None:
        path = STALE_DECISIONS
    path.parent.mkdir(parents=True, exist_ok=True)
    # Use fcntl.flock to ensure exclusive access during read-modify-write
    lock_file = path.parent / ".stale-decisions.lock"
    try:
        with open(lock_file, "w") as lock_f:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
            try:
                existing = path.read_text() if path.exists() else ""
                combined = existing + ("\n" if existing and not existing.endswith("\n") else "") + entry_text
                # Write to tmp file, then atomically replace original
                tmp_path = path.parent / f".{path.name}.tmp"
                tmp_path.write_text(combined)
                tmp_path.replace(path)
            finally:
                fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
    except Exception:
        # Fallback: if locking fails, use non-atomic write (graceful degradation)
        existing = path.read_text() if path.exists() else ""
        combined = existing + ("\n" if existing and not existing.endswith("\n") else "") + entry_text
        # Write to tmp file, then atomically replace original
        tmp_path = path.parent / f".{path.name}.tmp"
        tmp_path.write_text(combined)
        tmp_path.replace(path)


# ── entry point for hook ───────────────────────────────────────────────────────────

def check_file(
    file_path: str,
    chat_fn: Callable[[list[dict]], str] | None = None,
) -> dict[str, str | int]:
    """Read a newly-written file and flag any stale claims from memory/repo docs.
    Returns {status: ok|error, message: str, flags_added: int}."""
    try:
        path = Path(file_path)
        if not path.exists():
            return {"status": "ok", "message": "file does not exist", "flags_added": 0}
        new_text = path.read_text(errors="ignore")
        if not new_text.strip():
            return {"status": "ok", "message": "file is empty", "flags_added": 0}
        stale_findings = find_stale_claims(new_text, path.name, chat_fn=chat_fn, file_path=path)
        if not stale_findings:
            return {"status": "ok", "message": "no stale claims found", "flags_added": 0}
        existing_keys = existing_pending_keys()
        today = datetime.now(timezone.utc).date().isoformat()
        # Use hash of full path to handle same-named files in different repos
        path_hash = hashlib.md5(str(path.resolve()).encode()).hexdigest()[:8]
        key = (today, path_hash)
        if key in existing_keys:
            return {"status": "ok", "message": "entry already exists", "flags_added": 0}
        entry = format_entry(path.name, stale_findings, file_path=path)
        append_flags(entry)
        return {"status": "ok", "message": f"flagged {len(stale_findings)} stale claim(s)", "flags_added": len(stale_findings)}
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e), "flags_added": 0}


# ── sweep: find all stale claims across memory and repo docs ──────────────────────

def sweep(
    max_pairs: int = 50,
    chat_fn: Callable[[list[dict]], str] | None = None,
) -> list[dict]:
    """Memory-vs-memory and memory-vs-repo scan for stale claims.
    Returns list of {old_file, new_file, verdict, rationale} dicts for all STALE verdicts.
    Deduplicates pairs (A,B) and (B,A) and bounds comparisons."""
    candidates = gather_candidates()
    memory_docs = candidates["memory"]
    repo_docs = candidates["repo"]
    if not memory_docs and not repo_docs:
        return []

    # Precompute tokens once per document
    memory_tokens = {fname: project_catalog.tokens(text) for fname, text in memory_docs}
    repo_tokens = {fname: project_catalog.tokens(text) for fname, text in repo_docs}

    stale = []
    checked = 0
    checked_pairs = set()  # Deduplicate (A,B) vs (B,A)

    # Memory-vs-memory comparisons
    for old_fname, old_text in memory_docs:
        if checked >= max_pairs:
            break
        for new_fname, new_text in memory_docs:
            if checked >= max_pairs:
                break
            if old_fname == new_fname:
                continue
            # Skip if we've already checked this pair (either direction)
            pair_key = tuple(sorted([old_fname, new_fname]))
            if pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)

            old_tok = memory_tokens.get(old_fname, set())
            new_tok = memory_tokens.get(new_fname, set())
            if not old_tok or not new_tok:
                continue
            if _score_overlap(old_tok, new_tok) < 0.1:
                continue

            classification = classify_claim_pair(
                new_text, old_text, old_fname, chat_fn=chat_fn
            )
            checked += 1
            if classification.get("verdict") == STALE_VERDICT:
                stale.append({
                    "old_file": old_fname,
                    "new_file": new_fname,
                    "verdict": classification.get("verdict"),
                    "rationale": classification.get("rationale", ""),
                })

    # Memory-vs-repo comparisons
    for old_fname, old_text in memory_docs:
        if checked >= max_pairs:
            break
        for new_fname, new_text in repo_docs:
            if checked >= max_pairs:
                break

            old_tok = memory_tokens.get(old_fname, set())
            new_tok = repo_tokens.get(new_fname, set())
            if not old_tok or not new_tok:
                continue
            if _score_overlap(old_tok, new_tok) < 0.1:
                continue

            classification = classify_claim_pair(
                new_text, old_text, old_fname, chat_fn=chat_fn
            )
            checked += 1
            if classification.get("verdict") == STALE_VERDICT:
                stale.append({
                    "old_file": old_fname,
                    "new_file": new_fname,
                    "verdict": classification.get("verdict"),
                    "rationale": classification.get("rationale", ""),
                })

    return stale


def render_sweep_report(stale_findings: list[dict], now: datetime | None = None) -> str:
    """Render sweep findings as a markdown report."""
    now = now or datetime.now(timezone.utc)
    date_str = now.date().isoformat()
    L = [
        f"# Stale Decision Sweep — {date_str}",
        "",
        f"Auto-discovered {len(stale_findings)} potential stale claim(s) across memory and repo docs.",
        f"Review each and move confirmed findings to a specific ticket or decision node.",
        "",
    ]
    if not stale_findings:
        L.append("No stale claims found.")
        return "\n".join(L)
    for i, finding in enumerate(stale_findings, 1):
        L.append(f"## {i}. {finding['old_file']} vs {finding['new_file']}")
        L.append(f"**Verdict**: {finding['verdict']}")
        L.append(f"**Rationale**: {finding['rationale']}")
        L.append("")
    return "\n".join(L)


# ── CLI ────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("file_path", help="newly-written file path")
    s = sub.add_parser("sweep")
    s.add_argument("--output", help="directory for sweep report (default: ~/.claude/outbox/)")
    a = ap.parse_args()
    if a.cmd == "check":
        result = check_file(a.file_path)
        if result["status"] == "error":
            print(f"error: {result['message']}", file=sys.stderr)
            return 1
        if result["flags_added"] > 0:
            print(f"flagged {result['flags_added']} stale claim(s)")
        return 0
    elif a.cmd == "sweep":
        findings = sweep()
        report = render_sweep_report(findings)
        outdir = Path(a.output or (Path.home() / ".claude" / "outbox"))
        outdir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).date().isoformat()
        outpath = outdir / f"stale-decisions-sweep-{date_str}.md"
        outpath.write_text(report)
        print(f"sweep report: {outpath}")
        if findings:
            print(f"found {len(findings)} stale claim(s)")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
