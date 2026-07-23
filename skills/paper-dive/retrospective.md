# Paper Dive — Retrospective

## 2026-07-22 — Anthropic Fellows bibliography pipeline (build_bibliography.py)
**I:** Added a caution to `/paper-graph`'s SKILL.md entry: the blended SPECTER2 + nomic-embed
score can surface cross-domain false positives (semantically close, field-wrong) — flag anything
from a visibly different field than the seed for manual verification before citing.
**F:** Two candidate citations flagged for manual check after an OpenAlex-seeded run through the
shared traversal/scoring path — a CISPA technical report and a Nature Medicine DOI that looks like
a medicine-journal paper surfacing in an LLM-security citation graph, most likely an embedding
similarity false positive rather than a real connection.
