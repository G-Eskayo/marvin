from decimal import Decimal, ROUND_HALF_UP


def calculate_total(line_items):
    """Calculate report total by rounding each line item to 2 decimal places.

    Args:
        line_items: List of (qty, unit_price) tuples where prices are Decimal.

    Returns:
        Decimal: Sum of per-line-rounded values.
    """
    total = Decimal('0')
    for qty, unit_price in line_items:
        line_subtotal = (qty * unit_price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total += line_subtotal

    return total


# Example usage
if __name__ == '__main__':
    items = [
        (3, Decimal('10.004')),
        (1, Decimal('10.005')),
        (2, Decimal('10.003')),
    ]
    print(f"Report total: {calculate_total(items)}")
