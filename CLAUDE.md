# MARVIN (~/.agents) — Repo Instructions

## Agent skills

### Issue tracker

GitHub Issues on `G-Eskayo/marvin`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles, all real labels on this repo with default naming (no overrides).
See `docs/agents/triage-labels.md`.

### Decisions for the owner

A PR or ticket that needs the owner to choose something carries a Decisions section, never a question in prose.
See `docs/agents/decisions-format.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Codebase questions: grep first, graphify for structure

Measured on 30 real questions with known answers (`bench/retrieval_eval.py`, marvin#705, `bench/RESULTS.md`): grep put the answer in the top 5 for 67% of questions, `graphify query` 38%; on multi-hop questions grep 3 of 4, graphify 0 of 4.

Rules:
- For codebase questions, search with grep (`rg`) first.
- Use graphify for structure questions: who calls or imports X, what a module touches (`graphify path "<A>" "<B>"`, `graphify explain "<concept>"`). `graphify-out/GRAPH_REPORT.md` is for broad architecture review only.
- The graph rebuilds itself after commits, merges and rebases (`lib/graphify_freshness.py`, marvin#691); the Health card "Code graph is current" shows when it hasn't.
