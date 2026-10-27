## North-star fit

Reuses, rather than invents: `lib/instance.py:_config()`'s try/except-and-default-to-`{}` discipline (for the `enrichment.json` fix), `lib/vm_run.py`'s `RunResult` dataclass + golden-image-clone→run→`finally:` delete shape (for the new `lib/tart_run.py`), `lib/code_sync.py`'s existing nested-instance pull/push handling and `bin/pre-push-guard` call (already wired — nothing to add there), `dashboard/scripts/rebuild_and_install.sh` (invoked as-is, not rewritten), `lib/addon_migrate.py.KNOWN_ADDONS` as the add-ons-off check list, and `setup.sh`'s own existing per-OS `case` style (`install_ollama`) and warn-and-skip idempotency convention (`install_skills`). The only genuinely new code is `lib/tart_run.py` (a different VM backend for a different purpose — a real macOS GUI boot, which only `tart`/Virtualization.framework on Apple Silicon can do; `vm_run.py`'s libvirt/QEMU path is Linux/x86-only and lives on a different, Intel box) and the `--new`/`--join` flag handling itself.

Simplest sufficient approach: three isolated one-function bug fixes (contained — grep confirms `_label`/`_mobility_class` and the `ENRICHMENT_PATH` read have no other callers to break), one new installer step reusing an existing script verbatim, one new flag-handling block that creates/clones a git repo and writes a 3-key JSON file (no new sync mechanism — `code_sync.py` already syncs `instance/` for free once it's a nested git repo), and one new VM-runner module shaped exactly like the one that already exists for the other box.

Tokens: spent on reading real call sites before touching shared, high-fan-in code (`machine_label()` has 26 callers) to confirm the fix is contained; saved by not re-deriving `code_sync.py`'s instance-sync path, which already exists and needs zero changes.

Phone-OS fit: this is the "anyone can install it" step — every future phone-OS-shaped feature is pointless if a stranger can't even reach a working install.

More capable, not more passive: this removes Gil (and MARVIN) from being in the loop for every new install — the test gate is what lets that trust be automated. It is the right kind of automation under north star 3: it replaces manual installer babysitting, not a skill the user was developing themselves.

**Blocking-dependency check against GitHub's own metadata:** #647 (add-ons off by default) is CLOSED and its `KNOWN_ADDONS` gate already means a fresh instance has no add-ons on by construction — reused directly below, no new code needed for that half of the acceptance criteria. #646 (84 hardcoded `G-Eskayo` refs → instance lookup) and #641 (first-run setup) are both still **OPEN**. `lib/instance.py` itself is already built and already derives `owner()`/`engine_repo()` from `git remote get-url origin`/`instance.json`, so `--new`/`--join` can be built against it today — but any of the 84 still-hardcoded files #646 hasn't reached yet (e.g. `config/dispatch.json`, `config/models.json`, `task_dispatch.py`, `ticket_pipeline.py`, `health_checks.py`, per the Noah-install memory) may still silently assume Gil's own machines inside a clean-install VM. This plan does not fix those — that is #646's scope — but the clean-install test (below) will incidentally catch any of them that break the specific five checks the acceptance criteria name. I flag this as a real, open risk rather than papering over it.

## Decisions

```markdown
## Decisions
<!-- marvin:decisions -->
### instance_repo_name: What does `setup.sh --new` name the private instance repo it creates?
- [ ] A: Fixed name `marvin-instance` under the authenticated `gh` account (simplest; a second machine for the same person always uses `--join`, never `--new` again, so a name collision is the expected "you already have one" case, not a bug)
- [ ] B: Hostname-qualified, e.g. `marvin-instance-<hostname>` (lets one person run independent instances, at the cost of `--join` needing to be told which one)

### tart_base_image: Where does the tart VM's base macOS image come from?
- [ ] A: `tart clone` a prebuilt community OCI image (e.g. `ghcr.io/cirruslabs/macos-sequoia-base:latest`) — fast, no local build step, trusts a third-party-maintained image
- [ ] B: Build our own golden image once via `tart create --from-ipsw` from Apple's own restore image, kept locally on the M4 Mini — matches `vm_run.py`'s existing "frozen golden image" philosophy (no third-party image trusted), slower one-time setup
```

Everything else below is a call I made myself rather than escalate, with the reasoning stated inline (repo-naming mechanics once A/B above is picked, `--join`'s auth model, the hook-wiring scope, the add-ons check mechanism, the new WezTerm-install step).

## Tests written first

**`lib/machine_profile.py` — new `lib/tests/test_machine_profile.py`** (mac path; mirrors `test_machine_profile_linux.py`'s shape):
1. `hw_model="Mac14,2"` (Noah's real bug: unified numbering, no `"MacBook"` substring) + battery present → `mobility_class == "mobile"`, `label != "mac-mini"` (the actual regression this ticket fixes).
2. `hw_model="MacBookPro18,1"` (old-style identifier) + battery present → `mobility_class == "mobile"`, `label == "macbook-pro"` (backward-compat guard — Gil's own laptop's label must not change).
3. A real Mac mini's `hw_model` + **no** battery → `mobility_class == "stationary"`, `label == "mac-mini"` (regression guard — Gil's own Mini must not change).
4. `pmset -g batt` fails/empty output (dependency failure) → falls back to `"stationary"` without raising.
5. `hw_model=""` (malformed/empty input) + battery present → still returns `"mobile"`/a non-crashing label, never `"mac-mini"`.

**`lib/marvin_session.py` — add to `lib/tests/test_marvin_session.py`**:
6. `gui_identity()` returns `None` → `run` (the spawn-capable callable) is never invoked at all; `start()` is called with `wezterm start --cwd ... -- ...` directly (the actual Noah bug: today it still calls `wezterm cli spawn --new-window`, which auto-starts a windowless mux and "succeeds").
7. Existing gui-present, window-exists / window-closed-since-last-look / race-under-lock tests (already in the file) keep passing unchanged — regression guard that the fix doesn't touch the gui-present path.

**`brain-map/generate.py` — add to `brain-map/scripts/test_generate.py`**:
8. `ENRICHMENT_PATH` missing entirely → `main()`'s enrichment load returns a dict with safe defaults for every key the pipeline unconditionally indexes (`root`, `structural`, `category_order`, `category_labels`, `skill_categories`, `skill_desc_overrides`, `skills_trunk_desc`) and the whole generator runs to completion producing an (almost-empty) tree, not a `KeyError`/`FileNotFoundError`.
9. `enrichment.json` present but corrupt (truncated/invalid JSON) → same safe-default behavior, not a crash.
10. `enrichment.json` present but wrong-shaped (a JSON list, not an object) → same safe-default behavior.
11. `enrichment.json` present and valid but missing one optional key only (e.g. no `"plain"`) → unaffected (already-passing `.get()` path), confirming the fix doesn't regress the common case.

**`setup.sh` — new `lib/tests/test_setup_install_steps.py`** (same `source setup.sh; MARVIN_DIR=...; <call function>` harness as `test_push_guard.py`):
12. `install_commands()`: every `skills/*/SKILL.md` directory gets a `~/.claude/commands/<name>.md`; an already-present one is left untouched (warn-skip, matching `install_skills()`'s own convention) — this is the literal "0 skills wired" bug.
13. `configure_hook()`/the template: after extending `settings.template.json`, a fresh `settings.local.json` install contains `SessionStart` → `session_start_report.py` and `UserPromptSubmit` → `auto_route_hook.py`; an existing `settings.local.json` is still left untouched with a warning (regression guard on the existing skip-if-present behavior).
14. `ensure_node()`: Node already present → no-op; missing on macOS → `brew install node` is invoked; on Linux/WSL2 the whole `install_dashboard()` step is skipped (dashboard is mac-only).
15. New `install_wezterm()` (finding, not in the original ticket text — see Task List #10): WezTerm missing → installed via `brew install --cask wezterm` on macOS; already present → no-op; skipped on Linux/WSL2. Without this, "the MARVIN button works" in the acceptance criteria is untestable from a fresh VM, since nothing today installs WezTerm.
16. `install_dashboard()`: calls `dashboard/scripts/rebuild_and_install.sh` and surfaces (doesn't swallow) a non-zero exit from it — dependency-failure case (e.g. `npm install` fails offline).

**`setup.sh --new`/`--join` — add to the same test file**:
17. `--new` on a clean `$HOME` (no `gh` auth) → fails loud with a clear message; does **not** create a half-initialized `~/.agents/instance`.
18. `--new` with `gh` authenticated, run against a clone whose `origin` is the public upstream (`G-Eskayo/marvin`) directly, not a fork (a plausible real mistake) → `instance.json`'s `"owner"` is the authenticated `gh` user, **not** `"G-Eskayo"` — the `engine_repo()`-fallback trap identified while reading `lib/instance.py`.
19. `--new` succeeds → `~/.agents/instance` is a git repo with a remote pointing at the new private repo, one commit, `instance.json` has no `"features"` turned on for any of `addon_migrate.KNOWN_ADDONS` (reused list, not duplicated), and `retrospective-log.md` is present (already built by `deploy_retrospective_log()`).
20. `--new` run twice in a row (repeat) → refuses / no-ops on the second run rather than creating a second GitHub repo or clobbering the first instance's content.
21. `--join <url>` with a malformed or unreachable repo URL (person's mistake / dependency failure) → fails loud, leaves no partial `~/.agents/instance` behind.
22. `--join <url>` succeeds → clones the given repo into `~/.agents/instance`, and a subsequent plain `code_sync.py pull ~/.agents` picks it up with no further configuration (proves the "existing sync path" claim rather than assuming it).
23. `--join` run twice (repeat) → second run is a no-op/pull, not a re-clone-over-existing-work error.

**`lib/tart_run.py` — new `lib/tests/test_tart_run.py`** (same `host=` injection pattern `vm_run.py`'s own tests use):
24. Happy path: `tart clone` → `tart run` (backgrounded, not blocking) → IP found → SSH ready → command runs → `finally:` always calls `tart stop`/`tart delete`, even on success.
25. Boot timeout (no IP within budget) → `RunResult(ok=False, ...)`, VM still deleted in `finally:`.
26. SSH never comes up → same: fails cleanly, VM still deleted.
27. The remote command itself exits non-zero → `RunResult(ok=False, exit_code=...)` surfaced, VM still deleted — never silently "ok".
28. A crash between `tart clone` and `tart run` (simulated exception) → VM is still deleted (`finally:` covers every step, matching `vm_run.py`'s own test for this).
29. Secrets handling: if `--secret-env` is offered (reused from `vm_run.py`'s own convention) — bad secret name / value with embedded newline is refused before anything is spawned.

**Clean-install driver — new `lib/tests/test_clean_install_check.py`** (unit-tests the *driver's* own logic with `tart_run.run` monkeypatched to a canned `RunResult`; the real multi-minute VM boot is exercised manually/in CI, not in the fast suite):
30. `check_new()` builds the correct remote command: clone the engine, run `setup.sh --new`, then assert (a) the dashboard process is running (`pgrep`-style, reusing `rebuild_and_install.sh`'s own check), (b) `instance.json` exists and every `addon_migrate.KNOWN_ADDONS` entry reads `feature_enabled() == False`, (c) a push containing a seeded private-pattern string is refused (non-zero exit) by the guard.
31. `check_new()` with a tool failure partway (e.g. `setup.sh` itself exits non-zero inside the VM) → driver reports failure, not a false "ok", and the VM is still deleted (delegated to `tart_run.run`'s own `finally:`, tested at #28).
32. `check_join(instance_repo_url)` on a second VM: same three checks, plus confirms the instance pulled matches the first VM's (same `instance.json` content/same git history tip), not a fresh empty one.
33. Run-twice cleanliness (acceptance criterion's literal wording): calling `check_new()` twice in a row leaves zero `tart` VMs behind between runs (no leaked VM from a prior run interfering with the second).
34. Malformed/missing `--join` argument at the CLI level → the driver's `main()` refuses with a usage error rather than booting a VM for nothing.

## Task List

1. **`lib/machine_profile.py`**: add `_has_battery()` (runs `pmset -g batt`, checks for `"InternalBattery"`); change `_mobility_class()` to take that boolean instead of `hw_model`; change `_label()` to use mobility + a model-name substring (`MacBookPro`/`MacBookAir`/plain `MacBook` → precise label, else generic `"macbook"` when mobile; unchanged `"mac-mini"` default when stationary). Update `build_profile()`'s call sites. Tests 1–5 first.
2. **`lib/marvin_session.py`**: restructure `open_in_wezterm()` so a `None` `gui_identity()` skips both `_spawn()` attempts entirely and falls straight to the `start()` (`wezterm start`) branch, inside the same `fcntl` lock. Tests 6–7 first.
3. **`brain-map/generate.py`**: add a `_load_enrichment()` helper (try/except around `json.loads`, `{}` on any failure or non-dict, then `setdefault` safe defaults for the 7 unconditionally-indexed top-level keys), and call it from `main()` instead of the raw `json.loads(ENRICHMENT_PATH.read_text())`. Tests 8–11 first.
4. **`setup.sh` — command wrappers**: add `install_commands()` (one `~/.claude/commands/<name>.md` per `$SKILLS_DIR/*/SKILL.md`, diagnose.md's exact one-liner template, warn-skip if present), called from `main()` after `install_skills()`. Test 12 first.
5. **`setup.sh`/`claude-config/settings.template.json` — missing hooks**: add `SessionStart` → `lib/session_start_report.py` and `UserPromptSubmit` → `skills/route/scripts/auto_route_hook.py` entries to the template (plain, un-gated commands — matching the template's existing style, not the richer `marvin_hooks.py gate` wrapping the production `~/.claude/settings.json` has, which is out of this ticket's scope). Test 13 first.
6. **`setup.sh` — Node + dashboard install**: add `ensure_node()` (per-OS `brew install node` / skip on Linux-WSL2, styled like `install_ollama()`) and `install_dashboard()` (calls `dashboard/scripts/rebuild_and_install.sh`, skipped on Linux/WSL2, surfaces its exit code), called from `main()`. Tests 14 and 16 first.
7. **`setup.sh` — install WezTerm** (finding: nothing installs it today, and "the MARVIN button works" depends on it): `install_wezterm()`, `brew install --cask wezterm` on macOS, skipped on Linux/WSL2, called from `main()`. Test 15 first.
8. **`setup.sh` — `--new`/`--join` flags**: argument parsing in `main()`; `--new` checks `gh auth status`, refuses if `~/.agents/instance` already exists, creates the private repo per the chosen Decision option, writes `instance.json` via `$VENV_PYTHON -c "import json..."` with the real authenticated `gh` login as `"owner"` (never derived from `engine_repo()`), `git init`s + pushes `~/.agents/instance`; `--join <url>` instead does a plain `git clone <url> ~/.agents/instance` (bootstrap only — ongoing sync is `code_sync.py`'s existing, unmodified nested-instance pull/push). Both then run the full existing install sequence (steps 1–7 above included). Tests 17–23 first.
9. **`lib/tart_run.py`** (new module, `vm_run.py`-shaped `RunResult` + clone→run→`finally: delete`): `tart clone`/`tart run` (backgrounded)/`tart ip` polling/SSH-ready polling/command execution/`tart stop`+`tart delete` cleanup, targeting the M4 Mini. Base image source per the `tart_base_image` Decision. Tests 24–29 first.
10. **Clean-install test driver** (new `lib/clean_install_check.py`): `check_new()` and `check_join(url)`, each booting a VM via `lib/tart_run.py`, running `setup.sh --new`/`--join` inside it, then asserting the five acceptance-criteria checks (dashboard process up, MARVIN-button/WezTerm session opens, instance exists and is empty, push guard refuses a seeded private pattern, all `addon_migrate.KNOWN_ADDONS` off) — followed by VM deletion. CLI `main()` wires `--new`/`--join`. Tests 30–34 first; resolve both Decisions above before implementing the repo-naming and base-image pieces.
11. **`CONTEXT.md`**: new subsection under "## Engine, instance, the default build and add-ons" documenting the `tart`-on-the-M4-Mini clean-install mechanism (distinct box, distinct purpose, distinct VM tech from the existing mac-mini-2012 "Disposable VM" section — not folded into that bullet, which is specifically about isolating untrusted/bench code on a different machine) and the `--new`/`--join` flow, once the two Decisions are answered.
12. **Full-suite regression pass**: `~/.agents/venv/bin/python -m pytest lib/tests brain-map/scripts brain-map/tests -x` after each of steps 1–3 (the three named bug fixes) given their broad fan-in (`machine_label()` alone has 26 call sites), before moving on to the installer/VM work.