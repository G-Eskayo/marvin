## North-star fit

**Reuses, not reinvented:** the real production gate — `sandbox_orchestration.execute_ticket`'s exact three-stage verdict sequence (lines 489–505 of `lib/sandbox_orchestration.py`): `build_type_measure.measure()` + `metrics_registry.compare()` (tests pass), `test_change_rule.check_worktree(worktree, base, rules)` (tests must have changed, ADR 0063), `code_review_gate.review_worktree(worktree, base=...)` (review clean) — called directly as pure functions against a historical git worktree, instead of inventing a second notion of "passed." Also reuses `bench.py`'s `_ollama_available()` preflight, `run_once_ollama`'s wall-clock timing pattern, `select_model.py`'s `DEFAULT_LADDER` model choices (`qwen2.5:7b`, `qwen2.5:14b` — already validated here without tool use in #563), and `bench/RESULTS.md`'s existing 30-run log format/`results/<id>-<stamp>.json` convention.

**Why not bench.py's existing fs-task path:** I checked it (`run_once_ollama`, `score_correctness` in `bench/lib/score.py`) — fs tasks there run in a plain `tempfile.mkdtemp` copy with no git history, and "correct" means expect[]-substring matching. That's a weaker proxy than what the ticket asks for ("did the gate pass"), and `run_once_ollama` explicitly returns `None` for fs tasks ("tool use not supported") — exactly the gap `opencode` exists to close by actually editing files. So this spike needs a historical *git* worktree (for `test_change_rule`/`code_review_gate`'s `git diff base...HEAD`), which bench's existing harness deliberately doesn't use. Simplest sufficient form: a small new script living in `bench/` that calls the three real-gate functions directly, rather than bending the general synthetic-task harness to fit one backward-looking spike.

**Tokens:** spends a little real $ (one cheap Claude code-review call per run — the same cost every real ticket already pays at that gate stage) to get a faithful, non-fabricated "would this have passed" answer, rather than a free but meaningless proxy. Everything else (local model inference, opencode) is $0.

**Phone-OS fit:** indirect but real — this determines whether routine small tickets can run entirely on-device, which is the right direction for an offline-capable MARVIN.

**More capable, not more passive:** this is infrastructure measurement for Gil's own pipeline economics (subscription sunset before M3), not a user-facing feature — it leaves him better informed about where to route future tickets, nothing here automates a decision he hasn't made yet ("no adoption yet" stands).

## Tests to write first

The ticket has **no "How we'll try to break it" or Attacks section** — it's a measurement spike, not a feature with a stated threat model. The following covers the standard misuse checklist against this spike's actual moving parts (Ollama, opencode, powermetrics/sudo, git worktrees on historical SHAs, gh/GitHub state):

1. Ollama server down / model not pulled → preflight (`_ollama_available` reuse) fails closed with a clear message; no partial `RESULTS.md` write.
2. `opencode` binary missing from PATH → preflight fails closed with install guidance, same no-partial-write guarantee.
3. `powermetrics` needs sudo and no passwordless entry exists → energy sampler degrades to `energy_j: None` + logged reason; gate/tokens/time for that run are still recorded (an unavailable metric must never null out the rest).
4. A selected PR's merge commit has only one parent (squash/rebase merge, not a true merge) → detected (parent count ≠ 2) and the candidate is skipped, never silently scored against a wrong base.
5. PR has no linked `Closes #N` issue → falls back to the PR's own title+body as the prompt, documented, not a crash.
6. Fewer than 5 merged PRs match the docs-fix/one-line-bugfix/test-addition criteria → reports the actual count found; never fabricates placeholder tickets to force 5.
7. opencode produces an empty diff (refuses/times out) → scored as gate **FAIL** with reason "no changes produced," not confused with a crash or a false pass.
8. opencode produces a huge/runaway diff → the existing scoped test command (`build_type_measure.test_command_for`) and its existing timeout still apply unmodified; verify the sweep doesn't hang.
9. Worktree isolation/cleanup: each ticket gets its own `git worktree add` path, removed with `git worktree remove --force` in a `finally`, even when a run crashes mid-way.
10. Re-running the script (two machines at once, per ADR 0052) must not collide on worktree paths/branch names; `RESULTS.md` append must be a single write at the end of the sweep, not a half-written section if interrupted.
11. A ticket's base SHA isn't present locally (shallow history) → the fetch/worktree-add failure is caught and reported per-ticket, not crashing the whole sweep.
12. Running on a machine missing any one dependency (Ollama, opencode, sudo rights for powermetrics) fails the *specific* missing preflight check, not a generic error.
13. `bench/RESULTS.md` is being read/edited by a person concurrently → the spike's edit is one append at the very end of the run, minimizing collision risk.
14. opencode doesn't expose token usage for this provider → falls back to an approximate, explicitly `tokens_approx: true`-labeled count, never presented as exact.

## Decisions
<!-- marvin:decisions -->
### powermetrics-sudo: Energy is one of the ticket's required metrics, and `powermetrics` needs root. How should this spike get that privilege on the Mac Mini?
- [x] A: Add a scoped passwordless-sudo entry for `powermetrics` only (a `sudoers.d` rule), so this and any future unattended energy sampling just works.
- [ ] B: Run the sweep once by hand, entering the sudo password interactively when prompted; no system change, but energy can't be re-measured unattended later.
- [ ] C: Skip energy for this pass — report gate/tokens/time only, and revisit energy once this is decided.

**Rationale:** Option A enables unattended future measurement and is the most robust for a headless spike on the Mini.

## Task List

1. Resolve the Decision above; confirm `opencode` is installed on the Mac Mini (install if not) and Ollama has `qwen2.5:7b` and `qwen2.5:14b` pulled (same two models #563 already tested without tool use).
2. Write the 14 adversarial tests above against the new modules before implementing them (TDD).
3. Build `bench/lib/energy_apple.py`: an `EnergySampler` context manager wrapping a `powermetrics` subprocess for the call's duration, parsing CPU/GPU power samples and integrating to joules; degrades to `None` + reason when sudo is unavailable (test 3).
4. Build ticket selection in `bench/local_coding_spike.py`: `gh pr list --repo G-Eskayo/marvin --state merged --search ...` filtered to small diffs matching conventional-commit prefixes `docs:`/`fix:`/`test:`; resolve each PR's merge commit, require exactly 2 parents (test 4), extract base/tip SHAs and the linked issue body or PR body fallback (test 5); report plainly if fewer than 5 qualify (test 6).
5. Build a standalone historical-worktree helper (`git worktree add <path> <base_sha>` + `finally: git worktree remove --force`) — deliberately separate from `sandbox_orchestration._create_worktree`, which is tied to live ticket-branch naming, not a historical SHA replay (tests 9, 11).
6. Build `run_opencode()` (sibling to `bench.py`'s `run_once_ollama`): runs `opencode` against Ollama's OpenAI-compatible endpoint inside the historical worktree with the ticket's prompt; reuses `_ollama_available()` (test 1); fails closed if `opencode` is missing (test 2); scores empty/runaway diffs as gate FAIL, not crashes (tests 7, 8); captures tokens from opencode's reported usage with an approximate, labeled fallback (test 14).
7. Wire the real gate in that exact order: `build_type_measure.measure()` + `metrics_registry.compare()` → `test_change_rule.check_worktree(worktree, base_sha, sandbox_orchestration._test_rules(ticket_ref))` → `code_review_gate.review_worktree(worktree, base=base_sha)` — matching `execute_ticket`'s own sequence, producing one pass/fail verdict + reason per run.
8. Save each run's result (ticket, model, gate verdict/reason, tokens, wall time, energy or "unavailable") to `bench/results/local-coding-spike-<stamp>.json`, matching the existing `results/<task>-<stamp>.json` convention.
9. Run the real sweep: 5 tickets × {qwen2.5:7b, qwen2.5:14b} = 10 runs on the Mac Mini (repeat any noisy-looking result, per the harness's established "don't trust n=1" lesson).
10. Append `## Run 31` to `bench/RESULTS.md` in the existing format: results table, Findings, and the required recommendation — is there a "small tickets go local" lane, and which ticket kinds (docs fix / one-line bugfix / test addition) actually qualify — grounded strictly in what passed the real gate.
11. Clean up every worktree created, and confirm none of the 5 real (already-merged, already-closed) tickets had their labels, comments, or claim state touched by this spike.