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

import qa_capture
import qa_query
from qa_scan import detect_stack, extract_dependencies, extract_imports, extract_markers, analyze_python_file, store_entries
from qa_capture import build_entry
from qa_query import filter_results
import chromadb
import qa_scan


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


# ── store_entries ────────────────────────────────────────────────────────────

def test_store_entries_basic(monkeypatch, tmp_path):
    """Test that store_entries stores new entries correctly."""
    monkeypatch.setattr(qa_scan, "CHROMA_PATH", tmp_path)
    entries = [
        build_entry(content="Pattern A", category="pattern"),
        build_entry(content="Pattern B", category="pattern"),
    ]
    count = store_entries(entries)
    assert count == 2

    # Verify entries are in the database
    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection(qa_scan.COLLECTION)
    all_ids = col.get(include=[])["ids"]
    assert len(all_ids) == 2


def test_store_entries_duplicate_within_batch(monkeypatch, tmp_path):
    """Test that duplicate entries within a batch are deduplicated."""
    monkeypatch.setattr(qa_scan, "CHROMA_PATH", tmp_path)
    # Create two entries with the same content (same ID)
    entry = build_entry(content="Pattern X", category="pattern")
    entries = [entry, entry]  # Same entry twice
    count = store_entries(entries)
    assert count == 1  # Only one should be stored

    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection(qa_scan.COLLECTION)
    all_ids = col.get(include=[])["ids"]
    assert len(all_ids) == 1


def test_store_entries_skip_existing(monkeypatch, tmp_path):
    """Test that existing entries in the database are skipped."""
    monkeypatch.setattr(qa_scan, "CHROMA_PATH", tmp_path)

    # Add initial entry
    entry1 = build_entry(content="Existing pattern", category="pattern")
    store_entries([entry1])

    # Try to add the same entry again
    count = store_entries([entry1])
    assert count == 0  # Should not add duplicates

    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection(qa_scan.COLLECTION)
    all_ids = col.get(include=[])["ids"]
    assert len(all_ids) == 1


def test_store_entries_partial_batch(monkeypatch, tmp_path):
    """Test that batches work correctly when not all entries are new."""
    monkeypatch.setattr(qa_scan, "CHROMA_PATH", tmp_path)

    # Add some initial entries
    e1 = build_entry(content="Pattern 1", category="pattern")
    e2 = build_entry(content="Pattern 2", category="pattern")
    store_entries([e1, e2])

    # Now add a mix of existing and new entries
    e3 = build_entry(content="Pattern 3", category="pattern")
    e4 = build_entry(content="Pattern 4", category="pattern")
    count = store_entries([e1, e3, e2, e4])  # e1 and e2 exist, e3 and e4 are new
    assert count == 2  # Only e3 and e4 should be added

    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection(qa_scan.COLLECTION)
    all_ids = col.get(include=[])["ids"]
    assert len(all_ids) == 4


def test_store_entries_chunk_boundary(monkeypatch, tmp_path):
    """Test that batching at chunk boundaries works correctly."""
    monkeypatch.setattr(qa_scan, "CHROMA_PATH", tmp_path)

    # Create exactly 1000 entries to test across two batches (BATCH=500)
    entries = [
        build_entry(content=f"Pattern {i}", category="pattern")
        for i in range(1000)
    ]
    count = store_entries(entries)
    assert count == 1000

    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection(qa_scan.COLLECTION)
    all_ids = col.get(include=[])["ids"]
    assert len(all_ids) == 1000


def test_store_entries_mixed_across_batches(monkeypatch, tmp_path):
    """Test that mixed existing/new entries across batch boundaries work."""
    monkeypatch.setattr(qa_scan, "CHROMA_PATH", tmp_path)

    # Add 300 initial entries
    initial = [
        build_entry(content=f"Initial {i}", category="pattern")
        for i in range(300)
    ]
    store_entries(initial)

    # Create 1000 entries where some already exist
    # First 300 are duplicates of initial entries
    mixed = initial + [
        build_entry(content=f"New {i}", category="pattern")
        for i in range(700)
    ]
    count = store_entries(mixed)
    assert count == 700  # Only the new ones

    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection(qa_scan.COLLECTION)
    all_ids = col.get(include=[])["ids"]
    assert len(all_ids) == 1000


def test_store_entries_dry_run(monkeypatch, tmp_path):
    """Test that dry_run returns count without storing anything."""
    monkeypatch.setattr(qa_scan, "CHROMA_PATH", tmp_path)

    entries = [
        build_entry(content="Pattern A", category="pattern"),
        build_entry(content="Pattern B", category="pattern"),
    ]
    count = store_entries(entries, dry_run=True)
    assert count == 2

    # Database should be empty
    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection(qa_scan.COLLECTION)
    all_ids = col.get(include=[])["ids"]
    assert len(all_ids) == 0


def test_store_entries_empty_list(monkeypatch, tmp_path):
    """Test that storing empty list returns 0."""
    monkeypatch.setattr(qa_scan, "CHROMA_PATH", tmp_path)

    count = store_entries([])
    assert count == 0


def test_store_entries_no_limit_offset_via_code_inspection():
    """Verify store_entries never uses limit/offset pagination (code inspection test)."""
    import inspect
    source = inspect.getsource(store_entries)
    assert "limit=" not in source, "store_entries should not call col.get with limit="
    assert "offset=" not in source, "store_entries should not call col.get with offset="
    # Verify the while loop for pagination is gone
    assert "while True:" not in source or "PAGE" not in source, "store_entries should not have pagination loop"


def test_store_entries_large_batch_scales_efficiently(monkeypatch, tmp_path):
    """Test that col.get is called O(batches) not O(total_entries): 2 calls for 1000 entries."""
    monkeypatch.setattr(qa_scan, "CHROMA_PATH", tmp_path)

    import chromadb

    # Spy on col.get calls by wrapping the collection's get method
    get_call_count = []
    original_client = chromadb.PersistentClient

    def spy_client(*args, **kwargs):
        client = original_client(*args, **kwargs)
        original_get_or_create = client.get_or_create_collection

        def wrapped_get_or_create(*col_args, **col_kwargs):
            col = original_get_or_create(*col_args, **col_kwargs)
            original_get = col.get

            def spy_get(*get_args, **get_kwargs):
                get_call_count.append(1)
                return original_get(*get_args, **get_kwargs)

            col.get = spy_get
            return col

        client.get_or_create_collection = wrapped_get_or_create
        return client

    monkeypatch.setattr(chromadb, "PersistentClient", spy_client)

    # Add 1000 brand new entries (should trigger 2 col.get calls: one per BATCH=500 chunk)
    entries = [
        build_entry(content=f"Pattern {i}", category="pattern")
        for i in range(1000)
    ]

    count = store_entries(entries)
    assert count == 1000
    assert len(get_call_count) == 2, f"Expected 2 col.get calls (one per 500-entry batch), got {len(get_call_count)}"

    # Verify all entries are present
    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection(qa_scan.COLLECTION)
    all_ids = col.get(include=[])["ids"]
    assert len(all_ids) == 1000


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


# ── Dedup behavior regression tests ───────────────────────────────────────────

def test_skill_md_dedup_rule_states_sha256_not_cosine():
    """SKILL.md dedup rule must mention SHA-256, never cosine."""
    skill_path = Path(__file__).resolve().parents[2] / "SKILL.md"
    markdown = skill_path.read_text()
    # Extract the Behaviour rules section
    lines = markdown.split('\n')
    behaviour_start = None
    for i, line in enumerate(lines):
        if '## Behaviour rules' in line:
            behaviour_start = i
            break
    assert behaviour_start is not None, "## Behaviour rules section not found"
    # Find the dedup line
    dedup_line = None
    for i in range(behaviour_start, len(lines)):
        if 'Dedup:' in lines[i]:
            dedup_line = lines[i]
            break
    assert dedup_line is not None, "Dedup rule not found"
    assert 'SHA-256' in dedup_line, "Dedup rule must mention SHA-256"
    assert 'cosine' not in dedup_line.lower(), "Dedup rule must not mention cosine"


def test_skill_md_dedup_rule_links_1314():
    """SKILL.md dedup rule must reference issue #1314."""
    skill_path = Path(__file__).resolve().parents[2] / "SKILL.md"
    markdown = skill_path.read_text()
    lines = markdown.split('\n')
    behaviour_start = None
    for i, line in enumerate(lines):
        if '## Behaviour rules' in line:
            behaviour_start = i
            break
    assert behaviour_start is not None, "## Behaviour rules section not found"
    dedup_line = None
    for i in range(behaviour_start, len(lines)):
        if 'Dedup:' in lines[i]:
            dedup_line = lines[i]
            break
    assert dedup_line is not None, "Dedup rule not found"
    assert '#1314' in dedup_line, "Dedup rule must reference #1314"


def test_no_cosine_promise_anywhere_in_qa_agent_skill_folder():
    """No file in skills/qa-agent/ folder should mention cosine (regression guard)."""
    skill_folder = Path(__file__).resolve().parents[2]  # skills/qa-agent/
    cosine_mentions = []
    this_test_file = Path(__file__).resolve()
    for file_path in skill_folder.rglob('*'):
        if file_path.is_file() and not file_path.name.startswith('.') and file_path != this_test_file:
            try:
                content = file_path.read_text()
                if 'cosine' in content.lower():
                    cosine_mentions.append(str(file_path.relative_to(skill_folder)))
            except (UnicodeDecodeError, PermissionError):
                pass
    assert not cosine_mentions, f"Found 'cosine' in: {cosine_mentions}"


def test_store_entries_skips_exact_duplicate_content(tmp_path, monkeypatch):
    """store_entries should skip entries with identical IDs (exact content match)."""
    # Patch CHROMA_PATH at call time using monkeypatch (not sys.modules manipulation)
    monkeypatch.setattr(qa_scan, "CHROMA_PATH", tmp_path)

    from qa_scan import store_entries
    from qa_capture import build_entry

    # Create two identical entries
    entry1 = build_entry(
        content="Always use PersistentClient for ChromaDB",
        category="anti-pattern"
    )
    entry2 = build_entry(
        content="Always use PersistentClient for ChromaDB",
        category="anti-pattern"
    )
    assert entry1["id"] == entry2["id"], "Identical content should produce identical IDs"

    # First call stores 1
    result1 = store_entries([entry1])
    assert result1 == 1, f"Expected 1 new entry, got {result1}"

    # Second call with same entry stores 0
    result2 = store_entries([entry2])
    assert result2 == 0, f"Expected 0 new entries (duplicate), got {result2}"


def test_store_entries_does_not_dedup_near_identical_content(tmp_path, monkeypatch):
    """store_entries should NOT skip near-identical content with different IDs."""
    # Patch CHROMA_PATH at call time using monkeypatch
    monkeypatch.setattr(qa_scan, "CHROMA_PATH", tmp_path)

    from qa_scan import store_entries
    from qa_capture import build_entry

    # Create two entries with near-identical content (differ by one character)
    entry1 = build_entry(
        content="Always use PersistentClient for ChromaDB",
        category="anti-pattern"
    )
    entry2 = build_entry(
        content="Always use PersistentClient for Chroma_DB",  # Different by one char
        category="anti-pattern"
    )
    assert entry1["id"] != entry2["id"], "Different content should produce different IDs"

    # Both should be stored
    result = store_entries([entry1, entry2])
    assert result == 2, f"Expected 2 new entries (not deduplicated), got {result}"


def test_store_entry_skips_exact_duplicate_content(tmp_path, monkeypatch):
    """store_entry should skip entries that already exist (exact content match)."""
    # Patch CHROMA_PATH at call time using monkeypatch
    monkeypatch.setattr(qa_capture, "CHROMA_PATH", tmp_path)

    from qa_capture import store_entry, build_entry

    # Create two identical entries
    entry1 = build_entry(
        content="Use venv for Python isolation",
        category="pattern"
    )
    entry2 = build_entry(
        content="Use venv for Python isolation",
        category="pattern"
    )
    assert entry1["id"] == entry2["id"]

    # First call returns True (new)
    result1 = store_entry(entry1)
    assert result1 is True, f"Expected True (new entry), got {result1}"

    # Second call returns False (already exists)
    result2 = store_entry(entry2)
    assert result2 is False, f"Expected False (duplicate), got {result2}"

