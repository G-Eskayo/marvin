# Logic/State-Machine Prototype

Goal: answer "does this state model actually hold together?" by pushing it through the cases
that are hard to reason about just by reading the code — not by building anything resembling a
real app.

## Shape

A single runnable script (terminal, REPL-style or scripted scenario runner — whichever fits the
question faster) that:

1. **Instantiates the state model directly** — the real state machine/data model code if it
   already exists, or a minimal stand-in if this is pre-implementation. Don't build a parallel
   mock model; if the point is checking the real logic, use the real logic.
2. **Drives it through named scenarios**, each one a sequence of transitions/events chosen
   specifically because they're the cases someone would worry about — concurrent transitions,
   out-of-order events, boundary values, the "what if this happens twice" cases. Name each
   scenario after the question it's answering, e.g. `scenario_double_cancel_after_ship()`, not
   `test1()`.
3. **Prints full state after every transition** — not a diff, not a summary, the whole relevant
   state — so it's immediately visible whether something drifted into an invalid or surprising
   shape.
4. **Flags invariant violations loudly** — if the model has invariants (e.g. "quantity never goes
   negative," "these two flags are mutually exclusive"), assert them after every transition and
   print a very visible failure, not a quiet log line, when one breaks.

## What NOT to build

No UI, no persistence, no error recovery beyond what's needed to keep the scenario runner going.
If a scenario reveals the model doesn't hold up, that's the answer — stop there, don't try to
patch around it inside the prototype.

## Example shape

```python
def scenario_cancel_during_fulfillment():
    order = Order.create(items=[...])
    order.transition("ship")
    order.transition("cancel")  # the case in question — what should happen here?
    print(order.state_snapshot())
    assert order.status in VALID_STATUSES, f"invalid status: {order.status}"

if __name__ == "__main__":
    for name, fn in [(n, f) for n, f in globals().items() if n.startswith("scenario_")]:
        print(f"\n=== {name} ===")
        fn()
```
