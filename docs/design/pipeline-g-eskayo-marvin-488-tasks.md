1. In `lib/portfolio_longform.py`: add `from datetime import datetime, timezone` to the imports.
2. Add a small helper (near `rollback()`) that builds a collision-safe `before-rollback-<UTC %Y%m%dT%H%M%SZ>[-N].json` path under a given backup folder, reusing the `n = 2; while path.exists(): ...; n += 1` idiom from `lib/marvin_show.py`.
3. Rewrite `rollback(slug, outbox=OUTBOX, runner=pm._run)`:
   - Read `<outbox>/<slug>/before-longform.json`; on `FileNotFoundError` or `json.JSONDecodeError` return `{"ok": False, "stage": "no-backup", "url": slug}`.
   - Call `pm._wp(runner, "post", "get", str(saved["page_id"]), "--field=post_content")`; on non-zero `returncode` raise `pm.MigrationError(...)` (fail closed, no write, no update).
   - Write `{"page_id": saved["page_id"], "url": saved["url"], "content": r.stdout}` to the new collision-safe `before-rollback-*.json` path.
   - Run the existing restore `pm._wp(runner, "post", "update", str(saved["page_id"]), "-", input=saved["content"])`; on non-zero `returncode` raise `pm.MigrationError(...)` as today.
   - Return `{"ok": True, "restored": saved["url"], "saved_current": str(current_path)}`.
4. Update the existing round-trip test (`test_converting_saves_the_short_page_first_and_rollback_restores_it`) to assert the new `saved_current` key and that a `before-rollback-*.json` is written with the live content.
5. Add the five new tests listed above (missing backup, corrupt JSON, failing `post get`, empty live content, same-second collision).
6. In `skills/portfolio-page/SKILL.md` step 5's first bullet: delete the "Save your own backup of the current page content before rolling back: `ID=$(...)` ... with `W` set to the `wp_base()` command." sentence and replace it with: "`--rollback` saves the page it replaces to `~/.claude/outbox/migrations/<slug>/before-rollback-*.json` first." Leave the third bullet's `${=VAR}` note untouched.
7. Run `lib/tests/test_portfolio_longform.py` (and the full `portfolio_migrate`/`portfolio_longform` suite) to confirm everything passes, then re-read `SKILL.md` to confirm the one-liner is gone.