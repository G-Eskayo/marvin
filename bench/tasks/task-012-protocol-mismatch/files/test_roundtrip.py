"""Existing round-trip tests — all pass against the current v1/v2 implementation."""
import json
import pytest
from encoder import encode, PROTOCOL_VERSION
from decoder import decode


def test_encode_produces_valid_json():
    raw = encode("user.created", {"id": 99})
    data = json.loads(raw)
    assert data["event"] == "user.created"
    assert data["payload"] == {"id": 99}
    assert data["version"] == PROTOCOL_VERSION


def test_roundtrip_current_version():
    raw = encode("order.placed", {"order_id": 42, "amount": 9.99})
    event = decode(raw)
    assert event.event_type == "order.placed"
    assert event.payload["order_id"] == 42
    assert event.version == PROTOCOL_VERSION


def test_decode_rejects_unknown_version():
    bad = json.dumps({"version": 999, "ts": 1700000000, "event": "x", "payload": {}})
    with pytest.raises(ValueError, match="unsupported protocol version"):
        decode(bad)


def test_decode_rejects_malformed_json():
    with pytest.raises(ValueError, match="malformed JSON"):
        decode("not-json")
