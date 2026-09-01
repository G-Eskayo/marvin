The finance team has identified code duplication in our invoice calculation logic.
Three files independently implement the same calculation: `qty × unit_price` total.

**Problem:** The same logic appears in `pricing.py`, `invoice.py`, and `report.py`.
When changes are needed (e.g., to the tax formula or rounding), they must be synced
manually across all three files, creating maintenance debt and bugs.

**Task:** Extract the duplicated calculation into a single shared function in `pricing.py`.
Update `invoice.py` and `report.py` to import and reuse this function instead of
duplicating the code.

All existing tests must pass, and the extracted function must work correctly for
both modules' use cases.

See `SPEC.md` for the finance invariants that apply to this calculation.
