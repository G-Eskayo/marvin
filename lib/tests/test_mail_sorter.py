"""mail_sorter.py (#1405, part of #1357): the decision core, config loading, Gmail actions and the IDLE catch-up.
Adversarial: lookalike and spoofed senders, encoded headers, missing headers, UIDVALIDITY resets, the `N:*` quirk,
a failing action mid-batch. Run: ~/.agents/venv/bin/python -m pytest lib/tests/test_mail_sorter.py -v"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import mail_sorter as ms  # noqa: E402


# ---------- fixtures ----------

RULES = {
    "personal": ["gmail.com", "icloud.com"],
    "rules": [
        {"folder": "MARVIN/GitHub CI failures", "domains": ["github.com"], "subject": "run failed|failure"},
        {"folder": "MARVIN/GitHub", "domains": ["github.com"]},
        {"folder": "Job search", "domains": ["greenhouse-mail.io", "linkedin.com"]},
        {"folder": "Finance", "domains": ["chase.com"]},
    ],
}
WATCH = [
    {"name": "Anduril", "domains": ["anduril.com"], "mentions": ["anduril"],
     "mentions_from": ["greenhouse-mail.io", "greenhouse.io"]},
]


def cfg():
    return ms.Config.from_dicts(RULES, WATCH)


def msg(sender, subject="hello"):
    return ms.Message(uid=1, sender=sender, subject=subject)


# ---------- sender parsing ----------

@pytest.mark.parametrize("header,addr,dom", [
    ('"Anduril Recruiting" <jobs@anduril.com>', "jobs@anduril.com", "anduril.com"),
    ("no-reply@us.greenhouse-mail.io", "no-reply@us.greenhouse-mail.io", "greenhouse-mail.io"),
    ("Bob <BOB@Mail.Chase.COM>", "bob@mail.chase.com", "chase.com"),
    ("", "", ""),
    ("undisclosed-recipients:;", "", ""),
])
def test_parse_sender(header, addr, dom):
    s = ms.parse_sender(header)
    assert (s.address, s.domain) == (addr, dom)


def test_lookalike_domains_do_not_match():
    c = cfg()
    for sender in ["x@notanduril.com", "x@anduril.com.evil.io", "x@anduril-careers.com"]:
        assert ms.decide(msg(sender), c).kind == "keep", sender


def test_subdomain_of_watched_domain_matches():
    assert ms.decide(msg("r@talent.anduril.com"), cfg()).kind == "watch"


# ---------- decide ----------

def test_watch_beats_rules():
    # greenhouse-mail.io is a Job search rule, but an Anduril mention from Greenhouse must stay in the Inbox, starred.
    d = ms.decide(msg("Anduril Industries <no-reply@us.greenhouse-mail.io>", "Thank you for applying"), cfg())
    assert (d.kind, d.watch) == ("watch", "Anduril")


def test_mention_in_subject_from_scoped_domain():
    d = ms.decide(msg("no-reply@greenhouse.io", "Your application to ANDURIL Industries"), cfg())
    assert d.kind == "watch"


def test_mention_from_unscoped_sender_is_not_a_watch_hit():
    # A newsletter headline about Anduril, or a spoofed display name, must not trigger the alert.
    assert ms.decide(msg("news@tldrnewsletter.com", "Anduril raises $2B"), cfg()).kind == "keep"
    assert ms.decide(msg('"Anduril HR" <scam@evil.io>', "Offer letter"), cfg()).kind == "keep"


def test_unscoped_mentions_match_any_sender():
    c = ms.Config.from_dicts(RULES, [{"name": "X", "mentions": ["acme"]}])
    assert ms.decide(msg("a@b.io", "re: ACME"), c).kind == "watch"


def test_personal_senders_stay_in_inbox():
    for s in ["friend@gmail.com", "mom@icloud.com"]:
        d = ms.decide(msg(s), cfg())
        assert d.kind == "keep" and "person" in d.reason


def test_watch_beats_personal():
    c = ms.Config.from_dicts(RULES, [{"name": "Aaron", "addresses": ["aaron@gmail.com"]}])
    assert ms.decide(msg("Aaron <Aaron@gmail.com>"), c).kind == "watch"
    assert ms.decide(msg("someoneelse@gmail.com"), c).kind == "keep"


def test_rule_subject_and_first_match_wins():
    c = cfg()
    assert ms.decide(msg("n@github.com", "Run failed: CI"), c).folder == "MARVIN/GitHub CI failures"
    assert ms.decide(msg("n@github.com", "PR merged"), c).folder == "MARVIN/GitHub"


def test_unknown_sender_stays():
    d = ms.decide(msg("hi@brand-new-startup.dev"), cfg())
    assert d.kind == "keep" and d.folder is None


def test_empty_sender_stays():
    assert ms.decide(msg(""), cfg()).kind == "keep"


# ---------- config ----------

def test_load_config_from_instance(tmp_path):
    (tmp_path / "rules.json").write_text(json.dumps(RULES))
    (tmp_path / "watch.json").write_text(json.dumps(WATCH))
    c = ms.load_config(tmp_path)
    assert ms.decide(msg("jobs@anduril.com"), c).kind == "watch"


def test_missing_watch_file_is_empty_not_a_crash(tmp_path):
    (tmp_path / "rules.json").write_text(json.dumps(RULES))
    c = ms.load_config(tmp_path)
    assert c.watch == []


def test_missing_rules_file_refuses(tmp_path):
    # With no rules the daemon must not start and silently do nothing.
    with pytest.raises(ms.ConfigError):
        ms.load_config(tmp_path)


def test_bad_rule_regex_refuses(tmp_path):
    (tmp_path / "rules.json").write_text(json.dumps({"rules": [{"folder": "F", "domains": ["a.com"], "subject": "("}]}))
    with pytest.raises(ms.ConfigError):
        ms.load_config(tmp_path)


def test_rule_without_folder_refuses():
    with pytest.raises(ms.ConfigError):
        ms.Config.from_dicts({"rules": [{"domains": ["a.com"]}]}, [])


# ---------- header decoding ----------

def test_parse_headers_decodes_rfc2047():
    raw = (b"From: =?UTF-8?B?QW5kdXJpbCBJbmR1c3RyaWVz?= <no-reply@us.greenhouse-mail.io>\r\n"
           b"Subject: =?UTF-8?Q?Thank_you_for_applying_=E2=80=94_Anduril?=\r\n\r\n")
    sender, subject = ms.parse_headers(raw)
    assert "Anduril Industries" in sender and subject.endswith("Anduril")


def test_parse_headers_survives_garbage():
    assert ms.parse_headers(b"\xff\xfe not headers") == ("", "")


# ---------- Gmail actions ----------

def test_imap_quote_escapes():
    assert ms.imap_quote('Job search/Recruiters (cold)') == '"Job search/Recruiters (cold)"'
    assert ms.imap_quote('a"b\\c') == '"a\\"b\\\\c"'


def test_imap_quote_refuses_newlines():
    with pytest.raises(ValueError):
        ms.imap_quote("x\r\nA1 DELETE INBOX")


class FakeImap:
    """Records UID commands; `fail_on` makes one STORE raise like a dropped connection."""

    def __init__(self, uids=(), headers=None, uidvalidity=7, uidnext=100, fail_on=None):
        self.calls = []
        self.uids = list(uids)
        self.headers = headers or {}
        self.uidvalidity, self.uidnext = uidvalidity, uidnext
        self.fail_on = fail_on

    def uid(self, command, *args):
        self.calls.append((command.upper(),) + args)
        if command.upper() == "SEARCH":
            lo = int(args[-1].split(":")[0])
            hits = [u for u in self.uids if u >= lo] or ([max(self.uids)] if self.uids else [])  # the N:* quirk
            return "OK", [" ".join(map(str, hits)).encode()]
        if command.upper() == "FETCH":
            u = int(args[0])
            return "OK", [(f"{u} (UID {u} BODY[HEADER.FIELDS (FROM SUBJECT)] {{0}}".encode(), self.headers.get(u, b""))]
        if command.upper() == "STORE" and self.fail_on == (int(args[0]), args[1]):
            raise OSError("connection reset")
        return "OK", [b""]

    def status_values(self):
        return self.uidvalidity, self.uidnext


def stores(fake):
    return [c[1:] for c in fake.calls if c[0] == "STORE"]


def test_apply_watch_stars_and_marks_important_stays_in_inbox():
    f = FakeImap()
    ms.apply(f, 5, ms.Decision("watch", None, "watch: Anduril", "Anduril"))
    assert stores(f) == [("5", "+FLAGS", "(\\Flagged)"), ("5", "+X-GM-LABELS", "(\\Important)")]


def test_apply_sort_labels_then_removes_inbox():
    f = FakeImap()
    ms.apply(f, 9, ms.Decision("sort", "Job search/Recruiters (cold)", "rule"))
    assert stores(f) == [("9", "+X-GM-LABELS", '("Job search/Recruiters (cold)")'), ("9", "-X-GM-LABELS", "(\\Inbox)")]


def test_apply_keep_touches_nothing():
    f = FakeImap()
    ms.apply(f, 9, ms.Decision("keep", None, "unknown sender"))
    assert stores(f) == []


def test_apply_checks_server_status():
    class No(FakeImap):
        def uid(self, command, *args):
            return ("NO", [b"label error"]) if command.upper() == "STORE" else super().uid(command, *args)
    with pytest.raises(ms.ImapError):
        ms.apply(No(), 1, ms.Decision("sort", "Finance", "rule"))


# ---------- state + catch-up ----------

def H(sender, subject="s"):
    return f"From: {sender}\r\nSubject: {subject}\r\n\r\n".encode()


def run_catch_up(fake, tmp_path, config=None, alerts=None):
    state = ms.State(tmp_path / "state.json")
    return ms.catch_up(fake, config or cfg(), state, alert=(lambda d, m: alerts.append((d, m))) if alerts is not None else (lambda d, m: None),
                       log_path=tmp_path / "moves.jsonl"), state


def test_first_run_starts_at_uidnext_and_skips_backlog(tmp_path):
    f = FakeImap(uids=[10, 11], headers={10: H("x@chase.com"), 11: H("x@chase.com")}, uidnext=12)
    n, state = run_catch_up(f, tmp_path)
    assert n == 0 and stores(f) == [] and state.load() == {"uidvalidity": 7, "last_uid": 11}


def test_catch_up_processes_only_new_uids_and_ignores_star_quirk(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"uidvalidity": 7, "last_uid": 11}))
    f = FakeImap(uids=[11], headers={11: H("x@chase.com")})  # SEARCH 12:* returns 11 (the quirk)
    n, _ = run_catch_up(f, tmp_path)
    assert n == 0 and stores(f) == []


def test_catch_up_sorts_alerts_and_advances(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"uidvalidity": 7, "last_uid": 11}))
    f = FakeImap(uids=[12, 13, 14], headers={12: H("x@chase.com"), 13: H("jobs@anduril.com", "Interview"),
                                              14: H("new@unknown.dev")})
    alerts = []
    n, state = run_catch_up(f, tmp_path, alerts=alerts)
    assert n == 3 and state.load()["last_uid"] == 14
    assert ("12", "-X-GM-LABELS", "(\\Inbox)") in stores(f)
    assert [d.watch for d, m in alerts] == ["Anduril"] and alerts[0][1].subject == "Interview"
    log = [json.loads(line) for line in (tmp_path / "moves.jsonl").read_text().splitlines()]
    assert [e["kind"] for e in log] == ["sort", "watch", "keep"] and log[0]["folder"] == "Finance"


def test_uidvalidity_change_resets_without_reprocessing(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"uidvalidity": 3, "last_uid": 9999}))
    f = FakeImap(uids=[1, 2], headers={1: H("x@chase.com"), 2: H("x@chase.com")}, uidvalidity=8, uidnext=3)
    n, state = run_catch_up(f, tmp_path)
    assert n == 0 and stores(f) == [] and state.load() == {"uidvalidity": 8, "last_uid": 2}


def test_connection_failure_mid_batch_keeps_earlier_progress_and_retries_the_failed_one(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"uidvalidity": 7, "last_uid": 11}))
    f = FakeImap(uids=[12, 13], headers={12: H("x@chase.com"), 13: H("y@chase.com")},
                 fail_on=(13, "+X-GM-LABELS"))
    with pytest.raises(OSError):
        run_catch_up(f, tmp_path)
    assert ms.State(tmp_path / "state.json").load()["last_uid"] == 12  # 13 is retried after reconnect


def test_alert_failure_never_blocks_sorting(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"uidvalidity": 7, "last_uid": 0}))
    f = FakeImap(uids=[1, 2], headers={1: H("jobs@anduril.com"), 2: H("x@chase.com")})

    def boom(d, m):
        raise RuntimeError("notifier missing")
    state = ms.State(tmp_path / "state.json")
    n = ms.catch_up(f, cfg(), state, alert=boom, log_path=tmp_path / "m.jsonl")
    assert n == 2 and ("2", "-X-GM-LABELS", "(\\Inbox)") in stores(f)


def test_corrupt_state_reads_as_fresh(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    assert ms.State(p).load() is None


def test_state_write_is_atomic(tmp_path):
    p = tmp_path / "state.json"
    ms.State(p).save(7, 42)
    assert json.loads(p.read_text()) == {"uidvalidity": 7, "last_uid": 42}
    assert not list(tmp_path.glob("*.tmp"))


# ---------- IDLE line handling ----------

@pytest.mark.parametrize("line,expected", [
    (b"* 23 EXISTS\r\n", "new"),
    (b"* 4 EXPUNGE\r\n", "other"),
    (b"* 5 FETCH (FLAGS (\\Seen))\r\n", "other"),
    (b"* BYE System error\r\n", "bye"),
    (b"", "bye"),
])
def test_classify_idle_line(line, expected):
    assert ms.classify_idle_line(line) == expected


# ---------- CLI dry run ----------

def test_check_cli_prints_decision(tmp_path, capsys):
    (tmp_path / "rules.json").write_text(json.dumps(RULES))
    (tmp_path / "watch.json").write_text(json.dumps(WATCH))
    rc = ms.main(["check", "--config", str(tmp_path), "jobs@anduril.com", "Interview"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["kind"] == "watch" and out["watch"] == "Anduril"


# ---------- IDLE over a real socket ----------

import socket  # noqa: E402


class FakeM:
    """Stands in for imaplib.IMAP4_SSL: a real socket for select(), scripted server lines for readline()."""

    def __init__(self, sock, lines):
        self.sock, self.lines, self.sent = sock, list(lines), []

    def _new_tag(self):
        return b"A7"

    def send(self, data):
        self.sent.append(data)

    def readline(self):
        return self.lines.pop(0) if self.lines else b""


def conn_with(lines, push=False):
    a, b = socket.socketpair()
    if push:
        b.send(b"x")   # makes `a` readable, like the server pushing a line
    c = object.__new__(ms.GmailConnection)
    c.M = FakeM(a, lines)
    return c, (a, b)


def test_idle_returns_activity_on_push_and_ends_with_done():
    c, socks = conn_with([b"+ idling\r\n", b"* 24 EXISTS\r\n", b"A7 OK IDLE terminated\r\n"], push=True)
    assert c.idle(5) == "activity"
    assert c.M.sent == [b"A7 IDLE\r\n", b"DONE\r\n"]


def test_idle_refresh_timeout_sends_done():
    c, socks = conn_with([b"+ idling\r\n", b"A7 OK IDLE terminated\r\n"])
    t = time.monotonic()
    assert c.idle(0.2) == "timeout" and time.monotonic() - t < 2
    assert c.M.sent[-1] == b"DONE\r\n"


def test_idle_bye_means_reconnect():
    c, socks = conn_with([b"+ idling\r\n", b"* BYE going away\r\n"], push=True)
    assert c.idle(5) == "bye"


def test_idle_refused_raises():
    c, socks = conn_with([b"A7 BAD unknown command\r\n"])
    with pytest.raises(ms.ImapError):
        c.idle(1)


def test_idle_connection_closed_during_done_means_reconnect():
    c, socks = conn_with([b"+ idling\r\n"])
    assert c.idle(0.1) == "bye"

