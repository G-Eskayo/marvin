# Marvin Frame Protocol v2

## Frame Structure

A frame consists of:
1. **Start flag**: 0x7E (one byte)
2. **Escaped payload**: N bytes (payload with byte-stuffing applied)
3. **Checksum**: 1 byte (see Checksum section below)
4. **End flag**: 0x7E (one byte)

## Byte Stuffing (Escape Sequence)

To allow 0x7E (the frame delimiter) to appear in payload:
- Any payload byte equal to 0x7E is escaped as: 0x7D 0x5E
- Any payload byte equal to 0x7D is escaped as: 0x7D 0x5D

Unescaping (unescape to recover the original payload):
- Sequence 0x7D 0x5E → 0x7E
- Sequence 0x7D 0x5D → 0x7D
- Any other 0x7D is a protocol error

## Checksum Calculation (Key Point)

The checksum is a **simple XOR of all bytes in the original (pre-escape) payload**.

**Important:** The checksum is computed over the **raw payload bytes**, NOT the escaped on-wire bytes.

Formula:
```
checksum = raw_payload[0] ^ raw_payload[1] ^ ... ^ raw_payload[n-1]
```

Example: raw payload is `[0x01, 0x02, 0x03]`
- Checksum = 0x01 ^ 0x02 ^ 0x03 = 0x00

## Worked Example: Encoding and Decoding

### Frame with payload `[0xAB, 0x7E, 0xCD]`

**Encoding:**
1. Raw payload: `0xAB 0x7E 0xCD`
2. Checksum: 0xAB ^ 0x7E ^ 0xCD = 0xDC
3. Escape the payload:
   - 0xAB → 0xAB (no escape needed)
   - 0x7E → 0x7D 0x5E (escape frame delimiter)
   - 0xCD → 0xCD (no escape needed)
4. Frame on wire: `0x7E | 0xAB 0x7D 0x5E 0xCD | 0xDC | 0x7E`

**Decoding:**
1. On-wire frame: `0x7E | 0xAB 0x7D 0x5E 0xCD | 0xDC | 0x7E`
2. Extract and unescape the payload:
   - 0xAB → 0xAB
   - 0x7D 0x5E → 0x7E (unescape)
   - 0xCD → 0xCD
3. Recovered raw payload: `0xAB 0x7E 0xCD`
4. Verify checksum: 0xAB ^ 0x7E ^ 0xCD = 0xDC ✓ (matches on-wire checksum)
5. Return `{frame_ok: True, payload: [0xAB, 0x7E, 0xCD]}`

## Key Invariant

The checksum **must** be computed over the original, **unescaped** payload bytes.
If you accidentally compute the checksum over the escaped bytes, the decoder
will reject all valid frames. This is a common mistake when porting from other
byte-stuffing protocols that differ in this detail.

