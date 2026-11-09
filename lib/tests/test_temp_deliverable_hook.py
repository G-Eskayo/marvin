"""The temp-deliverable hook (marvin#715): a session that points Gil at a temp-only image, PDF or page is reminded.

Tries to break it: a path mentioned only by file name, /private vs /tmp spellings, a shown file mentioned again, a
reminder loop (stop_hook_active), each strictness mode, junk transcripts, and the real hook process failing open.
"""
import json
import subprocess
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))
import temp_deliverable_hook as h  # noqa: E402

SHOT = "/private/tmp/claude-501/x/scratchpad/portfolio-home.png"


def transcript(tmp_path, text, name="t.jsonl"):
    p = tmp_path / name
    rows = [{"type": "user", "message": {"content": "show me"}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return str(p)


def post(tmp_path, tool, **ti):
    return h.on_post({"session_id": "s1", "tool_name": tool, "tool_input": ti}, state_dir=tmp_path / "state")


def stop(tmp_path, text, rule="nudge", **extra):
    ev = {"session_id": "s1", "transcript_path": transcript(tmp_path, text), **extra}
    return h.on_stop(ev, state_dir=tmp_path / "state", rule=rule)


def test_writing_a_temp_deliverable_puts_a_reminder_in_context(tmp_path):
    out = post(tmp_path, "Write", file_path=SHOT, content="x")
    assert "marvin-show " + SHOT in out["hookSpecificOutput"]["additionalContext"]
    assert post(tmp_path, "Write", file_path=SHOT, content="x") is None  # once per file
    assert post(tmp_path, "Write", file_path="/private/tmp/x/notes.txt", content="x") is None  # not a deliverable
    assert post(tmp_path, "Write", file_path="/Users/g/.claude/outbox/a/b.png", content="x") is None  # not temp


def test_a_reply_naming_an_unshown_temp_file_is_reminded_once_then_let_go(tmp_path):
    post(tmp_path, "Write", file_path=SHOT, content="x")
    out = stop(tmp_path, "Here are the screenshots: portfolio-home.png")  # by file name only
    assert out["decision"] == "block" and "marvin-show" in out["reason"]
    again = stop(tmp_path, "Here are the screenshots: portfolio-home.png", stop_hook_active=True)
    assert "decision" not in again and "MARVIN:" in again["systemMessage"]  # never a loop


def test_a_temp_path_in_the_reply_counts_even_if_never_written_here(tmp_path):
    out = stop(tmp_path, "Saved to /tmp/claude-501/abc/scratchpad/mock.html, have a look.")
    assert out["decision"] == "block" and "/tmp/claude-501/abc/scratchpad/mock.html" in out["reason"]


def test_shown_with_marvin_show_or_copied_to_the_outbox_is_fine(tmp_path):
    post(tmp_path, "Write", file_path=SHOT, content="x")
    assert post(tmp_path, "Bash", command=f"~/.agents/bin/marvin-show {SHOT} --project portfolio-website-updater") is None
    assert stop(tmp_path, f"Shown: portfolio-home.png (marvin-show {SHOT})") is None
    post(tmp_path, "Write", file_path="/tmp/q/b.pdf", content="x")
    post(tmp_path, "Bash", command="cp /tmp/q/b.pdf ~/.claude/outbox/marvin-2026-11-02-b/")
    assert stop(tmp_path, "The PDF is b.pdf") is None


def test_private_and_plain_tmp_spellings_are_the_same_file(tmp_path):
    post(tmp_path, "Write", file_path="/private/tmp/z/a.png", content="x")
    post(tmp_path, "Bash", command="marvin-show /tmp/z/a.png")
    assert stop(tmp_path, "see /tmp/z/a.png") is None


def test_a_reply_that_names_nothing_is_left_alone(tmp_path):
    post(tmp_path, "Write", file_path=SHOT, content="x")
    assert stop(tmp_path, "All tests pass.") is None
    assert stop(tmp_path, "the file portfolio-home.png.bak is different") is None


def test_modes(tmp_path):
    post(tmp_path, "Write", file_path=SHOT, content="x")
    assert "decision" not in stop(tmp_path, "portfolio-home.png", rule="note")
    for _ in range(h.HOLD_LIMIT):
        assert stop(tmp_path, "portfolio-home.png", rule="hold", stop_hook_active=True)["decision"] == "block"
    assert "decision" not in stop(tmp_path, "portfolio-home.png", rule="hold", stop_hook_active=True)  # capped
    cfg = tmp_path / "rule.json"
    cfg.write_text('{"mode": "hold"}')
    assert h.mode(cfg) == "hold"
    cfg.write_text('{"mode": "bogus"}')
    assert h.mode(cfg) == "nudge"
    assert h.mode(tmp_path / "missing.json") == "nudge"


def test_junk_transcripts_and_events_never_raise(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n{\"type\": \"assistant\", \"message\": {}}\n")
    assert h.on_stop({"session_id": "s", "transcript_path": str(bad)}, state_dir=tmp_path / "s") is None
    assert h.on_stop({"session_id": "s", "transcript_path": str(tmp_path / "missing")}, state_dir=tmp_path / "s") is None
    assert h.on_post({"tool_name": "Read", "tool_input": {}}, state_dir=tmp_path / "s") is None
    assert h.on_post({"session_id": "../../etc", "tool_name": "Write", "tool_input": {"file_path": SHOT}}, state_dir=tmp_path / "s")
    assert all(p.parent == tmp_path / "s" for p in (tmp_path / "s").iterdir())  # a hostile session id stays inside


def test_the_real_process_fails_open_and_speaks_json(tmp_path):
    script = str(LIB / "temp_deliverable_hook.py")
    r = subprocess.run([sys.executable, script, "stop"], input="{not json", capture_output=True, text=True)
    assert (r.returncode, r.stdout) == (0, "")
    ev = {"session_id": "proc-test", "transcript_path": transcript(tmp_path, "see /tmp/zz/a.png")}
    r = subprocess.run([sys.executable, script, "stop"], input=json.dumps(ev), capture_output=True, text=True)
    assert r.returncode == 0 and "marvin-show /tmp/zz/a.png" in json.loads(r.stdout)["reason"]
    for f in (LIB.parent / "var" / "temp-deliverables").glob("proc-test*"):
        f.unlink()
