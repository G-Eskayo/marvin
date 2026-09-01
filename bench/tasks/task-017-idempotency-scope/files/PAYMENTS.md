# Payment Provider Webhook Documentation

## Idempotency Keys and Retry Semantics

### Key Rule

The provider uses `event['idempotency_key']` to prevent duplicate processing of retried webhooks.

If a webhook is retried (network failure, temporary outage, etc.), it will have the same
`idempotency_key` as the original attempt. Your service must recognize this and not
double-process.

### Important Clarification: Idempotency Scope per Event Type

**The same idempotency_key can legitimately appear multiple times in the webhook stream
for a single logical transaction, if the event type changes.**

Example transaction flow:
```
1. Event type: "charge.created"
   idempotency_key: "tx_12345"
   → Process charge, record idempotency_key "tx_12345"

2. Event type: "charge.updated"
   idempotency_key: "tx_12345"  (SAME KEY, DIFFERENT TYPE)
   → This is a NEW, legitimate event. Must be processed.
   → Do NOT skip because you saw idempotency_key "tx_12345" before.
```

### Correct Deduplication

Idempotency deduplication **must scope to the combination of event type AND key**:

```
dedup_key = (event['type'], event['idempotency_key'])
```

If you dedupe on `idempotency_key` alone, you will silently drop legitimate state-change
events like "charge.updated" and "refund.completed", breaking payment workflows.

### Why This Matters

The provider reuses idempotency keys across different event types to maintain semantic
coherence: all events related to one transaction share the same key. But the provider's
deduplication logic (and yours, if you want to avoid duplicates) is per-event-type, not
global.

