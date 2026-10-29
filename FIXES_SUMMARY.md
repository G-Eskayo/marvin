# Code Review Defect Fixes Summary

## Overview
This document summarizes the fixes for 7 must-fix defects found in the code review of the spec_search implementation.

## Defect 1: measure_setup — ERROR/TIMEOUT/UNPARSEABLE samples not excluded
**File:** `bench/spec_search.py`  
**Lines:** 262-353

**Problem:**
- Samples with teacher_finding = ["ERROR"], ["TIMEOUT"], or ["UNPARSEABLE"] were counted as valid samples
- These represent failed teacher calls, not real findings
- Failed samples were scored as "teacher found nothing", allowing students that return nothing to get credit
- This made the accuracy metric meaningless for the search loop

**Fix:**
- Added check to skip ERROR/TIMEOUT/UNPARSEABLE samples BEFORE incrementing total
- Only valid samples (with real findings or legitimately no findings) contribute to accuracy calculation
- Changed line 178 from `total += 1` to happen after the error check

**Before:**
```python
for sample in benchmark:
    total += 1  # Counted error samples
    ...
    if sample["teacher_finding"][0] in ("UNPARSEABLE", "ERROR", "TIMEOUT"):
        # But then never skipped them
```

**After:**
```python
for sample in benchmark:
    # Skip samples with error findings first
    if len(teacher_finding) > 0 and teacher_finding[0] in ("UNPARSEABLE", "ERROR", "TIMEOUT"):
        continue
    total += 1  # Only count valid samples
```

## Defect 2: run_baseline_measurement — Same ERROR/TIMEOUT/UNPARSEABLE issue
**File:** `bench/spec_search.py`  
**Lines:** 131-205

**Problem:** Same as Defect 1 — error samples were counted toward accuracy.

**Fix:** Applied the same fix as Defect 1 (skip error samples before incrementing total).

## Defect 3: build_benchmark_from_samples — No chat_fn injection point
**File:** `bench/spec_search.py`  
**Lines:** 69-127

**Problem:**
- `extract_structure()` was called without any way to inject a test fake
- Tests couldn't control or avoid real Ollama calls
- Made it impossible to test benchmark building without a real model

**Fix:**
- Added `chat_fn: callable = None` parameter to function signature (line 72)
- Updated docstring to document the parameter (line 76)
- Passed chat_fn to extract_structure call (line 108): `extract_structure(..., chat_fn=chat_fn)`
- Now tests can inject a fake chat function to avoid real network calls

## Defect 4: classify_and_extract — Hard-exit on missing qwen2.5:14b
**File:** `bench/benchmark_from_chroma.py`  
**Lines:** 120-136

**Problem:**
- Script checked if qwen2.5:14b was loaded and called `sys.exit()` if missing
- Per #563, qwen2.5:14b is deleted and not available
- Design says "resident-only, no re-pull", so the benchmark builder couldn't run at all
- Hard-exit happens before we even get to import logic_auditor

**Fix:**
- Removed the hard-exit check
- Changed to rely on logic_auditor's own model_registry to resolve the classification capability
- If logic_auditor can't find a model, it will raise its own error with better context
- Updated docstring to clarify that classification uses "resident model" not specifically qwen2.5:14b

**Before:**
```python
if not _can_load_model("qwen2.5:14b"):
    sys.exit("Model qwen2.5:14b is not loaded...")
```

**After:**
- Removed the check entirely; let logic_auditor.classify_paper_type() use its own capability resolution

## Defect 5: get_teacher_judgments — Tools not disabled for untrusted input
**File:** `bench/benchmark_from_chroma.py`  
**Lines:** 187-268

**Problem:**
- Called `claude -p` without `--tools ""` flag
- The prompt is built from untrusted extraction text (papers submitted by users)
- An adversarial paper abstract could include prompt injection that causes claude to run tools (read files, etc.)
- The output would be written into the benchmark JSON

**Fix:**
- Added `--tools ""` flag to the subprocess.run call (line 239)
- Now: `["claude", "-p", "--output-format", "text", "--tools", ""]`
- Disables ALL tools for this call, preventing injection attacks

## Defect 6: get_papers_from_chroma — None metadata not handled
**File:** `bench/benchmark_from_chroma.py`  
**Lines:** 36-96

**Problem:**
- Chroma can return `None` for absent metadata entries
- `metadata.get("title")` called on None raises AttributeError
- This crashed the entire benchmark build if a document had missing metadata

**Fix:**
- Added check after retrieving metadata: `if metadata is None: metadata = {}`
- Now: `metadata = metadatas[i] if i < len(metadatas) else {}` followed by `if metadata is None: metadata = {}`
- Gracefully handles missing metadata by treating it as an empty dict

## Defect 7: metrics_registry.record — Concurrency issue with flock
**File:** `bench/lib/metrics_registry.py`  
**Lines:** 67-101

**Problem:**
- Lock was only held during the final write (line 101)
- Read → append → write sequence happened without lock:
  - Thread 1 reads file → [snap1]
  - Thread 2 reads file → [snap1] (same state)
  - Thread 1 appends snap2 → [snap1, snap2]
  - Thread 2 appends snap3 → [snap1, snap3]
  - Thread 1 writes [snap1, snap2]
  - Thread 2 writes [snap1, snap3] (overwrites Thread 1's data)
- Two concurrent `record()` calls lose one snapshot

**Fix:**
- Moved lock acquisition to BEFORE the read operation
- Lock is now held for the entire read → append → write sequence
- No race conditions possible: only one thread can run this sequence at a time

**Before:**
```python
if snapshot_file.exists():
    snapshots = json.loads(snapshot_file.read_text())  # UNLOCKED
snapshots.append(snapshot)
_write_atomic(snapshot_file, json.dumps(snapshots))  # Lock only in _write_atomic
```

**After:**
```python
with open(lock_path, "w") as lock_file:
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)  # Lock FIRST
    if snapshot_file.exists():
        snapshots = json.loads(snapshot_file.read_text())  # LOCKED
    snapshots.append(snapshot)
    _write_atomic(snapshot_file, json.dumps(snapshots))  # Still locked
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
```

## Impact

These fixes unblock the spec_search implementation:

1. **Defects 1-2:** The search loop was stuck because every edit measured the same accuracy (error samples counted consistently). Now the search can detect real accuracy differences and accept improvements.

2. **Defect 3:** Tests can now inject fakes, making benchmark building testable without real models.

3. **Defect 4:** The benchmark builder won't hard-exit on missing models; it delegates to logic_auditor's capability resolution.

4. **Defect 5:** Security vulnerability plugged — untrusted paper abstracts can no longer inject commands to claude.

5. **Defect 6:** Robustness improved — missing metadata no longer crashes the builder.

6. **Defect 7:** Concurrency correctness improved — concurrent benchmark runs won't corrupt the metrics file.

## Testing

Verification scripts have been added:
- `verify_fixes.py` — Verifies all fixes are syntactically correct
- `test_search_loop.py` — Tests that the search loop actually works with the fixes

Run them with:
```bash
python3 verify_fixes.py
python3 test_search_loop.py
```
