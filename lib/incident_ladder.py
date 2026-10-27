#!/usr/bin/env python3
"""Solved problems stay solved: the incident ladder (design decided 2026-10-26; glossary: incident record, watch).

A fixed incident whose ticket carries a Recurrence check and the `watch` label is re-measured by the daily outcome
check every day after its check date (purpose_metrics.run calls `step`). Each rung runs only if the one before
didn't clear the probe:

  0. watch      re-measure the probe over the time since the incident's last recorded state (at most 7 days)
  1. first aid  run the ticket's '## First aid' steps, names from purpose_metrics.FIRST_AID only, on the Macs whose
                count tripped; then re-measure over the minutes since. No model call.
  2. reopen     still tripping: reopen the ticket (or comment, if it is open), add `regression`, and attach the
                evidence (probe value, scrubbed log lines from the window, which first aid ran, the original fixes)
  3. fix        queue the ticket for the existing pipeline (`ready-for-agent`) with an executor brief that requires a
                regression test failing on the current code first; at most one per incident per day
  4. you        rung 3 finished and the probe still trips: one notification saying what's waiting

The ticket's comments are the record, so a second Mac (or a second run) reads what the first one did and posts nothing
new: only a change of state (pass to fail, fail to pass) is posted. Only comments from the repo's owner, members or
collaborators count as the record, so an outside comment can't fake a state. A local log
(~/.claude/logs/incident-ladder.jsonl) feeds the measures and the morning brief; it is written only by the Mac that
ran the step, so summing the measures across Macs never counts twice.

Cost: one comments read per watched incident per day, plus one measure; first aid and evidence only on a trip.
Space: one log line per event (a trip, a fix, a notification), trimmed past LOG_MAX_LINES.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import purpose_metrics as pm  # noqa: E402

WATCH_LABEL = "watch"
REGRESSION_LABEL = "regression"
READY_LABEL = "ready-for-agent"
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
LOG_PATH = Path.home() / ".claude" / "logs" / "incident-ladder.jsonl"
LOG_MAX_LINES = 5000
MEASURE_DAYS = 30
MIN_WINDOW_S = 60
_MARK = re.compile(r"<!-- marvin:watch state=(pass|fail) at=(\S+)(?: aid=(\w+))? -->")
_RUNG3 = re.compile(r"<!-- marvin:rung3 day=(\d{4}-\d{2}-\d{2}) -->")
_RUNG4 = re.compile(r"<!-- marvin:rung4 at=(\S+) -->")
_NAME = re.compile(r"^\s*[-*]\s*`?([^`\s]+)`?\s*$", re.M)


# ── reading the ticket (parsed, never executed) ────────────────────────────────────────────────────────────────────

def _raw_section(body: str | None, heading: str) -> str | None:
    m = re.search(rf"^##\s*{heading}\s*$([\s\S]*?)(?=^##\s|\Z)", body if isinstance(body, str) else "", re.I | re.M)
    return m.group(1) if m else None


def first_aid_names(body: str | None) -> tuple[list[str], list[str]]:
    """(registered step names in order, anything else listed, defanged). Only a bullet that is exactly one name
    counts; a name not in purpose_metrics.FIRST_AID is never run."""
    text = _raw_section(body, "First aid")
    names, ignored = [], []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        m = _NAME.match(line)
        name = m.group(1) if m else None
        if name in pm.FIRST_AID and name not in names:
            names.append(name)
        elif line.strip().startswith(("-", "*")):
            ignored.append(pm._defang(line.strip(" -*`")))
    return names, ignored


def incident_record(body: str | None) -> dict:
    """What rung 3's executor needs: the root causes (prose), the original fix PRs and the ADRs the ticket names."""
    causes = (_raw_section(body, "Root causes") or "").strip()
    fixed = _raw_section(body, "Fixed by") or ""
    prs = list(dict.fromkeys(int(n) for n in re.findall(r"#(\d{1,6})\b", fixed)))
    adrs = list(dict.fromkeys(re.findall(r"\bADR\s*(\d{4})\b", body or "")))
    return {"root_causes": causes[:3000], "fix_prs": prs[:20], "adrs": adrs[:20]}


def _labels(issue: dict) -> set[str]:
    return {l.get("name") if isinstance(l, dict) else l for l in issue.get("labels") or []} - {None}


def is_watched(issue: dict) -> bool:
    spec = pm.parse(issue.get("body"))
    return bool(spec and spec.get("kind") == "recurrence" and WATCH_LABEL in _labels(issue))


# ── the record: the ticket's trusted comments ──────────────────────────────────────────────────────────────────────

def _trusted(comments: list) -> list[dict]:
    return [c for c in comments or [] if isinstance(c, dict) and isinstance(c.get("body"), str)
            and c.get("author_association") in TRUSTED]


def watch_state(comments: list, due: datetime) -> dict:
    """The incident's last recorded state: {"state", "at", "aid", "marked", "rung3_days", "rung4_at"}. With no marker,
    an earlier '## Outcome check' comment says it (✅ pass, ⚠️ fail); with neither, it's a fixed incident (pass)
    first measured on its check date."""
    st = {"state": "pass", "at": due, "aid": None, "marked": 0, "recorded": False, "rung3_days": set(), "rung4_at": None}
    for c in _trusted(comments):
        body = c["body"]
        for m in _MARK.finditer(body):
            when = pm._when(m.group(2))
            if when:
                st.update(state=m.group(1), at=when, aid=m.group(3), recorded=True)
                st["marked"] += 1
        if not st["marked"] and body.startswith(pm.OUTCOME_HEADING):
            when = pm._when(c.get("created_at")) or due
            st.update(state="pass" if body[len(pm.OUTCOME_HEADING):].lstrip().startswith("✅") else "fail", at=when)
            st["recorded"] = True
        st["rung3_days"] |= set(_RUNG3.findall(body))
        for m in _RUNG4.finditer(body):
            st["rung4_at"] = pm._when(m.group(1))
    return st


def _mark(state: str, now: datetime, aid: str | None = None) -> str:
    return f"<!-- marvin:watch state={state} at={now.isoformat()}{f' aid={aid}' if aid else ''} -->"


# ── GitHub (REST; bodies go through a file, never the command line) ────────────────────────────────────────────────

class GitHub:
    def __init__(self, repo: str):
        self.repo = repo

    def _api(self, *args: str) -> str:
        out = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise OSError(out.stderr.strip()[:200])
        return out.stdout

    def comments(self, n: int) -> list[dict]:
        return json.loads(self._api(f"repos/{self.repo}/issues/{n}/comments?per_page=100"))

    def comment(self, n: int, text: str) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(text)
        try:
            self._api(f"repos/{self.repo}/issues/{n}/comments", "-F", f"body=@{f.name}")
        finally:
            Path(f.name).unlink(missing_ok=True)

    def reopen(self, n: int) -> None:
        self._api("-X", "PATCH", f"repos/{self.repo}/issues/{n}", "-f", "state=open")

    def add_labels(self, n: int, names: list[str]) -> None:
        self._api(f"repos/{self.repo}/issues/{n}/labels", *[a for name in names for a in ("-f", f"labels[]={name}")])

    def remove_label(self, n: int, name: str) -> None:
        try:
            self._api("-X", "DELETE", f"repos/{self.repo}/issues/{n}/labels/{name}")
        except OSError:
            pass  # not there: nothing to remove

    def merged_prs_for(self, n: int, since: datetime) -> list[int]:
        """Pipeline PRs for this ticket (branch pipeline/<n>) merged at or after `since`: rung 3's fix."""
        prs = json.loads(self._api(f"repos/{self.repo}/pulls?state=closed&sort=updated&direction=desc&per_page=100"))
        return [p["number"] for p in prs if isinstance(p, dict) and _pipeline_branch(p, n)
                and (w := pm._when(p.get("merged_at"))) and w >= since]

    def open_prs_for(self, n: int) -> list[int]:
        """Open PRs the pipeline built for this ticket (its branch is pipeline/<n>)."""
        try:
            prs = json.loads(self._api(f"repos/{self.repo}/pulls?state=open&per_page=100"))
        except (OSError, ValueError):
            return []
        return [p["number"] for p in prs if isinstance(p, dict) and _pipeline_branch(p, n)]


def _pipeline_branch(pr: dict, n: int) -> bool:
    return bool(re.fullmatch(rf"pipeline/(?:[\w.-]+/[\w.-]+#)?{n}", (pr.get("head") or {}).get("ref", "")))


# ── the log (feeds the measures and the brief) ─────────────────────────────────────────────────────────────────────

def log_event(event: dict, path: Path | None = None) -> None:
    path = Path(path or LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(event, default=str) + "\n")
    try:
        lines = path.read_text().splitlines()
        if len(lines) > LOG_MAX_LINES:
            tmp = path.with_suffix(".tmp")
            tmp.write_text("\n".join(lines[-LOG_MAX_LINES // 2:]) + "\n")
            tmp.replace(path)
    except OSError:
        pass


def read_log(path: Path | None = None, days: float = MEASURE_DAYS, now: datetime | None = None) -> list[dict]:
    import github_usage
    cut = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    return [e for e in github_usage.read_jsonl(Path(path or LOG_PATH))
            if isinstance(e, dict) and (w := pm._when(e.get("at"))) and w >= cut]


# Any fix MARVIN made counts (the owner, 2026-10-27): first aid, its own code clearing it, and a rung-3 pipeline PR,
# whether it merged itself or with the owner's Approve. Only a clearing nobody can tie to MARVIN ("other") doesn't.
SELF_FIXERS = {"first-aid", "self-cleared", "rung-3-pr", "rung-3-auto"}


def recurrences(path: Path | None = None, now: datetime | None = None) -> float:
    """Times a watched incident came back over 30 days (lower is better)."""
    return float(sum(1 for e in read_log(path, now=now) if e.get("event") == "trip"))


def fixed_without_you(path: Path | None = None, now: datetime | None = None) -> float:
    """Of those, the ones MARVIN fixed: first aid, the symptom clearing on its own, or a rung-3 pipeline PR that
    merged, by itself or with the owner's Approve (higher is better)."""
    return float(sum(1 for e in read_log(path, now=now) if e.get("event") == "cleared" and e.get("fixer") in SELF_FIXERS))


def hours_to_fixed(path: Path | None = None, now: datetime | None = None) -> float:
    """Mean hours from a trip to its clearing, over 30 days (lower is better); 0 with nothing cleared."""
    hours = [float(e["hours"]) for e in read_log(path, now=now)
             if e.get("event") == "cleared" and isinstance(e.get("hours"), (int, float))]
    return round(sum(hours) / len(hours), 1) if hours else 0.0


def brief_lines(path: Path | None = None, now: datetime | None = None) -> list[dict]:
    """The last day's lines for the morning brief: {"kind": "fixed" | "needs-you", "line"}."""
    return [{"kind": e.get("brief_kind", "fixed"), "line": str(e["brief"])[:300]}
            for e in read_log(path, days=1, now=now) if e.get("brief")]


# ── one watched incident, one day ──────────────────────────────────────────────────────────────────────────────────

def _default_notify(title: str, message: str, url: str | None) -> None:
    import mr_notification
    mr_notification.notify_regression(title, message, url)


def _window_days(since: datetime, now: datetime) -> float:
    return min(pm.PROBE_WINDOW_DAYS, max((now - since).total_seconds(), MIN_WINDOW_S) / 86400)


def _fence(lines: list[str]) -> str:
    # A log line can't close the block, and can't carry a state marker into this (trusted) comment.
    return "\n".join(l.replace("```", "'''").replace("<!--", "<! --") for l in lines)


def _evidence_block(per_mac: dict[str, list[str]]) -> str:
    """Each Mac's lines in a code block, scrubbed again here (support.scrub) whatever the source did."""
    import support
    parts = []
    for mac, lines in per_mac.items():
        clean = [support.scrub(str(l)[:pm.EVIDENCE_LINE_CHARS]) for l in list(lines)[-pm.EVIDENCE_LINES:]]
        parts += [f"{support.scrub(str(mac))[:60]}:", "```text", _fence(clean) or "(nothing logged in the window)", "```"]
    return "\n".join(parts)


def executor_brief(issue: dict, spec: dict, record: dict) -> str:
    fixes = ", ".join(f"#{n}" for n in record["fix_prs"]) or "none listed"
    adrs = ", ".join(f"ADR {a}" for a in record["adrs"]) or "none listed"
    return "\n".join([
        "### What to build (rung 3: diagnose and fix the regression)",
        "",
        f"The fix for #{issue['number']} regressed: probe `{spec['measure']}` trips again and first aid didn't clear it. "
        "Use the diagnose skill (skills/diagnose/SKILL.md): build a feedback loop, reproduce, find which root cause "
        "came back (or what new one), then fix it.",
        "",
        f"- **Root causes on record:** see the ticket's '## Root causes' section.",
        f"- **The original fixes:** {fixes}. Read them first: a regression usually means one of them was undone or "
        "bypassed.",
        f"- **ADRs:** {adrs}.",
        "",
        "**Required: a regression test first.** Write a test that reproduces this regression and FAILS on the "
        "current code, before changing any non-test file. Then fix the code until it passes. Name it in the PR body "
        "under a '## Regression test' heading (file and test name). A PR without one that fails before the fix is "
        "not eligible to merge by itself.",
        "",
        "### How we'll try to break it",
        "",
        "- the regression test fails on the current code and passes after the fix;",
        "- the original incident's cases still pass (the fix PRs' tests are not weakened or deleted);",
        "- each dependency failing (network, GitHub, a missing or corrupt state file) leaves things no worse than before.",
    ])


def step(repo: str, issue: dict, now: datetime, gh=None, measure: Callable | None = None,
         first_aid: Callable | None = None, evidence: Callable | None = None, notify: Callable | None = None,
         log_path: Path | None = None) -> dict:
    """Rungs 0-4 for one watched incident. Returns what happened ({"number", "action", ...}). Never raises for a
    probe, a first-aid step or a notification failing; a GitHub write that fails stops the step (tried tomorrow)."""
    gh = gh or GitHub(repo)
    measure = measure or pm.measure_everywhere
    first_aid = first_aid or pm.first_aid_everywhere
    evidence = evidence or pm.evidence_everywhere
    notify = notify or _default_notify
    n = issue["number"]
    spec = pm.parse(issue.get("body"))
    due = pm.check_date(spec) if spec else None
    if not spec or spec.get("kind") != "recurrence" or not due or now < due:
        return {"number": n, "action": "not-due"}
    probe = spec["measure"]
    url = f"https://github.com/{repo}/issues/{n}"
    comments = gh.comments(n)
    st = watch_state(comments, due)
    days = pm.PROBE_WINDOW_DAYS if not st["recorded"] else _window_days(st["at"], now)

    def log(event: str, **kw) -> None:
        try:
            log_event({"at": now.isoformat(), "repo": repo, "number": n, "probe": probe, "event": event, **kw}, log_path)
        except OSError:
            pass

    def tell(title: str, message: str, kind: str) -> None:
        log("told", brief=message, brief_kind=kind)
        try:
            notify(title, message, url)
        except Exception:  # noqa: BLE001 -- a notification failing never stops the ladder
            pass

    def unchanged() -> bool:
        """Re-read the record just before writing: another Mac or run may have recorded a state since."""
        return watch_state(gh.comments(n), due)["marked"] == st["marked"]

    try:
        value, per = measure(probe, days)
    except Exception as exc:  # noqa: BLE001 -- measured again tomorrow; never claim a result we don't have
        log("not-measured", detail=str(exc)[:200])
        return {"number": n, "action": "not-measured"}
    op, bound = pm.target_value(spec)
    if pm.met(spec, value):
        if st["state"] == "pass" and st["recorded"]:
            return {"number": n, "action": "holding", "value": value}
        if not unchanged():
            return {"number": n, "action": "already-recorded"}
        if st["state"] == "pass":   # the first check of a watched fix
            gh.comment(n, pm.outcome_text(issue, spec, value, per, True, None) + "\n\nWatched daily from now on "
                       "(`watch`): only a change is posted here.\n" + _mark("pass", now))
            return {"number": n, "action": "first-pass", "value": value}
        hours = round((now - st["at"]).total_seconds() / 3600, 1)
        try:
            fixed_by = gh.merged_prs_for(n, st["at"])
        except Exception:  # noqa: BLE001 -- unknown who fixed it: count it as not MARVIN's
            fixed_by = []
        by = f" Fixed by MARVIN's PR {', '.join(f'#{p}' for p in fixed_by)}." if fixed_by else ""
        gh.comment(n, f"## Regression cleared\n\nProbe **{probe}** = **{value:g}** again (holds at {op} {bound:g}), "
                      f"{hours:g} h after it came back.{by}\n" + _mark("pass", now))
        gh.remove_label(n, pm.MISSED_LABEL)
        log("cleared", fixer="rung-3-pr" if fixed_by else "other", hours=hours, prs=fixed_by)
        if fixed_by:
            tell("MARVIN fixed a regression itself",
                 f"MARVIN fixed a regression of #{n} itself: PR {', '.join(f'#{p}' for p in fixed_by)}, and {probe} holds again.",
                 "fixed")
        return {"number": n, "action": "cleared", "value": value}

    # ── it tripped: rung 1, first aid ──
    steps, ignored = first_aid_names(issue.get("body"))
    only = {k for k, v in per.items() if v > 0} or None
    aid_results, after, aid = [], value, None
    if steps and st["aid"] != "worse":
        started = datetime.now(timezone.utc)
        try:
            live_before, _ = measure(probe, MIN_WINDOW_S / 86400)
        except Exception:  # noqa: BLE001
            live_before = None
        for name in steps:
            try:
                aid_results += first_aid(name, only)
            except Exception as exc:  # noqa: BLE001
                aid_results.append({"step": name, "ok": False, "changed": False, "mac": "?", "detail": str(exc)[:200]})
        try:
            after, _ = measure(probe, _window_days(started, datetime.now(timezone.utc)))
        except Exception:  # noqa: BLE001 -- can't tell whether it helped: treat as still tripping
            after = value
        aid = "worse" if live_before is not None and after > live_before else "ran"
        log("first-aid", steps=steps, results=aid_results, before=live_before, after=after)
    aid_lines = [f"- `{r.get('step')}` on {r.get('mac')}: {'ok' if r.get('ok') else 'failed'}"
                 f"{', changed something' if r.get('changed') else ''}: {str(r.get('detail', ''))[:300]}"
                 for r in aid_results] or ["- none listed in the ticket's '## First aid'" if not steps
                                            else "- skipped: first aid made it worse last time"]
    aid_lines += [f"- ignored (not a registered step): `{x}`" for x in ignored]

    if steps and aid != "worse" and pm.met(spec, after):
        if not unchanged():
            return {"number": n, "action": "already-recorded"}
        changed = any(r.get("changed") for r in aid_results)
        fixer = "first-aid" if changed else "self-cleared"
        hours = round((now - st["at"]).total_seconds() / 3600, 1) if st["state"] == "fail" else 0.0
        if st["state"] == "pass":
            log("trip", value=value)
        gh.comment(n, "\n".join([f"## Regression fixed by first aid" if changed else "## Regression cleared on its own",
                                 "", f"Probe **{probe}** read **{value:g}** (holds at {op} {bound:g}); after first aid "
                                 f"it reads **{after:g}**.", "", "**First aid**", "", *aid_lines, "", _mark("pass", now)]))
        gh.remove_label(n, pm.MISSED_LABEL)
        log("cleared", fixer=fixer, hours=hours)
        if changed:
            tell("MARVIN fixed a regression itself",
                 f"MARVIN fixed a regression of #{n} itself: {probe} came back and first aid ({', '.join(steps)}) cleared it.",
                 "fixed")
        else:
            log("told", brief=f"A regression of #{n} ({probe}) came back and had cleared on its own by the time first aid ran.", brief_kind="fixed")
        return {"number": n, "action": "first-aid-fixed" if changed else "self-cleared", "value": after}

    # ── still tripping ──
    if st["state"] == "fail":
        return _rung4(repo, issue, n, probe, st, gh, now, tell, log, unchanged)
    if not unchanged():
        return {"number": n, "action": "already-recorded"}
    log("trip", value=value)
    record = incident_record(issue.get("body"))
    try:
        ev = evidence(probe, days, only)
    except Exception as exc:  # noqa: BLE001
        ev = {"?": [f"(couldn't read the logs: {type(exc).__name__})"]}
    labels = _labels(issue)
    import ticket_policy
    person = ticket_policy.needs_person(labels) or labels & {"pinned", "hold", "held"}
    today = now.strftime("%Y-%m-%d")
    queue = not person and today not in st["rung3_days"]
    worse = "\n\n**First aid made it worse** (re-measured higher than before it ran); it won't run again for this " \
            "recurrence." if aid == "worse" else ""
    body = "\n".join([
        f"## Regression: {probe} came back", "",
        f"Probe **{probe}** = **{value:g}** (holds at {op} {bound:g}) over the "
        f"{days * 24:.0f} h since the last recorded state. It counts {pm.PROBES[probe][2]}. Per Mac: "
        + ", ".join(f"{k} {v:g}" for k, v in per.items()) + ".", "",
        "**First aid** (in order, then re-measured: " + (f"**{after:g}**" if steps else "nothing to run") + ")", "",
        *aid_lines, worse, "",
        "**Evidence** (log lines from the window, scrubbed)", "", _evidence_block(ev), "",
        "**Original fixes:** " + (", ".join(f"#{p}" for p in record["fix_prs"]) or "none listed") + ".", "",
        executor_brief(issue, spec, record) if queue else
        ("A person holds this ticket, so no fix build was queued." if person else "A fix build already ran today."),
        "", _mark("fail", now, aid), *([f"<!-- marvin:rung3 day={today} -->"] if queue else [])])
    if issue.get("state") == "closed":
        gh.reopen(n)
    gh.comment(n, body)
    gh.add_labels(n, [REGRESSION_LABEL, pm.MISSED_LABEL, *([READY_LABEL] if queue else [])])
    log("reopened", queued=queue)
    if queue:
        log("rung3-queued")
    tell("MARVIN: a solved problem came back",
         f"Regression: #{n} {probe} came back. First aid {'made it worse' if aid == 'worse' else 'failed' if steps else 'had nothing to try'}; "
         + ("a fix build is queued." if queue else "no fix build was queued: it needs you."), "needs-you")
    return {"number": n, "action": "reopened", "queued": queue, "value": value}


def _rung4(repo, issue, n, probe, st, gh, now, tell, log, unchanged) -> dict:
    """Still failing after its recurrence was recorded: once rung 3's build is no longer queued or running, say
    what's waiting, once per recurrence."""
    labels = _labels(issue)
    building = READY_LABEL in labels or any(l.startswith("claimed:") for l in labels)
    if building or (st["rung4_at"] and st["rung4_at"] >= st["at"]):
        return {"number": n, "action": "still-failing"}
    if not unchanged():
        return {"number": n, "action": "already-recorded"}
    prs = gh.open_prs_for(n)
    why = (f"Fix PR {', '.join(f'#{p}' for p in prs)} is waiting for you." if prs else
           "No fix PR could be made: the pipeline's notes are on this ticket.")
    gh.comment(n, f"## Regression still there\n\nProbe **{probe}** still trips and first aid failed. {why}\n"
                  f"<!-- marvin:rung4 at={now.isoformat()} -->")
    log("rung4", prs=prs)
    tell("MARVIN couldn't fix a regression", f"Regression: #{n} {probe} regressed. First aid failed. {why}", "needs-you")
    return {"number": n, "action": "rung4", "prs": prs}
