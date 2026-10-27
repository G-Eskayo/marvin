"""The question log (blind-spots note, test A; Gil 2026-10-26: automatic). Each question MARVIN couldn't answer from
data is logged once; asking again counts it, so the most-wanted missing signals rise to the top."""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import question_log as ql  # noqa: E402

LIB = Path(__file__).resolve().parents[1]


@pytest.fixture
def log(tmp_path):
    return tmp_path / "var" / "question-log.jsonl"


def test_default_path_is_marvin_owned_not_claude(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert ql.default_path() == tmp_path / ".agents" / "var" / "question-log.jsonl"


def test_add_then_top(log):
    ql.add("Why does the MacBook throttle?", why="no load history", want="overload minutes", path=log, machine="m")
    top = ql.top(path=log)
    assert top[0]["question"] == "Why does the MacBook throttle?"
    assert top[0]["count"] == 1 and top[0]["want"] == ["overload minutes"]


def test_the_same_question_asked_again_counts_not_duplicates(log):
    ql.add("Is #621 done?", path=log, machine="m")
    ql.add("  is #621   DONE? ", path=log, machine="m")
    assert [(q["count"]) for q in ql.top(path=log)] == [2]


def test_most_asked_first(log):
    for _ in range(3):
        ql.add("where is X running", path=log, machine="m")
    ql.add("what does it cost", path=log, machine="m")
    assert [q["question"] for q in ql.top(path=log)][0] == "where is X running"


@pytest.mark.parametrize("bad", ["", "   ", None, "\n\t"])
def test_empty_questions_are_refused(log, bad):
    with pytest.raises(ValueError):
        ql.add(bad, path=log, machine="m")
    assert not log.exists()


def test_huge_question_is_cut_not_refused(log):
    ql.add("x" * 50_000, path=log, machine="m")
    assert len(ql.top(path=log)[0]["question"]) <= ql.MAX_LEN


def test_a_torn_or_junk_line_is_skipped(log):
    log.parent.mkdir(parents=True)
    log.write_text('{"question": "ok q", "ts": "t", "machine": "m"}\n{"quest\nnot json\n[1,2]\n')
    assert [q["question"] for q in ql.top(path=log)] == ["ok q"]


def test_missing_log_is_empty(log):
    assert ql.top(path=log) == []


def test_concurrent_writers_lose_nothing(log):
    def go(i):
        for j in range(25):
            ql.add(f"q{i}-{j}", path=log, machine="m")
    ts = [threading.Thread(target=go, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    lines = log.read_text().splitlines()
    assert len(lines) == 100 and all(json.loads(x)["question"] for x in lines)


def test_text_is_stored_as_data_never_run(log):
    ql.add("$(touch /tmp/pwned-question-log) `id` <script>", path=log, machine="m")
    assert ql.top(path=log)[0]["question"].startswith("$(touch")
    assert not Path("/tmp/pwned-question-log").exists()


def test_cli_add_and_top(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}
    run = lambda *a: subprocess.run([sys.executable, str(LIB / "question_log.py"), *a], env=env,
                                    capture_output=True, text=True)
    r = run("add", "How much did #600 cost?", "--why", "no cost per PR yet", "--want", "cost per merged PR")
    assert r.returncode == 0, r.stderr
    out = run("top").stdout
    assert "How much did #600 cost?" in out and "cost per merged PR" in out
    assert (tmp_path / ".agents" / "var" / "question-log.jsonl").exists()


def test_cli_refuses_empty(tmp_path):
    r = subprocess.run([sys.executable, str(LIB / "question_log.py"), "add", "  "],
                       env={**os.environ, "HOME": str(tmp_path)}, capture_output=True, text=True)
    assert r.returncode != 0
