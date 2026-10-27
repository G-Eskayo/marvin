## North-star fit

**Reuses before adding anything new:**
- `lib/instance.py`'s existing `engine_repo()`/`owner()`/`tickets_repo()`/`feature_enabled()` (PR #633, already merged) — `--new`/`--join` call these rather than re-deriving ownership.
- `setup.sh`'s own `install_push_guard()` (already shipped) — `--new`/`--join` just call it, no new guard logic.
- `lib/tests/test_push_guard.py`'s test shape (`source setup.sh; MARVIN_DIR=...; <function>`, real temp `HOME`, real temp git remotes) — the pattern for every new `setup.sh` test in this ticket.
- `lib/vm_run.py`'s disposable-VM shape (`RunResult` dataclass, golden-image clone → run → `finally: destroy`, CLI with `--secret-env`) — the pattern for a new `lib/tart_run.py`, not a reinvented one. CONTEXT.md's "Disposable VM" decision already names two golden images on mac-mini-2012 (`marvin-test`, `quarantine`); this adds a third kind of disposable VM (macOS guest, Apple Silicon, `tart`, M4 Mini), same shape, different host/hypervisor.
- `dashboard/scripts/rebuild_and_install.sh` (already does `npm install` → `build:mac` → ad-hoc-sign fallback → install to `/Applications` → relaunch → verify via `pgrep`) — `setup.sh`'s new "build+install the dashboard" step shells out to this existing script instead of re-implementing it.
- `~/.claude/commands/diagnose.md`'s one-line wrapper shape — reused verbatim as the template for the new wrapper-generation step.

**Simplest sufficient approach:** everything above already exists and does the right thing in isolation; the gap is that `setup.sh` never calls most of it end-to-end for a brand-new machine, and three small, already-diagnosed bugs break the result when it does. No new abstraction is needed — just wiring plus three bug fixes plus one new, narrowly-scoped VM-test module.

**Where it spends tokens, not saves them:** a real new file (`lib/tart_run.py`) and a real new test file are unavoidable — there's no existing macOS-VM-on-Apple-Silicon harness to extend. This is a one-time cost that then makes every future "does a fresh install actually work" question answerable by running a script instead of manually walking a friend through SSH (as Noah's install required).

**Phone-OS / capability fit:** this is the ticket that turns "MARVIN runs on Gil's machines" into "MARVIN runs on anyone's machine, unattended" — directly serves north star 2 (OS-shaped: general, reachable by anyone) and leaves a new user *more* capable (a working partner with zero hand-holding) rather than more passive.

**Correction to the ticket's own stated scope:** the issue names three engine bugs (Apple Silicon label, missing command wrappers, `enrichment.json`). Checking `lib/machine_profile.py:open_in_wezterm` in `lib/marvin_session.py` against memory turned up a **fourth** bug already found and fixed ad hoc on Noah's machine but not yet in the engine: with no WezTerm GUI running, `wezterm cli spawn --new-window` auto-starts a headless mux and returns exit 0 with nothing visible open, so `open_in_wezterm` (lines 169-176) wrongly treats that as success and never falls through to `wezterm start`. The acceptance criterion "the MARVIN button works" cannot pass on a freshly-booted VM (no WezTerm GUI yet) without this fix, so it's in scope here even though the issue text doesn't name it.

**A real blocker, not a design choice:** #648 is `blocked by` #646, #647 and (via its body) #641 — all three still open. This isn't paperwork: `setup.sh`'s current `clone_resume_tailor()` unconditionally clones an add-on, which directly contradicts the acceptance criterion "add-ons are off" that #647 is supposed to deliver. I can't make "add-ons off" true in the VM test without either doing #647's work here (out of this ticket's scope and against the ADR's own build order) or leaving that specific check unimplemented until #647 lands. See Decisions below.

## Tests to write first

The issue has no "How we'll try to break it" section, so this list is built from the acceptance criteria plus the north star's general adversarial checklist (bad/empty/huge/malformed input, each dependency failing, repeats/concurrency, wrong permissions, stale state, a person's mistakes), applied to every piece of `setup.sh` this ticket touches. All of these follow `lib/tests/test_push_guard.py`'s pattern: real temp `HOME`, real temp git remotes, `source setup.sh; MARVIN_DIR=...; <function>` — never a mocked git or a mocked filesystem.

**`setup.sh --new` / `--join` flag parsing and flow** (new `lib/tests/test_setup_new_join.py`):
1. `--new` with no args creates `~/.agents/instance/instance.json` with no `features` key (or all-false) and a fresh `~/.claude/private-push-patterns.txt`.
2. `--new` run a second time (person re-runs the installer) does not clobber an existing `instance.json` or duplicate the GitHub repo — idempotent, matching `install_push_guard`'s existing "never overwrite" + "twice is a no-op" tests.
3. `--new` when `gh` is not authenticated fails loud with a clear message, makes no partial `instance.json`, and does not leave a half-created GitHub repo.
4. `--new` when `gh repo create` succeeds but the subsequent clone/push fails (network drop mid-setup) leaves no `instance.json` claiming success — partial state must not look like a finished install.
5. `--join <url>` with a malformed or unreachable instance-repo URL fails loud, same message shape as `--new`'s auth failure, no partial state.
6. `--join <url>` pointed at a repo that is NOT the same owner's instance (wrong account) refuses rather than silently merging a stranger's state — reuses `lib/instance.py`'s owner-derivation to detect the mismatch.
7. Running `setup.sh` with no flag at all still does the current unconditional install (back-compat for Gil's own machines) — regression guard.
8. Both flags given together (`--new --join <url>`) is rejected with a clear error, not "last flag wins" silently.
9. `--new`/`--join` run as a non-interactive script (no TTY, as inside the tart VM over SSH) behaves identically to run by hand — no step silently waits on stdin.

**`machine_profile._label` / `_mobility_class` fix** (extend `lib/tests/test_machine_profile.py` if it exists, else new):
10. `hw.model = "Mac14,2"` (MacBook Air M2 — Apple Silicon unified numbering, no "MacBook" substring) labels as mobile/`macbook-*`, not `mac-mini` — the exact regression from Noah's install.
11. `hw.model = "Mac14,3"` (Mac mini, same numbering scheme) still labels as `mac-mini`, not mobile — the fix must not flip the desktop case while fixing the laptop case.
12. A completely unrecognized `hw.model` string (future hardware) fails to a safe, clearly-labeled default (e.g. `"unknown-mac"`), never crashes and never silently mislabels as mobile or stationary.
13. Empty string from `sysctl hw.model` (sysctl unavailable/permission-denied) is handled the same way as case 12, not an exception.

**Command-wrapper + hook generation** (new `lib/tests/test_setup_wires_commands.py`):
14. After `install_skills()` + the new wiring step, every skill directory under `skills/` whose `SKILL.md` frontmatter does NOT carry `type:library` gets exactly one `~/.claude/commands/<name>.md`, matching the existing one-liner template byte-for-byte against a real wired skill (e.g. `diagnose.md`) as a golden file.
15. A skill tagged `type:library` (`safety-monitor`) gets no command wrapper.
16. A `SKILL.md` with no frontmatter at all (malformed skill) doesn't crash the wiring loop — it's skipped with a warning, the rest still get wired.
17. Re-running the installer never overwrites a wrapper the person has since hand-edited (same "never overwrite" discipline as `install_push_guard`'s private-patterns file).
18. `settings.local.json`'s generated `SessionStart` and `UserPromptSubmit` hook entries actually point at files that exist on disk after install (`session_start_report.py`, `auto_route_hook.py`) — a broken path here fails every future session silently today; must fail loud at install time instead.
19. If `settings.local.json` already exists (current `configure_hook` behavior), the new hook kinds are still at least *warned about* by name, not silently dropped from the warning list the way they are today.

**`brain-map/generate.py` + `enrichment.json`** (extend existing brain-map tests or new):
20. A completely missing `enrichment.json` (fresh VM, no file at all) makes `generate.py` fall back to `{}`-shaped defaults and produce a (plain, mostly-"Other"-categorized) `index.html`, not a crash — same "missing/corrupt reads as blank, never a crash" discipline `lib/instance.py:_config()` already uses.
21. A corrupt/non-JSON `enrichment.json` degrades the same way, with a warning, not a stack trace.
22. A syntactically valid but wrong-shaped `enrichment.json` (e.g. `root` missing, `structural` is a string not a list) degrades the same way rather than crashing deeper in the tree-walk.

**`marvin_session.open_in_wezterm` WezTerm-not-running fix** (extend `lib/tests/test_marvin_session.py`):
23. `gui_identity()` returns `None` (no WezTerm GUI process at all, the freshly-booted-VM case) → the function goes straight to `start([wezterm, "start", ...])`, never attempts `wezterm cli spawn` first.
24. Existing "WezTerm already running, reuse the saved window" and "window closed, open a new one" tests must still pass unchanged — the fix must not regress the already-working cases.

**Dashboard build+install step in `setup.sh`** (new):
25. On a machine with no Node/npm, the new step installs Node (brew) before attempting the dashboard build — mirrors `ensure_homebrew`/`install_ollama`'s existing per-OS branches.
26. If `dashboard/scripts/rebuild_and_install.sh` exits non-zero (e.g. signing fails in ways even its own ad-hoc fallback can't recover from), `setup.sh` fails loud with that script's own error context, not a generic "setup failed."
27. Dashboard build+install step is skipped cleanly (not attempted at all) on Linux/WSL2, where there's no macOS app to build.

**Tart-VM clean-install test harness** (new `lib/tart_run.py` + `lib/tests/test_tart_run.py`, modeled on `lib/tests/test_sandbox_orchestration.py`'s treatment of `vm_run.py`):
28. `tart` binary missing on the host fails the test driver loud and immediately, before attempting any clone/run/delete.
29. VM boot timeout (image never comes up) is treated as a failure, and the VM is still deleted in a `finally` — never leaks a half-booted VM.
30. The driven `setup.sh --new` run inside the VM itself fails (bad args, no network) → the test reports failure *and* still deletes the VM (same guarantee as `vm_run.py`'s existing `finally: destroy`).
31. **Run-twice clean**: running the whole clean-install test twice in a row (back-to-back) leaves no second orphaned VM and no second orphaned throwaway GitHub instance-repo — the test driver names/deletes its own throwaway repo via `gh repo delete --yes` in the same `finally`, reusing `vm_run.py`'s secret-passing convention (`--secret-env`) to hand the VM a scoped, disposable GH token, never a personal one.
32. `--join` test: a second VM boots, and if network/SSH to the first VM's pushed instance repo is down, `--join` fails loud rather than silently producing an "empty-looking but actually broken" instance.
33. Push-guard-in-the-VM check: inside the booted VM, a commit adding a string from a seeded fake `private-push-patterns.txt` is refused by `git push` (end-to-end exercise of the already-tested unit behavior, now through the real VM network path) — and the VM is confirmed still reachable/undamaged afterward (the refusal doesn't corrupt the clone).
34. Add-ons-off check, scoped to what's buildable now (see Decisions): the VM's fresh `instance.json` has no `features` entry set `true`; test explicitly does **not** yet assert on `resume-tailor`'s absence, since that's `clone_resume_tailor()`'s current unconditional behavior and is #647's job to change — this assertion gets added when #647 lands, not faked here.

## Decisions
<!-- marvin:decisions -->
### sequencing: #648 is blocked by #646/#647/#641, all still open. How should this PR handle that?
- [ ] A: Build and merge everything in this plan that doesn't need #646/#647/#641 (the `--new`/`--join` flags, all four engine bug fixes, dashboard build+install step, the tart-VM harness itself) now, with the VM test's "add-ons off" and "empty instance via first-run" checks left as explicit `pytest.mark.skip(reason="needs #647")`/`skip(reason="needs #641")` markers that fail loudly to remind whoever lands those tickets to unskip them
- [ ] B: Hold this whole ticket until #646, #647 and #641 all merge, then build it as one pass with every acceptance check live from the start

### test-instance-account: which GitHub account/org owns the throwaway private instance repos the clean-install test creates and deletes on every run?
- [ ] A: A dedicated disposable test account/org (not `G-Eskayo`), with its token stored wherever the Mac Mini already keeps other test secrets, handed into the tart VM the same way `vm_run.py --secret-env` already hands in a one-run GitHub token
- [ ] B: `G-Eskayo`'s own account, with the test repo named distinctly (e.g. `marvin-instance-test-<run-id>`) and always deleted in the test's `finally` (text)

## Task List

1. **`lib/machine_profile.py`**: fix `_label()`/`_mobility_class()` to stop keying off the `"MacBook"` substring (broken for Apple Silicon's unified `MacN,n` numbering) — detect mobility via a reliable signal (battery presence, per Noah's own ad hoc fix) with model-name as a secondary label source; write tests 10-13 first.
2. **`lib/marvin_session.py`**: fix `open_in_wezterm` so a `None` `gui_identity()` skips the `wezterm cli spawn` attempts entirely and goes straight to `wezterm start`; write tests 23-24 first.
3. **`brain-map/generate.py`**: make the `ENRICHMENT_PATH` read degrade to `{}`-shaped safe defaults on missing/corrupt/wrong-shaped input, matching `lib/instance.py:_config()`'s existing discipline; write tests 20-22 first.
4. **`setup.sh` — command + hook wiring step**: add a step after `install_skills()` that writes `~/.claude/commands/<name>.md` for every non-`type:library` skill (one-liner template from `diagnose.md`), and extend `claude-config/settings.template.json` with `SessionStart` (`session_start_report.py`) and `UserPromptSubmit` (`auto_route_hook.py`) hook entries; write tests 14-19 first.
5. **`setup.sh` — dashboard build+install step**: add Node install (brew/apt, following the existing `ensure_homebrew`/`install_ollama` per-OS branch style) and a call to `dashboard/scripts/rebuild_and_install.sh`, skipped on Linux/WSL2; write tests 25-27 first.
6. **`setup.sh --new` / `--join`**: add flag parsing to `main()`; `--new` creates the private instance repo (`gh repo create --private`), writes `~/.agents/instance/instance.json`, runs `install_push_guard`, and runs steps 4-5 above; `--join <url>` clones the given instance repo via the existing `code_sync.py pull` path instead of creating a new one; write tests 1-9 first.
7. **`lib/tart_run.py`**: new module, `vm_run.py`-shaped (`RunResult`, golden-image clone → run → `finally: delete`), targeting `tart` on the M4 Mini instead of `virsh`/`qemu-img`; write tests 28-30 first.
8. **Clean-install test driver**: a script (or `lib/tart_run.py` CLI invocation) that boots a `tart` VM, runs `setup.sh --new` from a fresh clone, checks dashboard launch + MARVIN button + empty instance + push-guard refusal + (scoped) add-ons-off, deletes the VM; a second VM for `--join` against the first's pushed instance; write tests 31-34 first, resolve the two Decisions above before implementing the add-ons-off and instance-repo-cleanup pieces.
9. **CONTEXT.md**: extend the existing "Disposable VM" bullet to name the M4 Mini's `tart`-based macOS clean-install images alongside the two existing `libvirt` images on mac-mini-2012.