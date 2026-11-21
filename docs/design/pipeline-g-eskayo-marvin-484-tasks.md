1. Add `correlated: list[dict] | None = None` parameter to `research_digest.generate()`; when not `None`, use it directly and skip the `load_correlated_from_chroma()` call (`skills/research-colony/scripts/research_digest.py:99-113`).
2. In `skills/research-colony/scripts/run_colony.py:36`, change `out = research_digest.generate()` to `out = research_digest.generate(correlated=correlated)`.
3. Leave `research_digest.py`'s `if __name__ == "__main__":` block (lines 174-177) unchanged — it calls `generate()` with no argument, preserving the standalone ChromaDB fallback.
4. Add tests 1–6 above to `skills/research-colony/scripts/tests/test_run_colony.py`.
5. Fix the two existing tests (`test_returns_1_when_digest_not_written`, `test_returns_0_when_digest_written`) whose zero-arg `research_digest.generate` mocks are broken by the new call-site kwarg.
6. Run the full `skills/research-colony/scripts/tests/` suite and confirm all tests (old and new) pass.