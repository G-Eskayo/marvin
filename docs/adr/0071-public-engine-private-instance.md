# 0071 — Public engine, private instance: one MARVIN codebase, one private state repo per person

## Status

Proposed (2026-10-25). Amended by [[0072]]: only free add-ons ship inside the engine; paid add-ons live in private repos.

## Context

`~/.agents` is two things in one public repo (G-Eskayo/marvin): the MARVIN **engine** (skills, hooks,
dashboard, brain-map, `setup.sh`, `lib/`) and one person's **instance state** (plans, bench metrics,
per-project profiles, the retrospective log, CONTEXT notes about its owner). Code sync ([[0021]]) commits
with `git add -A` minus a deny-list (`.gitignore`) and pushes to that public remote with no content check.

On 2026-10-25 that pushed a 2 MB Claude session transcript (`logs/*.jsonl`) to the public repo, and the
owner's phone number and clearance status had been public since July in a skill template. The existing
guards were in other places: snapshot redaction covers only the published brain-map, and the allow-list
covers only `~/.claude`, whose remote is self-hosted ([[0022]]). A deny-list is public-by-default: any new
file is published until someone thinks to exclude it.

The same mixing blocks the second goal: installing a blank MARVIN for another person. A clone carries the
owner's state, the dashboard reads the owner's home path, launchd plists hardcode it, and the new user's
auto-sync would try to push to the owner's repo.

## Decision

1. **Two repos per person.** The engine stays public and shared (`G-Eskayo/marvin`, pulled as
   `upstream`). Each person's state lives in their own **private** instance repo under their own GitHub
   account, and auto-sync pushes only there. `~/.claude` keeps its self-hosted remote ([[0022]]).
2. **Public by allow-list, not deny-list.** What may reach the engine repo is an explicit list of engine
   paths. A new file is private until it is added to the list on purpose.
3. **Three gates on every public push**, same patterns at each:
   - `bin/pre-push-guard`, linked as the `pre-push` hook by `setup.sh`: refuses commits adding
     transcript-shaped files, secrets, or any line matching a pattern. Shared patterns are committed
     (`config/push-guard/patterns.txt`); each person's own strings live in
     `~/.claude/private-push-patterns.txt`, never committed because it holds the strings it protects.
     A missing private file refuses the push rather than pushing blind;
   - `code_sync.py push` runs the same script itself before pushing, so a clone without the hook is
     still checked;
   - CI runs gitleaks and the same script (shared patterns only) on every PR and push to `main`.
   Only the commits the remote lacks are scanned, so a matching line already public (a test fixture)
   never blocks later pushes.
4. **Blank install.** `setup.sh --new` creates the person's private instance repo and wires every hook
   (save, SessionStart, UserPromptSubmit); `setup.sh --join <instance-repo>` adds another of *their*
   machines, the same sync path two of the owner's Macs use today. No path, host or account name of any
   one person is hardcoded; all derive from `$HOME`, `hostname` and the instance config.
5. **Hardware profiles.** `setup.sh` detects fanless or battery machines and sets the DesktopLive
   wallpaper to a low-power profile (lower frame rate, paused on battery).

## Build order

1. Guard in `setup.sh`, `code_sync.py` and CI (this ADR's first PR).
2. Engine/instance split: move the owner's state into a private instance repo; auto-sync pushes only
   there; an allow-list decides what the engine repo may carry.
3. Installer: `--new` / `--join`, every hook, the dashboard installed as an app, no hardcoded home
   paths, hardware profiles.
4. First-run setup: the new person's first session collects name, goals and projects into their memory.
5. Proof: a fresh install into a throwaway `$HOME`, scanned with zero hits for the owner's data.

## Consequences

Another person can run MARVIN from the public engine and add their own machines without any path back
into the owner's repo, and the owner's state stops being public by accident. Engine improvements still
reach everyone through `upstream`. The cost is a one-time migration of the owner's state out of
`~/.agents` into the private instance repo, and an allow-list that has to be kept current when a new
engine folder is added (a missed entry fails safe: the file stays private).

Space/time: the push scan reads only the new commits' added lines, O(size of the push); the allow-list
check is O(changed paths). Neither grows with repo history.

Alternatives considered: tightening `.gitignore` only (rejected: still public by default, it is what
failed); making the engine repo private (rejected: the engine is meant to be public and shareable);
one repo with an `instance/` folder that is ignored (rejected: the instance still needs a durable,
cross-machine remote, which brings back a second repo anyway).
