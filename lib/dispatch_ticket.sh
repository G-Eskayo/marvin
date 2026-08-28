#!/bin/zsh
# Dispatch a ready-for-agent GitHub issue to a remote machine for
# unattended headless implementation via `claude -p ... --permission-mode
# acceptEdits`. Generalizes the manual mac-mini dispatch pattern first
# used 2026-08-27 for G-Eskayo/marvin#80 -- reusable for any future
# ticket, on any target machine already reachable via an SSH host alias
# with `claude` installed at ~/.local/bin/claude (or adjust PATH_EXPORT
# below for a different install location on that machine).
#
# The caller is responsible for claiming the ticket first
# (`gh issue edit <n> --repo G-Eskayo/marvin --add-label claimed:<machine>`)
# -- claiming is fast, low-risk, and worth deciding live rather than
# folding into this script.
#
# Usage: dispatch_ticket.sh <issue_number> <target_host> <branch_name>
#
# What it does: builds a self-contained prompt (the dispatched instance
# has zero memory of any conversation that led here -- everything it
# needs comes from GitHub issues/ADRs/CONTEXT.md, which is exactly why
# this repo's doc-first process pays off here), copies it + a wrapper
# script to the target host, and launches the wrapper via `nohup` in the
# background so it survives the SSH session ending.
#
# Check progress: ssh <target_host> 'tail -f ~/dispatch_issue<n>.log'
# Final report lands at ~/dispatch_issue<n>_report.md on the target host.

set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: dispatch_ticket.sh <issue_number> <target_host> <branch_name>" >&2
  exit 1
fi

ISSUE_NUMBER="$1"
TARGET_HOST="$2"
BRANCH_NAME="$3"
REPO="G-Eskayo/marvin"

PROMPT_FILE=$(mktemp)
cat > "$PROMPT_FILE" <<EOF
You are implementing GitHub issue #${ISSUE_NUMBER} on repo ${REPO}. Read
it in full first: \`gh issue view ${ISSUE_NUMBER} --repo ${REPO}\`. If it
has a "## Parent" reference, read that issue too for full design context,
plus any docs/adr/*.md files it or its parent references, and CONTEXT.md's
relevant section.

This ticket is already claimed on your behalf -- don't claim it again. A
branch \`${BRANCH_NAME}\` already exists off \`main\` and is checked out in
this working directory (~/.agents) -- build directly on it, don't create a
new branch.

Follow this repo's existing patterns closely: look at how the most
recently merged similar work was done (recent PRs via \`gh pr list --state
merged --limit 5\`, and \`git log\`) before writing anything new. Write real
tests matching this codebase's existing test style. Run the full relevant
test suite and confirm a clean build before finishing.

If the ticket is HITL and needs live UI verification you can't get right
now (no one is watching live), substitute a real screenshot -- actually
launch the app, actually capture it (e.g. \`npm run dev\` + \`osascript\` to
bring the window forward + macOS \`screencapture\`) -- saved somewhere
durable, and note in your PR/report that it's substituting for the live
review.

Before opening a PR, check for open PRs or branches that might conflict
with or duplicate this work (\`gh pr list --repo ${REPO} --state open\`) --
if this ticket's files overlap with another open PR's, note that clearly
in your own PR description so whoever merges knows the order matters.

When done: commit, push the branch, open a PR against main
(\`gh pr create --repo ${REPO} ... --base main --head ${BRANCH_NAME}\`),
comment on issue #${ISSUE_NUMBER} with the PR link and what you verified,
and release the claim label
(\`gh issue edit ${ISSUE_NUMBER} --repo ${REPO} --remove-label
claimed:<this-machine>\` -- read the actual label off the issue first,
don't guess the machine name). Then write a final summary (what you
built, what you verified, any problems, screenshot paths, any merge-order
notes) to ~/dispatch_issue${ISSUE_NUMBER}_report.md on this machine.

Work autonomously without stopping for confirmation. For a genuine
blocker (not a design judgment call -- make the most reasonable choice
for those, consistent with this codebase's existing patterns, and note it
in your report), stop and write it to the report file instead of guessing
at anything risky. Never force-push, delete, or touch branches/PRs outside
this ticket's scope.
EOF

scp "$PROMPT_FILE" "${TARGET_HOST}:~/dispatch_issue${ISSUE_NUMBER}_prompt.md"

WRAPPER_FILE=$(mktemp)
cat > "$WRAPPER_FILE" <<EOF
#!/bin/zsh
export PATH="\$HOME/.local/bin:/opt/homebrew/bin:\$PATH"
set -e
cd ~/.agents
git checkout main
git pull origin main
git checkout -b ${BRANCH_NAME}

# ADR 0030: non-interactive -p has no TTY, so anything not pre-authorized
# hard-denies rather than prompting -- dontAsk + an explicit allowlist,
# not bypassPermissions (this worktree isn't container-isolated).

claude -p "\$(cat ~/dispatch_issue${ISSUE_NUMBER}_prompt.md)" \\
  --model claude-sonnet-5 \\
  --permission-mode dontAsk \\
  --allowedTools "Read,Edit,Write,Bash(git *),Bash(gh *),Bash(~/.agents/venv/bin/python -m pytest*),Bash(npm test*),Bash(npm install*),Bash(npx vitest run*)" \\
  > ~/dispatch_issue${ISSUE_NUMBER}.log 2>&1

echo "EXIT_CODE: \$?" >> ~/dispatch_issue${ISSUE_NUMBER}.log
EOF

scp "$WRAPPER_FILE" "${TARGET_HOST}:~/dispatch_issue${ISSUE_NUMBER}.sh"
ssh "$TARGET_HOST" "chmod +x ~/dispatch_issue${ISSUE_NUMBER}.sh && nohup ~/dispatch_issue${ISSUE_NUMBER}.sh > ~/dispatch_issue${ISSUE_NUMBER}.nohup.log 2>&1 & disown"

rm -f "$PROMPT_FILE" "$WRAPPER_FILE"
echo "Dispatched issue #${ISSUE_NUMBER} to ${TARGET_HOST} on branch ${BRANCH_NAME}."
echo "Check progress: ssh ${TARGET_HOST} 'tail -f ~/dispatch_issue${ISSUE_NUMBER}.log'"
