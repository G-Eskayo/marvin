# Fix date format validation edge case

The date validator fails on valid ISO 8601 dates with timezone offsets.

Fix the regex pattern to accept dates with timezone designators like +05:00 or Z.

Verify: pytest tests/test_date_validator.py -q
