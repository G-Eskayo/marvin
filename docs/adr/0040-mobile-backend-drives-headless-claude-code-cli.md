# 0040 — The mobile backend drives the headless Claude Code CLI, not the Agent SDK library

## Status

Accepted (2026-10-05). Supersedes [[0001]]'s choice of library; keeps its core point
(documented interface, not the private `remote-control` protocol).

## Context

[[0001]] chose the Claude Agent SDK for the voice client's backend. MARVIN deliberately runs on
Gil's Claude subscription with no paid API key (see memory: low-cost experimentation). The Agent
SDK docs (checked 2026-10-05, code.claude.com/docs/en/agent-sdk/overview) state: "Unless
previously approved, Anthropic does not allow third party developers to offer claude.ai login or
rate limits for their products, including agents built on the Claude Agent SDK. Use the API key
authentication methods … instead." Aimed at products, but it puts SDK-on-subscription in a grey
zone.

The same page documents the alternative: run the CLI as a subprocess with `-p` and JSON output.
That is plain first-party use of Claude Code under Gil's own login — and it's how the ticket
pipeline already runs ([[0030]]).

Alternatives: Agent SDK + paid API key (clean, but breaks the no-paid-API stance); Agent SDK on
subscription login (grey zone); local model as primary brain (too weak — see [[0039]]).

## Decision

The mobile backend runs `claude -p` (streaming JSON output, session resume) on the Mac Mini under
Gil's own Claude Code login, and translates its stream into whatever the app speaks.

## Consequences

- No new cost, no terms ambiguity; reuses the pipeline's proven headless-dispatch setup.
- Skills, memory and `~/.claude` config load exactly as in a terminal session.
- Extra plumbing: the backend parses the CLI's JSON stream instead of calling a typed library,
  and is exposed to CLI output-format changes across Claude Code updates.
- [[0005]]'s confirm-before-execute guardrail must be implemented through the CLI's permission
  mechanisms (permission-prompt tool / hooks) rather than an SDK callback — design still open.
- Usage counts against Gil's normal plan limits, shared with the pipeline and interactive sessions.
