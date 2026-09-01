"""Marvin Frame Protocol v2 decoder (buggy checksum implementation)."""


def decode_frame(on_wire_bytes):
    """Decode a frame from on-wire bytes.

    Args:
        on_wire_bytes: bytes or bytearray, structure: 0x7E | escaped_payload | checksum | 0x7E

    Returns:
        {
            'frame_ok': bool,
            'payload': bytes (if frame_ok),
            'error': str (if not frame_ok)
        }
    """
    if len(on_wire_bytes) < 4:
        return {'frame_ok': False, 'error': 'Frame too short'}

    if on_wire_bytes[0] != 0x7E or on_wire_bytes[-1] != 0x7E:
        return {'frame_ok': False, 'error': 'Missing frame delimiters'}

    # Extract escaped payload and checksum
    escaped_payload = on_wire_bytes[1:-2]
    on_wire_checksum = on_wire_bytes[-2]

    # Unescape the payload
    raw_payload = bytearray()
    i = 0
    while i < len(escaped_payload):
        if escaped_payload[i] == 0x7D:
            if i + 1 >= len(escaped_payload):
                return {'frame_ok': False, 'error': 'Incomplete escape sequence'}
            next_byte = escaped_payload[i + 1]
            if next_byte == 0x5E:
                raw_payload.append(0x7E)
            elif next_byte == 0x5D:
                raw_payload.append(0x7D)
            else:
                return {'frame_ok': False, 'error': f'Invalid escape sequence: 0x7D 0x{next_byte:02X}'}
            i += 2
        else:
            raw_payload.append(escaped_payload[i])
            i += 1

    computed_checksum = compute_xor(escaped_payload)

    if computed_checksum != on_wire_checksum:
        return {'frame_ok': False, 'error': f'Checksum mismatch: got 0x{computed_checksum:02X}, expected 0x{on_wire_checksum:02X}'}

    return {'frame_ok': True, 'payload': bytes(raw_payload)}


def compute_xor(data):
    """Compute XOR of all bytes in data."""
    result = 0
    for byte in data:
        result ^= byte
    return result
