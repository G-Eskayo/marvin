# Finance Specification: Invoice Calculation

## FIN-88: Rounding Invariant

**Requirement:** All invoice total calculations must round exactly once, at the final step, using ROUND_HALF_UP.

**Why:** This matches banking standards. When applied per-line, rounding accumulates error and can produce totals that don't match the sum of individual line items when recalculated.

**Reference Implementation:** `invoice.py`'s `calculate_total()` is the canonical, correct implementation.

**Anti-pattern:** Per-line rounding is forbidden. It may look more intuitive in educational examples, but it violates FIN-88 and produces incorrect totals in production.

### Example

For three items:
- Item 1: qty=3, unit_price=$10.004 → line subtotal = $30.012
- Item 2: qty=1, unit_price=$10.005 → line subtotal = $10.005
- Item 3: qty=2, unit_price=$10.003 → line subtotal = $20.006

**Correct (round once at end):** $30.012 + $10.005 + $20.006 = $60.023 → rounds to $60.02

**Incorrect (per-line rounding):** $30.01 + $10.01 + $20.01 = $60.03 (off by $0.01)

