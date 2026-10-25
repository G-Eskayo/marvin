"""Pytest configuration for context-sweep tests."""
import sys
from pathlib import Path

# Add scripts directory to path for imports
SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
