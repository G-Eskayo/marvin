# Refactor email lookup to reduce complexity

The email lookup function has high cyclomatic complexity and is hard to follow.

Extract nested conditionals into separate helper functions and simplify the main logic.

Verify: pytest tests/test_email_lookup.py -q
