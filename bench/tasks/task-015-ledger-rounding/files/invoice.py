from decimal import Decimal, ROUND_HALF_UP


def calculate_total(line_items):
    """Calculate invoice total with proper rounding per FIN-88.

    Args:
        line_items: List of (qty, unit_price) tuples where prices are Decimal.

    Returns:
        Decimal: Total rounded once at the end using ROUND_HALF_UP.
    """
    total = Decimal('0')
    for qty, unit_price in line_items:
        total += qty * unit_price

    # Round once, at the end, using ROUND_HALF_UP per FIN-88
    return total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


# Example usage
if __name__ == '__main__':
    items = [
        (3, Decimal('10.004')),
        (1, Decimal('10.005')),
        (2, Decimal('10.003')),
    ]
    print(f"Invoice total: {calculate_total(items)}")
