# Deep Modules

A deep module has a small, simple interface hiding real complexity — the caller doesn't need to
know how the work gets done, just what it needs to hand over and what comes back. A shallow
module's interface is nearly as complicated as its implementation, so it saves you nothing.

**Example of a deep module** — `select_candidates(candidates, top_k, relevance_floor)`. The
caller passes a flat list and two numbers and gets back a filtered, ranked list. Underneath:
cap logic, floor filtering, and a bypass rule for a special tag all happen — none of which the
caller needs to think about. The interface stayed the same size even as three separate rules
(cap, floor, bypass) accumulated inside it over successive TDD increments.

**Example of a shallow module** — a hypothetical `apply_cap(candidates, top_k)`,
`apply_floor(candidates, floor)`, and `apply_bypass(candidates)` as three separate public
functions the caller has to know to call in the right order. Same total logic, but now the
caller's code has to understand and orchestrate the internals — the complexity leaked out into
every call site instead of staying hidden behind one interface.

**Where to look for this during planning**: when a task has several related rules or steps, ask
whether they're actually one capability (deepen into one function/module) or genuinely separate
capabilities a caller would want independently (keep them separate). If every caller of A always
immediately calls B and C right after, they're probably one deep module wearing a shallow-module
disguise.
