#!/usr/bin/env python3
"""Tests for variable tracker."""

import pytest
import tempfile
import json
from pathlib import Path
import sys

# Add parent scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from track_vars import PythonVariableTracker, TextVariableTracker


@pytest.fixture
def python_tracker():
    return PythonVariableTracker()


@pytest.fixture
def text_tracker():
    return TextVariableTracker()


class TestPythonTracker:

    def test_simple_assignment(self, python_tracker, tmp_path):
        """Test tracking simple variable assignment."""
        code = """x = 5
print(x)
"""
        file = tmp_path / "test.py"
        file.write_text(code)

        result = python_tracker.track_file(str(file))
        assert "module" in result
        assert "x" in result["module"]
        assert result["module"]["x"]["declared_line"] == 1
        assert 2 in result["module"]["x"]["uses"]

    def test_annotated_assignment(self, python_tracker, tmp_path):
        """Test tracking annotated variable assignment."""
        code = """count: int = 10
print(count)
"""
        file = tmp_path / "test.py"
        file.write_text(code)

        result = python_tracker.track_file(str(file))
        assert result["module"]["count"]["type"] == "int"
        assert result["module"]["count"]["declared_line"] == 1

    def test_reassignment(self, python_tracker, tmp_path):
        """Test tracking variable reassignment."""
        code = """x = 1
x = 2
print(x)
"""
        file = tmp_path / "test.py"
        file.write_text(code)

        result = python_tracker.track_file(str(file))
        assert result["module"]["x"]["declared_line"] == 1
        assert 2 in result["module"]["x"]["uses"]
        assert 3 in result["module"]["x"]["uses"]

    def test_augmented_assignment(self, python_tracker, tmp_path):
        """Test tracking augmented assignment."""
        code = """count = 0
count += 1
"""
        file = tmp_path / "test.py"
        file.write_text(code)

        result = python_tracker.track_file(str(file))
        assert "count" in result["module"]
        assert result["module"]["count"]["declared_line"] == 1

    def test_for_loop_target(self, python_tracker, tmp_path):
        """Test tracking for-loop target as variable."""
        code = """for item in range(5):
    print(item)
"""
        file = tmp_path / "test.py"
        file.write_text(code)

        result = python_tracker.track_file(str(file))
        assert "item" in result["module"]
        assert 2 in result["module"]["item"]["uses"]

    def test_function_parameter_scope(self, python_tracker, tmp_path):
        """Test tracking function parameters in separate scope."""
        code = """x = 10

def foo(x):
    print(x)

foo(x)
"""
        file = tmp_path / "test.py"
        file.write_text(code)

        result = python_tracker.track_file(str(file))
        assert "x" in result["module"]
        assert result["module"]["x"]["declared_line"] == 1

        # Find function scope
        func_scopes = [k for k in result.keys() if k.startswith("function:")]
        assert len(func_scopes) == 1
        func_scope = func_scopes[0]
        assert "x" in result[func_scope]
        assert result[func_scope]["x"]["declared_line"] == 3

    def test_unused_variable(self, python_tracker, tmp_path):
        """Test tracking unused variable."""
        code = """unused = 42
used = 1
print(used)
"""
        file = tmp_path / "test.py"
        file.write_text(code)

        result = python_tracker.track_file(str(file))
        assert result["module"]["unused"]["uses"] == []
        assert len(result["module"]["used"]["uses"]) > 0

    def test_with_statement(self, python_tracker, tmp_path):
        """Test tracking with statement target."""
        code = """with open('file.txt') as f:
    data = f.read()
    print(data)
"""
        file = tmp_path / "test.py"
        file.write_text(code)

        result = python_tracker.track_file(str(file))
        assert "f" in result["module"]
        assert "data" in result["module"]


class TestTextTracker:

    def test_javascript_declaration(self, text_tracker, tmp_path):
        """Test approximate tracking in JavaScript."""
        code = """const count = 0;
console.log(count);
"""
        file = tmp_path / "test.js"
        file.write_text(code)

        result = text_tracker.track_file(str(file))
        assert "module" in result
        assert "count" in result["module"]
        assert result["module"]["count"]["declared_line"] == 1
        assert "unknown (regex-detected)" in result["module"]["count"]["type"]

    def test_typescript_detection(self, text_tracker, tmp_path):
        """Test approximate tracking in TypeScript."""
        code = """let userName = "John";
alert(userName);
"""
        file = tmp_path / "test.ts"
        file.write_text(code)

        result = text_tracker.track_file(str(file))
        assert "userName" in result["module"]


class TestJSONOutput:

    def test_json_output_format(self, python_tracker, tmp_path):
        """Test JSON output format."""
        code = """x = 1
print(x)
"""
        file = tmp_path / "test.py"
        file.write_text(code)

        result = python_tracker.track_file(str(file))

        # Simulate JSON output
        json_data = {}
        for scope_name, variables in result.items():
            json_data[scope_name] = {}
            for var_name, info in variables.items():
                json_data[scope_name][var_name] = {
                    "declared_line": info["declared_line"],
                    "type": info["type"],
                    "uses": sorted(set(info["uses"]))
                }

        # Should be JSON-serializable
        json_str = json.dumps(json_data)
        parsed = json.loads(json_str)
        assert "module" in parsed
        assert "x" in parsed["module"]


def test_cli_help(tmp_path):
    """Test CLI help output."""
    import subprocess
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent.parent / "track_vars.py"), "--help"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "Track variable declarations" in result.stdout


def test_cli_basic(tmp_path):
    """Test CLI basic invocation."""
    code = """x = 1
print(x)
"""
    file = tmp_path / "test.py"
    file.write_text(code)

    import subprocess
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent.parent / "track_vars.py"), str(file)],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "test.py" in result.stdout
    assert "x" in result.stdout


def test_cli_json_output(tmp_path):
    """Test CLI JSON output."""
    code = """x = 1
print(x)
"""
    file = tmp_path / "test.py"
    file.write_text(code)

    import subprocess
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent.parent / "track_vars.py"), str(file), "--json"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert str(file) in data


def test_cli_var_filter(tmp_path):
    """Test CLI variable filtering."""
    code = """x = 1
y = 2
print(x)
print(y)
"""
    file = tmp_path / "test.py"
    file.write_text(code)

    import subprocess
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent.parent / "track_vars.py"), str(file), "--var", "x"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "x" in result.stdout
    assert "y" not in result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
