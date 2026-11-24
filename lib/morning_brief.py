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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import brief_items as bi

CLAUDE = Path.home() / ".claude"
BRIEFS = CLAUDE / "briefs"
HEALTH_STATUS = CLAUDE / "logs" / "health-status.json"
OVERRIDES = CLAUDE / "catalog" / "overrides.json"
REPOS = ("G-Eskayo/marvin", "G-Eskayo/clarity-captions", "G-Eskayo/marvin-mobile")
DEADLINE_HORIZON_DAYS = 45


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


# ── item builders (each returns list[dict] with section, tier, line) ────────────────────────────────────────

def _your_projects_items(now: datetime) -> tuple[list[dict], list[str]]:
    """Your projects: immediate work and decisions for the day.

    Wraps each reader individually so one failure does not drop the whole section.
    Returns (items, failures) where failures are reader-level errors to report in Gaps.
    """
    items = []
    failures = []

    # Tier 0: regressions needing you, red checks (each reader separately)
    try:
        for r in _regressions(now):
            if r.get("kind") == "needs-you":
                items.append(bi.make_item("your_projects", 0, r["line"]))
    except Exception as e:  # noqa: BLE001 -- regressions failure does not kill the brief
        failures.append(f"couldn't read regressions ({str(e)[:80]})")

    try:
        for c in _red_checks():
            items.append(bi.make_item("your_projects", 0, f"{c['label']}: {c['detail']}"))
    except Exception as e:  # noqa: BLE001 -- red checks failure does not kill the brief
        failures.append(f"couldn't read red checks ({str(e)[:80]})")

    # Tier 1: auto-merge decision, PRs needing review, human tickets (each reader separately)
    try:
        am = _auto_merge_report()
        if am:
            items.append(bi.make_item("your_projects", 1, am))
    except Exception as e:  # noqa: BLE001 -- auto-merge failure does not kill the brief
        failures.append(f"couldn't read auto-merge report ({str(e)[:80]})")

    try:
        for p in _open_prs():
            if not p.get("waiting_on_marvin"):
                items.append(bi.make_item("your_projects", 1, _ref(p, pr=True), number=p["number"], repo=p["repo"]))
            else:
                # Store waiting PRs as special items (marked so render() knows to handle them)
                suffix = " and you asked a question" if p.get("question") else ""
                items.append(bi.make_item("your_projects", 1,
                                         f"{_ref(p, pr=True)}: your decisions are in{suffix}",
                                         number=p["number"], repo=p["repo"], waiting_on_marvin=True))
    except Exception as e:  # noqa: BLE001 -- open PRs failure does not kill the brief
        failures.append(f"couldn't read open PRs ({str(e)[:80]})")

    try:
        for t in _human_tickets():
            items.append(bi.make_item("your_projects", 1, f"Your task: {_ref(t)}", number=t["number"], repo=t["repo"]))
    except Exception as e:  # noqa: BLE001 -- human tickets failure does not kill the brief
        failures.append(f"couldn't read human tickets ({str(e)[:80]})")

    # Tier 2: top tickets by priority
    try:
        for t in _top_tickets():
            # _top_tickets already returns sorted by priority, so insertion order is preserved
            items.append(bi.make_item("your_projects", 2, f"{t['priority']}: {_ref(t)}", number=t["number"], repo=t["repo"]))
    except Exception as e:  # noqa: BLE001 -- top tickets failure does not kill the brief
        failures.append(f"couldn't read top tickets ({str(e)[:80]})")

    # Tier 3: digest idea
    try:
        idea = _digest_idea(now)
        if idea:
            items.append(bi.make_item("your_projects", 3, f"**Compounding move:** {idea}"))
    except Exception as e:  # noqa: BLE001 -- digest idea failure does not kill the brief
        failures.append(f"couldn't read digest idea ({str(e)[:80]})")

    return items, failures


def _your_day_items(now: datetime) -> list[dict]:
    """Your day: deadlines and calendar-based urgency."""
    items = []
    for d in _deadlines(now):
        days = _days_until(d["date"], now)
        # Tier by urgency: hard + ≤7 days highest
        tier = 0 if (d["hard"] and days <= 7) else (1 if days <= 7 else 2)
        items.append(bi.make_item("your_day", tier,
                                   f"{d['project']}: {days} days ({d['date']}{', hard deadline' if d['hard'] else ''})"))
    return items


def _research_items(now: datetime) -> list[dict]:
    """Research: ideas and insights."""
    items = []
    idea = _research_idea(now)
    if idea:
        items.append(bi.make_item("research", 2, f"**From research:** {idea}"))
    return items


def _world_security_items(now: datetime) -> list[dict]:
    """World security: not yet implemented."""
    return []


def default_sources(now: datetime) -> dict[str, Callable]:
    return {"your_projects": lambda: _your_projects_items(now), "your_day": lambda: _your_day_items(now),
            "research": lambda: _research_items(now), "world_security": lambda: _world_security_items(now)}


_SOURCE_NAMES = {"your_projects": "your projects items", "your_day": "your day items",
                 "research": "research items", "world_security": "world security items"}


def gather(now: datetime, sources: dict[str, Callable] | None = None) -> dict:
    """Gather items from all sources and rank/cap them. Returns {items, waiting, missing}.

    Waiting PRs (waiting_on_marvin=True) are stored separately so they don't consume
    slots in the 5-item cap; they're shown in a separate "Waiting on MARVIN" section.

    Builders can return either a list of items, or a tuple (items, reader_failures).
    Reader failures are added to missing so they appear in the Gaps section.
    """
    sources = sources or default_sources(now)
    items, missing = [], []
    for key, builder in sources.items():
        try:
            result = builder()
            # Handle both old-style (list) and new-style (tuple) returns from builders
            if isinstance(result, tuple):
                source_items, reader_failures = result
                items.extend(source_items or [])
                missing.extend(reader_failures or [])
            else:
                items.extend(result or [])
        except Exception as exc:  # noqa: BLE001 -- a brief with a named gap beats no brief
            missing.append(f"couldn't read {_SOURCE_NAMES.get(key, key)} ({str(exc)[:80]})")

    # Separate waiting items (shown separately, don't count toward cap)
    waiting = [i for i in items if i.get("waiting_on_marvin")]
    regular = [i for i in items if not i.get("waiting_on_marvin")]

    bi.rank_and_cap(regular)
    return {"items": regular, "waiting": waiting, "missing": missing}


def _ref(item: dict, pr: bool = False) -> str:
    repo = f"{item['repo']} " if item.get("repo") and item["repo"] != "marvin" else ""
    return f"{repo}{'PR ' if pr else ''}#{item['number']} {item['title']}"


def render(brief: dict, now: datetime) -> str:
    """Render the brief as markdown, using brief_items to structure sections.

    Items are the main content (capped at 5 total). Waiting PRs are shown separately
    in "Waiting on MARVIN" and don't count toward the cap.
    """
    day = now.astimezone().strftime("%A %Y-%m-%d")
    items = brief.get("items") or []
    waiting_items = brief.get("waiting") or []

    lines = [f"# Morning brief, {day}", ""]
    if items:
        lines.append(bi.render_sections(items))
        lines.append("")
    else:
        lines.append("## Needs you")
        lines.append("")
        lines.append("- Nothing is waiting on you.")
        lines.append("")

    # Add "Waiting on MARVIN" section (PRs where decisions are in, shown separately)
    if waiting_items:
        lines += ["## Waiting on MARVIN", ""]
        for item in waiting_items:
            lines.append(f"- {item['line']}")
        lines.append("")

    if brief.get("missing"):
        lines += ["## Gaps", "", *[f"- {m}" for m in brief["missing"]], ""]

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

    brief = gather(now, sources)
    path.write_text(render(brief, now))

    # Write items JSON store for future consumption (includes waiting items)
    items_path = BRIEFS / f"{_day(now)}.json"
    all_items = brief["items"] + brief.get("waiting", [])
    items_path.write_text(json.dumps(all_items, indent=2))

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


def read_items(now: datetime | None = None) -> list[dict] | None:
    """Read the items JSON store for a given day, or None if missing/corrupted."""
    now = now or datetime.now(timezone.utc)
    items_path = BRIEFS / f"{_day(now)}.json"
    if not items_path.exists():
        return None
    try:
        return json.loads(items_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def show_today(now: datetime | None = None) -> str | None:
    now = now or datetime.now(timezone.utc)
    path = BRIEFS / f"{_day(now)}.md"
    if not path.exists():
        return None
    (BRIEFS / f"{_day(now)}.read").write_text(now.isoformat())

    # Try to read the brief markdown; tolerate missing/corrupted JSON sidecar
    try:
        return path.read_text()
    except OSError:
        return None


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
