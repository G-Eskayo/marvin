"""job_report.py (#1123, ADR 0083): any scheduled job becomes an honest job_events run. Tries to break it: a refusal
that exits 0, an error-skip, an intentional skip, a crash, a kill, a missing program, a flood of output, binary junk,
output on stderr only, a bad job name."""
from __future__ import annotations
import io
import json
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import job_report as jr  # noqa: E402

PY = sys.executable


def _run(tmp_path, code, job="nightly"):
    out, err = io.StringIO(), io.StringIO()
    rc = jr.run(job, [PY, "-c", code], directory=tmp_path, out=out, err=err)
    doc = json.loads((tmp_path / f"{job}.json").read_text()) if (tmp_path / f"{job}.json").exists() else None
    return rc, (doc["runs"][-1] if doc else None), out.getvalue(), err.getvalue()


def test_a_clean_run_passes_and_its_output_still_reaches_the_launchd_logs(tmp_path):
    rc, run, out, err = _run(tmp_path, "import sys; print('hello'); print('warn', file=sys.stderr)")
    assert rc == 0 and run["status"] == "passed" and out == "hello\n" and err == "warn\n"


def test_a_refusal_that_exits_zero_is_a_failed_run(tmp_path):
    rc, run, *_ = _run(tmp_path, "print('REFUSING to run: conflict markers in lexicon.md')")
    assert rc == 0 and run["status"] == "failed" and "REFUSING" in run["error"]


def test_a_refusal_on_stderr_with_a_timestamp_prefix_is_caught(tmp_path):
    _, run, *_ = _run(tmp_path, "import sys; print('[12:00] REFUSING to push', file=sys.stderr)")
    assert run["status"] == "failed"


@pytest.mark.parametrize("line, failed", [
    ("skipped: the Mini already built today's digest", False),
    ("Skipping: nothing to do", False),
    ("skipped because the token check failed", True),
    ("skipping research: OAuth error 401", True),
    ("the word refusing in lower case is not a refusal", False),
])
def test_only_a_skip_caused_by_an_error_fails(tmp_path, line, failed):
    _, run, *_ = _run(tmp_path, f"print({line!r})")
    assert (run["status"] == "failed") is failed


def test_a_non_zero_exit_fails_with_the_last_line_and_passes_the_status_on(tmp_path):
    rc, run, *_ = _run(tmp_path, "print('step 1'); print('boom: no disk'); raise SystemExit(3)")
    assert rc == 3 and run["status"] == "failed" and run["error"] == "exited with status 3: boom: no disk"


def test_a_killed_job_is_a_failure_with_a_shell_style_status(tmp_path):
    rc, run, *_ = _run(tmp_path, "import os, signal; os.kill(os.getpid(), signal.SIGKILL)")
    assert rc == 137 and run["status"] == "failed"


def test_a_missing_program_is_recorded_not_raised(tmp_path):
    rc = jr.run("nightly", ["/nonexistent/prog"], directory=tmp_path, out=io.StringIO(), err=io.StringIO())
    run = json.loads((tmp_path / "nightly.json").read_text())["runs"][-1]
    assert rc == 127 and run["status"] == "failed" and "could not start" in run["error"]


def test_a_flood_of_output_and_binary_junk_stream_through(tmp_path):
    rc, run, out, _ = _run(tmp_path, "import sys\nfor i in range(20000): print('x' * 50)\nsys.stdout.buffer.write(b'\\xff\\xfe\\x00 end\\n')")
    assert rc == 0 and run["status"] == "passed" and out.count("\n") == 20001 and len(run["summary"]) <= 200


@pytest.mark.parametrize("job", ["", "../etc", "A", "a b", "x" * 80, "nightly;rm"])
def test_a_bad_job_name_writes_nothing_anywhere(tmp_path, job):
    assert jr.run(job, ["/bin/true"], directory=tmp_path) == 2
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("argv", [[], ["job"], ["job", "--"], ["a", "b", "--", "/bin/true"]])
def test_the_cli_refuses_a_malformed_call(argv):
    assert jr.main(argv) == 2
