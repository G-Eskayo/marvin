## North-star fit

**Reuses:** the real `longform-callout` component (`templates/components/longform-callout.html` + its `templates.json` entry — one field, `TEXT_HTML`, type `"html"` so it is never re-escaped), the existing `research` role **already present in all four content templates** (`templates/content/{app-product,skill-tool,system,ml-study}.json` — confirmed by reading all four; a prior pass on this ticket already added it), the one-line rule **already present in `templates/GUIDE.md`** ("research section (when present) comes from the evidence log with all public entries included" — also already done), `project_catalog.portfolio_repo_path()` for the content-file root, and the skill's existing, unmodified step 5 (`portfolio_longform.py <url> --author`) as the only thing that ever talks to WordPress. The only genuinely new code is one pure module, `lib/portfolio_evidence.py`, plus a one-line addition to `portfolio_content.py`'s existing `evidence_in()` (below).

**Simplest sufficient approach:** `portfolio_evidence.py` only ever reads `docs/research/evidence-log.md` and rewrites `content/longform/<slug>.json`. It never imports or calls `portfolio_longform.author()` — that needs a live page URL and already happens, correctly, as the skill's own step 5.

**Tokens:** the first "revised" design doc for this ticket already diagnosed every one of these bugs correctly from reading the real collaborators — but the code actually sitting in this worktree (`lib/portfolio_evidence.py`, `lib/tests/test_portfolio_evidence.py`) still has every one of them, unfixed, and code review caught the gap between plan and execution. That is where the tokens were actually lost last time: a correct diagnosis that was never applied. This revision changes nothing about the diagnosis; it (a) re-verifies every claim against the current file state line-by-line so nothing is assumed stale, and (b) adds one thing the previous plan missed entirely: the content templates' `"evidence": ["callout"]` requirement for the `research` role is never satisfiable, because `portfolio_content.py`'s `evidence_in()` has no notion of "callout" — every research section would permanently show as `template-missing-evidence` in the Evaluation. Catching that now is a few lines; catching it after shipping would be a second investigation.

**User capability:** unchanged — this surfaces research Gil already logs; it decides nothing for him.

**Ticket's stated fit:** the ticket doesn't state one.

## What the current (uncommitted) code actually does, re-verified line by line

All ten code-review findings are still present exactly as described, confirmed by re-reading `lib/portfolio_evidence.py` just now:

- `render_entry_html` (line 183-184) appends the caveat paragraph whenever `entry["caveat"]` is non-empty — never gated on `entry["public_use"] == "careful"`. A `Yes (...)` entry's parenthetical (real E7: "credit the open-source projects") still leaks.
- `_finalize_entry` (lines 111-120) computes `caveat` from `pub`, which is `(entry.get("public_use") or "").lower().strip()` — the caveat text itself gets lower-cased.
- `research_section_for` (lines 216-220) checks `project.get("localPaths")` before `project.get("primaryPath")` — exactly backwards.
- `apply()` (lines 254-257) still does `import portfolio_longform` and defaults `author_fn=portfolio_longform.author`, called as `author_fn(content_path)` — one positional `Path`, not `(url, content_dict)`.
- `apply()` (lines 302-308): the file is written at line 304 *before* `author_fn` is called at line 306; if it raises, line 308 returns `{"updated": True, "error": ...}` — the write already happened, the caller has no idea it's "partial."
- `_links` (lines 136-140) linkifies any non-empty `url` group, with no absolute-URL check at all.
- `sync_content_file` (line 313) takes no `content_path` parameter.
- `test_research_section_for_returns_none_when_catalog_missing` (line 425-427) calls `pe.research_section_for("any", None)`, which makes the module call `project_catalog.read_catalog(project_catalog.catalog_path())` against this machine's real `~/.claude/catalog/projects.<id>.json`.
- `test_apply_is_idempotent` and `test_apply_places_research_before_marvin_section` (lines 528-530, 543-545) are `pass` stubs.
- `test_apply_respects_public_use_flag_changes` (lines 579-616) corrupts `## E2. Another finding` into `## E2X. Another finding` instead of flipping the `Public use` value, and its final assertion is just `assert second_html` (truthy-only).
- `test_research_section_for_handles_missing_repo_field` (lines 459-468) wraps its real assertion in `if section is not None:`, so a `None` result makes the test vacuously pass, and it never checks a bare `#42` stays plain text.

Newly found while re-verifying against the real collaborators for this revision:

- **Internal-ID leak onto the public page.** `render_entry_html` (lines 174-176) always prepends `<p><strong>E1. Dark vs. light mode for older readers</strong></p>` — the evidence log's internal tracking ID and title, never asked for by the ticket ("source, what we took, and the decision it led to, with links" — no ID, no title), and it's also *why* `render_entry_html` can never return `""` for a malformed entry (code review's own note): there's always at least this label.
- **Transient read failure vs. genuine absence are conflated.** `research_section_for` returns `None` both when there's truly no evidence log *and* when reading it fails for any other reason (permission error, bad encoding — `log_path.read_text()` at line 231 only catches `OSError`, not `UnicodeDecodeError`, so that one isn't even caught). Both paths currently either crash or look like "no entries." If `sync_content_file` treats a transient `None` the same as "remove the section," a momentary permission hiccup would delete a real, already-synced research section.
- **`evidence_in()` can never see a "callout."** `templates/content/*.json` already declare `"evidence": ["callout"]` for the `research` role (added by an earlier pass on this ticket), but `portfolio_content.py`'s `evidence_in()` (lines 53-66) only ever adds `diagram`/`chart`/`screenshot`/`real-output`/`link`/`numbers` — "callout" is not a reachable value. Every research section, forever, would show a `template-missing-evidence` finding in the Evaluation. This directly blocks the previous design's own verification step ("confirm no new `template-missing-*` findings").
- **Diff churn note, cheap to fix:** `json.dumps(content, indent=2)` (line 304) uses default `ensure_ascii=True` and writes no trailing newline, reformatting the whole hand-written content file on first sync.

## Design

`lib/portfolio_evidence.py` — pure functions, no network, no WordPress calls, **no import of `portfolio_longform` at all**:

- `parse_log(text) -> list[dict]`: entries split on `^##\s+(E\d+)\.\s+(.+)$`. Field lines matched by **exact** normalized label (`re.match(r"^-\s*\*\*([^*]+):\*\*\s*(.*)$")`, label lower-cased and stripped) against a fixed map `{"source": "source", "what we took": "what_we_took", "drives": "drives", "decision": "drives", "public use": "public_use"}` — anything else (`confidence`, or any future field) falls through unmapped and is discarded, continuation lines included. This replaces the old substring `"word in before.lower()"` check, which is why `"Sources considered:"` could have hijacked the real `Source` field — exact-label matching can't do that.
- `_finalize_entry`: splits the **raw, not lower-cased** `public_use` value once on the first `(`; the primary token is lower-cased and normalized to `yes`/`careful`/`internal` (unrecognized or missing → `internal`); the parenthetical remainder, if any, is kept **verbatim** (original casing) as `entry["caveat"]`. Fixes the casing bug directly.
- `public_entries`: unchanged — filters to `yes`/`careful`, preserves order.
- `_links(text) -> str`: `[text](url)` → `<a href="url">` only when `url` matches `^(https?://|mailto:)`. Anything else — unclosed brackets, empty URLs, nested brackets, relative paths (real E7 `../research-existing-resources.md`) — stays plain text.
- `_linked_issues(text, repo)`: unchanged — bare `#123` → GitHub link when `repo` is known, else left as text.
- `render_entry_html(entry, repo=None) -> str`: builds Source / What we took / Decision paragraphs (never an ID/title label — dropped entirely: it was never asked for, and it leaked internal tracking numbers onto a public page), plus a caveat paragraph **only when `entry["public_use"] == "careful"` and `entry["caveat"]` is non-empty**. When there is nothing to say (every field empty), returns `""` directly, **never calling `portfolio_templates.render`** — so a template-field mismatch like last time's would fail loudly on the first real entry instead of being hidden behind an always-non-empty string. Otherwise calls `portfolio_templates.render("longform-callout", {"TEXT_HTML": composed})` and returns `result["html"]` (never `result.get("html", text_html)` — `render()` always returns a dict with an `"html"` key, confirmed by reading `portfolio_templates.render`; the fallback was dead code that happened to be hiding bug 1).
- `research_section_html(entries, repo=None) -> str | None`: joins non-empty rendered entries with `"\n\n"`; `None` when the list is empty or every entry rendered empty.
- `research_section_for(slug, catalog=None) -> dict | None`: resolves the project record (`project.get("primaryPath") or (project.get("localPaths") or [None])[0]` — `primaryPath` first, fixing the backwards check), reads `<path>/docs/research/evidence-log.md`. Three distinct outcomes, kept distinct on purpose:
  - no catalog / no catalog entry / entry has no path at all / log file doesn't exist / log parses to zero public entries → **`None`** (a legitimate "nothing to show").
  - log file exists but can't be read (`PermissionError`, `UnicodeDecodeError`, any other `OSError`) → **raises** `EvidenceReadError(path, cause)`, a module-local exception. This is the fix for the "transient failure silently deletes an existing section" bug: it must not look like `None`.
  - success → `{"heading": "Research behind it", "role": "research", "body_html": ...}`.
- `merge_section(content: dict, section: dict | None) -> dict`: pure upsert, no file I/O. Inserts the `research`-role section immediately before the first `built-with`/`marvin`-role section, or appends at the end when neither exists (verified against the real templates: this exact rule reproduces the declared order in all four — `app-product`/`system` put `research` right before `built-with`; `skill-tool` right before `marvin`; `ml-study` has neither, and `research` is its last declared section). Replaces an existing `research`-role section in place; removes it when `section is None`.
- `sync_content_file(slug, content_path=None, *, catalog=None) -> dict`: resolves `content_path` from `project_catalog.portfolio_repo_path() / "content" / "longform" / f"{slug}.json"` when not given (fixes the wrong-repo-path bug — confirmed against the real file layout: `~/Developer/portfolio-website-updater/content/longform/clarity-captions.json` exists; the evidence-log project's own `primaryPath` does not have a `content/` directory at all). Reads the JSON; if `research_section_for` raises `EvidenceReadError`, catches it and returns `{"updated": False, "error": str(exc)}` **without touching the file** — the existing section, if any, survives. Otherwise computes the section, applies `merge_section`, writes back only if the sections list actually changed, using `json.dumps(content, indent=2, ensure_ascii=False) + "\n"` (fixes the diff-churn note). Returns `{"updated": bool}` or `{"updated": False, "error": ...}` for corrupt JSON / missing content file / missing parent directory — all caught, none raised.
- CLI: `portfolio_evidence.py sync <slug>` → prints the `sync_content_file` result as JSON. No `apply` command, no `author_fn` parameter anywhere in this module.

**`portfolio_content.py` one-line addition** (`evidence_in`, after the existing `<img>`/`<a>` checks): `if re.search(r'class="longform-callout"', html or ""): kinds.add("callout")`. This is the only way the `research` role's already-declared `"evidence": ["callout"]` requirement can ever be satisfied; without it every research section permanently fails the Evaluation's coverage check.

**Already done, verified against the real repo, no action needed this round:** the `research` role in all four `templates/content/*.json`, and the GUIDE.md line. (Templates read directly; GUIDE.md grepped directly.)

**Module docstring:** will not cite "ADR 0061" — that number belongs to `0061-check-after-merge-retest-only-on-overlap.md`, an unrelated ADR; the previous attempt's docstring comment was simply wrong. This feature is additive to ADR 0051's content-template machinery and doesn't need a new ADR of its own.

## Decisions

No decisions needed — every open point here is a correctness call already settled by the ticket's own wording or the real code it has to integrate with, not a taste/branch call for the owner:
- Dropping the entry ID/title label from the rendered output: the ticket says each entry shows "source, what we took, and the decision it led to" — no ID, no title, and showing the internal `E1`/`E7` tracking numbers on a public page is a direct reading of the "sell it" voice rule, not a style preference.
- Relative/dead links left as plain text rather than guessing a GitHub default-branch blob URL: a correctness call, not a voice call.
- Caveat shown only for `careful`, never for `yes`: literal reading of the acceptance criterion.
- Adding the one-line `"callout"` evidence rule to `portfolio_content.py`: required for the templates' own already-declared, already-shipped requirement to ever pass; not a new feature decision.

## Tests first

Against the **real** `longform-callout` template/templates.json (no monkeypatched `render`) and a **verbatim fixture of the real** `~/Developer/clarity-captions/docs/research/evidence-log.md` (its real E1-E8, re-read directly for this revision — note the old test file's hand-written `EVIDENCE_LOG` fixture only goes to E7 and uses different, invented wording; it is replaced).

**From "How we'll try to break it" + general misuse:**
1. Malformed entry (missing `Source` or `What we took`) parses without raising; renders with what it has.
2. Entry with no `Public use` line at all → `internal`, excluded.
3. Malformed `Public use` (real E6: `Internal (the "..." outcome is Yes)`) → `internal`, primary token wins.
4. **Caveat casing preserved** for a `careful` entry with a parenthetical (real E1, E5, E8) — asserted against the *original-case* wording ("light and dark both work", not lower-cased). Guards the casing bug.
5. **Caveat shown only for `careful`**: real E7 is `Yes (credit the open-source projects)` — rendering E7 must NOT contain "credit the open-source projects" anywhere. Guards the leak bug directly with the real fixture, not a synthetic one.
6. `careful` entry with no parenthetical (real E3) → empty caveat, no "Caveat:" label at all, no crash.
7. **Exact-label field matching**: a line `- **Confidence:** ...` (single-line, as every real entry has) is discarded and never overwrites `source`/`what_we_took`/`drives`/`public_use`; a synthetic `- **Sources considered:** ...` line must NOT be read as the `Source` field (guards the substring-matching bug that exact-label matching replaces).
8. Dead/malformed link syntax — unclosed bracket, empty URL, nested brackets (the `DEAD_LINKS` fixture already in the file, currently unused by any test) — never produces an `<a>`.
9. **Relative-path link** (real E7's `[docs/research-existing-resources.md](../research-existing-resources.md)`) left as plain text, not emitted as a dead `href`.
10. Very long log (100+ generated entries, plus one entry with a 10k-character field) parses and renders correctly, with a generous (not flaky) bound — assert completion within a few seconds, not a tight wall-clock number.
11. Duplicate entry ids both parsed, neither dropped.
12. Out-of-order / gapped ids (`E1`, `E3`, `E2`) parsed in file order, not numeric order.
13. Empty log → `[]`.
14. Case/whitespace-insensitive `Public use` normalization (`" careful "`, `"YES."`).

**Dependency failures:**
15. `research_section_for` with no catalog entry, or a catalog missing entirely (passed as `catalog={}` / monkeypatched `project_catalog.read_catalog` to a tmp path — **not** `catalog=None` against the real machine catalog, which is what the current test wrongly does), or an evidence-log file that genuinely doesn't exist → `None`.
16. Corrupt catalog JSON (not a dict, or missing `"projects"`) → `None`, no crash.
17. **Evidence-log file exists but can't be read** — not UTF-8 (binary garbage) and a permission-denied read, simulated via monkeypatch — **raises `EvidenceReadError`**, does not silently return `None`.
18. **`sync_content_file` on that same unreadable-log case leaves the content file byte-for-byte unchanged** and reports `{"updated": False, "error": ...}` — the test that would have caught "transient failure deletes an existing section."
19. Catalog references a `primaryPath` that no longer exists on disk (stale catalog) → `None`, no crash.

**Template-contract regression guard (catches the exact bug 1 shape):**
20. `render_entry_html` against the **real** template: output contains `<div class="longform-callout">` and the real source/what-we-took/drives text — fails loudly if the field name this module sends ever drifts from `TEXT_HTML` again.
21. Issue numbers in Drives/What-we-took become real links when `repo` is known (real E1 `#96`); bare text when `repo` is `None`. Missing `repo` field on the catalog record → section still renders, no crash.
22. An entry with nothing left after filtering renders `""` and is excluded by `research_section_html` — never an empty callout div.
23. No entry's rendered HTML ever contains its own `E<n>` id or title text (replaces the old, now-wrong assumption that IDs *should* appear).

**End-to-end against the real fixture:**
24. The real evidence-log.md, full text: E6 (Internal) absent everywhere in the output (byte-level check); E1/E2/E3/E4/E5/E7/E8's real content present; E1/E5/E8's real caveat wording present with correct casing; E7's relative link not a dead `href`; E2/E4/E7 (`Yes`) carry no caveat text.

**`merge_section` (pure):**
25. Inserts before the first `built-with`/`marvin`-role section (verified against the real `app-product`/`system`/`skill-tool` layouts); appends at the end when neither exists (the real `ml-study` layout).
26. Replaces an existing `research`-role section in place, never duplicating.
27. Removes the section when passed `None` and one currently exists.
28. Passing the same section twice produces an identical sections list (true no-op).

**`sync_content_file` — repeats, permissions, stale state, a person's mistakes:**
29. **Resolves the content path from `project_catalog.portfolio_repo_path()`**, not the evidence-log project's own path — two distinct `tmp_path` trees, so a wrong resolution fails with a missing-file error instead of silently reading/writing the wrong tree.
30. First run on a project with public entries: `updated: True`, file now has exactly one `research`-role section with the real content, written with `ensure_ascii=False` and a trailing newline (no ASCII-escaping of non-ASCII text, no reformatting beyond the inserted section).
31. **Idempotent (repeats)**: running twice unchanged → second call reports `updated: False` and the file's bytes are byte-for-byte identical to after the first call.
32. **Re-running after the log changes updates the page**: flip one real entry's `Public use` value in place (e.g. real E7 `Yes` → `Careful (new caveat)`) — not by corrupting its header — and confirm the re-synced section reflects exactly the new state. Directly guards acceptance criterion 3.
33. Corrupt/unreadable content JSON → `{"updated": False, "error": ...}`, no raised traceback.
34. Content file's parent directory missing entirely (a project never authored before) → fails closed the same way, no `FileNotFoundError` escapes.
35. **Wrong permissions**: content file not writable (simulated by making the write raise `PermissionError`) → caught, returned as an error, no partial write left behind.
36. **Structural guard**: `portfolio_evidence.py`'s source text never contains `"portfolio_longform"` — asserted directly against the module's own source file. Guards the `author_fn` coupling from silently coming back.
37. **Concurrency, considered and accepted rather than skipped**: two sequential `sync_content_file` calls with different evidence-log states produce the last-writer-wins result with no corruption (no partial/interleaved JSON) — documented as acceptable for a single-operator CLI tool, not a multi-process server; no locking is added.

**`portfolio_content.py` (new, one test):**
38. `evidence_in()` on a real rendered `research` section's `body_html` (containing `class="longform-callout"`) includes `"callout"` in its result, so `coverage()` no longer reports `template-missing-evidence` for the `research` role once a section exists.

## Task List

1. Add `EvidenceReadError` and rewrite `lib/tests/test_portfolio_evidence.py` from scratch per the 38 tests above (red): delete the two `pass` stubs, replace the hand-written `EVIDENCE_LOG` fixture with a verbatim copy of the real `~/Developer/clarity-captions/docs/research/evidence-log.md`, fix the catalog-missing test to not touch the real machine catalog, fix the `Public use` flag-change test to flip a value instead of corrupting a header, stop monkeypatching `portfolio_templates.render` anywhere, add the `DEAD_LINKS`-based test that's currently defined but unused.
2. Rewrite `lib/portfolio_evidence.py`: exact-label `parse_log` (with correct-case caveat extraction), `public_entries`, `_links` (absolute-only), `_linked_issues`, `render_entry_html` (no id/title label, real `TEXT_HTML` field, caveat gated on `careful`), `research_section_html`, `research_section_for` (`primaryPath`-first, raises `EvidenceReadError` on a real read failure instead of returning `None`), `merge_section` (pure), `sync_content_file` (portfolio-repo path, `ensure_ascii=False` + trailing newline, catches `EvidenceReadError` without touching the file) — make all tests pass (green). No `apply()`, no `author_fn`, no import of `portfolio_longform`.
3. Add the one-line `"callout"` detection to `portfolio_content.py`'s `evidence_in()`, and the one test for it (`lib/tests/test_portfolio_content.py`).
4. Verify (no edits expected, but re-check after step 2/3 lands) that `templates/content/*.json` and `templates/GUIDE.md` in the portfolio repo still carry the already-shipped `research` role and GUIDE line — they do today; nothing to commit there this round unless something regressed.
5. Commit and push the marvin-repo changes (steps 1-3) as this ticket's PR.
6. On the mac-mini dev site, from `~/.agents/lib`: run `~/.agents/venv/bin/python portfolio_evidence.py sync clarity-captions` against the real `content/longform/clarity-captions.json`; verify by reading the file that the new `research`-role section has E1/E2/E3/E4/E5/E7/E8's real content, E6 absent, E1/E5/E8's real caveats present with correct casing, and no `E<n>` labels anywhere.
7. Run the `portfolio-page` skill's existing step 5 (`portfolio_longform.py <url> --author content/longform/clarity-captions.json`, `--plan` first) to push the updated page to the dev site.
8. Run `portfolio_content.py --json` to confirm the new `research` section registers no `template-missing-evidence` finding (depends on step 3) and no new `copy-ai-phrase`/em-dash hits.
9. Scroll-capture a screenshot of the rendered "Research behind it" section on the dev site for the PR, per the simulator/UI-image rule.
10. Flip one real entry's `Public use` value in the local (uncommitted) clarity-captions evidence log, re-run `sync` + step 7's author, confirm the dev-site section updates, then revert the test edit.
11. Report to Gil: what changed in `lib/`, the screenshot, and that the regression traced to a correct diagnosis never having been applied to the code — this pass re-verified every claim against the real files and fixed them in place, plus the `"callout"`-evidence gap the original plan missed.