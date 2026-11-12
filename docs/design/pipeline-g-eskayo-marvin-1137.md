## North-star fit

**Reuses:** `lib/job_catalog.py`'s `machine` field + `lib/health_checks.py:evaluate_job_placement`/`JOB_PLACEMENT` (health_checks.py:1091-1115) — the exact data-driven placement/drift mechanism already used for every other dual-machine job (`daily-digest`/`-fallback`, `research-colony`/`-fallback`, `morning-brief`/`-fallback`). It needs no new code: flipping one value (`"both"` → `"mini"`) is sufficient, because `evaluate_job_placement` already treats any catalogued `machine` value generically (missing/stray/unplaced). Also reuses `lib/machine_profile.py:pull_only()` / `remote_macs()` (ADR 0069) as the existing, already-adjudicated answer to "why not the 2012": that ADR and that code already establish mac-mini-2012 as a Linux, pull-only, non-general node that only mirrors `~/.agents`/`~/.claude` — not the iCloud-synced `~/Desktop`/`~/Documents` tree tidy-agent organizes.

**Simplest sufficient approach:** one catalog value change + matching test + a PR-body runbook correction + a factual reply. No new abstraction, no new job-placement mechanism, no code for the "2012" answer — it's already decided by ADR 0069 and provable from existing code, not a new design question.

**Tokens:** spends a little now (reading PR/ADR/registry code to ground the reply factually) to avoid a much bigger, speculative cost later (don't open a scoping ticket for an iCloud-on-Linux bridge nobody asked to build — that would be guessing at a want, not meeting one).

**Phone-OS / capability:** neutral — this is host-placement hygiene for an existing job, not new reach.

**User capability:** leaves Gil more informed, not more passive — it tells him plainly why the 2012 isn't a drop-in option today (so he can decide, later and separately, whether that's worth building) instead of silently humoring the idea or guessing an answer.

## Tests first (ticket's "How we'll try to break it" + misuse)

1. **Notes-contradict-chosen-option guard** — re-derive the chosen option straight from the PR description's ticked box (`[x] The Mini only`) and the machine-readable `marvin-decisions` JSON block (`"choices": ["The Mini only"]`), not from the prose note. Verified by eye before editing (not pytest-able — it's a reading-comprehension check): the note asks a *follow-up* question, it doesn't contradict the ticked choice, so no contradiction to flag.
2. **PR changed since the decisions** — re-fetch `gh pr view 1129` immediately before committing, to catch a race (new commits, a superseding Decisions comment, or the PR having closed) between this plan and the implementation step.
3. **`test_tidy_agent_is_placed_on_the_mini_only`** (new, `lib/tests/test_job_catalog.py`) — `jc.JOBS["tidy-agent"]["machine"] == "mini"`. Written first against the current `"both"` value (red), then the catalog edit turns it green.
4. **`test_job_placement_flags_tidy_agent_stray_on_the_laptop`** (new, `lib/tests/test_health_checks.py`, same pattern as the existing `test_job_placement_flags_missing_stray_and_unplaced_jobs`) — with `tidy-agent` now `"mini"`-only, `evaluate_job_placement(["tidy-agent", ...], "laptop")` reports it under "running here but meant for the other machine", and `evaluate_job_placement([...], "mini")` with `tidy-agent` present stays green. Exercises the real production function, no mock.
5. **Existing regression guard** — `test_health_placement_is_derived_from_the_catalog_not_kept_twice` (already in `test_job_catalog.py`) must keep passing unmodified: it is the thing that would catch `JOB_PLACEMENT` and `JOBS["tidy-agent"]["machine"]` ever disagreeing.
6. **Bad/empty/malformed input** — not applicable: this is a data-value + doc change, no new parsing/IO surface. `job_catalog.validate`-style input checks already exist for `job_units.py` and are untouched.
7. **Each dependency failing** — the PR-comment reply only depends on `gh` (via the gated `bin/gh`) succeeding; if posting fails, the implementation step must retry/report rather than silently stopping (existing `bin/gh` gate behavior, not new code).
8. **Repeats / wrong order** — re-running the catalog edit is idempotent (setting `"mini"` twice is a no-op); the PR reply must not be posted twice — check for an existing `<!-- marvin:decisions-addressed -->` reply on PR #1129 before posting (mirrors `owner_decisions.py`'s own dedup-before-filing pattern) so a retried run doesn't double-comment.
9. **A person's mistake** — don't re-edit the owner's already-submitted Decisions block/checkboxes in the PR body; only touch the "After merge" runbook text beneath it.

No pytest is needed for the "2012" answer itself — it's a factual claim grounded in `docs/adr/0069-kali-node-pulls-code-and-pushes-only-reviewed-branches.md` and `lib/machine_profile.py:pull_only()`/`remote_macs()`, both already covered by `lib/tests/test_pull_only_node.py` and `lib/tests/test_remote_macs.py`.

## Decisions

None needed. The chosen option ("The Mini only") is unambiguous, and Gil's note is answerable as settled fact from ADR 0069 (mac-mini-2012 is Linux, pull-only, holds no iCloud `~/Desktop`/`~/Documents` data, and isn't a "general"-work node) — not a fork requiring his choice. Nothing here is asked in prose on the PR; the reply states this as a finding, not a question.

## Task List

1. Fetch and check out `phase0/tidy-agent-venv` (PR #1129's branch) in this worktree; re-run `gh pr view 1129` to confirm nothing changed since the decisions were read.
2. Write the two failing tests first: `test_tidy_agent_is_placed_on_the_mini_only` in `lib/tests/test_job_catalog.py`, and `test_job_placement_flags_tidy_agent_stray_on_the_laptop` in `lib/tests/test_health_checks.py`. Confirm both fail (red) against the branch's current `"machine": "both"`.
3. Edit `lib/job_catalog.py`: change the `tidy-agent` entry's `"machine"` from `"both"` to `"mini"`. Run `test_job_catalog.py`, `test_health_checks.py`, and `test_job_units.py` to confirm green, with no other assertion broken (especially `test_health_placement_is_derived_from_the_catalog_not_kept_twice`).
4. Edit PR #1129's description "After merge (each Mac)" section: split it into Mini (install the new job + remove the old `com.giles.tidy-agent` plist, as today) and laptop (remove the old `com.giles.tidy-agent` plist only — no new install), so the runbook matches "Mini only" instead of silently still deploying to both.
5. Commit the test + catalog changes on `phase0/tidy-agent-venv` with a message naming #1137 and #1129.
6. Post the PR reply comment (via the gated `bin/gh`) carrying `<!-- marvin:decisions-addressed -->`: state the commit that carries out "Mini only"; state there are no screenshots to retake/pin (mutation score was 100% with 0 mutable lines — config/tests/docs only, nothing visual changed); answer the "could we consider this on the 2012?" note with the ADR 0069 / `machine_profile.pull_only()` finding — mac-mini-2012 has no path to the iCloud-synced `~/Desktop`/`~/Documents` today (it only mirrors `~/.agents`/`~/.claude`) and isn't registered for general macOS housekeeping work, so moving tidy-agent there isn't a drop-in swap; offer, without asking in prose, that a future ticket could scope an iCloud bridge if he ever wants to pursue it.
7. Verify: re-read PR #1129 once more after posting to confirm the comment landed with the marker, and that #1137 is positioned to close once GitHub's automation sees the addressed reply.