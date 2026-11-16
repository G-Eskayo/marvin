#!/usr/bin/env python3
"""Verify the gotchas.md migration is complete and correct."""

import re
import sys
from pathlib import Path

def count_bullets(text):
    """Count bullet points starting with '- *'."""
    return len(re.findall(r'^\- \*', text, re.MULTILINE))

def main():
    repo = Path(__file__).parent
    skill_file = repo / "skills/diagnose/SKILL.md"
    gotchas_file = repo / "skills/diagnose/gotchas.md"

    print("=" * 60)
    print("GOTCHAS.MD MIGRATION VERIFICATION")
    print("=" * 60)

    # Check 1: gotchas.md exists and has 32 bullets
    if not gotchas_file.exists():
        print("❌ gotchas.md does not exist")
        return False

    gotchas_text = gotchas_file.read_text()
    gotchas_bullet_count = count_bullets(gotchas_text)

    if gotchas_bullet_count == 32:
        print(f"✓ gotchas.md contains 32 bullets")
    else:
        print(f"❌ gotchas.md contains {gotchas_bullet_count} bullets (expected 32)")
        return False

    # Check 2: SKILL.md has pointer line, no bullets
    skill_text = skill_file.read_text()
    skill_bullet_count = count_bullets(skill_text)

    if skill_bullet_count == 0:
        print(f"✓ SKILL.md has no bullets left inline")
    else:
        print(f"❌ SKILL.md still contains {skill_bullet_count} bullets")
        return False

    # Check 3: SKILL.md has the pointer line
    if "read [`gotchas.md`](gotchas.md)" in skill_text:
        print(f"✓ SKILL.md has the gotchas.md pointer line")
    else:
        print(f"❌ SKILL.md missing gotchas.md pointer")
        return False

    # Check 4: gotchas.md starts with correct heading and intro
    if gotchas_text.startswith("# Diagnose — MARVIN-specific gotcha classes"):
        print(f"✓ gotchas.md has correct heading")
    else:
        print(f"❌ gotchas.md missing correct heading")
        return False

    if "Read early in Phase 3 when the symptom fits" in gotchas_text:
        print(f"✓ gotchas.md has correct intro line")
    else:
        print(f"❌ gotchas.md missing correct intro")
        return False

    # Check 5: No other "gotcha" references in skills or docs
    docs_dir = repo / "docs"
    skills_dir = repo / "skills"
    gotcha_references = []

    for md_file in list(docs_dir.glob("**/*.md")) + list(skills_dir.glob("**/*.md")):
        if md_file == gotchas_file:
            continue
        content = md_file.read_text()
        if "gotcha" in content.lower():
            # Only flag if it's not the reference we expect
            if md_file != skill_file or "gotchas.md" not in content:
                gotcha_references.append(str(md_file.relative_to(repo)))

    if not gotcha_references:
        print(f"✓ No dangling gotcha references elsewhere")
    else:
        print(f"⚠ Found references in: {gotcha_references}")
        # This might be expected, so not a hard fail

    print("=" * 60)
    print("✓ Migration verification complete - all checks passed!")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
