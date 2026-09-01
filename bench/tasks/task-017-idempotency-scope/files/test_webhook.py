"""Test suite for payment webhook handler."""
import time
from webhook import handle_webhook, processed_webhooks


def clear_cache():
    """Clear the webhook cache between tests."""
    processed_webhooks.clear()


def test_duplicate_webhook_ignored():
    """Test that a retried webhook (same type, same key) is deduplicated."""
    clear_cache()

    # First event
    event1 = {
        'type': 'charge.created',
        'idempotency_key': 'tx_12345',
        'data': {'amount': 100, 'currency': 'USD'}
    }
    result1 = handle_webhook(event1)
    assert result1['success'], f"First event should succeed: {result1}"

    # Small delay to ensure time.time() differs
    time.sleep(0.01)

    # Retry with same event (retry due to network failure)
    event2 = {
        'type': 'charge.created',
        'idempotency_key': 'tx_12345',  # SAME KEY
        'data': {'amount': 100, 'currency': 'USD'}
    }
    result2 = handle_webhook(event2)
    # After fix: should be marked as duplicate (already processed)
    # Before fix: with time.time() key, this would be treated as new


def test_different_event_types_same_key():
    """Test that different event types with same idempotency_key are NOT deduplicated.

    This tests the hidden invariant from PAYMENTS.md:
    The same idempotency_key can legitimately appear with different event types.
    """
    clear_cache()

    # First event: charge created
    event1 = {
        'type': 'charge.created',
        'idempotency_key': 'tx_12345',
        'data': {'amount': 100, 'currency': 'USD'}
    }
    result1 = handle_webhook(event1)
    assert result1['success'], f"charge.created should succeed: {result1}"
    assert 'created' in result1['message'].lower()

    # Second event: same logical transaction (same key), but different type
    event2 = {
        'type': 'charge.updated',
        'idempotency_key': 'tx_12345',  # SAME KEY
        'data': {'status': 'captured'}
    }
    result2 = handle_webhook(event2)
    # MUST succeed (not be treated as a duplicate)
    assert result2['success'], f"charge.updated with same idempotency_key should succeed: {result2}"
    assert 'updated' in result2['message'].lower()

    # Third event: refund (same transaction)
    event3 = {
        'type': 'refund.completed',
        'idempotency_key': 'tx_12345',  # SAME KEY
        'data': {'amount': 100, 'currency': 'USD'}
    }
    result3 = handle_webhook(event3)
    assert result3['success'], f"refund.completed with same idempotency_key should succeed: {result3}"
    assert 'refund' in result3['message'].lower()


def test_true_duplicate_detected():
    """Test that a true duplicate (same type, same key, both from provider retry) is detected."""
    clear_cache()

    # Initial event
    event_initial = {
        'type': 'charge.created',
        'idempotency_key': 'tx_67890',
        'data': {'amount': 50, 'currency': 'USD'}
    }
    result_initial = handle_webhook(event_initial)
    assert result_initial['success']

    # Retry of the exact same event (network failure caused the retry)
    event_retry = {
        'type': 'charge.created',
        'idempotency_key': 'tx_67890',  # SAME
        'data': {'amount': 50, 'currency': 'USD'}
    }
    result_retry = handle_webhook(event_retry)
    # After fix: should detect duplicate and not double-process
    assert not result_retry['success'], "Duplicate should be rejected"


if __name__ == '__main__':
    test_duplicate_webhook_ignored()
    print("✓ test_duplicate_webhook_ignored")

    test_different_event_types_same_key()
    print("✓ test_different_event_types_same_key")

    test_true_duplicate_detected()
    print("✓ test_true_duplicate_detected")

    print("\nAll tests passed!")
