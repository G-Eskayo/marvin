"""A Mac whose pipeline pauses for stale or stuck code hands the scanner role to the standby (marvin#458 follow-up).

#693 made a stale Mac refuse to dispatch, but it kept writing a fresh scanner heartbeat, so the standby saw "the primary
scanned 10 min ago" and stayed idle: nobody dispatched while the stuck Mac waited to be fixed. Now the heartbeat says
when a scan paused, the standby takes over while it does, and the primary takes the role back once it is current. A
claim check stops two scanners dispatching one ticket in the handover window.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scanner_role as sr  # noqa: E402
import ticket_pipeline as tp  # noqa: E402

PRIMARY = sr.PRIMARY_PREFIX + "-1"
STANDBY = "standby-1"
FIX = "this Mac's MARVIN code is 4 commits behind main (oldest 30h): code sync is stuck; resolve it (see repo:sync)"
STALE = {"state": "stale", "detail": "", "behind": 4, "oldest_hours": 30.0}
CURRENT = {"state": "current", "detail": "", "behind": 0, "oldest_hours": None}
REAL_WRITE = sr.write_heartbeat


# ── the heartbeat says when a scan paused ────────────────────────────────────

def test_heartbeat_records_a_pause_and_omits_it_otherwise(tmp_path):
    p = tmp_path / "hb.json"
    sr.write_heartbeat(PRIMARY, now=100.0, path=p, paused=FIX)
    assert json.loads(p.read_text()) == {"device": PRIMARY, "ts": 100.0, "paused": FIX}
    sr.write_heartbeat(PRIMARY, now=200.0, path=p)
    assert json.loads(p.read_text()) == {"device": PRIMARY, "ts": 200.0}


def test_check_primary_reads_the_pause_over_ssh(monkeypatch):
    import task_dispatch
    import machine_profile
    monkeypatch.setattr(machine_profile, "remote_devices", lambda: {PRIMARY: {"tailscale_hostname": "p"}})
    monkeypatch.setattr(task_dispatch, "_tailscale_online_hosts", lambda: {"p"})
    run = lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps({"device": PRIMARY, "ts": 1000.0, "paused": FIX}))
    assert sr.check_primary(now=1600.0, run=run) == (600.0, True, FIX)
    run = lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps({"device": PRIMARY, "ts": 1000.0}))
    assert sr.check_primary(now=1600.0, run=run) == (600.0, True, None)


@pytest.mark.parametrize("stdout", ["", "not json", "[]", '{"ts": "x"}', '{"ts": 1, "paused": 5}'])
def test_a_garbled_heartbeat_fails_open_never_crashes(monkeypatch, stdout):
    import task_dispatch
    import machine_profile
    monkeypatch.setattr(machine_profile, "remote_devices", lambda: {PRIMARY: {"tailscale_hostname": "p"}})
    monkeypatch.setattr(task_dispatch, "_tailscale_online_hosts", lambda: {"p"})
    age, reachable, paused = sr.check_primary(now=10.0, run=lambda *a, **k: SimpleNamespace(returncode=0, stdout=stdout))
    assert sr.decide(STANDBY, age, reachable, paused)[0] in (True, False)
    if stdout != '{"ts": 1, "paused": 5}':
        assert age is None   # unreadable heartbeat: the standby scans (fail open, as before)


# ── who scans ────────────────────────────────────────────────────────────────

def test_standby_takes_over_while_the_primary_is_paused_for_stale_code():
    ok, why = sr.decide(STANDBY, 10 * 60, True, FIX)
    assert ok is True and "paused" in why


def test_standby_stays_idle_once_the_primary_scans_unpaused_again():
    ok, _ = sr.decide(STANDBY, 10 * 60, True, None)
    assert ok is False


@pytest.mark.parametrize("age,reachable,paused", [(None, None, None), (60, True, FIX), (60, True, None), (None, False, None)])
def test_the_primary_always_scans_whatever_the_standby_does(age, reachable, paused):
    # No ping-pong: the primary's role never depends on anything the standby writes, so a paused primary keeps
    # scanning (and keeps refusing) until it is fixed, then simply resumes.
    assert sr.decide(PRIMARY, age, reachable, paused)[0] is True


# ── the pipeline writes the pause into its heartbeat ─────────────────────────

class Mac:
    """One machine running main(): its role, its code freshness, its heartbeat, and what it dispatched."""

    def __init__(self, monkeypatch, tmp_path, device, freshness, primary_hb=None, primary_reachable=True):
        self.mp, self.device, self.freshness = monkeypatch, device, freshness
        self.hb = tmp_path / f"{device}-hb.json"
        self.primary_hb, self.primary_reachable = primary_hb, primary_reachable
        self.dispatched: list[int] = []

    def run(self, now=1000.0):
        mp = self.mp
        import machine_profile
        mp.setattr(machine_profile, "registry_id", lambda: self.device)
        mp.setattr(sr, "write_heartbeat", lambda dev, paused=None, **k: REAL_WRITE(dev, now=now, path=self.hb, paused=paused))

        def check_primary():
            if not self.primary_reachable:
                return None, False, None
            doc = json.loads(self.primary_hb.read_text()) if self.primary_hb and self.primary_hb.exists() else None
            return (None, True, None) if doc is None else (now - doc["ts"], True, doc.get("paused"))
        mp.setattr(sr, "should_scan", lambda: sr.decide(self.device, *check_primary()))
        mp.setattr(tp.failure_breaker, "code_freshness", lambda *a, **k: self.freshness)
        mp.setattr(tp.failure_breaker, "tripped", lambda now=None, project=None: [])
        mp.setattr(tp, "_unclaimed_ready_tickets", lambda repo=None: [{"number": 7, "title": "t", "createdAt": "z", "labels": []}])
        mp.setattr(tp, "_select_for_profile", lambda *a, **k: (self.device, {}))
        mp.setattr(tp, "_retry_not_before", lambda *a, **k: None)
        mp.setattr(tp, "_claim", lambda n, *a, **k: True)
        mp.setattr(tp, "dispatch", lambda *a, **k: self.dispatched.append(7) or SimpleNamespace(ok=True, error=""))
        mp.setattr(sys, "argv", ["ticket_pipeline.py"])
        tp.main()
        return json.loads(self.hb.read_text()) if self.hb.exists() else None


def test_a_stale_scan_writes_a_paused_heartbeat_and_a_current_one_clears_it(monkeypatch, tmp_path):
    mini = Mac(monkeypatch, tmp_path, PRIMARY, STALE)
    assert "code sync is stuck" in mini.run()["paused"] and mini.dispatched == []
    mini.freshness = CURRENT
    assert "paused" not in mini.run() and mini.dispatched == [7]


def test_handover_then_handback(monkeypatch, tmp_path):
    mini = Mac(monkeypatch, tmp_path, PRIMARY, STALE)
    standby = Mac(monkeypatch, tmp_path, STANDBY, CURRENT, primary_hb=mini.hb)
    mini.run(now=1000.0)
    standby.run(now=1600.0)                          # primary paused 10 min ago: the standby dispatches
    assert mini.dispatched == [] and standby.dispatched == [7]
    mini.freshness = CURRENT
    mini.run(now=4600.0)                             # fixed: the primary takes the role back by itself
    standby.run(now=5200.0)                          # and the standby stands down on its next scan
    assert mini.dispatched == [7] and standby.dispatched == [7]


def test_both_macs_stale_nobody_dispatches_and_both_say_so(monkeypatch, tmp_path, capsys):
    mini = Mac(monkeypatch, tmp_path, PRIMARY, STALE)
    standby = Mac(monkeypatch, tmp_path, STANDBY, STALE, primary_hb=mini.hb)
    for t in (1000.0, 4600.0, 8200.0):              # several hours: neither flips the other back and forth
        mini.run(now=t)
        assert standby.run(now=t + 600)["paused"]
        assert sr.decide(PRIMARY, None, None, None)[0] is True
    assert mini.dispatched == [] and standby.dispatched == []
    assert capsys.readouterr().err.count("dispatch PAUSED on stale code") == 6
    # each Mac's own pipeline:breaker card goes red from its own trip
    assert tp.failure_breaker.code_trip(freshness=STALE)["fix"] == FIX


def test_standby_offline_the_primary_still_refuses_and_stays_red(monkeypatch, tmp_path):
    mini = Mac(monkeypatch, tmp_path, PRIMARY, STALE)
    assert mini.run()["paused"] and mini.dispatched == []


def test_a_stale_standby_taking_over_also_refuses(monkeypatch, tmp_path):
    mini = Mac(monkeypatch, tmp_path, PRIMARY, STALE)
    standby = Mac(monkeypatch, tmp_path, STANDBY, STALE, primary_hb=mini.hb)
    mini.run(now=1000.0)
    assert standby.run(now=1600.0)["paused"] and standby.dispatched == []


def test_primary_unreachable_and_standby_stale_nobody_dispatches(monkeypatch, tmp_path):
    standby = Mac(monkeypatch, tmp_path, STANDBY, STALE, primary_reachable=False)
    assert standby.run()["paused"] and standby.dispatched == []


# ── claim race at handover ───────────────────────────────────────────────────

class FakeGitHub:
    """One issue's labels, with `gh issue edit/view` served in a forced global order across threads."""

    def __init__(self, schedule):
        self.labels: set[str] = set()
        self.schedule, self.i = schedule, 0
        self.cv = threading.Condition()

    def run_for(self, who):
        def run(cmd, **k):
            op = "add" if "--add-label" in cmd else "remove" if "--remove-label" in cmd else "view"
            with self.cv:
                if op != "remove":   # removals are the loser backing off; they may happen at any time
                    self.cv.wait_for(lambda: self.i < len(self.schedule) and self.schedule[self.i] == (who, op), timeout=5)
                if op == "add":
                    self.labels.add(cmd[cmd.index("--add-label") + 1])
                elif op == "remove":
                    self.labels.discard(cmd[cmd.index("--remove-label") + 1])
                out = json.dumps({"labels": [{"name": l} for l in sorted(self.labels)]}) if op == "view" else ""
                if op != "remove":
                    self.i += 1
                self.cv.notify_all()
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        return run


def _orders():
    ops = [("a", "add"), ("a", "view"), ("b", "add"), ("b", "view")]
    import itertools
    for perm in itertools.permutations(ops):
        if perm.index(("a", "add")) < perm.index(("a", "view")) and perm.index(("b", "add")) < perm.index(("b", "view")):
            yield list(perm)


@pytest.mark.parametrize("schedule", list(_orders()), ids=lambda s: ",".join(f"{w}-{o}" for w, o in s))
def test_two_scanners_claiming_one_ticket_never_both_win(monkeypatch, schedule):
    gh = FakeGitHub(schedule)
    monkeypatch.setattr(tp, "_ensure_board", lambda repo: None)
    local = threading.local()
    monkeypatch.setattr(tp.subprocess, "run", lambda cmd, **k: local.run(cmd, **k))
    won = {}

    def scanner(who, label):
        local.run = gh.run_for(who)
        won[who] = tp._claim(7, label, title="t")

    threads = [threading.Thread(target=scanner, args=("a", "mac-a")), threading.Thread(target=scanner, args=("b", "mac-b"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sum(won.values()) <= 1, (schedule, won)
    winners = [w for w, ok in won.items() if ok]
    # the label left on the ticket is the winner's alone (or none, when both backed off: the next scan retries)
    assert gh.labels == ({f"claimed:mac-{winners[0]}"} if winners else set())


def test_claim_backs_off_when_another_scanner_already_holds_it(monkeypatch):
    calls = []
    def run(cmd, **k):
        calls.append(cmd)
        out = json.dumps({"labels": [{"name": "claimed:other-mac"}, {"name": "claimed:this-mac"}]}) if "view" in cmd else ""
        return SimpleNamespace(returncode=0, stdout=out, stderr="")
    monkeypatch.setattr(tp.subprocess, "run", run)
    monkeypatch.setattr(tp, "_ensure_board", lambda repo: None)
    assert tp._claim(7, "this-mac") is False
    assert any("--remove-label" in c and "claimed:this-mac" in c for c in calls)
    assert not [e for e in tp.ts.read_stages(7) if e.get("stage") == "claimed"]   # nothing recorded for a claim we gave up


def test_claim_still_proceeds_when_the_verify_read_fails(monkeypatch, capsys):
    # The verify is extra protection for the handover window; a failed read keeps the old behavior (claimed).
    def run(cmd, **k):
        return SimpleNamespace(returncode=1 if "view" in cmd else 0, stdout="", stderr="boom")
    monkeypatch.setattr(tp.subprocess, "run", run)
    monkeypatch.setattr(tp, "_ensure_board", lambda repo: None)
    assert tp._claim(7, "this-mac") is True
    assert "could not verify" in capsys.readouterr().err
