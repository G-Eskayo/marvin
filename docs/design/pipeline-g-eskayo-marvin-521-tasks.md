1. Capture current `route.py --table` stdout verbatim as `skills/route/scripts/tests/fixtures/table_output.txt`, before any code edit.
2. Write `skills/route/scripts/tests/test_route_table.py` with the five tests above; confirm test 4 fails against current code (sanity check it detects the dead twin), run the rest to confirm they pass or fail as expected pre-fix.
3. In `skills/route/scripts/route.py`: delete the unused `print_table()` (current lines 268-284).
4. Rename `print_table_proper` to `print_table` (body unchanged).
5. Update the two call sites (`route.py:389`, `route.py:444`) from `print_table_proper()` to `print_table()`.
6. Re-run `rg -n print_table ~/.agents` (per the ticket) and confirm the only hits are the single `def print_table` and its two call sites.
7. Run `skills/route/scripts/tests/` (both test files) and `lib/tests/test_route.py`; confirm all green, including the new golden-output and fallback/import tests from step 2.
8. Confirm acceptance criteria literally: `rg -n "def print_table" skills/route/scripts/route.py` → one hit; `rg -n print_table_proper` repo-wide → zero hits.