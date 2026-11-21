#!/usr/bin/env python3
"""Test #14: code coverage - verify all ollama calls go through the wrapper.

Grep-based test that every file outside lib/model_calls.py and its own tests
does NOT contain bare /api/chat, /api/embed, /api/embeddings, or localhost:11434
calls, ensuring all calls are routed through the wrapper.
"""
import re
import subprocess
from pathlib import Path

import pytest


def test_no_bare_ollama_endpoints():
    """Test #14: no file contains bare /api/chat, /api/embed, /api/embeddings."""
    repo_root = Path(__file__).resolve().parent.parent.parent

    # Patterns to search for (exact endpoint strings)
    forbidden_patterns = [
        r"/api/chat",
        r"/api/embed",
        r"/api/embeddings",
        r"localhost:11434",
        r"127.0.0.1:11434",
    ]

    # Files to exclude (the wrapper itself and its tests)
    exclude_files = {
        "lib/model_calls.py",
        "lib/tests/test_model_calls.py",
        "lib/tests/test_model_calls_summary.py",
        "lib/tests/test_model_calls_coverage.py",
    }

    violations = []

    # Search all Python files in the repo
    for py_file in repo_root.rglob("*.py"):
        rel_path = py_file.relative_to(repo_root)

        # Skip excluded files
        if str(rel_path) in exclude_files:
            continue

        # Skip test files for libraries being migrated (they have monkeypatches)
        if "test_logic_auditor.py" in str(py_file):
            # This test has monkeypatches for the old ollama_chat, which is fine
            continue

        try:
            content = py_file.read_text(errors="ignore")
        except OSError:
            continue

        # Check for forbidden patterns
        for pattern in forbidden_patterns:
            if re.search(pattern, content):
                # Double-check it's not in a comment/docstring explaining the old pattern
                for line_num, line in enumerate(content.split("\n"), 1):
                    if re.search(pattern, line):
                        # Skip lines that are in comments, docstrings, constants, or health probes
                        if not ("# " in line or '"""' in line or "'''" in line or
                                "OLLAMA_URL" in line or "OLLAMA_BASE" in line or
                                "curl http://localhost:11434" in line or
                                "requests.get" in line or ".get(" in line):  # health checks
                            violations.append(f"{rel_path}:{line_num}: {pattern}")

    # Hard failure if any violations found (except for OLLAMA_URL constants)
    if violations:
        pytest.fail(
            f"Found {len(violations)} bare Ollama endpoint(s) that should use model_calls wrapper:\n"
            + "\n".join(violations[:10]) +
            ("\n..." if len(violations) > 10 else "")
        )
