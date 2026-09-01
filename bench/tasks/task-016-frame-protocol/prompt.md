The frame decoder in `frame.py` is failing on valid frames from our protocol.
We think the checksum calculation is wrong.

**Background:** Our device firmware sends frames using Marvin Frame Protocol v2,
which is documented in `PROTOCOL.md` with worked examples.

**Task:** Debug and fix `decode_frame()` to correctly validate frames according to the spec.
All worked examples in `PROTOCOL.md` must decode successfully.

The function is partially implemented already (the byte-stuffing escape logic is correct),
but something is wrong with checksum validation. Read the protocol spec carefully and
ensure the checksum is computed exactly as specified.
