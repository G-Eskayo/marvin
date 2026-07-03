#!/usr/bin/env python3
"""
tag-files.py — one-time migration.
Inserts tags: (and calls: where defined) into frontmatter of all
skill SKILL.md files and memory .md files that don't have them yet.
"""
import re, sys
from pathlib import Path

HOME = Path.home()

SKILL_TAGS = {
    "caveman":                      {"tags": ["intent:communicate", "intent:compress", "type:skill"]},
    "creative":                     {"tags": ["intent:create", "intent:ideate", "intent:brainstorm", "type:skill"]},
    "diagnose":                     {"tags": ["domain:debugging", "intent:debug", "intent:fix", "intent:diagnose", "type:skill"]},
    "grill-me":                     {"tags": ["intent:plan", "intent:challenge", "intent:design", "intent:stress-test", "type:skill"]},
    "grill-with-docs":              {"tags": ["intent:plan", "intent:challenge", "domain:architecture", "intent:design", "type:skill"],
                                     "calls": ["grill-me", "lexicon"]},
    "handoff":                      {"tags": ["intent:handoff", "intent:context-switch", "intent:document", "type:skill"]},
    "improve-codebase-architecture":{"tags": ["domain:architecture", "intent:refactor", "intent:improve", "intent:review", "type:skill"],
                                     "calls": ["zoom-out"]},
    "index":                        {"tags": ["intent:retrieve", "intent:index", "intent:load", "type:skill"]},
    "lexicon":                      {"tags": ["domain:language", "intent:define", "intent:vocabulary", "intent:document", "type:skill"]},
    "prototype":                    {"tags": ["intent:prototype", "intent:design", "intent:mockup", "intent:explore", "type:skill"]},
    "research":                     {"tags": ["intent:research", "intent:investigate", "intent:evaluate", "intent:learn", "type:skill"]},
    "self-improve":                 {"tags": ["intent:improve", "intent:learn", "intent:codify", "intent:meta", "type:skill"],
                                     "calls": ["lexicon", "write-a-skill"]},
    "architecture-review":          {"tags": ["intent:optimize", "intent:review", "intent:meta", "type:skill"]},
    "setup-matt-pocock-skills":     {"tags": ["intent:setup", "intent:initialize", "intent:configure", "type:skill"]},
    "tdd":                          {"tags": ["domain:testing", "intent:test", "intent:tdd", "intent:build", "type:skill"],
                                     "calls": ["diagnose"]},
    "to-issues":                    {"tags": ["intent:plan", "intent:issues", "intent:breakdown", "type:skill"]},
    "to-prd":                       {"tags": ["intent:plan", "intent:prd", "intent:document", "type:skill"],
                                     "calls": ["to-issues"]},
    "triage":                       {"tags": ["intent:triage", "intent:issues", "intent:review", "type:skill"],
                                     "calls": ["to-issues"]},
    "write-a-skill":                {"tags": ["intent:create", "intent:skill", "intent:codify", "type:skill"]},
    "zoom-out":                     {"tags": ["domain:architecture", "intent:understand", "intent:explore", "intent:map", "type:skill"]},
}

MEMORY_TAGS = {
    "reference_mcp": {
        "tags": ["domain:mcp", "domain:auth", "domain:security", "domain:protocol",
                 "intent:build", "intent:debug", "intent:learn", "type:knowledge"]
    },
    "project_ai_development_theory": {
        "tags": ["domain:ai-theory", "domain:psychology", "intent:research", "intent:learn", "type:knowledge"]
    },
    "user_profile": {
        "tags": ["type:memory-user", "intent:personalize"]
    },
    "feedback_testing": {
        "tags": ["domain:testing", "intent:guide", "type:memory-feedback"]
    },
}


def insert_tags(text: str, tags: list, calls: list = None) -> str:
    """Insert tags (and calls) into YAML frontmatter before the closing ---."""
    # Find the closing --- of the frontmatter
    if not text.startswith("---"):
        return text
    close = text.find("\n---", 3)
    if close == -1:
        return text

    fm_section = text[:close]
    rest = text[close:]  # starts with \n---

    # Already has tags? skip
    if re.search(r'^tags:', fm_section, re.MULTILINE):
        return text

    tag_str = "[" + ", ".join(tags) + "]"
    insertion = f"\ntags: {tag_str}"
    if calls:
        insertion += "\ncalls: [" + ", ".join(calls) + "]"

    return fm_section + insertion + rest


def patch_file(path: Path, tags: list, calls: list = None):
    original = path.read_text(encoding="utf-8")
    patched = insert_tags(original, tags, calls)
    if patched == original:
        print(f"  SKIP (already tagged): {path}")
        return
    path.write_text(patched, encoding="utf-8")
    print(f"  TAGGED: {path}")


def main():
    # Patch skill files
    skills_dir = HOME / ".agents" / "skills"
    for skill_name, meta in SKILL_TAGS.items():
        skill_file = skills_dir / skill_name / "SKILL.md"
        if not skill_file.exists():
            print(f"  MISSING: {skill_file}", file=sys.stderr)
            continue
        patch_file(skill_file, meta["tags"], meta.get("calls"))

    # Patch memory files
    projects_dir = HOME / ".claude" / "projects"
    if projects_dir.exists():
        for project_dir in projects_dir.iterdir():
            mem_dir = project_dir / "memory"
            if not mem_dir.exists():
                continue
            for stem, meta in MEMORY_TAGS.items():
                mem_file = mem_dir / f"{stem}.md"
                if not mem_file.exists():
                    continue
                patch_file(mem_file, meta["tags"], meta.get("calls"))

    print("Done.")


if __name__ == "__main__":
    main()
