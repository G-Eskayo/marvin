"""Tests for deliverable_location_guard.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_deliverable_location_guard.py -v
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import deliverable_location_guard as g  # noqa: E402

SCRATCH = "/private/tmp/claude-501/-Users-x/abc/scratchpad/mock/shot.png"


def _denied(result):
    return result is not None and result["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_denies_scratchpad_file_sent_to_user():
    assert _denied(g.check("SendUserFile", {"files": [SCRATCH]}))


def test_denies_when_any_one_of_several_files_is_scratch():
    assert _denied(g.check("SendUserFile", {"files": ["/Users/x/.agents/docs/plans/a.md", SCRATCH]}))


def test_denies_tmp_and_private_tmp_and_var_folders():
    for p in ["/tmp/a.png", "/private/tmp/a.png", "/var/folders/ab/T/a.png", "/private/var/folders/ab/T/a.png"]:
        assert _denied(g.check("SendUserFile", {"files": [p]})), p


def test_denies_traversal_back_into_tmp():
    assert _denied(g.check("SendUserFile", {"files": ["/Users/x/../../tmp/a.png"]}))


def test_denies_artifact_publish_from_scratchpad():
    assert _denied(g.check("Artifact", {"file_path": SCRATCH}))


def test_denial_reason_names_the_right_homes():
    reason = g.check("SendUserFile", {"files": [SCRATCH]})["hookSpecificOutput"]["permissionDecisionReason"]
    assert "docs/plans" in reason and "docs/screenshots" in reason and "outbox" in reason


def test_allows_repo_docs_and_outbox():
    assert g.check("SendUserFile", {"files": ["/Users/x/.agents/docs/screenshots/102-a.png"]}) is None
    assert g.check("SendUserFile", {"files": ["/Users/x/.claude/outbox/topic/a.csv"]}) is None


def test_lookalike_names_outside_tmp_are_allowed():
    assert g.check("SendUserFile", {"files": ["/Users/x/notes/tmp/a.png", "/Users/x/temporary/a.png"]}) is None


def test_artifact_read_and_list_are_not_publishes():
    assert g.check("Artifact", {"action": "read", "url": "https://claude.ai/artifact/x"}) is None
    assert g.check("Artifact", {"action": "list"}) is None


def test_other_tools_and_malformed_input_pass_through():
    assert g.check("Bash", {"command": f"cat {SCRATCH}"}) is None
    assert g.check("SendUserFile", {}) is None
    assert g.check("SendUserFile", {"files": "not-a-list"}) is None
    assert g.check("SendUserFile", {"files": [None, 3]}) is None


def test_main_end_to_end_and_garbage_stdin_never_crashes():
    script = str(LIB / "deliverable_location_guard.py")
    out = subprocess.run([sys.executable, script], input=json.dumps(
        {"tool_name": "SendUserFile", "tool_input": {"files": [SCRATCH]}}), capture_output=True, text=True)
    assert json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    bad = subprocess.run([sys.executable, script], input="{not json", capture_output=True, text=True)
    assert bad.returncode == 0 and bad.stdout == ""
