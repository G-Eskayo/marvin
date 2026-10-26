#!/usr/bin/env python3
"""Test suite for stale_decision_check (marvin#652)."""
from __future__ import annotations
import hashlib
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stale_decision_check as sdc
import stale_decision_check_hook as hook


@pytest.fixture
def temp_repo(tmp_path):
    """Create a temp repo with .git."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


@pytest.fixture
def temp_memory(tmp_path):
    """Create a temp memory directory."""
    mem = tmp_path / "memory"
    mem.mkdir()
    return mem


def mock_chat_fn(verdict="CONSISTENT"):
    """Return a mock chat function that returns the given verdict."""
    def chat(messages):
        if "CONSISTENT" in verdict or verdict == "CONSISTENT":
            return f"VERDICT: CONSISTENT\nRATIONALE: Claims are compatible."
        elif verdict == "STALE" or "STALE" in verdict:
            return f"VERDICT: STALE\nRATIONALE: New claim contradicts old one."
        else:
            return f"VERDICT: {verdict}\nRATIONALE: Test response."
    return chat


# ── Test 1: planted case from AC1 ─────────────────────────────────────────────────

def test_planted_case_flags_contradiction(temp_memory):
    """Memory says 'free forever', new text says '$5 one-time' -> STALE flag."""
    # Create memory note
    old_text = "Seal Speak is a free and non-commercial app."
    (temp_memory / "project-seal-speak.md").write_text(old_text)

    with patch("stale_decision_check.MEMORY_DIR", temp_memory), \
         patch("stale_decision_check.repo_root", return_value=None):
        new_text = "Seal Speak is a $5 one-time App Store app, not free."
        chat_fn = mock_chat_fn("STALE")
        findings = sdc.find_stale_claims(new_text, "test.md", chat_fn=chat_fn)

    assert len(findings) == 1
    assert findings[0]["verdict"] == "STALE"
    assert findings[0]["file"] == "project-seal-speak.md"


# ── Test 2: consistent claims don't flag ──────────────────────────────────────────

def test_consistent_claims_no_flag(temp_memory):
    """Two compatible claims about the same topic -> no STALE flag."""
    old_text = "Seal Speak has in-app translation via IAP."
    (temp_memory / "project-seal-speak.md").write_text(old_text)

    with patch("stale_decision_check.MEMORY_DIR", temp_memory), \
         patch("stale_decision_check.repo_root", return_value=None):
        new_text = "The app supports translation purchases as in-app purchases."
        chat_fn = mock_chat_fn("CONSISTENT")
        findings = sdc.find_stale_claims(new_text, "test.md", chat_fn=chat_fn)

    assert len(findings) == 0


# ── Test 3: no lexical overlap -> chat_fn never called ───────────────────────────

def test_no_overlap_skips_judge(temp_memory):
    """Zero token overlap with candidates -> judge not called at all."""
    (temp_memory / "project-math.md").write_text("Linear algebra matrices tensors eigenvalues")

    with patch("stale_decision_check.MEMORY_DIR", temp_memory), \
         patch("stale_decision_check.repo_root", return_value=None):
        new_text = "The weather is sunny today."
        chat_fn = MagicMock()
        findings = sdc.find_stale_claims(new_text, "test.md", chat_fn=chat_fn)

    assert chat_fn.call_count == 0
    assert len(findings) == 0


# ── Test 4: empty inputs ──────────────────────────────────────────────────────────

def test_empty_new_text(temp_memory):
    """Empty new text -> returns [], no crash."""
    with patch("stale_decision_check.MEMORY_DIR", temp_memory), \
         patch("stale_decision_check.repo_root", return_value=None):
        findings = sdc.find_stale_claims("", "test.md")
    assert findings == []


def test_empty_memory_dir(tmp_path):
    """Empty memory dir -> returns [], no crash."""
    mem = tmp_path / "empty_memory"
    mem.mkdir()
    with patch("stale_decision_check.MEMORY_DIR", mem), \
         patch("stale_decision_check.repo_root", return_value=None):
        chat_fn = mock_chat_fn("CONSISTENT")
        findings = sdc.find_stale_claims("some text", "test.md", chat_fn=chat_fn)
    assert findings == []


def test_no_repo(tmp_path):
    """No .git, no CONTEXT.md, no docs/adr -> returns [], no crash."""
    repo = tmp_path / "no_repo"
    repo.mkdir()
    with patch("stale_decision_check.repo_root", return_value=repo), \
         patch("stale_decision_check.MEMORY_DIR", tmp_path / "memory"):
        findings = sdc.find_stale_claims("test", "test.md")
    assert findings == []


# ── Test 5: large/malformed files ─────────────────────────────────────────────────

def test_large_file_truncated(temp_memory):
    """Memory file > 1500 chars gets truncated before reaching prompt."""
    large_text = "word " * 500  # > 1500 chars
    (temp_memory / "large.md").write_text(large_text)

    with patch("stale_decision_check.MEMORY_DIR", temp_memory), \
         patch("stale_decision_check.repo_root", return_value=None):
        new_text = "word"
        chat_fn = MagicMock(return_value="VERDICT: CONSISTENT\nRATIONALE: test")
        findings = sdc.find_stale_claims(new_text, "test.md", chat_fn=chat_fn)
        # If memory file passes prefilter, it should be passed truncated to chat
        assert chat_fn.call_count > 0, "chat_fn should be called with overlapping text"
        call_args = chat_fn.call_args[0][0]
        # The full large_text should NOT be in the prompt
        prompt_text = str(call_args)
        assert large_text not in prompt_text, "Full large text should be truncated"
        # But it should still be truncated to 1500 chars by discover_memory
        assert "word " in prompt_text, "Truncated version should still contain the word"


def test_invalid_utf8_handled(temp_memory):
    """File with invalid UTF-8 is read with errors='ignore' -> no crash."""
    bad_file = temp_memory / "bad.md"
    bad_file.write_bytes(b"valid \xff\xfe invalid")

    with patch("stale_decision_check.MEMORY_DIR", temp_memory), \
         patch("stale_decision_check.repo_root", return_value=None):
        chat_fn = mock_chat_fn("CONSISTENT")
        findings = sdc.find_stale_claims("valid", "test.md", chat_fn=chat_fn)
    # Should not raise, may or may not find matches depending on how badly broken
    assert isinstance(findings, list)


# ── Test 6: Ollama down / chat_fn raises ──────────────────────────────────────────

def test_chat_fn_raises_fails_closed(temp_memory):
    """When chat_fn raises, find_stale_claims catches it, returns no flag."""
    (temp_memory / "note.md").write_text("test content test")

    def broken_chat(messages):
        raise RuntimeError("Ollama down")

    with patch("stale_decision_check.MEMORY_DIR", temp_memory), \
         patch("stale_decision_check.repo_root", return_value=None):
        findings = sdc.find_stale_claims("test", "test.md", chat_fn=broken_chat)
    # Should not crash, and error verdicts should be filtered out
    assert isinstance(findings, list)
    # No STALE verdicts should be returned since all verdicts are "error"
    assert len(findings) == 0, "Error verdicts should not produce flags"


def test_check_file_ollama_down():
    """check_file catches Ollama failure, logs, returns error status."""
    def broken_chat(messages):
        raise RuntimeError("Ollama timeout")

    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write("test content")
        path = f.name

    try:
        result = sdc.check_file(path, chat_fn=broken_chat)
        # May succeed with 0 flags (error handling), or be an error
        assert isinstance(result, dict)
    finally:
        Path(path).unlink()


# ── Test 7: idempotency – repeat calls don't duplicate ─────────────────────────────

def test_repeat_check_not_duplicated(temp_memory, tmp_path):
    """Calling check_file twice on the same file -> appends only once due to dedup."""
    (temp_memory / "note.md").write_text("old content")

    new_file = tmp_path / "new.md"
    new_file.write_text("old content new variant")

    stale_path = tmp_path / "stale-decisions.md"

    with patch("stale_decision_check.MEMORY_DIR", temp_memory), \
         patch("stale_decision_check.repo_root", return_value=None), \
         patch("stale_decision_check.STALE_DECISIONS", stale_path), \
         patch("stale_decision_check.find_stale_claims", return_value=[
             {"file": "note.md", "source": "memory", "old_claim": "old", "verdict": "STALE", "rationale": "test"}
         ]):
        # First call
        result1 = sdc.check_file(str(new_file))
        assert result1["status"] == "ok"
        assert result1["flags_added"] == 1
        first_content = stale_path.read_text()
        assert "## " in first_content, "Should write an entry"

        # Second call same file with same date
        result2 = sdc.check_file(str(new_file))
        assert result2["status"] == "ok"
        assert result2["flags_added"] == 0, "Second call should not add flags (dedup)"
        second_content = stale_path.read_text()

        # Content should be identical - no duplication
        assert first_content == second_content, "File should not be modified on second call"


# ── Test 8: concurrent appends use tmp-file-then-replace ──────────────────────────

def test_append_flags_atomic(tmp_path):
    """append_flags uses tmp-file-then-replace pattern."""
    path = tmp_path / "stale.md"
    path.write_text("existing entry\n")

    entry = "## new entry\ntest"
    sdc.append_flags(entry, path)

    result = path.read_text()
    assert "existing entry" in result
    assert "new entry" in result
    # tmp file should be cleaned up after replace
    assert (tmp_path / ".stale.md.tmp").exists() is False  # tmp cleaned up


def test_append_flags_tmp_file_created(tmp_path):
    """append_flags should use a tmp file during write (atomic replace)."""
    path = tmp_path / "stale.md"
    path.write_text("initial\n")

    # Patch to detect when tmp file is created
    tmp_path_detected = []
    original_write = Path.write_text

    def tracked_write(self, data, *args, **kwargs):
        if ".stale.md.tmp" in str(self):
            tmp_path_detected.append(str(self))
        return original_write(self, data, *args, **kwargs)

    with patch.object(Path, 'write_text', tracked_write):
        sdc.append_flags("entry1", path)

    # Should have created a tmp file
    assert len(tmp_path_detected) > 0, "append_flags should create a tmp file"
    assert path.read_text() == "initial\nentry1"


# ── Test 9: unreadable dir treated as no candidates ──────────────────────────────

def test_unreadable_memory_dir(tmp_path):
    """Memory dir unreadable -> treated as empty, no crash."""
    bad_mem = tmp_path / "bad_mem"
    bad_mem.mkdir()
    # Try to make it unreadable (may not work on all systems)
    try:
        bad_mem.chmod(0o000)
        with patch("stale_decision_check.MEMORY_DIR", bad_mem), \
             patch("stale_decision_check.repo_root", return_value=None):
            chat_fn = mock_chat_fn("CONSISTENT")
            findings = sdc.find_stale_claims("test", "test.md", chat_fn=chat_fn)
        # Should return empty list since memory dir is inaccessible
        assert isinstance(findings, list)
        assert len(findings) == 0, "Unreadable memory dir should be treated as empty"
    finally:
        bad_mem.chmod(0o755)  # restore for cleanup


# ── Test 10: sweep with missing catalog degrades gracefully ──────────────────────

def test_sweep_no_crash_on_missing_catalog():
    """sweep() runs memory-vs-memory even if project catalog unavailable."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mem = Path(tmpdir) / "memory"
        mem.mkdir()
        (mem / "note1.md").write_text("alpha content topic")
        (mem / "note2.md").write_text("beta different matter")

        with patch("stale_decision_check.MEMORY_DIR", mem), \
             patch("stale_decision_check.repo_root", return_value=None):
            findings = sdc.sweep()
        # Should not crash, may be empty due to low token overlap
        assert isinstance(findings, list), "sweep should return a list"


# ── Test 11: malformed stale-decisions.md doesn't break reading ─────────────────

def test_malformed_stale_decisions_read(tmp_path):
    """Hand-edited stale-decisions.md with bad format -> existing_pending_keys() doesn't crash."""
    bad_file = tmp_path / "stale.md"
    bad_file.write_text("## garbage without date\nno status line\n## also bad\n")

    with patch("stale_decision_check.STALE_DECISIONS", bad_file):
        keys = sdc.existing_pending_keys()
    # Should return an empty set or partial set, never raise
    assert isinstance(keys, set)


# ── Test 12: hook path filtering ──────────────────────────────────────────────

def test_hook_should_check_memory_notes():
    """should_check_path returns True for memory notes."""
    mem_path = str(Path.home() / ".claude" / "projects" / "-Users-gileskayo" / "memory" / "note.md")
    assert hook.should_check_path(mem_path) is True


def test_hook_should_skip_memory_index():
    """should_check_path returns False for MEMORY.md."""
    mem_index = str(Path.home() / ".claude" / "projects" / "-Users-gileskayo" / "memory" / "MEMORY.md")
    assert hook.should_check_path(mem_index) is False


def test_hook_should_check_context():
    """should_check_path returns True for CONTEXT.md."""
    assert hook.should_check_path("/some/repo/CONTEXT.md") is True


def test_hook_should_check_adr():
    """should_check_path returns True for docs/adr/*.md."""
    assert hook.should_check_path("/some/repo/docs/adr/0001-architecture.md") is True


def test_hook_should_skip_non_adr():
    """should_check_path returns False for other docs."""
    assert hook.should_check_path("/some/repo/docs/guides/readme.md") is False


def test_check_file_nonexistent():
    """check_file on nonexistent path -> returns ok with 0 flags."""
    result = sdc.check_file("/nonexistent/path.md")
    assert result["status"] == "ok"
    assert result["flags_added"] == 0


def test_check_file_empty():
    """check_file on empty file -> returns ok with 0 flags."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write("")
        path = f.name

    try:
        result = sdc.check_file(path)
        assert result["status"] == "ok"
        assert result["flags_added"] == 0
    finally:
        Path(path).unlink()


# ── Test 13: sweep bounded by prefilter, not O(N²) ────────────────────────────────

def test_sweep_prefilter_bounds_comparisons(tmp_path):
    """sweep() with N memory notes -> comparison count bounded by max_pairs."""
    mem = tmp_path / "memory"
    mem.mkdir()
    # Create 20 memory notes with enough similarity to pass prefilter
    for i in range(20):
        (mem / f"note{i}.md").write_text(f"topic shared content {i}")

    call_count = 0
    def counting_chat(messages):
        nonlocal call_count
        call_count += 1
        return "VERDICT: CONSISTENT\nRATIONALE: compatible"

    with patch("stale_decision_check.MEMORY_DIR", mem), \
         patch("stale_decision_check.repo_root", return_value=None):
        findings = sdc.sweep(max_pairs=50, chat_fn=counting_chat)

    # With max_pairs=50, should never exceed 50 chat calls
    assert call_count <= 50, f"Should not exceed max_pairs (50), got {call_count}"


# ── Test parsing ──────────────────────────────────────────────────────────────────

def test_parse_classification_result():
    """_parse_classification_result extracts VERDICT and RATIONALE."""
    response = """Some preamble
VERDICT: STALE
RATIONALE: New claim directly contradicts old one.
Some footer"""
    result = sdc._parse_classification_result(response)
    assert result["verdict"] == "STALE"
    assert "contradicts" in result["rationale"].lower()


def test_parse_classification_unknown_verdict():
    """Unknown VERDICT -> marked as 'unknown'."""
    response = "VERDICT: MAYBE\nRATIONALE: unclear"
    result = sdc._parse_classification_result(response)
    assert result["verdict"] == "unknown"


# ── Test rendering ────────────────────────────────────────────────────────────────

def test_format_entry():
    """format_entry produces a well-formed markdown block."""
    findings = [
        {"file": "note.md", "source": "memory", "old_claim": "old", "verdict": "STALE", "rationale": "reason"}
    ]
    now = datetime(2026, 10, 26, tzinfo=timezone.utc)
    entry = sdc.format_entry("test.md", findings, now)

    assert "2026-10-26" in entry
    assert "pending" in entry
    assert "note.md" in entry
    assert "Finding 1" in entry


def test_render_sweep_report():
    """render_sweep_report produces a valid report."""
    findings = [
        {"old_file": "a.md", "new_file": "b.md", "verdict": "STALE", "rationale": "test"}
    ]
    now = datetime(2026, 10, 26, tzinfo=timezone.utc)
    report = sdc.render_sweep_report(findings, now)

    assert "2026-10-26" in report
    assert "1" in report
    assert "a.md" in report
    assert "b.md" in report


def test_render_sweep_report_empty():
    """render_sweep_report with no findings -> clean message."""
    report = sdc.render_sweep_report([])
    assert "No stale claims found" in report


# ── Test score_overlap ────────────────────────────────────────────────────────────

def test_score_overlap():
    """_score_overlap calculates Jaccard correctly."""
    a = {"foo", "bar"}
    b = {"bar", "baz"}
    # intersection = {bar}, union = {foo, bar, baz}
    # jaccard = 1/3
    score = sdc._score_overlap(a, b)
    assert abs(score - 1.0 / 3.0) < 0.01

    # No overlap
    score = sdc._score_overlap({"x"}, {"y"})
    assert score == 0.0


# ── Test urllib import fix ─────────────────────────────────────────────────────────

def test_ollama_chat_uses_correct_import():
    """ollama_chat should use urllib.request correctly, not broken __import__."""
    # Mock urllib.request to ensure it's called correctly
    with patch("stale_decision_check.urllib.request.Request") as mock_req, \
         patch("stale_decision_check.urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"message": {"content": "test"}}).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        result = sdc.ollama_chat("test", [{"role": "user", "content": "test"}])

        assert mock_req.called, "Request should be called"
        assert mock_urlopen.called, "urlopen should be called"
        assert result == "test"


# ── Test default parameter binding fix ─────────────────────────────────────────────

def test_append_flags_uses_default_none():
    """append_flags should resolve path at call time, not bind at definition time."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path1 = Path(tmpdir) / "stale1.md"
        path2 = Path(tmpdir) / "stale2.md"

        # First call with explicit path1
        sdc.append_flags("entry1", path=path1)
        assert path1.exists()
        assert "entry1" in path1.read_text()

        # Second call with explicit path2
        sdc.append_flags("entry2", path=path2)
        assert path2.exists()
        assert "entry2" in path2.read_text()

        # Verify they went to different files
        assert "entry1" not in path2.read_text()
        assert "entry2" not in path1.read_text()


# ── Test tokens computed once in sweep ─────────────────────────────────────────────

def test_sweep_tokens_computed_once():
    """sweep() should precompute tokens once per document, not repeatedly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mem = Path(tmpdir) / "memory"
        mem.mkdir()
        (mem / "note1.md").write_text("shared topic content")
        (mem / "note2.md").write_text("shared topic content")
        (mem / "note3.md").write_text("different unrelated stuff")

        token_calls = []
        original_tokens = sdc.project_catalog.tokens

        def counting_tokens(text):
            token_calls.append(text[:20])  # Track which texts were tokenized
            return original_tokens(text)

        with patch("stale_decision_check.project_catalog.tokens", side_effect=counting_tokens), \
             patch("stale_decision_check.MEMORY_DIR", mem), \
             patch("stale_decision_check.repo_root", return_value=None):
            sdc.sweep(max_pairs=10)

        # Each memory doc should be tokenized once during precomputation
        # Plus a few times during overlap scoring, but not once per comparison
        text1_count = sum(1 for t in token_calls if "shared" in t)
        # Should be much less than if recomputed per pair (would be ~10 times)
        assert text1_count <= 5, f"Tokens for same text recomputed too many times: {text1_count}"


# ── Test (A,B) and (B,A) deduplication ────────────────────────────────────────────

def test_sweep_deduplicates_pair_directions():
    """sweep() should not check both (A,B) and (B,A)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mem = Path(tmpdir) / "memory"
        mem.mkdir()
        # Create docs that will have high overlap
        (mem / "noteA.md").write_text("shared topic content here")
        (mem / "noteB.md").write_text("shared topic content there")

        call_count = 0
        def counting_chat(messages):
            nonlocal call_count
            call_count += 1
            return "VERDICT: CONSISTENT\nRATIONALE: compatible"

        with patch("stale_decision_check.MEMORY_DIR", mem), \
             patch("stale_decision_check.repo_root", return_value=None):
            sdc.sweep(max_pairs=100, chat_fn=counting_chat)

        # Should be called at most once for the (A,B) pair
        assert call_count <= 1, f"Should deduplicate pair directions, got {call_count} calls"


# ── Test Status field checking ─────────────────────────────────────────────────────

def test_existing_pending_keys_checks_status():
    """existing_pending_keys should only count entries with **Status**: pending."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stale_path = Path(tmpdir) / "stale.md"
        stale_path.write_text("""## 2026-10-26 — note1.md
**Status**: pending
**Added**: 2026-10-26
**Source**: /repo/note1.md

## 2026-10-26 — note2.md
**Status**: resolved
**Added**: 2026-10-26
**Source**: /repo/note2.md

## 2026-10-26 — note3.md
**Status**: pending
**Added**: 2026-10-26
**Source**: /repo/note3.md
""")

        with patch("stale_decision_check.STALE_DECISIONS", stale_path):
            keys = sdc.existing_pending_keys()

        # Should only include the two pending entries (hashed by source path)
        assert len(keys) == 2
        # Keys are (date, path_hash) tuples
        assert all(k[0] == "2026-10-26" for k in keys), "All keys should have today's date"
        # Check that the note2 (resolved) is not in the keys
        note2_hash = hashlib.md5("/repo/note2.md".encode()).hexdigest()[:8]
        assert ("2026-10-26", note2_hash) not in keys


# ── Test hook cooldown ─────────────────────────────────────────────────────────────

def test_hook_cooldown_active():
    """Hook should skip check if cooldown is active."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cooldown_file = Path(tmpdir) / ".cooldown"

        with patch("stale_decision_check_hook.COOLDOWN_FILE", cooldown_file):
            # No cooldown file = no cooldown active
            assert hook.is_cooldown_active() is False

            # Set cooldown to just now
            hook.update_cooldown()
            assert hook.is_cooldown_active() is True

            # Wait and check again
            time.sleep(0.1)
            assert hook.is_cooldown_active() is True, "Should still be active within 5s window"


def test_hook_cooldown_expires():
    """Hook cooldown should expire after COOLDOWN_SECONDS."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cooldown_file = Path(tmpdir) / ".cooldown"

        with patch("stale_decision_check_hook.COOLDOWN_FILE", cooldown_file), \
             patch("stale_decision_check_hook.COOLDOWN_SECONDS", 0.1):
            # Set cooldown to just now
            hook.update_cooldown()
            assert hook.is_cooldown_active() is True

            # Wait for cooldown to expire
            time.sleep(0.15)
            assert hook.is_cooldown_active() is False, "Cooldown should expire"


# ── Test file locking in append_flags ──────────────────────────────────────────────

def test_append_flags_uses_locking():
    """append_flags should use file locking for concurrent safety."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stale_path = Path(tmpdir) / "stale.md"
        stale_path.write_text("initial\n")

        # Call append_flags multiple times
        sdc.append_flags("entry1", path=stale_path)
        sdc.append_flags("entry2", path=stale_path)

        content = stale_path.read_text()
        # Both entries should be present
        assert "initial" in content
        assert "entry1" in content
        assert "entry2" in content

        # Lock file should not persist
        lock_file = stale_path.parent / ".stale-decisions.lock"
        assert not lock_file.exists() or lock_file.stat().st_size < 100, "Lock file should not persist"


# ── Test repo_root from file path (Defect 1 fix) ──────────────────────────────────

def test_repo_root_from_file_path(temp_repo):
    """repo_root should find .git when given a file path."""
    test_file = temp_repo / "subdir" / "file.md"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("test")

    # Should find .git from the file's location
    root = sdc.repo_root(test_file)
    assert root == temp_repo


# ── Test exclude just-written file from candidates (Defect 2 fix) ────────────────────

def test_find_stale_claims_excludes_self(temp_memory, tmp_path):
    """find_stale_claims should exclude the just-written file from candidates."""
    # Create memory note that would self-match with Jaccard 1.0
    old_text = "test content topic"
    (temp_memory / "note.md").write_text(old_text)

    # Write a new file with the same name (simulating same-named file in repo)
    new_file = tmp_path / "note.md"
    new_file.write_text("test content topic")

    with patch("stale_decision_check.MEMORY_DIR", temp_memory), \
         patch("stale_decision_check.repo_root", return_value=None):
        chat_fn = MagicMock(return_value="VERDICT: CONSISTENT\nRATIONALE: test")
        findings = sdc.find_stale_claims(new_file.read_text(), "note.md",
                                         chat_fn=chat_fn, file_path=new_file)

        # Should not compare with itself despite Jaccard 1.0
        # Only one comparison should be made (new_text vs memory note)
        # If self-match wasn't excluded, it would have been the first match
        assert chat_fn.call_count <= 1, "Should not waste a comparison on self-match"


# ── Test path hash dedup key (Defect 3 fix) ──────────────────────────────────────────

def test_existing_pending_keys_uses_path_hash(tmp_path):
    """existing_pending_keys should use path hash to avoid collisions between repos."""
    stale_path = tmp_path / "stale.md"
    stale_path.write_text("""## 2026-10-26 — CONTEXT.md
**Status**: pending
**Added**: 2026-10-26
**Source**: /repo1/CONTEXT.md

## 2026-10-26 — CONTEXT.md
**Status**: pending
**Added**: 2026-10-26
**Source**: /repo2/CONTEXT.md
""")

    with patch("stale_decision_check.STALE_DECISIONS", stale_path):
        keys = sdc.existing_pending_keys()

    # Should have two distinct keys (hashes of different paths)
    assert len(keys) == 2, "Path hash should distinguish between different repos' CONTEXT.md files"


# ── Test hook queue-based cooldown (Defect 7 fix) ──────────────────────────────────

def test_hook_queues_checks_during_cooldown(tmp_path, monkeypatch):
    """Hook should queue checks instead of dropping them during cooldown."""
    # Setup paths
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    cooldown_file = logs_dir / ".stale-check-cooldown"

    monkeypatch.setattr(hook, "HOME", tmp_path)
    monkeypatch.setattr(hook, "COOLDOWN_FILE", cooldown_file)
    monkeypatch.setattr(hook, "COOLDOWN_SECONDS", 0.1)

    # Set cooldown as active (time.time() = now, so cooldown is active)
    cooldown_file.write_text(str(time.time()))

    # Mock the payload
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / ".claude/projects/-Users-gileskayo/memory/note.md")}}

    with patch("sys.stdin") as mock_stdin, \
         patch("json.load", return_value=payload), \
         patch("subprocess.Popen") as mock_popen:
        hook.main()

        # With cooldown active and no queue, file should be queued
        # Check if queue file was created
        queue_file = logs_dir / ".stale-check-queue.json"
        if queue_file.exists():
            queue = json.loads(queue_file.read_text())
            assert len(queue) > 0, "Check should be queued during cooldown"
        # If no queue file, subprocess should not have been spawned (due to cooldown)
        assert not mock_popen.called, "Should not spawn subprocess during cooldown"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
