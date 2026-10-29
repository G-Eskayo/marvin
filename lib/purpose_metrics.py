#!/usr/bin/env python3
"""Purpose metrics and outcome checks (marvin#304; glossary: purpose metric, outcome check, missed-purpose diagnosis).

A ticket whose purpose is measurable (faster, fewer tokens, fewer refusals) carries a section:

    ## Purpose metric
    - **Measure:** headless-refusals-per-week     (a name from MEASURES below, never code or a command)
    - **Baseline:** 376
    - **Target:** -70%                             (or +N%, "<= N", ">= N"; lower is better unless stated)
    - **Check on:** 2026-10-15

and the `purpose-metric` label. A fix (a `bug` ticket) whose effect isn't a number carries a **recurrence check**
instead: a named probe (a symptom counter registered in PROBES below, never text from the ticket) that passes when
the symptom has not come back:

    ## Recurrence check
    - **Probe:** gh-watch-change-storm            (a name from PROBES; its threshold is the target)
    - **Baseline:** 570                            (optional: the symptom's size when it was fixed)
    - **Check on:** 2026-11-02: the symptom has not come back   (7+ days after the fix ships: probes look back 7 days)

Every fix carries one or the other (decided 2026-10-26); the PR's fit check warns when it doesn't. Once the date has passed, the daily outcome check measures it on every Mac,
comments the result on the ticket, and on a miss writes a **missed-purpose diagnosis** (what was intended, what
was measured, the likely why, the options) and adds the `missed-purpose` label, which Health shows red until
someone decides. The ticket's own comments are the record, so both Macs can run the check without posting twice.

    purpose_metrics.py check                 # the daily outcome check (run by the cleanup sweep)
    purpose_metrics.py measure <name> --local  # one measure on this Mac only (how the other Mac is asked over ssh)
    purpose_metrics.py first-aid <name> --local  # one registered first-aid step on this Mac (asked over ssh)

A watched incident (Recurrence check + the `watch` label) is re-measured every day and, when it trips, climbs the
incident ladder: first aid, reopen with evidence, a pipeline fix (lib/incident_ladder.py).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

LABEL = "purpose-metric"
MISSED_LABEL = "missed-purpose"
BUG_LABEL = "bug"
OUTCOME_HEADING = "## Outcome check"
REPOS = ("G-Eskayo/marvin",)
SSH_OPTS = ["-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]


# ── measures: named, reviewed code. A ticket can only pick one. ───────────────────────────────────────────

def _headless_bash(days: int = 7) -> tuple[int, int]:
    """(refused, total) Bash calls in headless runs over the last `days`: refused = by the run's own dontAsk
    allowlist (the #277 baseline's measurement)."""
    import tool_usage as tu
    cut = datetime.now(timezone.utc) - timedelta(days=days)
    denied = total = 0
    for f in tu.find_transcripts(tu.TRANSCRIPTS, window_days=days):
        pending = {}
        for line in f.read_text(errors="ignore").splitlines():
            if '"tool_use' not in line and '"tool_result"' not in line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = (d.get("message") or {}).get("content")
            if not isinstance(content, list) or d.get("entrypoint") in (None, "cli"):
                continue
            when = tu._parse_ts(d.get("timestamp"))
            for b in content:
                if b.get("type") == "tool_use" and when:
                    pending[b.get("id")] = (b.get("name"), when)
                elif b.get("type") == "tool_result":
                    use = pending.pop(b.get("tool_use_id"), None)
                    if not use or use[1] < cut or use[0] != "Bash":
                        continue
                    total += 1
                    text = b.get("content")
                    text = text if isinstance(text, str) else json.dumps(text)
                    if b.get("is_error") and "don't ask mode" in text:
                        denied += 1
    return denied, total


def _cut(now: datetime | None, days: float) -> datetime:
    return (now or datetime.now(timezone.utc)) - timedelta(days=days)


def _when(value) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _github_calls(path: Path | None = None, days: float = 1, now: datetime | None = None) -> float:
    """North star 1: gh calls through the gate (bin/gh logs every one) over the last day. The log is rewritten with
    its newer half past 5 MB, so a day is always inside it."""
    import github_usage
    cut = _cut(now, days).timestamp()
    return float(sum(1 for r in github_usage.read_jsonl(path or github_usage.LOGS / "gh-calls.jsonl")
                     if isinstance(r.get("t"), (int, float)) and r["t"] >= cut))


def _failed_headless_runs(path: Path | None = None, days: float = 1, now: datetime | None = None) -> float:
    """North star 2 (nothing breaks silently): headless runs that ended non-zero over the last day: an error, a timeout
    (exit 124, recorded since #597), a refusal. exit_cause (#598) says which; any non-zero code counts."""
    import github_usage
    import marvin_launcher
    cut = _cut(now, days)
    return float(sum(1 for r in github_usage.read_jsonl(path or marvin_launcher.LAUNCH_LOG)
                     if r.get("exit_code") not in (0, None) and (w := _when(r.get("at"))) and w >= cut))


MEASURES: dict[str, Callable[[], float]] = {
    "headless-refusals-per-week": lambda: float(_headless_bash()[0]),
    "headless-bash-calls-per-week": lambda: float(_headless_bash()[1]),
    "github-calls-per-day": lambda: _github_calls(),
    "failed-headless-runs-per-day": lambda: _failed_headless_runs(),
}
# Not a measure yet: minutes a machine was overloaded. Nothing samples load over time (machine_resources keeps cpu_pct,
# not the load average, and its collector isn't running on either Mac as of 2026-10-26); run_ticket reads it only live.


# ── recurrence probes: did a fixed symptom come back? Each reads a log that already exists; a missing log means the
# thing that writes the symptom never ran, so the symptom is absent (0), not unknown. ─────────────────────────────

PROBE_WINDOW_DAYS = 7
_CHANGE_LINE = re.compile(r"\[gh-watch\] change detected on \S+ at (\d{4}-\d{2}-\d{2}T\d{2}):")


def _gh_watch_busiest_hour(log: Path | None = None, days: float = PROBE_WINDOW_DAYS, now: datetime | None = None) -> float:
    """#604: the busiest hour's `[gh-watch] change detected` lines in the dashboard webhook log. The 2026-10-22 storm
    ran ~570 an hour on one Mac; a normal hour is 0-30. O(log size), read once a day at most."""
    log = log or Path.home() / ".claude" / "logs" / "dashboard-webhook.log"
    try:
        text = log.read_text(errors="ignore")
    except OSError:
        return 0.0
    cut = _cut(now, days).strftime("%Y-%m-%dT%H")
    hours = Counter(h for h in _CHANGE_LINE.findall(text) if h >= cut)
    return float(max(hours.values(), default=0))


def _replanned_tickets(stages_dir: Path | None = None, days: float = PROBE_WINDOW_DAYS, now: datetime | None = None,
                       times: int = 3, within: timedelta = timedelta(hours=24)) -> float:
    """#606: tickets planned `times`+ times inside `within`, from the ticket stages log (one 'planning call' event per
    plan; a reused plan logs 'planning reused'). On 2026-10-22 five tickets were planned 6-13 times each.
    O(stage events in the window)."""
    import ticket_stages
    stages_dir = stages_dir or ticket_stages.STAGES_DIR
    cut = _cut(now, days)
    count = 0
    for f in (sorted(stages_dir.glob("*.json")) if stages_dir.is_dir() else []):
        try:
            events = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(events, list):
            continue
        plans = sorted(w for e in events if isinstance(e, dict) and e.get("stage") == "executing"
                       and e.get("status") == "started" and e.get("detail") == "planning call"
                       and (w := _when(e.get("timestamp"))) and w >= cut)
        if any(plans[i + times - 1] - plans[i] <= within for i in range(len(plans) - times + 1)):
            count += 1
    return float(count)


_SYNC_HEADER = re.compile(r"^## (\S+) — alert \(([^)]+)\)", re.M)


def _sync_stuck_episodes(log: Path | None = None, state: Path | None = None, label: str | None = None,
                         days: float = PROBE_WINDOW_DAYS, now: datetime | None = None,
                         after_s: float = 30 * 60) -> float:
    """#702/#706 (2026-10-26): this Mac's code-sync episodes stuck for 30+ min. Counts its own "sync has been failing"
    alerts in sync-log.md over the window (the log syncs between Macs, so only this Mac's header counts, and summing
    across Macs never double-counts), plus an episode still open past `after_s` in code-sync-stuck.json that hasn't
    alerted yet. Before the fix the MacBook was stuck for 4 days. O(log size)."""
    import code_sync
    from machine_profile import machine_label
    log = log or code_sync.LOG_PATH
    state = state or code_sync.LOG_PATH.parent / "logs" / "code-sync-stuck.json"
    label = label or machine_label()
    now = now or datetime.now(timezone.utc)
    cut = _cut(now, days)
    count = 0
    try:
        text = log.read_text(errors="replace")
    except OSError:
        text = ""
    for m in _SYNC_HEADER.finditer(text):
        when = _when(m.group(1))
        body = text[m.end():m.end() + 300]
        if m.group(2) == label and when and when >= cut and "sync has been failing" in body.split("\n## ")[0]:
            count += 1
    try:
        st = json.loads(state.read_text())
    except (OSError, ValueError):
        st = {}
    for ep in (st.values() if isinstance(st, dict) else []):
        if not isinstance(ep, dict):
            continue
        try:
            since = float(ep.get("since"))
        except (TypeError, ValueError):
            continue
        if now.timestamp() - since < after_s:
            continue
        # An alerted episode's alert line is already counted when it falls inside the window: it was written at or
        # after since + after_s, so since + after_s >= cut puts it there. An older one (a short window, as the
        # re-measure after first aid uses, or an episode open longer than the window) is counted here. Never
        # undercounts; at worst one late alert counts twice, which only matters to a probe that trips above 0 anyway.
        if not ep.get("alerted") or since + after_s < cut.timestamp():
            count += 1
    return float(count)


# name -> (symptom counter, the most it may read while the fix holds, what it counts). Summed across Macs like any
# measure; the logs are per Mac (~/.claude/logs doesn't sync), so nothing is counted twice.
# Each counter takes `days` (default the 7-day window): a watched incident is re-measured over the time since its last
# recorded state, and first aid is judged over the minutes since it ran (lib/incident_ladder.py).
PROBES: dict[str, tuple[Callable[..., float], float, str]] = {
    "gh-watch-change-storm": (lambda days=PROBE_WINDOW_DAYS: _gh_watch_busiest_hour(days=days), 120.0,
                              "the busiest hour's gh-watch 'change detected' lines over 7 days, all Macs (#604)"),
    "ticket-planned-3x-in-24h": (lambda days=PROBE_WINDOW_DAYS: _replanned_tickets(days=days), 0.0,
                                 "tickets planned 3+ times inside 24 h over 7 days, all Macs (#606)"),
    "code-sync-stuck": (lambda days=PROBE_WINDOW_DAYS: _sync_stuck_episodes(days=days), 0.0,
                        "code-sync episodes stuck 30+ min over 7 days, per Mac, summed (#702, #706)"),
}
MEASURES.update({name: fn for name, (fn, _limit, _what) in PROBES.items()})


def _ladder(fn: str) -> float:
    import incident_ladder
    return getattr(incident_ladder, fn)()


# Solved stays solved (lib/incident_ladder.py): read from the ladder's own log on the Mac that runs the daily check
# (marvin.db, #621, hasn't landed yet); the other Macs read 0, so the sum is that Mac's number.
MEASURES.update({
    "regression-recurrences-30d": lambda: _ladder("recurrences"),
    "regressions-fixed-without-you-30d": lambda: _ladder("fixed_without_you"),
    "regression-hours-to-fixed-30d": lambda: _ladder("hours_to_fixed"),
})
# Rates are computed from summed counts across Macs (refusals per 100 headless Bash calls), so more pipeline work
# doesn't read as a regression and a busy Mac weighs more than an idle one.
RATES = {"headless-refusal-rate": ("headless-refusals-per-week", "headless-bash-calls-per-week"),
         "regression-self-fix-rate": ("regressions-fixed-without-you-30d", "regression-recurrences-30d")}


def _rate(num: float, den: float) -> float:
    return round(100 * num / den, 1) if den else 0.0


def measure_here(name: str, days: float | None = None) -> float:
    """One measure on this Mac. `days` narrows a probe's window (a watched incident's re-measure); other measures
    ignore it."""
    if name in RATES:
        num, den = RATES[name]
        return _rate(MEASURES[num](), MEASURES[den]())
    if days is not None and name in PROBES:
        return PROBES[name][0](days=_days(days))
    return MEASURES[name]()


def _days(days) -> float:
    """A window in days: a finite number in [0, PROBE_WINDOW_DAYS]. Anything else raises (it came over ssh)."""
    d = float(days)
    if not 0 <= d <= PROBE_WINDOW_DAYS:
        raise ValueError(f"window {days!r} days is outside 0..{PROBE_WINDOW_DAYS}")
    return d


_SAFE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,59}")


def _macs(only=None):
    """(device id, ssh host) for every other registered Mac, or only the ids in `only`."""
    import machine_profile
    for device_id, info in machine_profile.remote_devices().items():
        host = info.get("tailscale_hostname")
        if not host or info.get("kind") not in (None, "desktop", "laptop") or (only is not None and device_id not in only):
            continue
        yield device_id, host


def _remote(host: str, verb: str, name: str, extra: str = "", timeout: int = 600) -> subprocess.CompletedProcess:
    """Run one registered verb on another Mac. The command holds only a registry name (checked against a strict
    pattern, so nothing a ticket wrote can reach the shell) and a number."""
    if not _SAFE_NAME.fullmatch(name or ""):
        raise ValueError(f"not a registered name: {_defang(name)}")
    cmd = ["ssh", *SSH_OPTS, host, f"~/.agents/venv/bin/python ~/.agents/lib/purpose_metrics.py {verb} {name} --local{extra}"]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def measure_everywhere(name: str, days: float | None = None) -> tuple[float, dict[str, float]]:
    """This Mac plus every other registered Mac over ssh, summed. Raises if any Mac can't be measured: a partial
    number would look like an improvement."""
    if name in RATES:
        (num, per_num), (den, per_den) = (measure_everywhere(m) for m in RATES[name])
        return _rate(num, den), {k: _rate(per_num[k], per_den[k]) for k in per_num}
    MEASURES[name]  # unknown names fail before anything runs
    import machine_profile
    extra = f" --days {_days(days):.6f}" if days is not None and name in PROBES else ""
    per = {machine_profile.registry_id(): measure_here(name, days if extra else None)}
    for device_id, host in _macs():
        out = _remote(host, "measure", name, extra)
        if out.returncode != 0:
            raise OSError(f"couldn't measure {name} on {device_id}: {out.stderr.strip()[:200]}")
        per[device_id] = float(out.stdout.strip().splitlines()[-1])
    return sum(per.values()), per


# ── first aid: what MARVIN tries, with no model call, when a watched incident's probe trips (lib/incident_ladder.py).
# Like PROBES, named, reviewed code: a ticket's '## First aid' section lists names from here and nothing else. Every
# step is idempotent, deletes nothing that isn't proven redundant, and returns {"changed": bool, "detail": str}.

def _stuck_sync(state: Path | None = None) -> list[tuple[Path, list[str]]]:
    """This Mac's stuck repos and the sync actions that failed in each, from code_sync's own episode file. Only a
    real git checkout and only 'push' / 'pull' survive; anything else in the file is ignored."""
    import code_sync
    state = state or code_sync.LOG_PATH.parent / "logs" / "code-sync-stuck.json"
    try:
        st = json.loads(state.read_text())
    except (OSError, ValueError):
        return []
    out = []
    for key, ep in (st.items() if isinstance(st, dict) else []):
        repo = Path(str(key))
        if not isinstance(ep, dict) or not repo.is_absolute() or not (repo / ".git").exists():
            continue
        failing = ep.get("failing") if isinstance(ep.get("failing"), dict) else {}
        actions = [a for a in ("pull", "push") if a in failing] or ["push"]
        out.append((repo, actions))
    return out


def _code_sync_rerun(state: Path | None = None, run=subprocess.run) -> dict:
    """#707: run the sync actions that failed again, for each stuck repo (the same command the scheduled job runs)."""
    stuck = _stuck_sync(state)
    if not stuck:
        return {"changed": False, "detail": "no repo is stuck on this Mac"}
    script = Path(__file__).resolve().parent / "code_sync.py"
    done = []
    for repo, actions in stuck:
        for action in actions:
            out = run([sys.executable, str(script), action, str(repo)], capture_output=True, text=True, timeout=600)
            done.append(f"{action} {repo.name}: exit {out.returncode}")
    return {"changed": True, "detail": "re-ran code sync (" + "; ".join(done) + ")"}


def _code_sync_drop_contained_stash(state: Path | None = None, drop=None) -> dict:
    """#707: drop a leftover stash only when every file in it already matches HEAD (code_sync's #706 containment
    check); any other stash is kept for a person."""
    import code_sync
    drop = drop or code_sync.drop_contained_stashes
    stuck = _stuck_sync(state)
    dropped = [f"{repo.name}: {d}" for repo, _a in stuck for d in drop(repo, "first-aid")]
    return {"changed": bool(dropped),
            "detail": ("dropped " + ", ".join(dropped)) if dropped else "no leftover stash HEAD already contains"}


FIRST_AID: dict[str, tuple[Callable[[], dict], str]] = {
    "code-sync-drop-contained-stash": (lambda: _code_sync_drop_contained_stash(),
                                       "drop leftover stashes whose every file already matches HEAD (#706's check)"),
    "code-sync-rerun": (lambda: _code_sync_rerun(), "re-run the failed code sync for each stuck repo"),
    # A nearly full disk (2026-10-28): the cleanup sweep's own rebuildable trims, nothing it doesn't already delete.
    # Run by the merge gate's disk check and by the health check's low-disk result.
    "disk-clear-rebuildable": (lambda: _disk_clear_rebuildable(),
                               "remove old aerial videos (keep the newest) and disk_trim's rebuildable caches"),
    # marvin#765: run on every Mac by the merge server after each merge (disk_triggers.py after-merge).
    "disk-clean-merged-worktrees": (lambda: _disk_clean_merged_worktrees(),
                                    "remove merged PRs' worktrees (none with uncommitted work or a process inside) "
                                    "and their Xcode build products"),
}


def _disk_clear_rebuildable() -> dict:
    import cleanup_sweep
    return cleanup_sweep.clear_rebuildable()


def _disk_clean_merged_worktrees() -> dict:
    import disk_triggers
    return disk_triggers.merged_worktrees_step()


def first_aid_here(name: str) -> dict:
    """One registered step on this Mac. Never raises: a step that throws is a failed step, logged."""
    if name not in FIRST_AID:
        return {"step": _defang(name), "ok": False, "changed": False, "detail": "not a registered first-aid step"}
    try:
        r = FIRST_AID[name][0]()
        r = r if isinstance(r, dict) else {}
        return {"step": name, "ok": True, "changed": bool(r.get("changed")), "detail": str(r.get("detail", ""))[:300]}
    except Exception as exc:  # noqa: BLE001 -- a broken step must not stop the ladder; the next rung still runs
        return {"step": name, "ok": False, "changed": False, "detail": f"{type(exc).__name__}: {str(exc)[:200]}"}


def first_aid_everywhere(name: str, only=None) -> list[dict]:
    """The step on this Mac (when it is in `only`, or `only` is None) and on each other Mac in `only`, over ssh.
    One result per Mac; an unreachable Mac is a failed step, not an exception."""
    import machine_profile
    here = machine_profile.registry_id()
    out = [{**first_aid_here(name), "mac": here}] if only is None or here in only else []
    for device_id, host in _macs(only):
        try:
            r = _remote(host, "first-aid", name, timeout=1200)
            res = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else None
        except (OSError, ValueError, IndexError, subprocess.SubprocessError) as exc:
            res, r = None, exc
        if not isinstance(res, dict):
            res = {"step": name, "ok": False, "changed": False, "detail": f"couldn't run on that Mac: {str(getattr(r, 'stderr', r))[:200]}"}
        out.append({**res, "mac": device_id})
    return out


# ── evidence: the log lines a reopened incident carries (bounded, secrets scrubbed by support.scrub) ─────────────

EVIDENCE_LINES = 40
EVIDENCE_LINE_CHARS = 240


def _sync_evidence(days: float = PROBE_WINDOW_DAYS, log: Path | None = None, state: Path | None = None,
                   label: str | None = None, now: datetime | None = None) -> list[str]:
    """This Mac's sync-log entries inside the window, and its open stuck episodes."""
    import code_sync
    from machine_profile import machine_label
    log = log or code_sync.LOG_PATH
    label = label or machine_label()
    cut = _cut(now, days)
    try:
        text = log.read_text(errors="replace")
    except OSError:
        text = ""
    lines = []
    for block in re.split(r"\n(?=## )", text):
        m = re.match(r"## (\S+) — \S+ \(([^)]+)\)", block)
        if m and m.group(2) == label and (w := _when(m.group(1))) and w >= cut:
            lines += [l for l in block.splitlines() if l.strip()]
    for repo, actions in _stuck_sync(state):
        lines.append(f"still stuck: {repo.name} ({', '.join(actions)} failing)")
    return lines


EVIDENCE: dict[str, Callable[..., list[str]]] = {
    "code-sync-stuck": lambda days=PROBE_WINDOW_DAYS: _sync_evidence(days=days),
}


def evidence_here(name: str, days: float = PROBE_WINDOW_DAYS) -> list[str]:
    """The last EVIDENCE_LINES lines, each cut to EVIDENCE_LINE_CHARS and scrubbed. A probe with no evidence source,
    or one that throws, gives one line saying so."""
    import support
    if name not in EVIDENCE:
        return ["(no log is registered for this probe)"]
    try:
        lines = [str(l) for l in EVIDENCE[name](days=_days(days))]
    except Exception as exc:  # noqa: BLE001
        return [f"(couldn't read the log: {type(exc).__name__})"]
    return [support.scrub(l[:EVIDENCE_LINE_CHARS]) for l in lines[-EVIDENCE_LINES:]]


def evidence_everywhere(name: str, days: float, only=None) -> dict[str, list[str]]:
    import machine_profile
    here = machine_profile.registry_id()
    out = {here: evidence_here(name, days)} if only is None or here in only else {}
    for device_id, host in _macs(only):
        try:
            r = _remote(host, "evidence", name, f" --days {_days(days):.6f}", timeout=120)
            lines = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else None
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            lines = None
        import support
        out[device_id] = [support.scrub(str(l)[:EVIDENCE_LINE_CHARS]) for l in lines][-EVIDENCE_LINES:] \
            if isinstance(lines, list) else ["(couldn't read that Mac's log)"]
    return out


# ── tickets ───────────────────────────────────────────────────────────────────────────────────────────────

def _section(body: str | None, heading: str) -> dict | None:
    m = re.search(rf"^##\s*{heading}\s*$([\s\S]*?)(?=^##\s|\Z)", body if isinstance(body, str) else "", re.I | re.M)
    return dict((k.lower(), v.strip()) for k, v in re.findall(r"\*\*([\w ]+):\*\*\s*(.+)", m.group(1))) if m else None


def parse(body: str | None) -> dict | None:
    """The ticket's outcome check: a Purpose metric, else a Recurrence check. None when there is none, or when it
    can't be read (the fit check says which at PR time: outcome_gap). Only parsed, never executed."""
    fields = _section(body, "Purpose metric")
    if fields is not None:
        try:
            return {"measure": fields["measure"], "baseline": float(fields["baseline"].replace(",", "")),
                    "target": fields["target"], "check_on": fields["check on"]}
        except (KeyError, ValueError):
            return None
    fields = _section(body, "Recurrence check")
    if fields is None or fields.get("probe") not in PROBES or not fields.get("check on"):
        return None
    try:
        baseline = float(fields["baseline"].replace(",", "")) if fields.get("baseline") else None
    except ValueError:
        return None
    return {"kind": "recurrence", "measure": fields["probe"], "baseline": baseline,
            "target": f"<= {PROBES[fields['probe']][1]:g}", "check_on": fields["check on"]}


def check_date(spec: dict) -> datetime | None:
    """'Check on: 2026-11-02' or '2026-11-02: the symptom has not come back': the leading date, or None."""
    m = re.match(r"\s*(\d{4}-\d{2}-\d{2})\b", spec.get("check_on") or "")
    try:
        return datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc) if m else None
    except ValueError:
        return None


def _defang(name: str) -> str:
    return re.sub(r"[^\w.-]", "?", str(name))[:60]


def outcome_gap(body: str | None, now: datetime | None = None) -> str | None:
    """Why this ticket has no outcome check the daily run can measure, or None when it has one. At PR time a date
    already passed is a gap too: the check would measure before the fix ran. Names are defanged before quoting."""
    now = now or datetime.now(timezone.utc)
    metric, recur = _section(body, "Purpose metric"), _section(body, "Recurrence check")
    if metric is None and recur is None:
        return ("no outcome check: add a '## Purpose metric' (a measure from purpose_metrics.MEASURES) or, when "
                "nothing numeric fits, a '## Recurrence check' (a probe from purpose_metrics.PROBES)")
    spec = parse(body)
    if spec is None:
        if metric is None and recur.get("probe") and recur["probe"] not in PROBES:
            return f"unknown probe '{_defang(recur['probe'])}': register it in purpose_metrics.PROBES"
        return ("malformed Purpose metric: needs Measure, Baseline (a number), Target and Check on" if metric is not None
                else "malformed Recurrence check: needs Probe and Check on (Baseline, if given, a number)")
    if spec["measure"] not in MEASURES and spec["measure"] not in RATES:
        return f"unknown measure '{_defang(spec['measure'])}': register it in purpose_metrics.MEASURES"
    try:
        target_value(spec)
    except ValueError:
        return "unreadable target: use -N%, +N%, '<= N' or '>= N'"
    due = check_date(spec)
    if due is None:
        return "unreadable Check on date: use YYYY-MM-DD"
    if due <= now:
        return "Check on is in the past: the check would measure before the fix ran"
    return None


def target_value(spec: dict) -> tuple[str, float]:
    t = spec["target"].replace(" ", "")
    if m := re.fullmatch(r"([+-])(\d+(?:\.\d+)?)%", t):
        pct = float(m.group(2)) / 100
        return ("<=", spec["baseline"] * (1 - pct)) if m.group(1) == "-" else (">=", spec["baseline"] * (1 + pct))
    if m := re.fullmatch(r"(<=|>=)(\d+(?:\.\d+)?)", t):
        return m.group(1), float(m.group(2))
    raise ValueError(f"unreadable target {spec['target']!r}")


def met(spec: dict, value: float) -> bool:
    op, bound = target_value(spec)
    return value <= bound if op == "<=" else value >= bound


def is_due(issue: dict, now: datetime) -> bool:
    spec = parse(issue.get("body"))
    due = check_date(spec) if spec else None
    return bool(due and now >= due) and not any(isinstance(c, str) and c.startswith(OUTCOME_HEADING)
                                                for c in issue.get("comments", []))


def _diagnose(issue: dict, spec: dict, value: float, per: dict) -> str:
    """The likely why, from a Background analyst (full MARVIN context: it has to reason about the system)."""
    import marvin_launcher
    prompt = (f"Ticket #{issue['number']} {issue['title']} promised a measurable effect and missed it.\n\n"
              f"Ticket:\n{issue.get('body', '')[:4000]}\n\nMeasured: {value:g} (per Mac: {per}); baseline "
              f"{spec['baseline']:g}; target {spec['target']}.\n\nIn at most 6 lines, give the most likely reasons, "
              "grounded in the code and data you can read (cite files). No fixes yet, just the why. Grounded, not agreeable.")
    result = marvin_launcher.launch("background-analyst", prompt, tools="Read,Grep,Glob", permission_mode="dontAsk",
                                    allowed_tools="Read,Grep,Glob", timeout=600, ticket=f"#{issue['number']}")
    return result.text.strip() or "(the analyst gave no answer; investigate by hand)"


def outcome_text(issue: dict, spec: dict, value: float, per: dict, ok: bool, why: str | None) -> str:
    op, bound = target_value(spec)
    per_mac = ", ".join(f"{k} {v:g}" for k, v in per.items())
    if spec.get("kind") == "recurrence":
        at_fix = f"; {spec['baseline']:g} when it was fixed" if spec.get("baseline") is not None else ""
        lines = [OUTCOME_HEADING, "",
                 f"{'✅ Fix held: the symptom has not come back' if ok else '⚠️ Missed purpose: the symptom came back'}: "
                 f"probe **{spec['measure']}** = **{value:g}** (holds at {op} {bound:g}{at_fix}). "
                 f"It counts {PROBES[spec['measure']][2]}. Per Mac: {per_mac}."]
        if not ok:
            lines += ["", "### Missed-purpose diagnosis", "", f"- **Intended:** the symptom stays at {op} {bound:g}.",
                      f"- **Measured:** {value:g}.", "", "**Likely why**", "", why or "", "", "**Your options**", "",
                      "- **Fix:** reopen this or open a follow-up ticket for what the diagnosis found, with its own outcome check.",
                      "- **Accept:** the symptom is rare enough to live with; remove `missed-purpose` and say why.",
                      "- **Adjust:** the probe's threshold is wrong; change it in `purpose_metrics.PROBES`."]
        return "\n".join(lines)
    lines = [OUTCOME_HEADING, "",
             f"{'✅ Purpose met' if ok else '⚠️ Purpose missed'}: **{spec['measure']}** = **{value:g}** "
             f"(target {op} {bound:g}; baseline {spec['baseline']:g}). Per Mac: "
             + ", ".join(f"{k} {v:g}" for k, v in per.items()) + "."]
    if not ok:
        lines += ["", "### Missed-purpose diagnosis", "",
                  f"- **Intended:** {spec['target']} against a baseline of {spec['baseline']:g}.",
                  f"- **Measured:** {value:g}.", "", "**Likely why**", "", why or "", "",
                  "**Your options**", "",
                  "- **Fix:** open a follow-up ticket for what the diagnosis found, with its own purpose metric.",
                  "- **Accept:** the change is worth keeping anyway; record the new baseline and remove `missed-purpose`.",
                  "- **Revert:** the change cost more than it gave; revert it."]
    return "\n".join(lines)


def check_issue(repo: str, issue: dict, now: datetime, measure=measure_everywhere,
                comment: Callable | None = None, label: Callable | None = None, diagnose=_diagnose) -> dict:
    spec = parse(issue["body"])
    try:
        value, per = measure(spec["measure"])
    except Exception as exc:  # noqa: BLE001 -- measured again tomorrow; never claim a result we don't have
        print(f"[purpose] #{issue['number']}: not measured ({exc})", file=sys.stderr)
        return {"number": issue["number"], "met": None}
    ok = met(spec, value)
    why = None if ok else diagnose(issue, spec, value, per)
    (comment or _comment)(repo, issue["number"], outcome_text(issue, spec, value, per, ok, why))
    if not ok:
        (label or _label)(repo, issue["number"], MISSED_LABEL)
    return {"number": issue["number"], "met": ok, "value": value}


# ── GitHub (REST: GraphQL's budget is shared with the dashboard) ─────────────────────────────────────────────

def _gh_json(path: str):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise OSError(out.stderr.strip()[:200])
    return json.loads(out.stdout)


def _comment(repo: str, number: int, text: str) -> None:
    subprocess.run(["gh", "api", f"repos/{repo}/issues/{number}/comments", "-f", f"body={text}"],
                   capture_output=True, text=True, timeout=60, check=True)


def _label(repo: str, number: int, name: str) -> None:
    subprocess.run(["gh", "api", f"repos/{repo}/issues/{number}/labels", "-f", f"labels[]={name}"],
                   capture_output=True, text=True, timeout=60, check=True)


def labelled_issues(repo: str, name: str) -> list[dict]:
    return [i for i in _gh_json(f"repos/{repo}/issues?labels={name}&state=all&per_page=100") if "pull_request" not in i]


def run(now: datetime | None = None, ladder_step: Callable | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    import incident_ladder
    ladder_step = ladder_step or incident_ladder.step
    results = []
    for repo in REPOS:
        # Every fix carries an outcome check, so `bug` tickets are read too (the newest 100; one list call each).
        issues = {}
        for name in (LABEL, BUG_LABEL, incident_ladder.WATCH_LABEL):
            for issue in labelled_issues(repo, name):
                issues.setdefault(issue["number"], issue)
        for issue in issues.values():
            if incident_ladder.is_watched(issue):
                # A watched incident is re-measured every day after its check date, not once (the incident ladder).
                try:
                    results.append(ladder_step(repo, issue, now))
                except Exception as exc:  # noqa: BLE001 -- one incident failing never stops the others
                    print(f"[purpose] #{issue['number']}: watch step failed ({exc})", file=sys.stderr)
                continue
            spec = parse(issue.get("body"))
            due = check_date(spec) if spec else None
            if not due or now < due:
                continue  # comments are only fetched for a ticket whose check is due
            issue["comments"] = [c["body"] for c in _gh_json(f"repos/{repo}/issues/{issue['number']}/comments")] \
                if issue.get("comments") else []
            if is_due(issue, now):
                results.append(check_issue(repo, issue, now))
    return results


def health_findings(missed: list[dict]) -> list[dict]:
    if not missed:
        return [{"id": "purpose:missed", "label": "Purpose metrics", "severity": "green",
                 "detail": "no ticket has missed its purpose"}]
    return [{"id": f"purpose:missed:{i['number']}", "label": "Missed purpose", "severity": "red",
             "detail": f"#{i['number']} {i['title']}: missed its purpose metric; the diagnosis and your options are on the ticket"}
            for i in missed]


if __name__ == "__main__":
    args = sys.argv[1:]
    days = float(args[args.index("--days") + 1]) if "--days" in args[:-1] else None
    if args[:1] == ["measure"] and len(args) >= 2:
        print(measure_here(args[1], days) if "--local" in args else json.dumps(measure_everywhere(args[1], days)))
    elif args[:1] == ["first-aid"] and len(args) >= 2 and "--local" in args:
        print(json.dumps(first_aid_here(args[1])))
    elif args[:1] == ["evidence"] and len(args) >= 2 and "--local" in args:
        print(json.dumps(evidence_here(args[1], PROBE_WINDOW_DAYS if days is None else days)))
    elif args == ["check"]:
        print(json.dumps(run()))
    else:
        sys.exit("usage: purpose_metrics.py check | measure <name> [--local] [--days N] | first-aid <name> --local | "
                 "evidence <name> --local [--days N]")
