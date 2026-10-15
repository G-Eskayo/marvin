1. `lib/tests/conftest.py`: add `_isolate_machine_profile` (stub `machine_profile.registry_id`).
2. `lib/tests/conftest.py`: extend `_isolate_ticket_evidence` to stub `ticket_pipeline._release_dead_claims_all` → `[]` by default.
3. `lib/tests/conftest.py`: add a default stub for `running_tickets.current` → `[]`.
4. `lib/tests/test_ticket_pipeline.py`: capture `_REAL_RELEASE_DEAD_CLAIMS`/`_REAL_RELEASE_DEAD_CLAIMS_ALL` at module import time, before fixtures run.
5. `lib/ticket_pipeline.py`: in `_release_dead_claims`, replace the `running_tickets.current()`/`live_pairs` block with `dispatch_concurrency.slots_in_use(this_device)`, filtered to records whose `ticket`/`repo` match the current issue; move this (free, local) check before the grace-period/`_claim_labeled_at` check (networked) to avoid paying for a `gh api events` call when a local record already proves the claim is alive.
6. `lib/ticket_pipeline.py`: drop the now-unused `import running_tickets` block from `_release_dead_claims`.
7. `lib/tests/test_ticket_pipeline.py`: write tests 4–16 above.
8. `lib/tests/test_rework_status.py`: write test 17 above.
9. Run `~/.agents/venv/bin/python -m pytest lib/tests -q` in full (not just the two touched files) and confirm both: zero failures, and wall-clock time back down near its pre-ticket baseline — a slow-but-passing run would still mean the isolation fix is incomplete somewhere.
10. Re-read the diff against the ticket's acceptance criteria and "How we'll try to break it" list one more time before calling it done.