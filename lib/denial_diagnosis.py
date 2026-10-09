#!/usr/bin/env python3
"""Denial diagnosis and kind-tallying for the ticket pipeline (marvin#325).

When a ticket is sent back (denied), diagnose what KIND of denial it is:
- wrong-approach: the approach itself was wrong; rebuild from scratch
- missing-tests: the code works but needs test coverage; fix forward
- ui-broken: UI doesn't match requirements; fix forward
- scope-creep: ticket asked for more than stated; rebuild/clarify
- style: naming, docs, perf tuning; fix forward
- regression: broke something that worked; fix forward
- unclear: the denial is unclear or unanswerable; needs a person

Routes each denial to fix_forward, rebuild, or needs_person based on the kind.
After 3 denials of the same KIND in one project, file an improvement ticket.

State is a per-machine append-only log (~/.claude/logs/denial-diagnoses.jsonl).
Reuses failure_breaker.py's pattern for consistency.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path.home() / ".claude" / "logs" / "denial-diagnoses.jsonl"
KINDS = ("wrong-approach", "missing-tests", "ui-broken", "scope-creep", "style", "regression", "unclear")
MIN_REPEATS = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _append(record: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a") as fh:
        fh.write(json.dumps(record) + "\n")


def _read() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    out = []
    for line in LOG_PATH.read_text().splitlines():
        try:
            rec = json.loads(line)
            rec["_t"] = datetime.fromisoformat(rec["t"])
            out.append(rec)
        except (ValueError, KeyError, TypeError):
            continue  # corrupt line must never take the system down
    return out


def _launch_analyst(prompt: str, timeout: int = 600) -> str:
    """Call the background-analyst with Read,Grep,Glob tools only, bounded time."""
    import marvin_launcher
    result = marvin_launcher.launch(
        "background-analyst", prompt, tools="Read,Grep,Glob", permission_mode="dontAsk",
        allowed_tools="Read,Grep,Glob", timeout=timeout, ticket="denial-diagnosis"
    )
    return result.text.strip() if result else ""


def _parse_kind_and_route(analyst_text: str) -> tuple[str, str]:
    """Extract kind and route from analyst's structured response."""
    # Try to find explicit kind: <word> patterns
    kind_match = re.search(r"\bkind:\s*(\w+)", analyst_text.lower())
    if kind_match:
        found_kind = kind_match.group(1)
        if found_kind in KINDS:
            kind = found_kind
        else:
            kind = "unclear"
    else:
        kind = "unclear"

    # Try to find route: fix_forward|rebuild|needs_person
    route_match = re.search(r"\broute:\s*(fix_forward|rebuild|needs_person)", analyst_text.lower())
    route = route_match.group(1) if route_match else "fix_forward"  # default to fix_forward

    return kind, route


def _comment_issue(ticket_number: int, text: str, repo: str = "G-Eskayo/marvin") -> None:
    """Post a comment on a GitHub issue."""
    subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/{ticket_number}/comments", "-f", f"body={text}"],
        capture_output=True, text=True, timeout=60, check=True
    )


def classify(
    issue: dict, pr_diff: str | None, failure_reason: str, repo: str = "G-Eskayo/marvin", now: datetime | None = None
) -> dict:
    """Diagnose what KIND of denial occurred and which ROUTE to take.

    Returns: {kind, route, note} where:
    - kind: one of KINDS (wrong-approach, missing-tests, ...)
    - route: "fix_forward", "rebuild", or "needs_person"
    - note: short explanation (what to change, or why needs a person)
    """
    now = now or _now()
    ticket_number = issue.get("number", 0)
    title = issue.get("title", "")
    body = issue.get("body", "")[:4000]
    diff = (pr_diff or "")[:10000]
    reason = (failure_reason or "")[:2000]

    prompt = (
        f"GitHub issue #{ticket_number} {title} was sent back (denied) by the pipeline.\n\n"
        f"Issue body:\n{body}\n\n"
        f"PR diff (first 10k chars):\n{diff}\n\n"
        f"Denial reason:\n{reason}\n\n"
        f"In at most 6 lines, diagnose the KIND of denial (wrong-approach, missing-tests, ui-broken, scope-creep, "
        f"style, regression, unclear) and which route to take (fix_forward for targeted changes, rebuild for "
        f"approach-level changes, needs_person if unclear). Format: 'kind: X' and 'route: Y'. "
        f"Grounded, not agreeable."
    )

    analyst_response = _launch_analyst(prompt)
    kind, route = _parse_kind_and_route(analyst_response) if analyst_response else ("unclear", "needs_person")

    if not analyst_response:
        note = "(the analyst gave no answer; investigate by hand)"
    else:
        # Extract any actionable note from the analyst response
        lines = analyst_response.split("\n")
        note = next((l for l in lines if l and not l.lower().startswith(("kind:", "route:"))), analyst_response[:200])

    record = {
        "t": now.isoformat(),
        "kind": "diagnosis",
        "ticket": ticket_number,
        "project": repo,
        "diagnosis_kind": kind,
        "route": route,
    }
    _append(record)

    # Post a comment on the issue with the diagnosis
    comment_text = f"### Diagnosis\n\n**Kind:** {kind}\n**Route:** {route}\n\n{note}"
    try:
        _comment_issue(ticket_number, comment_text, repo=repo)
    except Exception as e:  # noqa: BLE001
        # Comment failure should not stop the diagnosis
        print(f"[denial_diagnosis] failed to comment on #{ticket_number}: {e}", file=sys.stderr)

    return {"kind": kind, "route": route, "note": note}


def tally(now: datetime | None = None, project: str | None = None) -> list[dict]:
    """Group denials by (project, kind); return groups with >= MIN_REPEATS occurrences.

    Unlike failure_breaker.tripped(), this has NO time window (denials can span weeks).
    Returns: [{"project", "kind", "count", "tickets", "first_seen", "last_seen"}]
    """
    records = [r for r in _read() if r.get("kind") == "diagnosis"]
    if project is not None:
        records = [r for r in records if r.get("project") == project]

    result = []
    # Group by (project, diagnosis_kind)
    by_group: dict[tuple[str, str], list[dict]] = {}
    for r in records:
        proj = r.get("project", "G-Eskayo/marvin")
        diag_kind = r.get("diagnosis_kind", "unclear")
        key = (proj, diag_kind)
        by_group.setdefault(key, []).append(r)

    for (proj, kind), group in sorted(by_group.items()):
        if len(group) >= MIN_REPEATS:
            tickets = sorted({r["ticket"] for r in group})
            result.append({
                "project": proj,
                "kind": kind,
                "count": len(group),
                "tickets": tickets,
                "first_seen": min(r["_t"] for r in group).isoformat(),
                "last_seen": max(r["_t"] for r in group).isoformat(),
            })

    return result


def _gh_list_issues(repo: str, title_contains: str) -> list[dict]:
    """List issues with title containing the search term."""
    out = subprocess.run(
        ["gh", "issue", "list", "--repo", repo, "--search", f'"{title_contains}" in:title', "--json", "number,title"],
        capture_output=True, text=True, timeout=60
    )
    if out.returncode != 0:
        return []
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return []


def _gh_create_issue(repo: str, title: str, body: str, labels: list[str]) -> dict | None:
    """Create a new GitHub issue."""
    cmd = ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body]
    for label in labels:
        cmd.extend(["--label", label])
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        return None
    # Extract issue number from output (format: "Created issue <repo>#<number>")
    m = re.search(r"#(\d+)", out.stdout)
    return {"number": int(m.group(1))} if m else None


def file_improvements(mode: str = "propose", repo: str = "G-Eskayo/marvin") -> list[dict]:
    """For each denial kind that has hit MIN_REPEATS, file an improvement ticket (if not already filed).

    In propose mode, returns what WOULD be filed without actually creating issues.
    In act mode, creates the issues.
    """
    groups = tally(project=repo)
    filed = []

    for group in groups:
        kind = group["kind"]
        count = group["count"]
        tickets = group["tickets"]
        title = f'Denial kind "{kind}" seen {count} times — add a rule or gate check'

        # Check if an issue with this title already exists
        existing = _gh_list_issues(repo, f'Denial kind "{kind}"')
        if existing:
            continue  # Don't file a duplicate

        body = (
            f"The denial kind **{kind}** has recurred {count} times "
            f"(tickets: {', '.join(f'#{t}' for t in tickets)}).\n\n"
            f"This pattern should be prevented by a gate check or a rule earlier in the pipeline. "
            f"See the self-improve skill (skills/self-improve/SKILL.md) for the quality-filter criteria "
            f"before implementing a fix."
        )

        if mode == "propose":
            filed.append({"title": title, "body": body, "status": "proposed"})
        elif mode == "act":
            try:
                issue = _gh_create_issue(repo, title, body, labels=["enhancement"])
                if issue:
                    filed.append({"number": issue["number"], "title": title, "status": "filed"})
            except Exception as e:  # noqa: BLE001
                print(f"[denial_diagnosis] failed to file improvement for {kind}: {e}", file=sys.stderr)

    return filed


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: denial_diagnosis.py tally [--json] | file-improvements [propose|act]", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "tally":
        result = tally()
        if "--json" in sys.argv:
            print(json.dumps(result, indent=2))
        else:
            for group in result:
                print(f"{group['project']} {group['kind']}: {group['count']} times "
                      f"(#{', #'.join(map(str, group['tickets']))})")
    elif cmd == "file-improvements":
        mode = sys.argv[2] if len(sys.argv) > 2 else "propose"
        result = file_improvements(mode=mode)
        print(json.dumps(result, indent=2))
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
