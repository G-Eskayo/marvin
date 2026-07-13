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

import cross_machine_merge as cmm


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
