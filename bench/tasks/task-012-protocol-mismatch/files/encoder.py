"""Event encoder — serialises events to the internal JSON wire format."""
import json
from datetime import datetime, timezone

# Current protocol version. Decoders must list this in SUPPORTED_VERSIONS.
PROTOCOL_VERSION = 2


def encode(event_type: str, payload: dict) -> str:
    """Return a JSON string representing a single event.

    Version 2 wire format:
        {
          "version": 2,
          "ts": <unix timestamp as integer seconds>,
          "event": "<event_type>",
          "payload": { ... }
        }
    """
    return json.dumps({
        "version": PROTOCOL_VERSION,
        "ts": int(datetime.now(timezone.utc).timestamp()),
        "event": event_type,
        "payload": payload,
    })
