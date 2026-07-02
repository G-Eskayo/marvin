#!/usr/bin/env python3
"""
rebuild-manifest.py
Source of truth: frontmatter tags in each skill/memory file.
Regenerates ~/.claude/manifest.json (v2.0 flat index).
Run directly or via PostToolUse hook.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
MANIFEST_PATH = HOME / ".claude" / "manifest.json"
SKILLS_DIR = HOME / ".agents" / "skills"

# Scan all memory/ dirs under ~/.claude/projects/ that contain a MEMORY.md
PROJECTS_DIR = HOME / ".claude" / "projects"

ALWAYS = [
    "~/.claude/CLAUDE.md",
    "~/.claude/lexicon.md",
]

ON_SESSION_START = [
    "~/.claude/handoffs/",
    "~/.claude/suggestions.md",
]

TAG_PATTERN = re.compile(r'^[a-z][a-z0-9-]*:[a-z][a-z0-9-]*$')


def _hook_should_skip() -> bool:
    """When invoked as a PostToolUse hook (JSON payload piped on stdin),
    only rebuild if the edited file actually affects the manifest's output
    — a SKILL.md or a project memory .md file. Found 2026-07-02: unlike the
    other three PostToolUse hooks on the same Write|Edit matcher
    (emit-resume-prompt.py, qa_session_capture.py, improvement_sweep.py,
    all of which filter to their relevant path before doing real work),
    this one had no filtering at all — full rebuild + chained embeddings
    rebuild on every single Write/Edit anywhere in any project.
    Returns False (never skip) when run directly with no piped JSON, so
    `python rebuild-manifest.py` from the CLI still always does a full
    rebuild, matching this script's documented dual-mode use."""
    if sys.stdin.isatty():
        return False
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return False  # couldn't parse — rebuild anyway, safer than silently skipping

    if payload.get("tool_name", "") not in ("Write", "Edit", "MultiEdit"):
        return True
    fp = (payload.get("tool_input") or {}).get("file_path", "")
    if not fp:
        return True

    p = Path(fp)
    try:
        if p.name == "SKILL.md" and SKILLS_DIR.resolve() in [d.resolve() for d in p.parents]:
            return False
        if (p.suffix.lower() == ".md" and p.parent.name == "memory"
                and PROJECTS_DIR.resolve() in [d.resolve() for d in p.parents]):
            return False
    except Exception:
        return False  # path resolution failed — rebuild anyway, don't silently skip

    return True


def find_memory_dirs() -> list[Path]:
    dirs = []
    if PROJECTS_DIR.exists():
        for project_dir in PROJECTS_DIR.iterdir():
            mem_dir = project_dir / "memory"
            if mem_dir.exists() and (mem_dir / "MEMORY.md").exists():
                dirs.append(mem_dir)
    return dirs


def _read_inline_array(raw: str) -> list[str]:
    return [v.strip().strip("\"'") for v in raw.split(",")]


def _read_block_list(lines: list[str], start: int) -> tuple[list[str], int]:
    items, j = [], start
    while j < len(lines) and re.match(r'^\s+-\s+', lines[j]):
        items.append(re.sub(r'^\s+-\s+', '', lines[j]).strip().strip("\"'"))
        j += 1
    return items, j


def parse_frontmatter(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"  WARN: cannot read {path}: {e}", file=sys.stderr)
        return {}

    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}

    result: dict = {}
    lines = text[3:end].strip().split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        m = re.match(r'^([\w-]+):\s*\[(.+)\]\s*$', line)
        if m:
            result[m.group(1)] = _read_inline_array(m.group(2))
            i += 1
            continue
        m = re.match(r'^([\w-]+):\s*$', line)
        if m:
            result[m.group(1)], i = _read_block_list(lines, i + 1)
            continue
        m = re.match(r'^([\w-]+):\s+(.+)$', line)
        if m:
            items, i = _read_block_list(lines, i + 1)
            result[m.group(1)] = items if items else m.group(2).strip()
            continue
        i += 1

    return result


def normalize_tags(tags: list, source: str) -> list:
    out = []
    for tag in tags:
        if isinstance(tag, str):
            tag = tag.lower().replace(" ", "-")
            if not TAG_PATTERN.match(tag):
                print(f"  WARN: invalid tag '{tag}' in {source} — expected namespace:value", file=sys.stderr)
            out.append(tag)
    return out


def to_relative(path: Path) -> str:
    return "~/" + str(path.relative_to(HOME))


def scan_skills() -> list[dict]:
    entries = []
    if not SKILLS_DIR.exists():
        return entries

    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue

        fm = parse_frontmatter(skill_file)
        raw_tags = fm.get("tags", [])
        if not raw_tags:
            continue  # untagged — skip silently

        if isinstance(raw_tags, str):
            raw_tags = [raw_tags]

        raw_calls = fm.get("calls", [])
        if isinstance(raw_calls, str):
            raw_calls = [raw_calls]

        tags = normalize_tags(raw_tags, str(skill_file))
        entry = {
            "name": fm.get("name", skill_dir.name),
            "path": f"~/.agents/skills/{skill_dir.name}/SKILL.md",
            "tags": tags,
        }
        if raw_calls:
            entry["calls"] = raw_calls
        entries.append(entry)

    return entries


def scan_memory() -> list[dict]:
    entries = []
    for mem_dir in find_memory_dirs():
        for mem_file in sorted(mem_dir.glob("*.md")):
            if mem_file.name == "MEMORY.md":
                continue

            fm = parse_frontmatter(mem_file)
            raw_tags = fm.get("tags", [])
            if not raw_tags:
                continue

            if isinstance(raw_tags, str):
                raw_tags = [raw_tags]

            raw_calls = fm.get("calls", [])
            if isinstance(raw_calls, str):
                raw_calls = [raw_calls]

            tags = normalize_tags(raw_tags, str(mem_file))
            entry = {
                "name": fm.get("name", mem_file.stem),
                "path": to_relative(mem_file),
                "tags": tags,
            }
            if raw_calls:
                entry["calls"] = raw_calls
            entries.append(entry)

    return entries


def main():
    if _hook_should_skip():
        return

    print("Rebuilding manifest.json...", file=sys.stderr)

    index = scan_skills() + scan_memory()

    manifest = {
        "_version": "2.0",
        "_generated": datetime.now(timezone.utc).isoformat(),
        "_comment": "Auto-generated from frontmatter. Run rebuild-manifest.py to regenerate. Do not edit by hand.",
        "always": ALWAYS,
        "on_session_start": ON_SESSION_START,
        "index": index,
    }

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")

    skills = [e for e in index if "type:skill" in e["tags"]]
    knowledge = [e for e in index if "type:knowledge" in e["tags"]]
    print(f"  Done. {len(index)} entries → {MANIFEST_PATH}", file=sys.stderr)
    print(f"  Skills: {len(skills)}  Knowledge: {len(knowledge)}", file=sys.stderr)

    # Chain: rebuild embeddings after manifest is up to date
    embeddings_script = Path(__file__).parent / "rebuild-embeddings.py"
    if embeddings_script.exists():
        subprocess.run([sys.executable, str(embeddings_script)], check=False)

    # Chain: regenerate the brain-map graph — this hook already correctly
    # detects "a SKILL.md or memory file changed" (see _hook_should_skip),
    # so it's the natural trigger rather than a dedicated 6th hook. A brand
    # new skill still needs a manual category added to brain-map/
    # enrichment.json's skill_categories (generate.py warns and omits it
    # otherwise) — that's a deliberate judgment call, not something to guess.
    brainmap_script = Path.home() / ".agents" / "brain-map" / "generate.py"
    if brainmap_script.exists():
        subprocess.run([sys.executable, str(brainmap_script)], check=False)


if __name__ == "__main__":
    main()
