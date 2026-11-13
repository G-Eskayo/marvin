"""Tests for cross_machine_merge.py's sync_paper_knowledge(), which mirrors
sync_qa_knowledge()'s deterministic-set-union-by-id item sync. Run via:
    ~/.agents/venv/bin/python -m pytest scripts/tests/test_cross_machine_merge.py -v
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import chromadb
import pytest
from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

import cross_machine_merge as cmm


@pytest.fixture
def no_download(monkeypatch, tmp_path):
    """Local guard: no model cached, any attempt to fetch fails loudly (#1098)."""
    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to download Chroma's embedding model")

    monkeypatch.setattr(ONNXMiniLM_L6_V2, "DOWNLOAD_PATH", tmp_path / "empty-model-cache")
    monkeypatch.setattr(ONNXMiniLM_L6_V2, "_download", refuse)


def test_sync_paper_knowledge_imports_new_entries_and_advances_cursor(tmp_path, monkeypatch):
    monkeypatch.setattr(cmm, "CHROMA_PATH", tmp_path)

    remote_dump = {
        "ids": ["10.1/a", "10.1/b"],
        "documents": ["abstract a", "abstract b"],
        "metadatas": [
            {"doi": "10.1/a", "created_epoch": 100.0},
            {"doi": "10.1/b", "created_epoch": 200.0},
        ],
    }
    monkeypatch.setattr(cmm, "ssh_run", lambda host, cmd, timeout=30: json.dumps(remote_dump))

    sync_state: dict = {}
    cmm.sync_paper_knowledge("mac-mini-1", "gils-mac-mini", sync_state)

    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_collection("paper-knowledge")
    assert set(col.get()["ids"]) == {"10.1/a", "10.1/b"}
    assert sync_state["mac-mini-1"]["paper-knowledge"]["last_synced_epoch"] == 200.0


def test_sync_paper_knowledge_skips_already_known_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(cmm, "CHROMA_PATH", tmp_path)

    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection("paper-knowledge")
    col.add(ids=["10.1/a"], documents=["already have this one"], metadatas=[{"doi": "10.1/a", "created_epoch": 50.0}])

    remote_dump = {
        "ids": ["10.1/a", "10.1/b"],
        "documents": ["abstract a (remote copy)", "abstract b"],
        "metadatas": [
            {"doi": "10.1/a", "created_epoch": 50.0},
            {"doi": "10.1/b", "created_epoch": 200.0},
        ],
    }
    monkeypatch.setattr(cmm, "ssh_run", lambda host, cmd, timeout=30: json.dumps(remote_dump))

    sync_state: dict = {}
    cmm.sync_paper_knowledge("mac-mini-1", "gils-mac-mini", sync_state)

    # the already-known doc must not be overwritten by the remote's copy
    result = col.get(ids=["10.1/a"])
    assert result["documents"][0] == "already have this one"
    assert set(col.get()["ids"]) == {"10.1/a", "10.1/b"}


def test_sync_paper_knowledge_uses_prior_cursor_in_the_dump_command(tmp_path, monkeypatch):
    monkeypatch.setattr(cmm, "CHROMA_PATH", tmp_path)
    captured_cmds = []

    def fake_ssh_run(host, cmd, timeout=30):
        captured_cmds.append(cmd)
        return json.dumps({"ids": [], "documents": [], "metadatas": []})

    monkeypatch.setattr(cmm, "ssh_run", fake_ssh_run)

    sync_state = {"mac-mini-1": {"paper-knowledge": {"last_synced_epoch": 12345.0}}}
    cmm.sync_paper_knowledge("mac-mini-1", "gils-mac-mini", sync_state)

    assert "--since 12345.0" in captured_cmds[0]


def test_sync_paper_knowledge_skips_gracefully_when_remote_unreachable(tmp_path, monkeypatch):
    monkeypatch.setattr(cmm, "CHROMA_PATH", tmp_path)
    monkeypatch.setattr(cmm, "ssh_run", lambda host, cmd, timeout=30: None)

    sync_state: dict = {}
    cmm.sync_paper_knowledge("mac-mini-1", "gils-mac-mini", sync_state)  # should not raise

    assert "mac-mini-1" not in sync_state


# ── run_merge_authority failure guards ─────────────────────────────────────

def _make_ssh_run_mock(remote_profile_json="", remote_digest_content=""):
    """Factory for ssh_run mocks that properly distinguish between machine-profile and digest fetches."""
    def mock_ssh_run(host, cmd, timeout=30):
        if "machine-profile" in cmd:
            return remote_profile_json or json.dumps({"label": "test-remote"})
        elif "daily-digest" in cmd or "research-digest" in cmd:
            return remote_digest_content or "# Remote digest"
        return None
    return mock_ssh_run


def test_run_merge_authority_skips_when_local_is_failed(tmp_path, monkeypatch):
    """run_merge_authority skips merge if local content is a claude failure."""
    digest_dir = tmp_path / "daily-digest"
    digest_dir.mkdir(parents=True)
    local_file = digest_dir / f"{cmm.TODAY}.md"
    local_file.write_text(f"{cmm.CLAUDE_FAILED_PREFIX} test error)")

    monkeypatch.setattr(cmm, "CLAUDE_DIR", tmp_path)

    # Track calls to build_merged and scp_push
    build_merged_called = []
    scp_push_called = []

    def mock_build_merged(*args, **kwargs):
        build_merged_called.append(True)
        return "should not be called"

    def mock_scp_push(*args, **kwargs):
        scp_push_called.append(True)
        return True

    monkeypatch.setattr(cmm, "build_merged", mock_build_merged)
    monkeypatch.setattr(cmm, "scp_push", mock_scp_push)
    monkeypatch.setattr(cmm, "ssh_run", _make_ssh_run_mock())

    own_profile = {"label": "test-desktop", "mobility_class": "stationary"}
    cmm.run_merge_authority("mac-mini-1", "gils-mac-mini", own_profile)

    # Verify build_merged and scp_push were never called
    assert not build_merged_called
    assert not scp_push_called


def test_run_merge_authority_skips_when_remote_is_failed(tmp_path, monkeypatch):
    """run_merge_authority skips merge if remote content is a claude failure."""
    digest_dir = tmp_path / "daily-digest"
    digest_dir.mkdir(parents=True)
    local_file = digest_dir / f"{cmm.TODAY}.md"
    local_file.write_text("# Local digest")

    monkeypatch.setattr(cmm, "CLAUDE_DIR", tmp_path)

    build_merged_called = []
    scp_push_called = []

    def mock_build_merged(*args, **kwargs):
        build_merged_called.append(True)
        return "should not be called"

    def mock_scp_push(*args, **kwargs):
        scp_push_called.append(True)
        return True

    monkeypatch.setattr(cmm, "build_merged", mock_build_merged)
    monkeypatch.setattr(cmm, "scp_push", mock_scp_push)
    monkeypatch.setattr(cmm, "ssh_run", _make_ssh_run_mock(remote_digest_content=f"{cmm.CLAUDE_FAILED_PREFIX} remote error)"))

    own_profile = {"label": "test-desktop", "mobility_class": "stationary"}
    cmm.run_merge_authority("mac-mini-1", "gils-mac-mini", own_profile)

    # Verify build_merged and scp_push were never called
    assert not build_merged_called
    assert not scp_push_called


def test_run_merge_authority_skips_when_local_quarantined(tmp_path, monkeypatch):
    """run_merge_authority skips merge if local content is quarantined by safety-monitor."""
    digest_dir = tmp_path / "daily-digest"
    digest_dir.mkdir(parents=True)
    local_file = digest_dir / f"{cmm.TODAY}.md"
    local_file.write_text("Quarantined by safety-monitor")

    monkeypatch.setattr(cmm, "CLAUDE_DIR", tmp_path)

    build_merged_called = []

    def mock_build_merged(*args, **kwargs):
        build_merged_called.append(True)
        return "should not be called"

    monkeypatch.setattr(cmm, "build_merged", mock_build_merged)
    monkeypatch.setattr(cmm, "scp_push", lambda *a, **k: True)
    monkeypatch.setattr(cmm, "ssh_run", _make_ssh_run_mock())

    own_profile = {"label": "test-desktop", "mobility_class": "stationary"}
    cmm.run_merge_authority("mac-mini-1", "gils-mac-mini", own_profile)

    # Verify build_merged was never called
    assert not build_merged_called


def test_run_merge_authority_skips_when_merge_result_failed(tmp_path, monkeypatch):
    """run_merge_authority skips write and push if build_merged returns failure."""
    digest_dir = tmp_path / "daily-digest"
    digest_dir.mkdir(parents=True)
    local_file = digest_dir / f"{cmm.TODAY}.md"
    local_file.write_text("# Local digest")

    monkeypatch.setattr(cmm, "CLAUDE_DIR", tmp_path)

    scp_push_called = []

    def mock_build_merged(*args, **kwargs):
        return f"{cmm.CLAUDE_FAILED_PREFIX} merge failed)"

    def mock_scp_push(*args, **kwargs):
        scp_push_called.append(True)
        return True

    monkeypatch.setattr(cmm, "build_merged", mock_build_merged)
    monkeypatch.setattr(cmm, "scp_push", mock_scp_push)
    monkeypatch.setattr(cmm, "ssh_run", _make_ssh_run_mock())

    own_profile = {"label": "test-desktop", "mobility_class": "stationary"}
    cmm.run_merge_authority("mac-mini-1", "gils-mac-mini", own_profile)

    # Verify neither the merged file was written nor scp_push was called
    merged_file = digest_dir / f"{cmm.TODAY}-merged.md"
    assert not merged_file.exists()
    assert not scp_push_called


def test_run_merge_authority_succeeds_with_valid_inputs(tmp_path, monkeypatch):
    """run_merge_authority writes merged file and pushes when all inputs are valid."""
    digest_dir = tmp_path / "daily-digest"
    digest_dir.mkdir(parents=True)
    local_file = digest_dir / f"{cmm.TODAY}.md"
    local_file.write_text("# Local digest")

    monkeypatch.setattr(cmm, "CLAUDE_DIR", tmp_path)

    scp_push_called = []

    def mock_build_merged(*args, **kwargs):
        return "# Merged content"

    def mock_scp_push(*args, **kwargs):
        scp_push_called.append(True)
        return True

    monkeypatch.setattr(cmm, "build_merged", mock_build_merged)
    monkeypatch.setattr(cmm, "scp_push", mock_scp_push)
    monkeypatch.setattr(cmm, "ssh_run", _make_ssh_run_mock())

    own_profile = {"label": "test-desktop", "mobility_class": "stationary"}
    cmm.run_merge_authority("mac-mini-1", "gils-mac-mini", own_profile)

    # Verify the merged file was written and scp_push was called
    merged_file = digest_dir / f"{cmm.TODAY}-merged.md"
    assert merged_file.exists()
    assert "# Merged content" in merged_file.read_text()
    assert scp_push_called


def test_sync_paper_knowledge_skips_gracefully_on_malformed_json(tmp_path, monkeypatch):
    monkeypatch.setattr(cmm, "CHROMA_PATH", tmp_path)
    monkeypatch.setattr(cmm, "ssh_run", lambda host, cmd, timeout=30: "not valid json{")

    sync_state: dict = {}
    cmm.sync_paper_knowledge("mac-mini-1", "gils-mac-mini", sync_state)  # should not raise

    assert "mac-mini-1" not in sync_state


def test_sync_paper_knowledge_no_new_items_leaves_state_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(cmm, "CHROMA_PATH", tmp_path)
    monkeypatch.setattr(
        cmm, "ssh_run",
        lambda host, cmd, timeout=30: json.dumps({"ids": [], "documents": [], "metadatas": []}),
    )

    sync_state = {"mac-mini-1": {"paper-knowledge": {"last_synced_epoch": 999.0}}}
    cmm.sync_paper_knowledge("mac-mini-1", "gils-mac-mini", sync_state)

    assert sync_state["mac-mini-1"]["paper-knowledge"]["last_synced_epoch"] == 999.0


def test_sync_paper_knowledge_never_downloads_the_embedding_model(tmp_path, monkeypatch, no_download):
    """Regression guard: sync_paper_knowledge's col.add() must not trigger an embedding
    model download, even when called with fresh remote data. Covers #1098/#1156 (#1163).
    """
    monkeypatch.setattr(cmm, "CHROMA_PATH", tmp_path)

    remote_dump = {
        "ids": ["10.1/new1", "10.1/new2"],
        "documents": ["first new abstract", "second new abstract"],
        "metadatas": [
            {"doi": "10.1/new1", "created_epoch": 300.0},
            {"doi": "10.1/new2", "created_epoch": 400.0},
        ],
    }
    monkeypatch.setattr(cmm, "ssh_run", lambda host, cmd, timeout=30: json.dumps(remote_dump))

    sync_state: dict = {}
    # This should complete without hitting the download guard (no AssertionError)
    cmm.sync_paper_knowledge("mac-mini-1", "gils-mac-mini", sync_state)

    # Verify the sync actually happened
    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_collection("paper-knowledge")
    assert set(col.get()["ids"]) == {"10.1/new1", "10.1/new2"}
