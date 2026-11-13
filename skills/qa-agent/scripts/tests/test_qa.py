"""Tests for qa-agent scripts. Run via:
    ~/.agents/venv/bin/python -m pytest scripts/tests/test_qa.py -v
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

import pytest

# resolve scripts/ on path
SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from qa_scan import detect_stack, extract_dependencies, extract_imports, extract_markers, analyze_python_file
from qa_capture import build_entry
from qa_query import filter_results


# ── qa_scan ──────────────────────────────────────────────────────────────────

def make_project(files: dict[str, str]) -> Path:
    tmp = Path(tempfile.mkdtemp())
    for rel, content in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp


def test_detect_stack_python():
    p = make_project({"requirements.txt": "requests==2.28\nflask>=2.0"})
    stack = detect_stack(p)
    assert "python" in stack


def test_detect_stack_javascript():
    p = make_project({"package.json": json.dumps({"dependencies": {"react": "^18"}})})
    stack = detect_stack(p)
    assert "javascript" in stack


def test_detect_stack_multi():
    p = make_project({
        "requirements.txt": "fastapi",
        "package.json": json.dumps({"dependencies": {}}),
    })
    stack = detect_stack(p)
    assert "python" in stack and "javascript" in stack


def test_extract_dependencies_python():
    p = make_project({"requirements.txt": "requests==2.28\nflask>=2.0\n# comment\nnumpy"})
    deps = extract_dependencies(p)
    libs = [d["name"] for d in deps]
    assert "requests" in libs
    assert "flask" in libs
    assert "numpy" in libs


def test_extract_dependencies_node():
    pkg = {"dependencies": {"react": "^18", "axios": "^1"}, "devDependencies": {"jest": "^29"}}
    p = make_project({"package.json": json.dumps(pkg)})
    deps = extract_dependencies(p)
    libs = [d["name"] for d in deps]
    assert "react" in libs
    assert "axios" in libs
    assert "jest" in libs


def test_extract_imports_python():
    src = "import os\nimport sys\nfrom pathlib import Path\nfrom collections import defaultdict\n"
    p = make_project({"main.py": src})
    imports = extract_imports(p)
    assert "os" in imports
    assert "sys" in imports
    assert "pathlib" in imports
    assert "collections" in imports


def test_extract_markers():
    src = (
        "x = 1  # TODO: fix this later\n"
        "y = 2  # FIXME: broken\n"
        "z = 3  # HACK: workaround for upstream bug\n"
        "w = 4  # normal comment\n"
    )
    p = make_project({"main.py": src})
    markers = extract_markers(p)
    types = [m["marker"] for m in markers]
    assert "TODO" in types
    assert "FIXME" in types
    assert "HACK" in types
    assert len(markers) == 3  # not the normal comment


# ── qa_capture ────────────────────────────────────────────────────────────────

def test_build_entry_required_fields():
    entry = build_entry(
        content="Always use PersistentClient for ChromaDB",
        category="anti-pattern",
    )
    assert entry["document"] == "Always use PersistentClient for ChromaDB"
    assert entry["metadata"]["category"] == "anti-pattern"
    assert "created_at" in entry["metadata"]
    assert entry["id"].startswith("qa-")


def test_build_entry_optional_fields():
    entry = build_entry(
        content="Use venv for Python isolation",
        category="pattern",
        library="python",
        tags="venv,isolation,python",
        confidence="high",
        project="my-project",
    )
    assert entry["metadata"]["library"] == "python"
    assert entry["metadata"]["tags"] == "venv,isolation,python"
    assert entry["metadata"]["confidence"] == "high"
    assert entry["metadata"]["project"] == "my-project"


def test_build_entry_dedup_id_stable():
    e1 = build_entry(content="Use venv", category="pattern")
    e2 = build_entry(content="Use venv", category="pattern")
    assert e1["id"] == e2["id"]  # same content → same id → dedup in ChromaDB


# ── qa_query ─────────────────────────────────────────────────────────────────

def test_filter_results_by_category():
    results = [
        {"metadata": {"category": "pattern"}, "document": "a"},
        {"metadata": {"category": "anti-pattern"}, "document": "b"},
        {"metadata": {"category": "pattern"}, "document": "c"},
    ]
    filtered = filter_results(results, category="pattern")
    assert len(filtered) == 2
    assert all(r["metadata"]["category"] == "pattern" for r in filtered)


def test_filter_results_no_filter():
    results = [
        {"metadata": {"category": "pattern"}, "document": "a"},
        {"metadata": {"category": "failed"}, "document": "b"},
    ]
    filtered = filter_results(results, category=None)
    assert len(filtered) == 2


# ── complexity analysis ───────────────────────────────────────────────────────

def test_nested_loop_flagged():
    src = "def f(items):\n    for x in items:\n        for y in items:\n            pass\n"
    p = make_project({"main.py": src})
    issues = analyze_python_file(p / "main.py")
    kinds = [i["kind"] for i in issues]
    assert "complexity" in kinds


def test_linear_search_in_loop_flagged():
    src = "def f(items, vals):\n    for x in items:\n        idx = vals.index(x)\n"
    p = make_project({"main.py": src})
    issues = analyze_python_file(p / "main.py")
    assert any(i["kind"] == "complexity" and "index" in i["msg"] for i in issues)


def test_long_but_simple_function_not_flagged():
    # A long, purely linear function (no branches) is not a KISS violation —
    # length alone says nothing about whether the logic could be simpler.
    body = "def big():\n" + "    x = 1\n" * 45
    p = make_project({"main.py": body})
    issues = analyze_python_file(p / "main.py")
    assert not any(i["kind"] == "kiss" and "complexity" in i["msg"] for i in issues)


def test_high_complexity_function_flagged():
    lines = ["def tangled(x):"]
    for i in range(12):
        lines.append(f"    if x == {i}:")
        lines.append(f"        x += {i}")
    body = "\n".join(lines) + "\n"
    p = make_project({"main.py": body})
    issues = analyze_python_file(p / "main.py")
    assert any(i["kind"] == "kiss" and "complexity" in i["msg"] for i in issues)


def test_mixed_concerns_function_flagged():
    src = (
        "def do_everything(path):\n"
        "    import requests, subprocess, json\n"
        "    data = requests.get('http://x').json()\n"
        "    subprocess.run(['echo', 'hi'])\n"
        "    with open(path) as f:\n"
        "        f.write(json.dumps(data))\n"
    )
    p = make_project({"main.py": src})
    issues = analyze_python_file(p / "main.py")
    assert any(i["kind"] == "kiss" and "mixes concerns" in i["msg"] for i in issues)


def test_too_many_params_flagged():
    src = "def f(a, b, c, d, e, g):\n    pass\n"
    p = make_project({"main.py": src})
    issues = analyze_python_file(p / "main.py")
    assert any(i["kind"] == "kiss" and "parameters" in i["msg"] for i in issues)


def test_static_method_candidate_flagged():
    src = (
        "class Foo:\n"
        "    def compute(self, x):\n"
        "        return x * 2\n"
    )
    p = make_project({"main.py": src})
    issues = analyze_python_file(p / "main.py")
    assert any(i["kind"] == "oop" and "compute" in i["msg"] for i in issues)


def test_clean_function_no_flags():
    src = "def f(a, b):\n    return a + b\n"
    p = make_project({"main.py": src})
    issues = analyze_python_file(p / "main.py")
    assert issues == []


def test_dunder_method_not_flagged_as_static_candidate():
    src = (
        "class Foo:\n"
        "    def __str__(self):\n"
        "        return 'foo'\n"
    )
    p = make_project({"main.py": src})
    issues = analyze_python_file(p / "main.py")
    assert not any(i["kind"] == "oop" for i in issues)


def test_test_class_method_not_flagged_as_static_candidate():
    src = (
        "class TestFoo:\n"
        "    def test_bar(self):\n"
        "        assert 1 == 1\n"
    )
    p = make_project({"main.py": src})
    issues = analyze_python_file(p / "main.py")
    assert not any(i["kind"] == "oop" for i in issues)


# ── Documentation and path robustness ─────────────────────────────────────────

def extract_fenced_block(markdown_text: str, section_header: str) -> str:
    """Extract the first ```python...``` block from a markdown section.

    Raises ValueError if the section header is not found.
    """
    lines = markdown_text.split('\n')
    header_idx = None
    for i, line in enumerate(lines):
        if section_header in line:
            header_idx = i
            break

    if header_idx is None:
        raise ValueError(f"Section '{section_header}' not found")

    in_block = False
    block_lines = []
    for line in lines[header_idx:]:
        if line.strip().startswith("```python"):
            in_block = True
            continue
        if in_block and line.strip().startswith("```"):
            break
        if in_block:
            block_lines.append(line)

    if not block_lines:
        raise ValueError(f"No fenced code block found after '{section_header}'")

    return '\n'.join(block_lines)


def test_sub_agent_snippet_no_tilde_and_check_true():
    """Sub-agent usage snippet must use Path.home(), not ~/..., and check=True."""
    skill_path = Path(__file__).resolve().parents[2] / "SKILL.md"
    markdown = skill_path.read_text()
    snippet = extract_fenced_block(markdown, "## Sub-agent usage")

    assert "~/" not in snippet, "Snippet contains hardcoded ~/ path"
    assert "check=True" in snippet, "Snippet missing check=True"


def test_sub_agent_snippet_extraction_fails_loudly_if_section_missing():
    """Helper must raise if section header is missing or misspelled."""
    with pytest.raises(ValueError, match="not found"):
        extract_fenced_block("no such section here", "## Sub-agent usage")


def test_pattern_type_help_lists_every_keyword():
    """qa_capture.py --help must list every key from _PATTERN_TYPE_KEYWORDS."""
    import re
    script = SCRIPTS / "qa_capture.py"
    result = __import__("subprocess").run(
        [sys.executable, str(script), "--help"],
        capture_output=True, text=True
    )
    # Find the mechanism type line by looking for "mechanism type:" and capturing until the end
    lines = result.stdout.split('\n')
    mechanism_line = None
    for i, line in enumerate(lines):
        if 'mechanism type:' in line:
            # Capture this line and all subsequent indented lines (continuation)
            mechanism_line = line.split('mechanism type:')[1]
            i += 1
            while i < len(lines) and lines[i] and not lines[i][0].isalpha():
                mechanism_line += ' ' + lines[i].strip()
                i += 1
            break

    if not mechanism_line:
        raise AssertionError("Could not find 'mechanism type:' in help output")

    # Import the keywords to check against
    from qa_capture import _PATTERN_TYPE_KEYWORDS
    for key in _PATTERN_TYPE_KEYWORDS:
        # Create a regex pattern that matches the key even if wrapped with whitespace
        # e.g., "context-injection" matches "context-\n                        injection"
        pattern = re.sub(r'-', r'-\\s*', re.escape(key))
        if not re.search(pattern, mechanism_line):
            raise AssertionError(f"Pattern type '{key}' not found in mechanism type help")


def test_sub_agent_snippet_imports_path():
    """Sub-agent usage snippet must import Path from pathlib."""
    skill_path = Path(__file__).resolve().parents[2] / "SKILL.md"
    markdown = skill_path.read_text()
    snippet = extract_fenced_block(markdown, "## Sub-agent usage")

    assert "from pathlib import Path" in snippet, "Snippet must import Path from pathlib"


def test_sub_agent_snippet_with_check_true_raises_on_failure():
    """Extracted sub-agent snippet code must raise when qa_query fails, due to check=True."""
    import subprocess
    import json

    # Extract the actual snippet from SKILL.md
    skill_path = Path(__file__).resolve().parents[2] / "SKILL.md"
    markdown = skill_path.read_text()
    snippet = extract_fenced_block(markdown, "## Sub-agent usage")

    # Create a modified version that triggers qa_query failure with an invalid flag
    # This test verifies the snippet will raise CalledProcessError because of check=True
    modified_snippet = snippet.replace(
        '"topic"',  # Replace the query topic
        '"--invalid-flag"'  # with an invalid flag to make qa_query.py exit non-zero
    )

    # Verify the replacement actually happened
    assert modified_snippet != snippet, "Topic replacement failed — snippet unchanged"

    # Point paths at the repo copy, not the deployed version
    modified_snippet = modified_snippet.replace(
        'str(Path.home() / ".agents/venv/bin/python")',
        'sys.executable'
    )
    modified_snippet = modified_snippet.replace(
        'str(Path.home() / ".agents/skills/qa-agent/scripts/qa_query.py")',
        f'str(SCRIPTS / "qa_query.py")'
    )

    # Execute the modified snippet in a local scope with the necessary imports
    local_scope = {}
    with pytest.raises(subprocess.CalledProcessError):
        exec(modified_snippet, {
            "subprocess": subprocess,
            "json": json,
            "Path": Path,
            "sys": sys,
            "SCRIPTS": SCRIPTS,
        })

