This ticket has no open design questions — it's a fully mechanical text trim with exact wording given. No Decisions section needed. I now have everything required to write the plan.

## North-star fit

**Reuses:** no new mechanism at all — this is a one-field text edit to `skills/caveman/SKILL.md`'s existing YAML frontmatter `description:` block (lines 3–14), using the exact replacement text the ticket already specifies. The verification pattern it reuses is `skills/self-improve/scripts/rebuild-manifest.py`'s existing frontmatter-parse step (run directly, no piped stdin → full rebuild per its `_hook_should_skip` docstring), not a new check.

**Simplest sufficient approach:** delete the clause, nothing else. No refactor of the frontmatter structure, no touching the body (persistence rules, examples, auto-clarity exception) — none of that is in scope.

**North star 1 (tokens):** this frontmatter `description` loads into every session's skill list, so removing a ~27-word dead clause is a small, permanent per-session token saving, in every session, forever — exactly the north star's framing.

**North star 4/capability:** purely editorial; doesn't change behavior, so "more capable vs. more passive" doesn't apply — it's a resource cleanup, not a capability change. No north star argues against it: the full rationale stays recoverable from `bench/RESULTS.md` (confirmed above: Run 1 "backfired", Run 16 "confounded" retest, Run 31 current 11%/39% figures), so nothing is lost, only de-duplicated.

Verified against the live file (`skills/caveman/SKILL.md:3-14`): the clause to delete is exactly `— an earlier always-on configuration appeared to backfire but that test was later found to be confounded, not a real flaw in this mechanism.` All six required trigger phrases ("caveman mode", "talk like caveman", "use caveman", "less tokens", "be brief", "/caveman") are present today and the edit doesn't touch any of their lines. `.claude/commands/caveman.md` is not a path inside this repo (it's a symlink in the user's home `~/.claude`, outside `~/.agents`), confirming the ticket's note that there's genuinely only one file in this repo to edit.

**Decisions:** none — the ticket gives exact replacement wording, and nothing here requires an owner choice.

## Tests first

Ticket says "Docs-only: exempt" for break-it testing. I'll still add the three acceptance-criteria checks as the verification, since they're mechanical and catchable by script, not by human judgment:

1. **No "backfire"/"confounded" substrings remain** in `skills/caveman/SKILL.md`'s frontmatter description — grep check.
2. **All 6 trigger phrases still present** verbatim: "caveman mode", "talk like caveman", "use caveman", "less tokens", "be brief", "/caveman" — grep check per phrase.
3. **Frontmatter still parses and manifest rebuild succeeds** — run `skills/self-improve/scripts/rebuild-manifest.py` directly (CLI mode, no stdin) and confirm it exits 0 / doesn't error on this file's YAML.

No misuse/adversarial cases apply beyond these: this is a static doc file, not an input surface (no user input, no dependency call, no concurrency path) — nothing else in the north-star's "how we'll try to break it" checklist (bad/huge/malformed input, dependency failure, repeats, permissions, stale state) has any attack surface here.

## Task List

1. Edit `skills/caveman/SKILL.md` frontmatter: delete the clause `— an earlier always-on configuration appeared to backfire but that test was later found to be confounded, not a real flaw in this mechanism.`, keeping everything else (Run 16/31 figures, `RESULTS.md` pointer, "opt-in only, not session-wide", all 6 trigger phrases) verbatim, re-flowing the YAML block scalar so it stays valid.
2. Run `rebuild-manifest.py` directly and confirm it completes without error (acceptance criterion 3).
3. Grep-verify acceptance criteria 1 and 2 (no "backfire"/"confounded"; all 6 trigger phrases present).
4. Open PR against `main`.