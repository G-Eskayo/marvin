#!/usr/bin/env python3
"""Generate docs/skills.md from the skills' own SKILL.md frontmatter, so the list in the docs cannot drift from the skills.

    ~/.agents/venv/bin/python lib/skill_index.py            # writes docs/skills.md
    ~/.agents/venv/bin/python lib/skill_index.py --check    # exit 1 if docs/skills.md is out of date (for CI / hooks)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "skills.md"

GROUPS = [
    ("Quality and debugging", ["diagnose", "audit", "tdd", "qa-agent", "grill-with-docs", "grill-me", "improve-codebase-architecture", "safety-monitor"]),
    ("Research and reading", ["research", "paper-dive", "research-colony", "zoom-out"]),
    ("Writing and creating", ["readme", "writing-style", "portfolio-page", "creative", "prototype", "resume-tailor"]),
    ("Continuity and self-improvement", ["handoff", "index", "self-improve", "architecture-review", "improve", "lexicon", "write-a-skill", "variable-tracker"]),
    ("Project work and routing", ["setup-matt-pocock-skills", "triage", "to-issues", "to-prd", "to-tasklist", "route", "caveman"]),
]


def frontmatter(path: Path) -> dict:
    text = path.read_text()
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    out: dict[str, str] = {}
    if not m:
        return out
    key = None
    for line in m.group(1).splitlines():
        kv = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if kv:
            key, val = kv.group(1), kv.group(2).strip()
            out[key] = "" if val in (">", "|", ">-", "|-") else val.strip("\"'")
        elif key and line.strip():
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


def one_line(desc: str, limit: int = 230) -> str:
    desc = re.sub(r"\s+", " ", desc).strip()
    first = re.split(r"(?<=[.!?])\s", desc)[0]
    first = first if len(first) <= limit else desc[:limit].rsplit(" ", 1)[0] + "…"
    return first.replace("|", "\\|")


def build(root: Path = ROOT) -> str:
    skills = {p.parent.name: frontmatter(p) for p in sorted((root / "skills").glob("*/SKILL.md"))}
    placed = {n for _, names in GROUPS for n in names}
    groups = GROUPS + ([("Other", sorted(set(skills) - placed))] if set(skills) - placed else [])
    lines = ["# Skills", "",
             f"{len(skills)} skills. Generated from each skill's own `SKILL.md` by `lib/skill_index.py`: edit the skill, not this file.", ""]
    for title, names in groups:
        names = [n for n in names if n in skills]
        if not names:
            continue
        lines += [f"## {title}", "", "| Skill | What it does and when it fires |", "|---|---|"]
        for n in names:
            lines.append(f"| [`{n}`](../skills/{n}/SKILL.md) | {one_line(skills[n].get('description', ''))} |")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    text = build()
    if "--check" in sys.argv:
        sys.exit(0 if OUT.exists() and OUT.read_text() == text else 1)
    OUT.write_text(text)
    print(f"wrote {OUT} ({text.count(chr(10))} lines)")


if __name__ == "__main__":
    main()
