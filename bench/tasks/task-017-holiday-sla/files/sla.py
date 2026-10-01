"""SLA due date calculator."""
from datetime import datetime, timedelta


def add_business_days(start_date: datetime, num_days: int) -> datetime:
    """
    Add business days to a given date, skipping weekends.

    Args:
        start_date: Starting date
        num_days: Number of business days to add

    Returns:
        The resulting date after adding the specified business days
    """
    current_date = start_date
    days_added = 0

    while days_added < num_days:
        current_date += timedelta(days=1)
        # Skip weekends (Monday=0, Sunday=6)
        if current_date.weekday() < 5:  # Monday-Friday
            days_added += 1

    return current_date


def calculate_sla_due_date(ticket_created_at: datetime, sla_hours: int) -> datetime:
    """
    Calculate when an SLA is due.

    Args:
        ticket_created_at: When the ticket was created
        sla_hours: SLA duration in hours

    Returns:
        The due date
    """
    # Convert hours to business days (8 hours = 1 business day)
    business_days = sla_hours // 8

    return add_business_days(ticket_created_at, business_days)
