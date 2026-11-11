# 0085 — A local front desk hands briefs to paid tiers; every job runs on capability tiers

## Status

Accepted (2026-11-11), from the marvin#46 grill with Gil. Amends [[0044]].

## Context

MARVIN picks its models call site by call site: Opus for chats and pipeline builds, Sonnet and Haiku hard-coded in
about ten places, and Ollama in 44. ADR 0045 adds Apple's on-device models. Nothing ties these together, so a new
model means editing every call site, and no bench result can move work to a cheaper model. Gil plans to leave the
$100 Claude plan before 2027 for the $20 plan plus local models (marvin#594). That only works if the local models
take the conversation and the high-volume work, not just embeddings.

Alternatives considered:
- **Levels by job alone:** it binds work to vendors' model names.
- **A fixed job → model table:** simple, but frontier tokens are spent where a cheaper tier would pass.
- **The router guessing difficulty from a task's wording:** bench Runs 13 and 15 showed the keyword "lean" mode
  saved nothing on hard tasks.
- **Same context on every tier:** small models drown in a long preamble. The voice-ticket 13 crashes came while
  starting a `claude -p` call that carried the full work-rules preamble.

For where the front desk goes first, these were considered: the terminal (it risks Gil's daily throughput before
anything is measured) and both surfaces at once (twice the risk, the same learning).

## Decision

1. **Capability tiers** (frontier, workhorse, fast, local, on-device) are the unit. Each **job** (the launch kinds in
   `lib/marvin_launcher.py`) names its floor, its **default tier**, and a **tier layer set** for each tier it allows:
   fewer layers and more structure (steps, an example, a checked output format) lower down, and full context with
   loose instructions at frontier.
2. **Tier escalation:** a recorded failure moves the retry up one tier, never below the floor. A default tier moves
   down only on bench evidence, and together with its layer set.
3. **The front desk:** a local model Gil talks to first. It hands a **brief** (task, gathered context, acceptance
   check) to a paid tier when the job's floor is above local, when a local attempt has a recorded failure, or when
   Gil says "send this up". It never acts on code, a repo or GitHub itself.
4. **MARVIN Mobile's Thread is the front desk first.** Claude Code sessions ([[0044]]) open only on a hand-off. The
   terminal follows only after the **front-desk gate** (2 weeks: ≥90% clean hand-offs, <10% overrides, ≥30% fewer
   paid tokens per finished task). Clearing the gate is the first goal.
5. **Reinvested savings** may buy a higher frontier model for tasks, but only while the bench shows it meets edge
   cases and acceptance criteria measurably better. Otherwise the choice is reconsidered.

## Consequences

- One table (job × tier → model and layers) replaces the scattered model names. `config/models.json`
  capabilities are the natural place to hold it.
- The bench gains a new duty: a pass rate per job per tier, plus the gate's three numbers. Without those
  measurements, nothing moves.
- [[0044]] changes before Mobile is built: Thread messages go to the front desk, and the Session mapping applies
  only to hand-offs.
- Risk: a confident local answer that should have gone up. Mitigations: the job floors, the override, and the
  override rate in the gate.
- Open, pending the local-model review (`docs/research/local-models-review-2026-11-11.md`): which models fill
  the local and on-device tiers on 16 GB machines, and whether tuning them (LoRA on MARVIN's own data) beats
  picking better base models.
