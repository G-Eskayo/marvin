"""pytest configuration for bench lib tests.

Sets up paths and fixtures for testing build measurement and energy capture modules.
"""
import sys
from pathlib import Path

# Add parent lib directory to path so tests can import modules
bench_lib = Path(__file__).parent.parent
sys.path.insert(0, str(bench_lib))

import pytest


@pytest.fixture
def tmp_python_env(tmp_path):
    """Fixture providing a temporary Python project directory."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    # Create a minimal Python project
    (project_dir / "setup.py").write_text(
        "from setuptools import setup\nsetup(name='test', version='0.1')"
    )
    (project_dir / "src").mkdir()
    (project_dir / "src" / "__init__.py").write_text("")

    return project_dir
