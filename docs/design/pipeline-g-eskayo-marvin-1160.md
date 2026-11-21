## North-star fit

**Reuses, before adding anything new:**
- `lib/decisions_check.py` / `lib/pr_ticket_check.py`'s `gate(argv, say, log)` plug-in pattern already wired into `bin/gh`'s `main()` (import-with-`ImportError`-fallback, same `_say`/`_log` callbacks) — the new healing hook slots in the same way, so "catalog module missing or broken: `bin/gh` still works" is the same guarantee those two already give.
- `pr_ticket_check.py`'s own argv-walking idiom (`flag.partition("=")`, tracking a `target`, a URL regex for owner/repo) — I write one for `issue|pr create|edit`'s label flags instead of re-deriving a parsing style.
- `project_onboard.TRIAGE_LABELS` / `TRIAGE_LABEL_COLORS` for the 5 core labels, and `support.PREFIX` / `support.STATES` / `support.LABEL_COLORS` for the 11 `support:*` labels — the catalog imports these instead of re-stating colors that already live in one place (avoids the drift the ticket is about).
- `machine_profile._load_registry()` (already imported this way by `cold_store.py`, `health_checks.py`, `job_units.py`, `peer_care.py`) for the `claimed:<machine>` family, and `~/.claude/boards/registry.json`'s board `name` field (already the full, authoritative project-id list — it includes `marvin` itself, unlike `config/project_tags.json` which deliberately excludes a repo's own project) for the `project:<id>` family. No new ID list is invented.
- `purpose_metrics.py`'s `_github_calls()` pattern (`github_usage.read_jsonl` + epoch `"t"` field + `_cut(now, days).timestamp()`) is reused verbatim for the new `label-problems` probe, reading the gate's own `gh-calls.jsonl`.
- `lib/tests/test_gh_gate.py`'s `_fake_gh`/`_run`/`_run_gate` fixtures (a `#!/bin/sh` stand-in `gh`) are reused for the end-to-end healing tests, matching how the gate's existing rules (decisions, pr-ticket, ui-evidence) are already tested.

**Why this is the simplest sufficient shape:** one new data+logic module (`lib/label_catalog.py`) plus a small, isolable change to `bin/gh`'s existing tail (factoring the current "run real gh" block so the label-aware path only engages when the call actually carries `--add-label`/`--remove-label`/`--label`/`-l`; every other call — including every `issue|pr create|edit` with no labels — is untouched, byte-for-byte). No new onboarding, sync, or deny.js work: those are explicitly the follow-up tickets.

**Where it spends/saves tokens:** spends once to write ~35 lines of label metadata (mostly copied from code that already states it) and a retry loop; saves repeatedly by deleting the *need* for the 5-6 duplicated, inconsistent "create on first use" blocks already scattered in `ticket_claim.py`, `ticket_agents.py`, `main_red.py`, `owner_decisions.py`, `box_build.py`, `support.py` (not removing them this slice — out of scope — but no caller needs to add a 6th copy going forward).

**Phone-OS direction:** neutral — this is reliability plumbing (north star 2's precondition: "nothing may break silently"), not a new capability.

**More capable or more passive:** more capable — a send-back or claim no longer silently loses its real reason (`REBASE_CONFLICT` hidden behind `'needs-reengagement' not found`) to a label gap the owner never asked to track by hand.

## Decisions

None needed. Every open question in the ticket resolves to something already in the code or data: the "core subset" is `project_onboard.TRIAGE_LABELS` (already documented as the one "every project gets" set); the full fixed-label list is the deterministic grep inventory below, not a judgment call; label colors/descriptions are cosmetic ("whoever creates it first, sets them," per `docs/agents/triage-labels.md`) and don't need owner sign-off; and the two family memberships come from existing registries (`~/.claude/boards/registry.json`, `~/.claude/marvin-network.json`), not an invented list.

## Tests to write first

Two new/extended files: `lib/tests/test_label_catalog.py` (pure logic, no subprocess) and additions to `lib/tests/test_gh_gate.py` (end-to-end, fake `gh`, mirroring its existing `_fake_gh`/`_run_gate` style) and `lib/tests/test_purpose_metrics.py` (the new probe).

From the ticket's "How we'll try to break it":
1. Several missing labels in one call (`--add-label foo --add-label bar --add-label typo`): foo and bar each heal in turn, typo refuses; bounded total attempts (a pathological always-missing case gives up rather than looping forever).
2. `--add-label a,b`, `--label=a`, `-l a`, and repeated `--add-label` flags all parse to the same label set.
3. Add and remove in one call, with the removed one missing: the remove half drops silently, the add half still applies.
4. A typo (`ready-for-agnet`, `project:marvn`) is never created; original stderr/rc preserved, hint names `lib/label_catalog.py`.
5. `'x' not found` where x is an assignee/milestone/repo value, not a label passed in this call: call is untouched even when x happens to equal a catalogued label name (membership checked against *this call's own* parsed label values, never against the catalog alone).
6. Repo resolution: `--repo`, `-R`, an issue/PR URL target, `GH_REPO`, and cwd (via `gh repo view`) each select the right repo for the `label create`; a URL target never falls back to creating in the cwd's repo.
7. Two writers racing: `gh label create` failing with "already exists" counts as healed, not a refusal.
8. An existing label in another case (`Bug`) or with a person's own color is never touched (no `--force`, ever).
9. `gh label create` fails for a real reason (no permission, archived repo, rate limit): the *original* `issue|pr create|edit` error is restored and shown (not the label-create failure); no retry loop.
10. `--body-file -`: stdin is read into memory once and the same bytes are resent on every retry attempt.
11. Read-only commands (`issue list --label x`, `pr view`) and `gh api` are never touched by this code path at all.
12. `lib/label_catalog.py` missing, or raising on import or at call time (corrupt `marvin-network.json` / `boards/registry.json`): `bin/gh` still runs the call plain, unhealed, un-crashed.
13. Success path: `bin/gh issue edit N --add-label <catalogued-missing>` ends with stdout/exit code identical to the label already existing, and nothing extra printed to stderr (no "not found" noise survives a successful heal).
14. Each heal and each refusal is logged into `gh-calls.jsonl` on the final row, and `purpose_metrics.PROBES["label-problems"]` counts refusals (uncatalogued, create-failed, retry-bound-exceeded) over the 7-day window — successful heals are visible in the log but don't count as "problems."

Misuse the section didn't spell out, added:
15. Malformed/empty input: `--add-label ""`, `--add-label` with no following value, or a label value containing shell-special or absurdly long (4000+ char) text — never crashes the parser; an empty/garbage name that isn't catalogued just refuses normally.
16. `--help`/`-h` anywhere in the call: healing is skipped entirely (mirrors `decisions_check.py`'s own `"--help" in argv` guard) since there's no real call to heal.
17. The same label name present in *both* `--add-label` and `--remove-label` in one call: resolved without an infinite loop (via the error text's own "add"/"remove" wording, falling back to a fixed choice), never both created and dropped in a cycle.
18. A person at an interactive terminal running `gh issue edit N --add-label <missing>` directly: still heals (stderr capture is intentionally turned on for *any* `issue|pr create|edit` call that carries a label flag, tty or not); a label-less call at a terminal keeps full passthrough (colors/prompts), unchanged from today.
19. `real` gh not found at all (`find_real_gh` returns `None`): `label_catalog`'s entry point is never reached (existing `127` path in `main()` fires first) — test that `eligible()`/`run_with_healing` aren't invoked in that branch, not that they're defensive against a null `real`.

Also: before writing the "not found" regex itself, the first implementation step is to empirically capture the *real* installed `gh`'s exact stderr text and exit code for `--add-label <missing>` and `--remove-label <missing>` against a disposable test fixture (a throwaway label name on a scratch issue), per the north star's "test against the real collaborator's rules, not a mock of them" — the parser is written to match what `gh` actually says, not what the ticket paraphrases.

## Task List

1. Empirically capture real `gh`'s stderr/exit-code shape for a missing `--add-label` and a missing `--remove-label` (disposable fixture, read of real behavior only) and record it in `lib/label_catalog.py`'s docstring as the basis for the parser regex.
2. Write `lib/tests/test_label_catalog.py` covering (pure, no subprocess): catalog membership (`FIXED`, `CORE`, `project:<id>`, `claimed:<machine>` families, backed by fakes for the board registry / network registry), the label-call argv parser (items 2, 15, 16 above), the "drop one value from a repeated/comma-joined flag" reconstruction, and repo resolution (item 6).
3. Implement `lib/label_catalog.py`'s data: `FIXED` (every literal from the grep inventory: triage 5, `priority:p0..p3`, `bug`/`enhancement`, `needs-reengagement`, `hold`, `pinned`, `watch`, `foundation`, `breaking-change`, `linux-ok`, `regression`, `missed-purpose`, the 11 `support:*`, `from-box`, `main-red`, `site-deploy-failed`, `owner-decisions`), each with color+description (reusing `project_onboard`'s and `support.py`'s existing color dicts where they already exist); `CORE = project_onboard.TRIAGE_LABELS`; `known_projects()` from `~/.claude/boards/registry.json`; `known_machines()` from `machine_profile._load_registry()` plus the two fixed Mac classes; `is_catalogued(name, projects, machines)`.
4. Implement the pure argv layer: `label_call(argv)` → repo/target/add-labels/remove-labels (or `None` for an ineligible call), `drop_label_value(argv, flag, value)`, `resolve_repo(call, env, ask_cwd)` (explicit flag → URL target → `GH_REPO` → `ask_cwd()`).
5. Implement `run_with_healing(real, argv, env, ask=subprocess.run, say=...)`: bounded retry loop (steps b–d of the design above) that only engages when `label_call(argv)` found at least one label flag; always captures stderr (tty or not, for this call shape only); replays captured stdin once for `--body-file -`; returns `(rc, final_stderr_to_write, heal_log | None)`.
6. Refactor `bin/gh`'s existing tail: extract the current tty-vs-piped "run real gh" block unchanged into a small helper, then branch — `label_catalog.run_with_healing(...)` when importable and `label_call(argv)` is non-`None`, else the untouched old path (same `ImportError` fallback idiom as `decisions_check`/`pr_ticket_check`). Attach `heal_log` to the existing `_log(...)` row when present.
7. Write the end-to-end tests in `lib/tests/test_gh_gate.py` (items 1, 3–5, 7–14, 17–19) using the existing `_fake_gh`/`_run_gate` style, with the fake `gh` script shaped to the real error text captured in step 1.
8. Add `_label_problems(days=PROBE_WINDOW_DAYS, path=None, now=None)` to `lib/purpose_metrics.py` (reusing `_github_calls`'s read/cut pattern, counting only refusal outcomes) and register it in `PROBES["label-problems"]` with threshold `0.0`; add its test to `lib/tests/test_purpose_metrics.py` (item 14).
9. Run the full Python suite (not just the new files) per the "full suites before a hand-merge" rule, and open the PR naming "Closes #1160", with a Decisions-free body (none needed, per above) and a note that onboarding's core-set rollout, `check|sync`, `deny.js` containment, and the catalog-completeness scanner are deliberately left to follow-up tickets per the ticket's own "Left for follow-up" list.