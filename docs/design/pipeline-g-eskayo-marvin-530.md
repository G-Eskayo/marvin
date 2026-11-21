## North-star fit

- **Reuses:** two existing test patterns, nothing new is built. `tests/test_skill_doc_links.py` is the precedent for asserting a fact about one `SKILL.md`'s raw content. `lib/tests/test_rebuild_manifest.py` already imports `rebuild-manifest.py` via `importlib` and exercises its internals (`parse_frontmatter`, module-level constants) directly against real/synthetic files — the new tests slot into that same file.
- **Simplest sufficient approach:** a one-line frontmatter deletion plus two small assertions, instead of any new validation tooling. The ticket's framing ("bespoke field") doesn't hold — I found 9 `SKILL.md` files declaring `calls:` (`tdd`, `to-prd`, `to-tasklist`, `triage`, `self-improve`, `qa-agent`, `index`, `grill-with-docs`, `improve-codebase-architecture`), and the other 8 describe real runtime call relationships (confirmed via `brain-map/enrichment.json`'s `synapse_labels`, e.g. `"to-prd->to-issues": "calls to-issues once the PRD is synthesized"`). Only `to-tasklist`'s is false (it runs *instead of* `to-issues`, documented in its own body as "Sibling of `to-issues`"). So the fix stays scoped to that one line — the other 8 are out of scope and correct as-is.
- **Tokens:** trivial — a 1-line diff plus ~15 lines of test code, no new files, no new scripts.
- **Correction to the ticket's "What to build":** the instruction to rerun `~/.agents/skills/self-improve/scripts/rebuild-manifest.py` can't be done usefully from inside this PR. That script hardcodes `SKILLS_DIR = Path.home()/".agents"/"skills"` — the real main checkout at `~/.agents`, not this worktree — so running it now would scan the *unfixed* file and achieve nothing. Regenerating the live `~/.claude/manifest.json` (and the chained brain-map rebuild) is already automatic once the fix lands on the main `~/.agents` checkout: a `PostToolUse` hook fires on any edit under a skill's own directory, and mac-mini-2012's `marvin-mirror.service` reruns the same script every mirror tick (ADR 0069). That regeneration is a post-merge side effect, not a file this PR should contain or hand-run.
- **More capable, not passive:** removes a false edge that both `~/.claude/manifest.json` consumers and the brain-map graph (`build_synapses` in `brain-map/generate.py:527-537`) currently surface as a real dependency — anyone (human or agent) reading the graph no longer has to discount it by hand.

## Tests (written first)

Ticket's "How we'll try to break it" says **"Docs-only: exempt"** — correct: this is a static frontmatter edit with no outward-facing surface, no new input/parsing branch (`parse_frontmatter`/`scan_skills` already handle an absent `calls` key via `if raw_calls:` at lines 198/226), so there's no misuse surface the section missed. I'll still add two direct regression tests tying to the acceptance criteria, in `lib/tests/test_rebuild_manifest.py` (the existing home for this script's tests):

1. **AC1 — frontmatter has no `calls`:** `rebuild_manifest.parse_frontmatter(Path(repo)/"skills/to-tasklist/SKILL.md")` returns a dict with no `"calls"` key.
2. **AC2 — manifest entry has no `calls`:** monkeypatch `rebuild_manifest.SKILLS_DIR` to this repo's own `skills/` dir, call `scan_skills()`, find the entry named `"to-tasklist"`, assert `"calls" not in entry`. This exercises the real code path (lines 188-199) against the real fixed file — the closest in-repo proxy for "the rebuilt manifest's to-tasklist entry has no calls" without mutating `~/.claude/manifest.json` outside version control.

No Decisions needed — scope is unambiguous.

## Task List

1. Edit `skills/to-tasklist/SKILL.md`: delete line 5 (`calls: [to-issues]`) from the frontmatter. Leave the "Sibling of `to-issues`" body sentence as-is.
2. Add test (AC1) to `lib/tests/test_rebuild_manifest.py`: `parse_frontmatter` on the real `to-tasklist/SKILL.md` path has no `calls` key.
3. Add test (AC2) to `lib/tests/test_rebuild_manifest.py`: monkeypatch `SKILLS_DIR` to the repo's own `skills/` dir, run `scan_skills()`, assert the `to-tasklist` entry has no `calls` key.
4. Run `~/.agents/venv/bin/python -m pytest lib/tests/test_rebuild_manifest.py -v` to confirm both new tests pass and nothing existing regresses.
5. In the PR description, note that live `~/.claude/manifest.json`/brain-map regeneration happens automatically post-merge (hook + mac-mini-2012 mirror, ADR 0069) and is intentionally not part of this diff.