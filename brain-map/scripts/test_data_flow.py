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
    assert not gaps


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

    assert not threads
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
    assert not gaps


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
    assert not gaps


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
    assert not threads
    assert not gaps


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


# ── 2026-10-08: feeds never drew (docs/plans/map-connections-2026-10-08.md) ──────────────────────────────────

from data_flow import discover_readers, discover_writers, extract_js_reader_paths  # noqa: E402


def test_js_reader_paths_any_name_and_lib_scripts():
    source = '''
const VENV_PYTHON = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
const HEALTH_CHECKS_SCRIPT = path.join(homedir(), '.agents', 'lib', 'health_checks.py')
export const HEALTH_STATUS_PATH = path.join(homedir(), '.claude', 'logs', 'health-status.json')
  const evalScript = path.join(agentsDir, 'lib', 'portfolio_eval.py')
'''
    paths = extract_js_reader_paths(source)
    assert "~/.claude/logs/health-status.json" in paths
    assert "lib/health_checks.py" in paths
    assert "lib/portfolio_eval.py" in paths
    assert not any("venv" in p for p in paths)  # the interpreter is not data


def test_discover_readers_uses_tab_node_ids_and_warns_on_missing_files(tmp_path):
    (tmp_path / "jobs.js").write_text("export const JOBS_DIR = path.join(homedir(), '.claude', 'logs', 'jobs')\n")
    warnings = []
    readers = discover_readers({"Activity tab": ["jobs.js", "gone.js"]}, tmp_path, warnings)
    assert [(r["tab_id"], r["path"]) for r in readers] == [("Activity tab", "~/.claude/logs/jobs")]
    assert len(warnings) == 1 and "gone.js" in warnings[0]


def _lib(tmp_path, files):
    lib = tmp_path / "lib"
    lib.mkdir()
    for name, src in files.items():
        (lib / name).write_text(src)
    return lib


def test_writers_include_the_script_itself_and_helper_paths(tmp_path):
    lib = _lib(tmp_path, {
        "job_events.py": 'JOBS_DIR = Path.home() / ".claude" / "logs" / "jobs"\n',
        "ticket_pipeline.py": "import job_events\nwith job_events.job_run('x', 'y'):\n    pass\n",
        "unowned.py": "import job_events\njob_events.job_run('a', 'b')\n",
    })
    tree = {"id": "root", "children": [{"id": "ticket-pipeline", "path": "lib/ticket_pipeline.py", "children": []}]}
    writers = discover_writers(lib, {}, tree, helpers=["job_events"], repo_root=tmp_path)
    got = sorted((w["node_id"], w["path"]) for w in writers)
    assert got == [("ticket-pipeline", "lib/ticket_pipeline.py"), ("ticket-pipeline", "~/.claude/logs/jobs")]


def test_match_threads_collapses_duplicate_pairs():
    writers = [WriterRecord(node_id="usage-scan", path=p, source_file="lib/s.py") for p in ("~/a", "~/b")]
    readers = [ReaderRecord(tab_id="Metrics tab", path=p, source_file="m.js") for p in ("~/a", "~/b")]
    threads, gaps = match_threads(writers, readers)
    assert [(t["a"], t["b"]) for t in threads] == [("usage-scan", "Metrics tab")]
    assert "~/a" in threads[0]["label"] and "~/b" in threads[0]["label"]
    assert gaps == []
