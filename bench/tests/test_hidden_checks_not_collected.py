"""The repo's test suite never collects a bench task's hidden checks (marvin#645, bench/tasks/conftest.py).

They import the module an agent writes during a bench run, which doesn't exist in the repo, so collecting them broke
the Python tests check on PR #1036 with ModuleNotFoundError. They must still run where bench.py puts them.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TASKS = REPO / "bench" / "tasks"
sys.path.insert(0, str(REPO / "bench"))
sys.path.insert(0, str(REPO / "bench" / "lib"))

import bench  # noqa: E402


def _collect(*paths: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *paths],
                          cwd=REPO, capture_output=True, text=True, timeout=300)


def test_there_are_hidden_checks_to_keep_out():
    assert sorted(TASKS.glob("*/check/test_*.py")), "no hidden checks: this test guards nothing"


def test_collecting_the_tasks_folder_finds_no_hidden_check_and_no_error():
    out = _collect("bench/tasks")
    text = out.stdout + out.stderr
    assert "/check/" not in text, text[-2000:]
    assert "ModuleNotFoundError" not in text and "ERROR" not in text, text[-2000:]
    assert out.returncode in (0, 5), text[-2000:]  # 5: nothing collected


def test_a_hidden_check_still_runs_in_a_bench_workdir(tmp_path):
    # The real task-013 check against a fixed LRU cache, the way bench.py runs it after an agent's run.
    task = next(t for t in (TASKS.glob("task-013-*")))
    (tmp_path / "lru_cache.py").write_text(
        "from collections import OrderedDict\n"
        "class LRUCache:\n"
        "    def __init__(self, cap):\n        self.cap = cap\n        self._cache = OrderedDict()\n"
        "    def get(self, k):\n        if k not in self._cache:\n            return None\n"
        "        self._cache.move_to_end(k)\n        return self._cache[k]\n"
        "    def put(self, k, v):\n        self._cache[k] = v\n        self._cache.move_to_end(k)\n"
        "        if len(self._cache) > self.cap:\n            self._cache.popitem(last=False)\n"
        "    def __contains__(self, k):\n        return k in self._cache\n"
        "    def __len__(self):\n        return len(self._cache)\n"
    )
    import json
    spec = json.loads((task / "task.json").read_text())
    result = bench.run_hidden_check({**spec, "dir": str(task)}, tmp_path)
    assert result is not None
    assert result["pass"], result["output"]
    assert not (tmp_path / "conftest.py").exists()  # the guard stays in the repo
