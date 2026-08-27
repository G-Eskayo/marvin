# Graph Report - .agents  (2026-08-26)

## Corpus Check
- 276 files · ~401,979 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1768 nodes · 3191 edges · 123 communities (99 shown, 24 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 113 edges (avg confidence: 0.85)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `dece6c22`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Network Reachability Checks
- motion.12.42.2.js
- Session-Start Reporting & Hook Errors
- cleanup_sweep.py
- Cross-Machine Code Sync
- fn
- verify.py
- Bench Harness Runner
- co
- Route Classifier Benchmarks
- Metrics Registry
- Paper-Dive Argument Mapper
- Brain-Map Desktop Live App
- .forEach
- test_ticket_coordination.py
- Paper-Dive Logic Auditor
- Intent Classification (Route Skill)
- Metrics Registry Tests
- MARVIN Setup Script
- en
- Machine Profile & Task Dispatch
- Auto-Route Hook
- Brain-Map Tree Generator
- QA-Agent Scan Tests
- .get
- ke
- QA-Agent Code Scanner
- $r
- Cleanup Sweep Tests
- QA-Agent Capture
- e
- MR Raiser Tests
- QA-Agent Complexity Visitor
- Bench Task 012 Decoder
- Network Reachability Tests
- test_ticket_claim.py
- Graphify Skill Definition
- cron_health.py
- test_ticket_promotion.py
- s
- cross_machine_merge.py
- logic_auditor.py
- browser_ctl.py
- LRUCache
- mn
- test_mlx_lm_eval_adapter.py
- yn
- classify_paper_type
- SortedList
- auto_fix.py
- compute_reliability_signal
- ho
- build_audit_report
- extract_structure
- oo
- render_pdf.py
- LRUCache
- cross_domain_synthesis.py
- daily_digest.py
- retrieve.py
- inventory.py
- machine_profile.py
- fetch_related.py
- rebuild-embeddings.py
- .updateMotionValue
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
- cr
- me
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
- ur
- Diagnose
- sandbox_orchestration.py
- ticket_claim.py
- ticket_coordination.py
- Diagnose — Retrospective
- bl
- retrospective-log.md

## God Nodes (most connected - your core abstractions)
1. `co()` - 35 edges
2. `e()` - 31 edges
3. `n()` - 30 edges
4. `fn()` - 25 edges
5. `en` - 24 edges
6. `oo()` - 21 edges
7. `ke` - 20 edges
8. `yi()` - 20 edges
9. `_metric()` - 20 edges
10. `vl()` - 20 edges

## Surprising Connections (you probably didn't know these)
- `store_items()` --calls--> `machine_label()`  [INFERRED]
  skills/research-colony/scripts/source_monitor.py → lib/machine_profile.py
- `main()` --calls--> `log_hook_error()`  [INFERRED]
  brain-map/scripts/skill_activity.py → lib/hook_errors.py
- `log_hook_error()` --calls--> `main()`  [INFERRED]
  lib/hook_errors.py → skills/improve/scripts/improvement_sweep.py
- `log_hook_error()` --calls--> `main()`  [INFERRED]
  lib/hook_errors.py → skills/self-improve/scripts/background_review.py
- `process_and_check_quarantine()` --calls--> `process()`  [INFERRED]
  lib/session_start_report.py → skills/safety-monitor/scripts/process_quarantine_reviews.py

## Import Cycles
- None detected.

## Communities (123 total, 24 thin omitted)

### Community 0 - "Network Reachability Checks"
Cohesion: 0.05
Nodes (73): _arp_mac(), check_and_record(), check_domain(), current_network_id(), _default_gateway(), known_status(), _load_store(), main() (+65 more)

### Community 1 - "motion.12.42.2.js"
Cohesion: 0.04
Nodes (31): be(), Dr(), ec(), Et(), fa(), Fo(), Hr(), Io() (+23 more)

### Community 2 - "Session-Start Reporting & Hook Errors"
Cohesion: 0.07
Nodes (53): BaseException, main(), log_hook_error(), Shared failure logger for PostToolUse hooks. Hooks intentionally swallow…, check_auto_fix_log(), check_cron_health(), check_daily_digest(), _check_digest() (+45 more)

### Community 3 - "cleanup_sweep.py"
Cohesion: 0.30
Nodes (12): _default_list_worktrees(), _default_remove_worktree(), _extract_issue_number(), find_orphaned_worktrees(), find_stale_claims(), datetime, Path, Cron entry point. Runs both sweeps, logs what was removed/released (same… (+4 more)

### Community 4 - "Cross-Machine Code Sync"
Cohesion: 0.06
Nodes (32): _files_with_conflict_markers(), _git(), _git_ok(), _log(), main(), _merge_remote(), pull(), push() (+24 more)

### Community 5 - "fn"
Cohesion: 0.10
Nodes (16): ai(), dn(), fi(), fn(), Fs(), gi(), Is(), La() (+8 more)

### Community 6 - "verify.py"
Cohesion: 0.05
Nodes (52): append_to_queue(), extract_project(), find_project_path(), format_issue(), main(), Path, Returns True if the block was appended, False if safety-monitor quarantined it…, top_issues() (+44 more)

### Community 7 - "Bench Harness Runner"
Cohesion: 0.07
Nodes (43): aggregate_runs(), _check_quota(), _fmt_multi(), _fmt_single(), fmt_table(), _is_infra_error(), judge_run(), _load_marvin_context() (+35 more)

### Community 8 - "co"
Cohesion: 0.09
Nodes (16): animateVisualElement(), Ao(), At(), ba(), bi(), ci(), co(), Eo() (+8 more)

### Community 9 - "Route Classifier Benchmarks"
Cohesion: 0.08
Nodes (22): ArgumentParser, _classify_row(), run_ambiguous(), run_clean(), Genuinely held-out validation fixture v3 for route.py's embedding classifier…, run(), Tests for route.py's --embed flag and keyword-classifier fallback. Run via:…, Namespace (+14 more)

### Community 10 - "Metrics Registry"
Cohesion: 0.10
Nodes (27): compare(), _direction(), index(), latest(), _load_snapshots(), _narrative_path(), Path, Recompute, from every per-subsystem JSON file, a subsystem -> latest metrics… (+19 more)

### Community 11 - "Paper-Dive Argument Mapper"
Cohesion: 0.14
Nodes (27): build_argument_map(), enrich_missing_titles(), extract_core_claim(), fetch_title(), main(), ollama_chat(), _openalex_work_id(), OpenAlex's /works/{id} path accepts either its own W-prefixed id (already a… (+19 more)

### Community 12 - "Brain-Map Desktop Live App"
Cohesion: 0.11
Nodes (17): Any, Bool, AppDelegate, DesktopWebView, Cocoa, Date, Notification, NSApplicationDelegate (+9 more)

### Community 13 - ".forEach"
Cohesion: 0.15
Nodes (17): adopt(), As(), collectTargets(), constructor(), Es(), getRoot(), il(), ks() (+9 more)

### Community 15 - "Paper-Dive Logic Auditor"
Cohesion: 0.12
Nodes (22): judge_all(), judge_extraction(), Judges a type-adaptive extraction (from extract_structure) against its type-…, papers: {slug: (extraction_dict, paper_type)}. Returns {slug: findings_list}., render_markdown(), Tests for logic_auditor.py. Run via: ~/.agents/venv/bin/python -m pytest…, test_judge_all_handles_empty_input(), test_judge_all_judges_each_paper_by_its_own_type() (+14 more)

### Community 16 - "Intent Classification (Route Skill)"
Cohesion: 0.11
Nodes (14): build_collection(), classify(), embed_text(), _get_collection(), main(), Embed via Ollama nomic-embed-text. task='query' for classify() input,…, (Re)embed every reference example into the intent-routing collection. Uses…, Return {"status": "ok"|"no_match"|"unavailable", "intent": str|None, "score":… (+6 more)

### Community 17 - "Metrics Registry Tests"
Cohesion: 0.14
Nodes (23): _metric(), metrics_dir(), fixture, Tests for metrics_registry.py. Run via: ~/.agents/venv/bin/python -m pytest…, test_compare_all_improved_or_unchanged_is_passing(), test_compare_all_unchanged_is_not_passing(), test_compare_detects_improvement_higher_is_better(), test_compare_detects_improvement_lower_is_better() (+15 more)

### Community 18 - "MARVIN Setup Script"
Cohesion: 0.25
Nodes (25): build_embeddings(), clone_resume_tailor(), configure_claude(), configure_hook(), deploy_brain_map(), deploy_retrospective_log(), detect_gpu(), detect_os() (+17 more)

### Community 20 - "Machine Profile & Task Dispatch"
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

### Community 24 - ".get"
Cohesion: 0.14
Nodes (16): Al(), cl(), dl(), fl(), gl(), hl(), j(), Ki (+8 more)

### Community 25 - "ke"
Cohesion: 0.18
Nodes (3): Gt(), ke, zt()

### Community 26 - "QA-Agent Code Scanner"
Cohesion: 0.19
Nodes (20): analyze_comment_quality(), analyze_complexity(), analyze_quality(), detect_stack(), extract_dependencies(), extract_imports(), extract_markers(), infer_domain() (+12 more)

### Community 27 - "$r"
Cohesion: 0.08
Nodes (14): bo(), br(), ei(), Go(), hi(), jn(), $r(), So() (+6 more)

### Community 28 - "Cleanup Sweep Tests"
Cohesion: 0.16
Nodes (15): _iso(), _issue(), log_path(), fixture, Tests for cleanup_sweep.py. Run via: ~/.agents/venv/bin/python -m pytest…, test_does_not_flag_claim_under_threshold(), test_does_not_flag_worktree_with_active_claim(), test_does_not_remove_worktree_with_active_claim() (+7 more)

### Community 29 - "QA-Agent Capture"
Cohesion: 0.17
Nodes (18): build_entry(), infer_pattern_type(), main(), Return True if new, False if already existed (dedup by id)., Return best-guess pattern_type from document content and tags., store_entry(), extract_decisions(), extract_outcome() (+10 more)

### Community 30 - "e"
Cohesion: 0.11
Nodes (23): c(), ca(), e(), er(), fr(), Gr(), ha(), Ht() (+15 more)

### Community 31 - "MR Raiser Tests"
Cohesion: 0.17
Nodes (16): _failing_result(), _passing_result(), fixture, Tests for mr_raiser.py. Run via: ~/.agents/venv/bin/python -m pytest…, A bare 'origin' remote, a main-repo clone with one commit, and a worktree…, repo_with_worktree(), _run(), test_comment_on_ticket_called_with_ticket_and_pr_url() (+8 more)

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

### Community 39 - "s"
Cohesion: 0.12
Nodes (10): $a(), ga, ge(), Ll(), Ls(), ol(), reconcileRemovals(), Rr() (+2 more)

### Community 40 - "cross_machine_merge.py"
Cohesion: 0.24
Nodes (15): build_merged(), load_sync_state(), main(), profile_blurb(), Path, Identical shape to sync_qa_knowledge -- same deterministic-set-union- by-id…, Returns stdout on success, None on any failure (unreachable, non-zero exit,…, run_merge_authority() (+7 more)

### Community 41 - "logic_auditor.py"
Cohesion: 0.14
Nodes (15): check_inference_validity(), check_inference_validity_all(), _level_from_finding_count(), ollama_chat(), Symbolizes the paper's key inferential move and checks the argument's FORM --…, papers: {slug: (title, abstract)}. Returns {slug: inference_check_dict}., _worse_of(), test_check_inference_validity_all_handles_empty_input() (+7 more)

### Community 42 - "browser_ctl.py"
Cohesion: 0.25
Nodes (13): _chromium_executable(), cmd_click(), cmd_fill(), cmd_html(), cmd_navigate(), cmd_screenshot(), cmd_start(), cmd_status() (+5 more)

### Community 43 - "LRUCache"
Cohesion: 0.17
Nodes (7): LRUCache, LRU cache for expensive database queries. Evicts the least-recently-used entry…, fetch_user_report(), Database access layer. Uses LRUCache to avoid hitting the DB on every call., Simulate an expensive DB query (real implementation would hit the DB)., Return the cached report for (user_id, report_type), hitting the DB if needed., _run_query()

### Community 45 - "test_mlx_lm_eval_adapter.py"
Cohesion: 0.19
Nodes (9): Returns (summed_logprob, is_greedy) for `continuation` given `context`, using…, score_continuation(), model_and_tokenizer(), fixture, Tests for the in-process MLX loglikelihood adapter. Run via:…, Cross-checks score_continuation's single batched forward pass against a…, test_is_greedy_true_for_actual_argmax_continuation_false_otherwise(), test_logit_slicing_matches_independent_step_by_step_computation() (+1 more)

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

### Community 54 - "oo"
Cohesion: 0.11
Nodes (14): fe(), finalize(), jo(), Nn(), oo(), p, Qs(), ro() (+6 more)

### Community 55 - "render_pdf.py"
Cohesion: 0.26
Nodes (11): _annotate_sections(), _build_fit_ladder(), _content_fill_ratio(), _make_fit_step(), md_to_html(), _override_css(), Wrap the header cluster (name + short metadata lines) in CSS-hookable…, Give Projects entries and Experience role headers a distinct visual weight from… (+3 more)

### Community 56 - "LRUCache"
Cohesion: 0.18
Nodes (5): LRUCache, LRU (Least Recently Used) cache with a fixed capacity. Items are evicted in…, Return the cached value for key, or None if not present., Insert or update key. Evicts the LRU item if over capacity., Fixed-capacity LRU cache. Access order is maintained by the underlying…

### Community 57 - "cross_domain_synthesis.py"
Cohesion: 0.27
Nodes (9): main(), print_human(), Infer the problem's own domain (unless given), then fetch top-N transferable…, synthesize(), filter_results(), main(), query_kb(), test_filter_results_by_category() (+1 more)

### Community 58 - "daily_digest.py"
Cohesion: 0.29
Nodes (10): bench_summary(), improvement_queue_summary(), main(), qa_kb_summary(), Computed directly from the log, not via an LLM guess at "does this look…, launchd's environment doesn't source .zshrc/.zprofile, so PATH may not include…, recent_handoffs_summary(), _resolve_claude_bin() (+2 more)

### Community 59 - "retrieve.py"
Cohesion: 0.35
Nodes (10): bm25_rerank(), embed_query(), _entry_tag_words(), get_threshold(), main(), _query_collection(), retrieve(), rrf_merge() (+2 more)

### Community 60 - "inventory.py"
Cohesion: 0.29
Nodes (9): get_conn(), get_stock(), Inventory reservation system for a high-throughput e-commerce checkout service., Reserve `quantity` units of item_id. Returns True if the reservation succeeded., Return `quantity` units to inventory (e.g. on order cancellation)., release_item(), reserve_item(), setup_db() (+1 more)

### Community 61 - "machine_profile.py"
Cohesion: 0.40
Nodes (9): build_profile(), _claude_install_method(), _hardware_uuid(), _label(), load_or_build(), _mobility_class(), Read the cached profile if fresh enough, else regenerate., _run() (+1 more)

### Community 62 - "fetch_related.py"
Cohesion: 0.44
Nodes (9): arxiv_search(), fmt_paper(), get_requests(), main(), rank_papers(), recency_score(), s2_paper_by_doi(), s2_recommendations() (+1 more)

### Community 63 - "rebuild-embeddings.py"
Cohesion: 0.36
Nodes (9): build_doc_text(), collection_for(), content_hash(), embed(), main(), Upsert changed entries and prune deleted ones. Returns (embedded, skipped,…, resolve_path(), strip_frontmatter() (+1 more)

### Community 64 - ".updateMotionValue"
Cohesion: 0.18
Nodes (4): Cn, sn(), vn(), xn

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

### Community 103 - "cr"
Cohesion: 0.22
Nodes (4): ar(), cr, Ie(), lr()

### Community 104 - "me"
Cohesion: 0.24
Nodes (4): de(), le(), me(), pe()

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

### Community 116 - "Diagnose"
Cohesion: 0.17
Nodes (11): Diagnose, Iterate on the loop itself, Non-deterministic bugs, Phase 1 — Build a feedback loop, Phase 2 — Reproduce, Phase 3 — Hypothesise, Phase 4 — Instrument, Phase 5 — Fix + regression test (+3 more)

### Community 117 - "sandbox_orchestration.py"
Cohesion: 0.31
Nodes (8): _create_worktree(), _default_executor(), execute_ticket(), Path, Real default: a flagship-tier planning call, then a Haiku-tier execution call…, Drive `ticket_ref` through an isolated worktree and a tune-and-compare loop.…, Cron entry point: claim a ticket if capacity allows, then hand it to sandbox…, run_claim_cycle()

### Community 118 - "ticket_claim.py"
Cohesion: 0.36
Nodes (6): _claim_label(), claim_next_ticket(), _default_add_claim_label(), _default_list_claimed(), _default_remove_claim_label(), Claim the highest-priority (lowest issue number) unclaimed ready-for-agent…

### Community 119 - "ticket_coordination.py"
Cohesion: 0.25
Nodes (6): Release a claim this machine holds, so another machine (or a later cycle) can…, release(), claim_with_coordination(), Check `issue_number` for a same-instant collision (more than one claimed:*…, Claim via ticket_claim.claim_next_ticket (unchanged), then resolve any…, resolve_collision()

### Community 120 - "Diagnose — Retrospective"
Cohesion: 0.25
Nodes (7): 2026-07-07 — MLX on-device model benchmark (Qwen2.5-3B vs Llama-3.2-3B), 2026-07-14 — Converting the session-start checklist into a deterministic hook, 2026-07-17 — Brain-map reskin (dark gradient silently not rendering), 2026-07-17 — DesktopLive verification pass (post-Motion deploy), 2026-07-17 — Motion physics deploy to brain-map/DesktopLive (pulses, camera nudges, fitScale), 2026-08-26 — killer-sudoku full day (perf tuning + real bugs), Diagnose — Retrospective

### Community 121 - "bl"
Cohesion: 0.40
Nodes (4): bl(), Bs(), gs(), update()

## Knowledge Gaps
- **67 isolated node(s):** `Retrospective Log`, `Ways to construct one — try them in roughly this order`, `Iterate on the loop itself`, `Non-deterministic bugs`, `When you genuinely cannot build a loop` (+62 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **24 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `notify()` connect `Cross-Machine Code Sync` to `daily_digest.py`, `verify.py`?**
  _High betweenness centrality (0.010) - this node is a cross-community bridge._
- **Why does `scan()` connect `QA-Agent Code Scanner` to `SortedList`, `auto_fix.py`, `QA-Agent Capture`, `verify.py`?**
  _High betweenness centrality (0.010) - this node is a cross-community bridge._
- **Why does `machine_label()` connect `Cross-Machine Code Sync` to `verify.py`, `machine_profile.py`, `Machine Profile & Task Dispatch`, `sandbox_orchestration.py`, `ticket_claim.py`, `QA-Agent Capture`?**
  _High betweenness centrality (0.009) - this node is a cross-community bridge._
- **Are the 11 inferred relationships involving `e()` (e.g. with `ca()` and `dl()`) actually correct?**
  _`e()` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `n()` (e.g. with `er()` and `ha()`) actually correct?**
  _`n()` has 10 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Retrospective Log`, `Ways to construct one — try them in roughly this order`, `Iterate on the loop itself` to the rest of the system?**
  _67 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Network Reachability Checks` be split into smaller, more focused modules?**
  _Cohesion score 0.05126582278481013 - nodes in this community are weakly interconnected._