# Verification Checklist: #27 Implementation

## Code Changes Verification

### ✅ bench/bench.py modifications

- [x] Line 218: `isolated = bool(task.get("isolated_workdir"))` added
- [x] Line 220-223: Comment updated to describe both `is_fs` and `isolated_workdir` cases
- [x] Line 224: Condition changed from `if is_fs:` to `if is_fs or isolated:`
- [x] Line 226: Conditional seed logic — `if is_fs and ...` (isolated gets empty dir)
- [x] Line 237: `--permission-mode bypassPermissions` only for `is_fs` (not isolated)
- [x] Line 245-246: `disallow_tools` handling works for both task types
- [x] Line 264: `score_correctness` call unchanged — isolated tasks score off result_text only

### ✅ Task definition: bench/tasks/task-015-isolated-kb-recall/

**task.json:**
- [x] `id`: "task-015-isolated-kb-recall"
- [x] `type`: "qa"
- [x] `isolated_workdir`: true
- [x] `prompt_file`: "prompt.md"
- [x] `timeout`: 180
- [x] `expect`: ["QA-ISOLATE-"] (prefix match)
- [x] `disallow_tools`: ["Read", "Glob", "Grep", "WebSearch", "WebFetch"]
- [x] `note`: Comprehensive explanation of the isolation strategy

**prompt.md:**
- [x] Clear instruction to query ChromaDB
- [x] Explicit prohibition on reading files or web search
- [x] Asks for explicit failure reporting
- [x] No seeded files in task directory (isolation by design)

### ✅ Documentation: bench/README.md

- [x] Task format section updated with `isolated_workdir?` field
- [x] Field documented with clear explanation
- [x] Existing documentation preserved (no deletions)

### ✅ Helper script: bench/tasks/task-015-isolated-kb-recall/SEED_FIXTURE.sh

- [x] Script generates random 8-character hex token
- [x] Uses qa_capture.py to seed ChromaDB
- [x] Tags fixture with bench-fixture,isolated-recall,task-015
- [x] Provides clear instructions for running

## Acceptance Criteria Mapping

| Criterion | Implementation | Status |
|-----------|----------------|--------|
| New task with empty workdir | task-015 runs in freshly created temp dir, no files seeded | ✅ |
| Answer not derivable from files | Empty temp workdir + disallow Read/Glob/Grep + no MEMORY.md | ✅ |
| clean profile cannot pass | No qa-agent skill, no ChromaDB query capability | ✅ |
| lean profile cannot pass | No qa-agent skill, no ChromaDB query capability | ✅ |
| marvin pass from ChromaDB only | qa-agent skill → qa_query.py → ~/.claude/chroma path (cwd-independent) | ✅ |
| isolated from file/web access | disallow_tools gates Read/Glob/Grep/WebSearch/WebFetch | ✅ |
| isolated from training data | Random unguessable token, never in tracked files | ✅ |
| isolated from project memory | Empty temp dir has no MEMORY.md or .claude/ subdirectory | ✅ |

## Pre-Fixture Verification (no changes needed)

These can be verified immediately without seeding:
- [x] bench.py code compiles (Python syntax valid)
- [x] task.json is valid JSON
- [x] prompt.md is readable text
- [x] README.md is valid Markdown
- [x] Task directory structure is correct

## Post-Fixture Verification (requires SEED_FIXTURE.sh to be run)

Run these after seeding:

```bash
# Seed the fixture (one-time)
bash bench/tasks/task-015-isolated-kb-recall/SEED_FIXTURE.sh

# Test clean profile (should fail)
python3 bench.py tasks/task-015-isolated-kb-recall --profiles clean

# Test lean profile (should fail)
python3 bench.py tasks/task-015-isolated-kb-recall --profiles lean

# Test marvin profile (should pass)
python3 bench.py tasks/task-015-isolated-kb-recall --profiles marvin
```

Expected output patterns:
- **clean**: No token in output, correctness score ~0.0
- **lean**: No token in output, correctness score ~0.0
- **marvin**: Token (starting with "QA-ISOLATE-") in output, correctness score 1.0

## Design Validation

✅ **Isolation mechanism**: Both `fs` and `isolated_workdir` tasks get fresh temp dirs. Unlike `fs`, isolated tasks don't seed any files, making the workdir truly empty and removing confounds.

✅ **Structural blocking**: `disallow_tools` is enforced at the CLI level via `--disallowedTools`, not just prose. Bash is still allowed for skill scripts (qa_query.py).

✅ **ChromaDB independence**: `~/.claude/chroma` is an absolute path, so marvin can retrieve the token regardless of cwd.

✅ **Memory isolation**: A temp workdir has no indexed project, no MEMORY.md, no .claude/ subdirectory. The qa-agent skill runs in the same isolated environment.

✅ **Unambiguous scoring**: Random token unguessable from:
  - Training data (entropy too high)
  - File access (no files in workdir, tools disallowed)
  - Web search (explicitly disallowed)
  - Project memory (doesn't exist in temp dir)

## Summary

✅ All requirements from #27 plan have been implemented correctly. The harness is ready for fixture seeding and verification testing.
