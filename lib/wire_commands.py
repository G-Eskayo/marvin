#!/usr/bin/env python3
"""Wire all non-library skills from ~/.agents/skills as invocable commands.

Creates ~/.claude/commands/<name>.md for each skill, following the pattern
from existing commands like diagnose, paper-dive, etc. The command file
allows slash-command invocation in Claude Code."""

import re
import sys
from pathlib import Path


def parse_skill_name(skill_path: Path) -> str | None:
    """Extract skill name from SKILL.md frontmatter."""
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return None

    try:
        content = skill_md.read_text()
    except Exception:
        return None

    # Parse frontmatter
    if not content.startswith("---"):
        return None

    end = content.find("\n---", 3)
    if end == -1:
        return None

    fm = content[3:end]
    m = re.search(r"^name:\s*(.+)$", fm, re.MULTILINE)
    return m.group(1).strip() if m else None


def is_library_skill(skill_path: Path) -> bool:
    """Check if skill is tagged as type:library."""
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return False

    try:
        content = skill_md.read_text()
    except Exception:
        return False

    if not content.startswith("---"):
        return False

    end = content.find("\n---", 3)
    if end == -1:
        return False

    fm = content[3:end]
    return "type:library" in fm


def wire_commands(skills_dir: Path, commands_dir: Path) -> int:
    """Wire all non-library skills as commands.

    Returns count of commands created."""
    commands_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    for skill_path in sorted(skills_dir.iterdir()):
        if not skill_path.is_dir() or skill_path.name.startswith("_"):
            continue

        skill_name = parse_skill_name(skill_path)
        if not skill_name:
            continue

        if is_library_skill(skill_path):
            continue

        # Create the command file (simple wrapper)
        command_path = commands_dir / f"{skill_name}.md"
        # Command file format: slash command that invokes the skill
        command_content = f"/{skill_name}\n"

        try:
            command_path.write_text(command_content)
            count += 1
        except Exception as e:
            print(f"Failed to create command for {skill_name}: {e}", file=sys.stderr)

    return count


if __name__ == "__main__":
    skills_dir = Path.home() / ".agents" / "skills"
    commands_dir = Path.home() / ".claude" / "commands"

    count = wire_commands(skills_dir, commands_dir)
    print(f"Wired {count} skills as commands")
    sys.exit(0 if count > 0 else 1)
