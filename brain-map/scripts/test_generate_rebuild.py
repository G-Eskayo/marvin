#!/usr/bin/env python3
"""Rebuild the index.html as part of test setup."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import generate  # noqa: E402

def test_rebuild_index():
    """Regenerate index.html with current code."""
    generate.main()
    # Verify output files were created
    assert generate.OUTPUT_PATH.exists(), f"Output file not created: {generate.OUTPUT_PATH}"
    assert generate.TREE_DATA_PATH.exists(), f"Tree data file not created: {generate.TREE_DATA_PATH}"
