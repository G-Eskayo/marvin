Confirmed no ambiguity here, so the plan omits a Decisions section. Now I have everything needed to write the plan.

## North-star fit

**Reuses:** the surviving implementation is literally `print_table_proper()` (`skills/route/scripts/route.py:287-303`) — only it gets kept and renamed, no new logic is written. Its two call sites (`route.py:389`, `route.py:444`) already exist and just change the name they call. The new test file reuses `test_auto_route_hook.py`'s pattern (`skills/route/scripts/tests/test_auto_route_hook.py:10-11`, `sys.path.insert(0, str(SCRIPTS))` then `import auto_route_hook`) for locating and importing `route.py` from its tests directory.

**Simplest sufficient approach:** delete one dead function, rename the other, fix two call sites. No abstraction is introduced; this directly matches north star 4 ("one copy of each piece of logic") and removes exactly the maintenance-burden duplicate the ticket names — nothing more.

**Tokens:** trivially cheap to build (a few line edits, one small test file) and it's a net future saving: anyone touching the table format no longer has to notice/compare two near-identical functions, only one of which is live.

**Phone-OS direction:** neutral — internal CLI code hygiene, not user/OS-facing surface. Doesn't argue against it.

**User capability:** neutral by design — `--table` output is byte-for-byte unchanged (acceptance criterion 2), so this doesn't change what the user can do; it only removes a latent trap for the next person who edits this file.

## Tests to write first

All go in `skills/route/scripts/tests/test_route_table.py` (new file, same import pattern as `test_auto_route_hook.py`), except where noted:

1. **Golden-output regression** (ticket AC2): before touching `route.py`, capture `route.py --table`'s current stdout verbatim into a fixture (`skills/route/scripts/tests/fixtures/table_output.txt`). Test runs `route.py --table` as a subprocess and asserts stdout matches the fixture exactly, byte-for-byte, after the change.
2. **No-task-given fallback still works** (ticket "how we'll try to break it" #1): run `route.py` with no arguments (subprocess, empty argv) and assert exit code 0, the table header row is in stdout, and nothing resembling a traceback/`NameError` appears in stderr.
3. **Import path from another script still works** (ticket "how we'll try to break it" #2): reproduce `auto_route_hook.py`'s own pattern (`sys.path.insert(0, str(HERE))` then `import route`) in the test, and assert `route.print_table` exists and is callable, and `getattr(route, "print_table_proper", None) is None`.
4. **No dead twin remains** (ticket AC1, as an enforced regression rather than a one-off manual grep): assert the `route.py` source contains exactly one `def print_table` and zero occurrences of the substring `print_table_proper`. Run this test first against the *current* code to confirm it fails (proving it actually catches the bug being fixed), then make it pass with the real edit.
5. **Idempotency:** two consecutive `print_table()` calls produce identical stdout — guards against the rename accidentally picking up or mutating shared state (there is none today, but the table iterates the module-level `INTENTS` dict, so this is worth locking in).

Not adding tests for bad/empty/huge/malformed input, dependency failure, wrong permissions, or stale state: `print_table()` takes no arguments, touches no filesystem/network/external dependency, and holds no state across calls — there is no such surface on this function, and inventing one would be test theater (Watts check). Concurrency is likewise moot: stdout printing with no shared mutable state.

Verification (not new tests, but must pass clean): `skills/route/scripts/tests/test_auto_route_hook.py` and `lib/tests/test_route.py` run unmodified and green (ticket AC3), plus `rg -n print_table ~/.agents` finds no caller outside `route.py` (already confirmed during planning — only `route.py` itself references either name anywhere in the tree).

No Decisions section is needed — nothing here requires the owner to choose between options.

## Task List

1. Capture current `route.py --table` stdout verbatim as `skills/route/scripts/tests/fixtures/table_output.txt`, before any code edit.
2. Write `skills/route/scripts/tests/test_route_table.py` with the five tests above; confirm test 4 fails against current code (sanity check it detects the dead twin), run the rest to confirm they pass or fail as expected pre-fix.
3. In `skills/route/scripts/route.py`: delete the unused `print_table()` (current lines 268-284).
4. Rename `print_table_proper` to `print_table` (body unchanged).
5. Update the two call sites (`route.py:389`, `route.py:444`) from `print_table_proper()` to `print_table()`.
6. Re-run `rg -n print_table ~/.agents` (per the ticket) and confirm the only hits are the single `def print_table` and its two call sites.
7. Run `skills/route/scripts/tests/` (both test files) and `lib/tests/test_route.py`; confirm all green, including the new golden-output and fallback/import tests from step 2.
8. Confirm acceptance criteria literally: `rg -n "def print_table" skills/route/scripts/route.py` → one hit; `rg -n print_table_proper` repo-wide → zero hits.