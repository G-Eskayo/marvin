"""Keep the bench's hidden task checks out of the repo's own test suite (marvin#645).

A task's check/ folder holds pytest files that test the code an agent writes during a bench run. bench.py copies
them into that run's workdir and runs them there (run_hidden_check). In this repo they import modules that only
exist in a finished workdir (`from lru_cache import LRUCache`), so the suite collecting them fails with
ModuleNotFoundError (the Python tests check on PR #1036). bench.py copies only check/*.py, so this file never
reaches a workdir and the hidden checks still run there.
"""
collect_ignore_glob = ["*/check/*"]
