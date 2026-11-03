"""Hidden check (marvin#645): v3 round-trip works and v1/v2 events still decode."""
import json
from datetime import datetime, timezone

import encoder
from decoder import decode


def test_encoder_emits_v3_with_an_iso_timestamp():
    data = json.loads(encoder.encode("user.created", {"id": 1}))
    assert data["version"] == 3
    assert isinstance(data["ts"], str)
    datetime.fromisoformat(data["ts"])


def test_v3_roundtrip():
    ev = decode(encoder.encode("order.placed", {"order_id": 7}))
    assert ev.version == 3 and ev.event_type == "order.placed" and ev.payload == {"order_id": 7}
    assert ev.ts.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - ev.ts).total_seconds()) < 120


def test_v3_explicit_timestamp_decodes_exactly():
    raw = json.dumps({"version": 3, "ts": "2024-01-15T12:30:00+00:00", "event": "x", "payload": {}})
    assert decode(raw).ts == datetime(2024, 1, 15, 12, 30, tzinfo=timezone.utc)


def test_v1_and_v2_unix_timestamps_still_decode():
    for v in (1, 2):
        raw = json.dumps({"version": v, "ts": 1700000000, "event": "x", "payload": {}})
        assert decode(raw).ts == datetime.fromtimestamp(1700000000, tz=timezone.utc)
