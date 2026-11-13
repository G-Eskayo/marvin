No open decisions here — the ticket fully specifies the exact strings, call sites, and test cases. Now I have everything needed to write the plan.

## North-star fit

Reuses `notify()` from `~/.agents/lib/notify.py` (already imported at `research_digest.py:15`, already wired for the quarantine path at `research_digest.py:146-147`) — the exact same call shape (`notify(title, message, open_target=...)`) extends to the three failure sites, no new plumbing. Reuses `brief_fallback.produced()`'s existing placeholder-detection convention and the existing `"[colony] ..."` stderr logging style already used throughout all three scripts. This is the simplest sufficient fix: three localized edits across an existing module boundary (`source_monitor` → `research_digest` → `run_colony`), no new abstractions, no new files except the test file the ticket asks for. Token cost is negligible — a handful of `notify()` calls and one changed `return` expression; no change to the LLM call itself. It leaves the user more capable: today a silent "quiet day" requires Gil to manually open `research-colony-error.log` to notice a dead job; after this, `health_checks.py`'s existing `jobs:exit` check (confirmed at `~/.agents/lib/health_checks.py:1364-1371`, already reading launchd's last-exit status with no changes needed) surfaces it unprompted at the next session start, and a desktop notification fires immediately. No north star argues against this — it's pure "nothing may break silently" (north star 5).

Checked against the ticket's own stated fit: accurate, no correction needed. The one comment on the issue (2026-11-13) is just a transient "model service unavailable, released back to queue" notice, not design feedback — no prior-attempt failures to carry forward.

## Tests to write first (`skills/research-colony/scripts/tests/test_run_colony.py`, temp-HOME discipline: monkeypatch each module's `DIGEST_DIR`/`CACHE_DIR` to `tmp_path`, never touch real `~/.claude`)

From "How we'll try to break it" + acceptance criteria + the standard misuse checklist:

1. **All fetchers return `[]`** (`source_monitor.main`): monkeypatch `fetch_arxiv/fetch_github/fetch_hackernews` to `[]`; assert stderr gets the `ERROR: all sources returned 0 items` line and `save_raw_cache` (monkeypatched to raise `AssertionError` if called) is never invoked.
2. **All fetchers empty → full `run_colony.main()`**: chain through so `load_today_cache()` sees nothing; assert `generate()` returns `None`, a stubbed `notify` is called exactly once with reason `"no items fetched (all sources failed?)"`, and `run_colony.main()` returns `1`.
3. **Model call raises**: stub `marvin_launcher.launch` to raise; assert `generate()` returns `None`, stubbed `notify` called once with `"claude call failed: <first 120 chars of exc>"`, `run_colony.main()` returns `1`.
4. **Model call returns non-zero exit / empty text**: two sub-cases (`exit_code=1`, and `exit_code=0` with blank `text`); assert same notify-once + exit-1 behavior, reason built from `(stderr or text)[:120]`.
5. **Digest already exists** (`brief_fallback.produced` True via pre-written file): assert `generate()` returns the existing path without calling `notify` or `marvin_launcher.launch`, and `run_colony.main()` returns `0`.
6. **Quarantined digest**: stub `pass_or_quarantine` to return `False`; assert the digest still writes, `notify` is called exactly once (the existing quarantine notify, not a new one), and `run_colony.main()` returns `0`.
7. **One source fails, two succeed** (adversarial: partial failure must not look like total failure): `fetch_arxiv` returns `[]`, others return items; assert digest written, exit `0`, `notify` never called.
8. **`notify` itself raises**: monkeypatch the stubbed `notify` to raise inside `generate()`'s except-path call; assert `generate()` still returns `None` and `run_colony.main()` still returns `1` — i.e. `notify`'s own guaranteed non-raising contract (verified in `notify.py:82-91`) is not what we depend on; the calling code must not let a `notify` failure mask the real failure. *(Note: real `notify()` already never raises; this test guards against a future caller assuming `generate()`'s surrounding code depends on that rather than being independently safe.)*
9. **Fallback-gate-off path unchanged**: existing `test_gate_off_skips_the_whole_colony_run` continues to pass unmodified — `run_colony.main()` returns `0` with no steps called, no notify.
10. **Stale/garbage cache file** (misuse case not in the ticket's list but implied by "bad/malformed input"): `load_today_cache()` already returns `[]` on a corrupt JSON file (existing try/except) — add one assertion that this degrades to the same "no items fetched" notify-and-exit-1 path, not a crash.
11. **Repeated runs / idempotency**: calling `generate()` twice in a row after a successful write doesn't double-notify (covered by case 5's "already exists" path reused a second time).

Verify-fails-without-a-matching-code-change is satisfied by construction here: each new `notify()` call site and the `run_colony.main()` return-value change has exactly one test above pinned to it.

## Decisions
None — the ticket's "What to build" and "Acceptance criteria" fully specify exact reasons, call sites, and return-value semantics; nothing here is left to the owner's judgment.

## Task List

1. [ ] `skills/research-colony/scripts/source_monitor.py` — in `main()`, after computing `all_items`, branch: if empty, `print("[colony] ERROR: all sources returned 0 items", file=sys.stderr)` and skip the `save_raw_cache(all_items)` call; otherwise call `save_raw_cache` as today. Leave `store_items(all_items)` and the `return 0` unchanged.
2. [ ] `skills/research-colony/scripts/research_digest.py` — import stays the same (`notify` already imported at line 15). At the "no items" `return None` (~line 108-110), add `notify("MARVIN research-colony failed", "no items fetched (all sources failed?)", open_target=str(Path.home() / ".claude" / "logs" / "research-colony-error.log"))` before the `return None`.
3. [ ] Same file — at the `except Exception as exc` branch (~line 130-132), add `notify("MARVIN research-colony failed", f"claude call failed: {str(exc)[:120]}", open_target=str(Path.home() / ".claude" / "logs" / "research-colony-error.log"))` before `return None`.
4. [ ] Same file — at the `result.exit_code != 0 or not result.text.strip()` branch (~line 133-135), add `notify("MARVIN research-colony failed", f"claude call failed: {(result.stderr or result.text)[:120]}", open_target=str(Path.home() / ".claude" / "logs" / "research-colony-error.log"))` before `return None`.
5. [ ] `skills/research-colony/scripts/run_colony.py` — change the final `if out: ... else: ...` block's `else` print to `"[colony] no digest written — see errors above"` and change `return 0` to `return 0 if out else 1`.
6. [ ] `skills/research-colony/scripts/tests/test_run_colony.py` — add the 11 cases above as new test methods/classes alongside the existing `TestRunColonyGate` tests (leave the three existing tests untouched), monkeypatching `DIGEST_DIR`/`CACHE_DIR` per-module to `tmp_path` and `notify` to a capturing stub, never touching real `~/.claude`.
7. [ ] Run the full `scripts/tests/` suite for research-colony (`pytest skills/research-colony/scripts/tests/`) and confirm all pass, old and new.
8. [ ] `marvin-show` the diff (or the updated `research_digest.py`/`run_colony.py`/test file) to Gil before considering this done, per `docs/agents/showing-things.md`.