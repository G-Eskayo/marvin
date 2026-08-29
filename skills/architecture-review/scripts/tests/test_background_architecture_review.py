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
    # which would leave the reviewer with literally nothing to read.
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
        if cmd[0] == "/usr/bin/true":
            captured["prompt"] = cmd[2]
        class Result:
            returncode = 0
            stderr = ""
        return Result()

    monkeypatch.setattr(bar.subprocess, "run", fake_run)

    bar.run_review({"name": "handoffs", "paths": [str(chunk_dir) + "/"]}, "test reason", False)

    assert str(chunk_dir / "handoff-a.md") in captured["prompt"]
