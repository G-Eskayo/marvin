#!/usr/bin/env python3
"""Purpose metrics and outcome checks (marvin#304; glossary: purpose metric, outcome check, missed-purpose diagnosis).

A ticket whose purpose is measurable (faster, fewer tokens, fewer refusals) carries a section:

    ## Purpose metric
    - **Measure:** headless-refusals-per-week     (a name from MEASURES below, never code or a command)
    - **Baseline:** 376
    - **Target:** -70%                             (or +N%, "<= N", ">= N"; lower is better unless stated)
    - **Check on:** 2026-10-15

and the `purpose-metric` label. Once the date has passed, the daily outcome check measures it on every Mac,
comments the result on the ticket, and on a miss writes a **missed-purpose diagnosis** (what was intended, what
was measured, the likely why, the options) and adds the `missed-purpose` label, which Health shows red until
someone decides. The ticket's own comments are the record, so both Macs can run the check without posting twice.

    purpose_metrics.py check                 # the daily outcome check (run by the cleanup sweep)
    purpose_metrics.py measure <name> --local  # one measure on this Mac only (how the other Mac is asked over ssh)
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

LABEL = "purpose-metric"
MISSED_LABEL = "missed-purpose"
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


MEASURES: dict[str, Callable[[], float]] = {
    "headless-refusals-per-week": lambda: float(_headless_bash()[0]),
    "headless-bash-calls-per-week": lambda: float(_headless_bash()[1]),
}
# Rates are computed from summed counts across Macs (refusals per 100 headless Bash calls), so more pipeline work
# doesn't read as a regression and a busy Mac weighs more than an idle one.
RATES = {"headless-refusal-rate": ("headless-refusals-per-week", "headless-bash-calls-per-week")}


def _rate(num: float, den: float) -> float:
    return round(100 * num / den, 1) if den else 0.0


def measure_here(name: str) -> float:
    if name in RATES:
        num, den = RATES[name]
        return _rate(MEASURES[num](), MEASURES[den]())
    return MEASURES[name]()


def measure_everywhere(name: str) -> tuple[float, dict[str, float]]:
    """This Mac plus every other registered Mac over ssh, summed. Raises if any Mac can't be measured: a partial
    number would look like an improvement."""
    if name in RATES:
        (num, per_num), (den, per_den) = (measure_everywhere(m) for m in RATES[name])
        return _rate(num, den), {k: _rate(per_num[k], per_den[k]) for k in per_num}
    MEASURES[name]  # unknown names fail before anything runs
    import machine_profile
    per = {machine_profile.registry_id(): measure_here(name)}
    for device_id, info in machine_profile.remote_devices().items():
        host = info.get("tailscale_hostname")
        if not host or info.get("kind") not in (None, "desktop", "laptop"):
            continue
        cmd = ["ssh", *SSH_OPTS, host, f"~/.agents/venv/bin/python ~/.agents/lib/purpose_metrics.py measure {name} --local"]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if out.returncode != 0:
            raise OSError(f"couldn't measure {name} on {device_id}: {out.stderr.strip()[:200]}")
        per[device_id] = float(out.stdout.strip().splitlines()[-1])
    return sum(per.values()), per


# ── tickets ───────────────────────────────────────────────────────────────────────────────────────────────

def parse(body: str | None) -> dict | None:
    m = re.search(r"^##\s*Purpose metric\s*$([\s\S]*?)(?=^##\s|\Z)", body or "", re.I | re.M)
    if not m:
        return None
    fields = dict((k.lower(), v.strip()) for k, v in re.findall(r"\*\*([\w ]+):\*\*\s*(.+)", m.group(1)))
    try:
        return {"measure": fields["measure"], "baseline": float(fields["baseline"].replace(",", "")),
                "target": fields["target"], "check_on": fields["check on"]}
    except (KeyError, ValueError):
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
    if not spec:
        return False
    try:
        due = datetime.fromisoformat(spec["check_on"]).replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return now >= due and not any(c.startswith(OUTCOME_HEADING) for c in issue.get("comments", []))


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


def run(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    results = []
    for repo in REPOS:
        for issue in labelled_issues(repo, LABEL):
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
    if args[:1] == ["measure"] and len(args) >= 2:
        print(measure_here(args[1]) if "--local" in args else json.dumps(measure_everywhere(args[1])))
    elif args == ["check"]:
        print(json.dumps(run()))
    else:
        sys.exit("usage: purpose_metrics.py check | measure <name> [--local]")
