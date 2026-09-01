"""Pytest configuration for bench/tasks directory.

Prevents task fixture test files (starting states) from being collected
as real repo tests. Task fixtures are intentionally broken until fixed by
an agent in an isolated sandbox, not the repo tree.
"""

collect_ignore_glob = [
    "task-015-ledger-rounding/files/*",
    "task-016-frame-protocol/files/*",
    "task-017-idempotency-scope/files/*",
]
