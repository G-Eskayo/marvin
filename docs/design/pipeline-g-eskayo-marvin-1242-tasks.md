# Tasks: Update README to layered architecture with clearer opening

1. Write unit tests for `lib/skill_index.py` covering frontmatter parsing, description truncation, and markdown generation.
2. Regenerate `docs/skills.md` via `lib/skill_index.py` to confirm skill count (security-sweep already in GROUPS).
3. Add "Audience ladder" section to `docs/readme-criteria.md` per Gil's 2026-11-10 revision, cross-referencing `writing-style`'s "Two readers" rule.
4. Simplify README opening paragraph from jargon-heavy to plain language (e.g., "uses the smallest model that can do the job well" instead of "routes to the cheapest model that passes testing").
5. Verify portfolio link `https://gileskayo.me/ai-projects/marvin/` appears near the top of README.
6. Update README skill-count and Contributing section test-count numbers to reflect real measured counts.
7. Confirm issue #1240 is still open (add-on repo status) and note the deferred add-on-README link in PR.
8. Verify no private names introduced (check against existing convention and `config/push-guard/patterns.txt`).
9. Run `readme_audit.py` and verify no new failures from the changes.
10. Run pytest regression guard (`pytest lib/tests/test_readme_audit.py -q`) and capture output.
11. Apply lay-reader test to final opening and capture two-sentence summary for PR description.