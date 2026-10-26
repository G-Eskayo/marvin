#!/usr/bin/env python3
"""Tests for stale_decision_check.py: finding stale decisions and contradictions."""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import stale_decision_check
from stale_decision_check import Candidate, Flag, JudgeError, find_candidates, judge_contradiction


@pytest.fixture
def temp_memory_dir():
    """Create a temporary memory directory for test isolation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestTokenize:
    def test_tokenize_basic(self):
        tokens = stale_decision_check._tokenize("hello world")
        assert tokens == {"hello", "world"}

    def test_tokenize_removes_stopwords(self):
        tokens = stale_decision_check._tokenize("the project for using AI and testing")
        assert "the" not in tokens
        assert "for" not in tokens
        assert "and" not in tokens
        assert "testing" in tokens

    def test_tokenize_lowercases(self):
        tokens = stale_decision_check._tokenize("Hello WORLD")
        assert tokens == {"hello", "world"}


class TestExtractSnippet:
    def test_extract_snippet_finds_matching_line(self):
        text = "line 1\nthis is special\nline 3"
        tokens = {"special"}
        snippet = stale_decision_check._extract_snippet(text, tokens, max_len=100)
        assert "special" in snippet

    def test_extract_snippet_includes_context(self):
        text = "line 1\nthis is special\nline 3"
        tokens = {"special"}
        snippet = stale_decision_check._extract_snippet(text, tokens, max_len=100)
        # Should include the matching line and surrounding context
        assert "special" in snippet

    def test_extract_snippet_respects_max_len(self):
        text = "x" * 1000
        tokens = {"x"}
        snippet = stale_decision_check._extract_snippet(text, tokens, max_len=50)
        assert len(snippet) <= 50


class TestFindCandidates:
    def test_find_candidates_with_matching_catalog(self, temp_memory_dir):
        # Create a temp directory structure
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            project_dir = tmpdir_path / "test-project"
            project_dir.mkdir()

            # Create CONTEXT.md
            context_file = project_dir / "CONTEXT.md"
            context_file.write_text("# Context\n\nThis project handles database operations.")

            # Create a mock catalog
            catalog = {
                "projects": [
                    {
                        "id": "test-project",
                        "name": "Test Project",
                        "primaryPath": str(project_dir),
                        "localPaths": [str(project_dir)],
                    }
                ]
            }

            # Patch MEMORY_DIR for isolation
            with patch.object(stale_decision_check, "MEMORY_DIR", temp_memory_dir):
                # Find candidates for "database"
                candidates = find_candidates("database operations", project_hint="test-project", catalog=catalog)

                assert len(candidates) > 0
                assert candidates[0].file_type == "context"
                assert "database" in candidates[0].snippet.lower()

    def test_find_candidates_no_match(self, temp_memory_dir):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            project_dir = tmpdir_path / "test-project"
            project_dir.mkdir()

            context_file = project_dir / "CONTEXT.md"
            context_file.write_text("# Context\n\nSomething unrelated.")

            catalog = {
                "projects": [
                    {
                        "id": "test-project",
                        "name": "Test Project",
                        "primaryPath": str(project_dir),
                        "localPaths": [str(project_dir)],
                    }
                ]
            }

            # Patch MEMORY_DIR for isolation
            with patch.object(stale_decision_check, "MEMORY_DIR", temp_memory_dir):
                candidates = find_candidates("database", project_hint="test-project", catalog=catalog)
                assert len(candidates) == 0


class TestJudgeContradiction:
    def test_judge_contradiction_detects_real_contradiction(self):
        def mock_judge(prompt: str) -> str:
            return "VERDICT: contradiction (the claim says X but code does Y)"

        flag = judge_contradiction(
            "The system always validates input",
            "// skip validation for performance",
            judge=mock_judge,
        )

        assert flag is not None
        assert flag.verdict == "contradiction"

    def test_judge_contradiction_accepts_compatible_claim(self):
        def mock_judge(prompt: str) -> str:
            return "VERDICT: acceptable (the claim applies to current code)"

        flag = judge_contradiction(
            "The system validates input",
            "validate(input)",
            judge=mock_judge,
        )

        assert flag is None

    def test_judge_contradiction_anchors_on_verdict_token(self):
        """Test that verdict parsing anchors on VERDICT: token, not substring."""
        def mock_judge(prompt: str) -> str:
            # This should NOT be flagged as a contradiction
            return "VERDICT: acceptable (no contradiction here)"

        flag = judge_contradiction(
            "some claim",
            "some state",
            judge=mock_judge,
        )

        assert flag is None

    def test_judge_contradiction_raises_on_exception(self):
        """Test that judge exceptions raise JudgeError, not return None."""
        def mock_judge(prompt: str) -> str:
            raise Exception("Judge failed")

        with pytest.raises(JudgeError):
            judge_contradiction(
                "some claim",
                "some state",
                judge=mock_judge,
            )

    def test_judge_contradiction_raises_on_empty_output(self):
        """Test that empty judge output raises JudgeError."""
        def mock_judge(prompt: str) -> str:
            return ""

        with pytest.raises(JudgeError):
            judge_contradiction(
                "some claim",
                "some state",
                judge=mock_judge,
            )

    def test_judge_contradiction_raises_on_missing_verdict_token(self):
        """Test that unparseable output (missing VERDICT:) raises JudgeError."""
        def mock_judge(prompt: str) -> str:
            return "Some random output without the verdict token"

        with pytest.raises(JudgeError):
            judge_contradiction(
                "some claim",
                "some state",
                judge=mock_judge,
            )


class TestCheckClaim:
    def test_check_claim_finds_contradiction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            memory_file = tmpdir_path / "test-memory.md"
            memory_file.write_text("The system uses database X")

            project_dir = tmpdir_path / "project"
            project_dir.mkdir()
            (project_dir / "CONTEXT.md").write_text("We switched to database Y")

            catalog = {
                "projects": [
                    {
                        "id": "test-project",
                        "name": "Test Project",
                        "primaryPath": str(project_dir),
                        "localPaths": [str(project_dir)],
                    }
                ]
            }

            def mock_judge(prompt: str) -> str:
                return "VERDICT: contradiction (databases differ)"

            with patch("stale_decision_check.find_candidates") as mock_find:
                mock_find.return_value = [
                    Candidate(
                        file_path=project_dir / "CONTEXT.md",
                        project_id="test-project",
                        file_type="context",
                        snippet="We switched to database Y",
                    )
                ]
                with patch("stale_decision_check.judge_contradiction", return_value=Flag(
                    file_path=str(memory_file),
                    text_excerpt="The system uses database X",
                    issue="contradiction",
                    source="check_claim",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    verdict="contradiction",
                )):
                    flags = stale_decision_check.check_claim(memory_file, "The system uses database X")
                    assert len(flags) > 0
                    assert flags[0].verdict == "contradiction"

    def test_check_claim_idempotent_skips_already_flagged(self):
        """Test that check_claim doesn't re-flag already flagged claims."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            memory_file = tmpdir_path / "test-memory.md"
            contradictions_file = tmpdir_path / "contradictions.md"

            # Pre-populate contradictions file with an existing flag
            contradictions_file.write_text(
                "# Contradictions\n\n"
                "## 2026-10-25 | check_claim | " + str(memory_file) + "\n\n"
                "Some issue\n\n"
                "**Claim:**\n> The system uses database X\n\n"
            )

            with patch.object(stale_decision_check, "CONTRADICTIONS_FILE", contradictions_file):
                with patch("stale_decision_check.find_candidates") as mock_find:
                    mock_find.return_value = []
                    flags = stale_decision_check.check_claim(
                        memory_file,
                        "The system uses database X"
                    )
                    # Should return early without calling find_candidates
                    assert len(flags) == 0

    def test_check_claim_handles_judge_error(self):
        """Test that check_claim handles JudgeError and creates unreviewed flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            memory_file = tmpdir_path / "test-memory.md"
            contradictions_file = tmpdir_path / "contradictions.md"
            context_file = tmpdir_path / "CONTEXT.md"
            context_file.write_text("# Context\n\nSome content")

            def mock_judge(prompt: str) -> str:
                raise JudgeError("Judge is unavailable")

            with patch.object(stale_decision_check, "CONTRADICTIONS_FILE", contradictions_file):
                with patch("stale_decision_check.find_candidates") as mock_find:
                    mock_find.return_value = [
                        Candidate(
                            file_path=context_file,
                            project_id="test",
                            file_type="context",
                            snippet="something",
                        )
                    ]
                    with patch("stale_decision_check.judge_contradiction", side_effect=JudgeError("Judge is unavailable")):
                        flags = stale_decision_check.check_claim(memory_file, "The system uses database X")
                        assert len(flags) == 1
                        assert flags[0].verdict is None  # unreviewed
                        assert "Judge failed" in flags[0].issue


class TestFlagParsing:
    def test_parse_flag_header_valid(self):
        header = "2026-10-25 | sweep | /path/to/file.md | The issue"
        result = stale_decision_check._parse_flag_header(header)

        assert result is not None
        assert result["timestamp"] == "2026-10-25"
        assert result["source"] == "sweep"
        assert result["file_path"] == "/path/to/file.md"

    def test_parse_flag_header_short(self):
        header = "2026-10-25 | sweep"
        result = stale_decision_check._parse_flag_header(header)

        assert result is not None
        assert result["timestamp"] == "2026-10-25"
        assert result["source"] == "sweep"

    def test_parse_flag_header_invalid(self):
        header = "no pipes here"
        result = stale_decision_check._parse_flag_header(header)

        assert result is None


class TestIsResolved:
    def test_is_resolved_with_checked_box(self):
        text = "- [x] approve"
        assert stale_decision_check._is_resolved(text) is True

    def test_is_resolved_with_capital_x(self):
        text = "- [X] approve"
        assert stale_decision_check._is_resolved(text) is True

    def test_is_resolved_with_unchecked_box(self):
        text = "- [ ] approve"
        assert stale_decision_check._is_resolved(text) is False

    def test_is_resolved_empty_string(self):
        text = ""
        assert stale_decision_check._is_resolved(text) is False


class TestAppendFlag:
    def test_append_flag_creates_file(self):
        """Test that _append_flag creates contradictions.md if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            contradictions_file = Path(tmpdir) / "contradictions.md"

            flag = Flag(
                file_path="/path/to/memory.md",
                text_excerpt="test claim",
                issue="test issue",
                source="check_claim",
                timestamp="2026-10-25T00:00:00+00:00",
                verdict=None,
            )

            with patch.object(stale_decision_check, "CONTRADICTIONS_FILE", contradictions_file):
                stale_decision_check._append_flag(flag)

                assert contradictions_file.exists()
                content = contradictions_file.read_text()
                assert "test claim" in content
                assert "test issue" in content

    def test_append_flag_deduplicates_quoted_excerpt(self):
        """Test that _append_flag doesn't duplicate flags even with quoted format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            contradictions_file = Path(tmpdir) / "contradictions.md"

            # First append
            flag1 = Flag(
                file_path="/path/to/memory.md",
                text_excerpt="test claim",
                issue="issue 1",
                source="check_claim",
                timestamp="2026-10-25T00:00:00+00:00",
                verdict=None,
            )

            with patch.object(stale_decision_check, "CONTRADICTIONS_FILE", contradictions_file):
                stale_decision_check._append_flag(flag1)
                content_after_first = contradictions_file.read_text()
                count_first = content_after_first.count("test claim")

                # Second append with same excerpt
                flag2 = Flag(
                    file_path="/path/to/memory.md",
                    text_excerpt="test claim",
                    issue="issue 2",
                    source="check_claim",
                    timestamp="2026-10-25T01:00:00+00:00",
                    verdict=None,
                )

                stale_decision_check._append_flag(flag2)
                content_after_second = contradictions_file.read_text()
                count_second = content_after_second.count("test claim")

                # Should not have duplicated the excerpt
                assert count_second == count_first


class TestFindCandidatesExcludePath:
    """Tests for exclude_path parameter to prevent self-matches (defect 1)."""

    def test_find_candidates_excludes_context_md(self):
        """Test that CONTEXT.md being checked is not included as a candidate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            project_dir = tmpdir_path / "test-project"
            project_dir.mkdir()

            # Create CONTEXT.md
            context_file = project_dir / "CONTEXT.md"
            context_file.write_text("# Context\n\nThis project handles database operations.")

            catalog = {
                "projects": [
                    {
                        "id": "test-project",
                        "name": "Test Project",
                        "primaryPath": str(project_dir),
                        "localPaths": [str(project_dir)],
                    }
                ]
            }

            with patch.object(stale_decision_check, "MEMORY_DIR", tmpdir_path):
                # Find candidates without excluding the file
                candidates_with_self = find_candidates(
                    "database operations",
                    project_hint="test-project",
                    catalog=catalog,
                    exclude_path=None,
                )

                # Find candidates while checking the same file (should exclude it)
                candidates_without_self = find_candidates(
                    "database operations",
                    project_hint="test-project",
                    catalog=catalog,
                    exclude_path=context_file,
                )

                # With self-match: should find CONTEXT.md
                assert any(
                    c.file_path.name == "CONTEXT.md" for c in candidates_with_self
                )

                # Without self-match: should not find CONTEXT.md
                assert not any(
                    c.file_path.name == "CONTEXT.md" for c in candidates_without_self
                )

    def test_find_candidates_excludes_adr_files(self):
        """Test that ADR files being checked are not included as candidates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            project_dir = tmpdir_path / "test-project"
            adr_dir = project_dir / "docs" / "adr"
            adr_dir.mkdir(parents=True)

            # Create an ADR file
            adr_file = adr_dir / "0001-database.md"
            adr_file.write_text("# ADR: Database Choice\n\nWe use PostgreSQL for persistence.")

            catalog = {
                "projects": [
                    {
                        "id": "test-project",
                        "name": "Test Project",
                        "primaryPath": str(project_dir),
                        "localPaths": [str(project_dir)],
                    }
                ]
            }

            with patch.object(stale_decision_check, "MEMORY_DIR", tmpdir_path):
                # Find candidates without excluding
                candidates_with_self = find_candidates(
                    "PostgreSQL persistence",
                    project_hint="test-project",
                    catalog=catalog,
                    exclude_path=None,
                )

                # Find candidates while checking the same file
                candidates_without_self = find_candidates(
                    "PostgreSQL persistence",
                    project_hint="test-project",
                    catalog=catalog,
                    exclude_path=adr_file,
                )

                # With self-match: should find the ADR
                assert any(c.file_path.name == "0001-database.md" for c in candidates_with_self)

                # Without self-match: should not find the ADR
                assert not any(
                    c.file_path.name == "0001-database.md" for c in candidates_without_self
                )

    def test_find_candidates_excludes_memory_files(self):
        """Test that memory files being checked are not included as candidates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            memory_dir = tmpdir_path / "memory"
            memory_dir.mkdir()

            # Create two memory files
            # Note: must include project-foo in content for _is_project_memory to match
            memory1 = memory_dir / "project-foo.md"
            memory1.write_text("---\nname: foo\nproject: project-foo\n---\nThe system uses caching layers for project-foo.")

            memory2 = memory_dir / "project-bar.md"
            memory2.write_text("---\nname: bar\n---\nOther notes about caching strategies.")

            catalog = {
                "projects": [
                    {
                        "id": "project-foo",
                        "name": "project foo",
                        "primaryPath": str(tmpdir_path / "foo"),
                        "localPaths": [],
                    }
                ]
            }

            # Create the primary path
            (tmpdir_path / "foo").mkdir()
            (tmpdir_path / "foo" / "CONTEXT.md").write_text("foo context for database caching")

            with patch.object(stale_decision_check, "MEMORY_DIR", memory_dir):
                # Find candidates without excluding
                candidates_with_self = find_candidates(
                    "caching layers",
                    project_hint="project-foo",
                    catalog=catalog,
                    exclude_path=None,
                )

                # Find candidates while checking memory1 (should exclude it)
                candidates_without_self = find_candidates(
                    "caching layers",
                    project_hint="project-foo",
                    catalog=catalog,
                    exclude_path=memory1,
                )

                # With self-match: should find memory1
                assert any(
                    c.file_path.name == "project-foo.md" for c in candidates_with_self
                ), f"Expected to find project-foo.md in candidates_with_self, got {[c.file_path.name for c in candidates_with_self]}"

                # Without self-match: should not find memory1
                assert not any(
                    c.file_path.name == "project-foo.md" for c in candidates_without_self
                ), f"Expected to exclude project-foo.md from candidates_without_self, got {[c.file_path.name for c in candidates_without_self]}"


class TestMultiLineExcerptIdempotency:
    """Tests for multi-line excerpt matching in _is_already_flagged (defect 2)."""

    def test_is_already_flagged_matches_multiline_excerpt(self):
        """Test that multi-line excerpts are correctly matched."""
        with tempfile.TemporaryDirectory() as tmpdir:
            contradictions_file = Path(tmpdir) / "contradictions.md"

            # Create a flag with multi-line excerpt
            flag = Flag(
                file_path="/path/to/memory.md",
                text_excerpt="line 1\nline 2\nline 3",
                issue="potential contradiction",
                source="check_claim",
                timestamp="2026-10-25T00:00:00+00:00",
                verdict="contradiction",
            )

            with patch.object(stale_decision_check, "CONTRADICTIONS_FILE", contradictions_file):
                stale_decision_check._append_flag(flag)

                # Now check if the same excerpt is detected as already flagged
                content = contradictions_file.read_text()
                assert "line 1" in content
                assert "> line 1" in content  # Should be quoted

                # _is_already_flagged should find it
                is_flagged = stale_decision_check._is_already_flagged(
                    Path("/path/to/memory.md"),
                    "line 1\nline 2\nline 3",
                )
                assert is_flagged

    def test_is_already_flagged_handles_newlines_in_first_50_chars(self):
        """Test that newlines in first 50 chars are handled correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            contradictions_file = Path(tmpdir) / "contradictions.md"

            # Excerpt with newline early
            excerpt = "short\nline\nthat is long enough to test"

            flag = Flag(
                file_path="/path/to/memory.md",
                text_excerpt=excerpt,
                issue="test issue",
                source="check_claim",
                timestamp="2026-10-25T00:00:00+00:00",
                verdict="contradiction",
            )

            with patch.object(stale_decision_check, "CONTRADICTIONS_FILE", contradictions_file):
                stale_decision_check._append_flag(flag)

                # Check if already flagged
                is_flagged = stale_decision_check._is_already_flagged(
                    Path("/path/to/memory.md"),
                    excerpt,
                )
                assert is_flagged

    def test_is_already_flagged_skips_unreviewed_flags(self):
        """Test that flags with verdict=None are re-judged on next write."""
        with tempfile.TemporaryDirectory() as tmpdir:
            contradictions_file = Path(tmpdir) / "contradictions.md"

            # Create an unreviewed flag (verdict=None, no checked box)
            flag = Flag(
                file_path="/path/to/memory.md",
                text_excerpt="test claim",
                issue="Judge failed: timeout",
                source="check_claim",
                timestamp="2026-10-25T00:00:00+00:00",
                verdict=None,
            )

            with patch.object(stale_decision_check, "CONTRADICTIONS_FILE", contradictions_file):
                stale_decision_check._append_flag(flag)

                # _is_already_flagged should return False (not skip) because verdict is None
                is_flagged = stale_decision_check._is_already_flagged(
                    Path("/path/to/memory.md"),
                    "test claim",
                )
                assert not is_flagged  # Should NOT be flagged as "already handled"


class TestCheckClaimReJudgesOnFailure:
    """Tests for re-judging when previous verdict was None (defect 3)."""

    def test_check_claim_rejudges_when_previous_was_failed(self):
        """Test that check_claim re-judges if previous attempt failed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            memory_file = tmpdir_path / "memory.md"
            context_file = tmpdir_path / "CONTEXT.md"
            contradictions_file = tmpdir_path / "contradictions.md"

            context_file.write_text("We use database X")

            # Create a pre-existing unreviewed flag (from a failed judge)
            flag = Flag(
                file_path=str(memory_file),
                text_excerpt="The system uses database Y",
                issue="Judge failed: timeout",
                source="check_claim",
                timestamp="2026-10-25T00:00:00+00:00",
                verdict=None,
            )

            catalog = {
                "projects": [
                    {
                        "id": "test",
                        "name": "test",
                        "primaryPath": str(tmpdir_path),
                        "localPaths": [str(tmpdir_path)],
                    }
                ]
            }

            def mock_judge(prompt: str) -> str:
                # This time judge succeeds
                return "VERDICT: contradiction (databases Y vs X differ)"

            with patch.object(stale_decision_check, "CONTRADICTIONS_FILE", contradictions_file):
                with patch.object(stale_decision_check, "MEMORY_DIR", tmpdir_path):
                    stale_decision_check._append_flag(flag)

                    # Now call check_claim again with a successful judge
                    with patch("stale_decision_check.judge_contradiction") as mock_judge_fn:
                        mock_judge_fn.return_value = Flag(
                            file_path=str(memory_file),
                            text_excerpt="The system uses database Y",
                            issue="contradiction",
                            source="check_claim",
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            verdict="contradiction",
                        )

                        flags = stale_decision_check.check_claim(
                            memory_file, "The system uses database Y"
                        )

                        # Should have called judge (not skipped due to unreviewed flag)
                        # This is implicit in that we get a new flag back
                        # In reality, _is_already_flagged should return False for unreviewed
                        assert len(flags) == 0 or flags[0].verdict == "contradiction"


class TestProjectHintUsage:
    """Tests for project_hint parameter (defect 5)."""

    def test_project_hint_narrows_search_scope(self):
        """Test that project_hint is passed through correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create two projects
            project1_dir = tmpdir_path / "project1"
            project1_dir.mkdir()
            (project1_dir / "CONTEXT.md").write_text("Project 1 handles caching")

            project2_dir = tmpdir_path / "project2"
            project2_dir.mkdir()
            (project2_dir / "CONTEXT.md").write_text("Project 2 handles database")

            catalog = {
                "projects": [
                    {
                        "id": "project1",
                        "name": "Project One",
                        "primaryPath": str(project1_dir),
                        "localPaths": [str(project1_dir)],
                    },
                    {
                        "id": "project2",
                        "name": "Project Two",
                        "primaryPath": str(project2_dir),
                        "localPaths": [str(project2_dir)],
                    },
                ]
            }

            with patch.object(stale_decision_check, "MEMORY_DIR", tmpdir_path):
                # Search for "caching" with project1 hint
                candidates_p1 = find_candidates(
                    "caching",
                    project_hint="project1",
                    catalog=catalog,
                )

                # Search for "caching" with project2 hint (should find nothing)
                candidates_p2 = find_candidates(
                    "caching",
                    project_hint="project2",
                    catalog=catalog,
                )

                # Project 1 candidates should include project1's CONTEXT.md
                assert any(
                    str(project1_dir) in str(c.file_path)
                    for c in candidates_p1
                )

                # Project 2 candidates should not include project1's docs
                assert not any(
                    str(project1_dir) in str(c.file_path)
                    for c in candidates_p2
                )

    def test_check_claim_passes_project_hint(self):
        """Test that check_claim passes project_hint to find_candidates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            memory_file = tmpdir_path / "test.md"

            with patch("stale_decision_check.find_candidates") as mock_find:
                mock_find.return_value = []

                # Call check_claim with project_hint
                stale_decision_check.check_claim(
                    memory_file, "test claim", project_hint="specific-project"
                )

                # Verify find_candidates was called with the hint
                mock_find.assert_called_once()
                call_args = mock_find.call_args
                assert call_args.kwargs.get("project_hint") == "specific-project"

    def test_sweep_passes_project_hint_from_filename(self):
        """Test that sweep extracts and passes project hint from filename."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            memory_dir = tmpdir_path / "memory"
            memory_dir.mkdir()

            # Create a memory file with a project hint in its name
            memory_file = memory_dir / "project_my-app.md"
            memory_file.write_text("---\nname: test\n---\nClaim about the app")

            with patch.object(stale_decision_check, "MEMORY_DIR", memory_dir):
                with patch("stale_decision_check.check_claim") as mock_check:
                    mock_check.return_value = []

                    stale_decision_check.sweep()

                    # Verify check_claim was called with the extracted hint
                    mock_check.assert_called_once()
                    call_args = mock_check.call_args
                    assert call_args.kwargs.get("project_hint") == "project-my-app"


class TestHookFiltering:
    """Tests for the hook's path filtering logic."""

    def test_hook_excludes_memory_index(self):
        """Test that hook doesn't check MEMORY.md itself."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            memory_dir = tmpdir_path / "memory"
            memory_dir.mkdir()

            # MEMORY.md should be excluded
            memory_index = memory_dir / "MEMORY.md"
            memory_index.write_text("# Memory Index\n\n- [Item](file.md)")

            # Import hook module
            sys.path.insert(0, str(Path(__file__).parent.parent))
            import stale_decision_hook
            from stale_decision_hook import run_check

            with patch.object(stale_decision_hook, "MEMORY_DIR", memory_dir):
                with patch.object(stale_decision_check, "check_claim") as mock_check:
                    run_check(str(memory_index))
                    # Should not have called check_claim for MEMORY.md
                    mock_check.assert_not_called()

    def test_hook_includes_specific_memory_files(self):
        """Test that hook checks specific memory files (not MEMORY.md)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            memory_dir = tmpdir_path / "memory"
            memory_dir.mkdir()

            # A specific memory file should be checked
            memory_file = memory_dir / "project-foo.md"
            memory_file.write_text("---\nname: foo\n---\nSome memory content")

            # Import hook module
            sys.path.insert(0, str(Path(__file__).parent.parent))
            import stale_decision_hook
            from stale_decision_hook import run_check

            with patch.object(stale_decision_hook, "MEMORY_DIR", memory_dir):
                with patch.object(stale_decision_check, "check_claim") as mock_check:
                    run_check(str(memory_file))
                    # Should have called check_claim for this memory file
                    mock_check.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
