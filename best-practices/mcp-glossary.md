---
name: mcp-glossary
description: Glossary of Model Context Protocol (MCP) terms: hosts, clients, servers, primitives, transports, auth and security. Read when working on or explaining an MCP server or client.
tags: [domain:mcp, intent:reference, type:glossary]
---

# MCP glossary

Moved out of `~/.claude/lexicon.md` on 2026-11-09 (owner's decision on marvin PR #1124): the lexicon is now pasted
into every session in full, and these are generic MCP terms, not words MARVIN and the owner coined. Read this file
when the task involves MCP.

- **MCP** — open protocol for connecting AI applications to external systems (tools, data, workflows). Anthropic-originated, now community-governed. Think USB-C for AI.
- **MCP host** — the AI application that manages everything: creates clients, enforces security, coordinates LLM. Examples: Claude Desktop, VS Code, Claude Code.
- **MCP client** — protocol-level component inside the host. One client = one dedicated connection to one server. Stateful session per server.
- **MCP server** — program that exposes capabilities (tools/resources/prompts) to clients. Can be local (stdio) or remote (HTTP). Focused, composable, isolated.
- **MCP primitive** — the typed building blocks of the protocol. Server-side: tools, resources, prompts. Client-side: sampling, elicitation, roots.
- **tool (MCP)** — model-controlled executable function. LLM decides when to call it. Schema-defined via JSON Schema. Requires `tools/list` discovery then `tools/call` execution.
- **resource (MCP)** — application-controlled read-only data source. URI-addressed (`file://`, `calendar://`, etc.). Supports direct URIs and parameterized templates. App decides how/when to include in context.
- **prompt (MCP)** — user-controlled reusable template. Requires explicit invocation (slash command, palette). Parameterized. Structures interactions with the LLM.
- **sampling** — client primitive: server asks the host LLM to generate a completion. Server stays model-independent. Human-in-the-loop by design — user sees and can approve/modify both request and response.
- **elicitation** — client primitive: server asks the user for structured input mid-operation. Schema-driven form (not free text). Used for confirmations, preferences, missing data.
- **roots** — client primitive: host tells server which filesystem directories are in scope. Advisory, not enforced. Prevents accidents, not malicious servers.
- **capability negotiation** — handshake at session init where client and server declare what they support. Determines which primitives and notifications are available for the session. Drives progressive enhancement.
- **lifecycle (MCP)** — initialize → initialized notification → active session → terminate. Stateful. Capability negotiation happens at initialize.
- **transport layer (MCP)** — communication mechanism between client and server. Two types: stdio (local, direct pipes, zero network overhead) and Streamable HTTP (remote, HTTP POST + optional SSE, OAuth auth).
- **data layer (MCP)** — JSON-RPC 2.0 based protocol for client-server message exchange. Defines lifecycle, primitives, notifications, utilities.
- **MCP notification** — fire-and-forget JSON-RPC message (no id field, no response expected). Used for real-time updates: `notifications/tools/list_changed`, `notifications/initialized`, etc.
- **MCP Tasks** — experimental extension for async/long-running operations. Server returns a task handle instead of blocking. Client polls `tasks/get`. States: working → input_required → completed/failed/cancelled. Crash-resilient via durable task IDs.
- **MCP Apps** — extension for interactive UI widgets rendered inline in chat (forms, pickers, dashboards). Extends servers beyond flat text responses.
- **confused deputy (MCP)** — attack on MCP proxy servers: malicious client exploits static client ID + consent cookies at third-party auth server to steal authorization codes without user consent. Mitigated by per-client consent stored server-side before any third-party redirect.
- **token passthrough (MCP)** — forbidden anti-pattern: MCP server accepting tokens not issued for itself and forwarding them downstream. Breaks audit trails, bypasses security controls, enables privilege escalation.
- **SEP (Spec Enhancement Proposal)** — formal process for proposing changes to the MCP specification. Community-governed.
- **agent skill (MCP context)** — portable instruction set that gives AI coding assistants domain knowledge. `mcp-server-dev` plugin provides `build-mcp-server`, `build-mcp-app`, `build-mcpb` skills for scaffolding MCP servers.
- **title (MCP)** — human-readable display name on tools, resources, prompts. Separate from `name` (the unique identifier used in protocol calls). Show `title` to users; use `name` in tool calls.
- **instructions (MCP)** — optional string in server's `InitializeResult`. Guidance the host can pass to the LLM about how to use this server.
- **MCP endpoint** — single HTTP URL supporting both POST (client→server) and GET (server→client SSE stream) in Streamable HTTP transport. E.g. `https://example.com/mcp`.
- **MCP-Session-Id** — HTTP header for session management in Streamable HTTP. Cryptographically random (UUID/JWT). Client includes on all requests after init. Format used for secure binding: `<user_id>:<session_id>`.
- **MCP-Protocol-Version** — HTTP header client MUST include on all subsequent HTTP requests after init. Value = negotiated protocol version (e.g. `2025-11-25`).
- **resources/subscribe** — client subscribes to change notifications for a specific resource URI. Server sends `notifications/message` when that resource changes.
- **completions capability** — server capability for argument autocompletion. Supports `completion/complete` requests on prompt arguments and resource template parameters. E.g., typing "Par" → suggests "Paris".
- **parameter completion** — prompts and resource templates support completing partial argument values. Enables slash-command argument suggestions.
- **PKCE (MCP auth)** — Proof Key for Code Exchange. REQUIRED for all MCP OAuth flows. MUST use S256 method. If AS doesn't advertise `code_challenge_methods_supported` → client MUST refuse to proceed.
- **resource indicator (MCP)** — RFC 8707 `resource` parameter in OAuth auth/token requests. Binds token to specific MCP server URI. Clients MUST include; servers MUST validate audience claim matches.
- **Client ID Metadata Documents** — preferred MCP OAuth registration mechanism. Client uses HTTPS URL as `client_id`; AS fetches that URL to get client metadata (name, redirect_uris). No prior relationship needed.
- **Protected Resource Metadata** — RFC 9728. MCP servers MUST implement to advertise their authorization server location. Served at `.well-known/oauth-protected-resource` or via `WWW-Authenticate` header on 401.
- **scope challenge** — WWW-Authenticate header with `error="insufficient_scope"` and `scope="..."`. Client responds with step-up authorization flow to get elevated token.
- **MCP endpoint (auth)** — MCP server acts as OAuth 2.1 resource server. Validates tokens for correct audience. MUST NOT accept tokens not issued for it. MUST NOT forward tokens to upstream APIs.
- **mcp-server-dev** — Claude plugin (`anthropics/claude-plugins-official`) providing `build-mcp-server`, `build-mcp-app`, `build-mcpb` skills. Entry point for scaffolding any MCP server.
- **MCPB (MCP Bundle)** — packaged local stdio server with its runtime bundled as a single `.mcpb` archive. Users install without needing Node/Python. For local-machine servers. (`build-mcpb` skill scaffolds these.)
- **Server Card** — upcoming MCP standard. `.well-known` URL exposing structured server metadata so browsers/crawlers/registries can discover capabilities without connecting. On roadmap.
- **MCP Registry** — official centralized metadata repository for public MCP servers, versioned and moderated. Reverse DNS naming (`io.github.user/server`). Stores metadata pointing to npm/PyPI/Docker packages. REST API for aggregators.
- **DNS rebinding (MCP)** — attack where malicious domain changes DNS to internal IP mid-request. MCP HTTP servers MUST validate `Origin` header (HTTP 403 if invalid). Servers SHOULD bind to localhost only.
- **logging (MCP)** — server capability to emit structured log messages to client via `notifications/message`. Eight RFC 5424 levels (debug through emergency). Client sets minimum level via `logging/setLevel`.
