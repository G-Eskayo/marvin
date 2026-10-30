"""Tests for retrieval_eval.py (marvin#705): which retriever finds the known answer to a MARVIN question.
Fixture repos in tmp_path; graphify and memory_graph are faked at the subprocess boundary.
    ~/.agents/venv/bin/python -m pytest bench/tests/test_retrieval_eval.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))

import retrieval_eval as re_  # noqa: E402


# ── scoring ───────────────────────────────────────────────────────────────

def test_scores_for_a_single_gold_answer():
    s = re_.score(["a.py", "b.py", "gold.py", "c.py"], {"gold.py"})
    assert s == {"hit@1": 0, "hit@5": 1, "recall@5": 1.0, "mrr": pytest.approx(1 / 3)}


def test_recall_counts_each_gold_file_once_and_duplicates_do_not_inflate():
    # raw g2 is 6th; after de-duplication (x, g1, y, z, g2) it is 5th, so a repeated hit can't push gold out of the top 5
    s = re_.score(["x", "g1", "g1", "y", "z", "g2"], {"g1", "g2"})
    assert s["recall@5"] == 1.0
    assert s["hit@1"] == 0 and s["mrr"] == pytest.approx(0.5)
    assert re_.score(["g1", "g1", "g1"], {"g1", "g2"})["recall@5"] == 0.5


def test_nothing_found_scores_zero():
    assert re_.score([], {"gold"}) == {"hit@1": 0, "hit@5": 0, "recall@5": 0.0, "mrr": 0.0}


def test_rrf_rewards_agreement():
    fused = re_.rrf([["a", "b", "c"], ["b", "d"]])
    assert fused[0] == "b" and set(fused) == {"a", "b", "c", "d"}


# ── retrievers ────────────────────────────────────────────────────────────

def make_repo(tmp_path) -> Path:
    r = tmp_path / "repo"
    (r / "lib").mkdir(parents=True)
    (r / "lib" / "locks.py").write_text("def check_dispatch_lock(path):\n    # stale lock after an hour\n    return age > 3600\n")
    (r / "lib" / "dispatch.py").write_text("def dispatch(cmd):\n    return run(cmd)\n")
    (r / "README.md").write_text("MARVIN dispatches tickets.\n")
    (r / "graphify-out").mkdir()
    (r / "graphify-out" / "GRAPH_REPORT.md").write_text("dispatch lock stale stale stale\n")
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    subprocess.run(["git", "add", "-A"], cwd=r, check=True)
    return r


def test_keywords_drop_question_words():
    assert re_.keywords("Where is the dispatch lock checked for staleness?") == ["dispatch", "lock", "checked", "staleness"]


@pytest.mark.requires_tool("rg")
def test_rg_ranks_the_file_matching_most_distinct_keywords(tmp_path):
    r = make_repo(tmp_path)
    got = re_.rg_retrieve("where is the dispatch lock checked for being stale", r)
    assert got.ranked[0] == "lib/locks.py"
    assert "graphify-out/GRAPH_REPORT.md" not in got.ranked  # the graph's own output is never an answer
    assert got.tokens > 0


GRAPHIFY_OUT = """Graph: graphify-out/graph.json (11209 nodes) | Traversal: BFS depth=2 | 9 nodes found
NODE dispatch() [src=lib/dispatch.py loc=L200 community=x]
NODE timedelta [src= loc= community=timedelta]
NODE dispatch.py [src=lib/dispatch.py loc=L1 community=x]
NODE check_dispatch_lock() [src=lib/locks.py loc=L1 community=y]
EDGE a --calls [EXTRACTED]--> b at=lib/other.py:L3
"""


def test_graphify_output_is_parsed_into_files_in_order_of_first_mention():
    assert re_.parse_graphify(GRAPHIFY_OUT) == ["lib/dispatch.py", "lib/locks.py"]


def test_graphify_retriever_counts_its_output_as_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(re_, "_run", lambda cmd, cwd: GRAPHIFY_OUT)
    got = re_.graphify_retrieve("q", tmp_path)
    assert got.ranked == ["lib/dispatch.py", "lib/locks.py"] and got.tokens == len(GRAPHIFY_OUT) // 4


def test_a_retriever_that_fails_is_a_miss_not_a_crash(tmp_path, monkeypatch):
    def boom(cmd, cwd):
        raise subprocess.CalledProcessError(1, cmd, "graph missing")
    monkeypatch.setattr(re_, "_run", boom)
    got = re_.graphify_retrieve("q", tmp_path)
    assert got.ranked == [] and got.error and "graph missing" in got.error


MEMORY_OUT = "1.00  feedback-tests-first  — write the failing test first\n0.40  project-demo  — a demo [replaced by x]\n"


def test_memory_graph_output_is_parsed(tmp_path, monkeypatch):
    monkeypatch.setattr(re_, "_run", lambda cmd, cwd: MEMORY_OUT)
    assert re_.memory_retrieve("tests", tmp_path).ranked == ["memory:feedback-tests-first", "memory:project-demo"]


# ── a whole run ───────────────────────────────────────────────────────────

def test_run_scores_every_question_with_every_applicable_retriever(tmp_path, monkeypatch):
    questions = [
        {"id": "q1", "kind": "code", "q": "where is the dispatch lock checked", "gold": ["lib/locks.py"]},
        {"id": "q2", "kind": "memory", "q": "tests first?", "gold": ["memory:feedback-tests-first"]},
    ]
    fake = {
        "rg": lambda q, root: re_.Retrieved(["lib/locks.py"], 10),
        "graphify": lambda q, root: re_.Retrieved(["lib/dispatch.py", "lib/locks.py"], 500),
        "memory": lambda q, root: re_.Retrieved(["memory:feedback-tests-first"], 20),
    }
    monkeypatch.setattr(re_, "RETRIEVERS", fake)
    out = re_.run(questions, repo=tmp_path, memory_dir=tmp_path)
    by = {(r["id"], r["retriever"]): r for r in out["rows"]}
    assert by[("q1", "rg")]["hit@1"] == 1 and by[("q1", "graphify")]["hit@1"] == 0
    assert ("q1", "memory") not in by           # memory search only answers memory questions
    assert by[("q1", "hybrid")]["hit@5"] == 1   # fusion of rg + graphify
    assert ("q2", "rg") in by and by[("q2", "memory")]["hit@1"] == 1
    summary = out["summary"]
    assert summary["rg"]["questions"] == 2 and summary["memory"]["questions"] == 1
    assert summary["graphify"]["mean_tokens"] == 500


def test_question_file_is_validated(tmp_path):
    bad = tmp_path / "q.json"
    bad.write_text(json.dumps([{"id": "q1", "q": "x", "gold": []}]))
    with pytest.raises(ValueError, match="q1"):
        re_.load_questions(bad)


@pytest.mark.requires_tool("rg")
def test_rg_searches_the_folder_even_when_stdin_is_an_open_pipe(tmp_path):
    # 2026-10-26 real run: every rg call timed out. With no path argument and a non-tty stdin, rg searches stdin and
    # waits forever. pytest closes stdin, so only a child process with an open pipe reproduces it.
    r = make_repo(tmp_path)
    code = ("import sys; sys.path.insert(0, %r); import retrieval_eval as m; "
            "print(m.rg_retrieve('dispatch lock stale', __import__('pathlib').Path(%r)).ranked[0])") % (str(BENCH), str(r))
    p = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        out = p.stdout.readline()  # stdin stays open: the child must not wait on it
    finally:
        p.kill()
    assert out.strip() == "lib/locks.py"
