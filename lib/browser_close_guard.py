#!/usr/bin/env python3
"""Guard for Playwright browser cleanup (G-Eskayo/marvin#415).

Regex-over-source guard: scans test files for Playwright browser launch patterns
that lack proper cleanup. Two specific patterns that hide bugs:
1. browser = await browserType.launch(...) without a paired await close()
2. Bare (unassigned) .launch( calls
3. channel: 'chrome' with no explanation comment (often a test-only override)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Generator


def _strip_comments(text: str) -> str:
    """Strip // comments from a line, respecting strings. Returns the line without comments."""
    in_string = False
    string_char = None
    result = []
    i = 0
    while i < len(text):
        char = text[i]
        if char in ('"', "'", "`") and (i == 0 or text[i - 1] != "\\"):
            if not in_string:
                in_string = True
                string_char = char
            elif char == string_char:
                in_string = False
                string_char = None
            result.append(char)
        elif char == "/" and i + 1 < len(text) and text[i + 1] == "/" and not in_string:
            break  # Found comment start, stop processing
        else:
            result.append(char)
        i += 1
    return "".join(result)


def _is_in_string(line: str, match_pos: int) -> bool:
    """Check if a position in the line is inside a string."""
    in_string = False
    string_char = None
    for i in range(match_pos):
        char = line[i]
        if char in ('"', "'", "`") and (i == 0 or line[i - 1] != "\\"):
            if not in_string:
                in_string = True
                string_char = char
            elif char == string_char:
                in_string = False
                string_char = None
    return in_string


def check_source(
    text: str, filename: str = "<source>"
) -> list[tuple[int, str, str]]:
    """Scan source code for Playwright browser cleanup violations.
    Returns list of (line_number, violation_type, message)."""
    violations: list[tuple[int, str, str]] = []
    lines = text.splitlines()

    for i, line in enumerate(lines, start=1):
        # Strip comments for most checks, but check channel: 'chrome' on original line
        line_no_comments = _strip_comments(line)

        # Check 1: .launch( without proper await close() on same statement or nearby
        launch_match_iter = re.finditer(r"\.launch\s*\(", line_no_comments)
        for match in launch_match_iter:
            # Skip if inside a string
            if _is_in_string(line_no_comments, match.start()):
                continue

            # Extract variable name if this is an assignment
            launch_var_match = re.search(r"(?:const\s+|let\s+|var\s+)?(\w+)\s*=\s*await\s+\w+\.launch\s*\(", line_no_comments)
            bare_launch = re.search(r"^\s*await\s+\w+\.launch\s*\(", line_no_comments)

            if bare_launch:
                # Bare launch without assignment
                violations.append(
                    (i, "browser-launch-unassigned", f"`.launch(` on line {i} is unassigned (bare call)")
                )
            elif launch_var_match:
                var_name = launch_var_match.group(1)
                # Check for close() on same line first
                if f"{var_name}.close()" in line_no_comments:
                    continue
                # Check next few lines for awaited close
                found_close = False
                for j in range(i, min(i + 10, len(lines) + 1)):
                    next_line = lines[j - 1] if j <= len(lines) else ""
                    next_line_no_comments = _strip_comments(next_line)
                    if f"await {var_name}.close()" in next_line_no_comments:
                        found_close = True
                        break
                    if f"await {var_name}.close(" in next_line_no_comments:
                        found_close = True
                        break

                if not found_close:
                    violations.append(
                        (i, "browser-launch-cleanup", f"`.launch(` on line {i} lacks paired `await close()`")
                    )
            else:
                # Non-awaited launch (e.g., assignment without await)
                if ".launch(" in line_no_comments and "await" not in line_no_comments:
                    violations.append(
                        (i, "browser-launch-cleanup", f"`.launch(` on line {i} is not awaited")
                    )

        # Check 2: channel: 'chrome' without a // comment on original line (not stripped)
        if re.search(r"channel\s*:\s*['\"]chrome['\"]", line):
            # Check original line for comment
            if "//" not in line:
                # Check next line for comment, but on original (non-stripped) version
                has_next_comment = False
                if i < len(lines) and "//" in lines[i]:
                    has_next_comment = True

                if not has_next_comment:
                    violations.append(
                        (i, "channel-chrome-no-comment", f"`channel: 'chrome'` on line {i} needs a `//` explanation comment")
                    )

    return violations


def check_file(path: Path) -> list[tuple[int, str, str]]:
    """Check a single file for violations. Returns list of (line_number, type, message)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return check_source(text, str(path))


def check_repo(root: Path | None = None) -> dict[str, list[tuple[int, str, str]]]:
    """Scan all .test.mjs files under root for violations.
    Returns dict mapping file paths (relative to root) to violations."""
    if root is None:
        root = Path.cwd()
    root = Path(root).resolve()

    violations_by_file: dict[str, list[tuple[int, str, str]]] = {}

    # Scan all .test.mjs files, excluding node_modules
    for test_file in root.glob("**/*.test.mjs"):
        # Skip node_modules
        if "node_modules" in test_file.parts:
            continue

        violations = check_file(test_file)
        if violations:
            rel_path = str(test_file.relative_to(root))
            violations_by_file[rel_path] = violations

    return violations_by_file


if __name__ == "__main__":
    violations = check_repo()

    if not violations:
        print("✓ No browser cleanup violations found.")
        sys.exit(0)

    print(f"✗ Found {sum(len(v) for v in violations.values())} violation(s):")
    for filepath, file_violations in sorted(violations.items()):
        print(f"\n{filepath}:")
        for line_num, violation_type, message in file_violations:
            print(f"  Line {line_num} [{violation_type}]: {message}")

    sys.exit(1)
