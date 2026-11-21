1. Edit `skills/qa-agent/SKILL.md` line 100: replace `- Dedup: before inserting, check if near-identical content already exists (cosine > 0.95).` with `- Dedup: entries are skipped if their exact content already exists in the KB (SHA-256 hash match). Near-identical paraphrases are not deduplicated yet; see #1314.`
2. Add test 1 and 2 above (SKILL.md text assertions) to `test_qa.py`.
3. Add test 3 above (folder-wide "no cosine promise" regression guard) to `test_qa.py`.
4. Add tests 4, 5, 6 above (real-chromadb, tmp-path dedup behavior checks for `store_entries()` and `store_entry()`) to `test_qa.py`.
5. Run `~/.agents/venv/bin/python -m pytest skills/qa-agent/scripts/tests/test_qa.py -v` and confirm all pass (old and new).
6. Open the PR with body `Closes #506`, per `docs/agents/issue-tracker.md`'s "a PR names its ticket" convention; no Decisions section (none open).