---
name: security-sweep
description: Source-level security review of a repository or a diff, in one pass. Finds missing and bypassable controls as well as dangerous calls. Use for "security review", "audit this", "is this safe", before shipping a network-facing service.
---

# Security sweep

Most review methods walk from input to dangerous call. That finds injection and misses the bugs where nothing dangerous is called, because a check is absent, skippable or weaker on one route than another. This sweep walks the controls too. Read code, don't run it.

A finding needs an actor, what they do, and what they gain that the system meant to deny. If you can't name all three, it's a note, not a finding.

Report what you can show. Don't drop a finding because it's unlikely, inconvenient or merely a likely mistake in a config you can't see: mark it `needs_validation` and say what fact would settle it.

## 1. Map before judging

Read the README and any stated security model, then every entry point. Write this table for yourself before hunting, one row per route, handler, job, consumer or CLI command that takes outside input:

`entry | who can reach it | identity check | ownership or tenant check | input it trusts | state it changes`

An empty cell is a lead. Note what the system promises (tenants isolated, only admins can X, payments are final). Each promise is a thing to break.

## 2. Control sweep (absence and bypass)

**Compare peers.** Line up routes that do similar work: read vs list vs export vs search vs update vs delete, v1 vs v2, UI vs API vs batch vs webhook. If one has a check and its sibling doesn't, that's a finding.

**Run the sad paths on every check.** For each `if` guarding security, ask what happens when the value is absent, empty, null, zero, negative, huge, the wrong type, duplicated, or in a different case or encoding. Look hard at checks nested inside "if present". A check that only runs when the attacker supplies its input is no check. Also look at what happens on the error path: does a thrown exception, a timeout or a missing config fall through to allow?

**Follow each credential.** For every token, signature, session, API key, invite, reset or share link:
- Where is it made? Is the randomness from a secure source, and is the seed or input guessable?
- Where is it checked? On every path, against a pinned algorithm and key, in constant time?
- What is it bound to: user, tenant, action, resource, expiry? Can it be reused after use, logout, or a password or role change?
- What is the secret if the setting is unset? An empty or default signing key is a finding when the code accepts it.

**Check who owns the object.** For each ID that arrives from a client, find the line that proves the caller may touch that object. Don't accept a check on the parent if the child is fetched separately. Follow IDs across files.

**Check which fields a client can set.** Look for raw bodies passed to updates, and for allowlists that include role, owner, tenant, price, status or balance. Check server-owned values taken from the client: price, amount, user ID, role.

**Check shared state.** Anything kept across requests (caches, memo tables, globals, queues, file names, temp paths) must include identity in its key. Ask whether one user's response can reach another.

**Check sequence and timing.** Can steps be skipped, repeated or reordered? Is a check separated from its action, so that two parallel requests both pass (double spend, double redeem, over-limit)? Is an operation that should run once protected against replay? Do counts, money and quotas survive negative, zero, rounding and overflow?

**Check what's left after an exit.** After revocation, deletion, removal from a team or downgrade, is access really gone from sessions, tokens, shares, caches and exports?

## 3. Sink trace

Trace outside input to each dangerous operation: SQL and NoSQL, shell, file paths, archive extraction, deserialization, templates, HTML output, redirects, outbound requests, XML, regex built from input, eval and dynamic imports, and prompts to models that can take actions. Include second-order flows, where a value is stored safely and used unsafely later, including by an admin view or background job. Outbound requests need the host checked after redirects and DNS.

Check for secrets in source and for sensitive data in logs and responses, including fields returned by accident, verbose errors and timing or message differences that matter.

## 4. Join the dots

Take low findings together. Does a read bug feed a credential? Does a self-service field reach an admin view? Does an unauthenticated route reach a helper that assumes auth? Report a chain as its own finding if it raises the impact.

## 5. Confirm each candidate

Re-open the source for each candidate and try to find what stops it, looking in middleware, framework defaults, callers, and the database schema.

- `confirmed`: you traced input to effect and found no control.
- `needs_validation`: it depends on a fact outside the repo. Name the fact.
- `rejected`: only if you can cite the file and line that stops it, and that control holds on this path. "Unlikely", "looks fine" or "probably intentional" is not a reason. A control that exists elsewhere doesn't count.

When in doubt, keep it as `needs_validation`. A wrongly dropped real bug costs more here than one extra line in a report.

Things that aren't findings: a missing hardening header or flag with no reachable effect, an actor affecting only themselves, code that's dangerous-looking but given only fixed or validated values, weak hashes used for non-security purposes such as cache keys, and anything needing a privilege that already grants the same result.

## 6. Report

Print every `confirmed` and `needs_validation` item, most severe first:

```
### <title>
file:line | status | severity (confirmed only: critical, high, medium, low)
Actor and action: ...
Why nothing stops it: <the trace, with file:line for each hop>
Fix: <the smallest change, at the last trusted decision point>
```

Severity follows what you showed. Critical: an outside actor gets code execution, the data store or any account. High: an explicit control is fully defeated. Medium: a real boundary break with a narrow reach. Low: a small disclosure.

Then list `rejected` candidates in one line each with the line that stops them, and any part of the code you did not get to. Don't claim coverage you didn't do.

---
Method adapted from Cloudflare's security-audit skill (MIT, © 2025-2026 Cloudflare, Inc.): the control-led hunting, sad-path checks, credential binding and the confirmed / needs_validation split.
