# Python Stack

## Lessons

### Pinned dependencies
All dependencies must use pinned versions in `requirements.txt` (every line must have `==`). Unpinned dependencies (`>=`, `~=`, or no version constraint) cause CI failures when new releases break compatibility. If using `pyproject.toml` instead, a lock file (`poetry.lock` or `uv.lock`) counts as pinned; CI installs from the lock file, not the toml.

Example of good practice:
```
pytest==7.4.3
requests==2.31.0
```

Never use `>=` or `~=` in CI — that defeats the purpose of CI: to verify against known, tested versions.

### Machine-local test references
Tests must not reference machine-local paths like `Path.home()`, `expanduser("~")`, `~/.claude`, or `os.environ["HOME"]`. These fail in CI where the home directory does not exist or has different contents.

Instead:
- Use temporary directories: `import tempfile; with tempfile.TemporaryDirectory() as tmpdir:`
- Use test fixtures or mocks for configuration
- For config files, use relative paths or environment variables that CI can control

Example of bad practice:
```python
config_path = Path.home() / ".claude" / "config.json"  # ❌ fails in CI
```

Example of good practice:
```python
config_path = Path(os.environ.get("CONFIG_DIR", "/tmp")) / "config.json"  # ✅ works in CI
```

Marvin itself violated both of these rules in early versions (see ADR 0036-D4 for the full analysis).
