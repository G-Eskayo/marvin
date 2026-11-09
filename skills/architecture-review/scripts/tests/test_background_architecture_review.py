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


# ── after suggestions move into the inbox (ADR 0083) ──────────────────────────────────────────────────────────


sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "lib"))
import inbox  # noqa: E402
import sort_suggestions as ss  # noqa: E402

EXISTING = "## Old idea\n**Priority**: 4\n**Status**: pending\n**Impact**: speed\n**Effort**: low\n**Why**: w\n**Added**: 2026-10-01\n"
NEW = ("## New idea\n**Priority**: 7\n**Status**: pending\n**Impact**: reliability\n**Effort**: low\n**Why**: found it\n"
       "**What**: fix\n**How**:\n- step\n**Added**: 2026-11-04\n")


@pytest.fixture
def piled(tmp_path, monkeypatch):
    claude = tmp_path / ".claude"
    claude.mkdir()
    md = claude / "suggestions.md"
    md.write_text(EXISTING)
    state = tmp_path / "state"
    monkeypatch.setattr(inbox, "default_root", lambda: claude / "inbox")
    for name, value in (("STATE_DIR", state), ("CURSOR_FILE", state / "chunk-cursor.json"),
                        ("LOCK_FILE", state / ".last-run"), ("LOG_FILE", state / "background-review.log"),
                        ("SUGGESTIONS_FILE", md), ("SNAPSHOT_FILE", state / "suggestions-now.md"),
                        ("STAGING_FILE", state / "new-suggestions.md")):
        monkeypatch.setattr(bar, name, value)
    monkeypatch.setattr(bar, "_resolve_claude_bin", lambda: "/usr/bin/true")
    inbox.import_legacy("suggestions")
    return md


def _fake_claude(monkeypatch, write=None, rc=0):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1:2] == ["-p"]:
            calls_prompt.append(cmd[2])
            if write:
                write()

        class Result:
            returncode = rc
            stdout = ""
            stderr = ""
        return Result()
    calls_prompt: list[str] = []
    monkeypatch.setattr(bar.subprocess, "run", fake_run)
    return calls, calls_prompt


def test_inbox_mode_the_reviewer_writes_a_staging_file_that_is_added_to_the_inbox(piled, monkeypatch):
    calls, prompts = _fake_claude(monkeypatch, write=lambda: bar.STAGING_FILE.write_text(NEW))
    bar.run_review({"name": "handoffs", "paths": []}, "test reason", False)
    titles = [i["title"] for i in inbox.list_items("suggestions")["items"]]
    assert titles == ["New idea", "Old idea"]  # read in priority order
    assert piled.read_text() == EXISTING  # the old file is a read-only backup
    assert not bar.STAGING_FILE.exists()
    assert len(calls) == 1  # no sort_suggestions subprocess in inbox mode
    assert str(bar.STAGING_FILE) in prompts[0] and "Append your findings to ~/.claude/suggestions.md" not in prompts[0]
    assert "## Old idea" in bar.SNAPSHOT_FILE.read_text()  # the reviewer can read what's already there
    assert "1 new suggestion(s) added" in bar.LOG_FILE.read_text()
    assert bar.LOCK_FILE.exists()


def test_inbox_mode_a_rerun_with_the_same_entry_adds_nothing(piled, monkeypatch):
    _fake_claude(monkeypatch, write=lambda: bar.STAGING_FILE.write_text(NEW))
    bar.run_review({"name": "handoffs", "paths": []}, "r", False)
    bar.run_review({"name": "handoffs", "paths": []}, "r", False)
    assert len(inbox.list_items("suggestions")["items"]) == 2


def test_inbox_mode_a_failed_run_keeps_what_it_wrote_but_does_not_advance(piled, monkeypatch):
    _fake_claude(monkeypatch, write=lambda: bar.STAGING_FILE.write_text(NEW), rc=1)
    with pytest.raises(bar.ReviewFailed):  # a failed run still fails loudly (marvin#1123 0.5)
        bar.run_review({"name": "handoffs", "paths": []}, "r", False)
    assert len(inbox.list_items("suggestions")["items"]) == 2
    assert not bar.LOCK_FILE.exists() and not bar.CURSOR_FILE.exists()


def test_inbox_mode_entries_appended_to_the_old_file_by_habit_are_still_added(piled, monkeypatch):
    _fake_claude(monkeypatch, write=lambda: piled.write_text(EXISTING + "\n" + NEW))
    bar.run_review({"name": "handoffs", "paths": []}, "r", False)
    assert sorted(i["title"] for i in inbox.list_items("suggestions")["items"]) == ["New idea", "Old idea"]
    assert "wrote to the old suggestions.md" in bar.LOG_FILE.read_text()


def test_inbox_mode_a_garbage_staging_file_adds_nothing_and_does_not_crash(piled, monkeypatch):
    _fake_claude(monkeypatch, write=lambda: bar.STAGING_FILE.write_bytes(b"\xff\xfe no headers here"))
    bar.run_review({"name": "handoffs", "paths": []}, "r", False)
    assert len(inbox.list_items("suggestions")["items"]) == 1


def test_inbox_mode_a_symlinked_staging_file_is_not_followed(piled, monkeypatch, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text(NEW)
    _fake_claude(monkeypatch, write=lambda: bar.STAGING_FILE.symlink_to(outside))
    bar.run_review({"name": "handoffs", "paths": []}, "r", False)
    assert len(inbox.list_items("suggestions")["items"]) == 1


def test_sort_suggestions_leaves_the_old_file_alone_once_the_inbox_has_it(piled, monkeypatch):
    monkeypatch.setattr(ss, "SUGGESTIONS_FILE", piled)
    piled.write_text(NEW + "\n" + EXISTING)  # unsorted on purpose
    assert ss.sort_suggestions() == -1 and piled.read_text() == NEW + "\n" + EXISTING


def test_sort_suggestions_still_sorts_before_the_import(tmp_path, monkeypatch):
    md = tmp_path / "suggestions.md"
    md.write_text("# S\n\n" + EXISTING + "\n" + NEW)
    monkeypatch.setattr(ss, "SUGGESTIONS_FILE", md)
    assert ss.sort_suggestions() == 2 and md.read_text().index("## New idea") < md.read_text().index("## Old idea")
