#!/usr/bin/env python3
"""North-star fit checks on a PR (marvin#276; glossary: north-star fit, fit checks).

A ticket states its north-star fit when it's created (what it reuses, why it's the simplest sufficient approach,
where it saves or spends tokens). At review time this module sets facts code can measure next to that claim,
each marked ✅ or ⚠️: whether a fit was stated, new source files, net lines added, whether tests changed with
the code, and what the ticket's model runs cost. Only when something is flagged does a Judge (clean, no MARVIN
context) read the fit and the facts and say whether the flag is explained. "B always, C only when B flags."

    fit_check.py <owner/repo#N> <worktree> <pr-url>   # posts the report as a PR comment
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

MAX_NEW_SOURCE_FILES = 2      # composability: reuse before adding; every new file is a maintenance cost
MAX_NET_LINES = 400           # elegant sufficiency
MAX_TICKET_COST_USD = 3.0     # north star 1: tokens


def fit_section(body: str | None) -> str | None:
    m = re.search(r"^##\s*North-star fit\s*$([\s\S]*?)(?=^##\s|\Z)", body or "", re.I | re.M)
    text = m.group(1).strip() if m else ""
    return text or None


def is_test(path: str) -> bool:
    name = Path(path).name
    return bool(re.search(r"(^|/)(tests?|Tests)/", path) or name.startswith("test_")
                or re.search(r"(\.test\.[jt]sx?|_test\.py|Tests\.swift)$", name))


def diff_facts(worktree: Path, base: str = "origin/main") -> dict:
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(worktree), *args], capture_output=True, text=True).stdout
    added = lines_removed = 0
    source = tests = 0
    for line in git("diff", "--numstat", f"{base}...HEAD").splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        a, r, path = parts
        added += int(a) if a.isdigit() else 0
        lines_removed += int(r) if r.isdigit() else 0
        if is_test(path):
            tests += 1
        else:
            source += 1
    new = [l.split("\t", 1)[1] for l in git("diff", "--name-status", "--diff-filter=A", f"{base}...HEAD").splitlines()
           if "\t" in l]
    return {"new_files": new, "new_source_files": [p for p in new if not is_test(p)], "lines_added": added,
            "lines_removed": lines_removed, "source_files_changed": source, "test_files_changed": tests}


def ticket_cost(ticket_ref: str, log: Path | None = None) -> float:
    import marvin_launcher
    log = log or marvin_launcher.LAUNCH_LOG
    total = 0.0
    for line in (log.read_text().splitlines() if log.exists() else []):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("ticket") == ticket_ref:
            total += rec.get("cost_usd") or 0.0
    return round(total, 2)


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": ok, "detail": detail}


def run_checks(facts: dict, fit: str | None, cost_usd: float) -> list[dict]:
    new_src = facts["new_source_files"]
    net = facts["lines_added"] - facts["lines_removed"]
    return [
        _check("North-star fit stated", bool(fit), "on the ticket" if fit else "the ticket has no North-star fit section"),
        _check("Reuse before adding", len(new_src) <= MAX_NEW_SOURCE_FILES,
               f"{len(new_src)} new source file(s)" + (f": {', '.join(new_src[:5])}" if new_src else "")),
        _check("Simplest sufficient", net <= MAX_NET_LINES,
               f"+{facts['lines_added']} / -{facts['lines_removed']} lines (net {net:+d})"),
        _check("Tested", facts["source_files_changed"] == 0 or facts["test_files_changed"] > 0,
               f"{facts['test_files_changed']} test file(s) changed with {facts['source_files_changed']} source file(s)"),
        _check("Token cost", cost_usd <= MAX_TICKET_COST_USD, f"${cost_usd:.2f} of model runs for this ticket"),
    ]


def render(checks: list[dict], verdict: str | None = None) -> str:
    rows = "\n".join(f"| {'✅' if c['ok'] else '⚠️'} | {c['name']} | {c['detail']} |" for c in checks)
    text = f"## North-star fit check\n\n| | Check | Fact |\n|---|---|---|\n{rows}\n"
    if verdict:
        text += f"\n**Judge** (clean, read the fit and the facts because something was flagged):\n\n{verdict}\n"
    return text


_RUBRIC = """You are a Judge reviewing one pull request against the north-star fit its ticket claimed.
The north stars: do the job at equal or higher quality for fewer tokens; reuse before adding; the simplest
sufficient approach; tests with the code. Some deterministic checks were flagged (⚠️). For each flag, say in one
line whether the fit or the facts explain it (an acceptable reason) or not (a real concern). End with one line:
VERDICT: fits | VERDICT: concern: <the main one>. Be grounded, not agreeable."""


def _default_judge(prompt: str) -> str:
    import marvin_launcher
    result = marvin_launcher.launch("judge", prompt, model="claude-haiku-4-5-20251001", tools="",
                                    permission_mode=None, timeout=180)
    return result.text.strip() if result.exit_code == 0 else f"(Judge didn't answer: {result.stderr[:200]})"


def judge_if_flagged(checks: list[dict], fit: str | None, facts: dict,
                     judge: Callable[[str], str] = _default_judge) -> str | None:
    flags = [c for c in checks if not c["ok"]]
    if not flags:
        return None
    prompt = (f"{_RUBRIC}\n\nCLAIMED FIT:\n{fit or '(none stated)'}\n\nFLAGGED:\n"
              + "\n".join(f"- {c['name']}: {c['detail']}" for c in flags)
              + f"\n\nFACTS:\n{json.dumps(facts, indent=1)}")
    return judge(prompt)


def report(ticket_ref: str, worktree: Path, body: str | None, base: str = "origin/main",
           judge: Callable[[str], str] = _default_judge) -> str:
    facts = diff_facts(worktree, base)
    fit = fit_section(body)
    checks = run_checks(facts, fit, ticket_cost(ticket_ref))
    return render(checks, judge_if_flagged(checks, fit, facts, judge=judge))


def _ticket_body(ticket_ref: str) -> str:
    repo, number = ticket_ref.rsplit("#", 1)
    out = subprocess.run(["gh", "issue", "view", number, "--repo", repo, "--json", "body", "-q", ".body"],
                         capture_output=True, text=True, timeout=60)
    return out.stdout if out.returncode == 0 else ""


def post(ticket_ref: str, worktree: Path, pr_url: str) -> None:
    text = report(ticket_ref, worktree, _ticket_body(ticket_ref))
    subprocess.run(["gh", "pr", "comment", pr_url, "--body", text], capture_output=True, text=True, timeout=60)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage: fit_check.py <owner/repo#N> <worktree> <pr-url>")
    post(sys.argv[1], Path(sys.argv[2]), sys.argv[3])
