#!/usr/bin/env python3
"""
Tests for data_flow.py — matching writer and reader path constants to derive feeds threads.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from data_flow import (
    extract_py_path_constants,
    extract_js_path_constants,
    match_threads,
    WriterRecord,
    ReaderRecord,
)


def test_extract_py_path_constants_home_alias():
    """Extract *_PATH constants from Python code with HOME alias."""
    source = '''
HOME = Path.home()
STATUS_PATH = HOME / "example" / "status.json"
METRICS_DIR = HOME / "bench" / "metrics"
'''
    constants = extract_py_path_constants(source)
    assert "STATUS_PATH" in constants
    assert constants["STATUS_PATH"].startswith("~/")
    assert "example" in constants["STATUS_PATH"]
    assert "METRICS_DIR" in constants
    assert "bench" in constants["METRICS_DIR"]


def test_extract_py_path_constants_inline_path_home():
    """Extract *_PATH constants from Python code with inline Path.home()."""
    source = '''
CATALOG_DIR = Path.home() / "catalog" / "projects"
'''
    constants = extract_py_path_constants(source)
    assert "CATALOG_DIR" in constants
    assert "catalog" in constants["CATALOG_DIR"]
    assert "projects" in constants["CATALOG_DIR"]


def test_extract_py_path_constants_string_literal():
    """Extract *_PATH constants from Python string literals."""
    source = '''
CONFIG_PATH = "~/.config/app.json"
'''
    constants = extract_py_path_constants(source)
    assert "CONFIG_PATH" in constants
    assert constants["CONFIG_PATH"] == "~/.config/app.json"


def test_extract_js_path_constants_path_join():
    """Extract *_PATH constants from JavaScript path.join patterns."""
    source = '''
const HEALTH_STATUS_PATH = path.join(homedir(), '.agents', 'health', 'status.json');
const METRICS_DIR = path.join(homedir(), '.agents', 'bench', 'metrics');
'''
    constants = extract_js_path_constants(source)
    assert "HEALTH_STATUS_PATH" in constants
    assert ".agents" in constants["HEALTH_STATUS_PATH"]
    assert "health" in constants["HEALTH_STATUS_PATH"]
    assert "METRICS_DIR" in constants


def test_match_threads_exact_path_match():
    """Match writers and readers by exact path equality."""
    writers = [
        WriterRecord(
            node_id="ticket-pipeline",
            path="~/.agents/stages",
            source_file="lib/ticket_stages.py",
        ),
    ]
    readers = [
        ReaderRecord(
            tab_id="activity tab",
            path="~/.agents/stages",
            source_file="dashboard/activity.js",
        ),
    ]

    threads, gaps = match_threads(writers, readers)

    assert len(threads) == 1
    assert threads[0]["a"] == "ticket-pipeline"
    assert threads[0]["b"] == "activity tab"
    assert threads[0]["type"] == "feeds"
    assert len(gaps) == 0


def test_match_threads_no_match_different_paths():
    """No match when writer and reader paths differ."""
    writers = [
        WriterRecord(
            node_id="ticket-pipeline",
            path="~/.agents/stages",
            source_file="lib/ticket_stages.py",
        ),
    ]
    readers = [
        ReaderRecord(
            tab_id="activity tab",
            path="~/.agents/catalog",
            source_file="dashboard/activity.js",
        ),
    ]

    threads, gaps = match_threads(writers, readers)

    assert len(threads) == 0
    assert len(gaps) == 2  # one unmatched writer, one unmatched reader
    writer_gap = [g for g in gaps if g["kind"] == "unmatched_writer"][0]
    reader_gap = [g for g in gaps if g["kind"] == "unmatched_reader"][0]
    assert writer_gap["path"] == "~/.agents/stages"
    assert reader_gap["path"] == "~/.agents/catalog"


def test_match_threads_multiple_writers_one_reader():
    """Multiple writers to one reader on same path."""
    writers = [
        WriterRecord(
            node_id="ticket-pipeline",
            path="~/.agents/catalog",
            source_file="lib/project_catalog.py",
        ),
        WriterRecord(
            node_id="health-check",
            path="~/.agents/catalog",
            source_file="lib/another.py",
        ),
    ]
    readers = [
        ReaderRecord(
            tab_id="docs tab",
            path="~/.agents/catalog",
            source_file="dashboard/catalog.js",
        ),
    ]

    threads, gaps = match_threads(writers, readers)

    assert len(threads) == 2
    assert threads[0]["a"] == "ticket-pipeline"
    assert threads[1]["a"] == "health-check"
    assert all(t["b"] == "docs tab" for t in threads)
    assert len(gaps) == 0


def test_match_threads_one_writer_multiple_readers():
    """One writer to multiple readers on same path."""
    writers = [
        WriterRecord(
            node_id="metrics-registry",
            path="~/.agents/bench/metrics",
            source_file="lib/metrics_registry.py",
        ),
    ]
    readers = [
        ReaderRecord(
            tab_id="metrics tab",
            path="~/.agents/bench/metrics",
            source_file="dashboard/metrics.js",
        ),
        ReaderRecord(
            tab_id="health tab",
            path="~/.agents/bench/metrics",
            source_file="dashboard/health.js",
        ),
    ]

    threads, gaps = match_threads(writers, readers)

    assert len(threads) == 2
    assert all(t["a"] == "metrics-registry" for t in threads)
    assert {t["b"] for t in threads} == {"metrics tab", "health tab"}
    assert len(gaps) == 0


def test_match_threads_partial_match():
    """Some paths match, some don't."""
    writers = [
        WriterRecord(
            node_id="w1",
            path="~/.agents/path1",
            source_file="lib/file1.py",
        ),
        WriterRecord(
            node_id="w2",
            path="~/.agents/path2",
            source_file="lib/file2.py",
        ),
    ]
    readers = [
        ReaderRecord(
            tab_id="tab1",
            path="~/.agents/path1",
            source_file="dashboard/file1.js",
        ),
        ReaderRecord(
            tab_id="tab2",
            path="~/.agents/path3",
            source_file="dashboard/file3.js",
        ),
    ]

    threads, gaps = match_threads(writers, readers)

    assert len(threads) == 1
    assert threads[0]["a"] == "w1"
    assert threads[0]["b"] == "tab1"
    # Gaps: w2 (unmatched), tab2 (unmatched)
    assert len(gaps) == 2


def test_match_threads_empty():
    """No writers or readers yields no threads and no gaps."""
    threads, gaps = match_threads([], [])
    assert len(threads) == 0
    assert len(gaps) == 0


if __name__ == "__main__":
    test_extract_py_path_constants_home_alias()
    print("✓ test_extract_py_path_constants_home_alias")

    test_extract_py_path_constants_inline_path_home()
    print("✓ test_extract_py_path_constants_inline_path_home")

    test_extract_py_path_constants_string_literal()
    print("✓ test_extract_py_path_constants_string_literal")

    test_extract_js_path_constants_path_join()
    print("✓ test_extract_js_path_constants_path_join")

    test_match_threads_exact_path_match()
    print("✓ test_match_threads_exact_path_match")

    test_match_threads_no_match_different_paths()
    print("✓ test_match_threads_no_match_different_paths")

    test_match_threads_multiple_writers_one_reader()
    print("✓ test_match_threads_multiple_writers_one_reader")

    test_match_threads_one_writer_multiple_readers()
    print("✓ test_match_threads_one_writer_multiple_readers")

    test_match_threads_partial_match()
    print("✓ test_match_threads_partial_match")

    test_match_threads_empty()
    print("✓ test_match_threads_empty")

    print("\nAll tests passed!")
