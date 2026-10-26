#!/usr/bin/env python3
"""Detect when claims in memory or decisions have become stale relative to new writes.

Core check: when a file is written/edited, extract its key terms, search memory files and
repo docs for related claims, ask a judge LLM whether any contradict the new claim, and
flag contradictions in ~/.claude/stale-decisions.md.

Cheap two-stage retrieval (keyword overlap) narrows candidates before the judge call, so
cost scales with the number of *related* files, not all memory files or all repos.

Fails open: any error (gh call, judge timeout, etc.) logs via hook_errors and returns
no flag, never blocks the write it triggers on.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

import host_os  # noqa: E402
import marvin_launcher  # noqa: E402

MEMORY_DIR = host_os.memory_dir()
STALE_FLAGS_FILE = Path.home() / ".claude" / "stale-decisions.md"
OUTBOX_DIR = Path.home() / ".claude" / "outbox"
DOC_REPOS_CACHE = Path.home() / ".claude" / "logs" / "doc-repos-cache.json"

# Min extraction signal: at least this many concrete tokens (noun-ish) before attempting search
_MIN_SIGNAL = 2


@dataclass
class Candidate:
    source: str  # "memory" | "repo"
    repo: str | None  # repo owner/name if from a repo, None if memory
    path: str  # file path (relative in memory_dir, or absolute for repos)
    old_claim: str  # the excerpt matching the new claim
    new_claim: str  # the new/changed text


def extract_terms(text: str, max_length: int = 2000) -> list[str]:
    """Extract noun-ish terms from text (alphanumeric + $-€¢ tokens, skip common words).
    Bounded length to prevent huge extracts from hanging the retrieval."""
    text = text[:max_length].lower()
    # Match tokens like "$5", "€10", "app", "non-commercial"
    # Using negative lookahead/lookbehind to avoid word boundaries (which don't work with currency symbols)
    pattern = r'(?<![a-z0-9])[a-z0-9$€¢][a-z0-9$€¢\-/]*(?![a-z0-9\-/])'
    words = re.findall(pattern, text)
    # Skip common function words, prepositions, etc.
    stop = {
        'the', 'a', 'an', 'and', 'or', 'of', 'to', 'in', 'on', 'at', 'by', 'for',
        'is', 'are', 'am', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does',
        'did', 'will', 'would', 'should', 'could', 'can', 'may', 'might', 'must',
        'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they',
        'from', 'up', 'out', 'if', 'as', 'than', 'so', 'but', 'not', 'no', 'yes',
        'with', 'it', 'what', 'which', 'who', 'when', 'where', 'why', 'how',
        'tbh', 'tbp', 'tbd', 'xxx', 'etc', 'eg', 'ie', 'vs', 'v',
        'then', 'now', 'just', 'only', 'also', 'same', 'more', 'most', 'some',
        'v', 'vs', 'e.g', 'e.g.', 'i.e', 'i.e.', 'etc.', 'url'
    }
    return [w for w in words if w not in stop and len(w) > 1]


def find_memory_candidates(new_claim: str, skip_file: Path | None = None) -> list[Candidate]:
    """Search memory files for claims that share keyword overlap with new_claim.

    Skip the file that just changed (skip_file) to avoid matching the new text against itself.
    Bounded to avoid re-reading hundreds of files per write.
    """
    terms = extract_terms(new_claim)
    if len(terms) < _MIN_SIGNAL:
        return []

    found = []
    memory_files = sorted(MEMORY_DIR.glob("*.md"))
    for mf in memory_files:
        if skip_file and mf.resolve() == skip_file.resolve():
            continue
        try:
            content = mf.read_text(encoding="utf-8", errors="replace")
            # Extract body (skip frontmatter)
            parts = content.split("---", 2)
            body = parts[2].strip() if len(parts) == 3 and parts[0] == "" else content
            if not body:
                continue
            # Quick keyword overlap check
            overlap = sum(1 for t in terms if t in body.lower())
            if overlap >= _MIN_SIGNAL:
                # Simple heuristic: grab first matching paragraph
                for para in body.split("\n\n"):
                    if any(t in para.lower() for t in terms):
                        found.append(Candidate(
                            source="memory",
                            repo=None,
                            path=mf.name,
                            old_claim=para[:500],  # first 500 chars of matching para
                            new_claim=new_claim[:500]
                        ))
                        break
        except Exception:
            continue  # Read errors are logged by the hook, not here
    return found


def discover_doc_repos() -> list[dict]:
    """Find all repos with CONTEXT.md by checking the cache first, falling back to live discovery.

    Returns list of dicts with keys: owner, name, description (from `gh repo list --json`).
    """
    # Try cache first
    if DOC_REPOS_CACHE.exists():
        try:
            return json.loads(DOC_REPOS_CACHE.read_text())
        except Exception:
            pass

    # Fallback: live discovery via gh repo list
    try:
        result = subprocess.run(
            ["gh", "repo", "list", "--json", "owner,name,description"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass

    return []


def fetch_repo_docs(owner: str, name: str, run: Callable | None = None) -> dict:
    """Fetch CONTEXT.md and docs/adr/*.md from a GitHub repo via gh api.

    Returns dict keyed by doc type: {"context": "...", "adrs": ["content1", "content2", ...]}.
    """
    if run is None:
        run = subprocess.run

    docs = {"context": "", "adrs": []}
    repo = f"{owner}/{name}"

    # Fetch CONTEXT.md
    try:
        proc = run(
            ["gh", "api", f"repos/{repo}/contents/CONTEXT.md", "-H", "Accept: application/vnd.github.raw"],
            capture_output=True, text=True, timeout=5
        )
        if proc.returncode == 0:
            docs["context"] = proc.stdout
    except Exception:
        pass

    # Fetch ADR files (list first)
    try:
        proc = run(
            ["gh", "api", f"repos/{repo}/contents/docs/adr", "--jq", ".[].name"],
            capture_output=True, text=True, timeout=5
        )
        if proc.returncode == 0:
            for fname in proc.stdout.strip().split("\n"):
                if fname.endswith(".md"):
                    try:
                        proc2 = run(
                            ["gh", "api", f"repos/{repo}/contents/docs/adr/{fname}", "-H", "Accept: application/vnd.github.raw"],
                            capture_output=True, text=True, timeout=5
                        )
                        if proc2.returncode == 0:
                            docs["adrs"].append(proc2.stdout)
                    except Exception:
                        continue
    except Exception:
        pass

    return docs


def find_repo_candidates(new_claim: str, repos: list[dict]) -> list[Candidate]:
    """Find repo docs that might contradict new_claim.

    Keyword-filter by repo name/description first (Decision: repo-search-scope=A),
    then fetch and search their docs.
    """
    terms = extract_terms(new_claim)
    if len(terms) < _MIN_SIGNAL:
        return []

    found = []
    for repo_info in repos:
        owner = repo_info.get("owner", {}).get("login", "")
        name = repo_info.get("name", "")
        desc = (repo_info.get("description") or "").lower()
        repo_name_lower = f"{owner}/{name}".lower()

        # Keyword filter: does the repo name/desc overlap with the claim?
        overlap = sum(1 for t in terms if t in repo_name_lower or t in desc)
        if overlap < 1:
            continue  # Skip repos with no keyword match

        # Fetch CONTEXT.md and ADRs
        docs = fetch_repo_docs(owner, name)
        for doc_type, content in [("CONTEXT", docs["context"])] + [(f"adr_{i}", c) for i, c in enumerate(docs["adrs"])]:
            if not content:
                continue
            # Quick overlap in content
            overlap_content = sum(1 for t in terms if t in content.lower())
            if overlap_content >= _MIN_SIGNAL:
                for para in content.split("\n\n"):
                    if any(t in para.lower() for t in terms):
                        found.append(Candidate(
                            source="repo",
                            repo=f"{owner}/{name}",
                            path=f"{doc_type}.md",
                            old_claim=para[:500],
                            new_claim=new_claim[:500]
                        ))
                        break

    return found


def judge_contradiction(old_claim: str, new_claim: str, judge: Callable | None = None) -> bool:
    """Ask a Haiku judge: does new_claim contradict old_claim?

    Returns True if judge says yes (contradiction), False otherwise.
    Fails open: any error returns False (no flag).
    """
    if judge is None:
        # Use marvin_launcher to run the judge
        judge_prompt = f"""You are a fact-checker comparing two claims. Answer ONLY "yes" or "no" (lowercase, one word).

OLD claim: {old_claim[:500]}

NEW claim: {new_claim[:500]}

Does the NEW claim directly contradict the OLD claim? Say only "yes" or "no"."""

        try:
            result = marvin_launcher.launch(
                "judge",
                judge_prompt,
                timeout=10,
                permission_mode="dontAsk"
            )
            if result.exit_code != 0:
                return False
            answer = result.text.strip().lower()
            return answer == "yes"
        except Exception:
            return False
    else:
        # For testing: inject a callable that returns True/False
        try:
            return judge(old_claim, new_claim)
        except Exception:
            return False


def check_decision(new_text: str, new_file: Path | None = None, judge: Callable | None = None) -> Candidate | None:
    """Check if new_text contradicts any claims in memory or repo docs.

    new_file: the Path to the file being written (used to skip matching it against itself).
    judge: injectable judge callable for testing.

    Returns a Candidate if a contradiction is found, None otherwise.
    """
    if not new_text or not new_text.strip():
        return None

    terms = extract_terms(new_text)
    if len(terms) < _MIN_SIGNAL:
        return None

    # Search memory
    memory_cands = find_memory_candidates(new_text, skip_file=new_file)

    # Search repos
    repos = discover_doc_repos()
    repo_cands = find_repo_candidates(new_text, repos)

    all_cands = memory_cands + repo_cands

    # Judge each candidate
    for cand in all_cands:
        if judge_contradiction(cand.old_claim, new_text, judge=judge):
            return cand

    return None


def flag(candidate: Candidate, flags_file: Path | None = None) -> None:
    """Idempotently append a flagged contradiction to the flags file.

    Uses the quarantine.md format: dated block, quoted old+new claim, checkbox.
    Deduplicates: if the exact same flag is already queued, doesn't append again.
    """
    if flags_file is None:
        flags_file = STALE_FLAGS_FILE

    # Build the entry
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry = f"""## Stale claim flagged at {now}

**Source:** {candidate.source} ({candidate.repo or candidate.path})

**Old claim:**
> {candidate.old_claim.replace(chr(10), chr(10) + '> ')}

**New claim:**
> {candidate.new_claim.replace(chr(10), chr(10) + '> ')}

- [ ] Approve (update old claim)
- [ ] Dismiss (new claim needs correction)

---
"""

    # Check if this entry already exists (dedupe)
    if flags_file.exists():
        existing = flags_file.read_text()
        if candidate.old_claim in existing and candidate.new_claim in existing:
            return  # Already flagged

    # Append
    flags_file.parent.mkdir(parents=True, exist_ok=True)
    with flags_file.open("a") as f:
        f.write(entry)


def sweep(output_file: Path | None = None) -> None:
    """Report-only sweep: scan memory files against each other and against repo docs.

    Writes a dated report to output_file (or ~/.claude/outbox/stale-decisions-sweep-<date>.md).
    Does not modify any memory file, CONTEXT.md, or ADR.
    """
    if output_file is None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        output_file = OUTBOX_DIR / f"stale-decisions-sweep-{now}.md"

    report_lines = [
        "# Stale-decisions sweep report",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
    ]

    memory_files = sorted(MEMORY_DIR.glob("*.md"))
    contradictions = []

    for mf in memory_files:
        try:
            content = mf.read_text(encoding="utf-8", errors="replace")
            parts = content.split("---", 2)
            body = parts[2].strip() if len(parts) == 3 and parts[0] == "" else content
            if body:
                # Check this memory file against all others
                for other_mf in memory_files:
                    if mf.resolve() == other_mf.resolve():
                        continue
                    try:
                        other_content = other_mf.read_text(encoding="utf-8", errors="replace")
                        other_parts = other_content.split("---", 2)
                        other_body = other_parts[2].strip() if len(other_parts) == 3 and other_parts[0] == "" else other_content
                        if other_body:
                            # Quick term overlap
                            my_terms = set(extract_terms(body))
                            their_terms = set(extract_terms(other_body))
                            if len(my_terms & their_terms) >= _MIN_SIGNAL:
                                # Possible contradiction
                                if judge_contradiction(body, other_body):
                                    contradictions.append((mf.name, other_mf.name, body[:200], other_body[:200]))
                    except Exception:
                        continue
        except Exception:
            continue

    # Also check memory against repos
    repos = discover_doc_repos()
    for mf in memory_files:
        try:
            content = mf.read_text(encoding="utf-8", errors="replace")
            parts = content.split("---", 2)
            body = parts[2].strip() if len(parts) == 3 and parts[0] == "" else content
            if body:
                repo_cands = find_repo_candidates(body, repos)
                for rc in repo_cands:
                    if judge_contradiction(body, rc.old_claim):
                        contradictions.append((mf.name, f"{rc.repo}/{rc.path}", body[:200], rc.old_claim[:200]))
        except Exception:
            continue

    # Write report
    if contradictions:
        report_lines.append(f"## Found {len(contradictions)} potential contradiction(s):\n")
        for src1, src2, claim1, claim2 in contradictions:
            report_lines.append(f"- **{src1}** vs **{src2}**")
            report_lines.append(f"  - {claim1}...")
            report_lines.append(f"  - {claim2}...")
            report_lines.append("")
    else:
        report_lines.append("No contradictions found.")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(report_lines))


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Check for stale decisions.")
    subparsers = parser.add_subparsers(dest="command")

    check_parser = subparsers.add_parser("check", help="Check a specific claim")
    check_parser.add_argument("claim", help="The claim to check")
    check_parser.add_argument("--file", type=Path, help="File being written (for deduplication)")

    subparsers.add_parser("sweep", help="Report-only sweep of all memory")

    args = parser.parse_args()
    if args.command == "check":
        cand = check_decision(args.claim, new_file=args.file)
        if cand:
            flag(cand)
            print(f"Flagged contradiction in {cand.path}")
        else:
            print("No contradiction found")
    elif args.command == "sweep":
        sweep()
        print(f"Sweep report written to {OUTBOX_DIR / 'stale-decisions-sweep-*.md'}")


if __name__ == "__main__":
    main()
