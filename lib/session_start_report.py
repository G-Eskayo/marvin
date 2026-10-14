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

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path.home() / ".agents" / "skills" / "safety-monitor" / "scripts"))

from hook_errors import log_hook_error  # noqa: E402
import machine_profile  # noqa: E402

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


def _git_short_head(repo: Path) -> str:
    if not (repo / ".git").exists():
        return "?"
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() or "?"
    except Exception as exc:
        log_hook_error(HOOK_NAME, "_git_short_head", exc)
        return "?"


def check_identity() -> str:
    """A single, verifiable line proving this session is actually running
    with MARVIN's infrastructure wired in — not just prose claiming to be
    MARVIN. Every field is checkable against live state (git log, ls
    ~/.claude/commands) rather than a static greeting string, so it can't
    silently go stale the way a hardcoded banner could."""
    machine = machine_profile.machine_label()
    agents_head = _git_short_head(HOME / ".agents")
    claude_head = _git_short_head(CLAUDE_DIR)
    skills = len(list((CLAUDE_DIR / "commands").glob("*.md")))
    return f"MARVIN active — {machine} · agents@{agents_head} · claude@{claude_head} · {skills} skills wired"


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
    """Latest sync-log entry in the last 24h, for visibility only. Whether sync
    is CURRENTLY blocked is decided by check_sync_block() against live git
    state plus this Mac's own failure streak, not by this one line."""
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


# A blocked sync is a hard stop at the top of the report (marvin#426). As one bullet among the backlog counts it was
# ignored for 4 days in Oct 2026 while ~/.claude refused to sync 766 times and memories never reached the other Mac.
SYNC_BLOCK_AFTER_HOURS = 2
SYNC_FAILURE_PREFIXES = ("REFUSING", "CONFLICT", "commit failed", "push failed", "pulled cleanly, but restoring")
SYNC_NEUTRAL_PREFIXES = ("deferring", "skipping")  # skipping: off main, code_sync leaves the tree alone (#440)
CONFLICT_CODES = {"UU", "AA", "DD", "AU", "UA", "UD", "DU"}


def _git_out(repo: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=10)
    except Exception as exc:
        log_hook_error(HOOK_NAME, f"git {args[0]} {repo}", exc)
        return None
    return r.stdout if r.returncode == 0 else None


def _fmt_age(delta: timedelta) -> str:
    mins = max(0, int(delta.total_seconds() // 60))
    days, hours, mins = mins // 1440, mins // 60 % 24, mins % 60
    if days:
        return f"{days}d {hours}h"
    return f"{hours}h {mins}m" if hours else f"{mins}m"


def _sync_failure_streak(text: str, machine: str, repo: Path) -> tuple[int, int, datetime, str] | None:
    """This Mac's trailing run of failed sync entries for `repo`: (failed, refused, since, latest summary).
    Only this Mac's own entries count: sync-log.md is itself synced, so it also holds the other Mac's, possibly stale."""
    entries = []
    for m in re.finditer(r"^## (\S+) — \S+ \(([^)]+)\) \[([^\]]+)\]\n(.*?)(?=\n## |\Z)", text, re.DOTALL | re.MULTILINE):
        ts = _parse_iso(m.group(1))
        if ts and m.group(2) == machine and m.group(3) == str(repo):
            entries.append((ts, m.group(4).strip().split("\n", 1)[0]))
    failed = refused = 0
    since, latest = None, ""
    for ts, summary in sorted(entries, key=lambda e: e[0], reverse=True):
        if summary.startswith(SYNC_NEUTRAL_PREFIXES):
            continue
        if not summary.startswith(SYNC_FAILURE_PREFIXES):
            break
        failed += 1
        refused += summary.startswith("REFUSING")
        since, latest = ts, latest or summary
    return (failed, refused, since, latest) if failed else None


def _live_sync_problems(repo: Path, now: datetime) -> list[str]:
    status = _git_out(repo, "status", "--porcelain=v1")
    if status is None:
        return []
    problems = []
    if (repo / ".git" / "MERGE_HEAD").exists() or any(line[:2] in CONFLICT_CODES for line in status.splitlines()):
        problems.append("unresolved merge conflict")
    n_stash = len([line for line in (_git_out(repo, "stash", "list") or "").splitlines() if line.strip()])
    if n_stash:
        problems.append(f"{n_stash} leftover stash(es) from a failed WIP restore")
    # Only on main: ~/.agents is often on a ticket branch, where pull merges origin/main into the branch instead.
    if (_git_out(repo, "symbolic-ref", "--short", "HEAD") or "").strip() != "main":
        return problems
    if _git_out(repo, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/main") is None:
        return problems
    cutoff = now - timedelta(hours=SYNC_BLOCK_AFTER_HOURS)
    for rng, what in (("origin/main..main", "committed here but not pushed"),
                      ("main..origin/main", "on origin but not merged here")):
        stamps = [int(t) for t in (_git_out(repo, "log", "--format=%ct", rng) or "").split() if t.isdigit()]
        if not stamps:
            continue
        oldest = datetime.fromtimestamp(min(stamps), tz=timezone.utc)
        if oldest <= cutoff:
            problems.append(f"{len(stamps)} commit(s) {what}, oldest {_fmt_age(now - oldest)} old")
    return problems


def check_sync_block(repos: list[Path] | None = None, log_path: Path | None = None,
                     machine: str | None = None, now: datetime | None = None) -> str | None:
    """The hard-stop block for a synced repo that is not syncing: live git state (conflict, stash, ahead/behind
    origin for over SYNC_BLOCK_AFTER_HOURS) plus this Mac's failure streak from sync-log.md (how long, how many)."""
    repos = repos if repos is not None else [CLAUDE_DIR, HOME / ".agents"]
    log_path = log_path or CLAUDE_DIR / "sync-log.md"
    machine = machine or machine_profile.machine_label()
    now = now or _now()
    try:
        text = log_path.read_text(errors="replace") if log_path.exists() else ""
    except OSError:
        text = ""
    blocks = []
    for repo in repos:
        if not (Path(repo) / ".git").exists():
            continue
        problems = _live_sync_problems(repo, now)
        streak = _sync_failure_streak(text, machine, repo)
        if not problems and not streak:
            continue
        name = str(repo).replace(str(HOME), "~", 1)
        lines = [f"**{name}** on {machine}: " + (" · ".join(problems) if problems else "sync is failing")]
        if streak:
            failed, refused, since, latest = streak
            lines.append(f"- Stuck since {since.strftime('%Y-%m-%d %H:%M')} UTC ({_fmt_age(now - since)}): "
                         f"{failed} failed sync run(s) in a row, {refused} refused")
            lines.append(f"- Latest: {latest[:240]}")
        lines.append(f"- Look: `git -C {name} status && git -C {name} stash list && git -C {name} log --oneline -3 origin/main...main`")
        blocks.append("\n".join(lines))
    if not blocks:
        return None
    return ("## ⛔ SYNC BLOCKED — fix this before anything else\n\n"
            "Nothing written on this Mac (memory, handoffs, code) reaches the other one, and the other way round, "
            "until this is fixed.\n\n" + "\n\n".join(blocks))


def _check_digest(label: str, dirpath: Path) -> str | None:
    today = _now().astimezone().strftime("%Y-%m-%d")
    f = dirpath / f"{today}.md"
    if not f.exists():
        return None
    m = re.search(r"^\*(.+?)\*\s*$", f.read_text(), re.MULTILINE)
    extra = f" — {m.group(1)}" if m else ""
    return f"{label} ready ({f.name}){extra}"


def check_morning_brief() -> str | None:
    """Today's morning brief (marvin#306), shown in full; showing it is what marks it read."""
    import morning_brief
    return morning_brief.show_today()


def check_auto_merge_report() -> str | None:
    """Auto-merge's shadow report, once it is ready (ADR 0064, #341): the one place Gil is told to switch it on."""
    import auto_merge_shadow
    return auto_merge_shadow.report_line_anywhere()


def check_daily_digest() -> str | None:
    return _check_digest("today's daily digest", CLAUDE_DIR / "daily-digest")


def check_research_digest() -> str | None:
    return _check_digest("today's research digest", CLAUDE_DIR / "research-digest")


def main() -> None:
    identity = _safe(check_identity) or "MARVIN active — identity check failed, see hook-errors.log"
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
        _safe(check_auto_merge_report),
        _safe(check_daily_digest),
        _safe(check_research_digest),
    ) if n]

    sections = [identity]
    sync_block = _safe(check_sync_block)
    if sync_block:
        sections.append(sync_block)
    brief = _safe(check_morning_brief)
    if brief:
        sections.append(brief.replace("# Morning brief", "## Morning brief", 1))
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
