"""Event decoder — deserialises events from the internal JSON wire format."""
import json
from datetime import datetime, timezone

# All protocol versions this decoder accepts.
SUPPORTED_VERSIONS = frozenset({1, 2})


class DecodedEvent:
    def __init__(self, version: int, ts: datetime, event_type: str, payload: dict):
        self.version = version
        self.ts = ts
        self.event_type = event_type
        self.payload = payload

    def __repr__(self) -> str:
        return (f"DecodedEvent(version={self.version}, ts={self.ts.isoformat()}, "
                f"event={self.event_type!r})")


def decode(raw: str) -> DecodedEvent:
    """Parse a raw JSON event string and return a DecodedEvent.

    Raises ValueError on unknown version or malformed input.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed JSON: {exc}") from exc

    version = data.get("version")
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"unsupported protocol version: {version!r}")

    # Version 1 and 2 both encode timestamps as Unix integer seconds.
    ts = datetime.fromtimestamp(int(data["ts"]), tz=timezone.utc)

    return DecodedEvent(
        version=version,
        ts=ts,
        event_type=data["event"],
        payload=data.get("payload", {}),
    )
