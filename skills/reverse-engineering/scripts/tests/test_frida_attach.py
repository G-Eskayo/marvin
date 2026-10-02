"""Tests for frida_attach.py. Run via:
    ~/.agents/venv/bin/python -m pytest skills/reverse-engineering/scripts/tests/test_frida_attach.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import pytest
from frida_attach import check_authorization, check_frida, load_script


# ── check_authorization ─────────────────────────────────────────────────────

def test_check_authorization_requires_flag():
    """Authorization gate should reject missing flag."""
    class Args:
        i_own_this_target = False

    args = Args()
    assert check_authorization(args) is False


def test_check_authorization_accepts_flag():
    """Authorization gate should accept when flag is set."""
    class Args:
        i_own_this_target = True

    args = Args()
    assert check_authorization(args) is True


def test_check_authorization_missing_attribute():
    """Authorization gate should reject when attribute missing entirely."""
    class Args:
        pass

    args = Args()
    assert check_authorization(args) is False


# ── check_frida ────────────────────────────────────────────────────────────

def test_check_frida_installed():
    """Should return True when Frida is installed."""
    # Frida is imported inside check_frida(), so we mock at sys.modules level
    mock_frida = MagicMock()
    with patch.dict('sys.modules', {'frida': mock_frida}):
        result = check_frida()
    assert result is True


def test_check_frida_not_installed():
    """Should return False when Frida is not installed."""
    with patch.dict('sys.modules', {'frida': None}):
        # Simulate ImportError by mocking the import
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == 'frida':
                raise ImportError("No module named 'frida'")
            return real_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=mock_import):
            result = check_frida()
    assert result is False


# ── load_script ────────────────────────────────────────────────────────────

def test_load_script_exists():
    """Should load script content when file exists."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
        f.write('console.log("test");')
        temp_path = f.name

    try:
        content = load_script(temp_path)
        assert content == 'console.log("test");'
    finally:
        Path(temp_path).unlink()


def test_load_script_not_found():
    """Should raise FileNotFoundError when script doesn't exist."""
    with pytest.raises(FileNotFoundError, match="Script not found"):
        load_script('/nonexistent/path/to/script.js')


def test_load_script_empty():
    """Should load empty script file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
        f.write('')
        temp_path = f.name

    try:
        content = load_script(temp_path)
        assert content == ''
    finally:
        Path(temp_path).unlink()


def test_load_script_multiline():
    """Should load multi-line script correctly."""
    script_content = '''function hook_malloc(lib) {
    Interceptor.attach(lib.symbols.malloc, {
        onEnter: function(args) {
            console.log("malloc called");
        }
    });
}'''

    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
        f.write(script_content)
        temp_path = f.name

    try:
        content = load_script(temp_path)
        assert content == script_content
    finally:
        Path(temp_path).unlink()
