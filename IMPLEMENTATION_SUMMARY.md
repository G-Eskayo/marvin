# Implementation Summary: #27 — Isolated-memory QA task type

## What has been implemented

### 1. ✅ Modified `bench/bench.py` — added `isolated_workdir` task flag

- **Lines 218, 224-228**: Generalized the temp-dir logic to support both `fs` tasks and tasks with `isolated_workdir: true`
- Both types now get a freshly created empty temp directory (`Path(tempfile.mkdtemp(...))`)
- `is_fs` tasks still seed files from `task["dir"] / "files"` if they exist
- `isolated_workdir` tasks do NOT seed any files — the workdir is empty by design
- Updated comment above the branch to reflect the new behavior (lines 220-223)
- `--permission-mode bypassPermissions` remains only for `is_fs` tasks (line 237)
- `disallow_tools` continues to work for both task types via `--disallowedTools` (lines 245-246)
- `score_correctness` call unchanged — isolated tasks score off `result_text` only (line 264)

### 2. ✅ Created new task: `bench/tasks/task-015-isolated-kb-recall/`

**`task.json`:**
- `id`: "task-015-isolated-kb-recall"
- `type`: "qa"
- `isolated_workdir: true` — triggers the new isolation mechanism
- `timeout`: 180 seconds
- `expect`: `["QA-ISOLATE-"]` — prefix match for any token starting with this string
- `disallow_tools`: `["Read", "Glob", "Grep", "WebSearch", "WebFetch"]` — blocks all file/web access
- `note`: Comprehensive explanation of the isolation strategy (see task.json for full details)

**`prompt.md`:**
- Clear, prose-only instruction to query ChromaDB for the canary token
- Explicitly forbids reading files or browsing the web
- Asks for explicit failure reporting if token cannot be retrieved

### 3. ✅ Updated `bench/README.md`

- Added `isolated_workdir?` to the task.json format spec (line 50)
- Added documentation explaining the new field (lines 58-60)
- Clarified that this applies to qa tasks only

### 4. ✅ Created `SEED_FIXTURE.sh` helper script

- Documents the one-time seeding process
- Generates a random 8-character hex token
- Provides the exact command to run qa_capture.py
- Stores fixture in ChromaDB with tags `bench-fixture,isolated-recall,task-015` for later cleanup

## What still needs to be done (external, one-time)

### Seed the fixture into ChromaDB

Run the seeding script once to populate the fixture:

```bash
bash bench/tasks/task-015-isolated-kb-recall/SEED_FIXTURE.sh
```

This will:
1. Generate a random token like `QA-ISOLATE-a1b2c3d4`
2. Store it in `~/.claude/chroma` under the qa-knowledge collection
3. Tag it with `bench-fixture`, `isolated-recall`, `task-015` for easy cleanup
4. Print the generated token (update `task.json` `expect` array if you want exact matching instead of prefix matching)

## Verification tests (requires fixture to be seeded first)

After running the SEED_FIXTURE.sh script:

```bash
# Test 1: clean profile should fail (no ChromaDB access, empty workdir)
python3 bench.py tasks/task-015-isolated-kb-recall --profiles clean

# Test 2: lean profile should fail (no qa-agent skill)
python3 bench.py tasks/task-015-isolated-kb-recall --profiles lean

# Test 3: marvin profile should pass (has qa-agent skill + ChromaDB access)
python3 bench.py tasks/task-015-isolated-kb-recall --profiles marvin
```

## Key design decisions

1. **Empty workdir for all profiles**: Isolated qa tasks get the same temp directory treatment as fs tasks. This removes the confound that "maybe marvin's cwd just happened to have more files."

2. **No `--permission-mode bypassPermissions` for isolated tasks**: Permission handling stays on so `disallow_tools` continues to gate Read/Glob/Grep structurally.

3. **Prefix matching in `expect`**: Using `["QA-ISOLATE-"]` allows the fixture to be any token starting with this prefix, making verification robust even if the exact token isn't perfectly generated.

4. **ChromaDB path is cwd-independent**: `~/.claude/chroma` is an absolute path, so running in a temp workdir doesn't affect marvin's ability to query it via the qa-agent skill.

5. **No project-scoped memory in temp dir**: A brand-new empty temp dir has no `MEMORY.md` or `.claude/` subdirectory, isolating the qa-agent → `qa_query.py` → ChromaDB path as the only answer channel.

## Test expectations

- **clean/lean**: Fail — empty workdir + no tool access + no qa-agent skill = cannot produce token
- **marvin**: Pass — qa-agent skill triggers on "query the knowledge base" → runs `qa_query.py` against `~/.claude/chroma` → retrieves token

This configuration proves marvin's pass is attributable to **ChromaDB retrieval specifically**, not to:
- Ambient project memory (`MEMORY.md` — can't exist in temp dir)
- File access (`Read/Glob/Grep` — disallowed)
- Web search (`WebSearch/WebFetch` — disallowed)
- Training data (unguessable random token)

## Files modified

1. `bench/bench.py` — Added isolated_workdir support to run_once function
2. `bench/README.md` — Documented the new field
3. `bench/tasks/task-015-isolated-kb-recall/task.json` — New task definition
4. `bench/tasks/task-015-isolated-kb-recall/prompt.md` — Task prompt
5. `bench/tasks/task-015-isolated-kb-recall/SEED_FIXTURE.sh` — Seeding helper script

## Next steps

1. Run `bash bench/tasks/task-015-isolated-kb-recall/SEED_FIXTURE.sh` to seed the fixture
2. Run verification tests as documented above
3. Commit changes to the repo
4. Optional: Update `task.json` `expect` array with the exact token generated by the script if you want stricter matching
