# ADR 0082: Memories and handoffs made on the Linux box reach shared memory through layered trust

**Status:** Proposed (2026-10-30, marvin#912). Gil's decision on the parity plan's `learning` question, verbatim:
"I think we should do layered trust like how we do with the review section. And also incorporate the review too into
that." Builds on ADR 0069 (the box is pull-only and the quarantine host), ADR 0064 (trust ramp) and the Safety reviews
on Health (CONTEXT.md).

## Context

Gil now talks to a full MARVIN at mac-mini-2012, so sessions there write memories and handoffs. The box's `~/.claude`
is a pull-only mirror (`code_sync.py mirror`): an edit to a tracked file is reset away on the next run (a patch is
kept in `~/.claude/backups/mirror/`), and a new file stays on the box. Nothing reaches the Macs. The box also runs
untrusted code, so whatever comes from it may have been written by an attacker: a planted memory is a standing
prompt injection into every later session on both Macs.

## Decision

1. **The Mini pulls; the box never pushes.** On the box, `lib/box_memory_export.py` turns changes in the shared memory
   folder and `handoffs/` into items and keeps them in an outbox outside the synced tree (`~/.claude/box-outbox/`),
   captured before the mirror resets them. The primary Mac runs `box_memory_export.py export` on the box over its
   existing ssh login and reads the JSON from stdout. No new credential, nothing writable from the box.
2. **Items are untrusted data.** `lib/box_memory_review.py` on the primary checks each item before anything else:
   known kind, a plain file name (no `/`, no `..`, `.md`), size caps (memory 64 KB, handoff 256 KB, bundle 4 MB, 200
   items), UTF-8 without control characters, and an id it recomputes from the content (a forged or altered item is
   refused). Ids already seen are ignored, so a replay does nothing. A refused item goes to the error log (Health).
   Nothing the box says about status or approval is read.
3. **Scanned twice.** The shared push-guard patterns (`config/push-guard/patterns.txt`: secrets, transcripts), a
   fixed list of instruction-shaped text (prompt injection, hidden Unicode), and the safety monitor's judge with a
   `box_memory` rubric. The judge fails closed here: no score means no auto-pass.
4. **Held items use the existing review.** Each held item is a `box_memory` entry in `~/.claude/quarantine.md`, so it
   shows as a card in Health ▸ Safety reviews with no new screen. Fine = apply it; Block = drop it; Fix it = drop it
   with Gil's note kept. The primary acts on the **tick in quarantine.md** (`box_memory_review.py settle`), a file
   that syncs only between the Macs, so the box can't write it. It never acts on a calibration label: the primary's
   `POST /safety/label` takes labels from any Tailscale host, the box included. The review's own processing step
   leaves a ticked `box_memory` entry for settle, which records the label afterwards, so Gil's reviews still tune the
   `box_memory` limit like every other loop.
5. **Layered trust.** A layer is kind × risk: new memory, edit, delete, handoff, handoff delete, MEMORY.md index line;
   high risk = a `feedback`/`user` memory. A layer auto-passes after N clean approvals in a row, counted in its own
   trust-ramp file (`trust_ramp.py` with a separate path). Defaults: handoff 3, index line 5, new memory 5 (high 10),
   edit 10, delete 20; edits and deletes of high-risk memories and handoff deletes never auto-pass. A flagged item, a
   Block, a Fix it or a revert resets the layer to 0. A flagged item or one that collides with a Mac's change never
   auto-passes. N and the never-list live in `config/box_memory_trust.json`, a core file.
6. **Every apply is logged and revertible.** `~/.claude/box-memory/audit.jsonl` keeps what each apply replaced.
   `box_memory_review.py revert <id>` puts it back if the file hasn't changed since, and resets the layer.
7. **Same memory changed on the box and a Mac:** the item carries the hash of the file it started from; if the Mac's
   file differs now, it is held, never auto-passed. Approving it writes the box's version; the Mac's is in the audit.

## Consequences

- What a box session learns reaches both Macs within a pull, and Gil reviews only what its layer hasn't earned.
- A compromised box can at most queue items: everything goes through checks, scans and a layer that resets on the first
  flag. It still can't write the Macs' memory; ADR 0069 holds unchanged.
- An edit made on the box disappears from the box at the next mirror run until it is approved and comes back.
- Triggers today: every `process_quarantine_reviews.py` run on the primary (session start, the 20:00 job) starts a
  pull in the background, and every answer settles at once. A box-side "something to pull" ping through the observer
  forced command is a follow-up.
