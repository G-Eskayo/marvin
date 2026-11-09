## North-star fit

**Reuses:** the existing `machine` field on `job_catalog.JOBS` (`lib/job_catalog.py:40-113`) and the placement check it drives, `evaluate_job_placement` in `lib/health_checks.py:1101-1114`. That field already encodes exactly this shape of decision for other jobs (`daily-digest`: `"mini"`, `daily-digest-fallback`: `"laptop"`). No new mechanism is needed — just setting `tidy-agent`'s existing field to the value the owner chose. I checked job_units.py (`lib/job_units.py`) too: it has no machine-scoping of its own, so the catalog's `machine` field is the one and only place "where a job runs" is recorded (confirmed by `test_health_placement_is_derived_from_the_catalog_not_kept_twice`).

**Simplest sufficient approach:** a one-line dict value change (`"both"` → `"mini"`) plus correcting the PR description's "After merge" instructions so Gil doesn't install the job on the laptop too. No new code path, no new abstraction.

**Tokens:** small, bounded cost now (one commit + one PR reply) against a real recurring cost it prevents — both Macs racing to tidy the same iCloud-shared `~/Desktop`/`~/Downloads` nightly is exactly the kind of silent contention ns2 rules out, and the current PR body would have had Gil re-create that race by hand on the laptop.

**Phone-OS fit:** neutral (background job placement, not a capability).

**User capability:** leaves Gil more capable/freed — Health now catches a stray laptop install automatically instead of him noticing file-organizer races later by hand.

The PR's own stated north-star fit ("ns2 and ns3, needs no new permissions") still holds; it just didn't yet reflect the owner's "Mini only" tick.

## What "could we consider this on the 2012?" resolves to

Checked against `docs/adr/0069-kali-node-pulls-code-and-pushes-only-reviewed-branches.md` and `config/mac-mini-2012/README.md`: no, it doesn't fit, for three independent reasons — (1) mac-mini-2012 runs Kali Linux with no macOS `~/Desktop`/`~/Downloads`/iCloud at all, so there's nothing for `tidy_agent.py` to organize there; (2) its registry entry only `"accepts": ["security", "quarantine", "test", "bench"]` work (ADR 0069 §6, README §7) — `tidy-agent` is untagged "general" macOS work, which only the Macs accept; (3) it's pull-only and "never writes to `~/.claude`" (README §9), which is where the organizer and its map live. This is a factual "no," not a judgment call, so it goes in the reply as a plain answer, not a new Decisions section.

## Tests I'll write first

The ticket's own "How we'll try to break it" items are process risks for me as the acting agent, not code behavior — I'm treating them as pre-commit checks rather than forcing them into fake pytest tests:
- *"The notes contradict a chosen option"* → re-read the full Decisions comment and PR body before committing (done above: the only note is the 2012 question, which doesn't contradict "Mini only").
- *"The PR changed since the decisions"* → re-fetch `gh pr view 1129` immediately before pushing, not just now.

The one piece of actual code behavior changing (`job_catalog.JOBS["tidy-agent"]["machine"]`) gets a paired test, plus one adversarial case the ticket's list doesn't mention — a person reinstalling the old habit on the laptop:

1. `jc.JOBS["tidy-agent"]["machine"] == "mini"` — direct assertion of the chosen option, so verify fails if the catalog value changes without the test changing.
2. `hc.evaluate_job_placement(["tidy-agent"], "laptop")` returns `"yellow"` naming `tidy-agent` as stray — covers "a person's mistake": if Gil (or old muscle memory) runs `job_units.py install tidy-agent` on the laptop again, Health must flag it instead of staying silently green (ns2).
3. Rerun `test_a_switched_off_job_is_never_reported_missing` and `test_health_placement_is_derived_from_the_catalog_not_kept_twice` (both already build their expectations dynamically from `JOB_PLACEMENT`/`JOBS`, so they should stay green with no edits — run them to confirm, not to change them).

No changes needed to `lib/tests/test_job_units.py` or `lib/cron_health.py`'s tests — nothing there is machine-scoped.

## Decisions

None needed. The owner's note is answerable with existing architecture facts (above); nothing in this ticket requires asking Gil to choose anything further.

## Task List

1. Fetch and check out `phase0/tidy-agent-venv` in this worktree.
2. Re-read PR #1129's current body and Decisions comment to confirm nothing changed since filing (repeat the check done above at commit time).
3. Edit `lib/job_catalog.py`: change `tidy-agent`'s `"machine": "both"` to `"machine": "mini"`.
4. Edit `lib/tests/test_job_catalog.py`: add a test asserting `jc.JOBS["tidy-agent"]["machine"] == "mini"` and that `hc.evaluate_job_placement(["tidy-agent"], "laptop")` comes back `"yellow"` naming `tidy-agent`.
5. Run `lib/tests/test_job_catalog.py`, `lib/tests/test_job_units.py`, `lib/tests/test_health_checks.py` on the venv Python; confirm green.
6. Edit PR #1129's description "After merge (each Mac)" section via `bin/gh pr edit`: Mini gets `job_units.py install tidy-agent` + bootout/trash of the old `com.giles.tidy-agent` plist; laptop gets only the bootout/trash step, no new job installed.
7. Commit the two file changes on `phase0/tidy-agent-venv` (message references #1137 and the chosen Decision option), push to origin.
8. Post a reply comment on PR #1129 via `bin/gh pr comment` carrying `<!-- marvin:decisions-addressed -->`: states the commit, that `machine` is now `"mini"` and the laptop install step was dropped from the PR body; answers "could we consider this on the 2012?" with "no" and the three concrete reasons above; states no screenshots were retaken because nothing visual changed (config/lib/tests only).
9. Confirm the comment clears `bin/gh`'s decisions gate (no unstructured question heading in it) and that ticket #1137 is positioned to self-close per `lib/owner_decisions.py` once PR #1129 is addressed.