#!/usr/bin/env python3
"""Stale decision checker: find contradictions between memory/docs and current code state.

Compares memory claims (project notes, memory index, CLAUDE.md rules) against what's
actually in the repo (CONTEXT.md, docs/adr/, README.md) and code to surface decisions
that have gone stale — claimed intent that the implementation contradicts.

Designed to run both on-demand (when a memory file is written) and periodically (sweep),
using a Judge (clean, no MARVIN context) to call contradictions that deterministic checks
can't decide alone.
"""
from __future__ import annotations

import fcntl
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import host_os  # noqa: E402
import marvin_launcher  # noqa: E402
import project_catalog  # noqa: E402

MEMORY_DIR = host_os.memory_dir()
CONTRADICTIONS_FILE = Path.home() / ".claude" / "contradictions.md"


class JudgeError(Exception):
    """Raised when Judge call fails or returns unparseable output."""
    pass


@dataclass(frozen=True)
class Candidate:
    """A matched file that might contain relevant info about the claim."""
    file_path: Path
    project_id: str | None  # None if it's a global doc
    file_type: str  # "context", "adr", "readme", "memory", "code"
    snippet: str  # relevant excerpt


@dataclass(frozen=True)
class Flag:
    """A flagged contradiction or stale decision."""
    file_path: str  # memory or docs file that was checked
    text_excerpt: str  # the claim that was flagged
    issue: str  # short description of the potential contradiction
    source: str  # "check_claim" or "sweep"
    timestamp: str  # ISO format
    verdict: str | None = None  # "contradiction" | "acceptable" | None (unreviewed)


def _tokenize(text: str) -> set[str]:
    """Extract meaningful tokens from text, reusing project_catalog's pattern."""
    return project_catalog.tokens(text)


def find_candidates(
    new_text: str,
    project_hint: str | None = None,
    catalog: dict | None = None,
    exclude_path: Path | None = None,
) -> list[Candidate]:
    """Find files in the matched project that might contain relevant context.

    Matches tokens from new_text against project docs (CONTEXT.md, docs/adr/*, README.md),
    code files, and memory notes. Returns candidates ranked by likely relevance.

    Args:
        new_text: the claim text to search for
        project_hint: specific project ID to search (takes precedence)
        catalog: project catalog (loaded if None)
        exclude_path: file path to exclude from candidates (self-match prevention)
    """
    if catalog is None:
        catalog_path = project_catalog.catalog_path()
        catalog = project_catalog.read_catalog(catalog_path) or {}

    tokens = _tokenize(new_text)
    if not tokens:
        return []

    candidates: list[Candidate] = []

    # Match against project catalog to find the relevant project
    matched_project = None
    if project_hint:
        for p in (catalog.get("projects") or []):
            if p.get("id") == project_hint:
                matched_project = p
                break

    if not matched_project:
        # Try to infer from tokens in project names/descriptions
        # Require at least 2 token matches to avoid false positives on common words
        best_match = None
        best_overlap = 0
        for p in (catalog.get("projects") or []):
            p_tokens = _tokenize(f"{p.get('name', '')} {p.get('description', '')}")
            overlap = len(p_tokens & tokens)
            if overlap > best_overlap:
                best_overlap = overlap
                best_match = p
        if best_overlap >= 2:  # require at least 2 matches
            matched_project = best_match

    if not matched_project:
        return []

    project_id = matched_project.get("id")
    primary_path = matched_project.get("primaryPath")

    if not primary_path:
        return []

    primary = Path(primary_path)

    # Normalize exclude_path for comparison
    exclude_resolved = None
    if exclude_path:
        try:
            exclude_resolved = exclude_path.resolve()
        except (OSError, ValueError):
            pass

    # Search CONTEXT.md, README.md, and docs/adr/*.md
    for doc_file, doc_type in [
        (primary / "CONTEXT.md", "context"),
        (primary / "README.md", "readme"),
    ]:
        if doc_file.exists():
            # Skip self-matches
            if exclude_resolved and doc_file.resolve() == exclude_resolved:
                continue
            try:
                content = doc_file.read_text(errors="ignore")
                # Check if the tokens appear in the doc
                doc_tokens = _tokenize(content)
                if tokens & doc_tokens:
                    # Find a relevant snippet (section or first N lines)
                    snippet = _extract_snippet(content, tokens, max_len=300)
                    candidates.append(
                        Candidate(
                            file_path=doc_file,
                            project_id=project_id,
                            file_type=doc_type,
                            snippet=snippet,
                        )
                    )
            except (OSError, UnicodeDecodeError):
                pass

    # Search docs/adr/
    adr_dir = primary / "docs" / "adr"
    if adr_dir.is_dir():
        for adr_file in sorted(adr_dir.glob("*.md")):
            # Skip self-matches
            if exclude_resolved and adr_file.resolve() == exclude_resolved:
                continue
            try:
                content = adr_file.read_text(errors="ignore")
                doc_tokens = _tokenize(content)
                if tokens & doc_tokens:
                    snippet = _extract_snippet(content, tokens, max_len=300)
                    candidates.append(
                        Candidate(
                            file_path=adr_file,
                            project_id=project_id,
                            file_type="adr",
                            snippet=snippet,
                        )
                    )
            except (OSError, UnicodeDecodeError):
                pass

    # Also check memory notes for the same project
    for memory_file in MEMORY_DIR.glob("*.md"):
        if memory_file.name == "MEMORY.md":
            continue
        # Skip self-matches
        if exclude_resolved and memory_file.resolve() == exclude_resolved:
            continue
        try:
            content = memory_file.read_text(errors="ignore")
            # Check if this memory note is about the same project
            if _is_project_memory(content, project_id):
                doc_tokens = _tokenize(content)
                if tokens & doc_tokens:
                    snippet = _extract_snippet(content, tokens, max_len=300)
                    candidates.append(
                        Candidate(
                            file_path=memory_file,
                            project_id=project_id,
                            file_type="memory",
                            snippet=snippet,
                        )
                    )
        except (OSError, UnicodeDecodeError):
            pass

    return candidates


def _is_project_memory(content: str, project_id: str) -> bool:
    """Check if a memory note is about a specific project."""
    # Look for project ID in the content or frontmatter
    return project_id in content.lower()


def _extract_snippet(text: str, tokens: set[str], max_len: int = 300) -> str:
    """Extract a relevant snippet from text containing the tokens."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        line_tokens = _tokenize(line)
        if line_tokens & tokens:
            # Found a matching line, grab context around it
            start = max(0, i - 1)
            end = min(len(lines), i + 3)
            snippet = "\n".join(lines[start:end])
            return snippet[: min(len(snippet), max_len)]
    return text[:max_len]


_JUDGE_RUBRIC = """You are a Judge reviewing a potential contradiction between a documented claim and current system state.

Your job: is this a real contradiction (the claim and reality fundamentally disagree) or an acceptable situation
(the claim is dated but not wrong, or applies to a different context)?

Read both texts carefully. For a contradiction to be REAL:
1. The claim must be specific enough to verify (not vague general guidance)
2. The current state must directly contradict it, not just be different
3. The contradiction must be material (not a trivial wording difference)

Respond with ONLY one line:
VERDICT: contradiction (explain briefly)
OR
VERDICT: acceptable (explain briefly)

Be grounded and skeptical of false alarms. A rule can be overridden without being "stale."
"""


def judge_contradiction(
    claim_text: str,
    current_state_text: str,
    judge: Callable[[str], str] | None = None,
) -> Flag | None:
    """Use Judge to determine if claim_text contradicts current_state_text.

    Returns a Flag if a contradiction is found, None if the claim is acceptable.
    On Judge failure (exception, no output, unparseable), raises JudgeError.
    """
    if judge is None:
        judge = _default_judge

    prompt = (
        f"{_JUDGE_RUBRIC}\n\n"
        f"DOCUMENTED CLAIM:\n{claim_text}\n\n"
        f"CURRENT STATE:\n{current_state_text}"
    )

    try:
        verdict = judge(prompt)
    except Exception as e:
        # Judge failed: re-raise so caller can distinguish failure from "acceptable"
        raise JudgeError(f"Judge call failed: {e}") from e

    if not verdict:
        # Empty output is a judge failure
        raise JudgeError("Judge returned empty output")

    # Parse the verdict, anchoring on VERDICT: token
    verdict_lower = verdict.lower()
    if "verdict:" not in verdict_lower:
        raise JudgeError(f"Judge output missing VERDICT: token: {verdict}")

    # Extract the verdict line and check what comes after VERDICT:
    for line in verdict.split("\n"):
        if "verdict:" in line.lower():
            # Find the position of "verdict:" and check what follows
            idx = line.lower().find("verdict:")
            after_verdict = line[idx + 8:].strip().lower()
            if after_verdict.startswith("contradiction"):
                return Flag(
                    file_path="",  # will be set by caller
                    text_excerpt=claim_text[:200],
                    issue=verdict,
                    source="",  # will be set by caller
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    verdict="contradiction",
                )
            break

    return None


def _default_judge(prompt: str) -> str:
    """Default Judge implementation using marvin_launcher."""
    result = marvin_launcher.launch(
        "judge",
        prompt,
        model="claude-haiku-4-5-20251001",
        tools="",
        permission_mode=None,
        timeout=120,
    )
    return result.text.strip() if result.exit_code == 0 else ""


def _is_already_flagged(file_path: Path, text: str) -> bool:
    """Check if this claim is already in contradictions.md (idempotency).

    Only considers flags with a resolved verdict (not None). Flags with verdict=None
    are unreviewed/failed and will be re-judged on the next write.
    """
    if not CONTRADICTIONS_FILE.exists():
        return False

    existing = CONTRADICTIONS_FILE.read_text()
    file_str = str(file_path)

    # Look for file_path in existing flags
    if file_str not in existing:
        return False

    # Extract the first 200 chars for comparison
    text_excerpt = text[:200]

    # Build both quoted and unquoted versions for matching
    # Quoted version: each line starts with "> "
    quoted_excerpt = "\n".join(f"> {line}" for line in text_excerpt.splitlines())

    # Search for file_path block containing this flag
    # Find all ## headers for this file
    file_pattern = rf"^## [^\n]* \| [^\n]* \| {re.escape(file_str)}"
    matches = list(re.finditer(file_pattern, existing, re.MULTILINE))

    if not matches:
        return False

    # For each matching flag block, check if the excerpt appears AND verdict is not None
    for match in matches:
        block_start = match.start()
        # Find the next ## header (next flag block)
        next_header = re.search(r"^## ", existing[block_start + 1 :], re.MULTILINE)
        if next_header:
            block_end = block_start + next_header.start() + 1
        else:
            block_end = len(existing)

        block = existing[block_start:block_end]

        # Check if excerpt appears (either raw or quoted format)
        excerpt_found = text_excerpt in block or quoted_excerpt in block

        if not excerpt_found:
            continue

        # Check if this flag has a resolved verdict (not None)
        # Flags with verdict=None are unreviewed/failed and should be re-judged
        has_resolved_verdict = bool(
            re.search(r"- \[x\].*(?:approve|contradiction|update)", block, re.IGNORECASE)
        )

        if has_resolved_verdict:
            # This flag was already judged (result was acceptable/contradiction/update)
            return True

    return False


def check_claim(
    file_path: Path, text: str, project_hint: str | None = None
) -> list[Flag]:
    """Check if a memory file's claims are contradicted by current repo state.

    Idempotent: only flags new contradictions not already in contradictions.md.

    Args:
        file_path: path to the file being checked (memory, CONTEXT.md, ADR, etc.)
        text: the claim text to verify
        project_hint: optional project ID to narrow search scope
    """
    flags: list[Flag] = []

    # Check if this claim is already flagged (idempotency)
    if _is_already_flagged(file_path, text):
        return flags

    # Find relevant project/docs, excluding self-matches
    candidates = find_candidates(text, project_hint=project_hint, exclude_path=file_path)
    if not candidates:
        return flags

    # Check each candidate
    for candidate in candidates[:3]:  # limit to top 3 to avoid exploding flag count
        if not candidate.file_path.exists():
            continue

        try:
            candidate_content = candidate.file_path.read_text(errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue

        # Judge the contradiction
        try:
            flag = judge_contradiction(text, candidate_content)
            if flag:
                flags.append(
                    Flag(
                        file_path=str(file_path),
                        text_excerpt=text[:200],
                        issue=flag.issue,
                        source="check_claim",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        verdict="contradiction",
                    )
                )
                break  # One flag per checked claim is enough
        except JudgeError as e:
            # Judge failed: append as "unreviewed" flag with the error
            flags.append(
                Flag(
                    file_path=str(file_path),
                    text_excerpt=text[:200],
                    issue=f"Judge failed to evaluate: {e}",
                    source="check_claim",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    verdict=None,  # unreviewed
                )
            )
            break

    return flags


def sweep(project_filter: str | None = None) -> list[Flag]:
    """Scan all memory files against their projects' docs for stale decisions.

    Report-only: writes to contradictions.md under a 'source: sweep' marker.
    Returns all found flags but does not modify memory/repo files.
    """
    flags: list[Flag] = []

    for memory_file in sorted(MEMORY_DIR.glob("*.md")):
        if memory_file.name == "MEMORY.md":
            continue

        try:
            content = memory_file.read_text(errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue

        # Extract project hint from filename if possible
        project_hint = memory_file.stem.lower().replace("_", "-")

        # Check the main body
        parts = content.split("---", 2)
        body = parts[2].strip() if len(parts) == 3 else content

        # Check for claims in this note, passing the project hint
        check_flags = check_claim(memory_file, body, project_hint=project_hint)
        for flag in check_flags:
            flag_with_source = Flag(
                file_path=flag.file_path,
                text_excerpt=flag.text_excerpt,
                issue=flag.issue,
                source="sweep",
                timestamp=flag.timestamp,
                verdict=flag.verdict,
            )
            flags.append(flag_with_source)

    return flags


def open_flags() -> list[Flag]:
    """Read unresolved flags from contradictions.md."""
    if not CONTRADICTIONS_FILE.exists():
        return []

    flags: list[Flag] = []
    content = CONTRADICTIONS_FILE.read_text()

    # Parse sections starting with ##
    for section in re.split(r"^## ", content, flags=re.MULTILINE)[1:]:
        lines = section.split("\n")
        if not lines:
            continue

        # First line is the date and issue
        header = lines[0]
        flag_dict = _parse_flag_header(header)
        if not flag_dict:
            continue

        # Check if it has checkboxes (unresolved if none are checked)
        rest = "\n".join(lines[1:])
        if not _is_resolved(rest):
            flags.append(
                Flag(
                    file_path=flag_dict.get("file_path", ""),
                    text_excerpt=flag_dict.get("text_excerpt", ""),
                    issue=header,
                    source=flag_dict.get("source", ""),
                    timestamp=flag_dict.get("timestamp", ""),
                    verdict=None,
                )
            )

    return flags


def _parse_flag_header(header: str) -> dict | None:
    """Parse a flag header line to extract metadata."""
    # Format: YYYY-MM-DD | source | file_path | issue
    parts = header.split(" | ", 3)
    if len(parts) < 2:
        return None

    return {
        "timestamp": parts[0],
        "source": parts[1] if len(parts) > 1 else "",
        "file_path": parts[2] if len(parts) > 2 else "",
        "text_excerpt": "",
    }


def _is_resolved(text: str) -> bool:
    """Check if a quarantine-style section has a checked box."""
    return bool(re.search(r"- \[x\]", text, re.IGNORECASE))


def _append_flag(flag: Flag) -> None:
    """Append a flag to contradictions.md in quarantine-style format.

    Uses file locking for concurrent-safe append: multiple processes can call
    this simultaneously without corrupting the file.

    If the judge has already determined a verdict (contradiction), auto-check
    the corresponding box. Unreviewed flags (verdict=None) have all boxes empty,
    waiting for human decision.
    """
    CONTRADICTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    issue_short = flag.issue[: min(len(flag.issue), 100)]

    block = (
        f"## {today} | {flag.source} | {flag.file_path}\n\n"
        f"{issue_short}\n\n"
    )
    if flag.text_excerpt:
        quoted = "\n".join(f"> {line}" for line in flag.text_excerpt.splitlines())
        block += f"**Claim:**\n{quoted}\n\n"

    # Auto-check the box for resolved verdicts; leave empty for unreviewed
    approve_box = "- [ ] approve (claim is stale but acceptable)\n"
    update_box = "- [ ] update: (update memory file with current truth)\n"
    contradiction_box = "- [ ] contradiction (claim vs reality disagree materially)\n"

    if flag.verdict == "contradiction":
        contradiction_box = "- [x] contradiction (claim vs reality disagree materially)\n"
    elif flag.verdict == "acceptable":
        approve_box = "- [x] approve (claim is stale but acceptable)\n"

    block += approve_box
    block += update_box
    block += contradiction_box

    # Use exclusive lock for concurrent-safe append
    lock_file = CONTRADICTIONS_FILE.parent / ".contradictions.lock"
    with open(lock_file, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            # Re-check for duplicate after acquiring lock
            if CONTRADICTIONS_FILE.exists():
                existing = CONTRADICTIONS_FILE.read_text()
                if flag.file_path in existing and flag.text_excerpt[:50] in existing:
                    return  # Already flagged
            else:
                existing = (
                    "# Contradictions\n\n"
                    "Potential stale decisions: documented claims that may contradict current system state.\n"
                    "For each item: check whether the claim is acceptable despite being dated, whether memory\n"
                    "needs updating, or whether this is a material contradiction that should block a design.\n\n"
                )

            # Append the new flag
            CONTRADICTIONS_FILE.write_text(existing.rstrip() + "\n\n---\n" + block)
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sweep", help="Scan all memory against repo docs")
    sub.add_parser("open", help="List unresolved flags")
    sub.add_parser("check")
    args = ap.parse_args()

    if args.cmd == "sweep":
        found = sweep()
        for f in found:
            _append_flag(f)
        print(f"Found {len(found)} potential contradiction(s)")
    elif args.cmd == "open":
        open_list = open_flags()
        for f in open_list:
            print(f"{f.file_path}: {f.issue}")
