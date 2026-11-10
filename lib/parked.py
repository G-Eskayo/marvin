#!/usr/bin/env python3
"""Parked choices (marvin#1222; piece 3 of instance/docs/plans/data-freshness-2026-11-09.md).

Triage sat "propose until <the owner> decides" for 19 days with 562 proposals, written in a config comment no one would read
again. A memory note said "conflicts with the 11-02 handoff, ask <the owner>" while its blocker (ticket 715) closed the same
day, and nothing noticed. An open question has one home: a ticket with a Decisions block and a review-by date.
Everywhere else names that ticket and never restates the question.

The grammar (ticket_policy.parse_revisit_comment's rules, the same "Revisit by: date [— #N closes]" the revisit agent
reads):

    config, any config/ or instance/config/ JSON:   "parked": {"triage": {"decision": "<owner>/marvin#1220",
                                                     "review_by": "2026-11-16", "condition": "#715 closes",
                                                     "what": "triage acts again"}}
    memory front matter:                            open_question: G-Eskayo/marvin#N
                                                    review_by: YYYY-MM-DD      (condition: "#N closes", optional)

A parked choice may sit 7 days (Gil, 2026-11-09), so review_by is at most a week out when it's written. It's due when
review_by passes, or when its condition ticket (bare #N = the decision's repo, or owner/repo#N) closes. Flagged: a
decision ticket GitHub can't read, one with no Decisions block, a closed one (answered: remove the park), a garbled
entry, the same park in two files.

  report()   every park, judged in one GitHub call (lib/resume_check.fetch)
  row()      the health row parked:overdue (yellow on overdue or flagged; unknown, never green, if GitHub can't be
             read and nothing is due by date alone)
  sweep()    on the hourly scan: an overdue park's decision ticket goes to Needs you (needs-info, hold off) with one
             comment. It's idempotent: a ticket already in Needs you is left alone, so it fires once, not hourly, and
             two Macs sweeping make the same single change.

    parked.py [--sweep]   print the report (and run the sweep)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
CHECK_ID, CHECK_LABEL = "parked:overdue", "Parked choices come back when due"
REVIEW_DAYS = 7
_REF = re.compile(r"^([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d{1,6})$")
_COND = re.compile(r"(?:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#(\d{1,6})\s+closes\b", re.I)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NEEDS_YOU, HOLD = "needs-info", "hold"


def config_dirs() -> list[Path]:
    import instance
    return [ROOT / "config", instance.path("config")]


def _memory_dir() -> Path | None:
    try:
        import host_os
        return host_os.memory_dir()
    except Exception:  # noqa: BLE001
        return None


def _entry(pid, raw, source) -> dict:
    import ticket_policy
    e = {"id": str(pid), "source": str(source), "problems": [], "decision": None, "revisit": None, "what": None,
         "condition_ref": None}
    if not isinstance(raw, dict):
        e["problems"].append("not an object")
        return e
    e["what"] = str(raw.get("what") or pid)[:120]
    dec = str(raw.get("decision") or "").strip()
    if not dec:
        e["problems"].append("names no decision ticket")
    elif not _REF.match(dec):
        e["problems"].append(f"decision '{dec[:40]}' is not owner/repo#N")
    else:
        e["decision"] = dec
    review = str(raw.get("review_by") or "").strip()
    cond = str(raw.get("condition") or "").strip()
    if not review:
        e["problems"].append("no review_by")
    else:
        rv = ticket_policy.parse_revisit_comment(f"Revisit by: {review}" + (f" — {cond}" if cond else "")) \
            if _DATE.match(review) else None
        if rv is None:
            e["problems"].append(f"review_by '{review[:20]}' is not YYYY-MM-DD")
        else:
            e["revisit"] = rv
    m = _COND.search(cond) if cond else None
    if m and e["decision"]:
        e["condition_ref"] = f"{m.group(1) or e['decision'].split('#')[0]}#{m.group(2)}"
    return e


def entries(config_dirs: list[Path] | None = None, memory_dir: Path | None = None) -> list[dict]:
    """Every park in config JSON and memory front matter, garbled ones included (with their problems)."""
    out = []
    for d in config_dirs if config_dirs is not None else globals()["config_dirs"]():
        for f in sorted(Path(d).rglob("*.json")) if Path(d).is_dir() else []:
            try:
                data = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and isinstance(data.get("parked"), dict):
                out += [_entry(k, v, f) for k, v in data["parked"].items()]
    mem = memory_dir if memory_dir is not None else _memory_dir()
    if mem and Path(mem).is_dir():
        import memory_lint
        for f in sorted(Path(mem).glob("*.md")):
            try:
                fields, _ = memory_lint._frontmatter(f.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            if fields.get("open_question"):
                out.append(_entry(f.stem, {"decision": fields.get("open_question"), "review_by": fields.get("review_by"),
                                           "condition": fields.get("condition"), "what": fields.get("description")}, f))
    return out


def _labels(node: dict) -> set[str]:
    return {(x or {}).get("name") for x in ((node.get("labels") or {}).get("nodes") or [])} - {None}


def report(config_dirs: list[Path] | None = None, memory_dir: Path | None = None, *, run=subprocess.run,
           now: datetime | None = None, node=True) -> dict:
    import resume_check as rc
    import decisions_check
    now = now or datetime.now(UTC)
    today = now.date()
    es = entries(config_dirs, memory_dir)
    out = {"status": "checked", "reason": None, "parked": len(es), "overdue": [], "flagged": [], "tickets": {}}
    seen = {}
    for e in es:
        for p in e["problems"]:
            out["flagged"].append({"id": e["id"], "source": e["source"], "problem": p})
        key = (e["id"], e["decision"])
        if key in seen:
            out["flagged"].append({"id": e["id"], "source": e["source"], "problem": f"also parked in {seen[key]}"})
        seen.setdefault(key, e["source"])
    good = [e for e in es if not e["problems"]]
    keys = list(dict.fromkeys([k for e in good for k in (e["decision"], e["condition_ref"]) if k]))
    nodes = {}
    if keys:
        try:
            nodes = rc.fetch(keys, run=run, timeout=rc.BUDGET_S, with_body=True)
        except RuntimeError as err:
            out["status"], out["reason"] = "unverified", str(err)
    out["tickets"] = nodes
    done = set()
    for e in good:
        if (e["id"], e["decision"]) in done:
            continue
        done.add((e["id"], e["decision"]))
        review = datetime.fromisoformat(e["revisit"]["date"]).date()
        why = "review-by passed" if today >= review else None
        if out["status"] == "checked":
            t = nodes.get(e["decision"])
            if not t:
                out["flagged"].append({"id": e["id"], "source": e["source"],
                                       "problem": f"decision ticket {e['decision']} couldn't be read (deleted or private?)"})
                continue
            if t.get("state") == "CLOSED":
                out["flagged"].append({"id": e["id"], "source": e["source"],
                                       "problem": f"decision ticket {e['decision']} is closed: answered, so remove the park"})
                continue
            parsed = decisions_check.parse(t.get("body") or "", node=node)
            if parsed is not None and not (parsed.get("present") and not parsed.get("problems")):
                out["flagged"].append({"id": e["id"], "source": e["source"],
                                       "problem": f"decision ticket {e['decision']} has no Decisions block the owner can answer"})
                continue
            if e["condition_ref"]:
                c = nodes.get(e["condition_ref"])
                if not c:
                    out["flagged"].append({"id": e["id"], "source": e["source"],
                                           "problem": f"condition ticket {e['condition_ref']} couldn't be read (deleted?)"})
                    continue
                if c.get("state") == "CLOSED" and not why:
                    why = f"its condition came true ({e['condition_ref']} closed)"
        if why:
            out["overdue"].append({"id": e["id"], "what": e["what"], "decision": e["decision"], "source": e["source"],
                                   "why": why, "days_over": max(0, (today - review).days)})
    return out


def row(r: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    parts = [f"{o['what']}: {o['why']}" + (f" {o['days_over']} days ago" if o["why"] == "review-by passed" else "")
             + f", waiting on you (Decision: {o['decision']})" for o in r["overdue"][:4]]
    parts += [f"{f['id']} ({Path(f['source']).name}): {f['problem']}" for f in r["flagged"][:4]]
    tail = f" · couldn't check GitHub: {r['reason']}" if r["status"] == "unverified" else ""
    if parts:
        sev, detail = "yellow", "; ".join(parts) + tail
    elif r["status"] == "unverified":
        sev, detail = "unknown", f"couldn't check {r['parked']} parked choice(s): {r['reason']}"
    else:
        sev, detail = "green", f"{r['parked']} parked choice(s), none due"
    return {"id": CHECK_ID, "label": CHECK_LABEL, "severity": sev, "detail": detail, "checked_at": now.isoformat(),
            "value": len(r["overdue"]) + len(r["flagged"])}


def _gh(args: list[str]) -> str:
    gh = Path.home() / ".agents" / "bin" / "gh"
    p = subprocess.run([str(gh) if gh.exists() else "gh", *args], capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise OSError(p.stderr.strip()[:200])
    return p.stdout


def sweep(r: dict, gh=_gh) -> list[str]:
    """Each overdue park's decision ticket into Needs you, once. Returns the tickets changed."""
    changed = []
    for o in r["overdue"]:
        t = (r.get("tickets") or {}).get(o["decision"])
        if not t:
            continue  # GitHub couldn't be read: change nothing on a guess
        labels = _labels(t)
        if NEEDS_YOU in labels and HOLD not in labels:
            continue  # already in Needs you: nothing to do (once, not hourly)
        repo, n = o["decision"].split("#")
        args = ["issue", "edit", n, "-R", repo, "--add-label", NEEDS_YOU]
        if HOLD in labels:
            args += ["--remove-label", HOLD]
        try:
            gh(args)
            gh(["issue", "comment", n, "-R", repo, "--body",
                f"Parked choice due ({o['why']}): {o['what']}. It was parked in `{Path(o['source']).name}`; "
                f"it's back in Needs you so the Decisions above get an answer (lib/parked.py, marvin#1222)."])
        except OSError:
            continue
        changed.append(o["decision"])
    return changed


def main(argv: list[str]) -> int:
    r = report()
    print(json.dumps(row(r), indent=2))
    if "--sweep" in argv:
        print("swept:", sweep(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
