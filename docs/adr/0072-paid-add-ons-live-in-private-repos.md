# 0072 — Paid add-ons live in private repos; the engine stays free and public

## Status

Accepted (2026-10-25)

## Context

MARVIN's business model (Gil, 2026-10-25) follows VS Code: a free base download, the development and research
assistant with devices and voice, plus add-ons a person buys to configure their own MARVIN. Each add-on adds its own
tab and setup walkthrough. A public marketplace for other people's add-ons may follow later.

[[0071]] put add-ons inside the public engine, switched off by default. That cannot work for a paid add-on: anyone
can read the code or flip the setting. Four options were weighed:

- **Paid add-ons in private repos** (chosen): open core; purchase grants access; an existing store service takes the
  payment.
- **A signed licence checked offline**: the add-on stays in the public engine and MARVIN verifies a licence file.
  No server, but the check sits in public code and is trivially patched out.
- **Everything public, pay for service** (setup, updates, support): nothing to enforce, but few people pay.
- **Our own hosted marketplace with accounts**: most control, but a server we pay to run from day one, before
  there are customers.

## Decision

The engine stays free and public. Each paid add-on lives in its own private repo and never enters the engine.
Buying one gives the buyer access, and the installer pulls it into their instance. Payment goes through an existing
store service, so we run no servers. Free add-ons may still ship inside the engine, as [[0071]] says.

## Consequences

- Amends [[0071]]: "add-ons ship in the engine" now holds for free add-ons only.
- The engine needs one small, general add-on loader that turns any add-on (free or paid) into a tab plus a setup
  walkthrough. Every paid add-on reuses it.
- Add-ons that are already public (paper-dive, resume-tailor) are out in the open for good. Each either stays free or
  ships its future paid version from a private repo. Decided per add-on.
- Not resolved here: which store service, how access is granted (a GitHub invite or a key the installer uses), what
  happens when a subscription lapses, and the marketplace's revenue share. Prices live in the owner's private
  business plan, not in this repo.
- A buyer could still share the code once they have it. The defence is the updates and support that come with the
  purchase, not secrecy.
