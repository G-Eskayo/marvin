"""Tests for route.py table output and function naming."""
import sys
import io
import subprocess
from pathlib import Path

# Add the scripts directory to path so we can import route
sys.path.insert(0, str(Path(__file__).parent.parent))

import route


def test_print_table_exists():
    """Test that print_table function exists and is callable."""
    assert hasattr(route, 'print_table'), "print_table function should exist"
    assert callable(route.print_table), "print_table should be callable"


def test_print_table_proper_does_not_exist():
    """Test that the old print_table_proper function does not exist (after refactoring)."""
    # This test expects the refactoring to be complete
    assert not hasattr(route, 'print_table_proper'), (
        "print_table_proper should not exist after refactoring - use print_table instead"
    )


def test_print_table_output_format():
    """Test that print_table outputs a properly formatted table."""
    output = io.StringIO()
    sys.stdout = output
    try:
        route.print_table()
    finally:
        sys.stdout = sys.__stdout__

    result = output.getvalue()

    # Check that the output contains all intent names
    assert 'recall' in result, "Output should contain 'recall' intent"
    assert 'research' in result, "Output should contain 'research' intent"
    assert 'coding' in result, "Output should contain 'coding' intent"
    assert 'architecture' in result, "Output should contain 'architecture' intent"

    # Check that it contains column headers
    assert 'INTENT' in result, "Output should contain INTENT header"
    assert 'PROFILE' in result, "Output should contain PROFILE header"
    assert 'MODEL' in result, "Output should contain MODEL header"

    # Check for separator line (row of dashes)
    assert '---' in result, "Output should contain separator line with dashes"

    # Check for keyword threshold info
    assert 'Keyword threshold' in result, "Output should mention keyword threshold"
    assert 'MIN_HITS' in result or '2' in result or 'override default' in result


def test_print_table_includes_all_intents():
    """Test that print_table includes all intents from INTENTS dict."""
    output = io.StringIO()
    sys.stdout = output
    try:
        route.print_table()
    finally:
        sys.stdout = sys.__stdout__

    result = output.getvalue()

    # Verify each intent and its properties are in output
    for intent_name, intent_config in route.INTENTS.items():
        assert intent_name in result, f"Intent '{intent_name}' should be in output"
        assert intent_config['alias'] in result, f"Alias '{intent_config['alias']}' should be in output"


def test_route_intents_are_valid():
    """Test that all intents have required keys."""
    required_keys = {'profile', 'model', 'config_dir', 'alias', 'keywords', 'why', 'savings'}

    for intent_name, intent_config in route.INTENTS.items():
        assert isinstance(intent_config, dict), f"Intent '{intent_name}' should be a dict"
        for key in required_keys:
            assert key in intent_config, f"Intent '{intent_name}' missing required key '{key}'"


def test_subprocess_no_argument_fallback():
    """Test that route.py with no arguments calls print_table (via subprocess)."""
    script_path = Path(__file__).parent.parent / 'route.py'

    # Run route.py with no arguments - should output the table
    result = subprocess.run(
        ['python3', str(script_path)],
        cwd=script_path.parent,
        capture_output=True,
        text=True,
        timeout=5
    )

    output = result.stdout

    # Should succeed
    assert result.returncode == 0, f"route.py with no args failed: {result.stderr}"

    # Should contain table output
    assert 'INTENT' in output, "No-argument call should output table"
    assert 'recall' in output, "Table should contain 'recall' intent"
    assert 'Keyword threshold' in output, "Table should mention keyword threshold"


def test_print_table_golden_output():
    """Test print_table output against golden fixture via subprocess (if available)."""
    fixture_path = Path(__file__).parent / 'fixtures' / 'table_output.txt'

    if not fixture_path.exists():
        # Skip this test if fixture doesn't exist
        return

    script_path = Path(__file__).parent.parent / 'route.py'

    # Run route.py --table as subprocess
    result = subprocess.run(
        ['python3', str(script_path), '--table'],
        cwd=script_path.parent,
        capture_output=True,
        text=True,
        timeout=5
    )

    assert result.returncode == 0, f"route.py --table failed: {result.stderr}"

    output = result.stdout
    expected = fixture_path.read_text()

    # Allow for some whitespace variations
    result_lines = [line.rstrip() for line in output.split('\n')]
    expected_lines = [line.rstrip() for line in expected.split('\n')]

    assert result_lines == expected_lines, (
        f"Output does not match fixture.\nExpected:\n{expected}\n\nGot:\n{output}"
    )


def test_print_table_idempotency():
    """Test that running route.py --table twice produces identical output."""
    script_path = Path(__file__).parent.parent / 'route.py'

    # Run route.py --table twice
    result1 = subprocess.run(
        ['python3', str(script_path), '--table'],
        cwd=script_path.parent,
        capture_output=True,
        text=True,
        timeout=5
    )

    result2 = subprocess.run(
        ['python3', str(script_path), '--table'],
        cwd=script_path.parent,
        capture_output=True,
        text=True,
        timeout=5
    )

    assert result1.returncode == 0, f"First run failed: {result1.stderr}"
    assert result2.returncode == 0, f"Second run failed: {result2.stderr}"

    # Outputs should be identical
    assert result1.stdout == result2.stdout, (
        "Idempotency check failed: two consecutive runs produced different output"
    )
