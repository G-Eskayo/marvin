# Test Defect Fixes Summary

Fixed 7 must-fix code review defects in `lib/tests/test_work_loop_e2e.py`:

## Defect 1: Fake gh crashes on stdin body (line 42)
**Issue:** `--body-file -` (stdin) made fake gh crash with FileNotFoundError.
**Fix:** Guard stdin case with `val if val != '-' else None` check
```python
# Before:
body_file = a[i + 1]

# After:
val = a[i + 1]
body_file = val if val != '-' else None
```

## Defect 2: Incorrect `-F` file path heuristic (line 47)
**Issue:** `-F` heuristic treated `/` as file marker, breaking URLs like `-F url=https://...`
**Fix:** Use `@` instead (actual syntax for file fields is `key=@path`)
```python
# Before:
if '/' in val or os.path.exists(val):

# After:
if '@' in val or os.path.exists(val):
```

## Defect 3: `_od()` PATH and env setup (line 103-109)
**Issue:** 
- PATH had `GATE.parent` first, so owner_decisions.py bypassed fake gh
- Missing `MARVIN_PULL_ONLY=0` for deterministic CI behavior
- Used bare `python3` instead of venv interpreter

**Fix:** 
- Put `realbin` first on PATH (fake gh only)
- Add `MARVIN_PULL_ONLY=0`
- Use venv python with fallback to current interpreter
```python
# Before:
env = {"PATH": f"{GATE.parent}:{realbin}:/usr/bin:/bin", ...}
return subprocess.run(["python3", ...], env=env, ...)

# After:
env = {"PATH": f"{realbin}:/usr/bin:/bin", ..., "MARVIN_PULL_ONLY": "0", ...}
venv_python = ROOT / "venv" / "bin" / "python"
if not venv_python.exists():
    venv_python = Path(sys.executable)
return subprocess.run([str(venv_python), ...], env=env, ...)
```

## Defect 4: Weak assertion in overdue detection (line 346)
**Issue:** Assertion `assert "would file" in ... or res.stdout` passed on any non-empty output
**Fix:** Explicitly check that no `issue create` calls reached fake GitHub (verify --dry-run)
```python
# Before:
assert "would file" in res.stdout or "skipped" in res.stdout or res.stdout

# After:
reached = _reached(tmp_path)
assert not any(c["argv"][:2] == ["issue", "create"] for c in reached)
```

## Defect 5: Invalid SHA and missing routes (line 267)
**Issue:** 
- SHA was 41 chars instead of valid 40 chars
- No route for compare API calls, so UI files never detected

**Fix:**
- Use valid 40-char SHA
- Add routes for both main...x and sha...x compare calls
```python
# Before:
body = "...abc1234567890abcdef1234567890abcdef123456/assets..."  # 41 chars

# After:
sha = "abc1234567890abcdef1234567890abcdef12345"  # 40 chars
_route(tmp_path, {
    "repos/o/r/compare/main...x": {...},
    f"repos/o/r/compare/{sha}...x": {...}
})
```

## Defect 6: Weak error assertion (line 232)
**Issue:** Test only asserted `returncode != 0` without checking specific error reason
**Fix:** Assert specific error code "BAD_IMAGE_LINK"
```python
# Before:
assert p.returncode != 0, f"expected failure, got: {p.stderr}"

# After:
assert p.returncode != 0, f"expected failure, got: {p.stderr}"
assert "BAD_IMAGE_LINK" in p.stderr, f"expected BAD_IMAGE_LINK error, got: {p.stderr}"
```

## Defect 7: Missing bare-commit test case (line 420)
**Issue:** No test for the design rule that a bare commit alone doesn't count (marvin#733)
**Fix:** Added new test `test_i3_bare_commit_without_addressed_marker_still_waits`

The test verifies that a PR with:
- Decisions posted by owner
- A commit made after decisions
- BUT no addressed marker reply

Still appears in the waiting list (bare commit alone doesn't address decisions).

## Test Results
All 30 tests pass:
- 20 I2 (decisions format) tests ✓
- 5 I1 (UI images) tests ✓
- 5 I3 (owner decisions) tests ✓

Each defect fix is now covered by a passing test that would catch regressions.
