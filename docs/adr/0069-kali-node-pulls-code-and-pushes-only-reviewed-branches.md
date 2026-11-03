# 0069 — The Kali node pulls code, pushes only gated branches, and takes only tagged work

## Status

Accepted (2026-10-16)

## Context

mac-mini-2012 (Kali Linux, 2012 Intel Mac Mini) joins MARVIN as its third device and its first non-macOS one.
It has three roles on one box: a security/network-tools host, a quarantine sandbox for untrusted outside code,
and MARVIN's test environment, where bench and test numbers come from (CONTEXT.md, "Third node"). Splitting
the sandbox roles onto separate machines was considered and rejected, because one box for all three was the
original vision.

The roles conflict. The box runs untrusted code, and code sync ([[0021]]/[[0022]]) is two-way: whatever one
machine pushes to `main`, the others pull and run automatically. A quarantine escape that could push would put
its code on both Macs. Task dispatch ([[0013]]) also picks any online, idle device with no idea what each is
for, so registering the box as-is would send it research-colony runs and ticket builds it can't do. Finally,
`main` on G-Eskayo/marvin was not protected, so "PR only" held only by habit.

Alternatives considered: making the box pull-only with no push at all (rejected: it then can't work tickets);
an explicit `--target` on every dispatch call (rejected: hard-codes machines, breaks location transparency
[[0013]]); a whole-box snapshot rollback or containers for isolating runs (rejected: rollback hits concurrent
work, and containers share the kernel with untrusted tools).

## Decision

1. **Code sync on the box is pull-only.** It never auto-commits to `main` and never writes to `~/.claude`.
2. **Ticket and test work runs only in a disposable `marvin-test` VM** cloned from a frozen golden image.
   Untrusted code runs only in disposable `quarantine` VMs. The host is the trusted control layer.
3. **The push credential is handed in per run** by the dispatching Mac and dies with the VM. It is never
   stored on the box.
4. **`main` is protected (PRs only)** for every identity. The Macs' code sync keeps a bypass.
5. **PRs from the box go through [[0064]]'s trust ramp:** none auto-merge until 5 clean PRs have been approved.
6. **Dispatch routes by work tags.** Devices list the tags they accept, and untagged work counts as `general`,
   which only the Macs accept. When no accepting device is online the job fails loudly and never falls back
   to a Mac.

## Consequences

- The box can work tickets while a compromise there can't reach the Macs without passing PR review.
- The bypass needs the box to push as an identity that is *not* a repo admin. A token minted as Gil inherits
  the admin bypass, so the box needs its own GitHub identity (a machine-user account or a GitHub App).
- Changes made while sitting at the Kali box don't sync back. They're made from a Mac.
- Results (bench numbers, test results, scan findings) return through dispatch output, not git.
- Porting work is real: synced `settings.json` hard-codes `/Users/gileskayo`, Tailscale's path is hard-coded,
  and the CPU lacks AVX2, so prebuilt ML libraries such as ChromaDB may crash with `Illegal instruction`.
- Roughly 2 disposable VMs at a time with Whonix running (16GB RAM).

## Amendment (2026-10-30): test and bench work falls back to a Mac when the box stalls

Decided by Gil on G-Eskayo/marvin-instance PR #6 (`adr-0069-fallback`), after the box's calibration (marvin #623);
built in marvin #930.

Point 6's "fail loudly, never fall back" now has one exception, for **`test` and `bench` work only**:

- The work runs with a timeout of 3x its measured box time (#536's rule): 480 s for the full Python suite at `-n 8`
  (measured 158 s), 120 s for dashboard vitest (measured 35 s). The caller passes it as the dispatch timeout.
- On the box the run is wrapped in GNU `timeout`, so a stall is killed there (SIGTERM, then SIGKILL 15 s later) and
  nothing keeps running on the box.
- When the box times out, drops off mid-run (ssh exit 255) or isn't online and idle at dispatch, **the same command
  reruns once on the less busy Mac**: 1-minute load per core plus the runs already on that Mac (plan section F); a
  tie or an unreadable load goes to the Mini. A busy Mac is passed over for the other, but a fallback is never
  dropped because both are busy.
- A box run that finishes with failing tests is a result, not a stall: it stands, and nothing reruns.
- Every fallback is a line in `~/.claude/logs/dispatch-fallback.jsonl` (from, to, why, the Mac's load score, outcome).
- At most 2 fallback runs at once from one dispatcher. Over that cap the job fails loudly (`capped` in the log), so a
  box that stalls on everything can't pile its work onto the Macs.
- A caller can turn the fallback off (`--no-fallback`): an extra runner whose verdict comes from a Mac anyway.

**`security` and `quarantine` work keeps "fail loudly, never fall back".** A Mac must never run untrusted code. So
does every other tag. The allow-list is `FALLBACK_NEEDS` in `lib/task_dispatch.py`; adding a tag to it is an amendment
to this ADR.

## Amendment 2 (2026-10-30): ticket builds on the box, one at a time, each in a fresh VM

Approved by Gil on 2026-10-30; built in marvin #949 (#950 image, #951 dispatch, #952 trust). Points 2, 3, 5 and 6 made
concrete for ticket builds:

- **The image.** `marvin-build` is a frozen golden image made from `marvin-test` by
  `config/mac-mini-2012/build-builder-image.sh`, as the box's user (no sudo), so it lives in `runs/golden/`, not root's
  `golden/`. It holds the tools and the venv and no credential; the provisioning refuses to freeze one that does.
- **Who builds.** The Mac that runs the scheduler claims the ticket as `claimed:mac-mini-2012` and runs
  `lib/box_build.py`. It hands the box the bot's token and a Claude login (the plan's token; the API key only for a
  build beyond the box's plan slots, the `builder_auth.sh` rule) on ssh's stdin. The box clones a VM, the VM runs
  run_ticket's build half and pushes the branch and PR as the bot, and the VM is destroyed whatever happens. The Mac
  settles the outcome with run_ticket's settle half, as for any run. The box host never builds a ticket itself, and a box
  build never falls back to it.
- **What goes there.** A ticket goes to the box only when its project opted in (`"linux_ok": true` in its profile), the
  ticket is labelled `linux-ok`, nothing in its labels, title or body names a macOS thing (Swift, Xcode, launchd, the
  dashboard, ...), and the box's registry entry accepts the `box-build` tag. Otherwise it goes to the Macs as before.
- **One at a time.** `config/dispatch.json` `box_builds.slots` (0 or 1, enforced by `dispatch_concurrency`), and a lock
  on the box so two dispatchers can't both get in. The box refuses a build when the VM's memory plus `reserve_mb`
  isn't available or VM disk space is under `guards.min_disk_gb`; box test and trial work keep queuing as before.
- **Failure.** A refusal (busy, memory, disk, no image, token rejected) gives the claim back with no strike. A hang, a
  crash or the box dropping off is the box's failure, not the ticket's: no strike, a retry with backoff, and it feeds
  the failure breaker. Both rest the box lane for a while (`box-lane.json`) so a broken box can't fail every ticket.
  `vm_run.py sweep` removes any VM or disk a killed run left.
- **Trust.** Box PRs are labelled `from-box` (information only) and are authored by the bot, whose own trust ramp
  (ADR 0064, `trust_ramp.record_author`) keeps them waiting for Gil until 5 clean approvals.
