Our payment webhook handler is dropping legitimate events and causing refunds to fail.
We suspect it's a deduplication bug.

**Background:** Payment providers retry webhooks to ensure delivery.
To prevent duplicate processing, we maintain a cache of recently-processed webhook IDs.

**Task:** Debug `webhook.py` and fix the deduplication logic.

The current implementation has an obvious flaw (easy to spot and fix), but there's a
subtler issue hidden in the provider documentation (`PAYMENTS.md`). Read the docs
carefully to understand the full scope of the deduplication rule.

All test cases in `test_webhook.py` must pass, including the provider's own event
sequences.
