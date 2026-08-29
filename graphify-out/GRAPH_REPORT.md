# Graph Report - .agents  (2026-08-29)

## Corpus Check
- 328 files · ~503,241 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2943 nodes · 4397 edges · 281 communities (239 shown, 42 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 136 edges (avg confidence: 0.85)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `5fb13ceb`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Network Reachability Checks
- motion.12.42.2.js
- session_start_report.py
- cleanup_sweep.py
- code_sync.py
- fn
- test_evidence_capture.py
- Bench Harness Runner
- $r
- route.py
- test_sandbox_orchestration.py
- Paper-Dive Argument Mapper
- Brain-Map Desktop Live App
- test_metrics_registry.py
- me
- Paper-Dive Logic Auditor
- test_intent_classify.py
- devDependencies
- MARVIN Setup Script
- en
- task_dispatch.py
- Auto-Route Hook
- Brain-Map Tree Generator
- QA-Agent Scan Tests
- MARVIN
- dashboard/package.json
- QA-Agent Code Scanner
- mr_review.js
- Cleanup Sweep Tests
- QA-Agent Capture
- e
- test_mr_raiser.py
- QA-Agent Complexity Visitor
- Bench Task 012 Decoder
- Network Reachability Tests
- test_ticket_claim.py
- Graphify Skill Definition
- cron_health.py
- test_ticket_promotion.py
- build
- cross_machine_merge.py
- logic_auditor.py
- browser_ctl.py
- LRUCache
- scripts
- test_mlx_lm_eval_adapter.py
- MetricsScorecard.jsx
- classify_paper_type
- SortedList
- auto_fix.py
- compute_reliability_signal
- ho
- build_audit_report
- extract_structure
- .add
- render_pdf.py
- LRUCache
- cross_domain_synthesis.py
- During the session
- retrieve.py
- inventory.py
- machine_profile.py
- fetch_related.py
- rebuild-embeddings.py
- App.jsx
- main
- _parse_findings
- test_cross_machine_merge.py
- check_remote_session.py
- generate_handoff_from_transcript.py
- main
- main
- _parse_fields
- patch_file
- task-006-email-lookup/files/db.py
- append
- extract
- build_events
- capture_brainmap_v4.py
- sort_suggestions.py
- _resolve_claude_bin
- compute_all_reliability_signals
- profiles/setup.sh
- validate_date
- capture_brainmap.py
- capture_brainmap_v3.py
- capture_brainmap_v5.py
- capture_brainmap_v6.py
- _call_root_name
- route/install.sh
- holdout_fixture_v1_spent.py
- holdout_fixture_v2_spent.py
- brain-map/install.sh
- improve/install.sh
- research-colony/install.sh
- Process
- graphify reference: extra exports and benchmark
- Agent skills
- graphify reference: query, path, explain
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- .claude/CLAUDE.md
- extraction-spec.md
- improvement_sweep.py
- Diagnose
- Triage
- test_ticket_coordination.py
- Diagnose — Retrospective
- retrospective-log.md
- daily_digest.py
- to-prd/SKILL.md
- 7. Architecture Decision Records
- measure
- To Tasklist
- Writing Skills
- ticket_claim.py
- mac
- ticket_coordination.py
- Process
- Design Document — Resume Tailor
- tdd/SKILL.md
- 2. Functional Requirements
- setup-matt-pocock-skills/SKILL.md
- [TAILOR] — Full Application Package
- Logic/State-Machine Prototype
- Resume Tailor
- Creative
- Direct inspirations & dependencies
- n8n platform research
- Architecture Review
- QA Code Agent
- Architecture — Safety & Drift Monitor
- marvin-bench — results log
- Safety Monitor
- Token Optimization Best Practices
- MARVIN — Context Glossary
- Animation tools evaluation — 2026-07-17
- intent_classify.py
- test_route.py
- Design — Safety & Drift Monitor
- compare_route_classifiers.py
- Run 15 — 2026-07-01 (account session-limit discovery, infra-error handling, quota preflight, select_model.py, two more judge bugs)
- Context Window Best Practices
- Claude Code Global Settings
- Index — Pull the Right Boxes
- Research Colony Skill
- Requirements — Safety & Drift Monitor
- marvin-bench
- 0024 — Fixed PR evidence schema for v1, adaptive per-ticket requirements deferred
- Scenario: Diagnose → Improve
- Scenario: Research → Design → Build
- Handoff
- Route Skill
- Run 13 — 2026-07-01 (three new discriminator tasks: multi-file invariant, deceptive comment, KB isolation)
- Run 5 — 2026-06-30 (v2 corrected grading + redesigned task-007)
- 0001 — Use the Claude Agent SDK, not `remote-control`, as the voice client's backend
- 0002 — Native iOS app, not a PWA, for the voice client
- 0003 — Dual-mode architecture: full MARVIN online, degraded local model offline
- 0004 — Distribute via free Apple ID + AltStore/AltServer, not a paid Developer account
- 0005 — Plan-and-confirm guardrail for voice-triggered tool execution
- 0006 — MLX for the offline-mode on-device model, over llama.cpp/GGUF
- 0007 — Greedy best-first search, not depth-penalized A*, for citation-graph traversal
- 0008 — Bidirectional traversal (references + citations), asymmetric caps, shared relevance floor with a result-intent bypass
- 0009 — Store first-discovery edge metadata only, not all paths
- 0010 — Checkpoint-and-confirm with a diminishing-returns signal, not a flat hard node cap
- 0011 — Blend SPECTER2 with nomic-embed for relevance scoring, not SPECTER2 alone
- 0012 — Semantic Scholar rate-limit handling: exponential backoff, no API key (yet)
- 0013 — Task-dispatch: general primitive, not a cron patch; single-target only for v1
- 0014 — research-colony fan-out+merge: layer on existing triggers, event-driven completion signal
- 0015 — Quarantine over-flagging: rubric grounding + the missing review-feedback loop
- 0016 — Intent-vs-reality audit agent: reuse the Agent tool, don't build dedicated infrastructure
- 0017 — suggestions.md: priority-ordered backlog, whole-system scope, not TaskList-backed
- 0018 — Auto-discover brain-map's Autonomous Agents from launchd plists
- 0019 — Auto-discover brain-map's Infrastructure hooks from settings.local.json
- 0020 — Add a Cross-Machine Network trunk to brain-map
- 0021 — Bidirectional code sync via a scoped auto-commit exception
- 0022 — ~/.claude sync: self-hosted git remote, and a conflict-marker propagation guard
- 0023 — route.py's keyword classifier: replace with an embedding classifier, phased and flag-gated
- Session-start checklist
- Audit
- Improve Skill
- Lexicon
- Run 14 — 2026-07-01 (judge isolation fix + setup.sh durability bug)
- Security Policy
- caveman/SKILL.md
- Sources
- Self-Improve Retrospective
- Run 3 — 2026-06-30 (recall task on all 3 profiles — profile routing confirmation)
- Run 1 — 2026-06-26 (first full suite, single run each)
- Run 4 — 2026-06-30 (initial v2 run — grading bugs found)
- Shared Lexicon
- Issue Tracker
- Run 2 — 2026-06-28 (profile routing validation)
- Run 18 — 2026-08-13 (route.py embedding classifier — reference-set expansion, same fixture)
- Run 19 — 2026-08-13 (grown fixture: 20 → 40 clean items + 8 ambiguous — 85% didn't hold)
- Run 20 — 2026-08-13 (targeted research reference-set expansion)
- Run 21 — 2026-08-13 (genuine held-out validation set — first honest read)
- Run 22 — 2026-08-13 (score-formula bug found + fixed, threshold recalibrated, default flipped)
- Run 23 — 2026-08-13 (off-topic detection gap, investigated — two hypotheses, both negative)
- Run 24 — 2026-08-13 (targeted research + coding expansion — real gain, real cost)
- Run 25 — 2026-08-13 (recall regression fixed, one new small cost surfaced)
- Run 26 — 2026-08-13 (fresh holdout v2 built — the honest number is 72%, not 87.5%)
- Run 27 — 2026-08-13 (architecture diagnosed and fixed — large gain, real disclosed cost)
- Run 28 — 2026-08-13 (coding diagnosed and fixed — clean, zero collateral cost, confirms Run 27's hypothesis)
- Run 29 — 2026-08-13 (fresh holdout v3 built — 87.5%, independently confirmed)
- brain-map GIF capture experiments (paused 2026-07-17)
- Domain Docs
- Triage Labels
- Handoff — Retrospective
- Paper Dive — Retrospective
- Safety Monitor — Retrospective
- Retrospective — to-tasklist
- index.md
- brain-map/CONTEXT.md
- tailwindcss
- MrReview.jsx
- @vitejs/plugin-react
- verify.py
- co
- sandbox_orchestration.py
- mn
- ticket-21.md
- ticket-22.md
- run
- test_gh_merge_guard.py
- background_review.py
- deny.js
- test_build_type_measure.py
- test_ticket_pipeline.py
- .get
- research_digest.py
- test_run_ticket.py
- playwright-core
- process
- 0025 — Deny action: two dashboard buttons, structured-feedback modal, not a third "adjust" button
- MR-approval webhook contract
- webhook-server/package.json
- calibrate.py
- ticket_pipeline.py
- yi
- run_colony.py
- source_monitor.py
- ticket-24.md
- fixture
- dispatch_ticket.sh
- Path

## God Nodes (most connected - your core abstractions)
1. `co()` - 35 edges
2. `e()` - 31 edges
3. `n()` - 30 edges
4. `fn()` - 25 edges
5. `marvin-bench — results log` - 25 edges
6. `en` - 24 edges
7. `oo()` - 21 edges
8. `ke` - 20 edges
9. `_metric()` - 20 edges
10. `vl()` - 20 edges

## Surprising Connections (you probably didn't know these)
- `main()` --calls--> `log_hook_error()`  [INFERRED]
  skills/improve/scripts/improvement_sweep.py → lib/hook_errors.py
- `main()` --calls--> `notify()`  [INFERRED]
  skills/improve/scripts/daily_digest.py → lib/notify.py
- `main()` --calls--> `log_hook_error()`  [INFERRED]
  brain-map/scripts/skill_activity.py → lib/hook_errors.py
- `main()` --calls--> `log_hook_error()`  [INFERRED]
  skills/self-improve/scripts/background_review.py → lib/hook_errors.py
- `process()` --calls--> `process_and_check_quarantine()`  [INFERRED]
  skills/safety-monitor/scripts/process_quarantine_reviews.py → lib/session_start_report.py

## Import Cycles
- None detected.

## Communities (281 total, 42 thin omitted)

### Community 0 - "Network Reachability Checks"
Cohesion: 0.05
Nodes (73): _arp_mac(), check_and_record(), check_domain(), current_network_id(), _default_gateway(), known_status(), _load_store(), main() (+65 more)

### Community 1 - "motion.12.42.2.js"
Cohesion: 0.04
Nodes (43): adopt(), be(), collectTargets(), constructor(), Dr(), ec(), Et(), fa() (+35 more)

### Community 2 - "session_start_report.py"
Cohesion: 0.07
Nodes (56): BaseException, main(), _allow_decision(), check(), main(), log_hook_error(), Shared failure logger for PostToolUse hooks. Hooks intentionally swallow…, check_auto_fix_log() (+48 more)

### Community 3 - "cleanup_sweep.py"
Cohesion: 0.30
Nodes (12): _default_list_worktrees(), _default_remove_worktree(), _extract_issue_number(), find_orphaned_worktrees(), find_stale_claims(), datetime, Path, Cron entry point. Runs both sweeps, logs what was removed/released (same… (+4 more)

### Community 4 - "code_sync.py"
Cohesion: 0.05
Nodes (40): _files_with_conflict_markers(), _git(), _git_ok(), _log(), main(), _merge_remote(), pull(), push() (+32 more)

### Community 5 - "fn"
Cohesion: 0.11
Nodes (6): fn(), Fs(), Is(), Ki, os(), ti()

### Community 6 - "test_evidence_capture.py"
Cohesion: 0.11
Nodes (9): _commit_change(), fixture, Tests for evidence_capture.py. Run via: ~/.agents/venv/bin/python -m pytest…, repo_with_worktree(), _run(), test_touches_ui_false_for_a_backend_only_change(), test_touches_ui_true_for_a_dashboard_electron_change(), test_touches_ui_true_for_a_dashboard_src_change() (+1 more)

### Community 7 - "Bench Harness Runner"
Cohesion: 0.07
Nodes (43): aggregate_runs(), _check_quota(), _fmt_multi(), _fmt_single(), fmt_table(), _is_infra_error(), judge_run(), _load_marvin_context() (+35 more)

### Community 8 - "$r"
Cohesion: 0.10
Nodes (9): bo(), br(), Go(), jn(), $r(), ur, vo(), xo() (+1 more)

### Community 9 - "route.py"
Cohesion: 0.17
Nodes (16): ArgumentParser, Namespace, _build_arg_parser(), classify(), launch(), _launch_cmd(), main(), print_aliases() (+8 more)

### Community 10 - "test_sandbox_orchestration.py"
Cohesion: 0.15
Nodes (16): git_repo(), _metric(), metrics_dir(), _noop_executor(), fixture, Tests for sandbox_orchestration.py. Run via: ~/.agents/venv/bin/python -m…, test_baseline_recorded_to_metrics_registry(), test_creates_isolated_worktree_not_touching_live_repo() (+8 more)

### Community 11 - "Paper-Dive Argument Mapper"
Cohesion: 0.14
Nodes (27): build_argument_map(), enrich_missing_titles(), extract_core_claim(), fetch_title(), main(), ollama_chat(), _openalex_work_id(), OpenAlex's /works/{id} path accepts either its own W-prefixed id (already a… (+19 more)

### Community 12 - "Brain-Map Desktop Live App"
Cohesion: 0.11
Nodes (17): Any, Bool, AppDelegate, DesktopWebView, Cocoa, Date, Notification, NSApplicationDelegate (+9 more)

### Community 13 - "test_metrics_registry.py"
Cohesion: 0.08
Nodes (36): compare(), _direction(), index(), latest(), _load_snapshots(), _narrative_path(), Path, Recompute, from every per-subsystem JSON file, a subsystem -> latest metrics… (+28 more)

### Community 14 - "me"
Cohesion: 0.12
Nodes (11): Cn, de(), fe(), Gt(), Ht(), le(), me(), pe() (+3 more)

### Community 15 - "Paper-Dive Logic Auditor"
Cohesion: 0.12
Nodes (22): judge_all(), judge_extraction(), Judges a type-adaptive extraction (from extract_structure) against its type-…, papers: {slug: (extraction_dict, paper_type)}. Returns {slug: findings_list}., render_markdown(), Tests for logic_auditor.py. Run via: ~/.agents/venv/bin/python -m pytest…, test_judge_all_handles_empty_input(), test_judge_all_judges_each_paper_by_its_own_type() (+14 more)

### Community 16 - "test_intent_classify.py"
Cohesion: 0.15
Nodes (6): _FakeCollection, Tests for intent_classify.py. Run via: ~/.agents/venv/bin/python -m pytest…, test_classify_embeds_the_description_as_a_query_not_a_document(), test_classify_returns_best_matching_intent_when_confident(), test_classify_returns_no_match_when_below_threshold(), test_classify_score_uses_correct_cosine_distance_conversion()

### Community 17 - "devDependencies"
Cohesion: 0.12
Nodes (17): autoprefixer, devDependencies, autoprefixer, electron, electron-builder, electron-vite, postcss, react (+9 more)

### Community 18 - "MARVIN Setup Script"
Cohesion: 0.25
Nodes (25): build_embeddings(), clone_resume_tailor(), configure_claude(), configure_hook(), deploy_brain_map(), deploy_retrospective_log(), detect_gpu(), detect_os() (+17 more)

### Community 19 - "en"
Cohesion: 0.08
Nodes (4): en, ke, kn(), zt()

### Community 20 - "task_dispatch.py"
Cohesion: 0.17
Nodes (22): _load_registry(), This machine's stable id in marvin-network.json, resolved by matching hardware…, All registered devices that aren't this one, keyed by device id., registry_id(), remote_devices(), _build_wrapper_script(), _candidates(), dispatch() (+14 more)

### Community 21 - "Auto-Route Hook"
Cohesion: 0.12
Nodes (13): _already_fired(), classify(), main(), _mark_fired(), Return the routing message for prompt, or None to stay silent (architecture/no-…, _resolve_intent(), Tests for auto_route_hook.py. Run via: ~/.agents/venv/bin/python -m pytest…, _run_main() (+5 more)

### Community 22 - "Brain-Map Tree Generator"
Cohesion: 0.19
Nodes (22): build_agent_children(), build_device_children(), build_hook_children(), build_skill_node(), build_synapses(), build_tree(), collect_ids(), discover_devices() (+14 more)

### Community 23 - "QA-Agent Scan Tests"
Cohesion: 0.19
Nodes (22): analyze_python_file(), Return complexity/principles issues for a single .py file., make_project(), Path, Tests for qa-agent scripts. Run via: ~/.agents/venv/bin/python -m pytest…, test_clean_function_no_flags(), test_detect_stack_javascript(), test_detect_stack_multi() (+14 more)

### Community 24 - "MARVIN"
Cohesion: 0.04
Nodes (47): 1. Coding tasks — MARVIN adds ~10% overhead with zero quality gain, 1. Recall — MARVIN knows things the others don't, 1b. MARVIN advantage grows on weaker models (Haiku cross-model run), 1c. Local model context injection — works for facts, fails for jargon (Run 9), 1d. 14B + RAG closes the jargon gap — semantic parity at zero cost (Runs 10–12), 2. Caveman mode "backfired" — REVISED 2026-07-02, was likely a confound, not a real finding, 2. Navigation efficiency — MARVIN finds the answer 3× cheaper, 3. Profile routing — recovers the coding overhead (+39 more)

### Community 25 - "dashboard/package.json"
Cohesion: 0.20
Nodes (9): author, dependencies, recharts, description, main, name, private, version (+1 more)

### Community 26 - "QA-Agent Code Scanner"
Cohesion: 0.19
Nodes (20): analyze_comment_quality(), analyze_complexity(), analyze_quality(), detect_stack(), extract_dependencies(), extract_imports(), extract_markers(), infer_domain() (+12 more)

### Community 27 - "mr_review.js"
Cohesion: 0.11
Nodes (31): execFileAsync, ghIssueView(), ADR-0024, ADR-0025, listOpenPrs(), postJson(), registerMetricsHandlers(), registerMrReviewHandlers() (+23 more)

### Community 28 - "Cleanup Sweep Tests"
Cohesion: 0.16
Nodes (15): _iso(), _issue(), log_path(), fixture, Tests for cleanup_sweep.py. Run via: ~/.agents/venv/bin/python -m pytest…, test_does_not_flag_claim_under_threshold(), test_does_not_flag_worktree_with_active_claim(), test_does_not_remove_worktree_with_active_claim() (+7 more)

### Community 29 - "QA-Agent Capture"
Cohesion: 0.17
Nodes (18): build_entry(), infer_pattern_type(), main(), Return True if new, False if already existed (dedup by id)., Return best-guess pattern_type from document content and tags., store_entry(), extract_decisions(), extract_outcome() (+10 more)

### Community 30 - "e"
Cohesion: 0.07
Nodes (26): ar(), c(), ca(), cr, e(), er(), fr(), Gr() (+18 more)

### Community 31 - "test_mr_raiser.py"
Cohesion: 0.11
Nodes (20): _failing_result(), _passing_result(), fixture, Tests for mr_raiser.py. Run via: ~/.agents/venv/bin/python -m pytest…, A bare 'origin' remote, a main-repo clone with one commit, and a worktree…, repo_with_worktree(), _run(), test_comment_on_ticket_called_with_ticket_and_pr_url() (+12 more)

### Community 32 - "QA-Agent Complexity Visitor"
Cohesion: 0.15
Nodes (6): _analyze_function_body(), ComplexityVisitor, QualityVisitor, Single-pass structural read of a function: cyclomatic complexity + concern…, Walk an AST and collect complexity signals., Detect verbosity, naming, and logic anti-patterns via AST.

### Community 33 - "Bench Task 012 Decoder"
Cohesion: 0.17
Nodes (13): decode(), DecodedEvent, datetime, Event decoder — deserialises events from the internal JSON wire format., Parse a raw JSON event string and return a DecodedEvent. Raises ValueError on…, encode(), Event encoder — serialises events to the internal JSON wire format., Return a JSON string representing a single event. Version 2 wire format: {… (+5 more)

### Community 34 - "Network Reachability Tests"
Cohesion: 0.13
Nodes (5): _FakeCompleted, Tests for network_reachability.py. Run via: ~/.agents/venv/bin/python -m pytest…, test_arp_mac_parses_non_zero_padded_octets(), test_arp_mac_parses_zero_padded_octets(), test_arp_mac_returns_none_when_no_entry()

### Community 35 - "test_ticket_claim.py"
Cohesion: 0.14
Nodes (7): _issue(), Tests for ticket_claim.py. Run via: ~/.agents/venv/bin/python -m pytest…, test_cap_is_exactly_three(), test_claims_lowest_issue_number_first(), test_claims_nothing_when_at_cap(), test_claims_when_under_cap(), test_count_claimed_only_counts_this_machines_claims()

### Community 36 - "Graphify Skill Definition"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 37 - "cron_health.py"
Cohesion: 0.18
Nodes (16): _archive_previous_latest(), check_job(), check_organize_sync(), check_repo_convergence(), check_repo_integrity(), _load_state(), main(), _new_content() (+8 more)

### Community 38 - "test_ticket_promotion.py"
Cohesion: 0.15
Nodes (10): _promoting_evaluator(), Tests for ticket_promotion.py. Run via: ~/.agents/venv/bin/python -m pytest…, _skipping_evaluator(), test_creates_ticket_when_evaluator_says_promote(), test_no_manual_approval_step_runs_synchronously_to_completion(), test_reasoning_captured_in_result_and_passed_to_ticket_creator(), test_reasoning_present_even_when_not_promoted(), test_skips_ticket_creation_when_evaluator_says_dont_promote() (+2 more)

### Community 39 - "build"
Cohesion: 0.29
Nodes (7): build, appId, directories, files, productName, output, out/**/*

### Community 40 - "cross_machine_merge.py"
Cohesion: 0.26
Nodes (14): build_merged(), load_sync_state(), main(), profile_blurb(), Path, Identical shape to sync_qa_knowledge -- same deterministic-set-union- by-id…, Returns stdout on success, None on any failure (unreachable, non-zero exit,…, run_merge_authority() (+6 more)

### Community 41 - "logic_auditor.py"
Cohesion: 0.14
Nodes (15): check_inference_validity(), check_inference_validity_all(), _level_from_finding_count(), ollama_chat(), Symbolizes the paper's key inferential move and checks the argument's FORM --…, papers: {slug: (title, abstract)}. Returns {slug: inference_check_dict}., _worse_of(), test_check_inference_validity_all_handles_empty_input() (+7 more)

### Community 42 - "browser_ctl.py"
Cohesion: 0.25
Nodes (13): _chromium_executable(), cmd_click(), cmd_fill(), cmd_html(), cmd_navigate(), cmd_screenshot(), cmd_start(), cmd_status() (+5 more)

### Community 43 - "LRUCache"
Cohesion: 0.17
Nodes (7): LRUCache, LRU cache for expensive database queries. Evicts the least-recently-used entry…, fetch_user_report(), Database access layer. Uses LRUCache to avoid hitting the DB on every call., Simulate an expensive DB query (real implementation would hit the DB)., Return the cached report for (user_id, report_type), hitting the DB if needed., _run_query()

### Community 44 - "scripts"
Cohesion: 0.33
Nodes (6): scripts, build, build:mac, dev, preview, test

### Community 45 - "test_mlx_lm_eval_adapter.py"
Cohesion: 0.19
Nodes (9): Returns (summed_logprob, is_greedy) for `continuation` given `context`, using…, score_continuation(), model_and_tokenizer(), fixture, Tests for the in-process MLX loglikelihood adapter. Run via:…, Cross-checks score_continuation's single batched forward pass against a…, test_is_greedy_true_for_actual_argmax_continuation_false_otherwise(), test_logit_slicing_matches_independent_step_by_step_computation() (+1 more)

### Community 46 - "MetricsScorecard.jsx"
Cohesion: 0.28
Nodes (3): formatTimestamp(), SubsystemCard(), SubsystemDrilldown()

### Community 47 - "classify_paper_type"
Cohesion: 0.14
Nodes (14): classify_all(), classify_paper_type(), Returns one of PAPER_TYPES, or "unknown" if the response can't be parsed into…, papers: {slug: (title, abstract)}. Returns {slug: type}., test_classify_all_classifies_every_paper_in_the_input_dict(), test_classify_all_handles_empty_input(), test_classify_paper_type_extracts_label_from_extra_prose(), test_classify_paper_type_falls_back_to_unknown_on_unparseable_response() (+6 more)

### Community 48 - "SortedList"
Cohesion: 0.15
Nodes (5): A sorted list that maintains elements in ascending order with O(log n)…, Insert value maintaining sorted order., Return True if value is present., Remove the first occurrence of value. Does nothing if value is absent., SortedList

### Community 49 - "auto_fix.py"
Cohesion: 0.32
Nodes (12): backup_files(), build_prompt(), _core_files(), get_candidates(), log_run(), main(), Path, Fresh qa_scan.py pass (via its importable scan() function, same as… (+4 more)

### Community 50 - "compute_reliability_signal"
Cohesion: 0.15
Nodes (13): compute_reliability_signal(), layer1_findings: from judge_extraction. layer2_result: from…, test_deductive_invalid_adds_its_own_finding(), test_deductive_invalid_does_not_improve_an_already_worse_paper(), test_deductive_invalid_floors_a_clean_paper_to_low_not_high(), test_deductive_valid_does_not_floor_or_add_a_finding(), test_four_or_more_findings_is_very_low(), test_inductive_weak_adds_a_finding_but_does_not_hard_floor() (+5 more)

### Community 52 - "build_audit_report"
Cohesion: 0.21
Nodes (12): build_audit_report(), needs_second_look(), Assembles the full per-paper audit -- type, both layers' visible extraction,…, _sample_report_inputs(), test_build_audit_report_entry_has_all_expected_fields(), test_build_audit_report_flags_low_reliability_papers(), test_build_audit_report_handles_empty_slug_list(), test_build_audit_report_includes_one_entry_per_slug_in_given_order() (+4 more)

### Community 53 - "extract_structure"
Cohesion: 0.17
Nodes (12): extract_all(), extract_structure(), Extracts the type-appropriate structure as a reviewable intermediate artifact…, papers: {slug: (title, abstract, paper_type)}. Returns {slug: extraction_dict}., test_extract_all_handles_empty_input(), test_extract_all_routes_each_paper_by_its_own_type(), test_extract_structure_benchmark_uses_construct_validity_fields(), test_extract_structure_conceptual_uses_structural_claim_fields() (+4 more)

### Community 54 - ".add"
Cohesion: 0.16
Nodes (7): $a(), ga, Ll(), ol(), reconcileRemovals(), Rr(), ys()

### Community 55 - "render_pdf.py"
Cohesion: 0.26
Nodes (11): _annotate_sections(), _build_fit_ladder(), _content_fill_ratio(), _make_fit_step(), md_to_html(), _override_css(), Wrap the header cluster (name + short metadata lines) in CSS-hookable…, Give Projects entries and Experience role headers a distinct visual weight from… (+3 more)

### Community 56 - "LRUCache"
Cohesion: 0.18
Nodes (5): LRUCache, LRU (Least Recently Used) cache with a fixed capacity. Items are evicted in…, Return the cached value for key, or None if not present., Insert or update key. Evicts the LRU item if over capacity., Fixed-capacity LRU cache. Access order is maintained by the underlying…

### Community 57 - "cross_domain_synthesis.py"
Cohesion: 0.27
Nodes (9): main(), print_human(), Infer the problem's own domain (unless given), then fetch top-N transferable…, synthesize(), filter_results(), main(), query_kb(), test_filter_results_by_category() (+1 more)

### Community 58 - "During the session"
Cohesion: 0.07
Nodes (24): ADR Format, CONTEXT.md Format, Challenge against the glossary, Cross-reference with code, Discuss concrete scenarios, Domain awareness, During the session, File structure (+16 more)

### Community 59 - "retrieve.py"
Cohesion: 0.35
Nodes (10): bm25_rerank(), embed_query(), _entry_tag_words(), get_threshold(), main(), _query_collection(), retrieve(), rrf_merge() (+2 more)

### Community 60 - "inventory.py"
Cohesion: 0.29
Nodes (9): get_conn(), get_stock(), Inventory reservation system for a high-throughput e-commerce checkout service., Reserve `quantity` units of item_id. Returns True if the reservation succeeded., Return `quantity` units to inventory (e.g. on order cancellation)., release_item(), reserve_item(), setup_db() (+1 more)

### Community 61 - "machine_profile.py"
Cohesion: 0.32
Nodes (11): build_profile(), _claude_install_method(), _hardware_uuid(), _label(), load_or_build(), machine_label(), _mobility_class(), Fast path for tagging — just the label, cached aggressively. (+3 more)

### Community 62 - "fetch_related.py"
Cohesion: 0.44
Nodes (9): arxiv_search(), fmt_paper(), get_requests(), main(), rank_papers(), recency_score(), s2_paper_by_doi(), s2_recommendations() (+1 more)

### Community 63 - "rebuild-embeddings.py"
Cohesion: 0.36
Nodes (9): build_doc_text(), collection_for(), content_hash(), embed(), main(), Upsert changed entries and prune deleted ones. Returns (embedded, skipped,…, resolve_path(), strip_frontmatter() (+1 more)

### Community 65 - "main"
Cohesion: 0.47
Nodes (8): extract_pdf(), extract_url(), main(), parse_metadata(), Path, Best-effort extraction of title, authors, DOI from raw text., save_session(), slugify()

### Community 66 - "_parse_findings"
Cohesion: 0.22
Nodes (9): _parse_findings(), qwen2.5:3b doesn't reliably put one FINDING per line -- seen live 2026-07-13…, test_parse_findings_extracts_each_finding_line(), test_parse_findings_filters_out_stray_none_captured_as_a_finding(), test_parse_findings_ignores_preamble_before_the_first_marker(), test_parse_findings_returns_empty_list_for_blank_response(), test_parse_findings_returns_empty_list_for_none_response(), test_parse_findings_splits_multiple_findings_crammed_onto_one_line() (+1 more)

### Community 68 - "check_remote_session.py"
Cohesion: 0.48
Nodes (6): _check_remote(), _load_state(), main(), Path, _save_state(), _surface_resume_prompt()

### Community 69 - "generate_handoff_from_transcript.py"
Cohesion: 0.52
Nodes (6): extract_recent_excerpt(), _extract_text(), main(), Path, Dispatched here via task_dispatch.py's plain-bash wrapper script over SSH — a…, _resolve_claude_bin()

### Community 70 - "main"
Cohesion: 0.57
Nodes (6): file_at_commit(), is_append_only_extension(), main(), Path, True if `newer` == `older` + zero or more new lines at the end, with every line…, run_git()

### Community 71 - "main"
Cohesion: 0.60
Nodes (5): check_content(), main(), Path, ssh_cat(), tail_log()

### Community 72 - "_parse_fields"
Cohesion: 0.33
Nodes (6): _parse_fields(), Parses a "FIELD: value" formatted response into {lowercase_field: value},…, test_parse_fields_accumulates_multiline_values_until_next_field(), test_parse_fields_extracts_single_line_values(), test_parse_fields_is_case_insensitive_on_labels(), test_parse_fields_missing_field_is_absent_not_empty_string()

### Community 73 - "patch_file"
Cohesion: 0.47
Nodes (5): insert_tags(), main(), patch_file(), Path, Insert tags (and calls) into YAML frontmatter before the closing ---.

### Community 74 - "task-006-email-lookup/files/db.py"
Cohesion: 0.40
Nodes (4): add_order(), add_user(), Add an order for an existing user. Raises ValueError if user not found., Add a new user. Raises ValueError if email already registered.

### Community 75 - "append"
Cohesion: 0.70
Nodes (4): append(), main(), pulse(), Path

### Community 76 - "extract"
Cohesion: 0.80
Nodes (4): extract(), _extract_docx(), _extract_pdf(), Path

### Community 77 - "build_events"
Cohesion: 0.67
Nodes (3): build_events(), main(), (step_index, kind, arg) — spread across the loop by fraction, twice.

### Community 78 - "capture_brainmap_v4.py"
Cohesion: 0.83
Nodes (3): build_segment_b_events(), capture_loop(), main()

### Community 79 - "sort_suggestions.py"
Cohesion: 0.83
Nodes (3): _sort_key(), sort_suggestions(), _split_entries()

### Community 80 - "_resolve_claude_bin"
Cohesion: 0.67
Nodes (3): main(), SSH's non-interactive shell doesn't source .zshrc/.zprofile, so PATH may not…, _resolve_claude_bin()

### Community 81 - "compute_all_reliability_signals"
Cohesion: 0.50
Nodes (4): compute_all_reliability_signals(), layer1_findings: {slug: findings_list} from judge_all. layer2_results: {slug:…, test_compute_all_reliability_signals_combines_per_paper(), test_compute_all_reliability_signals_handles_empty_input()

### Community 89 - "_call_root_name"
Cohesion: 0.67
Nodes (3): Call, _call_root_name(), First identifier of a call chain: requests.get(...) -> 'requests'.

### Community 103 - "Process"
Cohesion: 0.17
Nodes (11): 1. Gather context, 2. Explore the codebase (optional), 3. Draft vertical slices, 4. Quiz the user, 5. Publish the issues to the issue tracker, Acceptance criteria, Blocked by, Parent (+3 more)

### Community 105 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 106 - "Agent skills"
Cohesion: 0.29
Nodes (6): Agent skills, Domain docs, graphify, Issue tracker, MARVIN (~/.agents) — Repo Instructions, Triage labels

### Community 107 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 108 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 109 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 110 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

### Community 115 - "improvement_sweep.py"
Cohesion: 0.39
Nodes (8): append_to_queue(), extract_project(), find_project_path(), format_issue(), main(), Path, Returns True if the block was appended, False if safety-monitor quarantined it…, top_issues()

### Community 116 - "Diagnose"
Cohesion: 0.17
Nodes (11): Diagnose, Iterate on the loop itself, Non-deterministic bugs, Phase 1 — Build a feedback loop, Phase 2 — Reproduce, Phase 3 — Hypothesise, Phase 4 — Instrument, Phase 5 — Fix + regression test (+3 more)

### Community 117 - "Triage"
Cohesion: 0.11
Nodes (16): For `ready-for-human` specifically, Structure, What makes a brief durable vs. fragile, Writing Durable Agent Briefs, Consumer rules, Structure, The `.out-of-scope/` Knowledge Base, Invocation (+8 more)

### Community 120 - "Diagnose — Retrospective"
Cohesion: 0.22
Nodes (8): 2026-07-07 — MLX on-device model benchmark (Qwen2.5-3B vs Llama-3.2-3B), 2026-07-14 — Converting the session-start checklist into a deterministic hook, 2026-07-17 — Brain-map reskin (dark gradient silently not rendering), 2026-07-17 — DesktopLive verification pass (post-Motion deploy), 2026-07-17 — Motion physics deploy to brain-map/DesktopLive (pulses, camera nudges, fitScale), 2026-08-26 — killer-sudoku full day (perf tuning + real bugs), 2026-08-26 — killer-sudoku Kotlin port (UI parity + animation/input bugs), Diagnose — Retrospective

### Community 123 - "daily_digest.py"
Cohesion: 0.29
Nodes (11): bench_summary(), call_claude(), improvement_queue_summary(), main(), qa_kb_summary(), Computed directly from the log, not via an LLM guess at "does this look…, launchd's environment doesn't source .zshrc/.zprofile, so PATH may not include…, recent_handoffs_summary() (+3 more)

### Community 124 - "to-prd/SKILL.md"
Cohesion: 0.22
Nodes (8): Further Notes, Implementation Decisions, Out of Scope, Problem Statement, Process, Solution, Testing Decisions, User Stories

### Community 125 - "7. Architecture Decision Records"
Cohesion: 0.07
Nodes (28): 1. System Overview, 2. Directory Structure, 3.1 SKILL.md, 3.2 `scripts/fetch_jd.py`, 3.3 `scripts/extract_text.py`, 3.4 `scripts/render_pdf.py`, 3.5 `template/resume.css`, 3. Component Breakdown (+20 more)

### Community 127 - "measure"
Cohesion: 0.26
Nodes (11): measure(), Path, One touched file -> the pytest path arg it implies. `skills/` gets two path…, Which test command matches what this ticket's diff actually touches, scoped…, metrics_registry.compare()-shaped measure() for build-type tickets. Returns two…, _scope_root(), test_command_for(), _touched_files() (+3 more)

### Community 128 - "To Tasklist"
Cohesion: 0.50
Nodes (3): Process, To Tasklist, When to use this instead of to-issues/to-prd

### Community 129 - "Writing Skills"
Cohesion: 0.07
Nodes (25): Evidence gate, Quality Filter, Recurrence gate, Value gate, When a gate fails, 1. Identify the pattern, 2. Apply the quality filter, 3. Draft or update the skill (+17 more)

### Community 130 - "ticket_claim.py"
Cohesion: 0.36
Nodes (6): _claim_label(), claim_next_ticket(), _default_add_claim_label(), _default_list_claimed(), _default_remove_claim_label(), Claim the highest-priority (lowest issue number) unclaimed ready-for-agent…

### Community 131 - "mac"
Cohesion: 0.40
Nodes (5): mac, category, target, dmg, zip

### Community 132 - "ticket_coordination.py"
Cohesion: 0.25
Nodes (6): Release a claim this machine holds, so another machine (or a later cycle) can…, release(), claim_with_coordination(), Check `issue_number` for a same-instant collision (more than one claimed:*…, Claim via ticket_claim.claim_next_ticket (unchanged), then resolve any…, resolve_collision()

### Community 133 - "Process"
Cohesion: 0.10
Nodes (19): Applying tiers, Contested, Epistemic Framework — Confidence Tier Definitions, Established, Speculative, Unknown, 1. Frame the question precisely, 2. Map the space (+11 more)

### Community 134 - "Design Document — Resume Tailor"
Cohesion: 0.10
Nodes (19): 1. User Flows, 2. Skill Commands, 3.1 Relevance score, 3.2 Recency score, 3.3 Combined score, 3.4 Aerospace crossover signal, 3. Scoring & Selection Algorithm, 4. Template Slots — revised 2026-07-02 (+11 more)

### Community 135 - "tdd/SKILL.md"
Cohesion: 0.11
Nodes (14): Deep Modules, Designing Interfaces for Testability, Mocking Guidelines, Refactor Candidates, 1. Planning, 2. Tracer Bullet, 3. Incremental Loop, 4. Refactor (+6 more)

### Community 136 - "2. Functional Requirements"
Cohesion: 0.11
Nodes (18): 1. Purpose, 2.1 Master Resume, 2.2 Company & Role Research, 2.3 Master Resume Updates, 2.3 Tailoring, 2.4 Cover Letter, 2.4 Transcript Parsing, 2.5 Output Package (+10 more)

### Community 137 - "setup-matt-pocock-skills/SKILL.md"
Cohesion: 0.11
Nodes (12): Domain Docs, Issue Tracker: GitHub, Issue Tracker: GitLab, Issue Tracker: Local Markdown, 1. Explore, 2. Present findings and ask, 3. Confirm and edit, 4. Write (+4 more)

### Community 138 - "[TAILOR] — Full Application Package"
Cohesion: 0.12
Nodes (16): [ADD-TO-MASTER] — Add New Entry, Command Routing, Constants, [MERGE-RESUME] — Merge Uploaded Resume, [PARSE-TRANSCRIPT] — Extract Skills from Academic Transcript, Phase 1: Intake, Phase 2: Research, Phase 3: Tailoring (+8 more)

### Community 139 - "Logic/State-Machine Prototype"
Cohesion: 0.13
Nodes (12): Example shape, Logic/State-Machine Prototype, Shape, What NOT to build, Pick a branch, Prototype, Rules that apply to both, When done (+4 more)

### Community 140 - "Resume Tailor"
Cohesion: 0.14
Nodes (13): 1. Install system dependency (macOS), 2. Install Python dependencies, 3. Create your master resume, 4. Wire the skill (Claude Code), Commands, How tailoring works, Output, Privacy model (+5 more)

### Community 141 - "Creative"
Cohesion: 0.15
Nodes (12): 1. Resist the first idea, 2. Reframe the brief, 3. Apply constraints deliberately, 4. Generate divergent options, 5. Iterate, don't perfect, Creative, Cross-Domain Pattern Synthesis (technical/engineering problems only), Domain-Specific Notes (+4 more)

### Community 142 - "Direct inspirations & dependencies"
Cohesion: 0.17
Nodes (11): Acknowledgements, [Anthropic Claude Code](https://github.com/anthropics/claude-code), [ChromaDB — Chroma Core](https://github.com/chroma-core/chroma), Contributing, Direct inspirations & dependencies, [FastMCP](https://github.com/jlowin/fastmcp), [Hermes Agent — NousResearch](https://github.com/NousResearch/hermes-agent), [markdown-it-py](https://github.com/executablebooks/markdown-it-py) & [pdfminer.six](https://github.com/pdfminer/pdfminer.six) (+3 more)

### Community 143 - "n8n platform research"
Cohesion: 0.18
Nodes (10): 1. What it is, architecturally, 2. Licensing — most important to get exactly right, 3. Versions, 4. Self-hosting, 5. Debugging, 6. Real-world applications, Caveats, From the n8n MCP tool server directly (synta-mcp) (+2 more)

### Community 144 - "Architecture Review"
Cohesion: 0.18
Nodes (10): 1. Audit the system, 2. Generate suggestions, 3. Present to user, 4. On approval, Architecture Review, Optimization Priorities, Review Process, Review Subcommand (+2 more)

### Community 145 - "QA Code Agent"
Cohesion: 0.18
Nodes (10): 1 — Scan a project (auto-extract patterns), 2 — Query the knowledge base, 3 — Capture a pattern manually, 4 — Lateral (cross-domain) query, Behaviour rules, Commands, Data schema, QA Code Agent (+2 more)

### Community 146 - "Architecture — Safety & Drift Monitor"
Cohesion: 0.18
Nodes (10): Architecture — Safety & Drift Monitor, `calibrate.py` — risk-controlled threshold, Component overview, `drift_report.py` — weekly divergence check, Dual-channel drift audit (`otr_log.py`), File layout, Integration points (diffs to existing files, not rewrites), Session-start integration (+2 more)

### Community 147 - "marvin-bench — results log"
Cohesion: 0.20
Nodes (9): Findings from Run 16, Findings from Run 17, marvin-bench — results log, Next bench priorities, Next bench priorities, Run 16 — 2026-07-02 (caveman mode retest — Run 1's finding was confounded), Run 17 — 2026-08-13 (route.py keyword classifier vs. new embedding classifier, ADR 0023), Run 30 — 2026-08-13 (targeted fix: bare "bug in {file}" phrasing losing to recall) (+1 more)

### Community 148 - "Safety Monitor"
Cohesion: 0.20
Nodes (9): Integration status, Known gaps (tracked, not silently assumed fixed), Known gotchas, Manual invocation / smoke test, Output files, Safety Monitor, Scripts, Triggers (+1 more)

### Community 149 - "Token Optimization Best Practices"
Cohesion: 0.22
Nodes (8): Anti-Patterns, Caching, Chunking for Large Inputs, Context Reuse, Model Routing (highest leverage), Output Discipline, Prompt Design, Token Optimization Best Practices

### Community 150 - "MARVIN — Context Glossary"
Cohesion: 0.20
Nodes (9): Citation-graph knowledge base (in design, not yet built), Code sync (built 2026-07-09/12 — distinct from cross_machine_merge.py's data sync), Dashboard app — Files tab (in design, 2026-08-27), Fan-out + merge (mode 2), first application: research-colony, MARVIN — Context Glossary, MR pipeline (in design, 2026-08-19), Session continuity (in design, 2026-07-12), Task-dispatch (v1 built and tested; mode 2 built and applied to research-colony) (+1 more)

### Community 151 - "Animation tools evaluation — 2026-07-17"
Cohesion: 0.22
Nodes (8): Animation tools evaluation — 2026-07-17, Anime.js — recommended, targeted use, Bklit — catalogued, not usable as-is, Bottom line / recommended next step, `brain-map`'s actual constraint, which shapes every recommendation below, Kokonut UI — catalogued, not usable as-is, Manus (manus.im) — different category entirely, Motion (motion.dev, ex-Framer Motion) — recommended, targeted use

### Community 152 - "intent_classify.py"
Cohesion: 0.39
Nodes (8): build_collection(), classify(), embed_text(), _get_collection(), main(), Embed via Ollama nomic-embed-text. task='query' for classify() input,…, (Re)embed every reference example into the intent-routing collection. Uses…, Return {"status": "ok"|"no_match"|"unavailable", "intent": str|None, "score":…

### Community 154 - "Design — Safety & Drift Monitor"
Cohesion: 0.22
Nodes (8): Connection to the requested automation pipeline, Design — Safety & Drift Monitor, Open questions / risks, `quarantine.md`, Review command, Rollout plan, Session start, User-facing surface

### Community 155 - "compare_route_classifiers.py"
Cohesion: 0.39
Nodes (5): _classify_row(), run_ambiguous(), run_clean(), Genuinely held-out validation fixture v3 for route.py's embedding classifier…, run()

### Community 156 - "Run 15 — 2026-07-01 (account session-limit discovery, infra-error handling, quota preflight, select_model.py, two more judge bugs)"
Cohesion: 0.25
Nodes (8): Findings from Run 15, First trustworthy select_model.py results (post judge-fixes), Next bench priorities, "Ran out of tokens fast" — not a Fable 5 model swap, Robustness fixes to bench.py, Run 15 — 2026-07-01 (account session-limit discovery, infra-error handling, quota preflight, select_model.py, two more judge bugs), select_model.py — ascending-cost model-selection sweep, Two more judge bugs found while verifying select_model.py, both fixed

### Community 157 - "Context Window Best Practices"
Cohesion: 0.25
Nodes (7): Anti-Patterns, Compression Signals, Context Window Best Practices, Handoff Before Context Switch, Indexing Over Inlining, Skill File Discipline, The Five-Level Loading Hierarchy

### Community 158 - "Claude Code Global Settings"
Cohesion: 0.25
Nodes (7): Architecture Review Queue, Claude Code Global Settings, Context Switch Protocol, Development Defaults, Lexicon, Session Start, Skills

### Community 159 - "Index — Pull the Right Boxes"
Cohesion: 0.25
Nodes (7): Examples, Fallback: manual manifest matching, Index — Pull the Right Boxes, Keeping the Manifest Current, Manifest Structure, Primary: hybrid retrieval engine, Tag Namespaces

### Community 160 - "Research Colony Skill"
Cohesion: 0.25
Nodes (7): ChromaDB collections, Correlation signals, Output files, Research Colony Skill, Running manually, Scripts, Triggers

### Community 161 - "Requirements — Safety & Drift Monitor"
Cohesion: 0.25
Nodes (7): Acceptance criteria, Functional requirements, Goals, Non-functional requirements, Non-goals, Problem statement, Requirements — Safety & Drift Monitor

### Community 162 - "marvin-bench"
Cohesion: 0.29
Nodes (6): Isolation, Known limitations, marvin-bench, Run, Task format, Why

### Community 163 - "0024 — Fixed PR evidence schema for v1, adaptive per-ticket requirements deferred"
Cohesion: 0.33
Nodes (5): 0024 — Fixed PR evidence schema for v1, adaptive per-ticket requirements deferred, Consequences, Context, Decision, Status

### Community 164 - "Scenario: Diagnose → Improve"
Cohesion: 0.29
Nodes (6): Failure modes, Handoff points, Known companions, Scenario: Diagnose → Improve, Skill sequence, When to use

### Community 165 - "Scenario: Research → Design → Build"
Cohesion: 0.29
Nodes (6): Failure modes, Handoff points, Known companions, Scenario: Research → Design → Build, Skill sequence, When to use

### Community 166 - "Handoff"
Cohesion: 0.29
Nodes (6): Document Structure, Handoff, On Resume, Rules, Save Location, When to Run Autonomously

### Community 167 - "Route Skill"
Cohesion: 0.29
Nodes (6): CLI usage, Evidence base, Install, Route Skill, Routing table (bench-validated), Triggers

### Community 168 - "Run 13 — 2026-07-01 (three new discriminator tasks: multi-file invariant, deceptive comment, KB isolation)"
Cohesion: 0.33
Nodes (6): Findings from Run 13, Next bench priorities, Run 13 — 2026-07-01 (three new discriminator tasks: multi-file invariant, deceptive comment, KB isolation), task-012-protocol-mismatch (fs, expect both `fromisoformat` + `{1, 2, 3}` for 1.00), task-013-lru-cache-bug (fs, expect `move_to_end`), task-014-kb-lookup (qa, expect exact phrase `"Context quality matters more than model size"`)

### Community 169 - "Run 5 — 2026-06-30 (v2 corrected grading + redesigned task-007)"
Cohesion: 0.33
Nodes (6): Findings from Run 5, Next bench priorities, Run 5 — 2026-06-30 (v2 corrected grading + redesigned task-007), task-005-date-validator (fixed grading: `datetime.date`), task-006-email-lookup (fixed grading: `, None)`), task-007-dyld-recall (redesigned: caveman mode token counts)

### Community 170 - "0001 — Use the Claude Agent SDK, not `remote-control`, as the voice client's backend"
Cohesion: 0.33
Nodes (5): 0001 — Use the Claude Agent SDK, not `remote-control`, as the voice client's backend, Consequences, Context, Decision, Status

### Community 171 - "0002 — Native iOS app, not a PWA, for the voice client"
Cohesion: 0.33
Nodes (5): 0002 — Native iOS app, not a PWA, for the voice client, Consequences, Context, Decision, Status

### Community 172 - "0003 — Dual-mode architecture: full MARVIN online, degraded local model offline"
Cohesion: 0.33
Nodes (5): 0003 — Dual-mode architecture: full MARVIN online, degraded local model offline, Consequences, Context, Decision, Status

### Community 173 - "0004 — Distribute via free Apple ID + AltStore/AltServer, not a paid Developer account"
Cohesion: 0.33
Nodes (5): 0004 — Distribute via free Apple ID + AltStore/AltServer, not a paid Developer account, Consequences, Context, Decision, Status

### Community 174 - "0005 — Plan-and-confirm guardrail for voice-triggered tool execution"
Cohesion: 0.33
Nodes (5): 0005 — Plan-and-confirm guardrail for voice-triggered tool execution, Consequences, Context, Decision, Status

### Community 175 - "0006 — MLX for the offline-mode on-device model, over llama.cpp/GGUF"
Cohesion: 0.33
Nodes (5): 0006 — MLX for the offline-mode on-device model, over llama.cpp/GGUF, Consequences, Context, Decision, Status

### Community 176 - "0007 — Greedy best-first search, not depth-penalized A*, for citation-graph traversal"
Cohesion: 0.33
Nodes (5): 0007 — Greedy best-first search, not depth-penalized A*, for citation-graph traversal, Consequences, Context, Decision, Status

### Community 177 - "0008 — Bidirectional traversal (references + citations), asymmetric caps, shared relevance floor with a result-intent bypass"
Cohesion: 0.33
Nodes (5): 0008 — Bidirectional traversal (references + citations), asymmetric caps, shared relevance floor with a result-intent bypass, Consequences, Context, Decision, Status

### Community 178 - "0009 — Store first-discovery edge metadata only, not all paths"
Cohesion: 0.33
Nodes (5): 0009 — Store first-discovery edge metadata only, not all paths, Consequences, Context, Decision, Status

### Community 179 - "0010 — Checkpoint-and-confirm with a diminishing-returns signal, not a flat hard node cap"
Cohesion: 0.33
Nodes (5): 0010 — Checkpoint-and-confirm with a diminishing-returns signal, not a flat hard node cap, Consequences, Context, Decision, Status

### Community 180 - "0011 — Blend SPECTER2 with nomic-embed for relevance scoring, not SPECTER2 alone"
Cohesion: 0.33
Nodes (5): 0011 — Blend SPECTER2 with nomic-embed for relevance scoring, not SPECTER2 alone, Consequences, Context, Decision, Status

### Community 181 - "0012 — Semantic Scholar rate-limit handling: exponential backoff, no API key (yet)"
Cohesion: 0.33
Nodes (5): 0012 — Semantic Scholar rate-limit handling: exponential backoff, no API key (yet), Consequences, Context, Decision, Status

### Community 182 - "0013 — Task-dispatch: general primitive, not a cron patch; single-target only for v1"
Cohesion: 0.33
Nodes (5): 0013 — Task-dispatch: general primitive, not a cron patch; single-target only for v1, Consequences, Context, Decision, Status

### Community 183 - "0014 — research-colony fan-out+merge: layer on existing triggers, event-driven completion signal"
Cohesion: 0.33
Nodes (5): 0014 — research-colony fan-out+merge: layer on existing triggers, event-driven completion signal, Consequences, Context, Decision, Status

### Community 184 - "0015 — Quarantine over-flagging: rubric grounding + the missing review-feedback loop"
Cohesion: 0.33
Nodes (5): 0015 — Quarantine over-flagging: rubric grounding + the missing review-feedback loop, Consequences, Context, Decision, Status

### Community 185 - "0016 — Intent-vs-reality audit agent: reuse the Agent tool, don't build dedicated infrastructure"
Cohesion: 0.33
Nodes (5): 0016 — Intent-vs-reality audit agent: reuse the Agent tool, don't build dedicated infrastructure, Consequences, Context, Decision, Status

### Community 186 - "0017 — suggestions.md: priority-ordered backlog, whole-system scope, not TaskList-backed"
Cohesion: 0.33
Nodes (5): 0017 — suggestions.md: priority-ordered backlog, whole-system scope, not TaskList-backed, Consequences, Context, Decision, Status

### Community 187 - "0018 — Auto-discover brain-map's Autonomous Agents from launchd plists"
Cohesion: 0.33
Nodes (5): 0018 — Auto-discover brain-map's Autonomous Agents from launchd plists, Consequences, Context, Decision, Status

### Community 188 - "0019 — Auto-discover brain-map's Infrastructure hooks from settings.local.json"
Cohesion: 0.33
Nodes (5): 0019 — Auto-discover brain-map's Infrastructure hooks from settings.local.json, Consequences, Context, Decision, Status

### Community 189 - "0020 — Add a Cross-Machine Network trunk to brain-map"
Cohesion: 0.33
Nodes (5): 0020 — Add a Cross-Machine Network trunk to brain-map, Consequences, Context, Decision, Status

### Community 190 - "0021 — Bidirectional code sync via a scoped auto-commit exception"
Cohesion: 0.33
Nodes (5): 0021 — Bidirectional code sync via a scoped auto-commit exception, Consequences, Context, Decision, Status

### Community 191 - "0022 — ~/.claude sync: self-hosted git remote, and a conflict-marker propagation guard"
Cohesion: 0.33
Nodes (5): 0022 — ~/.claude sync: self-hosted git remote, and a conflict-marker propagation guard, Consequences, Context, Decision, Status

### Community 192 - "0023 — route.py's keyword classifier: replace with an embedding classifier, phased and flag-gated"
Cohesion: 0.33
Nodes (5): 0023 — route.py's keyword classifier: replace with an embedding classifier, phased and flag-gated, Consequences, Context, Decision, Status

### Community 193 - "Session-start checklist"
Cohesion: 0.33
Nodes (5): Editing this checklist, Failure isolation, Session-start checklist, What it checks, per session, What's still prose in CLAUDE.md

### Community 194 - "Audit"
Cohesion: 0.33
Nodes (5): Audit, How to dispatch, Output routing, Reporting back to the user, When to trigger

### Community 195 - "Improve Skill"
Cohesion: 0.33
Nodes (5): Improve Skill, Install cron, Manual invocation, Session start integration, Triggers (manual invocation)

### Community 196 - "Lexicon"
Cohesion: 0.33
Nodes (5): Adding an Entry, Lexicon, Reviewing, Sections, When to Run Autonomously

### Community 197 - "Run 14 — 2026-07-01 (judge isolation fix + setup.sh durability bug)"
Cohesion: 0.40
Nodes (5): Findings from Run 14, Next bench priorities, Related bug: `setup.sh` wasn't durable, Run 14 — 2026-07-01 (judge isolation fix + setup.sh durability bug), Verification re-run: task-014-kb-lookup (post judge-fix)

### Community 198 - "Security Policy"
Cohesion: 0.40
Nodes (4): Pre-push checklist, Reporting a vulnerability, Security Policy, What must never be committed

### Community 199 - "caveman/SKILL.md"
Cohesion: 0.40
Nodes (4): Auto-Clarity Exception, Examples, Persistence, Rules

### Community 200 - "Sources"
Cohesion: 0.40
Nodes (4): Confirmed while researching (not from the papers — found by reading the repo), Primary papers, Sources, Why these two combine

### Community 201 - "Self-Improve Retrospective"
Cohesion: 0.40
Nodes (4): 2026-07-02 — MARVIN feature-inventory audit + brain-map build, 2026-07-03 — background self-improvement reviewer + integrity checker, 2026-07-08 — Marlin n8n automation (Snorkel contract work), background review, Self-Improve Retrospective

### Community 202 - "Run 3 — 2026-06-30 (recall task on all 3 profiles — profile routing confirmation)"
Cohesion: 0.50
Nodes (4): Bug found and fixed, Findings, Next bench priorities, Run 3 — 2026-06-30 (recall task on all 3 profiles — profile routing confirmation)

### Community 203 - "Run 1 — 2026-06-26 (first full suite, single run each)"
Cohesion: 0.50
Nodes (4): Caveats, Findings, Run 1 — 2026-06-26 (first full suite, single run each), Strategic implications (each itself A/B-testable here)

### Community 204 - "Run 4 — 2026-06-30 (initial v2 run — grading bugs found)"
Cohesion: 0.50
Nodes (4): Run 4 — 2026-06-30 (initial v2 run — grading bugs found), task-005-date-validator, task-006-email-lookup, task-007 original (DYLD_LIBRARY_PATH recall)

### Community 205 - "Shared Lexicon"
Cohesion: 0.50
Nodes (3): MCP (Model Context Protocol), Meta, Shared Lexicon

### Community 206 - "Issue Tracker"
Cohesion: 0.50
Nodes (3): Consumer rules, Conventions, Issue Tracker

### Community 207 - "Run 2 — 2026-06-28 (profile routing validation)"
Cohesion: 0.67
Nodes (3): Findings, Next bench priorities, Run 2 — 2026-06-28 (profile routing validation)

### Community 208 - "Run 18 — 2026-08-13 (route.py embedding classifier — reference-set expansion, same fixture)"
Cohesion: 0.67
Nodes (3): Findings from Run 18, Next bench priorities, Run 18 — 2026-08-13 (route.py embedding classifier — reference-set expansion, same fixture)

### Community 209 - "Run 19 — 2026-08-13 (grown fixture: 20 → 40 clean items + 8 ambiguous — 85% didn't hold)"
Cohesion: 0.67
Nodes (3): Findings from Run 19, Next bench priorities, Run 19 — 2026-08-13 (grown fixture: 20 → 40 clean items + 8 ambiguous — 85% didn't hold)

### Community 210 - "Run 20 — 2026-08-13 (targeted research reference-set expansion)"
Cohesion: 0.67
Nodes (3): Findings from Run 20, Next bench priorities, Run 20 — 2026-08-13 (targeted research reference-set expansion)

### Community 211 - "Run 21 — 2026-08-13 (genuine held-out validation set — first honest read)"
Cohesion: 0.67
Nodes (3): Findings from Run 21, Next bench priorities, Run 21 — 2026-08-13 (genuine held-out validation set — first honest read)

### Community 212 - "Run 22 — 2026-08-13 (score-formula bug found + fixed, threshold recalibrated, default flipped)"
Cohesion: 0.67
Nodes (3): Findings from Run 22, Next bench priorities, Run 22 — 2026-08-13 (score-formula bug found + fixed, threshold recalibrated, default flipped)

### Community 213 - "Run 23 — 2026-08-13 (off-topic detection gap, investigated — two hypotheses, both negative)"
Cohesion: 0.67
Nodes (3): Findings from Run 23, Next bench priorities, Run 23 — 2026-08-13 (off-topic detection gap, investigated — two hypotheses, both negative)

### Community 214 - "Run 24 — 2026-08-13 (targeted research + coding expansion — real gain, real cost)"
Cohesion: 0.67
Nodes (3): Findings from Run 24, Next bench priorities, Run 24 — 2026-08-13 (targeted research + coding expansion — real gain, real cost)

### Community 215 - "Run 25 — 2026-08-13 (recall regression fixed, one new small cost surfaced)"
Cohesion: 0.67
Nodes (3): Findings from Run 25, Next bench priorities, Run 25 — 2026-08-13 (recall regression fixed, one new small cost surfaced)

### Community 216 - "Run 26 — 2026-08-13 (fresh holdout v2 built — the honest number is 72%, not 87.5%)"
Cohesion: 0.67
Nodes (3): Findings from Run 26, Next bench priorities, Run 26 — 2026-08-13 (fresh holdout v2 built — the honest number is 72%, not 87.5%)

### Community 217 - "Run 27 — 2026-08-13 (architecture diagnosed and fixed — large gain, real disclosed cost)"
Cohesion: 0.67
Nodes (3): Findings from Run 27, Next bench priorities, Run 27 — 2026-08-13 (architecture diagnosed and fixed — large gain, real disclosed cost)

### Community 218 - "Run 28 — 2026-08-13 (coding diagnosed and fixed — clean, zero collateral cost, confirms Run 27's hypothesis)"
Cohesion: 0.67
Nodes (3): Findings from Run 28, Next bench priorities, Run 28 — 2026-08-13 (coding diagnosed and fixed — clean, zero collateral cost, confirms Run 27's hypothesis)

### Community 219 - "Run 29 — 2026-08-13 (fresh holdout v3 built — 87.5%, independently confirmed)"
Cohesion: 0.67
Nodes (3): Findings from Run 29, Next bench priorities, Run 29 — 2026-08-13 (fresh holdout v3 built — 87.5%, independently confirmed)

### Community 250 - "MrReview.jsx"
Cohesion: 0.12
Nodes (9): MrDetail(), DENY_REASONS, DenyModal(), EvidenceTable(), ADR-0025, MrReview(), reload(), reloadAndReturnToList() (+1 more)

### Community 252 - "verify.py"
Cohesion: 0.33
Nodes (8): _load_rubric(), pass_or_quarantine(), quarantine(), Append a flagged artifact to ~/.claude/quarantine.md for review., The one-line integration point for existing loops. `source_context`: the real…, Return a risk score in [0, 1] for `artifact_text` under `loop_name`'s rubric.…, _resolve_claude_bin(), verify()

### Community 253 - "co"
Cohesion: 0.06
Nodes (16): ba(), bl(), Bs(), co(), ei(), Eo(), ge(), gs() (+8 more)

### Community 254 - "sandbox_orchestration.py"
Cohesion: 0.27
Nodes (9): _create_worktree(), _default_executor(), execute_ticket(), Path, Branches explicitly from `origin/main` (fetched fresh first), not repo_path's…, Drive `ticket_ref` through an isolated worktree and a tune-and-compare loop.…, Real default: a flagship-tier planning call, then a Haiku-tier execution call…, Cron entry point: claim a ticket if capacity allows, then hand it to sandbox… (+1 more)

### Community 255 - "mn"
Cohesion: 0.06
Nodes (11): Ae(), dn(), La(), mn(), pn(), runUpdate(), sn(), then() (+3 more)

### Community 258 - "run"
Cohesion: 0.15
Nodes (19): capture_dev_evidence(), capture_test_results(), _default_capture_screenshot(), _is_ui_path(), parse_test_output(), Path, For a UI-touching ticket, drive the app headlessly and capture a screenshot;…, Extract pass/fail/total from a test runner's real stdout+stderr. Recognizes… (+11 more)

### Community 259 - "test_gh_merge_guard.py"
Cohesion: 0.16
Nodes (5): _FakeStdin, Tests for gh_merge_guard.py. Run via: ~/.agents/venv/bin/python -m pytest…, test_main_never_raises_on_garbage_stdin(), test_main_writes_allow_decision_for_a_matching_command(), test_main_writes_nothing_for_a_non_matching_command()

### Community 260 - "background_review.py"
Cohesion: 0.33
Nodes (8): _cooldown_active(), main(), Runs synchronously — only ever called from the already-detached relaunch below,…, See daily_digest.py's identical helper — launchd's environment doesn't source…, Post-hoc check on what the review actually appended to the append-only…, _resolve_claude_bin(), run_review(), _verify_and_reconcile()

### Community 261 - "deny.js"
Cohesion: 0.14
Nodes (18): assertGithubPrUrl(), dropEntirely(), execFileAsync, formatFeedback(), ADR-0025, releaseClaim(), sendFeedback(), tagForReengagement() (+10 more)

### Community 262 - "test_build_type_measure.py"
Cohesion: 0.16
Nodes (11): _commit_change(), fixture, Tests for build_type_measure.py. Run via: ~/.agents/venv/bin/python -m pytest…, repo_with_worktree(), _run(), test_command_for_falls_back_to_whole_repo_when_touched_paths_have_no_real_directory(), test_command_for_picks_vitest_for_a_dashboard_change(), test_command_for_picks_vitest_when_both_dashboard_and_backend_changed() (+3 more)

### Community 263 - "test_ticket_pipeline.py"
Cohesion: 0.19
Nodes (5): _issue(), Tests for ticket_pipeline.py. Run via: ~/.agents/venv/bin/python -m pytest…, test_main_dry_run_does_not_claim_or_dispatch(), test_unclaimed_ready_tickets_filters_out_claimed(), test_unclaimed_ready_tickets_sorted_oldest_first()

### Community 264 - ".get"
Cohesion: 0.11
Nodes (28): Al(), As(), cl(), dl(), Es(), fl(), gl(), hl() (+20 more)

### Community 265 - "research_digest.py"
Cohesion: 0.43
Nodes (7): _fmt_item(), generate(), load_correlated_from_chroma(), load_today_cache(), Path, launchd's environment doesn't source .zshrc/.zprofile, so PATH may not include…, _resolve_claude_bin()

### Community 266 - "test_run_ticket.py"
Cohesion: 0.23
Nodes (9): _failing_result(), _passing_result(), Tests for run_ticket.py. Run via: ~/.agents/venv/bin/python -m pytest…, test_run_captures_test_results_and_dev_evidence_on_a_passing_result(), test_run_comments_the_failure_reason_when_not_raised(), test_run_does_not_comment_on_a_successful_raise(), test_run_skips_evidence_capture_on_a_failing_result(), test_run_triggers_redispatch_even_when_not_raised() (+1 more)

### Community 268 - "process"
Cohesion: 0.36
Nodes (7): label: 0 = approved (was actually fine), 1 = denied (was actually bad).…, record_label(), _parse_block(), process(), Splits on the entry-header pattern, not "---" (which can appear unquoted inside…, Returns (processed_count, remaining_count)., _split_entries()

### Community 269 - "0025 — Deny action: two dashboard buttons, structured-feedback modal, not a third "adjust" button"
Cohesion: 0.33
Nodes (5): 0025 — Deny action: two dashboard buttons, structured-feedback modal, not a third "adjust" button, Consequences, Context, Decision, Status

### Community 270 - "MR-approval webhook contract"
Cohesion: 0.29
Nodes (6): Contract, Contract: `POST /approve`, Contract: `POST /deny`, Deliberately out of scope here, MR-approval webhook contract, Running it

### Community 272 - "calibrate.py"
Cohesion: 0.43
Nodes (6): calibrate(), get_tau(), Smallest tau such that the false-accept rate on labeled-bad rows <=…, Fast path for verify.py: use the cached tau if present, else calibrate., _read_calibration_rows(), _write_tau()

### Community 273 - "ticket_pipeline.py"
Cohesion: 0.43
Nodes (7): _build_wrapper_command(), _claim(), _label_for_device(), main(), run_ticket.py handles worktree creation (from origin/main, not whatever…, _release(), _unclaimed_ready_tickets()

### Community 274 - "yi"
Cohesion: 0.10
Nodes (21): ai(), animateVisualElement(), Ao(), At(), bi(), ci(), fi(), gi() (+13 more)

### Community 276 - "source_monitor.py"
Cohesion: 0.52
Nodes (6): fetch_arxiv(), fetch_github(), fetch_hackernews(), main(), save_raw_cache(), store_items()

## Knowledge Gaps
- **709 isolated node(s):** `execFileAsync`, `__dirname`, `REBUILD_SCRIPT`, `TICKET_PIPELINE_SCRIPT`, `VENV_PYTHON` (+704 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **42 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `scan()` connect `QA-Agent Code Scanner` to `SortedList`, `auto_fix.py`, `improvement_sweep.py`, `QA-Agent Capture`?**
  _High betweenness centrality (0.009) - this node is a cross-community bridge._
- **Why does `ComplexityVisitor` connect `QA-Agent Complexity Visitor` to `QA-Agent Code Scanner`, `QA-Agent Scan Tests`?**
  _High betweenness centrality (0.005) - this node is a cross-community bridge._
- **Are the 11 inferred relationships involving `e()` (e.g. with `ca()` and `dl()`) actually correct?**
  _`e()` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `n()` (e.g. with `er()` and `ha()`) actually correct?**
  _`n()` has 10 INFERRED edges - model-reasoned connections that need verification._
- **What connects `execFileAsync`, `__dirname`, `REBUILD_SCRIPT` to the rest of the system?**
  _709 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Network Reachability Checks` be split into smaller, more focused modules?**
  _Cohesion score 0.05126582278481013 - nodes in this community are weakly interconnected._
- **Should `motion.12.42.2.js` be split into smaller, more focused modules?**
  _Cohesion score 0.04146612365790448 - nodes in this community are weakly interconnected._