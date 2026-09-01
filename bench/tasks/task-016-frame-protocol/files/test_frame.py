"""Test suite for Marvin Frame Protocol v2 decoder."""
from frame import decode_frame


def test_simple_frame():
    """Test decoding a simple frame without escape sequences."""
    # Frame: 0x7E | 0x01 0x02 0x03 | checksum | 0x7E
    # checksum = 0x01 ^ 0x02 ^ 0x03 = 0x00
    frame = bytes([0x7E, 0x01, 0x02, 0x03, 0x00, 0x7E])
    result = decode_frame(frame)
    assert result['frame_ok'], f"Expected frame to be OK, got error: {result.get('error')}"
    assert result['payload'] == bytes([0x01, 0x02, 0x03])


def test_frame_with_escaped_delimiter():
    """Test frame with 0x7E (frame delimiter) in payload.

    Worked example from PROTOCOL.md:
    Payload: [0xAB, 0x7E, 0xCD]
    Checksum: 0xAB ^ 0x7E ^ 0xCD = 0xDC
    On-wire: 0x7E | 0xAB 0x7D 0x5E 0xCD | 0xDC | 0x7E
    """
    frame = bytes([0x7E, 0xAB, 0x7D, 0x5E, 0xCD, 0xDC, 0x7E])
    result = decode_frame(frame)
    assert result['frame_ok'], f"Expected frame to be OK, got error: {result.get('error')}"
    assert result['payload'] == bytes([0xAB, 0x7E, 0xCD]), \
        f"Expected payload [0xAB, 0x7E, 0xCD], got {list(result['payload'])}"


def test_frame_with_escaped_escape():
    """Test frame with 0x7D (escape byte) in payload.

    Payload: [0x42, 0x7D, 0x99]
    Checksum: 0x42 ^ 0x7D ^ 0x99 = 0xEC
    On-wire: 0x7E | 0x42 0x7D 0x5D 0x99 | 0xEC | 0x7E
    """
    frame = bytes([0x7E, 0x42, 0x7D, 0x5D, 0x99, 0xEC, 0x7E])
    result = decode_frame(frame)
    assert result['frame_ok'], f"Expected frame to be OK, got error: {result.get('error')}"
    assert result['payload'] == bytes([0x42, 0x7D, 0x99])


def test_invalid_checksum():
    """Test that invalid checksum is detected."""
    # Correct frame: 0x7E | 0x01 0x02 0x03 | 0x00 | 0x7E
    # Corrupt checksum to 0xFF
    frame = bytes([0x7E, 0x01, 0x02, 0x03, 0xFF, 0x7E])
    result = decode_frame(frame)
    assert not result['frame_ok'], "Expected checksum mismatch error"


if __name__ == '__main__':
    test_simple_frame()
    print("✓ test_simple_frame")
    test_frame_with_escaped_delimiter()
    print("✓ test_frame_with_escaped_delimiter")
    test_frame_with_escaped_escape()
    print("✓ test_frame_with_escaped_escape")
    test_invalid_checksum()
    print("✓ test_invalid_checksum")
    print("\nAll tests passed!")
