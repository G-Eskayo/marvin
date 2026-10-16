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
