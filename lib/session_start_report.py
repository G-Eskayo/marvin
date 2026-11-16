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
import inbox  # noqa: E402
import resume_check  # noqa: E402

HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
SKILLS_DIR = HOME / ".agents" / "skills"
HOOK_NAME = "session_start_report"

# Claude Code caps hook stdout at 10,000 characters. Over that it saves the output to a file and puts only the
# path and the first 2,000 characters in context, and never asks Claude to read the file (hooks reference,
# "Over the limit"). The report was 12.8-15.4 KB, so the lexicon's tail and the whole handoff never arrived
# (marvin#1037). BUDGET leaves room for the other commands in the same SessionStart chain (code_sync, the
# remote-session check), whose stdout counts toward the same cap.
INLINE_LIMIT = 10_000
BUDGET = 8_000
LEXICON_MAX = 2_500  # full definitions every session (PR #1124); the live lexicon is ~1.2 KB without the MCP glossary
BRIEF_MAX = 3_500  # the morning brief is shown first (marvin#306); this keeps room for the checklist below it
FULL_REPORT = HOME / ".agents" / "var" / "session-start-report.md"  # everything, for whatever had to be cut


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


def _dir_entries(d: Path) -> list[Path]:
    """Safe iterdir(): returns [] on OSError, otherwise sorted list of direct subdirectories."""
    try:
        return sorted([p for p in d.iterdir() if p.is_dir()])
    except OSError:
        return []


def skill_names(skills_dir: Path) -> list[str]:
    """Direct subdirectories of skills_dir that contain a file named exactly SKILL.md."""
    names = []
    for d in _dir_entries(skills_dir):
        if (d / "SKILL.md").exists():
            names.append(d.name)
    return sorted(names)


def _prune_dangling_commands(commands_dir: Path) -> None:
    """Unlink any symlink under commands_dir that no longer resolves, logging failures via log_hook_error."""
    if not commands_dir.exists():
        return
    try:
        entries = sorted(commands_dir.iterdir())
    except OSError:
        return
    for p in entries:
        if not p.is_symlink():
            continue
        try:
            p.resolve(strict=True)
        except (OSError, RuntimeError):
            try:
                p.unlink()
            except OSError as exc:
                log_hook_error(HOOK_NAME, f"_prune_dangling_commands {p.name}", exc)


def _wired_skill_names(skills_dir: Path, commands_dir: Path) -> set[str]:
    """Set of skill names that are wired: a .md command file's stem matches, or its content references skills/<name>/SKILL.md."""
    wired = set()
    skills = skill_names(skills_dir)
    if not commands_dir.exists():
        return wired
    try:
        entries = list(commands_dir.iterdir())
    except OSError:
        return wired
    for p in sorted(entries):
        if not p.suffix == ".md":
            continue
        if p.is_symlink():
            try:
                p.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
        if not p.is_file():
            continue
        name = p.stem
        if name in skills:
            wired.add(name)
        try:
            text = p.read_text(errors="replace")
            for skill in skills:
                if skill not in wired and f"skills/{skill}/SKILL.md" in text:
                    wired.add(skill)
        except OSError:
            pass
    return wired


def check_identity() -> str:
    """A single, verifiable line proving this session is actually running
    with MARVIN's infrastructure wired in — not just prose claiming to be
    MARVIN. Every field is checkable against live state (git log, live skills,
    wired skills) rather than a static greeting string, so it can't
    silently go stale the way a hardcoded banner could."""
    _prune_dangling_commands(CLAUDE_DIR / "commands")
    machine = machine_profile.machine_label()
    agents_head = _git_short_head(HOME / ".agents")
    claude_head = _git_short_head(CLAUDE_DIR)
    total_skills = len(skill_names(SKILLS_DIR))
    wired_skills = len(_wired_skill_names(SKILLS_DIR, CLAUDE_DIR / "commands"))
    return f"MARVIN active — {machine} · agents@{agents_head} · claude@{claude_head} · {total_skills} skills ({wired_skills} wired)"


def check_handoff() -> str | None:
    """The newest handoff by its content date (`as_of`, not mtime), with its ticket and PR claims checked against
    GitHub first (lib/resume_check.py, marvin#1221): a claim that changed since is shown as history, never as current."""
    d = CLAUDE_DIR / "handoffs"
    now = _now()
    ranked = resume_check.ranked_handoffs(d, now)
    if not ranked:
        return None
    latest, when = ranked[0]
    if now - when.at > timedelta(days=7):
        return None
    text = latest.read_text(errors="replace")
    try:
        report = resume_check.check(text, when, now=now)
    except Exception as exc:  # noqa: BLE001  (the check never hides the handoff; it says it couldn't run)
        log_hook_error(HOOK_NAME, "check_handoff", exc)
        report = resume_check.Report("unverified", when, reason=f"the check failed ({exc.__class__.__name__})")
    resume_check.log_run(report, handoff=latest, where="session-start", machine=machine_profile.machine_label())
    return resume_check.render_section(latest, report, home=HOME, text=text, now=now)


def _open_in_inbox(pile: str) -> int | None:
    """Open items in an inbox pile (ADR 0083), or None while the pile hasn't moved in yet (read the old file)."""
    root = CLAUDE_DIR / "inbox"
    return len(inbox.open_items(pile, root)) if inbox.pile_exists(pile, root) else None


def check_suggestions() -> str | None:
    n = _open_in_inbox("suggestions")
    if n is not None:
        return f"{n} architecture suggestion(s) pending in the inbox" if n else None
    f = CLAUDE_DIR / "suggestions.md"
    if not f.exists():
        return None
    n = len(re.findall(r"^\*\*Status\*\*:\s*pending", f.read_text(), re.MULTILINE))
    if n == 0:
        return None
    return f"{n} architecture suggestion(s) pending in suggestions.md"


def load_lexicon() -> str | None:
    """The lexicon in full, every session (owner's decision on PR #1124, after the generic MCP glossary moved to
    best-practices/mcp-glossary.md). Capped at LEXICON_MAX so a lexicon that grows again can't push the checklist
    and the handoff out of the report; past the cap it's cut at a line and says where the rest is."""
    f = CLAUDE_DIR / "lexicon.md"
    if not f.exists():
        return None
    return load_lexicon_text(f.read_text(errors="replace"), str(f).replace(str(HOME), "~", 1))


def load_lexicon_text(text: str, where: str = "~/.claude/lexicon.md") -> str | None:
    if not re.search(r"^\s*- \*\*(.+?)\*\*", text, re.MULTILINE):
        return None
    text = re.sub(r"<!--.*?(-->|\Z)", "", text, flags=re.DOTALL)  # the "add new terms" template
    lines = [ln.rstrip() for ln in text.splitlines()]
    lines = [ln for ln in lines if not ln.startswith("# ") and ln.strip() != "---"]
    lines = ["#" + ln if ln.startswith("## ") else ln for ln in lines]  # its sections nest under ## Lexicon
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    section = "## Lexicon (apply these terms without explanation)\n\n" + body
    if len(section) <= LEXICON_MAX:
        return section
    note = f"\n…(the lexicon is longer than {LEXICON_MAX:,} characters; the rest is in `{where}`)"
    head = section[: LEXICON_MAX - len(note)]
    head = head[: head.rfind("\n")] if "\n" in head else head
    return head + note


def check_improvement_queue() -> str | None:
    n = _open_in_inbox("improvement-queue")
    if n is not None:
        return f"{n} item(s) queued in the improvement queue" if n else None
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
    n_task_dispatch = 0
    for line in f.read_text().splitlines():
        m = re.match(r"^(\S+)", line)
        ts = _parse_iso(m.group(1)) if m else None
        if ts and ts >= cutoff:
            n += 1
            if "[task_dispatch]" in line:
                n_task_dispatch += 1
    if n == 0:
        return None
    note = f"{n} hook failure(s) in the last 24h"
    if n_task_dispatch:
        note += f" ({n_task_dispatch} from task_dispatch)"
    return note + " — check ~/.claude/logs/hook-errors.log"


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


def _last_wake() -> datetime | None:
    """When this Mac last woke from sleep (`sysctl kern.waketime`), or None if unknown."""
    try:
        out = subprocess.run(["/usr/sbin/sysctl", "-n", "kern.waketime"], capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    m = re.search(r"\bsec = (\d+)", out.stdout or "") if out.returncode == 0 else None
    return datetime.fromtimestamp(int(m.group(1)), tz=timezone.utc) if m and int(m.group(1)) > 0 else None


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
    # Count from this Mac's last wake too (marvin#451): commits that landed while it slept aren't stuck until the sync
    # job has had its window since waking. A wake time in the future (clock skew) is ignored, never trusted to hide.
    wake = _last_wake()
    wake = wake if wake and wake <= now else None
    for rng, what in (("origin/main..main", "committed here but not pushed"),
                      ("main..origin/main", "on origin but not merged here")):
        stamps = [int(t) for t in (_git_out(repo, "log", "--format=%ct", rng) or "").split() if t.isdigit()]
        if not stamps:
            continue
        stuck_from = max(datetime.fromtimestamp(min(stamps), tz=timezone.utc), wake or datetime.min.replace(tzinfo=timezone.utc))
        if stuck_from <= cutoff:
            problems.append(f"{len(stamps)} commit(s) {what}, for {_fmt_age(now - stuck_from)}")
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

    _safe(lambda: _save_full_report("\n\n".join(sections)))
    # The brief stays first (marvin#306) but can't take the room the checklist needs (marvin#1037).
    shown = [_cap(sec, BRIEF_MAX) if sec.startswith("## Morning brief") else sec for sec in sections]
    print(fit(shown, BUDGET))


def _save_full_report(text: str) -> None:
    FULL_REPORT.parent.mkdir(parents=True, exist_ok=True)
    tmp = FULL_REPORT.with_name(FULL_REPORT.name + ".tmp")
    tmp.write_text(text + "\n")
    tmp.replace(FULL_REPORT)


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    note = f"\n…(cut to fit Claude Code's hook limit; the full report is at `{FULL_REPORT}`)"
    head = text[: max(0, limit - len(note))]
    head = head[: head.rfind("\n")] if "\n" in head else head
    return head + note


def fit(sections: list[str], budget: int) -> str:
    """Join sections in order (most important first) without passing `budget` characters. A section that doesn't
    fit is cut at a line break and says so; sections after it that don't fit are named in one closing line.
    The first section (the banner) is always kept."""
    sep = "\n\n"
    where = str(FULL_REPORT)
    out: list[str] = [sections[0][:budget]]
    used = len(out[0])
    dropped: list[str] = []
    tail_room = 160 + len(where)  # kept free for the closing "left out" line
    for sec in sections[1:]:
        if used + len(sep) + len(sec) <= budget - tail_room:
            out.append(sec)
            used += len(sep) + len(sec)
            continue
        title = sec.splitlines()[0].lstrip("# ").strip()[:60]
        note = f"\n…(cut to fit Claude Code's hook limit; the full report is at `{where}`)"
        room = budget - tail_room - used - len(sep) - len(note)
        if not dropped and room >= 400:
            head = sec[:room]
            head = head[: head.rfind("\n")] if "\n" in head else head
            out.append(head + note)
            used += len(sep) + len(head) + len(note)
        else:
            dropped.append(title)
    if dropped:
        line = f"Left out to fit Claude Code's hook limit ({', '.join(dropped)}): read `{where}`."
        out.append(line[: max(0, budget - used - len(sep))])
    return sep.join(out)


if __name__ == "__main__":
    main()
