"""Payment webhook handler with deduplication (buggy)."""
import time


# Cache of recently processed webhook IDs (in real code, this would be Redis)
processed_webhooks = {}


def handle_webhook(event):
    """Process a payment webhook event.

    Args:
        event: dict with keys 'type', 'idempotency_key', and 'data'

    Returns:
        dict with 'success' bool and 'message' str
    """
    event_type = event.get('type')
    idempotency_key = event.get('idempotency_key')
    event_data = event.get('data', {})

    # BUG 1: Using time.time() as a cache key
    # This creates a new key for every single call, defeating the purpose of deduplication
    cache_key = time.time()

    if cache_key in processed_webhooks:
        return {
            'success': False,
            'message': f'Duplicate webhook (already processed at {processed_webhooks[cache_key]})'
        }

    # Process the event (in real code, this updates the database)
    processed_webhooks[cache_key] = time.time()

    # Simulate processing the charge
    if event_type == 'charge.created':
        return {
            'success': True,
            'message': f'Charge created: {event_data.get("amount")} {event_data.get("currency")}'
        }
    elif event_type == 'charge.updated':
        return {
            'success': True,
            'message': f'Charge updated: {event_data.get("status")}'
        }
    elif event_type == 'refund.completed':
        return {
            'success': True,
            'message': f'Refund completed: {event_data.get("amount")} {event_data.get("currency")}'
        }
    else:
        return {
            'success': False,
            'message': f'Unknown event type: {event_type}'
        }
