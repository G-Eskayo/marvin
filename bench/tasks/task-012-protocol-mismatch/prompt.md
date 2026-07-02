The team has decided to upgrade the event protocol to version 3.

**Version 3 change:** timestamps must be encoded as ISO 8601 strings
(`"2024-01-15T12:30:00+00:00"`) instead of Unix integer seconds.

All existing v1/v2 tests must continue to pass. A version 3 round-trip
(encode then decode) must also work correctly end-to-end.

Update `encoder.py` and any other files that need to change to support
version 3. Do not break backward compatibility for v1 and v2 decoding.
