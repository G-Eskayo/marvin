#!/usr/bin/env python3
"""SessionStart hook: deterministic replacement for the CLAUDE.md session-start checklist.

The checklist in ~/.claude/CLAUDE.md (steps 1-11; step 12's auto-route is
skipped here — it needs the first user message, which doesn't exist yet at
SessionStart) used to be prose Claude was supposed to read and act on every
session. Nothing guaranteed that actually happened — a rushed reply or a
compacted context could skip it silently. This script does the same checks
itself and prints the result to stdout, which Claude Code surfaces as
context at session start regardless of what the model does. Every check
degrades independently (one file missing/corrupt doesn't blank the rest),
and the whole thing never raises: a broken check is logged to
hook-errors.log via hook_errors.log_hook_error and skipped, never crashes
the SessionStart hook chain.

Run standalone to preview what a session would see:
    ~/.agents/venv/bin/python ~/.agents/lib/session_start_report.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
sys.path.insert(0, str(Path.home() / ".agents" / "skills" / "safety-monitor" / "scripts"))

from hook_errors import log_hook_error  # noqa: E402

HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
HOOK_NAME = "session_start_report"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _safe(fn):
    """Runs one checklist step; a failure is logged and treated as 'nothing to report'
    so one broken check can't blank out the rest of the session-start report."""
    try:
        return fn()
    except Exception as exc:
        log_hook_error(HOOK_NAME, fn.__name__, exc)
        return None


def check_handoff() -> str | None:
    d = CLAUDE_DIR / "handoffs"
    if not d.exists():
        return None
    files = sorted(d.glob("handoff-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    latest = files[0]
    age = _now() - datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
    if age > timedelta(days=7):
        return None
    return f"## Most recent handoff — {latest.name} ({age.days}d old)\n\n{latest.read_text()}"


def check_suggestions() -> str | None:
    f = CLAUDE_DIR / "suggestions.md"
    if not f.exists():
        return None
    n = len(re.findall(r"^\*\*Status\*\*:\s*pending", f.read_text(), re.MULTILINE))
    if n == 0:
        return None
    return f"{n} architecture suggestion(s) pending in suggestions.md"


def load_lexicon() -> str | None:
    f = CLAUDE_DIR / "lexicon.md"
    if not f.exists():
        return None
    return f"## Lexicon\n\n{f.read_text()}"


def check_improvement_queue() -> str | None:
    f = CLAUDE_DIR / "improvement-queue.md"
    if not f.exists():
        return None
    n = len(re.findall(r"^- \*\*\[", f.read_text(), re.MULTILINE))
    if n == 0:
        return None
    return f"{n} item(s) queued in improvement-queue.md"


def process_and_check_quarantine() -> str | None:
    processed, remaining = 0, None
    try:
        from process_quarantine_reviews import process
        processed, remaining = process()
    except Exception as exc:
        log_hook_error(HOOK_NAME, "process_quarantine_reviews", exc)

    if remaining is None:
        # Fall back to a read-only count using the same header pattern the
        # processor itself uses, so a processor bug doesn't hide the count too.
        f = CLAUDE_DIR / "quarantine.md"
        if not f.exists():
            return None
        header_re = re.compile(r"^## \d{4}-\d{2}-\d{2} — \S+ \[SAFETY,", re.MULTILINE)
        remaining = len(header_re.findall(f.read_text()))

    if remaining == 0:
        return None
    note = f"{remaining} item(s) awaiting quarantine review"
    if processed:
        note += f" ({processed} processed just now)"
    return note


def check_hook_errors() -> str | None:
    f = CLAUDE_DIR / "logs" / "hook-errors.log"
    if not f.exists():
        return None
    cutoff = _now() - timedelta(hours=24)
    n = 0
    for line in f.read_text().splitlines():
        m = re.match(r"^(\S+)", line)
        ts = _parse_iso(m.group(1)) if m else None
        if ts and ts >= cutoff:
            n += 1
    if n == 0:
        return None
    return f"{n} hook failure(s) in the last 24h — check ~/.claude/logs/hook-errors.log"


def check_cron_health() -> str | None:
    f = CLAUDE_DIR / "logs" / "cron-health.md"
    if not f.exists():
        return None
    text = f.read_text()
    m = re.search(r"^## Latest.*?\n(.*?)(?=\n## |\Z)", text, re.DOTALL | re.MULTILINE)
    if not m:
        return None
    body = m.group(1).strip()
    if body == "All monitored jobs ran cleanly.":
        return None
    return f"cron-health flagged:\n{body}"


def check_auto_fix_log() -> str | None:
    f = CLAUDE_DIR / "auto-fix-log.md"
    if not f.exists():
        return None
    text = f.read_text()
    entries = list(re.finditer(r"^## (\S+)\n(.*?)(?=\n## |\Z)", text, re.DOTALL | re.MULTILINE))
    if not entries:
        return None
    ts, body = entries[-1].group(1), entries[-1].group(2).strip()
    dt = _parse_iso(ts)
    if not dt or _now() - dt > timedelta(hours=24):
        return None
    return f"auto-fix ({ts}): {body.splitlines()[0]}"


def check_sync_log() -> str | None:
    """Latest sync-log entry in the last 24h, for visibility only. Whether a
    conflict is CURRENTLY open is decided by check_git_conflicts() against
    live git state, not by scanning log prose — a log line saying CONFLICT
    can be hours-stale once resolved, and stays in the 24h window looking
    like an open problem long after `git stash pop` actually cleared it."""
    f = CLAUDE_DIR / "sync-log.md"
    if not f.exists():
        return None
    text = f.read_text()
    cutoff = _now() - timedelta(hours=24)
    entries = list(re.finditer(r"^## (\S+) — ([^\n]+)\n(.*?)(?=\n## |\Z)", text, re.DOTALL | re.MULTILINE))
    recent = [(ts, header, body.strip()) for ts, header, body in
              ((m.group(1), m.group(2), m.group(3)) for m in entries)
              if (dt := _parse_iso(ts)) and dt >= cutoff]
    if not recent:
        return None
    ts, header, body = recent[-1]
    first_line = body.splitlines()[0] if body else ""
    return f"code-sync ({ts}) {header}: {first_line}"


def check_git_conflicts() -> str | None:
    """Live git state for the synced repos — authoritative, unlike scanning
    sync-log.md prose (see check_sync_log). Flags an unresolved merge
    (conflict markers in `git status` or a live MERGE_HEAD) and any stash
    left behind by a failed WIP-restore, since that's exactly how code_sync's
    stash-then-pull-then-pop dance leaves local work stranded."""
    findings = []
    for repo in (CLAUDE_DIR, HOME / ".agents"):
        if not (repo / ".git").exists():
            continue
        try:
            status = subprocess.run(
                ["git", "-C", str(repo), "status", "--porcelain=v1"],
                capture_output=True, text=True, timeout=10,
            ).stdout
        except Exception as exc:
            log_hook_error(HOOK_NAME, f"git status {repo}", exc)
            continue
        conflict_codes = {"UU", "AA", "DD", "AU", "UA", "UD", "DU"}
        has_conflict = (repo / ".git" / "MERGE_HEAD").exists() or any(
            line[:2] in conflict_codes for line in status.splitlines()
        )
        if has_conflict:
            findings.append(f"**{repo} has an unresolved merge conflict right now** — needs a live session to fix")

        try:
            stash = subprocess.run(
                ["git", "-C", str(repo), "stash", "list"],
                capture_output=True, text=True, timeout=10,
            ).stdout
        except Exception as exc:
            log_hook_error(HOOK_NAME, f"git stash list {repo}", exc)
            continue
        n_stash = len([l for l in stash.splitlines() if l.strip()])
        if n_stash:
            findings.append(f"{repo} has {n_stash} stash(es) left over from a code-sync WIP restore — check `git -C {repo} stash list`")

    return "\n".join(findings) if findings else None


def _check_digest(label: str, dirpath: Path) -> str | None:
    today = _now().astimezone().strftime("%Y-%m-%d")
    f = dirpath / f"{today}.md"
    if not f.exists():
        return None
    m = re.search(r"^\*(.+?)\*\s*$", f.read_text(), re.MULTILINE)
    extra = f" — {m.group(1)}" if m else ""
    return f"{label} ready ({f.name}){extra}"


def check_daily_digest() -> str | None:
    return _check_digest("today's daily digest", CLAUDE_DIR / "daily-digest")


def check_research_digest() -> str | None:
    return _check_digest("today's research digest", CLAUDE_DIR / "research-digest")


def main() -> None:
    handoff = _safe(check_handoff)
    lexicon = _safe(load_lexicon)

    notes = [n for n in (
        _safe(check_suggestions),
        _safe(check_improvement_queue),
        _safe(process_and_check_quarantine),
        _safe(check_hook_errors),
        _safe(check_cron_health),
        _safe(check_auto_fix_log),
        _safe(check_sync_log),
        _safe(check_git_conflicts),
        _safe(check_daily_digest),
        _safe(check_research_digest),
    ) if n]

    sections = []
    if notes:
        sections.append("## Session-start checklist\n\n" + "\n".join(f"- {n}" for n in notes))
    else:
        sections.append("## Session-start checklist\n\nAll clear — nothing pending.")
    if lexicon:
        sections.append(lexicon)
    if handoff:
        sections.append(handoff)

    print("\n\n".join(sections))


if __name__ == "__main__":
    main()
