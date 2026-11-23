<!-- marvin:decisions-addressed -->

## Answering the decisions on deep answers

**deep-latency:** "Keep it" is carried out. The PR ships the holding line (8 s Siri-doorway wait) and Thread fallback for long deep answers, matching the already-built behavior—no additional code change needed. Evidence is the CLI/HTTP table in the PR description; no screenshot required since this is backend-only.

**deep-tools:** None of the three options was chosen. The note attached is a status report ("we are still working on that"), not a question—so there is nothing to answer here. The same three options remain live and unticked in the PR description whenever you're ready to decide.

One thing worth noting: `instance/docs/plans/dashboard-ux-potholes-2026-10-29.md` (#670, section S3) already scopes a "status sentence" feature—a human-language summary ("2 things need you; the Mini is low on disk") for voice/phone/header surfaces, as opposed to naming individual alerts by file. That's related to what your note describes ("not just telling me alerts by file name"), though this PR doesn't build it. It may be useful context as you work through the tool-scope question.

## Earlier answers to the same question (kept)

The five relation hits found by ticket #670 reference are all kept, with their reasons:

1. `instance/docs/plans/dashboard-ux-potholes-2026-10-29.md:487` — Scopes a different feature (status sentence), not a restatement. Keep.
2. `instance/docs/plans/marvin-business-plan-2026-10-25.md:53` — Risk narrative citing #670–675; different question. Keep.
3. `instance/docs/plans/marvin-website-2026-11-02.md:226` — Public roadmap table row; describes the feature for website copy, not the tool-scope/latency choice. Keep.
4. `~/.claude/projects/-Users-gileskayo/memory/project-homepod-appletv-spike.md` — Dependency/status note; different question. Keep.
5. `~/.claude/projects/-Users-gileskayo/memory/project-investor-demo-plan.md` — Milestone-scheduling line; different question. Keep.
