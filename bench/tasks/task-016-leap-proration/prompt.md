**Issue:** A customer downgraded their annual plan mid-cycle on Feb 29 (leap year), and the refund calculated by our system is $0.38 off from what finance calculated manually.

**Details:**
- Customer started annual plan on Jan 1, 2024 for $100/year ($0.274 per day)
- On Feb 29, 2024, they downgraded to a lower tier
- Finance calculated the refund as $14.45 for the unused portion
- Our system calculated $14.07

**What to fix:**

Review `billing.py` and `BILLING.md` to understand the correct proration policy, then fix the refund calculation to match finance's number exactly.

The customer should receive the correct refund amount according to company billing policy.
