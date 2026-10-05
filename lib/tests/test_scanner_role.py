import json
import scanner_role as sr


def test_primary_always_scans():
    assert sr.decide("mac-mini-1", None, None)[0] is True


def test_standby_waits_while_primary_is_fresh():
    ok, why = sr.decide("macbook-pro-1", 40 * 60, True)
    assert ok is False and "40 min" in why


def test_standby_takes_over_when_primary_is_stale_unreachable_or_unreadable():
    assert sr.decide("macbook-pro-1", sr.STALE_AFTER + 60, True)[0] is True
    assert sr.decide("macbook-pro-1", None, False)[0] is True
    assert sr.decide("macbook-pro-1", None, True)[0] is True   # fail open: a duplicate scan is safe


def test_heartbeat_roundtrip(tmp_path):
    p = tmp_path / "hb.json"
    sr.write_heartbeat("mac-mini-1", now=100.0, path=p)
    assert json.loads(p.read_text()) == {"device": "mac-mini-1", "ts": 100.0}
