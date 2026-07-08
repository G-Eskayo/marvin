# n8n platform research

Deep-research pass done 2026-07-08 to evaluate n8n for personal/job automation (SnorkelAI-era job
search automation, email/recruiter outreach) and as possible architectural inspiration for
MARVIN's own orchestration layer. Two sources: n8n's own MCP tool server (`synta-mcp` — node
search, best-practices, AI-agent architecture patterns, live-instance build/test/deploy) for
functionality/patterns, and a general research pass for everything that tool doesn't cover
(licensing, versions, self-hosting, debugging, case studies). Source tier tagged per claim below:
**[Official]** n8n's own docs/GitHub, **[Community]** forum/blogs/YouTube, **[Low-confidence]**
unverified.

## 1. What it is, architecturally

Node-based workflow automation: trigger nodes (webhook/schedule/chat) start a directed graph,
regular nodes do work, data flows as JSON item arrays, Code nodes available but discouraged as a
default (see best-practices below). **[Official + Community]**

Stack **[Community, corroborated across independent deep-dives]**: TypeScript, pnpm monorepo,
Turbo build. Vue.js editor + Pinia. Express API → service layer → TypeORM. Internal event bus
decouples subsystems. Same codebase powers self-hosted and n8n Cloud.

**Two execution modes** — the key architectural fork **[Official + Community]**:
- **Regular/main mode**: single process runs UI+API+triggers+executions. Fine for personal/single-user.
- **Queue mode**: main process is UI/API only, jobs queue into Redis, separate worker processes
  execute. Needs Postgres (not SQLite). Gives horizontal scaling + execution persistence.

**vs alternatives** **[Community, directional]**: Zapier = cloud-only, no-code, task-priced,
broadest catalog, easiest onboarding. Make = between Zapier and n8n, still SaaS-only. Airflow =
different category entirely — code-first Python DAG engine for engineered data pipelines, no
visual builder; n8n is for app/glue/AI automation, not a substitute for heavy ETL.

**Relevance to MARVIN**: the architecture worth borrowing is the event-bus decoupling, the
queue/worker separation, and the visual separation of "agent logic" from sub-nodes (model, memory,
tools) — n8n's hierarchical AI-agent node system is built natively on LangChain.

## 2. Licensing — most important to get exactly right

**Sustainable Use License (SUL)** — "fair-code," source-available, NOT OSI open-source.
**[Official — n8n docs + LICENSE.md]**. Three conditions: (1) internal business or
non-commercial/personal use only, (2) may redistribute only free-of-charge for non-commercial
purposes, (3) can't strip license/copyright notices.

**Explicitly fine, no license needed** **[Official]**: self-hosting for personal use; self-hosting
for a company's own internal operations; building custom nodes for your own use; consulting/support
services building workflows *for* clients.

**Needs a commercial agreement** **[Official]**: hosting n8n as a paid service to third parties,
white-labeling it, exposing the n8n interface itself as your product, multi-tenant SaaS collecting
end-users' credentials. Contact `license@n8n.io` if this ever applies.

**Bottom line**: personal automation and internal job-search/email automation are unambiguously
free and license-clean. Separate paid Enterprise tier exists for SSO/RBAC/environments/external
secrets — irrelevant for a personal instance.

## 3. Versions

Current (as of this research): stable **2.29.7**, pre-release **2.30.0** — on the 2.x line, 2.0
was a hardening/legacy-removal major. **[Official — GitHub releases]**. Release cadence is fast,
effectively weekly across stable+pre-release — pin a version in Docker, don't chase `:latest`.

**2.0 breaking changes** **[Official]**: Code nodes now run isolated, `process.env` access blocked
by default; MySQL/MariaDB support removed (migrate to Postgres/SQLite *before* upgrading, legacy
SQLite driver also removed); binary data no longer defaults to in-memory (filesystem/DB mode now);
`N8N_RESTRICT_FILE_ACCESS_TO` now defaults to `~/.n8n-files`; new Save-vs-Publish model (Save
doesn't touch the live workflow, Publish does). n8n ships a migration tool that scans for
incompatible workflows before upgrading — use it. 1.x gets security fixes for 3 months post-2.0.

## 4. Self-hosting

**Personal single-instance** **[Official + Community]**: Docker/Compose is the recommended path;
`npm install` is lighter on RAM (relevant on a Pi). SQLite is fine for personal use — known pain is
slow editor performance and "database is locked" under concurrency, and **SQLite can't do queue
mode**. No Redis/workers needed at this scale.

**Scaled/reliable** **[Official]**: queue mode + Redis + Postgres + worker processes, optionally
dedicated webhook processors. Key env vars: `EXECUTIONS_MODE=queue`, `N8N_WORKER_CONCURRENCY`,
`N8N_DEFAULT_BINARY_DATA_MODE`, `N8N_PAYLOAD_SIZE_MAX`, `NODE_OPTIONS=--max-old-space-size=…`.

**Hardware** **[Community, directional not official]**: ~2GB RAM/2 vCPU minimum for testing;
4-8GB RAM/4 cores + Postgres for comfortable production, especially AI workflows. Raspberry Pi 4
(4GB) or Pi 5 recommended (Pi 3/1GB struggles with AI/concurrent flows; prefer npm install over
Docker on a Pi). **A Mac Mini-class machine is comfortably more than enough** for personal +
moderate AI-agent use, with headroom for Postgres+Redis if you ever want queue mode.

## 5. Debugging

**Built-in** **[Official]**: Error Workflows + Error Trigger node (a separate workflow that fires
on any monitored workflow's failure, routes to Slack/email/logging — the standard production
pattern). Per-node "Continue on Fail" and "Retry on Fail" settings, Stop-and-Error node. Every
execution is stored with full per-node input/output JSON, inspectable and re-runnable — this
visual per-node data inspection is n8n's biggest debugging strength.

**Common failure modes** **[Community + Official docs page]**: webhook timeouts (caller expects a
response in ~30-60s — fix: "Respond Immediately", process async); memory exhaustion (n8n loads all
items into memory by default, chokes around a few hundred–thousand heavy JSON items — fix: Split
In Batches, filesystem/DB binary mode, raise `--max-old-space-size`, or queue mode at real volume);
"existing execution data is too large" on self-hosted (documented, fixable); 429 rate limits from
bursty API calls (fix: batching + Wait node); misconfigured env vars as a frequent stall/slowness
root cause.

**Community**: forum.n8n.io (30k+ members, thousands of solved threads, primary searchable
resource), Discord (faster/real-time, less persistent), GitHub issues (actively triaged). Overall:
genuinely active, responsive ecosystem — a real strength vs. most self-hosted tools.

## 6. Real-world applications

**Categories** **[Community + Official use-case pages]**: personal/homelab automation
(notifications, monitoring, syncing — mostly tutorials, thinner on rigorous public case studies);
small-business process automation (lead routing, CRM sync, invoicing, approvals — deterministic
if-this-then-that with branches/loops is n8n's strongest fit); AI agent orchestration (fastest-
growing — 70+ dedicated AI nodes built natively on LangChain, hierarchical node system separating
main agent from sub-nodes/memory/tools/vector-DB/output-parsers, multi-agent patterns increasingly
built-in; cited use cases: customer support, lead qualification, invoice processing, internal RAG
knowledge assistants, contract review); data pipeline/light ETL (supported, not the sweet spot);
notification/monitoring systems.

**Recruiter/outreach automation** **[Community, thinner — flagged low-confidence]**: no canonical
public reference workflow found. The building blocks are all idiomatic n8n (lead qualification,
CRM sync, outreach sequencing are called-out core strengths) — buildable, not "here's a template."
Shape: parse inbound recruiter emails → AI Agent classifies/prioritizes → drafts/personalizes
replies → Calendar scheduling → logs to sheet/DB. This maps directly onto the "triage" pattern
(AI Agent + Structured Output Parser) already pulled from the MCP tool.

**NetworkChuck's n8n + Claude Code project** — confirmed, directly relevant prior art
**[Community: `theNetworkChuck/n8n-claude-code-guide` on GitHub + his own posts]**: n8n drives
Claude Code (not just API calls — full terminal access) on a box he controls via n8n's native SSH
node, running `claude -p "<prompt>"` headless, using `--session-id`/`-r` for continuous
conversational context across workflow runs. Architecture is hub-and-spoke: n8n orchestrates, SSH
is the transport, Claude Code executes on his own infra (he runs a Hostinger VPS). Demonstrated
uses: homelab ping/monitoring (Zima board, NAS, RPi), UniFi AP status checks, log parsing +
port-scan alerting, local LLM workflows via Open WebUI/LiteLLM, prompting Claude from his phone via
Slack. Security note: `--dangerously-skip-permissions` for multi-agent parallelism is powerful but
a real blast-radius concern worth sandboxing — directly relevant if MARVIN ever takes this shape.

## Caveats

Resource requirements are directional (independent blogs, not an official hardware matrix) and
vary a lot by workload — AI flows are much heavier than plain automation. Integration counts
(~400 vs ~1,000 depending on source) shouldn't be quoted precisely. No canonical recruiter-outreach
template exists yet — that would be original work, not adaptation.

## Sources

Official: [Sustainable Use License](https://docs.n8n.io/privacy-and-security/sustainable-use-license) ·
[LICENSE.md](https://github.com/n8n-io/n8n/blob/master/LICENSE.md) ·
[GitHub releases](https://github.com/n8n-io/n8n/releases) ·
[v2.0 breaking changes](https://docs.n8n.io/changelog/v20-breaking-changes) ·
[v2.0 migration tool](https://docs.n8n.io/changelog/v20-migration-tool) ·
[Introducing n8n 2.0](https://blog.n8n.io/introducing-n8n-2-0/) ·
[Memory-related errors](https://docs.n8n.io/hosting/scaling/memory-errors/) ·
[n8n AI](https://n8n.io/ai/) · [Multi-agent systems](https://blog.n8n.io/multi-agent-systems/)

Community: [n8n Deep Dive architecture](https://jimmysong.io/blog/n8n-deep-dive/) ·
[Server & API architecture](https://deepwiki.com/n8n-io/n8n/6.1-server-and-api-architecture) ·
[n8n vs Zapier](https://www.datacamp.com/blog/n8n-vs-zapier) ·
[n8n vs Make vs Zapier](https://www.digidop.com/blog/n8n-vs-make-vs-zapier) ·
[n8n vs Airflow](https://techpoint.africa/guide/n8n-vs-apache-airflow/) ·
[License explained](https://scalevise.com/resources/n8n-automation-license-commercial-use/) ·
[System requirements 2025](https://latenode.com/blog/low-code-no-code-platforms/n8n-setup-workflows-self-hosting-templates/n8n-system-requirements-2025-complete-hardware-specs-real-world-resource-analysis) ·
[Self-host requirements 2026](https://vps.us/blog/n8n-self-hosting/) ·
[How to self-host n8n](https://localtonet.com/blog/how-to-self-host-n8n) ·
[Timeout/memory fixes](https://industrialmonitordirect.com/blogs/knowledgebase/fixing-n8n-timeout-and-memory-errors-in-high-volume-workflows) ·
[Webhook failures](https://prosperasoft.com/blog/automation-tools/n8n/n8n-webhook-failures-production/) ·
["Execution data too large" fix](https://www.tva.sg/insights/solving-n8n-existing-execution-data-is-too-large-error-the-complete-fix-for-self-hosted-instances) ·
[Where to get n8n help](https://axshul.site/n8n/guide/where-to-get-n8n-help/) ·
[GitHub issues](https://github.com/n8n-io/n8n/issues) ·
[AI Agent vs LLM Chain](https://dev.to/ciphernutz/n8n-ai-agent-vs-llm-chain-when-to-use-langchain-code-48h4) ·
[70+ AI nodes](https://www.digitalapplied.com/blog/n8n-70-ai-nodes-langchain-agent-workflows-open-source)

NetworkChuck: [n8n-claude-code-guide](https://github.com/theNetworkChuck/n8n-claude-code-guide) ·
[Claude Code via n8n](https://x.com/NetworkChuck/status/1999178380176974053) ·
[Self-hosting n8n homelab](https://x.com/NetworkChuck/status/1930316341648535935)

## From the n8n MCP tool server directly (synta-mcp)

n8n's own use-case taxonomy (`get_best_practices` mode=list) — the fastest fit-check for "is this
n8n-shaped": universal, scheduling, chatbot, form_input, scraping_and_research, triage,
content_generation, document_processing, data_extraction, data_analysis, data_transformation,
data_persistence, notification, web_app.

Universal best practice: prefer native nodes (Edit Fields/Set, If, Switch, Filter, Merge,
Aggregate, Split Out, Sort, Structured Output Parser) over a Code node — Code nodes are slower
(sandboxed) and should be a last resort, not a default.

AI-agent architecture patterns, in increasing complexity: Simple AI Agent → AI Agent with Tools
(+ memory, tool nodes the agent decides whether to invoke) → Multi-Agent System/Orchestrator
(supervisor delegates to AgentTool sub-agents, each with its own Chat Model) → RAG
Ingestion/RAG Query → Hybrid Chat & Schedule with Shared Memory (one Window Buffer Memory node
connected to both a scheduled processing agent and a chat-query agent, so users can ask about
previously processed data). Each pattern's exact topology is treated as mandatory by the tool —
deviating breaks the workflow, not just suboptimal.
