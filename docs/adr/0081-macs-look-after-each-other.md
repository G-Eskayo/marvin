# 0081 — The Macs look after each other: trigger-based peer care and a guarded nightly reset

## Status

Accepted (2026-10-30: the owner answered the Decisions on PR #769; being built in marvin#847). Design: [docs/design/763-macs-look-after-each-other.md](../design/763-macs-look-after-each-other.md).
Builds on #679's buddy-restart design (owner decisions of 2026-10-26: password in the keychain for `authrestart`; a
smart plug with a local API). Not accepted until the owner answers the Decisions on the design PR.

## Context

On 2026-10-29 the Mac mini hung. Its log shows 1,821 memory kills (`OS_REASON_JETSAM`) between 14:30:04 and 14:31:12,
then 83 minutes of silence, until the owner held the power button (`btn_rst`, 15:54). From outside it looked like
"off Tailscale and the LAN". Approvals failed (#762) and the overnight queue couldn't start. While checking, three more
problems turned up. The Mini is on Wi-Fi, not Ethernet. The LAN backup path's jump host, the 2012 mini, had been
offline for 22 hours unnoticed. And macOS 26 can unlock FileVault over SSH, so the unlock screen is not the dead end
the ticket assumed.

## Decision

1. **Every registered device is a watcher of every other.** No new watcher process per pair. A watcher acts only on a
   trigger, never a timer: a Tailscale peer change pushed on `tailscaled`'s IPN bus, a failure of real work (dispatch,
   SSH, merge, sync), the peer's boot-time "I'm back", or a stale peer heartbeat noticed at the end of an existing
   code-sync run.
2. **One probe, one pure `classify`.** It names the state as *service*, *network*, *locked*, *asleep*, *hung* or
   *unknown from here*. Each state has a short fix ladder: restart the service, restart Tailscale over the LAN,
   Wake-on-LAN, SSH unlock, smart-plug power cycle, or notify. An incident gets at most N attempts, and a lock per
   watched Mac stops two watchers acting at once. Waits are bounded inside an attempt, and there is no retry loop.
3. **Everything is logged through `job_events`** (job `peer-care-<peer>`), so it shows in the Activity tab with no
   new UI. "Needs you" notifications use ADR 0046's delivery path, with `mr_notification.notify_needs_you` as the
   fallback.
4. **Nightly reset, one Mac per slot, never both.** A calendar event starts it. A pure `may_reset` checks the owner's
   activity, helpers, merges, tests, live Seal Speak/Xcode work, and the peer's health. Work in progress re-triggers
   the check on its own exit, never with a kill. Owner activity is the one bounded re-check, because macOS has no
   "user went idle" event. A reset skips the night if the peer isn't healthy.
5. **Planned restarts use `fdesetup authrestart`.** It goes through one root-owned script that sudoers allows, which
   reads the password from a root-only System keychain item and pipes it to `-inputplist`. This is the recommended
   option; Decision `credential` chooses.
6. **After a restart, the peer verifies once**, on "I'm back" or after a 10-minute deadline. A failure enters the
   fix ladder.

## Consequences

- No new periodic job. The idle cost is one blocked IPN reader per Mac.
- Anything running as the owner can restart a Mac, but nothing can read the password (with option B of
  `credential`). The man page warns that `authrestart` keeps an unlock key in memory until the next boot.
- A watcher off the home LAN can only tell the owner: it can't wake, unlock or reach the LAN path. The always-home
  watcher (the 2012) matters, and it is down today.
- Remote unlock and WoL may depend on Ethernet; Apple doesn't document either over Wi-Fi.
- The reset does not prevent a mid-day memory hang like today's. That is the memory guard's job (separate ticket).

## Alternatives considered

- **A polling health loop**: rejected by the owner's no-polling rule (2026-10-26). It wakes when nothing changed and
  can run away itself.
- **Turn FileVault off on the Mini**: removes the unlock screen, but the owner chose to keep FileVault on
  (2026-10-26). Offered again as a Decision because remote unlock now changes the trade-off.
- **A password in the login keychain, read by a user-level script with `sudo -S`**: simpler, but any process running
  as the owner could read it.
