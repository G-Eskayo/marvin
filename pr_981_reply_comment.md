## Decisions addressed

All four Decisions on PR #981 stand as built. No drift from the Decisions-comment commit (68f6f589, 2026-10-30 23:26):

- **routing-signal** ✓ `lib/box_build.py:201` checks `LINUX_LABEL not in _label_names(ticket)` — explicit, fails closed
- **order** ✓ box tried before the Macs (`ticket_pipeline._dispatch_one` / `box_build.routes()`)
- **vm-size** ✓ `config/dispatch.json` → `box_builds: {slots:1, memory_mb:6144, vcpus:6, timeout_s:9000, reserve_mb:3072}`
- **private-context** ✓ `marvin_launcher.py:88` — no memory, work-rules, or lexicon in a VM

### Note answer (two parts)

The Note attached to *private-context* asked: "should be using our default build ... and then configure it to whatever tools we need ... for whatever task/project it is."

1. **Per-project tool setup** — **already as built.** `lib/project_profile.py`'s `setup` field (`project_profile.py:140`, run by `Measurer._setup` at `project_profile.py:478/518-532`) is the existing generic per-project tool-setup mechanism. Both Mac and box runs call identical `execute_ticket(..., measurer, ...)` paths (`run_ticket.py:269-300`), so a box build gets identical per-project tooling with zero box-specific code. This reuses the existing pattern.

2. **The default build installer** — **not built yet.** Tracked by marvin#648 ("Default build step 6: installer --new/--join... and a clean-install test in a tart VM") — still open, not shipped. `builder/provision.sh` can't wire itself to an installer that doesn't exist yet. A follow-up issue filed: marvin#??? ("Wire the box's marvin-build provisioning to the default-build installer (#648)"), blocked-by #648, will wire `provision.sh` to the real installer once it ships.

### Commits since Decisions comment

Two merges in the range 68f6f589..b8521211 (2026-10-30 23:26 to 2026-11-03 17:41):
- `68f6f589` merge: stack-ticket/950 into stack-ticket/951
- `b8521211` merge: origin/ticket/950-box-builder-image into HEAD

Diff of `lib/box_build.py` and `config/dispatch.json`: **no change.** Only touched: `config/mac-mini-2012/{README.md,marvin-observer-feed.sh,marvin-observer.sh}` (marvin#954, unrelated).

### Screenshots

Not applicable — PR #981 has no UI surface.

<!-- marvin:decisions-addressed -->
