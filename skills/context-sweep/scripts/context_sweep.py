#!/usr/bin/env python3
"""Core logic for context-sweep: enumerate context files and chunk them.

Importable and testable independent of subprocess machinery. Run via:
    ~/.agents/venv/bin/python context_sweep.py
"""
from __future__ import annotations
from pathlib import Path


def enumerate_context_files(home_dir: Path | None = None) -> list[Path]:
    """Walk the context file database: skills, docs, CLAUDE.md variants,
    handoffs, and per-project memory. Deterministic sort by path string.
    Excludes suggestions.md and improvement-queue.md (don't review output).
    Accepts optional home_dir for testing."""
    files = []
    home = home_dir or Path.home()

    # Skill markdown files
    skills_dir = home / ".agents" / "skills"
    if skills_dir.exists():
        for md_file in skills_dir.rglob("*.md"):
            if md_file.name != "SKILL.md":
                continue
            files.append(md_file)

    # Docs (ADRs, handbooks, etc.)
    docs_dir = home / ".agents" / "docs"
    if docs_dir.exists():
        for md_file in docs_dir.rglob("*.md"):
            files.append(md_file)

    # Central context
    context_md = home / ".agents" / "CONTEXT.md"
    if context_md.exists():
        files.append(context_md)

    # Global user config and lexicon
    claude_md = home / ".claude" / "CLAUDE.md"
    if claude_md.exists():
        files.append(claude_md)

    lexicon_md = home / ".claude" / "lexicon.md"
    if lexicon_md.exists():
        files.append(lexicon_md)

    # Handoffs (saved context switches)
    handoffs_dir = home / ".claude" / "handoffs"
    if handoffs_dir.exists():
        for md_file in sorted(handoffs_dir.glob("*.md")):
            files.append(md_file)

    # Per-project memory
    projects_dir = home / ".claude" / "projects"
    if projects_dir.exists():
        for memory_md in projects_dir.rglob("memory/*.md"):
            files.append(memory_md)

    # Project-local CLAUDE.md (in current working dir or git root)
    cwd = Path.cwd()
    project_claude = cwd / "CLAUDE.md"
    if project_claude.exists():
        files.append(project_claude)

    # Project README and retrospective
    for name in ["README.md", "retrospective-log.md"]:
        md_file = cwd / name
        if md_file.exists():
            files.append(md_file)

    # Deduplicate and sort deterministically
    files = list(dict.fromkeys(files))  # preserve order, remove dupes
    files.sort(key=lambda f: str(f))

    return files


def next_chunk(files: list[Path], cursor_index: int, chunk_size: int = 5) -> tuple[list[Path], int]:
    """Return (chunk, new_index) — a slice of `chunk_size` files at cursor
    position, and the next index to use. Wraps modulo len(files)."""
    if not files:
        return [], 0

    start = cursor_index % len(files)
    end = min(start + chunk_size, len(files))
    chunk = files[start:end]

    # If we wrap, include the beginning of the list
    if end < start + chunk_size:
        remaining = chunk_size - len(chunk)
        chunk.extend(files[:remaining])

    new_index = (start + chunk_size) % len(files)
    return chunk, new_index
