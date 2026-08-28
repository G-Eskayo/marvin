# 0028 — Formal semver, driven by existing issue labels, with an auto-generated changelog

## Status

Accepted (2026-08-28)

## Context

With merges happening autonomously through the integration pipeline in [[0026]]/[[0027]], "what
version is MARVIN on" needed an answer a human would recognize — Gil explicitly rejected a raw
commit SHA as the version identity. But autonomous merges mean nothing is present at merge time to
make a MAJOR/MINOR/PATCH judgment call the way a human release manager normally would.

Considered signals for the bump type: parsing conventional-commit-style prefixes from commit
messages (would require enforcing a new commit convention this repo doesn't have today), calendar
versioning (sidesteps the bump-type question entirely, but loses the "how big a change was this"
information semver conveys), or reusing labels already applied to every ticket that reaches merge
(`enhancement` already exists and is already applied; nothing conflicting exists for bugfixes or
breaking changes).

## Decision

A root-level `VERSION` file (semver) and `CHANGELOG.md`, both updated as part of the same
merge-time integration step [[0026]] already introduced. Bump type comes from the merged ticket's
existing labels: `enhancement` present → MINOR; absent → PATCH; a new `breaking-change` label
(created, not yet applied to anything) → MAJOR. Each changelog entry is generated from the
ticket's title and PR link — human-readable, not a raw diff or commit log dump.

## Consequences

- No new labeling convention to teach — reuses `enhancement` exactly as it's already used, and
  extends the same label-based coordination pattern this repo already relies on for
  `ready-for-agent`/`claimed:*`/`needs-triage` etc.
- A ticket mislabeled (missing `enhancement` when it should have it, or vice versa) silently
  produces the wrong bump type — there is no independent verification of label accuracy. Left as a
  known gap, not resolved here.
- `breaking-change` has to actually get applied by whoever files or triages a ticket that
  introduces one — nothing today detects a breaking change automatically. Under-labeling silently
  degrades a MAJOR bump to MINOR/PATCH.
- One combined MARVIN-wide version, not per-component (dashboard app, skills, libs don't get their
  own independent version numbers) — matches how tickets are actually scoped today, but means the
  dashboard's own `package.json` version and this VERSION file will need to be kept in sync or
  one deferred to the other; not resolved here.
