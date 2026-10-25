1. Write the test file `skills/research-colony/scripts/tests/test_query_research_feed.py` with all 13 cases above (red).
2. Implement `skills/research-colony/scripts/query_research_feed.py` (library function + CLI) to make them pass (green); run against real `chromadb` via `~/.agents/venv/bin/python -m pytest`.
3. Edit `skills/research/SKILL.md`: add `calls: [research-colony]` to frontmatter; add Process step 0 invoking the new script, with the soft-merge instruction.
4. Add the `research->research-colony` entry to `brain-map/enrichment.json`'s `synapse_labels`; confirm `rebuild-manifest.py` / brain-map regenerate picks it up without error (no new test needed — no existing count-assertion to break, checked).
5. Finalize and commit `docs/adr/0070-research-skill-checks-research-feed-first.md`: update its Decision section to "resolved — unconditional check, soft-merge, built in #54 directly" instead of "pending owner."
6. Update `reference-research-feed-recheck.md` memory to drop the "pending" framing and point at the shipped helper.
7. `gh issue edit 54 --repo G-Eskayo/marvin` to add the missing "What to build" section (content = item list above), directly resolving the triage comment.
8. Commit all of the above, push, open the PR against `main`, and comment on / close #54 referencing the ADR and PR once merged, satisfying its three acceptance criteria.