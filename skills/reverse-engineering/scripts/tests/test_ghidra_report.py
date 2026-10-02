"""Tests for ghidra_report.py. Run via:
    ~/.agents/venv/bin/python -m pytest skills/reverse-engineering/scripts/tests/test_ghidra_report.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import json

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import pytest
from ghidra_report import check_authorization, generate_ghidra_script, run_ghidra_analysis


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


# ── generate_ghidra_script ──────────────────────────────────────────────────

def test_generate_ghidra_script_basic():
    """Script generation should produce valid Jython code."""
    script = generate_ghidra_script()
    assert isinstance(script, str)
    assert 'json.dumps' in script
    assert 'currentProgram' in script


def test_generate_ghidra_script_with_function():
    """Script should accept function_name parameter."""
    script = generate_ghidra_script(function_name='main')
    assert isinstance(script, str)
    # Script is built regardless of function_name (actual decompilation happens in Ghidra)


def test_generate_ghidra_script_with_all_functions():
    """Script should accept all_functions parameter."""
    script = generate_ghidra_script(all_functions=True)
    assert isinstance(script, str)


# ── run_ghidra_analysis (mocked subprocess) ─────────────────────────────────

@patch('ghidra_report.subprocess.run')
@patch('ghidra_report.find_ghidra')
def test_run_ghidra_analysis_calls_analyzeheadless(mock_find_ghidra, mock_subprocess):
    """Calling run_ghidra_analysis should invoke analyzeHeadless."""
    # Mock Ghidra installation
    mock_find_ghidra.return_value = '/opt/ghidra/support/analyzeHeadless'

    # Mock subprocess output
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "binary": "test",
        "arch": "x86-64",
        "entry_point": "0x400000",
        "functions": [],
        "strings": [],
        "imports": []
    })
    mock_result.stderr = ""
    mock_subprocess.return_value = mock_result

    # Patch Path.exists() to return True for the binary
    with patch('pathlib.Path.exists', return_value=True):
        with patch('pathlib.Path.mkdir'):
            with patch('pathlib.Path.write_text'):
                with patch('pathlib.Path.unlink'):
                    result = run_ghidra_analysis(
                        binary_path='/tmp/test_binary',
                        ghidra_project_dir='/tmp/ghidra'
                    )

    # Verify subprocess was called
    assert mock_subprocess.called
    call_args = mock_subprocess.call_args[0][0]
    assert 'analyzeHeadless' in call_args[0]
    assert '-import' in call_args
    # Path may be resolved to /private/tmp on macOS
    assert any('test_binary' in str(arg) for arg in call_args)

    # Verify output structure
    assert result['arch'] == 'x86-64'
    assert result['entry_point'] == '0x400000'


@patch('ghidra_report.find_ghidra')
def test_run_ghidra_analysis_binary_not_found(mock_find_ghidra):
    """Should raise FileNotFoundError for missing binary."""
    mock_find_ghidra.return_value = '/opt/ghidra/support/analyzeHeadless'

    with pytest.raises(FileNotFoundError):
        run_ghidra_analysis(binary_path='/nonexistent/binary')


@patch('ghidra_report.subprocess.run')
@patch('ghidra_report.find_ghidra')
def test_run_ghidra_analysis_subprocess_failure(mock_find_ghidra, mock_subprocess):
    """Should raise RuntimeError if analyzeHeadless fails."""
    mock_find_ghidra.return_value = '/opt/ghidra/support/analyzeHeadless'

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "Failed to import binary"
    mock_subprocess.return_value = mock_result

    with patch('pathlib.Path.exists', return_value=True):
        with patch('pathlib.Path.mkdir'):
            with patch('pathlib.Path.write_text'):
                with patch('pathlib.Path.unlink'):
                    with pytest.raises(RuntimeError, match="Ghidra analysis failed"):
                        run_ghidra_analysis(binary_path='/tmp/test_binary')


@patch('ghidra_report.subprocess.run')
@patch('ghidra_report.find_ghidra')
def test_run_ghidra_analysis_timeout(mock_find_ghidra, mock_subprocess):
    """Should raise RuntimeError if analysis times out."""
    import subprocess
    mock_find_ghidra.return_value = '/opt/ghidra/support/analyzeHeadless'
    mock_subprocess.side_effect = subprocess.TimeoutExpired('analyzeHeadless', 300)

    with patch('pathlib.Path.exists', return_value=True):
        with patch('pathlib.Path.mkdir'):
            with patch('pathlib.Path.write_text'):
                with patch('pathlib.Path.unlink'):
                    with pytest.raises(RuntimeError, match="timed out"):
                        run_ghidra_analysis(binary_path='/tmp/test_binary', ghidra_project_dir='/tmp/ghidra')


@patch('ghidra_report.subprocess.run')
@patch('ghidra_report.find_ghidra')
def test_run_ghidra_analysis_output_to_file(mock_find_ghidra, mock_subprocess):
    """Should write output to file when --output is specified."""
    mock_find_ghidra.return_value = '/opt/ghidra/support/analyzeHeadless'

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({
        "binary": "test",
        "arch": "x86-64",
        "entry_point": "0x400000",
        "functions": [],
        "strings": [],
        "imports": []
    })
    mock_result.stderr = ""
    mock_subprocess.return_value = mock_result

    with patch('pathlib.Path.exists', return_value=True):
        with patch('pathlib.Path.mkdir'):
            with patch('pathlib.Path.write_text') as mock_write:
                with patch('pathlib.Path.unlink'):
                    run_ghidra_analysis(
                        binary_path='/tmp/test_binary',
                        output_file='/tmp/output.json',
                        ghidra_project_dir='/tmp/ghidra'
                    )

    # Verify write_text was called for output file
    assert mock_write.called
