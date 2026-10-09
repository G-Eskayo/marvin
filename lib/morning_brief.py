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

CLAUDE = Path.home() / ".claude"
BRIEFS = CLAUDE / "briefs"
HEALTH_STATUS = CLAUDE / "logs" / "health-status.json"
OVERRIDES = CLAUDE / "catalog" / "overrides.json"
REPOS = ("G-Eskayo/marvin", "G-Eskayo/clarity-captions", "G-Eskayo/marvin-mobile")
DEADLINE_HORIZON_DAYS = 45
LATE_HOUR = 23  # local time; a session still active after this counts as a late night


# ── sources (each is a small reader; gather() tolerates any of them failing) ──────────────────────────────────

def _gh(path: str):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise OSError(out.stderr.strip()[:200] or "gh failed")
    return json.loads(out.stdout)


def _open_prs() -> list[dict]:
    prs = []
    for repo in REPOS:
        for p in _gh(f"repos/{repo}/pulls?state=open&per_page=50"):
            prs.append({"number": p["number"], "title": p["title"], "repo": repo.split("/")[1]})
    return prs


def _red_checks() -> list[dict]:
    data = json.loads(HEALTH_STATUS.read_text())
    return [c for c in data.get("checks", []) if c.get("severity") == "red"]


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


def default_sources(now: datetime) -> dict[str, Callable]:
    return {"open_prs": _open_prs, "red_checks": _red_checks, "human_tickets": _human_tickets,
            "launches": lambda: _launches(now), "merged": lambda: _merged(now), "deadlines": lambda: _deadlines(now),
            "top_tickets": _top_tickets, "digest_idea": lambda: _digest_idea(now),
            "research_idea": lambda: _research_idea(now), "late_night": lambda: _late_night(now),
            "auto_merge": _auto_merge_report}


_SOURCE_NAMES = {"open_prs": "open PRs", "red_checks": "Health", "human_tickets": "tickets waiting on you",
                 "launches": "the launch log", "merged": "merged PRs", "deadlines": "deadlines",
                 "top_tickets": "top tickets", "digest_idea": "the daily digest", "research_idea": "the research digest",
                 "late_night": "last night's sessions", "auto_merge": "auto-merge's shadow report"}


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


def _ref(item: dict, pr: bool = False) -> str:
    repo = f"{item['repo']} " if item.get("repo") and item["repo"] != "marvin" else ""
    return f"{repo}{'PR ' if pr else ''}#{item['number']} {item['title']}"


def render(data: dict, now: datetime) -> str:
    day = now.astimezone().strftime("%A %Y-%m-%d")
    lines = [f"# Morning brief, {day}", ""]
    needs = [f"- {data['auto_merge']}"] if data.get("auto_merge") else []
    needs += [f"- Review {_ref(p, pr=True)}" for p in data.get("open_prs") or []]
    needs += [f"- {c['label']}: {c['detail']}" for c in data.get("red_checks") or []]
    needs += [f"- Your task: {_ref(t)}" for t in data.get("human_tickets") or []]
    lines += ["## Needs you", "", *(needs or ["- Nothing is waiting on you."]), ""]

    runs = data.get("launches") or []
    merged = data.get("merged") or []
    overnight = []
    if runs:
        by_kind: dict[str, int] = {}
        for r in runs:
            by_kind[r.get("kind", "?")] = by_kind.get(r.get("kind", "?"), 0) + 1
        cost = sum(r.get("cost_usd") or 0 for r in runs)
        overnight.append(f"- {len(runs)} model runs (" + ", ".join(f"{n} {k}" for k, n in sorted(by_kind.items()))
                         + f"), ${cost:.2f}")
    overnight += [f"- Merged {_ref(p, pr=True)}" for p in merged]
    lines += ["## Overnight", "", *(overnight or ["- Quiet: no model runs or merges in the last day."]), ""]

    today = []
    for d in data.get("deadlines") or []:
        days = _days_until(d["date"], now)
        today.append(f"- {d['project']}: {days} days ({d['date']}{', hard deadline' if d['hard'] else ''})")
    today += [f"- {t['priority']}: {_ref(t)}" for t in data.get("top_tickets") or []]
    lines += ["## Today", "", *(today or ["- No deadlines close and nothing marked p0/p1."]), ""]

    ideas = [f"- **Compounding move:** {data['digest_idea']}"] if data.get("digest_idea") else []
    ideas += [f"- **From research:** {data['research_idea']}"] if data.get("research_idea") else []
    if ideas:
        lines += ["## One idea each", "", *ideas, ""]

    if data.get("late_night"):
        lines += ["## Balance", "",
                  f"- Last night's last session was still going at {data['late_night']}. Today's list above is what "
                  "matters; the rest can wait for tomorrow.", ""]
    if data.get("missing"):
        lines += ["## Gaps", "", *[f"- {m}" for m in data["missing"]], ""]
    return "\n".join(lines).rstrip() + "\n"


# ── files and consumption ──────────────────────────────────────────────────────────────────────────────────────

def _day(now: datetime) -> str:
    return now.astimezone().strftime("%Y-%m-%d")


def write(now: datetime | None = None, sources: dict[str, Callable] | None = None) -> Path:
    now = now or datetime.now(timezone.utc)
    BRIEFS.mkdir(parents=True, exist_ok=True)
    path = BRIEFS / f"{_day(now)}.md"
    path.write_text(render(gather(now, sources), now))
    return path


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


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        print(write())
    elif sys.argv[1:] == ["show"]:
        print(show_today() or "No brief for today yet.")
    else:
        sys.exit("usage: morning_brief.py build | show")
