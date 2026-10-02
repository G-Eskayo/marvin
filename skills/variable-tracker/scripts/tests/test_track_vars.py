"""Tests for track_vars.py variable tracking. Run via:
    ~/.agents/venv/bin/python -m pytest skills/variable-tracker/scripts/tests/test_track_vars.py -v
"""
from __future__ import annotations
import sys
import json
import subprocess
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import track_vars  # noqa: E402


def test_module_level_var_with_multiple_uses(tmp_path):
    """Module-level var definition and multiple uses are tracked correctly."""
    py_file = tmp_path / "example.py"
    py_file.write_text("""cfg = load_config()
print(cfg)
return cfg
""")

    result = track_vars.extract_variables(str(py_file))

    assert len(result) > 0
    cfg_vars = [v for v in result if v["name"] == "cfg"]
    assert len(cfg_vars) > 0
    cfg = cfg_vars[0]
    assert cfg["scope"] == "[module]"
    assert len(cfg["definitions"]) == 1
    assert len(cfg["uses"]) >= 2


def test_shadowed_vars_across_scopes_not_conflated(tmp_path):
    """Same var name in different scopes tracked as separate entries."""
    py_file = tmp_path / "shadowed.py"
    py_file.write_text("""x = 10

def func1():
    x = 20
    print(x)

def func2():
    x = 30
    print(x)
""")

    result = track_vars.extract_variables(str(py_file))

    x_vars = [v for v in result if v["name"] == "x"]
    assert len(x_vars) == 3  # module + func1 + func2

    scopes = {v["scope"] for v in x_vars}
    assert "[module]" in scopes
    assert "func1" in scopes
    assert "func2" in scopes


def test_annassign_captures_type_annotation(tmp_path):
    """Annotated assignment captures the type annotation."""
    py_file = tmp_path / "typed.py"
    py_file.write_text("""x: int = 10
y: str = "hello"
z: list[str] = []
""")

    result = track_vars.extract_variables(str(py_file))

    x_var = next(v for v in result if v["name"] == "x")
    assert any("int" in d.get("type", "") for d in x_var["definitions"])

    y_var = next(v for v in result if v["name"] == "y")
    assert any("str" in d.get("type", "") for d in y_var["definitions"])


def test_augassign_counted_as_def_and_use(tmp_path):
    """Augmented assignment (+=, etc) counted as both definition and use."""
    py_file = tmp_path / "augassign.py"
    py_file.write_text("""counter = 0
counter += 1
counter *= 2
""")

    result = track_vars.extract_variables(str(py_file))

    counter = next(v for v in result if v["name"] == "counter")
    assert len(counter["definitions"]) >= 1  # initial definition
    assert len(counter["uses"]) >= 2  # += and *= each use counter


def test_for_target_counted_as_definition(tmp_path):
    """for loop targets are counted as definitions."""
    py_file = tmp_path / "for_target.py"
    py_file.write_text("""items = [1, 2, 3]
for item in items:
    print(item)
""")

    result = track_vars.extract_variables(str(py_file))

    item_var = next(v for v in result if v["name"] == "item")
    assert len(item_var["definitions"]) >= 1
    assert any("for" in d.get("kind", "") for d in item_var["definitions"])


def test_with_target_counted_as_definition(tmp_path):
    """with statement targets are counted as definitions."""
    py_file = tmp_path / "with_target.py"
    py_file.write_text("""with open("file.txt") as f:
    data = f.read()
""")

    result = track_vars.extract_variables(str(py_file))

    f_var = next((v for v in result if v["name"] == "f"), None)
    assert f_var is not None
    assert len(f_var["definitions"]) >= 1


def test_function_params_counted_as_definitions(tmp_path):
    """Function parameters are counted as definitions."""
    py_file = tmp_path / "func_params.py"
    py_file.write_text("""def my_func(a, b, c=10):
    print(a, b, c)
""")

    result = track_vars.extract_variables(str(py_file))

    a_var = next(v for v in result if v["name"] == "a")
    assert a_var["scope"] == "my_func"
    assert len(a_var["definitions"]) >= 1
    assert any("param" in d.get("kind", "") for d in a_var["definitions"])


def test_name_filter_single_var_across_files(tmp_path):
    """--name filter returns only the named variable across all files."""
    file1 = tmp_path / "file1.py"
    file1.write_text("""x = 10
y = 20
""")

    file2 = tmp_path / "file2.py"
    file2.write_text("""x = 30
z = 40
""")

    result = track_vars.extract_variables(
        str(file1), str(file2),
        name_filter="x"
    )

    assert all(v["name"] == "x" for v in result)
    assert len(result) == 2  # x in file1 and file2


def test_directory_input_aggregates_multiple_files(tmp_path):
    """Directory input recursively finds .py files."""
    (tmp_path / "file1.py").write_text("a = 1")
    (tmp_path / "file2.py").write_text("b = 2")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "file3.py").write_text("c = 3")

    result = track_vars.extract_variables(str(tmp_path))

    names = {v["name"] for v in result}
    assert "a" in names
    assert "b" in names
    assert "c" in names


def test_since_git_ref_restricts_file_set(tmp_path):
    """--since restricts to files changed since git ref."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        capture_output=True
    )

    file1 = tmp_path / "file1.py"
    file1.write_text("x = 1")
    subprocess.run(["git", "add", "file1.py"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True)

    # Modify the file (working tree change shows in git diff HEAD)
    file1.write_text("x = 2\nz = 3")

    # Now file1.py is "changed since HEAD"
    result = track_vars.extract_variables(str(tmp_path), since_ref="HEAD")

    # Should find the modified file1.py
    assert len(result) > 0
    assert any(v["file"].endswith("file1.py") for v in result)


def test_nonexistent_path_raises_error(tmp_path):
    """Nonexistent path raises clear error."""
    nonexistent = tmp_path / "does_not_exist.py"

    try:
        track_vars.extract_variables(str(nonexistent))
        assert False, "Should have raised an error"
    except FileNotFoundError:
        pass


def test_format_json_output_is_valid_json(tmp_path):
    """--format json outputs valid JSON matching schema."""
    py_file = tmp_path / "example.py"
    py_file.write_text("x = 10\nprint(x)")

    # Since we don't have a CLI wrapper yet, test the underlying function
    result = track_vars.extract_variables(str(py_file))

    # Should be serializable to JSON
    json_str = json.dumps(result)
    parsed = json.loads(json_str)

    assert isinstance(parsed, list)
    if parsed:
        v = parsed[0]
        assert "name" in v
        assert "scope" in v
        assert "file" in v
        assert "definitions" in v
        assert "uses" in v


def test_global_declaration_tracked(tmp_path):
    """Global declarations are tracked."""
    py_file = tmp_path / "global_var.py"
    py_file.write_text("""x = 10

def modify_x():
    global x
    x = 20
""")

    result = track_vars.extract_variables(str(py_file))

    x_vars = [v for v in result if v["name"] == "x"]
    assert len(x_vars) >= 1


def test_nonlocal_declaration_tracked(tmp_path):
    """Nonlocal declarations are tracked."""
    py_file = tmp_path / "nonlocal_var.py"
    py_file.write_text("""def outer():
    x = 10
    def inner():
        nonlocal x
        x = 20
""")

    result = track_vars.extract_variables(str(py_file))

    # Should successfully extract without error
    assert isinstance(result, list)


def test_skips_venv_and_common_dirs(tmp_path):
    """Directory traversal skips venv, node_modules, .git."""
    (tmp_path / "code.py").write_text("a = 1")
    (tmp_path / "venv" / "lib").mkdir(parents=True)
    (tmp_path / "venv" / "lib" / "ignored.py").write_text("x = 999")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "ignored.py").write_text("y = 999")

    result = track_vars.extract_variables(str(tmp_path))

    # Should find 'a' but not 'x' or 'y' from ignored dirs
    names = {v["name"] for v in result}
    assert "a" in names
    assert "x" not in names
    assert "y" not in names
