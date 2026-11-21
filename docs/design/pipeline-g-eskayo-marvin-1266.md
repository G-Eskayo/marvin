## North-star fit

**Reuses:** `lib/ticket_pipeline.py::_select_for_profile` (lines 822–862) already knows how to rank/filter the devices in a profile — it just has no notion of "skip this one, I already tried it." The fix adds a single `exclude` filter to that existing selection loop and wraps the existing selection call in `_dispatch_one` (lines 1058–1081) in a small bounded retry, instead of inventing a second selection path. The existing refusal-list plumbing (`refusals`, already threaded through `_select_for_profile` → `_dispatch_one` → `_scan`'s `step()`/Health's `_classify_stall_reason`) is reused to carry the new memory/merge-hold reason, rather than adding a second reporting channel.

**Simplest sufficient approach:** a `for`-bounded loop (bounded by the machine count in the profile, so it can never spin) that re-asks `_select_for_profile` with the held machine excluded, only when the one it picked is this scanning machine and `memory_guard.guard` refuses it. Remote machines are untouched — the guard only ever applies to "is this machine's own memory/merge," so a laptop pick short-circuits immediately, same as today.

**Token/compute cost:** near zero — this only runs extra work (one more `_select_for_profile` call, each O(number of machines) ≤ 2 today) in the one case that's currently broken (a held scanning machine); the common case (no hold) is unchanged, one call as before.

**North star 5 fit (every machine works, none overloaded):** this is exactly what #1266 is — the laptop sitting idle with free slots while the Mini was held for a merge is the failure mode north star 5 names directly. The fix makes the scan actually look at the laptop's headroom instead of stalling on the Mini.

**User impact:** fully internal/automated; no change in what the user does — tickets that used to wait an hour now dispatch to the idle machine within the same scan. More capable (throughput), not more passive (no behavior change for the user at all).

No open owner decision — the acceptance criteria fully determine the design; nothing here is a judgment call that needs Gil's input.

---

## Root cause (confirmed by reading the code)

`_dispatch_one` (ticket_pipeline.py:1058–1081) calls `_select_for_profile` once, gets back a device, and — only if that device `is_self` — calls `memory_guard.guard(...)`. If the guard refuses (a merge is pending/running on *this* machine, or memory pressure), the function returns `"memory"` immediately. `_select_for_profile` is never asked again, so the other machine in the profile (the laptop) is never considered even when it's idle. `_select_for_profile` itself has no way to be told "not that one" — there's no `exclude` parameter. This matches the issue's evidence line (`"A merge is running on the Mac mini, so #1193 waits"`) exactly: the guard fired, and the function gave up instead of trying the laptop.

Also confirmed: `lib/dispatch_concurrency.py::can_start_another` (the parallel-mode guard-rail check already inside `_select_for_profile`) has no knowledge of merge-pending/memory-pressure at all — so even in parallel mode (the live `config/dispatch.json` has `"parallel": true` today), the Mini is deemed "viable" by `_select_for_profile` and only found out to be held *after* selection, by which point the laptop's viability was already discarded.

## Tests to write first

In `lib/tests/test_ticket_pipeline.py`, following the existing `# ── memory guard (marvin#845) ──` section's style and fixtures (`_one_ready`, direct `tp._select_for_profile(...)` / `tp._dispatch_one(...)` calls):

1. **The acceptance criterion itself:** Mini selected first, its `memory_guard.guard` refuses (merge pending), laptop is viable → `_dispatch_one` dispatches to the laptop, not the Mini. Assert `dispatch(...)` was called with `target="macbook-pro-1"` and the claim label matches it.
2. **Both machines held/unviable** → ticket waits: outcome is `"memory"` (or `"no-machine"`, whichever applies), nothing claimed/dispatched, and the step/`refusals` output contains *both* machines' reasons (not just the first).
3. **The laptop is unreachable over SSH** (`select_machine` returns `None` for it) while the Mini is held → no crash, no infinite loop, ticket correctly waits with the Mini's reason recorded.
4. **The merge ends between the guard check and the retry** (guard refuses on the first call, then returns `ok: True` on a second call for the *same* device because pressure/merge cleared) — the retry must not re-try the *same* already-excluded device; simulate via a `guard` stub that changes behavior across calls and assert the loop still terminates and behaves sanely (doesn't dispatch to a device it already excluded in this pass — that's `_scan`'s next run's job, not a mid-loop flip-flop).
5. **A remote (non-self) machine is still never guard-checked** — extend the existing `test_another_macs_dispatch_does_not_read_this_macs_memory` pattern to the retry path: if the *first* candidate is already remote, `memory_guard.guard` must not be called at all (regression guard for the new loop).
6. **Bounded retry / no infinite loop**: a profile with only one machine (the held one) — the retry must terminate after excluding it (profile machines exhausted), returning `"memory"`, matching today's single-machine behavior exactly (regression check against `test_under_memory_pressure_this_mac_neither_claims_nor_dispatches_and_queues_a_rescan`).
7. **Every machine's reason surfaces, including "not reachable"**: `_select_for_profile` with a device profile where `select_machine` returns `None` for one device — assert a refusal reason is now recorded for it (closing the pre-existing silent-`continue` gap), both in the non-parallel serial branch and the `is_self`-busy / `missing_here` branches that currently `continue` without recording anything.
8. **Repeats/idempotency**: calling `_dispatch_one` twice in a row (simulating the next hourly scan) after the first call left the ticket waiting — the second call must not double-count or corrupt `taken`/`refusals` state (these are passed in fresh per `_scan` iteration already, but add a direct test since `_dispatch_one` is the unit under test here).
9. **`_select_for_profile`'s new `exclude` param defaults to `None`/empty** — existing callers (`health_checks.py`'s `select_for_profile_impl`, which never passes `exclude`) keep working unchanged; add/extend a direct unit test asserting `_select_for_profile(profile)` (no `exclude` kwarg) behaves exactly as before.
10. **Parallel-mode interaction**: with `settings["parallel"] = True` (today's live default) and both machines passing `can_start_another` (slots free), Mini's merge hold still routes to the laptop — this is the real-world config, so it needs its own test distinct from the default-off serial-path tests above.

## Decisions

None — every design choice is fixed by the acceptance criteria and the existing code shape; no owner judgment call is needed.

## Task List

1. Add tests 1–10 above to `lib/tests/test_ticket_pipeline.py` (red first).
2. Add an `exclude: set[str] | None = None` parameter to `_select_for_profile` (`lib/ticket_pipeline.py:822`): skip any `device` in `exclude` at the top of the existing `for device in profile.get("machines", []):` loop. No other behavior change.
3. In the same function, record a refusal reason (into `refusals`, when given) for the three currently-silent `continue` paths: `select_machine(device)` returning `None`, the non-parallel `is_self` + `_local_busy()` skip, and the `pp.missing_here(profile)` skip — reusing the `"{device} lacks tools the project needs: ..."` phrasing already used by `dispatch_concurrency.can_start_another` for the tools case, for consistency with Health's `_classify_stall_reason` guard markers.
4. In `_dispatch_one` (`lib/ticket_pipeline.py:1041`), replace the single `_select_for_profile` call + `is_self` memory-guard check (lines 1058–1081) with a bounded retry loop: call `_select_for_profile(base_profile, settings, taken, local_base, refusals, exclude=tried)`; if the picked device `is_self`, run `memory_guard.guard` as today; on refusal, append its message to `refusals`, add the device to `tried`, and loop again (bounded by `len(base_profile["machines"]) + 1` iterations, with a defensive break if the same device id comes back despite being excluded); on success or a non-self pick, proceed exactly as today.
5. After the loop, if no device was settled on, report `"no-machine"` if nothing was ever memory/merge-held, or `"memory"` if any retry step was a memory/merge hold — keeping the existing `why = "; ".join(dict.fromkeys(refusals[mine:]))` reporting, which now naturally includes every machine's reason across all retry iterations.
6. Run the full test file (`~/.agents/venv/bin/python -m pytest lib/tests/test_ticket_pipeline.py lib/tests/test_health_checks.py lib/tests/test_dispatch_fallback.py lib/tests/test_memory_guard.py -v`) plus the full project suite before calling it done (main-green rule).
7. Update the ticket's "How we'll try to break it" checklist / PR description with which of the adversarial cases (both-held, laptop-unreachable, merge-ends-mid-retry) are covered by which new tests.