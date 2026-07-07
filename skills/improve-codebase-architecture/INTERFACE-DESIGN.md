# Exploring Alternative Interfaces for a Deepened Module

Once a candidate is picked in the grilling loop, the interface for the deepened module isn't
fixed yet — walk through these questions with the user before settling on one.

**What's the smallest interface that still lets every current caller do what it needs?** Start
from zero and add only what's proven necessary by an actual caller's need, not by what the old
shallow modules happened to expose. A shallow module's existing method list is not a spec for the
deep module's interface — it's the thing being replaced.

**Where does configuration live?** A deep interface takes structural inputs (what the caller
actually varies between calls) and hides policy (constants, thresholds, internal sequencing) that
never varies per-call. If a proposed interface has more than two or three parameters, ask whether
some of them are actually policy that belongs behind the seam, not in front of it.

**What's the error/edge-case contract?** Walk through what happens when: the input is empty, a
downstream dependency fails, a precondition the old shallow modules silently assumed turns out to
be false in some caller's real usage. A deep module's interface should make these decisions once,
not push them back out to every caller to handle individually — that's exactly the leverage the
depth is supposed to buy.

**Is this actually one seam or two?** If the grilling conversation reveals that "the deepened
module" wants to do two genuinely independent things for different reasons, that's a sign to split
back into two deep modules rather than force one interface to serve two purposes — don't let
"we already decided to consolidate" override a real seam that shows up during design.

**Sketch the call site before finalizing.** Write out what calling code looks like with the
proposed interface, using a real scenario from the codebase, not a hypothetical one. If the call
site still needs to know internal details to use it correctly, the interface isn't deep yet —
keep iterating before committing.
