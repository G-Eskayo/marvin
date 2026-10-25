#!/usr/bin/env python3
"""Guard against browser resource leaks in test files.

Detects uses of chromium.launch() without corresponding awaited browser.close()
calls, which leaves Chromium processes running and accumulates over many test
runs (the repeated hangs on #304/#305).

This is a scanning tool, not a runtime guard. Run check_repo() to scan the
current project or check_file() on a specific test file.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def _strip_comments(line: str) -> str:
    """Remove comments from a line, respecting quoted strings."""
    result = []
    in_string = False
    quote_char = None
    i = 0
    while i < len(line):
        ch = line[i]
        if ch in ('"', "'") and (i == 0 or line[i - 1] != "\\"):
            if not in_string:
                in_string = True
                quote_char = ch
            elif ch == quote_char:
                in_string = False
            result.append(ch)
        elif ch == "/" and not in_string and i + 1 < len(line) and line[i + 1] == "/":
            break
        else:
            result.append(ch)
        i += 1
    return "".join(result)


LAUNCH_RE = re.compile(r"(?:(?:const|let|var)\s+)?(\w+)\s*=\s*(?:await\s+)?chromium\.launch\(")
CHANNEL_RE = re.compile(r"channel\s*:\s*['\"]chrome['\"]")


def check_file(filepath: Path | str) -> list[str]:
    """Check a single .test.mjs file for launch/close violations.

    Returns a list of violation messages. A bare launch() without assignment
    is flagged immediately. For assigned launches, subsequent lines are scanned
    for both a close() call and an awaited close() call, and violations are
    flagged if found. Also checks for chromium.launch({ channel: 'chrome' }).
    """
    filepath = Path(filepath)
    if filepath.suffix != ".mjs":
        return []

    try:
        lines = filepath.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return []

    violations = []
    launches = {}

    # Pass 1: Check for launch/close violations
    for i, line in enumerate(lines, 1):
        stripped = _strip_comments(line)

        # Skip whole-line comments: raw line is not blank but stripped result is
        if line.strip() and not stripped.strip():
            continue

        # Check for bare chromium.launch() without assignment
        if re.search(r"chromium\.launch\(", stripped) and not re.search(LAUNCH_RE, stripped):
            violations.append(f"{filepath}:{i}: bare chromium.launch() without variable assignment")
            continue

        # Track assigned launches
        match = re.search(LAUNCH_RE, stripped)
        if match:
            var_name = match.group(1)
            launches[var_name] = i

    # For each launched variable, scan the rest of the file for close()
    for var_name, launch_line in launches.items():
        has_close = False
        has_awaited_close = False

        for i in range(launch_line, len(lines)):
            line = lines[i]
            stripped = _strip_comments(line)

            if re.search(rf"(?:await\s+)?{re.escape(var_name)}\??\.close\(\)", stripped):
                has_close = True
                if re.search(rf"await\s+{re.escape(var_name)}\??\.close\(\)", stripped):
                    has_awaited_close = True
                    break

        if not has_close:
            violations.append(f"{filepath}: chromium.launch() assigned to `{var_name}` (line {launch_line}) has no close() call")
        elif has_close and not has_awaited_close:
            violations.append(f"{filepath}: `{var_name}.close()` is not awaited (line {launch_line})")

    # Pass 2: Check for channel: 'chrome' without comment
    for i, line in enumerate(lines, 1):
        stripped = _strip_comments(line)

        # Skip whole-line comments
        if line.strip() and not stripped.strip():
            continue

        if CHANNEL_RE.search(stripped):
            # Check if this line has an inline comment (contains // after the match)
            has_inline_comment = "//" in line[line.find(stripped):] if stripped in line else False
            # Or if the previous non-comment line is itself a comment
            prev_is_comment = False
            for j in range(i - 2, -1, -1):
                prev_stripped = _strip_comments(lines[j])
                if lines[j].strip() and not prev_stripped.strip():
                    prev_is_comment = True
                    break
                elif prev_stripped.strip():
                    break

            if not has_inline_comment and not prev_is_comment:
                violations.append(f"{filepath}:{i}: channel: 'chrome' without comment")

    return violations


def check_repo(glob_pattern: str = "**/*.test.mjs") -> list[str]:
    """Scan all test files in the current repo matching the glob pattern.

    Excludes node_modules. Returns a flat list of all violations found.
    """
    violations = []
    for filepath in Path(".").glob(glob_pattern):
        if "node_modules" in filepath.parts:
            continue
        violations.extend(check_file(filepath))
    return violations


if __name__ == "__main__":
    violations = check_repo()
    if violations:
        for v in violations:
            print(v)
        sys.exit(1)
    else:
        print("All browser.close() patterns are correct.")
        sys.exit(0)
