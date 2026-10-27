"""calibrate.py and shared_labels.py: one calibration on the primary host, tau per loop with a global fallback.

Tests try to break it: the old smallest-tau bug and the never-recomputed cache (#599), loops with 0 or 1 labels, an
unknown loop, malformed rows and tau.json, a duplicate answer from two Macs, the primary offline and back, a hostile
label from the network. Everything lives in tmp_path; nothing touches the real ~/.claude or the network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
for _name in ("calibrate", "process_quarantine_reviews", "verify", "shared_labels"):
    _mod = sys.modules.get(_name)
    if _mod is not None and Path(getattr(_mod, "__file__", "") or "").resolve().parent != SCRIPTS:
        del sys.modules[_name]

import calibrate as c  # noqa: E402
import shared_labels as s  # noqa: E402


@pytest.fixture
def state(tmp_path, monkeypatch):
    d = tmp_path / "safety-monitor"
    monkeypatch.setattr(c, "STATE_DIR", d)
    monkeypatch.setattr(c, "CALIBRATION_FILE", d / "calibration.jsonl")
    monkeypatch.setattr(c, "TAU_FILE", d / "tau.json")
    return d


def write_rows(state: Path, rows):
    state.mkdir(parents=True, exist_ok=True)
    (state / "calibration.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def rows_for(loop, good_scores, bad_scores):
    return [{"loop": loop, "score": x, "label": 0} for x in good_scores] + [{"loop": loop, "score": x, "label": 1} for x in bad_scores]


# --- #599: the right tau, and it moves ------------------------------------------------------------------------------

def test_tau_is_the_largest_risk_controlled_threshold_not_the_lowest_score(state):
    write_rows(state, rows_for("research_colony", [0.4, 0.45, 0.5, 0.55, 0.6] * 3, [0.8, 0.85, 0.9, 0.95, 0.99]))
    tau = c.calibrate("research_colony")
    assert tau == 0.8  # every bad row still held; approved rows at 0.4-0.6 now pass
    assert c.get_tau("research_colony") == 0.8


def test_tau_never_drops_below_the_default(state):
    write_rows(state, rows_for("daily_digest", [0.1] * 15, [0.12] * 5))
    assert c.calibrate("daily_digest") == c.DEFAULT_TAU


def test_no_bad_labels_keeps_the_default(state):
    write_rows(state, rows_for("daily_digest", [0.5] * 25, []))
    assert c.calibrate("daily_digest") == c.DEFAULT_TAU


def test_the_cached_tau_moves_when_new_labels_arrive(state):
    write_rows(state, rows_for("research_colony", [0.4] * 10, [0.5] * 10))
    assert c.calibrate("research_colony") == 0.5
    for i in range(20):
        c.record_label("research_colony", 0.6, 0, entry_id=f"{i:016x}")
    c.record_label("research_colony", 0.9, 1, entry_id="f" * 16)
    # 11 bad rows (ten at 0.5, one at 0.9): the largest tau with <= 5% of them below it is still 0.5 ...
    assert c.get_tau("research_colony") == 0.5
    # ... until the bad rows move up: the cache follows the file, not the first value written (#599).
    write_rows(state, rows_for("research_colony", [0.4] * 20, [0.7] * 20))
    c.record_label("research_colony", 0.95, 1, entry_id="e" * 16)
    assert c.get_tau("research_colony") == 0.7


# --- per loop, with the global fallback -----------------------------------------------------------------------------

@pytest.mark.parametrize("n", [0, 1, 19])
def test_a_loop_under_the_minimum_uses_the_global_tau(state, n):
    other = rows_for("research_colony", [0.4] * 15, [0.8] * 10)
    write_rows(state, other + rows_for("self_improve", [0.35] * n, []))
    taus = c.recalibrate_all()
    assert taus["*"] == 0.8  # 25 labels in all: the global tau is risk-controlled
    assert c.get_tau("self_improve") == 0.8
    assert taus.get("self_improve", taus["*"]) == 0.8


def test_with_too_few_labels_anywhere_everything_is_the_default(state):
    write_rows(state, rows_for("research_colony", [0.4], [0.9]))
    c.recalibrate_all()
    assert c.get_tau("research_colony") == c.DEFAULT_TAU and c.get_tau("daily_digest") == c.DEFAULT_TAU


def test_a_loop_at_the_minimum_gets_its_own_tau(state):
    write_rows(state, rows_for("research_colony", [0.4] * 15, [0.8] * 5) + rows_for("daily_digest", [0.35] * 15, [0.6] * 5))
    taus = c.recalibrate_all()
    assert (taus["research_colony"], taus["daily_digest"]) == (0.8, 0.6)


def test_an_unknown_loop_gets_the_global_tau_or_the_default(state):
    assert c.get_tau("never_seen_loop") == c.DEFAULT_TAU
    write_rows(state, rows_for("research_colony", [0.4] * 15, [0.8] * 10))
    c.recalibrate_all()
    assert c.get_tau("never_seen_loop") == 0.8


def test_malformed_rows_and_a_corrupt_tau_file_do_not_raise(state):
    state.mkdir()
    (state / "calibration.jsonl").write_text('{"loop": "x", "score": 0.5, "label": 1}\nnot json\n[1,2]\n{"loop": 3}\n'
                                             '{"loop": "x", "score": "high", "label": 1}\n{"loop": "x", "score": true, "label": 0}\n')
    (state / "tau.json").write_text("{corrupt")
    assert c.get_tau("x") == c.DEFAULT_TAU
    assert c.tau_map() == {"*": c.DEFAULT_TAU, "x": c.DEFAULT_TAU}
    (state / "tau.json").write_text('{"x": "0.9", "y": 7, "z": true}')
    assert c.get_tau("x") == c.DEFAULT_TAU


@pytest.mark.parametrize("bad", [
    dict(loop_name="../etc", score=0.5, label=1), dict(loop_name="*", score=0.5, label=1),
    dict(loop_name="ok", score=1.5, label=1), dict(loop_name="ok", score=float("nan"), label=1),
    dict(loop_name="ok", score=True, label=1), dict(loop_name="ok", score=0.5, label=2),
    dict(loop_name="ok", score=0.5, label=True), dict(loop_name="ok", score=0.5, label=0, note="a\nb"),
    dict(loop_name="ok", score=0.5, label=0, note="x" * 1001), dict(loop_name="ok", score=0.5, label=0, entry_id="zz"),
])
def test_hostile_labels_are_refused_and_nothing_is_written(state, bad):
    with pytest.raises(ValueError):
        c.record_label(**bad)
    assert not (state / "calibration.jsonl").exists()


def test_the_same_entry_answered_twice_is_recorded_once(state):
    assert c.record_label("research_colony", 0.4, 0, entry_id="a" * 16) is True
    assert c.record_label("research_colony", 0.4, 1, entry_id="a" * 16) is False
    assert [r["label"] for r in c._rows()] == [0]


def test_cli_record_and_taus_speak_json(state, capsys):
    assert c._cli(["record", json.dumps({"loop": "daily_digest", "score": 0.4, "label": 1, "entry_id": "b" * 16})]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["recorded"] and out["taus"]["*"] == c.DEFAULT_TAU
    assert c._cli(["record", '{"loop": "x; rm -rf ~", "score": 0.4, "label": 1}']) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert c._cli(["record", "not json"]) == 1


# --- shared across Macs ----------------------------------------------------------------------------------------------

class FakePrimary:
    """The primary host's webhook: records into its own calibration (a separate state dir), or is offline."""

    def __init__(self, tmp_path, monkeypatch):
        self.online = True
        self.dir = tmp_path / "primary-state"
        self.calls = []
        self.mp = monkeypatch

    def _as_primary(self, fn):
        saved = (c.STATE_DIR, c.CALIBRATION_FILE, c.TAU_FILE)
        c.STATE_DIR, c.CALIBRATION_FILE, c.TAU_FILE = self.dir, self.dir / "calibration.jsonl", self.dir / "tau.json"
        try:
            return fn()
        finally:
            c.STATE_DIR, c.CALIBRATION_FILE, c.TAU_FILE = saved

    def post(self, url, payload, timeout):
        self.calls.append(("POST", url, payload))
        if not self.online:
            raise OSError("no route to host")
        try:
            rec = self._as_primary(lambda: c.record_label(payload["loop"], payload["score"], payload["label"],
                                                          payload.get("note"), payload.get("entry_id")))
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "recorded": rec, "taus": self._as_primary(c.read_taus)}

    def get(self, url, timeout):
        self.calls.append(("GET", url, None))
        if not self.online:
            raise OSError("no route to host")
        return self._as_primary(lambda: c.read_taus() or c.tau_map())

    def rows(self):
        return self._as_primary(c._rows)


@pytest.fixture
def laptop(state, tmp_path, monkeypatch):
    primary = FakePrimary(tmp_path, monkeypatch)
    monkeypatch.setattr(s, "is_primary", lambda: False)
    monkeypatch.setattr(s, "base_url", lambda: "http://primary.test:7878")
    monkeypatch.setattr(s, "_post", primary.post)
    monkeypatch.setattr(s, "_get", primary.get)
    return primary


def label(i, lab=0, loop="research_colony", score=0.4):
    return {"loop": loop, "score": score, "label": lab, "entry_id": f"{i:016x}"}


def test_on_the_primary_a_label_is_recorded_locally_with_no_network(state, monkeypatch):
    monkeypatch.setattr(s, "is_primary", lambda: True)
    monkeypatch.setattr(s, "_post", lambda *a: pytest.fail("the primary never posts to itself"))
    s.submit(label(1))
    assert [r["entry_id"] for r in c._rows()] == [f"{1:016x}"]
    assert s.deliver() == {"delivered": 0, "queued": 0, "dropped": 0}


def test_another_mac_delivers_to_the_primary_and_keeps_no_local_rows(laptop, state):
    s.submit(label(1, 1))
    assert s.deliver() == {"delivered": 1, "queued": 0, "dropped": 0}
    assert [r["label"] for r in laptop.rows()] == [1]
    assert c._rows() == []  # the one calibration is the primary's
    assert laptop.calls[0][1] == "http://primary.test:7878/safety/label"


def test_primary_offline_queues_then_delivers_on_contact_in_order(laptop, state):
    laptop.online = False
    for i in range(3):
        s.submit(label(i))
    assert s.deliver() == {"delivered": 0, "queued": 3, "dropped": 0}
    assert s.deliver()["queued"] == 3  # still offline: nothing lost, nothing duplicated
    laptop.online = True
    assert s.sync()["delivered"] == 3
    assert [r["entry_id"] for r in laptop.rows()] == [f"{i:016x}" for i in range(3)]
    assert s.deliver() == {"delivered": 0, "queued": 0, "dropped": 0}


def test_a_redelivery_after_a_lost_reply_is_not_counted_twice(laptop, state, monkeypatch):
    s.submit(label(7))
    real = laptop.post

    def reply_lost(url, payload, timeout):
        real(url, payload, timeout)  # the primary recorded it ...
        raise TimeoutError("... but the reply never arrived")

    monkeypatch.setattr(s, "_post", reply_lost)
    assert s.deliver()["queued"] == 1
    monkeypatch.setattr(s, "_post", real)
    assert s.deliver()["delivered"] == 1
    assert len(laptop.rows()) == 1


def test_two_macs_answering_the_same_entry_record_one_label(laptop, state, monkeypatch):
    s.submit(label(9, 0))
    s.deliver()
    s.submit(label(9, 1))  # the other Mac's answer for the same entry, before its sync caught up
    assert s.deliver()["delivered"] == 1
    assert [r["label"] for r in laptop.rows()] == [0]


def test_a_label_the_primary_refuses_is_dropped_not_retried_forever(laptop, state):
    s.submit(label(1))
    with c._locked():
        (state / "outbox.jsonl").open("a").write(json.dumps({"loop": "../x", "score": 0.5, "label": 1}) + "\n")
    s.submit(label(2))
    out = s.deliver()
    assert out == {"delivered": 2, "queued": 0, "dropped": 1}


def test_a_torn_outbox_line_does_not_block_the_rest(laptop, state):
    s.submit(label(1))
    (state / "outbox.jsonl").open("a").write('{"loop": "research_col')
    assert s.deliver() == {"delivered": 1, "queued": 0, "dropped": 1}


def test_sync_caches_the_primarys_taus_for_this_macs_loops(laptop, state):
    laptop._as_primary(lambda: write_rows(laptop.dir, rows_for("research_colony", [0.4] * 15, [0.8] * 10)))
    laptop._as_primary(c.recalibrate_all)
    s.sync()
    assert c.get_tau("research_colony") == 0.8
    laptop.online = False
    s.sync()
    assert c.get_tau("research_colony") == 0.8  # offline: the last known map stays


def test_no_registry_means_this_machine_is_the_primary(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "_registry", lambda: {})
    assert s.primary() is None and s.is_primary() is True


def test_the_primary_is_the_registrys_macos_desktop_never_a_hardcoded_name(monkeypatch):
    reg = {"lap": {"kind": "laptop", "tailscale_hostname": "lap-ts"},
           "box": {"kind": "desktop", "os": "linux", "tailscale_hostname": "box-ts"},
           "desk": {"kind": "desktop", "tailscale_hostname": "desk-ts"}}
    monkeypatch.setattr(s, "_registry", lambda: reg)
    assert s.primary() == ("desk", "desk-ts")
    monkeypatch.setattr(s, "_my_id", lambda: "desk")
    assert s.is_primary() is True
    monkeypatch.setattr(s, "_my_id", lambda: "lap")
    assert s.is_primary() is False
    monkeypatch.delenv("MARVIN_SAFETY_URL", raising=False)
    assert s.base_url() == "http://desk-ts:7878"
