#!/usr/bin/env python3
"""One-time check (2026-07-07 only — see com.marvin.verify-digest-fix.plist)
confirming the 2026-07-06 fix to daily_digest.py / research_digest.py
(--disallowedTools Write,Edit, blocking the confused self-write-permission
narration bug) held up on a real unattended scheduled run, not just the
manual test it was verified with at the time.

Deliberately a plain scripted check, not an LLM call — "does this file
contain a known failure string" doesn't need agentic judgment, and a
scripted check can't itself fall prey to the same class of bug it's
checking for.

Deletes itself and its launchd job after running once, since this check
has no reason to exist past 2026-07-07.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
CHECK_DATE = "2026-07-07"
LAPTOP_HOST = "c02f52gpq05ps-macbook-pro"

FAILURE_SIGNATURES = (
    "claude call failed",
    "don't have permission",
    "protected path",
    "Quarantined by safety-monitor",
)


def ssh_cat(host: str, path: str) -> str | None:
    try:
        proc = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", host, f"cat {path}"],
            capture_output=True, text=True, timeout=15,
        )
        return proc.stdout if proc.returncode == 0 else None
    except Exception:
        return None


def check_content(label: str, content: str | None) -> str:
    if content is None:
        return f"MISSING — {label} not found"
    hit = next((sig for sig in FAILURE_SIGNATURES if sig in content), None)
    if hit:
        return f"FAIL — {label} contains failure signature: \"{hit}\""
    return f"PASS — {label} looks like real content ({len(content)} chars)"


def tail_log(path: Path, lines: int = 15) -> str:
    if not path.exists():
        return "(no error log)"
    text = path.read_text(errors="ignore").strip()
    return "(empty)" if not text else "\n".join(text.splitlines()[-lines:])


def main() -> None:
    results = []

    results.append(check_content(
        "Mac Mini daily-digest",
        (CLAUDE_DIR / "daily-digest" / f"{CHECK_DATE}.md").read_text() if (CLAUDE_DIR / "daily-digest" / f"{CHECK_DATE}.md").exists() else None,
    ))
    results.append(check_content(
        "Mac Mini research-digest",
        (CLAUDE_DIR / "research-digest" / f"{CHECK_DATE}.md").read_text() if (CLAUDE_DIR / "research-digest" / f"{CHECK_DATE}.md").exists() else None,
    ))
    results.append(check_content(
        "Mac Mini merged daily-digest",
        (CLAUDE_DIR / "daily-digest" / f"{CHECK_DATE}-merged.md").read_text() if (CLAUDE_DIR / "daily-digest" / f"{CHECK_DATE}-merged.md").exists() else None,
    ))
    results.append(check_content(
        "Mac Mini merged research-digest",
        (CLAUDE_DIR / "research-digest" / f"{CHECK_DATE}-merged.md").read_text() if (CLAUDE_DIR / "research-digest" / f"{CHECK_DATE}-merged.md").exists() else None,
    ))
    results.append(check_content(
        "laptop daily-digest",
        ssh_cat(LAPTOP_HOST, f"~/.claude/daily-digest/{CHECK_DATE}.md"),
    ))
    results.append(check_content(
        "laptop research-digest",
        ssh_cat(LAPTOP_HOST, f"~/.claude/research-digest/{CHECK_DATE}.md"),
    ))

    error_logs = [
        ("Mac Mini daily-digest-error.log", tail_log(CLAUDE_DIR / "logs" / "daily-digest-error.log")),
        ("Mac Mini research-colony-error.log", tail_log(CLAUDE_DIR / "logs" / "research-colony-error.log")),
        ("Mac Mini cross-machine-merge-error.log", tail_log(CLAUDE_DIR / "logs" / "cross-machine-merge-error.log")),
        ("laptop daily-digest-error.log", ssh_cat(LAPTOP_HOST, "~/.claude/logs/daily-digest-error.log") or "(unreachable)"),
        ("laptop research-colony-error.log", ssh_cat(LAPTOP_HOST, "~/.claude/logs/research-colony-error.log") or "(unreachable)"),
    ]

    passed = sum(1 for r in results if r.startswith("PASS"))
    report_lines = [f"# Digest fix verification — {CHECK_DATE}", "", f"{passed}/{len(results)} checks passed", ""]
    report_lines += ["## Content checks", *[f"- {r}" for r in results], "", "## Error log tails"]
    for label, tail in error_logs:
        report_lines += [f"### {label}", "```", tail, "```", ""]

    report_path = CLAUDE_DIR / "logs" / f"digest-fix-verification-{CHECK_DATE}.md"
    report_path.write_text("\n".join(report_lines))

    summary = f"Digest fix check: {passed}/{len(results)} passed. Full report: {report_path}"
    subprocess.run(["osascript", "-e", f'display notification "{summary}" with title "MARVIN digest fix check"'])
    print(summary)

    # one-shot: remove the launchd job and this script now that it's run
    plist = Path.home() / "Library" / "LaunchAgents" / "com.marvin.verify-digest-fix.plist"
    subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
    plist.unlink(missing_ok=True)
    Path(__file__).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
