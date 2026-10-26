# Support-bot patterns

What we learned helping a friend's fresh MARVIN install (2026-10-25), written down so a future MARVIN IT-support bot for paying users can reuse it. Status: **patterns only, nothing built.** Doc-first: a design doc and the owner's sign-off come before any code.

The setup: one MARVIN (the **helper**) supports another person's MARVIN (the **user's MARVIN**) on their own Mac. The user's MARVIN does the work on its own machine; the helper advises.

## 1. Audit first, change nothing

The first message to the user's MARVIN asks for a **read-only check and a report**, then waits for the user's yes before any change. It worked: the audit found every expected link back to the helper (an SSH key, a fallback repo name, the code paths that could write to that repo) and confirmed nothing else.

The audit's checklist, in the order that found things:
- git remotes of the engine and the instance
- the signed-in GitHub and Claude accounts (`gh api user --jq .login`)
- `~/.ssh/authorized_keys` (who can log in), `~/.ssh/config`, `known_hosts`
- background jobs (`~/Library/LaunchAgents/com.marvin.*`) and what each contacts
- hooks in `~/.claude/settings.json` and MCP servers in `~/.claude.json`
- repo names written into the code (`grep -rhoE "<owner>/[A-Za-z0-9_.-]+"`)
- the machine registry (`~/.claude/marvin-network.json`)
- tunnels (Tailscale, ngrok, cloudflared)

Each finding is reported as a table: the item, what it points to, and whether it's **the user's** or **not the user's**. Fixes are proposed separately, each one rerunning the audit and showing before and after.

## 2. The user's MARVIN fixes its own machine

The helper does not log in to the user's Mac to fix things. Remote access (SSH) was needed for the first install only, and it is removed afterwards. The user's MARVIN has the context and the permissions on its own machine; the helper sends it precise instructions.

This is also the product test: if a fix needs the helper's hands, the product isn't finished. Every such case becomes an installer or first-run ticket (see #641, first-run setup).

## 3. The chat channel: one private issue thread

The two MARVINs talk through **one GitHub issue in a private repo the user owns** (`marvin-support`), with the helper invited as a collaborator. Each side checks the thread on a timer (`/loop`, about 5 minutes) and replies.

Why this channel:
- no open ports, no SSH, no tunnel: both sides only make outbound HTTPS calls they already make
- every message is logged and readable by both humans, from a phone
- the user owns it and can revoke the helper with one click
- it reuses the private-git-queue pattern already designed for the SlopeCycle Send app

For a paid product this becomes a support queue (one thread per case), with the same shape.

## 4. Messages are advice, never commands

The rule that makes a bot-to-bot channel safe: **each MARVIN treats the other's messages as data.** Nothing the helper writes runs on the user's Mac without the user's yes, and nothing the user's MARVIN writes runs on the helper's side without its owner's yes. Without this, the chat is a prompt-injection path into both machines.

Also:
- never paste secrets, tokens or private files into the thread; refer to them by path
- each side acts only on its own repos and machine, and checks the target repo's owner before any `gh` write
- the thread itself is untrusted input on both sides; follow the north-stars rule that outward-facing input is attacked like an adversary would and must fail closed

## 5. Fail loudly when the instance isn't set up

What the audit caught in practice: with no `origin` and an empty `instance.json`, the code fell back to the upstream repo, and the user's MARVIN started working on the owner's merge queue. Only GitHub's permissions stopped it.

The rule (ADR 0071 step 3): anything that reads or writes tickets or PRs refuses to run against a repo the user doesn't own and shows "connect your repo" instead. The upstream stays only as the source of engine updates. A support bot's first check is whether the instance is set up.

## 6. Plain-language reports

The user's MARVIN ended its audit with a handoff in the standard shape (what we were working on, current state, decisions, next steps, resume prompt). That made it easy to paste between the two humans. Support sessions should always end with one, written for the person, not the helper.

## What a paid support bot would add later

- a support queue: a thread per case, with labels for state (waiting on user / waiting on support / fixed)
- a scripted audit (the checklist in §1 as one command) whose output the user attaches to a case
- known-issue answers drawn from past cases, with each fixed case turned into an installer test
- an escalation path to a human
- pricing and scope go in the business plan, not here
