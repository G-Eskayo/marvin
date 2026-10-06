# Python Stack

## Honesty checks

### Pinned dependencies
Python projects must have a pinned `requirements.txt` or exact version pins in `pyproject.toml`. Unpinned or missing dependency files lead to non-reproducible environments and CI failures. The plan stage detects this (ADR 0036 D4) and blocks CI generation until dependencies are explicitly pinned.

### Machine-local test isolation
Tests that read `~/.claude`, `$HOME`, or other machine-local state will fail in CI. The plan stage scans test files for markers like `Path.home()`, `expanduser()`, and `~/.claude`-style paths (ADR 0036 D4), and blocks CI generation if found. Tests must use fixtures or environment variables instead.

## Test command
The standard test command is `pytest`. If tests exist but aren't named `test_*.py` or `*_test.py`, they will not run automatically.

## References
- ADR 0036 D4: Plan stage honesty checks for unpinned requirements and machine-local test reads
- CONTEXT.md: Marvin's own test suite example (machines-local state in lib/tests/)
