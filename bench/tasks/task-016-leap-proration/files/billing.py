"""Annual plan proration calculation."""
from datetime import datetime


def calculate_refund(annual_cost: float, start_date: datetime, end_date: datetime) -> float:
    """
    Calculate refund for an annual plan downgrade.

    Args:
        annual_cost: Total annual subscription cost ($)
        start_date: Start of the subscription period
        end_date: End date (downgrade date)

    Returns:
        Refund amount for unused portion of the year
    """
    # Calculate days used (WRONG: uses actual calendar days instead of 30/360 convention)
    days_used = (end_date - start_date).days

    # Determine if this is a leap year
    year = start_date.year
    is_leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
    total_days = 366 if is_leap else 365

    unused_fraction = (total_days - days_used) / total_days
    refund = annual_cost * unused_fraction

    return round(refund, 2)
