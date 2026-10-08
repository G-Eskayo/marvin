# ADR 0055: Dashboard Feeds Threads from Writer/Reader Path Constants

**Status:** Accepted (2026-10-07)  
**Context:** #239 — derive "feeds" data-flow threads from code

## Problem

The brain-map currently shows:
- `calls:` edges from skill frontmatter (explicit declarations)
- `hook`/`cron` edges from launchd/settings.local.json wiring (explicit infrastructure)
- `undeclared` edges for real dependencies that never made it into frontmatter

But it has no visibility into **data flows**: when a library module writes a file (e.g., `STAGES_DIR = ~/.agents/stages`) and a dashboard tab reads it (e.g., `const STAGES_DIR = path.join(homedir(), '.agents', 'stages')`), that coupling is invisible to the graph.

The issue asks for a way to automatically detect these "feeds" threads and render them alongside the existing wiring.

## Solution

### 1. **Writer Detection** (lib/*.py)

For each Python file in `~/.agents/lib/` (excluding tests and `_`-prefixed files):

1. Extract constants matching `*_PATH` or `*_DIR` from the source
2. Regex handles:
   - `HOME / "x" / "y"` chains (where `HOME = Path.home()` aliased earlier)
   - `Path.home() / "x" / "y"` inline
   - String literals `"~/x/y"` or `"/path/to/x"`
3. Resolve to `~` formatted paths under home directory
4. **Attribute to a node** by:
   - Direct `script_path` match in the tree (e.g., `lib/agents/ticket_pipeline.py` → `ticket-pipeline` node)
   - Or `writer_module_owners` override in `enrichment.json` (e.g., `"ticket_stages": "ticket-pipeline"` when ticket_stages.py is imported but not directly opened)

### 2. **Reader Detection** (dashboard tabs)

Dashboard readers are **hand-listed** per tab in `enrichment.json`:

```json
"dashboard_tab_readers": {
  "health": ["health.js"],
  "metrics": ["metrics.js"],
  "activity": ["activity.js", "../webhook-server/ticket_stages.js"],
  "docs": ["catalog.js", "docs_service.js", "docs_local.js", "docs.js"]
}
```

For each tab's files:
1. Read the file from disk
2. Extract constants matching `*_PATH` or `*_DIR` (JavaScript: `path.join(homedir(), ...)` patterns; Python: same as writers)
3. Resolve to `~` formatted paths

**Why hand-listed?** Auto-following imports would miss readers reached only through runtime injection (e.g., `docs_service.js` takes a `getCatalog` closure, never statically imports `catalog.js`). The hand-maintained list is the explicit tradeoff, same philosophy used elsewhere in the codebase (skill_desc_overrides, agent_overrides, hook_overrides).

### 3. **Matching & Threading**

For each unique path resolved by writers and readers:
- Connect every writer → every reader on that path
- Emit `{a: writer_node_id, b: tab_id, label, type: "feeds"}` synapse
- Report unmatched writers/readers as gaps in CI output

### 4. **Visualization**

- **Dash pattern:** `[6, 2]` (distinct from `[3, 4]` undeclared, `[1, 4]` hook/cron, solid calls)
- **Tooltip label:** "DATA FEED (writer → reader)"
- **Footer legend:** updated to include feeds in the wiring description
- **Privacy:** paths in synapses redacted to `~` via `export_snapshot.py`

## Trade-offs

### Why writer_module_owners overrides?

A module like `ticket_stages.py` is **imported** by `ticket_pipeline.py` but never opened as its own node. Without an override, its path constants (e.g., `STAGES_DIR`) would have no attribution. The override maps the module stem to the owning node.

**Alternative:** Auto-detect ownership by tracing imports in the importing node's script. **Rejected:** too fragile (import order, conditional imports, late bindings), and introduces a build-time dependency on Python's AST that goes unmaintained if the codebase refactors.

### Why hand-maintained tab readers?

**Alternative:** Auto-crawl all files under dashboard/* and extract constants. **Rejected:** miss runtime-injected readers (e.g., docs_service.js), and overcollect files that reference *_PATH in comments/strings but aren't real readers.

The explicit list is short (< 10 entries) and stable. Updated only when a reader file is added or removed from a tab.

### Why not trace subprocess calls (tool_usage.py → usage_report.js)?

The plan explicitly excludes subprocess-call tracing (e.g., `usage_report.py` invoked by `usage_report.js`, reading stdout). That's a different relationship (cross-process RPC), not a shared file dependency. Included in the AC #1 scope ("Metrics tab"), satisfied by the standalone `metrics_registry.py` ↔ `metrics.js` pairing on `~/.agents/bench/metrics`.

## Implementation

### Code

- `brain-map/scripts/data_flow.py`: extract_py_path_constants, extract_js_path_constants, discover_writers, discover_readers, match_threads
- `brain-map/scripts/test_data_flow.py`: fixture tests per AC
- `enrichment.json`: writer_module_owners, dashboard_tab_readers
- `generate.py`: call data_flow.match_threads() after build_synapses
- `template.html`: feeds dash pattern, tooltip label, footer legend
- `export_snapshot.py`: redact paths in synapses (privacy AC)

### Tests

- `test_data_flow.py`: pure unit tests (extract_py_path_constants, extract_js_path_constants, match_threads with synthetic fixtures)
- `test_generate.py`: extend with an end-to-end case (tmp_path writer + reader files → feeds synapse appears)
- `code-layer.test.mjs`: pre-existing failure (3/4, "no openable nodes found"), unrelated to this ticket, left alone

## Gaps & Future Work

1. **Subprocess calls:** tool_usage.py → usage_report.js is out of scope; could be added later as a `"subprocess"` synapse type
2. **Reader auto-discovery:** if a pattern emerges (e.g., `electron/main/` becomes a source of readers), can lift to auto-crawl + override allowlist instead of hand-listing
3. **Path format:** all paths currently formatted as `~`. Could extend to support other home-like anchors (e.g., project root) if needed

## Acceptance Criteria

1. ✅ Two distinct writer/reader path constants → expected "feeds" synapse; unmatched constants → gap record
2. ✅ Gaps reported in CI output (same format as existing "WARNING: … dropped" line)
3. ✅ Footer legend explains "feeds" and its dash pattern
4. ✅ Snapshot export redacts paths in synapses, privacy scan covers them
