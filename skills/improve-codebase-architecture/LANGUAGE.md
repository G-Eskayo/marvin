# Architecture Language — Full Reference

The vocabulary this skill uses in every suggestion. Consistency is the point — don't drift into
"component," "service," "API," or "boundary" once these terms apply.

## Core terms

- **Module** — anything with an interface and an implementation: a function, a class, a package,
  a vertical slice. Size doesn't matter; the interface/implementation split does.
- **Interface** — everything a caller must know to use the module correctly: types, invariants,
  error modes, ordering requirements, configuration. Not just the type signature — a function
  that requires calls in a specific order, or that silently assumes a precondition, has a bigger
  real interface than its signature suggests.
- **Implementation** — the code inside the module that the interface hides.
- **Depth** — leverage at the interface: how much behavior sits behind how small a surface.
  **Deep** = a small interface hiding a lot of well-organized complexity. **Shallow** = the
  interface is nearly as complicated as just doing the work yourself.
- **Seam** — a place in the code where behavior can be swapped without editing in place — where
  an interface actually lives. Not the same as "the file boundary" or "the module boundary";
  a seam is specifically where substitution becomes possible.
- **Adapter** — a concrete implementation satisfying an interface at a seam.
- **Leverage** — what a *caller* gets from depth: less to know, less to get wrong.
- **Locality** — what a *maintainer* gets from depth: a change, a bug, or a piece of domain
  knowledge stays concentrated in one place instead of spreading across call sites.

## Principles

- **Deletion test**: imagine deleting the module and inlining its one caller's use of it. If the
  complexity vanishes, it was a pure pass-through — no real leverage, just indirection. If the
  complexity reappears (because two or more callers now each have to reimplement it), it was
  earning its keep.
- **The interface is the test surface.** Tests should exercise the interface, not the
  implementation behind it (see `tdd/tests.md` for the same principle from the testing side).
- **One adapter is a hypothetical seam; two adapters is a real one.** Don't introduce an
  interface/adapter split speculatively for a capability that has exactly one implementation and
  no concrete second one in sight — that's premature abstraction wearing architecture language.
- **Shallow modules accumulate at boundaries under time pressure.** A rushed extraction ("pull
  this into its own function for testability") without also giving it real behavioral leverage
  produces exactly this: a pure function that's easy to unit-test in isolation, while the actual
  bugs live in how callers sequence and combine several such functions — no locality, because the
  domain knowledge of "how these pieces fit together" never got a home.
- **Depth is not size.** A one-line function can be deep (hides a subtle invariant or a tricky
  edge case behind a trivial-looking call) and a five-hundred-line class can be shallow (every
  method is a thin, order-dependent wrapper the caller has to understand anyway).
