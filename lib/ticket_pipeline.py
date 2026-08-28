#!/usr/bin/env python3
"""Ticket pipeline: scans G-Eskayo/marvin for `ready-for-agent` issues with
no existing claim, and dispatches the oldest one to an available machine
for unattended headless implementation (claude -p --permission-mode
acceptEdits).

Generalizes the manual pattern in dispatch_ticket.sh (first used
2026-08-27 for #80) into a scheduled scanner -- see that script's header
for the original prompt structure and safety invariants this reuses
(self-contained prompt, since the dispatched session has zero memory of
any conversation; never force-push/delete outside the ticket's scope;
work autonomously, stop and report genuine blockers instead of guessing).

One ticket per run, by design: keeps blast radius small and lets
task_dispatch's per-machine busy-lock do the concurrency control -- a
still-running ticket keeps its machine "busy" (dispatch-state.json), so
the next scan naturally skips it or picks the other machine instead.

Claiming (adding claimed:<machine> label) happens right before dispatch,
not earlier -- a small TOCTOU race against a concurrent scan on the other
machine is possible but low-stakes for a 2-machine personal setup: worst
case is a wasted duplicate PR, and every PR still needs human approval
before merge regardless (the MR-review tab's whole reason to exist).

Run standalone: ~/.agents/venv/bin/python ticket_pipeline.py [--dry-run]
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
from task_dispatch import select_machine, dispatch  # noqa: E402

REPO = "G-Eskayo/marvin"
LOG_PREFIX = "[ticket-pipeline]"


def _label_for_device(device_id: str) -> str:
    return "mac-mini" if device_id.startswith("mac-mini") else "macbook-pro"


def _unclaimed_ready_tickets() -> list[dict]:
    proc = subprocess.run(
        ["gh", "issue", "list", "--repo", REPO, "--label", "ready-for-agent",
         "--state", "open", "--json", "number,title,labels,createdAt"],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        print(f"{LOG_PREFIX} gh issue list failed: {proc.stderr[:300]}", file=sys.stderr)
        return []
    issues = json.loads(proc.stdout)
    unclaimed = [
        i for i in issues
        if not any(l["name"].startswith("claimed:") for l in i["labels"])
    ]
    unclaimed.sort(key=lambda i: i["createdAt"])
    return unclaimed


def _claim(issue_number: int, label: str) -> bool:
    proc = subprocess.run(
        ["gh", "issue", "edit", str(issue_number), "--repo", REPO, "--add-label", f"claimed:{label}"],
        capture_output=True, text=True, timeout=15,
    )
    if proc.returncode != 0:
        print(f"{LOG_PREFIX} failed to claim #{issue_number}: {proc.stderr[:300]}", file=sys.stderr)
        return False
    return True


def _release(issue_number: int, label: str) -> None:
    subprocess.run(
        ["gh", "issue", "edit", str(issue_number), "--repo", REPO, "--remove-label", f"claimed:{label}"],
        capture_output=True, text=True, timeout=15,
    )


def _build_prompt(issue_number: int, branch_name: str, claim_label: str) -> str:
    return f"""You are implementing GitHub issue #{issue_number} on repo {REPO}. Read
it in full first: `gh issue view {issue_number} --repo {REPO}`. If it
has a "## Parent" reference, read that issue too for full design context,
plus any docs/adr/*.md files it or its parent references, and CONTEXT.md's
relevant section.

This ticket is already claimed on your behalf (label claimed:{claim_label})
-- don't claim it again. A branch `{branch_name}` already exists off `main`
and is checked out in this working directory (~/.agents) -- build directly
on it, don't create a new branch.

Follow this repo's existing patterns closely: look at how the most
recently merged similar work was done (recent PRs via `gh pr list --state
merged --limit 5`, and `git log`) before writing anything new. Write real
tests matching this codebase's existing test style. Run the full relevant
test suite and confirm a clean build before finishing.

If the ticket is HITL and needs live UI verification you can't get right
now (no one is watching live), substitute a real screenshot -- actually
launch the app, actually capture it (e.g. `npm run dev` + `osascript` to
bring the window forward + macOS `screencapture`) -- saved somewhere
durable, and note in your PR/report that it's substituting for the live
review.

Before opening a PR, check for open PRs or branches that might conflict
with or duplicate this work (`gh pr list --repo {REPO} --state open`) --
if this ticket's files overlap with another open PR's, note that clearly
in your own PR description so whoever merges knows the order matters.

When done: commit, push the branch, open a PR against main
(`gh pr create --repo {REPO} ... --base main --head {branch_name}`),
comment on issue #{issue_number} with the PR link and what you verified,
and release the claim label
(`gh issue edit {issue_number} --repo {REPO} --remove-label
claimed:{claim_label}`). Then write a final summary (what you built, what
you verified, any problems, screenshot paths, any merge-order notes) to
~/dispatch_issue{issue_number}_report.md on this machine.

Work autonomously without stopping for confirmation. For a genuine
blocker (not a design judgment call -- make the most reasonable choice
for those, consistent with this codebase's existing patterns, and note it
in your report), stop and write it to the report file instead of guessing
at anything risky. Never force-push, delete, or touch branches/PRs outside
this ticket's scope."""


# ADR 0030: non-interactive -p has no TTY, so anything not pre-authorized
# hard-denies rather than prompting -- dontAsk + an explicit allowlist, not
# bypassPermissions (this checkout isn't container-isolated). This whole
# function is superseded by G-Eskayo/marvin#95 (driving execute_ticket +
# raise_mr instead), which moves git/gh work to plain subprocess calls
# outside any nested Claude session -- kept working here in the meantime
# so dispatch isn't broken until #95 lands.
_WRAPPER_ALLOWED_TOOLS = (
    "Read,Edit,Write,Bash(git *),Bash(gh *),"
    "Bash(~/.agents/venv/bin/python -m pytest*),"
    "Bash(npm test*),Bash(npm install*),Bash(npx vitest run*)"
)


def _build_wrapper_command(issue_number: int, branch_name: str, prompt: str) -> str:
    prompt_path = f"/tmp/ticket_{issue_number}_prompt.md"
    return (
        f"cat > {prompt_path} << 'TICKET_PROMPT_EOF'\n{prompt}\nTICKET_PROMPT_EOF\n"
        f"cd ~/.agents && "
        f"git checkout main && git pull origin main && "
        f"git checkout -b {branch_name} && "
        f'claude -p "$(cat {prompt_path})" --model claude-sonnet-5 '
        f'--permission-mode dontAsk --allowedTools "{_WRAPPER_ALLOWED_TOOLS}" '
        f"> ~/dispatch_issue{issue_number}.log 2>&1; "
        f'echo "EXIT_CODE: $?" >> ~/dispatch_issue{issue_number}.log; '
        f"rm -f {prompt_path}"
    )


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    tickets = _unclaimed_ready_tickets()
    if not tickets:
        print(f"{LOG_PREFIX} no unclaimed ready-for-agent tickets", file=sys.stderr)
        return

    ticket = tickets[0]
    issue_number = ticket["number"]

    selected = select_machine()
    if selected is None:
        print(f"{LOG_PREFIX} #{issue_number} ready but no machine currently available", file=sys.stderr)
        return
    device_id, _info = selected
    claim_label = _label_for_device(device_id)
    branch_name = f"agent/issue-{issue_number}"

    if dry_run:
        print(f"{LOG_PREFIX} [dry-run] would claim #{issue_number} ({ticket['title']}) "
              f"and dispatch to {device_id} as claimed:{claim_label}", file=sys.stderr)
        return

    if not _claim(issue_number, claim_label):
        return

    prompt = _build_prompt(issue_number, branch_name, claim_label)
    command = _build_wrapper_command(issue_number, branch_name, prompt)

    result = dispatch(command, target=device_id, mode="async",
                       task_label=f"ticket #{issue_number}: {ticket['title'][:40]}")
    if result.ok:
        print(f"{LOG_PREFIX} dispatched #{issue_number} to {device_id}", file=sys.stderr)
    else:
        print(f"{LOG_PREFIX} dispatch failed for #{issue_number}: {result.error} -- releasing claim", file=sys.stderr)
        _release(issue_number, claim_label)


if __name__ == "__main__":
    main()
