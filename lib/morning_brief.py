#!/usr/bin/env python3
"""The morning brief (marvin#306): one short start-of-day brief instead of two digests and a checklist.

North star 3 (raise the human experience): what needs a decision first, what happened overnight, today's deadlines
and top tickets, one idea from each digest, and a factual note when the night ran late. It coaches; it doesn't
nag. Built from what MARVIN already knows (Health, the launch log, the digests, GitHub over REST), so it costs no
model run: north star 1.

Written to ~/.claude/briefs/<day>.md (private, synced) after the digests, and shown by the session-start report.
Showing it marks it read (<day>.read), which is how the output contracts know the brief, and through it the
digests, were consumed.

    morning_brief.py build   # write today's brief (scheduled after the digests)
    morning_brief.py show    # print it and mark it read
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import resume_check

# ── Item structure ──────────────────────────────────────────────────────────

@dataclass
class Item:
    section: str           # one of SECTIONS
    line: str              # one-line summary with markup removed
    summary: str | None    # optional extended summary
    source: dict           # {label, url?, related?}
    rank: int              # 1–5 (lower is higher priority)

    def to_md_line(self) -> str:
        return f"- {self.line}"


SECTIONS = ("World & security", "Research", "Your day", "Your projects")
LINE_MAX = 100
SUMMARY_MAX = 200

def _sanitize(text: str, max_len: int = LINE_MAX) -> str:
    """Remove markup and control chars from externally-sourced strings."""
    return resume_check.strip_markup(text, max_len) if text else ""

CLAUDE = Path.home() / ".claude"
BRIEFS = CLAUDE / "briefs"
HEALTH_STATUS = CLAUDE / "logs" / "health-status.json"
OVERRIDES = CLAUDE / "catalog" / "overrides.json"
REPOS = ("G-Eskayo/marvin", "G-Eskayo/clarity-captions", "G-Eskayo/marvin-mobile")
DEADLINE_HORIZON_DAYS = 45
LATE_HOUR = 23  # local time; a session still active after this counts as a late night


# ── item builders (map feeds → candidate items) ──────────────────────────────────

def _item_from_red_check(check: dict) -> Item | None:
    if not check.get("label") or not check.get("detail"):
        return None
    return Item(
        section="Your projects",
        line=f"Health: {_sanitize(check['label'])}: {_sanitize(check['detail'])}",
        summary=None,
        source={"label": "Health"},
        rank=0
    )


def _item_from_open_pr(pr: dict) -> Item | None:
    if pr.get("waiting_on_marvin"):
        return None
    if not pr.get("number") or not pr.get("title"):
        return None
    repo = f"{pr.get('repo', 'marvin')} " if pr.get("repo") != "marvin" else ""
    return Item(
        section="Your projects",
        line=f"Review {repo}PR #{pr['number']} {_sanitize(pr['title'])}",
        summary=None,
        source={"label": "open PRs", "repo": pr.get("repo"), "number": pr.get("number")},
        rank=0
    )


def _item_from_human_ticket(ticket: dict) -> Item | None:
    if not ticket.get("number") or not ticket.get("title"):
        return None
    repo = f"{ticket.get('repo', 'marvin')} " if ticket.get("repo") != "marvin" else ""
    return Item(
        section="Your projects",
        line=f"Your task: {repo}#{ticket['number']} {_sanitize(ticket['title'])}",
        summary=None,
        source={"label": "ready-for-human", "repo": ticket.get("repo"), "number": ticket.get("number")},
        rank=0
    )


def _item_from_top_ticket(ticket: dict) -> Item | None:
    if not ticket.get("number") or not ticket.get("title"):
        return None
    priority = ticket.get("priority", "p0")
    repo = f"{ticket.get('repo', 'marvin')} " if ticket.get("repo") != "marvin" else ""
    return Item(
        section="Your projects",
        line=f"{priority}: {repo}#{ticket['number']} {_sanitize(ticket['title'])}",
        summary=None,
        source={"label": "top tickets", "repo": ticket.get("repo"), "number": ticket.get("number"), "priority": priority},
        rank=0
    )


def _item_from_regression(regression: dict) -> Item | None:
    if regression.get("kind") != "needs-you":
        return None
    if not regression.get("line"):
        return None
    return Item(
        section="Your projects",
        line=_sanitize(regression["line"]),
        summary=None,
        source={"label": "incident ladder"},
        rank=0
    )


def _item_from_auto_merge(text: str) -> Item | None:
    if not text:
        return None
    return Item(
        section="Your projects",
        line=_sanitize(text),
        summary=None,
        source={"label": "auto-merge"},
        rank=0
    )


def _item_from_deadline(deadline: dict, now: datetime) -> Item | None:
    if not deadline.get("project") or not deadline.get("date"):
        return None
    days = _days_until(deadline["date"], now)
    hard = ", hard deadline" if deadline.get("hard") else ""
    return Item(
        section="Your day",
        line=f"{deadline['project']}: {days} days ({deadline['date']}{hard})",
        summary=None,
        source={"label": "deadlines", "project": deadline.get("project")},
        rank=1
    )


def _item_from_research_idea(text: str) -> Item | None:
    if not text:
        return None
    return Item(
        section="Research",
        line=f"From research: {_sanitize(text)}",
        summary=None,
        source={"label": "research digest"},
        rank=2
    )


# ── sources (each is a small reader; gather() tolerates any of them failing) ──────────────────────────────────

def _gh(path: str):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise OSError(out.stderr.strip()[:200] or "gh failed")
    return json.loads(out.stdout)


def _open_prs() -> list[dict]:
    """Open PRs, one GraphQL call for all REPOS. A PR whose owner decisions are in and not yet acted on is marked
    waiting_on_marvin (marvin#607): it is MARVIN's move, so it is not listed under "Needs you"."""
    import owner_decisions
    now = datetime.now(timezone.utc)
    data = owner_decisions.fetch(REPOS)
    if data is None:
        raise OSError("gh failed")
    waiting = {(s["repo"], s["number"]): s for s in owner_decisions.statuses(data, now, owner_decisions.grace_hours())
               if not s["addressed_by"]}
    out = []
    for p in data["prs"]:
        s = waiting.get((p["repo"], p["number"]))
        out.append({"number": p["number"], "title": p["title"], "repo": p["repo"].split("/")[1],
                    "waiting_on_marvin": bool(s), "question": bool(s and s["question"])})
    return out


def _red_checks() -> list[dict]:
    import stamped
    copy = stamped.read(HEALTH_STATUS)
    if copy.missing:
        raise OSError(f"no readable {HEALTH_STATUS.name}")  # the caller's existing "couldn't read Health" path
    return [c for c in copy.value.get("checks", []) if c.get("severity") == "red"]


def _human_tickets() -> list[dict]:
    out = []
    for repo in REPOS:
        out += [{"number": i["number"], "title": i["title"], "repo": repo.split("/")[1]}
                for i in _gh(f"repos/{repo}/issues?labels=ready-for-human&state=open&per_page=50") if "pull_request" not in i]
    return out


def _launches(now: datetime) -> list[dict]:
    import marvin_launcher
    since = now - timedelta(days=1)
    out = []
    for line in (marvin_launcher.LAUNCH_LOG.read_text().splitlines() if marvin_launcher.LAUNCH_LOG.exists() else []):
        try:
            rec = json.loads(line)
            if datetime.fromisoformat(rec["at"]) >= since:
                out.append(rec)
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return out


def _merged(now: datetime) -> list[dict]:
    since = now - timedelta(days=1)
    out = []
    for repo in REPOS:
        for p in _gh(f"repos/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=30"):
            if p.get("merged_at") and datetime.fromisoformat(p["merged_at"].replace("Z", "+00:00")) >= since:
                out.append({"number": p["number"], "title": p["title"], "repo": repo.split("/")[1]})
    return out


def _days_until(date: str, now: datetime) -> int:
    """Calendar days, as a person counts them: from Friday the 9th to the 25th is 16 days."""
    return (datetime.fromisoformat(date).date() - now.astimezone().date()).days


def _deadlines(now: datetime) -> list[dict]:
    data = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}
    out = []
    for project, o in data.items():
        if isinstance(o, dict) and o.get("due"):
            days = _days_until(o["due"], now)
            if 0 <= days <= DEADLINE_HORIZON_DAYS:
                out.append({"project": project, "date": o["due"], "hard": bool(o.get("dueHard"))})
    return sorted(out, key=lambda d: d["date"])


def _top_tickets() -> list[dict]:
    out = []
    for repo in REPOS:
        for label in ("priority:p0", "priority:p1"):
            out += [{"repo": repo.split("/")[1], "number": i["number"], "title": i["title"], "priority": label[-2:]}
                    for i in _gh(f"repos/{repo}/issues?labels={label}&state=open&per_page=20") if "pull_request" not in i]
    return sorted(out, key=lambda t: t["priority"])[:6]


def _first_paragraph(path: Path, heading: str | None) -> str | None:
    if not path.exists():
        return None
    text = path.read_text()
    if heading:
        m = re.search(rf"^## {re.escape(heading)}\s*$\n+(.+?)(?:\n\n|\n##|\Z)", text, re.M | re.S)
    else:
        m = re.search(r"^\*\*(.+?)\*\*:?\s*(.+?)(?:\n\n|\Z)", text, re.M | re.S)
        return f"{m.group(1)}: {m.group(2).split('. ')[0].strip()}." if m else None
    return m.group(1).strip() if m else None


def _digest_idea(now: datetime) -> str | None:
    day = now.astimezone().strftime("%Y-%m-%d")
    for name in (f"{day}-merged.md", f"{day}.md"):
        idea = _first_paragraph(CLAUDE / "daily-digest" / name, "Compounding Move")
        if idea:
            return idea
    return None


def _research_idea(now: datetime) -> str | None:
    day = now.astimezone().strftime("%Y-%m-%d")
    return _first_paragraph(CLAUDE / "research-digest" / f"{day}.md", None)


def _late_night(now: datetime) -> str | None:
    """The latest time an interactive session was active last night, if it was after LATE_HOUR."""
    import tool_usage as tu
    local_now = now.astimezone()
    start = (local_now - timedelta(days=1)).replace(hour=LATE_HOUR, minute=0, second=0, microsecond=0)
    end = local_now.replace(hour=5, minute=0, second=0, microsecond=0)
    latest = None
    for f in tu.find_transcripts(tu.TRANSCRIPTS, window_days=1, now=now):
        for line in f.read_text(errors="ignore").splitlines()[-400:]:
            if '"entrypoint":"cli"' not in line.replace(" ", ""):
                continue
            m = re.search(r'"timestamp"\s*:\s*"([^"]+)"', line)
            when = tu._parse_ts(m.group(1)).astimezone() if m and tu._parse_ts(m.group(1)) else None
            if when and start <= when <= end and (latest is None or when > latest):
                latest = when
    return latest.strftime("%H:%M") if latest else None


def _auto_merge_report() -> str | None:
    """Auto-merge's shadow report line once it is ready (ADR 0064, #341), else None."""
    import auto_merge_shadow
    return auto_merge_shadow.report_line_anywhere()


def _regressions(now: datetime) -> list[dict]:
    """Solved problems that came back in the last day: fixed by MARVIN itself, or waiting on you (incident_ladder)."""
    import incident_ladder
    lines = incident_ladder.brief_lines(now=now)
    try:
        import auto_merge_regression  # what rung 3's auto-merge would have done, while it shadows
        shadow = auto_merge_regression.report()["line"]
    except Exception:  # noqa: BLE001 -- the ladder's own lines still show
        shadow = None
    return lines + ([{"kind": "needs-you", "line": shadow}] if shadow else [])


def _revisited(now: datetime) -> list[dict]:
    """Tickets returned from hold in the last day (revisit agent)."""
    import ticket_agents
    since = now - timedelta(days=1)
    out = []
    for line in (ticket_agents.AUDIT_PATH.read_text().splitlines() if ticket_agents.AUDIT_PATH.exists() else []):
        try:
            rec = json.loads(line)
            if (rec.get("agent") == "revisit" and rec.get("op") == "remove_label" and rec.get("arg") == "hold" and
                rec.get("status") == "applied" and datetime.fromisoformat(rec["at"]) >= since):
                out.append({"number": rec["number"], "title": rec.get("title", ""), "repo": rec.get("repo", "G-Eskayo/marvin")})
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return out


def default_sources(now: datetime) -> dict[str, Callable]:
    return {"open_prs": _open_prs, "red_checks": _red_checks, "human_tickets": _human_tickets,
            "launches": lambda: _launches(now), "merged": lambda: _merged(now), "revisited": lambda: _revisited(now),
            "deadlines": lambda: _deadlines(now), "top_tickets": _top_tickets, "digest_idea": lambda: _digest_idea(now),
            "research_idea": lambda: _research_idea(now), "late_night": lambda: _late_night(now),
            "auto_merge": _auto_merge_report, "regressions": lambda: _regressions(now)}


_SOURCE_NAMES = {"open_prs": "open PRs", "red_checks": "Health", "human_tickets": "tickets waiting on you",
                 "launches": "the launch log", "merged": "merged PRs", "revisited": "the revisit agent",
                 "deadlines": "deadlines", "top_tickets": "top tickets", "digest_idea": "the daily digest",
                 "research_idea": "the research digest", "late_night": "last night's sessions", "auto_merge": "auto-merge's shadow report",
                 "regressions": "the incident ladder"}


def gather(now: datetime, sources: dict[str, Callable] | None = None) -> dict:
    sources = sources or default_sources(now)
    data, missing = {}, []
    for key, read in sources.items():
        try:
            data[key] = read()
        except Exception as exc:  # noqa: BLE001 -- a brief with a named gap beats no brief
            data[key] = None
            missing.append(f"couldn't read {_SOURCE_NAMES.get(key, key)} ({str(exc)[:80]})")
    data["missing"] = missing
    return data


def _build_candidates(brief: dict, now: datetime) -> list[Item]:
    """Convert gathered data into candidate items."""
    candidates = []

    # Your projects section
    for check in brief.get("red_checks") or []:
        item = _item_from_red_check(check)
        if item:
            candidates.append(item)

    for pr in brief.get("open_prs") or []:
        item = _item_from_open_pr(pr)
        if item:
            candidates.append(item)

    for ticket in brief.get("human_tickets") or []:
        item = _item_from_human_ticket(ticket)
        if item:
            candidates.append(item)

    for ticket in brief.get("top_tickets") or []:
        item = _item_from_top_ticket(ticket)
        if item:
            candidates.append(item)

    for regression in brief.get("regressions") or []:
        item = _item_from_regression(regression)
        if item:
            candidates.append(item)

    if brief.get("auto_merge"):
        item = _item_from_auto_merge(brief["auto_merge"])
        if item:
            candidates.append(item)

    # Your day section
    for deadline in brief.get("deadlines") or []:
        item = _item_from_deadline(deadline, now)
        if item:
            candidates.append(item)

    # Research section
    if brief.get("research_idea"):
        item = _item_from_research_idea(brief["research_idea"])
        if item:
            candidates.append(item)

    return candidates


def _dedup_key(item: Item) -> tuple:
    """Return a key for de-duplication: (repo, number) if available, else normalized line."""
    src = item.source
    if src.get("repo") is not None and src.get("number") is not None:
        return ("ref", src["repo"], src["number"])
    return ("line", _sanitize(item.line, 1000).lower())


def rank_items(candidates: list[Item]) -> list[Item]:
    """Assign ranks 1–5 based on tier, de-duplicate, sort, and truncate to 5, with stable tie-breaker."""
    tier_1 = [c for c in candidates if c.rank == 0]
    tier_2 = [c for c in candidates if c.rank == 1]
    tier_3 = [c for c in candidates if c.rank == 2]

    seen = set()
    deduped = []
    for tier in [tier_1, tier_2, tier_3]:
        sorted_tier = sorted(tier, key=lambda x: (x.source.get("label", ""), x.line.lower()))
        for item in sorted_tier:
            key = _dedup_key(item)
            if key not in seen:
                seen.add(key)
                deduped.append(item)

    ranked = []
    for i, item in enumerate(deduped[:5]):
        new_item = Item(
            section=item.section,
            line=item.line,
            summary=item.summary,
            source=item.source,
            rank=i + 1
        )
        ranked.append(new_item)

    return ranked


def render(brief: dict, now: datetime) -> str:
    day = now.astimezone().strftime("%A %Y-%m-%d")
    lines = [f"# Morning brief, {day}", ""]

    items = rank_items(_build_candidates(brief, now))

    for section in SECTIONS:
        section_items = [item for item in items if item.section == section]
        lines.append(f"## {section}")
        lines.append("")
        if section_items:
            lines.extend(item.to_md_line() for item in section_items)
        else:
            if section == "World & security":
                lines.append("- Nothing new yet.")
            elif section == "Research":
                lines.append("- Nothing from research digests today.")
            elif section == "Your day":
                lines.append("- No deadlines close.")
            elif section == "Your projects":
                lines.append("- Nothing is waiting on you.")
        lines.append("")

    prs = brief.get("open_prs") or []
    marvin = []
    for p in prs:
        if p.get("waiting_on_marvin"):
            repo = f"{p.get('repo', 'marvin')} " if p.get("repo") != "marvin" else ""
            marvin.append(f"- {repo}PR #{p['number']} {_sanitize(p['title'])}: your decisions are in"
                          f"{' and you asked a question' if p.get('question') else ''}")
    if marvin:
        lines.append("## Waiting on MARVIN")
        lines.append("")
        lines.extend(marvin)
        lines.append("")

    if brief.get("late_night"):
        lines.append("## Balance")
        lines.append("")
        lines.append(f"- Last night's last session was still going at {brief['late_night']}. Today's list above is what "
                    "matters; the rest can wait for tomorrow.")
        lines.append("")

    if brief.get("missing"):
        lines.append("## Gaps")
        lines.append("")
        lines.extend(f"- {m}" for m in brief["missing"])
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ── files and consumption ──────────────────────────────────────────────────────────────────────────────────────

def _day(now: datetime) -> str:
    return now.astimezone().strftime("%Y-%m-%d")


def write(now: datetime | None = None, sources: dict[str, Callable] | None = None, builder_reason: str = "primary") -> Path:
    now = now or datetime.now(timezone.utc)
    BRIEFS.mkdir(parents=True, exist_ok=True)
    path = BRIEFS / f"{_day(now)}.md"

    # Idempotent: don't overwrite an existing brief for today
    if path.exists():
        return path

    path.write_text(render(gather(now, sources), now))

    # Write sidecar tracking which machine built it
    import machine_profile
    label = machine_profile.machine_label()
    sidecar_path = BRIEFS / f"{_day(now)}.built-by"
    sidecar_path.write_text(f"{label}: {builder_reason}\n")

    return path


def build(now: datetime | None = None, sources: dict[str, Callable] | None = None) -> Path:
    """Build the morning brief for today. Checks fallback gate before building."""
    import brief_fallback
    now = now or datetime.now(timezone.utc)
    brief_path = BRIEFS / f"{_day(now)}.md"
    uh, um = brief_fallback.usual_time("morning-brief")  # the primary plist's own schedule
    decision = brief_fallback.should_run(local_path=brief_path, usual_hour=uh, usual_minute=um)
    if not decision.should_build:
        print(f"[morning-brief] {decision.reason} — skipping", file=sys.stderr)
        return brief_path
    return write(now, sources, builder_reason=decision.reason)


def show_today(now: datetime | None = None) -> str | None:
    now = now or datetime.now(timezone.utc)
    path = BRIEFS / f"{_day(now)}.md"
    if not path.exists():
        return None
    (BRIEFS / f"{_day(now)}.read").write_text(now.isoformat())
    return path.read_text()


def _dates(suffix: str) -> list[datetime]:
    return sorted(datetime.fromisoformat(p.stem).replace(tzinfo=timezone.utc)
                  for p in BRIEFS.glob(f"*{suffix}") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem))


def brief_dates() -> list[datetime]:
    return _dates(".md")


def read_dates() -> list[datetime]:
    return _dates(".read")


def builder_of(day: str) -> str | None:
    """Read the .built-by sidecar for a given day (YYYY-MM-DD format).
    Returns a string like "mac-mini: primary" or None if no sidecar exists."""
    sidecar_path = BRIEFS / f"{day}.built-by"
    if not sidecar_path.exists():
        return None
    try:
        return sidecar_path.read_text().strip()
    except Exception:
        return None


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        path = build()
        print(path)
    elif sys.argv[1:] == ["show"]:
        print(show_today() or "No brief for today yet.")
    else:
        sys.exit("usage: morning_brief.py build | show")
