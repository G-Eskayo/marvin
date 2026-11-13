I now have everything needed. Here's the plan.

## North-star fit

**Reuses:** three existing patterns, no new files or dependencies.
- `lib/portfolio_migrate.py`'s `rollback()`/`migrate()` (lines 326–365): the `pm._wp(...)` call shape, the `MigrationError` fail-closed-on-wp-cli-failure pattern, and the `{page_id, url, content}` backup JSON shape — the exact same shape this fix writes for the new `before-rollback-*.json`.
- `portfolio_longform.py`'s own `convert()`/`author()` (lines 148–156, 188–196): the "write backup JSON, then run `post update`, raise `pm.MigrationError` on non-zero return" sequence this fix mirrors inside `rollback()` itself.
- `lib/marvin_show.py`'s collision-safe filename loop (lines 206–210, `n = 2; while dest.exists(): ...; n += 1`): reused for disambiguating `before-rollback-<ts>.json` when two rollbacks land in the same UTC second — the exact case the ticket's "how we'll try to break it" flags.

**Simplest sufficient approach:** one function (`rollback()`) grows by ~15 lines, one one-line helper is added for the collision-safe filename, and one sentence in `SKILL.md` is replaced. No new module, no new test infra (plain `monkeypatch` on `datetime`, already the project's standard mocking tool — no `freezegun` dependency added).

**Tokens/compute:** negligible — one extra `wp post get` round trip per `--rollback` call, the same cost `convert`/`author` already pay for their own backup step. Pure reliability gain for near-zero added cost (north star 1).

**Phone-OS direction (north star 2):** marginal but positive — it finishes moving this tool's state fully into the canonical `~/.claude/outbox/migrations/<slug>/` location, replacing the only remaining ad hoc, repo-relative (`backup/`) path in this workflow.

**More capable or more passive:** more capable (north star 3) — removes the single manual zsh one-liner that was the *only* thing protecting an authored page before a rollback. The human's judgment work (authoring copy) is untouched; only fragile bookkeeping that depended on a model remembering a prose step is removed.

No recorded decision is contradicted — `~/.claude/outbox/migrations/` is confirmed by CONTEXT.md and the existing pilot (2026-10-05) as the right location; ADR 0066's "outbox" terminology refers to a separate JSONL event-log system and doesn't apply here.

**Out of scope, by design:** the issue's "Recurrence check" probe ("add one counting `--rollback` runs with no `before-rollback-*.json` written") is outside the ticket's "What to build" and "Acceptance criteria" sections, which are the authoritative scope per this task's instructions. I'm not building it — it would need its own design (where the probe lives, which health check surfaces it) and isn't a concrete, bounded unit here.

**Decisions:** none. The spec is fully concrete; the one judgment call I made (treating corrupt `before-longform.json` JSON the same as a missing one, both as `stage: "no-backup"`) is reasonable and non-blocking, not an owner choice — no separate stage name is defined in the ticket for that case, and "no usable backup" covers both.

## Tests to write first (`lib/tests/test_portfolio_longform.py`)

1. **Missing backup → clean failure, no update** (acceptance criterion): `rollback()` on a slug with no `before-longform.json` returns `{"ok": False, "stage": "no-backup", "url": slug}`, and no `"post update"` call appears in the fake runner's call log.
2. **Corrupt backup JSON → same clean failure** (break-it #3): write garbage text to `before-longform.json`, call `rollback()`, assert the same `{"ok": False, "stage": "no-backup", ...}` shape and no `"post update"` call.
3. **Failing `post get` → fail closed, no update** (acceptance criterion + break-it): a fake runner whose `"post get"` call returns `returncode=1` raises `pm.MigrationError`, and the call log contains no `"post update"`.
4. **Rollback saves the live page before restoring, then restores** (acceptance criterion, replaces/extends the existing round-trip assertion at test_portfolio_longform.py:90-98): after `convert()` writes `before-longform.json`, call `rollback()` with a runner whose `"post get"` returns a known "live" string; assert a `before-rollback-<UTC-ts>.json` file exists under `tmp_path / "p"` holding `{"page_id", "url", "content"}` with that live string, that the `"post update"` call's input is the *original* `before-longform.json` content (the restore), and that the result includes `"saved_current"` pointing at the new file's path.
5. **Empty live content is saved as a real state, not a failure** (break-it #2): fake runner's `"post get"` returns `returncode=0, stdout=""`; assert `rollback()` still returns `ok: True`, still writes a `before-rollback-*.json` (with `"content": ""`), and still performs the restore `"post update"` call.
6. **Two rollbacks in the same second don't collide** (break-it #1): monkeypatch `lf.datetime` to a fixed `now()`, call `rollback()` twice against the same `tmp_path`/slug (with a backup present both times); assert two distinct `before-rollback-*.json` files exist (the second gets a `-2` suffix, per the `marvin_show.py` collision pattern) and both calls still succeed.

`SKILL.md`'s "no longer contains the `${=W} post get` one-liner" criterion is a doc edit verified by direct inspection after the edit (no existing precedent in this repo for pytest-asserting on skill markdown prose, and inventing one for a single doc line isn't warranted).

## Task List

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