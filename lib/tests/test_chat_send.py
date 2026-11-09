"""marvin#1067: the dashboard sends a message into a chat tab only when it is safely idle, never onto a prompt."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chat_send as cs  # noqa: E402
import wezterm_cli  # noqa: E402

IDLE_SCREEN = "some earlier output\n\n> \n  ? for shortcuts\n"
PERMISSION_SCREEN = ("╭──────────────╮\n│ Bash command │\n│   rm -rf build │\n│ Do you want to proceed?\n"
                     "│ ❯ 1. Yes\n│   2. Yes, and don't ask again\n│   3. No, and tell Claude what to do differently\n")
QUESTION_SCREEN = "Which base font?\n❯ 1. Courier Prime\n  2. VT323\n"


def chat(**over):
    c = {"id": "c1", "mac": "macbook-pro", "socket": "/s/gui-sock-1", "pane": 16, "state": "your-turn",
         "title": "✳ PR 1067", "unknown": False}
    c.update(over)
    return c


class FakeWez:
    def __init__(self, screen=IDLE_SCREEN, fail=None):
        self.screen, self.fail, self.sent = screen, fail, []

    def get_text(self, pane):
        return self.screen

    def send_text(self, pane, text, paste=True):
        if self.fail:
            raise wezterm_cli.WeztermError(self.fail)
        self.sent.append((pane, text, paste))


def run(text, chats=None, wez=None, log=None, rechecks=None):
    wez = wez or FakeWez()
    seq = iter(rechecks or [])
    lookups = {"n": 0}

    def find(cid):
        lookups["n"] += 1
        if lookups["n"] > 1 and rechecks is not None:
            return next(seq, None)
        return next((c for c in (chats if chats is not None else [chat()]) if c["id"] == cid), None)
    out = cs.send("c1", text, find=find, wezterm_for=lambda c: wez, log=(log.append if log is not None else lambda e: None))
    return out, wez


# ── the text ────────────────────────────────────────────────────────────────────────────────

def test_a_plain_message_goes_in_as_a_paste_with_a_note_then_a_separate_enter():
    out, wez = run("Decision tokens: Yes, everywhere")
    assert out["ok"]
    assert wez.sent == [(16, "[from the MARVIN dashboard] Decision tokens: Yes, everywhere", True), (16, "\r", False)]


def test_multi_line_text_keeps_its_newlines():
    out, wez = run("line one\nline two")
    assert wez.sent[0][1].endswith("line one\nline two")


@pytest.mark.parametrize("bad", ["\x1b[201~ then raw keys", "esc \x1b", "csi \x9b2J", "\x1bOA"])
def test_escape_sequences_are_refused_outright(bad):
    out, wez = run(bad)
    assert not out["ok"] and "escape" in out["why"] and wez.sent == []


def test_other_control_characters_and_carriage_returns_are_stripped():
    out, wez = run("a\rb\x00c\x07d\te\x7f")
    assert out["ok"] and wez.sent[0][1].endswith("ab cd e") or wez.sent[0][1].endswith("abcd\te")


@pytest.mark.parametrize("bad", ["", "   \n  ", None, 42])
def test_empty_or_non_text_is_refused(bad):
    out, wez = run(bad)
    assert not out["ok"] and wez.sent == []


def test_huge_text_is_refused_not_truncated_silently():
    out, wez = run("x" * (cs.MAX_CHARS + 1))
    assert not out["ok"] and "long" in out["why"] and wez.sent == []


# ── is it safe right now ────────────────────────────────────────────────────────────────────

def test_a_chat_that_is_working_is_refused():
    out, wez = run("hi", chats=[chat(state="working", title="◐ PR 1067")])
    assert not out["ok"] and "working" in out["why"] and wez.sent == []


def test_a_chat_waiting_on_a_permission_is_refused():
    out, wez = run("y", chats=[chat(state="waiting", title="✳ PR")])
    assert not out["ok"] and wez.sent == []


def test_both_idle_signals_must_agree():
    out, wez = run("hi", chats=[chat(state="your-turn", title="◐ PR 1067")])   # hooks say idle, title says working
    assert not out["ok"] and wez.sent == []


def test_a_permission_dialog_on_screen_is_refused_even_if_both_signals_say_idle():
    out, wez = run("y", wez=FakeWez(screen=PERMISSION_SCREEN))
    assert not out["ok"] and "prompt" in out["why"] and wez.sent == []


def test_a_question_menu_on_screen_is_refused():
    out, wez = run("1", wez=FakeWez(screen=QUESTION_SCREEN))
    assert not out["ok"] and wez.sent == []


def test_an_old_dialog_far_up_the_scrollback_does_not_block():
    out, wez = run("hi", wez=FakeWez(screen=PERMISSION_SCREEN + "\n" * 40 + IDLE_SCREEN))
    assert out["ok"]


def test_the_chat_changing_between_the_check_and_the_send_is_caught():
    out, wez = run("hi", rechecks=[chat(state="working", title="◐ busy")])
    assert not out["ok"] and wez.sent == []


def test_the_chat_closing_between_the_check_and_the_send_is_caught():
    out, wez = run("hi", rechecks=[None])
    assert not out["ok"] and wez.sent == []


@pytest.mark.parametrize("c", [None, chat(unknown=True), chat(mac="mac-mini-1", here=False)])
def test_an_unknown_missing_or_other_mac_chat_is_refused(c):
    out, wez = run("hi", chats=[c] if c else [])
    assert not out["ok"] and wez.sent == []


def test_a_wezterm_failure_is_reported_not_raised():
    out, wez = run("hi", wez=FakeWez(fail="no such pane"))
    assert not out["ok"] and "no such pane" in out["why"]


# ── the record ──────────────────────────────────────────────────────────────────────────────

def test_every_send_and_every_refusal_is_logged():
    log = []
    run("hello", log=log)
    run("y", chats=[chat(state="working", title="◐ x")], log=log)
    assert [e["ok"] for e in log] == [True, False]
    assert log[0]["pane"] == 16 and log[0]["socket"] == "/s/gui-sock-1" and log[0]["state"] == "your-turn"
    assert log[0]["title"] == "✳ PR 1067" and log[0]["text"].endswith("hello")


def test_the_cli_reads_json_on_stdin_and_answers_json(monkeypatch, capsys):
    import io
    monkeypatch.setattr(cs, "send", lambda cid, text, **k: {"ok": True, "id": cid, "text": text})
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"id": "c1", "text": "hi"})))
    assert cs.main(["send"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "id": "c1", "text": "hi"}


def test_the_cli_refuses_garbage_input(monkeypatch, capsys):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert cs.main(["send"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
