## North-star fit

**Reuses, no new design needed.** `#763`'s design was already done and merged (`docs/design/763-macs-look-after-each-other.md`, ADR 0081, PR #769, closing sub-ticket #768), and the build against that design is already done and merged too (PR #856, closing sub-ticket #847): `lib/peer_care.py` (`classify`, `fix_for`, `handle`, `read_ipn`, `expect_back`), `lib/nightly_reset.py` (`decide`, `run_night`, `restart`, `night_window`), `bin/marvin-authrestart`, `bin/marvin-peer-unlock`, `config/peer_care.json`, the launchd/systemd units, plus the separately-built memory guard (`lib/memory_guard.py`, marvin#845 — the design's "separate ticket" decision). All 12 Decisions on PR #769 are answered and baked into the shipped config (`test_config_carries_the_owner_answers_from_769` pins them). `#763` is the parent/tracking ticket; it was simply never closed after its two sub-tickets landed.

- **Simplest sufficient approach:** don't rebuild anything. The remaining work is (a) closing two narrow test-coverage gaps against the ticket's own wording, (b) writing the domain doc entry that #847/#856 skipped, (c) closing the loop on the ticket itself.
- **Resource cost:** near zero — a couple of parametrized tests and a CONTEXT.md section, not new design/build cycles. This is the "least that does the job," per north star 1.
- **Phone-OS direction:** not directly applicable; this is a reliability precondition (north star 2), not a phone-reachable feature.
- **More capable, not passive:** yes — the owner stops having to notice and manually fix a hung Mac, and stops losing a reset window to his own activity; the test coverage lets him trust it without watching it.

I verified this by reading the actual merged code and its 407+550 lines of tests (`lib/tests/test_peer_care.py`, `lib/tests/test_nightly_reset.py`), not just the PR descriptions.

## Mapping the ticket's acceptance criteria to what already exists

**AC1 — design doc + ADR + Decisions, approved before building:** done. `docs/design/763-macs-look-after-each-other.md`, ADR 0081 (status: Accepted), 12/12 Decisions answered on PR #769.

**AC2 — "Each failure mode simulated and recovered in a test (stopped webhook, stopped Tailscale, sleep), with the owner notified when it can't be fixed remotely":**
- Stopped Tailscale → fully covered end-to-end through `handle()`: opens an incident, fixes it, recovers (`test_a_fix_that_works_closes_the_incident`), a fix that "succeeds" but doesn't actually fix it still counts as a failure (`test_fix_that_says_ok_but_probe_still_fails_counts_as_a_failure`), 3 attempts then notify-once (`test_three_attempts_then_it_stops_and_tells_the_owner_once`), and a later recovery resets the budget (`test_recovery_after_giving_up_starts_a_fresh_budget_next_time`).
- Stopped webhook (service down) and sleep (asleep) → `classify()` and `fix_for()` are tested for these rows (`test_classify_the_design_table`, `test_ladder_step_switches_on_with_what_exists`), but unlike the Tailscale case, no test drives them through the *full* `handle()` incident/recovery loop. **Gap** — see Task List #2.
- Owner notified when unfixable → covered generally (`test_tell_owner_states_message_once_per_incident_and_say_what_to_do`, `test_watcher_off_the_home_lan_can_only_tell`), and specifically after 3 failed attempts.
- The ticket's own design doc (section 8) puts the literal hardware actions — actually killing the webhook, pulling Tailscale, sleeping a Mac — in a separate "live, owner-present" acceptance pass, because a headless agent must not crash real production Macs. That's correctly out of this agent's scope; it needs Gil physically present.

**AC3 — "A reset correctly waits while the owner is active and while a helper runs, then goes ahead":** fully covered — `test_run_owner_active_until_0110_rechecks_every_15_minutes_then_resets` and `test_run_helper_exit_triggers_the_reset_without_a_timer`.

Beyond the ticket's literal wording, the existing tests already attack it adversarially per north star ("tests try to break it"): concurrent triggers on the same peer, a crash mid-fix still spending its budget, clock skew, malformed IPN JSON, non-UTF-8 command output, a path-traversal peer name fed to the root unlock script, and proof the FileVault password never touches argv/env/disk. Nothing more to add there.

## Tests to write first (closing the one real gap)

1. `test_peer_care.py`: parametrize the existing recovery path (`World` + `handle()`) over `state="service"` (webhook down, `services_ok=False` → `restart-service`) and `state="asleep"` with Ethernet present (→ `wake`), each driven from a down-probe to an up-probe, asserting `action == "fixed"` and the right fix name recorded in `w.fixes`. This is the same harness the existing "network" recovery tests use (`World`, `DOWN`/`UP` probes) — just parametrized over state, no new scaffolding.
2. No new tests needed for AC3 (already fully covered) or AC1 (not code).

## Decisions

None. All Decisions required by this ticket were already asked and answered on PR #769, and are pinned in the shipped config (`test_config_carries_the_owner_answers_from_769`). There is nothing left for the owner to choose here.

## Task List

1. Add parametrized `handle()`-level recovery tests for the "service" and "asleep" states in `lib/tests/test_peer_care.py` (closing the literal AC2 gap described above). No production code changes expected — this only exercises existing `classify`/`fix_for`/`handle`.
2. Add a CONTEXT.md section documenting peer care and the nightly reset (pattern: the existing dated "built"/"decided" sections, e.g. `## Third node: mac-mini-2012 (in design, 2026-10-16)`, `## Merges under memory pressure (built 2026-10-30, marvin#940)`). Cover: the four no-polling triggers, `classify`'s six states and their fix ladder, the 3-attempt budget and per-peer lock, the nightly reset's guardrails and the FileVault/`authrestart` credential path, and that Ethernet/2012-online/smart-plug/root-script-setup are the owner's remaining physical steps that switch on more of the ladder with no further code. This fills the gap left by #847/#856, whose merge never touched CONTEXT.md, so a future agent researching this area isn't stuck re-deriving it from 1,100+ lines of code.
3. Run `lib/tests/test_peer_care.py` and `lib/tests/test_nightly_reset.py`, then the full Python test suite (per "full suites before a hand-merge" — a merge here must not silently break something these modules share, like `job_events` or `code_sync`).
4. Open the PR with "Closes #763", summarizing that the design (#768/#769) and build (#847/#856) are both already merged, that this PR only closes the one test-coverage gap and the missing domain doc, and that the owner's outstanding physical steps (Ethernet for the Mini, bringing the 2012 back online, buying the smart plug, running `marvin-reset-setup`/`marvin-peer-unlock-setup` on each Mac) are what's left before the full fix ladder is live — none of which need new code.