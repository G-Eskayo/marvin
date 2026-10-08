# 0043 — Mobile backend admits only Gil's iPhone (Tailscale whois) and gates side effects behind Face ID

## Status

Accepted (2026-10-05). Extends [[0005]].

## Context

The mobile backend ([[0042]]) can trigger real side effects on the Mac Mini — merging/denying PRs,
and (via [[0005]]) approving Claude Code tool calls from Chat/Voice. Binding to the Tailscale
address keeps the public internet out, but any device on the tailnet (the laptop today, anything
added later) could still reach it, and an unlocked phone in someone else's hands could too.

Alternatives: Tailscale reachability alone (any tailnet device = full control); an app-level
password/token (more friction and secret management, little gain over biometrics).

## Decision

1. Every request is attributed with Tailscale's peer identity (`tailscale whois`); only an
   explicit allowlist — initially just Gil's iPhone 17 Pro node — is admitted. Default deny.
2. Read-only actions need nothing further. Any side-effecting action requires a fresh Face ID
   (LocalAuthentication) confirmation on the phone before the request is sent; [[0005]]'s
   confirm step becomes "confirm + Face ID".

## Consequences

- No passwords or tokens to store, rotate or leak; identity comes from Tailscale's node keys.
- New devices (e.g. an iPad) need a deliberate allowlist edit.
- Face ID is a client-side gate; the backend trusts the allowlisted device to have enforced it.
  Acceptable for a single-user app; a signed per-action assertion could harden it later.
- Voice-only, hands-busy moments (driving) still need a glance/tap for side effects — accepted.

## Amendment (2026-10-08): Gil's two Macs are allowlisted for development

Gil chose to allowlist the MacBook (`c02f52gpq05ps-macbook-pro`) and the Mac Mini
(`gils-mac-mini`) alongside the iPhone (`iphone181`), so the iOS simulator on either Mac can
use the real backend while the app is being built and inspected. This deliberately relaxes the
"laptop can't control MARVIN by accident" goal of user story 2 in PRD G-Eskayo/marvin#152.

- Low added risk: both Macs already hold full local control of MARVIN (shell, `claude`, `gh`).
  Allowlisting them adds the backend as one more way in, not new powers.
- The simulator has no Face ID, so side effects from it rely on simulated biometrics. That is
  acceptable on Gil's own machines and only there.
- Repeatable ticket screenshots don't depend on this. The app's `-demo` launch mode uses a
  built-in fake backend, so screenshots need no allowlisting.
- Revisit before the app is used day-to-day: drop the Macs from the allowlist if the
  accidental-control risk starts to matter.
