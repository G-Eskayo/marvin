def validate_date(date_str):
    """Return True if date_str is a valid date in YYYY-MM-DD format."""
    try:
        parts = date_str.split('-')
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        return month <= 12 and day <= 31
    except Exception:
        return False
