# The two Macs look after each other, plus a safe daily reset (marvin#763)

Status: design for review (2026-10-29). Draft ADR: [0081](../adr/0081-macs-look-after-each-other.md).
Nothing here is built yet. The Decisions are in the PR description.

## 1. What happened today, from the Mini's own logs

The ticket says the Mini "dropped off Tailscale and the home network". The logs say the Mini itself stopped, and the
network went with it. Read on the Mini after the restart, without changing anything:

| Time (MDT) | Evidence | Source |
|---|---|---|
| 10:19:55 | A boot. Fault `target_off_restart`, no button press. Cause not found. | `/Library/Logs/DiagnosticReports/ResetCounter-2026-10-29-102006.diag` |
| 10:20 → 14:07 | The aerial wallpaper extension wrote 2.1 GB in 3.8 h (the known disk filler). | `WallpaperAerialsExtension_2026-10-29-140746…diag` |
| 14:30:04 → 14:31:12 | **1,821 processes killed for memory (`OS_REASON_JETSAM`) in 68 seconds.** System daemons (sandboxd, GSSCred, biometrickitd, WirelessRadioManager…) were killed and relaunched about 40 times each. | unified log, `launchd` exit reasons |
| 14:31:12 | The log stops. Nothing is written for 83 minutes. | unified log |
| 15:54:33 | A boot. Fault `rst btn_rst,btn_seq_reset`: the power button was held. | `ResetCounter-2026-10-29-155433.diag` |

The machine: Mac16,10, 16 GiB RAM, 3 GB of swap, 14 GB free disk (94% full). Five helpers were running.

So today's failure was **a hang from memory exhaustion**, which looks exactly like "off the network" from outside. Three
more facts found while checking, each of which changes the design:

1. **The Mini is on Wi-Fi.** `en0` (Ethernet) is `inactive`; the default route is `en1` (Wi-Fi), 192.168.0.41.
2. **The backup path is dead.** `gils-mac-mini-lan` jumps through the 2012 Linux mini, and that machine has been offline
   for 22 hours (Tailscale: `offline, last seen 22h ago`; no ARP reply on 192.168.0.15). Nobody noticed.
3. **A FileVault screen can be unlocked over SSH.** `man fdesetup` (macOS 26.5.1), section *REMOTE UNLOCKING VIA SSH*:
   "when Remote Login is enabled, it is possible to perform password authentication using SSH even in this situation.
   This can be used to unlock the data volume remotely over the network." Apple's deployment guide confirms it is new
   in macOS 26 on Apple silicon [S1]. The ticket assumed the unlock screen can't be fixed remotely. It can, from a
   network that reaches the Mini before unlock, with the password. Whether that works over the Mini's **Wi-Fi** is not
   in Apple's docs: Apple says only "a network connection is available" [S1]. One third-party test says Wi-Fi works as
   of macOS 26.5 [S9]. Ethernet removes the doubt (Decision `ethernet`).

## 2. Which machines

| Machine | Registry id | Always home? | FileVault | Power settings (checked today) |
|---|---|---|---|---|
| M4 Mac mini | `mac-mini-1` | yes | on, `supportsauthrestart` true | `sleep 0`, `autorestart 1`, `womp 1`, `ttyskeepawake 1` |
| MacBook Pro (M1) | `macbook-pro-1` | no, leaves the house | on, `supportsauthrestart` true | `sleep 1` (held off by assertions), `womp 1` |
| 2012 Linux mini | `mac-mini-2012` | yes | none | offline since 2026-10-29 01:14 UTC |

"The two Macs" are the Mini and the MacBook. The MacBook can only do LAN things (wake, LAN SSH, unlock) when it is home.
The 2012 is the other always-home machine and was the Mini's buddy in #679. The design treats every registered
device as a possible watcher, so the 2012 joins when it's back, with no extra code. Whether it should is a Decision.

## 3. Noticing: what triggers a check

The owner's rule: no polling loops (memory `feedback-trigger-based-not-polling`). The design uses events that already
happen, and says plainly where an absence can only be seen on a clock.

| Trigger | What fires it | Latency | New cost |
|---|---|---|---|
| **Peer went offline** | `tailscaled` pushes peer changes on its IPN bus (`tailscale debug watch-ipn --peer-changes`, flag present in 1.104.2 on the Mini; a transition was not observed live today). One blocked reader per Mac, started by launchd `KeepAlive`. It wakes only when the tailnet changes. | about as fast as Tailscale's control plane marks the peer offline (not measured) | one idle process, ~0 CPU |
| **Real work failed** | a dispatch, an SSH call, a merge approval (#762), a sync push to the peer | immediate | none: a hook in the failure path that already exists |
| **I'm back** | the restarted Mac's boot (launchd `RunAtLoad` LaunchDaemon, so it runs before anyone logs in) | at boot | one message per boot |
| **Heartbeat missing** | the end of each existing code-sync run on the healthy Mac (every 30 min, already scheduled) compares the peer's last job heartbeat (`job_events`) with now | ≤ 30 min | one file read per existing run |

The heartbeat row is the only one that runs on a clock, and it adds no clock: a missing message can only be seen by
something that runs anyway. A wrong-side alarm costs one probe, so false positives are cheap.

## 4. Telling apart what is down

On any trigger the healthy Mac runs one **probe** (time-bounded, ~15 s worst case) and a pure function `classify(facts)`
names the state. "Same LAN" means both Macs see the same gateway MAC (`network_reachability.current_network_id`).

| Tailscale | LAN (same network only) | SSH with key | State | Confidence |
|---|---|---|---|---|
| up | – | works | **service**: check webhook `:7878`, launchd jobs, disk, sync | tested today (all readable) |
| down | answers | works over LAN | **network**: Tailscale only | path tested 10-26 |
| down | port 22 open | key refused, password offered | **locked**: at the FileVault screen | per `man fdesetup`; untested, needs one supervised restart |
| down | no ARP reply | – | **asleep or off or hung**: try a wake once, then decide | – |
| down | ARP answers, nothing else | – | **hung**: NIC alive, OS not (today, probably) | hypothesis |
| down | not on the same LAN | – | **unknown from here**: ask another watcher, else tell the owner | – |

## 5. Fixing, from the healthy Mac

Each state has a short ladder. **Every incident has a budget of 3 attempts** (a Decision); then the watcher stops and
tells the owner. One lock per watched Mac (`~/.agents/var/peer-care/<peer>.lock`) means two watchers never both act.
Every step goes to `job_events` as job `peer-care-<peer>`, so it shows in the Activity tab with no new UI.

- **service**: `launchctl kickstart -k gui/<uid>/<label>` for a dead MARVIN job, the existing `webhook_restart`
  logic for the merge server, and the disk ladder from memory `merge-failures-check-disk-and-main-first` (the aerial
  wallpaper videos first; never simulators or Xcode, which belong to live Seal Speak sessions).
- **network**: over the LAN path, `tailscale down && tailscale up --ssh=false` (no sudo needed with the Homebrew daemon,
  checked 10-26). If `tailscaled` itself is dead, that needs root: notify.
- **asleep**: send one Wake-on-LAN magic packet from the same LAN (`womp 1` on both Macs). The packet is a few lines of
  Python, no tool to install. Wait up to 2 minutes, probe once. `pmset(1)` documents `womp` as "wake on ethernet
  magic packet" [S3], and no Apple page says a magic packet wakes a Mac over Wi-Fi [S4]. So the wake is reliable only
  for a Mac on Ethernet. Today the Mini never sleeps (`sleep 0`) and the MacBook is on Wi-Fi, so this is mostly a
  best-effort step for the MacBook.
- **locked**: unlock over SSH with the stored password if the owner allows it (Decision `remote-unlock`), else notify
  "The Mac mini needs you: it's at the unlock screen".
- **hung**: nothing software can do. Power-cycle with the smart plug if there is one (Decision `smart-plug`), which
  then lands at the unlock screen, which is the **locked** case. Otherwise notify at once on every device.
- When the watched Mac stays down, the healthy one takes its queued work through the existing dispatch, and approvals
  fail over per #762.

Waits inside one attempt are bounded (at most 2 minutes, then the attempt ends). There is no retry loop: the next
attempt needs the next trigger.

Notification path: ADR 0046's single delivery path (MARVIN Mobile push, urgent bypass of quiet hours), with
`mr_notification.notify_needs_you` (desktop + `PushNotification`) as the fallback that works today.

## 6. The daily reset

### Why
Today's hang was memory, after a day of helpers. A restart a night clears leaked memory and swap. It does not stop a
single bad afternoon, so a memory guard is proposed alongside (Decision `memory-guard`). It is trigger-based too:
the system posts memory-pressure changes (`DISPATCH_SOURCE_TYPE_MEMORYPRESSURE`, levels normal / warn / critical [S7]),
and a helper launch is the other trigger.

### When
A launchd `StartCalendarInterval` at each Mac's slot: one event a night, not a poll. The slots never overlap. Before
starting, the resetting Mac probes its peer; **if the peer is not healthy, it skips the night**, so one Mac is always up.

### Guardrails, all checked right before the restart
A pure function `may_reset(facts) -> (verdict, reason)` over a snapshot. Every signal below was read on the Mini today
without root:

| Signal | How it's read | Today on the Mini |
|---|---|---|
| Owner at the keyboard | `CGEventSourceSecondsSinceLastEventType` [S5], Apple's documented API; `ioreg` `HIDIdleTime` gives the same number but is undocumented | 2,946 s idle (via `ioreg`) |
| Owner watching something | power assertions (`pmset -g assertions`: `PreventUserIdleDisplaySleep` from a player). Apple warns video produces no input events [S5] | none |
| Screen Sharing in use | `screensharingd` running, or an established TCP connection on port 5900 | no |
| SSH sessions in | established TCP connections on port 22 (excluding the watcher's own) | 1 (this session) |
| Helpers | WezTerm helper tabs (`wezterm cli list`, the `●` running mark from `helper_tab`), `claude -p` processes, dispatch-state `busy` | readable |
| Merge in flight | the merge server's in-flight lock (#762) | readable |
| Tests running | a test run's own lock or process | readable |
| Xcode / Seal Speak / simulators | `pgrep -x Xcode`, `xcrun simctl list devices booted` | none |
| Memory | `kern.memorystatus_vm_pressure_level` (1 = normal; mentioned only on Apple's forums) | level 1 |

What happens when one blocks:
- **A helper, merge or test is running:** wait for its exit. `helper-tab --on-exit`, the dispatch wrapper's `EXIT`
  trap and the merge lock release each re-run `may_reset`. Never a kill.
- **The owner is active:** there is no "owner went idle" event in macOS. So this is the one bounded re-check: every
  15 minutes until the postpone limit (Decision `postpone-limit`), then skip the night. At most a handful of checks
  per night, and only on nights the owner is up.
- **A few minutes before:** a notification with **Postpone** and **Skip tonight** (where it shows is a Decision).

### FileVault
A normal restart stops at the unlock screen and nothing runs, not even `tailscaled`. Planned restarts use
`fdesetup authrestart`, which per its man page "must be run as root and itself prompts for a password", accepts the
password on stdin with `-inputplist`, and "restarts the system, bypassing the initial unlock"; "upon successful
unlock, the unlock key will be removed", so it covers one restart only [S2]. The man page warns
that "FileVault protections are reduced during authenticated restarts": the unlock key is kept in memory until the
next boot uses it. How the restart gets root and the password is Decision `credential`. The recommended shape:

- a root-owned script, `/usr/local/libexec/marvin-authrestart` (`root:wheel 0755`), the only thing a sudoers rule
  allows without a password;
- it reads the password from a **System keychain** item only root can read, and pipes the plist straight into
  `fdesetup authrestart -inputplist`, never to disk (the man page asks for exactly this);
- it refuses unless `may_reset` passed in the last minute.

Anything running as the owner can then trigger a restart, but can never read the password.

### After the restart
The restarted Mac's boot event says "I'm back". The peer runs the same probe as section 4 and checks SSH, Tailscale,
the webhook and the launchd jobs. If no "I'm back" arrives within 10 minutes (one bounded deadline), the peer treats
it as down and section 5 starts.

## 7. Cost

| Piece | Time | Space |
|---|---|---|
| IPN bus reader | O(1) per tailnet change; idle otherwise | one process, a few MB |
| Probe + classify | O(1) per trigger, ≤ ~15 s wall clock | none |
| Fix ladder | ≤ 3 attempts per incident, each bounded | one `job_events` file per peer (20 runs kept) |
| Reset guard | O(1) per check; ≤ (postpone limit / 15 min) checks on a late night | one state file per Mac |
| Heartbeat check | one file read per existing 30-min sync run | none |

No new periodic job.

## 8. Tests (for the build, written first)

Each one tries to break it (memory `feedback-tests-try-to-break-it`).

- `classify` over every row of the table, plus: probe timeouts mid-way, a stale LAN address (DHCP moved the Mini),
  the watcher on a different network, clock skew between the Macs.
- The fix ladder: the attempt budget holds across two triggers arriving together; the lock stops two watchers; a fix
  that "succeeds" but the probe still fails counts as a failure.
- `may_reset`: owner active → wait; helper running → wait, then the helper's exit re-runs it and it goes ahead; peer
  down → skip; Postpone past the limit → skip; a merge lock left behind by a crash doesn't block forever.
- The credential script: refuses without a fresh `may_reset`; the password never appears in argv, env or a file
  (checked with a fake `fdesetup`).
- Live, with the owner present (acceptance): stop the webhook on one Mac → the other restarts it; `tailscale down` on
  the Mini → the MacBook brings it back over the LAN; MacBook asleep on the home LAN → woken; one supervised
  `authrestart` → back up with nobody typing; one supervised restart to the unlock screen → the remote unlock.

## 9. Order of work (each a small ticket with its own PR)

1. `classify` + probe, and the heartbeat check at the end of code-sync.
2. The IPN bus reader and the "real work failed" hook.
3. The fix ladder with the budget, lock and `job_events` logging; notifications.
4. `may_reset` and the exit-triggered re-checks.
5. The credential script (needs the owner at the Mini once, to install it with sudo).
6. The reset itself and the after-restart check.
7. Remote unlock, if allowed.

Independent of all of it, and probably worth more than any of it for today's failure: Ethernet for the Mini, the
2012 back online, and the memory guard.

## What I could not test, and why

- A peer-offline event on the IPN bus: it needs a peer to go offline; nothing was taken down.
- Wake-on-LAN over Wi-Fi, the remote FileVault unlock, `authrestart`: each needs a sleep or a restart, which this
  session must not do.
- Whether SSH answered during today's hang: no watcher was recording.
- The 10:19 boot's cause: no panic report; `target_off_restart` alone doesn't say.

## Sources

- [S1] Apple Platform Deployment, *Intro to FileVault*: "On a Mac with Apple silicon and with macOS 26 or later,
  FileVault can be unlocked over ssh after a restart if Remote Login is turned on and a network connection is
  available." https://support.apple.com/guide/deployment/intro-to-filevault-dep82064ec40/web. The same sentence is in
  Apple Platform Security, *Managing FileVault*: https://support.apple.com/guide/security/managing-filevault-sec8447f5049/web
- [S2] `fdesetup(8)`, macOS 26.5.1: `authrestart`, `-inputplist`, `supportsauthrestart`, *REMOTE UNLOCKING VIA SSH*.
  Read locally with `man fdesetup`.
- [S3] `pmset(1)`, macOS 26.5.1: `womp`, `autorestart`, `ttyskeepawake`, `-g assertions`, `-g log`.
- [S4] Apple Support, *Share your Mac's resources when it's in sleep*:
  https://support.apple.com/guide/mac-help/share-your-mac-resources-when-its-in-sleep-mh27905/mac. It doesn't say
  whether magic packets work over Wi-Fi.
- [S5] `CGEventSourceSecondsSinceLastEventType`:
  https://developer.apple.com/documentation/coregraphics/cgeventsource/secondssincelasteventtype(_:eventtype:), and
  the forum advice to check power assertions as well: https://developer.apple.com/forums/thread/25509
- [S6] Notification actions (Postpone, Skip): https://developer.apple.com/documentation/usernotifications/unnotificationcategory
- [S7] Memory pressure events: https://developer.apple.com/documentation/dispatch/dispatch_source_type_memorypressure
- [S8] Automatic login isn't available with FileVault on: https://support.apple.com/en-us/102316. So a power-loss
  restart (`autorestart 1`) stops at the unlock screen. Apple doesn't say this in one sentence; it follows from S3 and S8.
- [S9] Third party, not Apple: Jeff Geerling, remote FileVault unlock over SSH in macOS 26, "As of macOS 26.5, I was
  able to unlock the Mini over WiFi as well":
  https://www.jeffgeerling.com/blog/2025/you-can-finally-manage-macs-filevault-remotely-tahoe/
- Tailscale 1.104.2 CLI: `tailscale debug watch-ipn --help` lists `--peer-changes`. The bus connected on the Mini
  today (it printed `Connected.` and the state).
