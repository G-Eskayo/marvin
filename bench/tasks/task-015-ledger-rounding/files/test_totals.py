"""Test suite for invoice calculation refactoring."""
from decimal import Decimal
import invoice
import report


def test_invoice_calculation():
    """Test that invoice calculation is correct."""
    items = [
        (3, Decimal('10.004')),
        (1, Decimal('10.005')),
        (2, Decimal('10.003')),
    ]
    result = invoice.calculate_total(items)
    assert result == Decimal('60.02'), f"Expected 60.02, got {result}"


def test_invoice_and_report_use_shared_logic():
    """After refactoring, both should use pricing.py's canonical implementation.
    This verifies they both produce the correct result (60.02).
    """
    items = [
        (3, Decimal('10.004')),
        (1, Decimal('10.005')),
        (2, Decimal('10.003')),
    ]
    inv_result = invoice.calculate_total(items)
    rep_result = report.calculate_total(items)
    # Both must agree on the correct total
    assert inv_result == rep_result == Decimal('60.02'), \
        f"invoice={inv_result}, report={rep_result}, expected both 60.02"


if __name__ == '__main__':
    test_invoice_calculation()
    print("Invoice test passes")
    try:
        test_invoice_and_report_use_shared_logic()
        print("Refactored: invoice and report now agree on correct total!")
    except AssertionError as e:
        print(f"Not yet refactored: {e}")
