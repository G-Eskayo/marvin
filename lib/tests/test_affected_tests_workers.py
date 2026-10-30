"""marvin#940 meets #826: the merge gate sizes pytest's workers to free memory and passes the count in
MARVIN_TEST_WORKERS; lib/affected_tests.py, which now builds the pytest command, must use it."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import affected_tests as at  # noqa: E402


def test_the_gates_worker_count_wins():
    assert at.parallel_args(True, {"MARVIN_TEST_WORKERS": "3"}) == ["-n", "3"]


def test_no_count_means_auto():
    assert at.parallel_args(True, {}) == ["-n", "auto"]


def test_junk_or_zero_counts_fall_back_to_auto_never_to_no_tests():
    for bad in ("", "0", "-2", "auto", "3; rm -rf /", " 4"):
        assert at.parallel_args(True, {"MARVIN_TEST_WORKERS": bad}) == ["-n", "auto"]


def test_without_xdist_it_is_serial_whatever_the_count():
    assert at.parallel_args(False, {"MARVIN_TEST_WORKERS": "3"}) == []
