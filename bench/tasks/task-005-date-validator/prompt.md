The function `validate_date` in validator.py has a bug: it incorrectly accepts dates like `2024-02-31` (Feb 31 doesn't exist) and `2024-04-31` (Apr has 30 days) as valid.

Fix the function so it correctly validates calendar dates. Keep the same signature and return type.

Then briefly state what was wrong and what you changed.
