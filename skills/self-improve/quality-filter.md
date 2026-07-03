# Quality Filter

A new or updated skill must pass all three gates. If any gate fails, write a one-line note on why and stop — don't codify it.

## Recurrence gate

Will this come up again, in a *different* context — not just a repeat of the exact same task?

- Pass: "any time a script shells out to `claude` from a launchd cron, PATH won't include the interactive shell's additions" — a class of situation, not one script.
- Fail: "this one config file needed a specific value today" — true once, not a pattern.

## Evidence gate

Is the approach grounded in something that actually happened — a real failure, a real fix, a real measurement — not just a plausible-sounding idea?

- Pass: traced to a specific bug, a specific fix that was verified to work, or a benchmark result.
- Fail: "this seems like it would probably help" with no instance of it actually mattering yet.

## Value gate

Does codifying this meaningfully change an outcome next time, or is it something any competent pass would naturally get right anyway?

- Pass: a non-obvious gotcha that cost real time to find (e.g. a linking quirk, a silent failure mode, a naming collision).
- Fail: restating a well-known best practice with no MARVIN-specific twist.

## When a gate fails

State which gate failed and why in one line. That's a valid, complete outcome — not every observation needs to become a skill. A background reviewer with nothing to say after checking is doing its job correctly, not failing at it.
