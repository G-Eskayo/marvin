"""Tests for background_architecture_review.py's chunk-path rendering. Run via:
    ~/.agents/venv/bin/python -m pytest skills/architecture-review/scripts/tests/test_background_architecture_review.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import background_architecture_review as bar  # noqa: E402


def test_directory_path_expands_to_its_files_not_a_bare_directory_bullet(tmp_path):
    # G-Eskayo/marvin's suggestions.md priority-2 finding: the reviewer runs
    # with Read/Write/Edit only (no Glob/LS), so a bare directory string is
    # unreadable to it -- Read hits EISDIR and the chunk silently produces
    # zero findings every rotation.
    chunk_dir = tmp_path / "handoffs"
    chunk_dir.mkdir()
    (chunk_dir / "handoff-b.md").write_text("b")
    (chunk_dir / "handoff-a.md").write_text("a")

    rendered = bar._render_chunk_paths([str(chunk_dir) + "/"])

    assert str(chunk_dir) not in rendered.splitlines()[0] or "handoff-a.md" in rendered
    assert str(chunk_dir / "handoff-a.md") in rendered
    assert str(chunk_dir / "handoff-b.md") in rendered
    # sorted, so handoff-a.md's bullet comes before handoff-b.md's
    assert rendered.index("handoff-a.md") < rendered.index("handoff-b.md")


def test_directory_path_includes_files_in_nested_subdirectories(tmp_path):
    chunk_dir = tmp_path / "some-skill"
    (chunk_dir / "scripts" / "tests").mkdir(parents=True)
    (chunk_dir / "SKILL.md").write_text("skill")
    (chunk_dir / "scripts" / "tool.py").write_text("code")
    (chunk_dir / "scripts" / "tests" / "test_tool.py").write_text("test")

    rendered = bar._render_chunk_paths([str(chunk_dir) + "/"])

    assert str(chunk_dir / "SKILL.md") in rendered
    assert str(chunk_dir / "scripts" / "tool.py") in rendered
    assert str(chunk_dir / "scripts" / "tests" / "test_tool.py") in rendered


def test_file_path_is_rendered_as_is_not_expanded(tmp_path):
    a_file = tmp_path / "CLAUDE.md"
    a_file.write_text("hello")

    rendered = bar._render_chunk_paths([str(a_file)])

    assert rendered.strip() == f"- {a_file}"


def test_mixed_files_and_directory_in_the_same_chunk(tmp_path):
    a_file = tmp_path / "CLAUDE.md"
    a_file.write_text("hello")
    chunk_dir = tmp_path / "commands"
    chunk_dir.mkdir()
    (chunk_dir / "caveman.md").write_text("x")

    rendered = bar._render_chunk_paths([str(a_file), str(chunk_dir) + "/"])

    assert f"- {a_file}" in rendered
    assert str(chunk_dir / "caveman.md") in rendered


def test_empty_directory_falls_back_to_the_bare_directory_bullet(tmp_path):
    # No real files to enumerate -- must not render an empty/blank chunk,
    # which would leave the reviewer with nothing to read.
    chunk_dir = tmp_path / "empty-dir"
    chunk_dir.mkdir()

    rendered = bar._render_chunk_paths([str(chunk_dir) + "/"])

    assert rendered.strip() == f"- {chunk_dir}/"


def test_nonexistent_directory_falls_back_to_the_bare_directory_bullet(tmp_path):
    missing = tmp_path / "does-not-exist"

    rendered = bar._render_chunk_paths([str(missing) + "/"])

    assert rendered.strip() == f"- {missing}/"


def test_run_review_uses_rendered_paths_in_the_prompt(tmp_path, monkeypatch):
    chunk_dir = tmp_path / "handoffs"
    chunk_dir.mkdir()
    (chunk_dir / "handoff-a.md").write_text("a")

    monkeypatch.setattr(bar, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(bar, "CURSOR_FILE", tmp_path / "state" / "chunk-cursor.json")
    monkeypatch.setattr(bar, "LOCK_FILE", tmp_path / "state" / ".last-run")
    monkeypatch.setattr(bar, "LOG_FILE", tmp_path / "state" / "background-review.log")
    monkeypatch.setattr(bar, "SUGGESTIONS_FILE", tmp_path / "suggestions.md")
    monkeypatch.setattr(bar, "_resolve_claude_bin", lambda: "/usr/bin/true")

    captured = {}

    def fake_run(cmd, **kwargs):
        if cmd[1:2] == ["-p"]:
            captured["prompt"] = cmd[2]
        class Result:
            returncode = 0
            stderr = ""
        return Result()

    monkeypatch.setattr(bar.subprocess, "run", fake_run)

    bar.run_review({"name": "handoffs", "paths": [str(chunk_dir) + "/"]}, "test reason", False)

    assert str(chunk_dir / "handoff-a.md") in captured["prompt"]


def test_run_review_skips_sort_and_state_update_on_a_nonzero_claude_exit(tmp_path, monkeypatch):
    # A claude -p call that exits non-zero without timing out (rate limit,
    # auth error, immediate crash) must be treated the same as the existing
    # TimeoutExpired branch -- otherwise the chunk is marked reviewed and
    # skipped for a full rotation even though no review actually happened.
    monkeypatch.setattr(bar, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(bar, "CURSOR_FILE", tmp_path / "state" / "chunk-cursor.json")
    monkeypatch.setattr(bar, "LOCK_FILE", tmp_path / "state" / ".last-run")
    monkeypatch.setattr(bar, "LOG_FILE", tmp_path / "state" / "background-review.log")
    monkeypatch.setattr(bar, "SUGGESTIONS_FILE", tmp_path / "suggestions.md")
    monkeypatch.setattr(bar, "_resolve_claude_bin", lambda: "/usr/bin/true")

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class Result:
            returncode = 1
            stderr = ""
        return Result()

    monkeypatch.setattr(bar.subprocess, "run", fake_run)

    import pytest
    with pytest.raises(bar.ReviewFailed):  # and it says so (marvin#1123 0.5)
        bar.run_review({"name": "handoffs", "paths": []}, "test reason", False)

    assert len(calls) == 1  # sort_suggestions.py must never be invoked
    assert not bar.LOCK_FILE.exists()
    assert not bar.CURSOR_FILE.exists()


def test_run_review_still_advances_state_on_a_zero_claude_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(bar, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(bar, "CURSOR_FILE", tmp_path / "state" / "chunk-cursor.json")
    monkeypatch.setattr(bar, "LOCK_FILE", tmp_path / "state" / ".last-run")
    monkeypatch.setattr(bar, "LOG_FILE", tmp_path / "state" / "background-review.log")
    monkeypatch.setattr(bar, "SUGGESTIONS_FILE", tmp_path / "suggestions.md")
    monkeypatch.setattr(bar, "_resolve_claude_bin", lambda: "/usr/bin/true")

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class Result:
            returncode = 0
            stderr = ""
        return Result()

    monkeypatch.setattr(bar.subprocess, "run", fake_run)

    bar.run_review({"name": "handoffs", "paths": []}, "test reason", False)

    assert len(calls) == 2  # claude call + sort_suggestions.py call
    assert bar.LOCK_FILE.exists()


# ── a failed review fails loudly (marvin#1123 0.5) ───────────────────────────
# Found 2026-11-04: on the Mini every run since 11-01 logged "OAuth session expired" and claude exit 1, yet the job
# exited 0 and Health showed it green for four days. A run that didn't review anything must exit non-zero, record a
# hook error, and leave the cursor where it was.

import pytest  # noqa: E402


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(bar, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(bar, "CURSOR_FILE", tmp_path / "state" / "chunk-cursor.json")
    monkeypatch.setattr(bar, "LOCK_FILE", tmp_path / "state" / ".last-run")
    monkeypatch.setattr(bar, "LOG_FILE", tmp_path / "state" / "background-review.log")
    monkeypatch.setattr(bar, "SUGGESTIONS_FILE", tmp_path / "suggestions.md")
    monkeypatch.setattr(bar, "_resolve_claude_bin", lambda: "/usr/bin/true")
    errors = []
    monkeypatch.setattr(bar, "log_hook_error", lambda name, ctx, exc: errors.append((name, ctx, str(exc))))
    return errors


def _claude_says(monkeypatch, returncode, stdout="", stderr=""):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class Result:
            pass
        r = Result()
        r.returncode, r.stdout, r.stderr = returncode, stdout, stderr
        return r
    monkeypatch.setattr(bar.subprocess, "run", fake_run)
    return calls


def _run_main(monkeypatch):
    monkeypatch.setattr(bar, "_cooldown_active", lambda: False)
    monkeypatch.setattr(bar, "pick_chunk", lambda: ({"name": "handoffs", "paths": []}, "test", False))
    with pytest.raises(SystemExit) as exc:
        bar.main()
    return exc.value.code


def test_an_expired_login_makes_the_job_exit_non_zero_and_records_why(tmp_path, monkeypatch):
    errors = _isolate(tmp_path, monkeypatch)
    _claude_says(monkeypatch, 1, stdout="Failed to authenticate: OAuth session expired and could not be refreshed")

    assert _run_main(monkeypatch) == 1
    assert len(errors) == 1
    name, ctx, why = errors[0]
    assert name == "background_architecture_review"
    assert "OAuth session expired" in why
    assert not bar.LOCK_FILE.exists() and not bar.CURSOR_FILE.exists()


def test_a_json_is_error_reply_with_exit_zero_still_fails(tmp_path, monkeypatch):
    # claude -p --output-format json can exit 0 and say is_error: the launcher turns that into exit 1.
    errors = _isolate(tmp_path, monkeypatch)
    _claude_says(monkeypatch, 0, stdout='{"is_error": true, "result": "Not logged in"}')

    assert _run_main(monkeypatch) == 1
    assert "Not logged in" in errors[0][2]


def test_a_timeout_fails_the_job(tmp_path, monkeypatch):
    errors = _isolate(tmp_path, monkeypatch)

    def hang(cmd, **kwargs):
        raise bar.subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
    monkeypatch.setattr(bar.subprocess, "run", hang)

    assert _run_main(monkeypatch) == 1
    assert "timed out" in errors[0][2]
    assert not bar.LOCK_FILE.exists()


def test_claude_missing_fails_the_job(tmp_path, monkeypatch):
    errors = _isolate(tmp_path, monkeypatch)

    def missing():
        raise FileNotFoundError("claude not found")
    monkeypatch.setattr(bar, "_resolve_claude_bin", missing)

    assert _run_main(monkeypatch) == 1
    assert "claude not found" in errors[0][2]


def test_a_crash_picking_the_chunk_fails_the_job(tmp_path, monkeypatch):
    errors = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(bar, "_cooldown_active", lambda: False)

    def boom():
        raise ValueError("cursor file is garbage")
    monkeypatch.setattr(bar, "pick_chunk", boom)
    with pytest.raises(SystemExit) as exc:
        bar.main()
    assert exc.value.code == 1
    assert errors[0][1] == "picking chunk"


def test_a_good_run_exits_zero_and_records_nothing(tmp_path, monkeypatch):
    errors = _isolate(tmp_path, monkeypatch)
    _claude_says(monkeypatch, 0, stdout='{"result": "reviewed", "is_error": false}')
    monkeypatch.setattr(bar, "_cooldown_active", lambda: False)
    monkeypatch.setattr(bar, "pick_chunk", lambda: ({"name": "handoffs", "paths": []}, "test", False))

    bar.main()  # no SystemExit

    assert errors == []
    assert bar.LOCK_FILE.exists()


def test_the_cooldown_skip_is_not_a_failure(tmp_path, monkeypatch):
    errors = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(bar, "_cooldown_active", lambda: True)
    bar.main()
    assert errors == []


def test_the_failure_and_its_reason_reach_the_job_log(tmp_path, monkeypatch):
    # The dashboard reads job_events, not launchd's exit code: the run must be recorded failed there, with the reason.
    import json
    import job_events
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(job_events, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.delenv("XPC_SERVICE_NAME", raising=False)
    _claude_says(monkeypatch, 1, stdout="Failed to authenticate: OAuth session expired")
    _run_main(monkeypatch)
    run = json.loads((tmp_path / "jobs" / "architecture-review.json").read_text())["runs"][-1]
    assert run["status"] == "failed"
    assert "OAuth session expired" in run["error"]
