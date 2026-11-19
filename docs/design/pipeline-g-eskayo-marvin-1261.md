## North-star fit

**Reuses before adding anything new:**
- `lib/owner_decisions.py`'s existing `fetch`/`statuses`/`pr_status` (the exact same "owner-answered, not addressed, no work commit since" logic `merge_facts.js`'s `unbuiltFrom` already encodes) — I add one thin fresh-read wrapper around it rather than a second implementation of "is this PR unbuilt."
- `dashboard/webhook-server/decisions_gate.js`'s existing `assertDecisions` pattern (a `gh`-reading, fail-closed `MergeFailure`-throwing assertion called from `mergePrUnqueued`) — the new check is a sibling function in the same file, same shape.
- `merge_order.js`'s own wording, `"your answers aren't built yet"`, and its `HOLD_UNTIL` hold-vs-fail bucketing — reused verbatim so the dashboard shows one consistent reason regardless of which of the two code paths caught it.
- The single existing merge choke point: every real merge (including a stacked PR retargeted by `checkOpenPrs`) goes through `mergePrUnqueued`'s one `gh pr merge` call (confirmed: it's the only production call site). One new check there covers every case in "how we'll try to break it," including the stacked-PR one, with no second insertion point.
- The existing hourly `owner_decisions.py sync` / `_dedupe` mechanism for filing and deduplicating the follow-up ticket — untouched; I only stop it from wrongly closing one.

**Why this is the simplest sufficient fix:** two independent, narrow gaps, each closed at its own point, no new infrastructure:
1. A fresh, single-PR read (one `gh` call, only at the moment of merging) replaces trusting the dashboard's periodically-refreshed cache at the exact moment that matters.
2. A fresh, single-PR read (one `gh` call, only for a follow-up whose PR already left the open-PR page) replaces assuming "not open" means "done."

**Cost:** +1 `gh`/GraphQL call per actual merge (not per queue evaluation — those still use the cheap cache), and +1 `gh` call per *open follow-up whose PR has already closed* during an hourly scan (rare by construction). No new polling, no new files, no new cross-process state.

**Phone-OS direction:** neutral/positive — this is exactly the kind of "nothing breaks silently" correctness fix the OS-of-the-phone destination assumes already holds.

**More capable or more passive?** More capable: Gil's answer is now guaranteed to reach either the code (new commit) or a ticket (follow-up), even in the exact race he hit on #1248, without him having to notice and hand-carry it again.

I checked the ticket's own stated fit against the code: root cause #1 is real (`/approve` in `index.js` never calls `refreshFacts()` before queuing, and the queue's cached `unbuiltCache` is what the dashboard's own comment claims refreshes on Approve — it doesn't). Root cause #2 is real and is dead-simple to confirm: `by_pr` is built only from `fetch()`'s open-PR results, so a merged PR's row is always `None`, and the existing `elif (repo, pr) not in open_prs` branch closes the follow-up unconditionally. Both match the ticket's text exactly; I'm not fixing the stale `/approve` comment itself (out of scope — the merge-time fresh check makes it irrelevant regardless of when the cache last refreshed).

## Decisions

None needed. The ticket itself offers the one real implementation choice ("asks `owner_decisions.py request` ... **or** reads a fresh waiting row") as an explicit either/or, and the codebase's own established distinction (`unbuiltFrom`'s `!addressed_by && !built_since`, deliberately looser than `request()`'s "any unaddressed") settles which to use: reusing `request()` directly would hold merges that are already fine today (committed, just not yet replied to), a behavior regression nothing in the ticket asks for. Reading a fresh status row keeps today's semantics, just fresh instead of cached.

## Tests first

From "How we'll try to break it":
1. **The answer lands while the merge is running** → `freshlyUnbuilt`/`assertAnswersBuilt` unit tests (unbuilt row → refuse; addressed/built/no-decisions → pass) + a `mergePr`-level test proving the refusal fires before `shouldGateMerge`.
2. **An optional Decision answered after merge** → covered structurally: the Decisions-comment detection never distinguishes required/optional (it's comment-shaped, not field-shaped), so no special case needed; existing + new tests already exercise the comment-level path uniformly.
3. **A stacked PR merged by its base's after-steps** → covered by construction: `checkOpenPrs` never calls `gh pr merge`; the stacked PR still merges through the one real choke point (`mergePrUnqueued`). No new test needed beyond confirming (via code reading) there's no second `pr merge` call site — confirmed.
4. **GitHub unreadable at merge time: hold, never merge on a guess** → test: `freshlyUnbuilt` throws on exec failure → `assertAnswersBuilt` throws `DECISIONS_UNCHECKED` (fails closed, same as `assertDecisions` already does).

Additional misuse the section didn't spell out:
5. Merged PR's follow-up, never addressed → `sync()` keeps it open (not "no longer open").
6. Merged PR's follow-up, addressed only *after* merging → `sync()` closes it, naming how.
7. GitHub unreadable for the *targeted* closed-PR lookup specifically (while the main scan otherwise succeeds) → `sync()` leaves that one follow-up open, closes/files everything else normally.
8. Two Macs racing → unchanged existing `_dedupe`/`_list_label` mechanism still applies (no new code, so no new race to test).
9. A person's mistake / stale cache coincidence → every other existing `mergePr`-reaching test in the dashboard suite that uses a generic JSON stub lacking a `url` field must still pass unaffected (verified by code reading: `unbuiltFrom` requires a truthy `.url`, so any unrelated stub JSON safely resolves to "not unbuilt").

## Task List

1. `lib/owner_decisions.py`: add `status_for(repo, number, now=None, run=subprocess.run)` — fresh single-repo `fetch` + `statuses`, finds the one PR, raises `RuntimeError` when GitHub can't be read, returns `None` when the PR has no owner-Decisions comment. Add CLI subcommand `status --repo R --pr N` (prints the row as JSON or `null`; exits 1 with a stderr note when unreadable). Update the module docstring's command list and `main()`'s usage string.
2. `lib/owner_decisions.py`: add `_closed_pr_status(repo, number, run)` (one `gh pr view ... --json comments,body` call, reusing `pr_status`). Rewrite `sync()`'s follow-up-closing loop: when `(repo, pr) not in open_prs` (merged/closed, so `by_pr` has no row by construction), call `_closed_pr_status` instead of unconditionally closing — close only if it reports `addressed_by`, otherwise leave the follow-up open; leave it open too when the lookup itself fails.
3. `lib/tests/test_owner_decisions.py`: extend `FakeGitHub` with a surviving `all_prs` map and a `"pr view"` response branch; add tests for `status_for` (unaddressed, no-decisions `None`, raises when unreadable), the `status` CLI (JSON/`null`/exit 1, via monkeypatching `od.fetch`), and three `sync()` scenarios: merged+unaddressed stays open, merged+addressed-after closes with the new wording, merged+unreadable-lookup stays open.
4. `dashboard/webhook-server/merge_facts.js`: add `freshlyUnbuilt(repo, number, { exec, python = VENV_PYTHON, script = OWNER_DECISIONS })`, reusing the file's own `unbuiltFrom`.
5. `dashboard/webhook-server/decisions_gate.js`: add `assertAnswersBuilt(prUrl, exec)` — parses repo/number from the URL, calls `freshlyUnbuilt`; throws `MergeFailure(DECISIONS_UNCHECKED)` on a read error, `MergeFailure(DECISIONS_UNBUILT, "your answers aren't built yet")` when unbuilt, else resolves.
6. `dashboard/webhook-server/merge.js`: import `assertAnswersBuilt`; add `answersBuilt = assertAnswersBuilt` to `mergePrUnqueued`'s injectable `deps`; call `await answersBuilt(prUrl, exec)` immediately after `await decisions(prUrl, exec)`.
7. `dashboard/webhook-server/merge_order.js`: add `DECISIONS_UNBUILT: 'later'` to `HOLD_UNTIL`, alongside `DECISIONS_UNCHECKED`.
8. Update the mocks in `dashboard/test/merge.test.js`, `merge_memory_guard.test.js`, `merge_gate_progress.test.js`, `gate_flaky_rerun.test.js` (each mocks `decisions_gate.js` wholesale) to also export `assertAnswersBuilt: vi.fn(async () => {})`.
9. `dashboard/test/merge_queue.test.js`: import `freshlyUnbuilt`; add its unit tests (true/false/throws); add `DECISIONS_UNBUILT` to the existing `outcomeFor` hold-vs-fail assertion.
10. `dashboard/test/decisions.test.js`: import `assertAnswersBuilt`; add pass/refuse/fail-closed/non-PR-url unit tests and one `mergePr`-level test showing the refusal fires before `shouldGateMerge`.
11. Docs: `site/.../merge-gate.mdx` step 4 and `site/.../decisions.mdx` steps 5–6 — note the new `DECISIONS_UNBUILT` refusal and that a merged PR's unaddressed answer still gets its follow-up ticket (marvin#1261).