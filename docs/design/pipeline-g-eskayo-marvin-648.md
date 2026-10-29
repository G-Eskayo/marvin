## North-star fit

**Reuses before adding anything new:**
- `bin/build-instance` (already does local instance-repo creation: `.gitignore`, blank `instance.json` with `{"features": {}}`, `git init` + commit) — `--new` calls it instead of re-implementing instance bootstrap.
- `lib/code_sync.py:main()` (already syncs `<repo>/instance` nested repo automatically whenever `instance/.git` exists — no new sync code needed for `--join`, just `git clone` into place).
- `lib/marvin_hooks.py:install()` (already writes the *complete* hook set — SessionStart, UserPromptSubmit, PostToolUse, PreToolUse — gated by launch kind, plus `commit_check.install_hook`) — replaces the stale `setup.sh:configure_hook()`/`claude-config/settings.template.json` path, which only ever wired a subset into `settings.local.json` (a location `marvin_hooks.py`'s own docstring says Claude Code ignores outside the home folder).
- `dashboard/scripts/rebuild_and_install.sh` (already builds, signs, installs, launches and verifies MARVIN.app) — setup.sh calls it rather than duplicating build logic.
- `lib/instance.py:_config()`'s try/except-and-default discipline — the model for `brain-map/generate.py`'s new `_load_enrichment()`.
- `lib/vm_run.py`'s `RunResult` + clone→run→`finally: delete` shape — the model for the new `lib/tart_run.py`, swapping `virsh`/`qemu-img` for `tart`.
- `lib/tests/test_push_guard.py`'s `source setup.sh; MARVIN_DIR=...; <function>` harness — reused for every new setup.sh test (no bats dependency needed; none exists in this repo).
- `lib/addon_migrate.KNOWN_ADDONS` + `lib/instance.feature_enabled()` — reused by the clean-install checks for "add-ons off," no new addon-listing logic.

**Simplest sufficient approach:** keep `machine_profile.py`'s existing label *values* (`"mac-mini"`/`"macbook-pro"`) unchanged — only the *detection* of mobility moves from a brittle `"MacBook" in hw_model` substring check to battery presence. The previous attempt's richer label set (`"macbook"`, `"macbook-air"`) is unnecessary for this ticket's acceptance criteria and was the exact thing code review caught as a regression (26 untouched callers, two models colliding). Not re-introducing it is the Colton check applied directly to a real, logged failure.

**Token cost:** spends tokens on three small, well-isolated bug fixes with full regression test runs after each (cheap, fast, deterministic); spends more on the VM harness/driver (unavoidable — the acceptance criteria require a real boot). Saves tokens by not hand-duplicating `marvin_hooks.py`'s hook table or `build-instance`'s repo-bootstrap logic.

**Phone-OS / capability:** this is the "anyone can download MARVIN and it works" milestone (M2) — directly serves north star 2 (OS-shaped: reachable, general, works without Gil). It leaves a new user more capable (a working partner from one command) rather than more passive.

---

## Why the ticket's own "ADR 0071 step 6" framing needs a correction

The push guard is **already installed on every clone today** — `install_push_guard()` is already unconditionally called from `setup.sh:main()` (commit `dcfe1b25`). The ticket's "What" section implies this still needs building; it doesn't. What's actually missing, verified against the current tree, is narrower:

1. `setup.sh` has no `--new`/`--join` flags at all.
2. No command wrappers (`~/.claude/commands/<skill>.md`) get created — `install_skills()` only copies skill folders.
3. `setup.sh`'s hook wiring (`configure_hook`) is the *superseded* pre-`marvin_hooks.py` mechanism (writes to `settings.local.json`, which Claude Code ignores outside the home folder) and never wires SessionStart/UserPromptSubmit.
4. No Node, no WezTerm, no dashboard build/install step.
5. The three named engine bugs (Apple Silicon label, `open_in_wezterm` with no GUI running, `generate.py` crashing on missing `enrichment.json`) are all still present, verified by reading the current code.
6. `lib/tart_run.py` and a clean-install test driver don't exist.

---

## Tests to write first

No "How we'll try to break it" section exists on #648 — misuse cases below are derived from the generic adversarial checklist.

**A. `lib/machine_profile.py` (new file `lib/tests/test_machine_profile.py` — zero coverage today)**
1. `_has_battery()` returns `True` when `pmset -g batt` output contains `InternalBattery`.
2. `_has_battery()` returns `False` when it doesn't (desktop Mac).
3. `_has_battery()` returns `False` (never raises) when `pmset` is missing/times out/returns garbage — dependency failure.
4. `_mobility_class()` driven by `_has_battery()`, not `hw_model` substring: `"mobile"` on battery present regardless of `hw_model` string shape.
5. `_label()` returns `"macbook-pro"` for a battery-bearing Mac whose `hw_model` is `"Mac14,2"` (Noah's real case — exactly the bug) and `"mac-mini"` for a non-battery Mac with any `hw_model`.
6. `_label()`/`_mobility_class()` unaffected by an empty or malformed `hw_model` string (empty, whitespace, unicode garbage) — battery is the only signal now.
7. `build_profile()`'s existing 26 callers still see only `"mac-mini"`/`"macbook-pro"` — grep-assert no new label string appears anywhere call sites key off (regression guard for the exact defect code review caught last round).

**B. `lib/marvin_session.py` (extend `lib/tests/test_marvin_session.py`)**
8. **Rewrite** `test_spawns_into_the_running_wezterm_and_falls_back_to_starting_it` (line 62): when `identity` returns `None`, assert **zero** `cli spawn` calls happen at all, and `start` is called directly (this test currently asserts the opposite — the bug itself).
9. New: gui present but both spawn attempts fail → still falls back to `start` (existing behavior, must survive the restructure).
10. New: gui present, saved window still open → tab spawn succeeds, `start` never called (existing behavior, regression guard).
11. Concurrency: two presses racing the `fcntl.flock` while gui is `None` both end up starting WezTerm once each via `start`, never both calling `_spawn`.

**C. `brain-map/generate.py` (new file `brain-map/tests/test_generate_enrichment_load.py`)**
12. Missing `enrichment.json` → `_load_enrichment()` returns all 7 safe defaults (`structural`, `category_order`, `skill_categories`, `category_labels`, `skills_trunk_desc`, `root`, `skill_desc_overrides`), no exception.
13. Corrupt/truncated JSON → defaults returned **and** a WARNING is printed to stderr (not silently swallowed — the exact must-fix defect from last review).
14. Valid JSON but top-level is a list/string, not an object → same warn-and-default path.
15. Partial file (has `root` and `category_order` but missing `skill_desc_overrides`) → only the missing keys get defaulted, existing ones untouched.
16. **`main()` itself**, with `ENRICHMENT_PATH`/`MANIFEST_PATH`/`OUTPUT_PATH`/`TEMPLATE_PATH`/`TREE_DATA_PATH` monkeypatched to temp files and `ENRICHMENT_PATH` pointing at a nonexistent file: `main()` runs to completion and `OUTPUT_PATH` is written (fixes the exact "test never calls `main()`" defect from last review — this is the one that actually proves the wiring, not just the helper).
17. `structural[0]` indexing on the full default (`[{"id": "Core", ...}]`) doesn't raise `IndexError` — direct regression test for the one default most likely to be gotten wrong again.

**D. `setup.sh` (new `lib/tests/test_setup_commands.py`, `test_setup_hooks.py`, `test_setup_instance.py`, `test_setup_dashboard.py` — same `source setup.sh; MARVIN_DIR=...` harness as `test_push_guard.py`)**
18. `install_commands()` writes `~/.claude/commands/<name>.md` for a `type:skill` skill, with the exact one-liner template.
19. `install_commands()` **skips** a skill tagged `type:library` (e.g. `safety-monitor`).
20. `install_commands()` warns and skips (never overwrites) an already-present command file.
21. `install_commands()` on a skill folder with no `SKILL.md` at all (malformed skill) doesn't crash the whole install.
22. `install_hooks()` calls `marvin_hooks.py install` and `~/.claude/settings.json` ends up with `SessionStart` and `UserPromptSubmit` entries.
23. `install_hooks()` run twice is a no-op (idempotent — already guaranteed by `marvin_hooks.py`'s own tested `install()`, this test just proves setup.sh's call site).
24. `install_hooks()` when `marvin_hooks.py` exits nonzero (simulate with a broken venv python) fails loudly, doesn't silently continue.
25. `main --new`: with `gh` stubbed (fake script on PATH recording calls, no network), `~/.agents/instance` ends up as a git repo with `instance.json` containing `{"features": {}}` and a remote pointing at the created repo.
26. `main --new` refuses (clear error) when `gh auth status` fails — dependency-not-ready case.
27. `main --new` refuses (clear error, no partial state left behind) when `~/.agents/instance` already exists.
28. `main --join <url>`: clones the given URL into `~/.agents/instance`, no `build-instance` call, no `gh repo create` call.
29. `main --join` with an unreachable/bad URL fails loudly (git clone's own nonzero exit propagates, no silent empty instance).
30. `main` with **neither** `--new` nor `--join` behaves exactly as before (no instance repo created) — backward-compatibility regression guard for Gil's existing 3 machines.
31. `ensure_node()`/`install_wezterm()`/`install_dashboard()` are no-ops on `linux`/`wsl2` `$OS`.
32. `install_dashboard()` failure (simulate `rebuild_and_install.sh` exiting nonzero) warns and lets `main()` continue rather than aborting the whole install (setup.sh runs under `set -euo pipefail`, so this must be deliberately guarded, not accidental).
33. Unknown flag (`setup.sh --bogus`) fails loudly with a usage message, not silently ignored.

**E. `lib/tart_run.py` (new file `lib/tests/test_tart_run.py`, `host` injected like `vm_run.py`'s)**
34. Happy path: clone → run → wait-for-IP → wait-for-SSH → command → `RunResult(ok=True)` → `finally` always calls `tart stop`+`tart delete`.
35. `tart clone` itself fails (bad/missing base image) → `RunResult(ok=False)`, no VM left running, no crash.
36. IP never appears within timeout → `RunResult(ok=False, error="...timed out")`, VM still deleted in `finally`.
37. SSH never comes up within timeout → same, VM still deleted.
38. The remote command exits nonzero → `RunResult(ok=False, exit_code=N)`, output captured, VM still deleted.
39. An exception mid-run (e.g. `rsync`/copy-in step raises) → VM still deleted (the `finally` must be unconditional, mirroring `vm_run.py`'s own tested discipline).
40. Called twice concurrently with different VM names → no name collision, no shared state (two independent `uuid`-suffixed names).
41. A VM name collision on the host (name already exists from a crashed prior run) → clear failure, not a silent overwrite.

**F. Clean-install driver (new `lib/clean_install_check.py` + `lib/tests/test_clean_install_check.py`)**
42. `check_new()` boots a VM, runs `setup.sh --new` inside it, asserts: dashboard process present, a WezTerm session opens after triggering the launcher mechanism, `instance.json` exists with empty `features`, every `addon_migrate.KNOWN_ADDONS` entry is off via `instance.feature_enabled()`, a seeded secret-shaped push is refused by the guard — then always deletes the VM (`finally`), even if an assertion fails mid-check.
43. `check_join(url)` on a second VM: same five assertions, no `build-instance`/`gh repo create` involved.
44. Either check function, given a `tart_run.run()` that returns `ok=False` at any step, surfaces that failure clearly instead of proceeding to assert against a VM that never finished booting.
45. CLI entry point (`--new`/`--join`) exits nonzero on any check failure (so this is usable as a real gate, not just advisory output).

---

## Decisions

<!-- marvin:decisions -->
### tart_base_image: What does the tart clean-install test clone from?
- [ ] A: Pull a public pre-built macOS base image from cirruslabs' OCI registry (`tart pull ghcr.io/cirruslabs/macos-...`) once, cache it on the M4 Mini, clone it per run. Fast (~seconds to clone), but the base image already has its own set of preinstalled tools, so the test exercises less of `ensure_homebrew`/Xcode-CLT-adjacent setup than a truly bare machine would.
- [ ] B: Build and maintain a custom golden `tart` image on the M4 Mini from a bare macOS install (closer to a real stranger's machine — nothing preinstalled), rebuilt periodically by hand. Slower to set up once, but every clean-install run tests the real first-run path end to end.

### instance_repo_naming: What should `setup.sh --new` name the private instance repo it creates?
- [ ] A: Always `<github-login>/marvin-instance` — one fixed name, no prompt, matches "one person, one instance."
- [ ] B: Prompt interactively for a repo name during `--new` (more flexible, but breaks the "no help from Gil or MARVIN" unattended-install goal the ticket itself states).

---

## Task List

1. **`lib/machine_profile.py`**: add `_has_battery()` (runs `/usr/sbin/pmset -g batt`, absolute path per the existing `ioreg`/`scutil`/`sysctl` convention in this file, checks for `"InternalBattery"`, returns `False` on any failure); change `_mobility_class()` and `_label()` to take that boolean instead of parsing `hw_model`; update `build_profile()`'s call sites. Tests 1–7 first.
2. **`lib/marvin_session.py`**: restructure `open_in_wezterm()` so a `None` `gui_identity()` result skips both `_spawn()` attempts entirely (the window-id one and the `--new-window` one) and goes straight to the `start()` branch, inside the same `fcntl` lock. Tests 8–11 first (test 8 is a rewrite of an existing test whose current assertion encodes the bug).
3. **`brain-map/generate.py`**: add `_SAFE_DEFAULTS` (the 7 unconditionally-indexed top-level keys: `structural`, `category_order`, `skill_categories`, `category_labels`, `skills_trunk_desc`, `root`, `skill_desc_overrides`) and `_load_enrichment(path)` (missing file → defaults silently; corrupt/wrong-shaped JSON → warn to stderr, then defaults; valid partial JSON → `setdefault` only what's missing). Call it from `main()` instead of the raw `json.loads(ENRICHMENT_PATH.read_text())`. Tests 12–17 first.
4. **`setup.sh` — command wrappers**: add `install_commands()` (one `~/.claude/commands/<name>.md` per `$SKILLS_DIR/*/SKILL.md` lacking the `type:library` tag, using the exact one-liner template already used by every installed skill's command file; warn-skip if the destination exists or the skill has no `SKILL.md`), called from `main()` right after `install_skills()`. Tests 18–21 first.
5. **`setup.sh` — hooks**: delete `configure_hook()` and its call, delete `claude-config/settings.template.json` (dead once this lands — no other references exist in the repo); add `install_hooks()` calling `"$VENV_PYTHON" "$AGENTS_DIR/lib/marvin_hooks.py" install`, called from `main()` in place of the old step. Tests 22–24 first.
6. **`setup.sh` — `--new`/`--join`**: argument parsing in `main()`; `setup_instance(mode, join_url)` — `--new` checks `gh auth status`, refuses if `$AGENTS_DIR/instance` already exists, calls `$MARVIN_DIR/bin/build-instance` then `gh repo create <login>/marvin-instance --private --source=. --remote=origin --push` (per Decision `instance_repo_naming`); `--join <url>` does a plain `git clone <url> "$AGENTS_DIR/instance"`. No new sync code — `code_sync.py`'s existing nested-instance handling covers both from here on. Tests 25–30 first.
7. **`setup.sh` — Node, WezTerm, dashboard**: `ensure_node()` (`brew install node`, skip on Linux/WSL2, styled like `install_ollama()`), `install_wezterm()` (`brew install --cask wezterm`, skip on Linux/WSL2 — nothing installs it today, and the MARVIN-button check depends on it), `install_dashboard()` (calls `dashboard/scripts/rebuild_and_install.sh`, skip on Linux/WSL2, `|| warn` so a build failure doesn't abort the rest of `main()`). Tests 31–33 first.
8. **`lib/tart_run.py`** (new, `vm_run.py`-shaped): `RunResult`, `run(name_prefix, command, ...)` doing `tart clone` → `tart run` (backgrounded) → poll `tart ip` → poll SSH → run the command → `finally: tart stop && tart delete`. No machine name hardcoded — callable from any Mac with `tart` installed. Tests 34–41 first.
9. **`lib/clean_install_check.py`** (new): `check_new()` and `check_join(url)`, each booting a VM via `lib/tart_run.py`, running `setup.sh --new`/`--join` inside it, then asserting the five acceptance-criteria checks (dashboard process up; a WezTerm session opens via the launcher mechanism; `instance.json` exists and every `addon_migrate.KNOWN_ADDONS` entry is off via `instance.feature_enabled()`; the push guard refuses a seeded secret-shaped push) — VM always deleted after, pass or fail. CLI `main()` wires `--new`/`--join`, nonzero exit on any failed check. Tests 42–45 first; resolve `tart_base_image` before building the base-image acquisition step.
10. **`CONTEXT.md`**: new subsection under "Engine, instance, the default build and add-ons" documenting `setup.sh --new`/`--join`, the command-wrapper step, and the `tart`-based clean-install mechanism on the M4 Mini — distinct from the existing mac-mini-2012 "Disposable VM" section (different box, different VM tech, different purpose: that one isolates untrusted code, this one proves a stranger's install works). Note that routing the M4 Mini to accept `tart`-tagged dispatch work is an instance-side (`marvin-network.json`) config change for Gil to make post-merge, not part of this engine PR.
11. **Full-suite regression pass**: `~/.agents/venv/bin/python -m pytest lib/tests brain-map/scripts brain-map/tests -x` after steps 1–3 (the three named engine bugs, given `machine_label()`'s 26-caller fan-in) before touching the installer/VM work in steps 4–9.