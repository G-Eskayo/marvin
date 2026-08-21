# Graph Report - .agents  (2026-08-21)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 1677 nodes · 3114 edges · 108 communities (89 shown, 19 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 113 edges (avg confidence: 0.85)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c4890594`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 36
- Community 37
- Community 38
- Community 39
- Community 40
- Community 41
- Community 42
- Community 43
- Community 44
- Community 45
- Community 46
- Community 47
- Community 48
- Community 49
- Community 50
- Community 51
- Community 52
- Community 53
- Community 54
- Community 55
- Community 56
- Community 57
- Community 58
- Community 59
- Community 60
- Community 61
- Community 62
- Community 63
- Community 64
- Community 65
- Community 66
- Community 67
- Community 68
- Community 69
- Community 70
- Community 71
- Community 72
- Community 73
- Community 74
- Community 75
- Community 76
- Community 77
- Community 78
- Community 79
- Community 80
- Community 81
- Community 82
- Community 84
- Community 85
- Community 86
- Community 87
- Community 88
- Community 89
- Community 90
- Community 91
- Community 92
- Community 96
- Community 100
- Community 101
- Community 103
- Community 104
- Community 105
- Community 106
- Community 107

## God Nodes (most connected - your core abstractions)
1. `co()` - 35 edges
2. `e()` - 31 edges
3. `n()` - 30 edges
4. `fn()` - 25 edges
5. `en` - 24 edges
6. `oo()` - 21 edges
7. `ke` - 20 edges
8. `_metric()` - 20 edges
9. `vl()` - 20 edges
10. `yi()` - 20 edges

## Surprising Connections (you probably didn't know these)
- `main()` --calls--> `log_hook_error()`  [INFERRED]
  brain-map/scripts/skill_activity.py → lib/hook_errors.py
- `main()` --calls--> `log_hook_error()`  [INFERRED]
  skills/improve/scripts/improvement_sweep.py → lib/hook_errors.py
- `main()` --calls--> `log_hook_error()`  [INFERRED]
  skills/self-improve/scripts/background_review.py → lib/hook_errors.py
- `process_and_check_quarantine()` --calls--> `process()`  [INFERRED]
  lib/session_start_report.py → skills/safety-monitor/scripts/process_quarantine_reviews.py
- `main()` --calls--> `registry_id()`  [INFERRED]
  skills/improve/scripts/cross_machine_merge.py → lib/machine_profile.py

## Import Cycles
- None detected.

## Communities (108 total, 19 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (73): _arp_mac(), check_and_record(), check_domain(), current_network_id(), _default_gateway(), known_status(), _load_store(), main() (+65 more)

### Community 1 - "Community 1"
Cohesion: 0.04
Nodes (41): be(), bl(), Bs(), c(), Dr(), ec(), Et(), fa() (+33 more)

### Community 2 - "Community 2"
Cohesion: 0.07
Nodes (53): BaseException, main(), log_hook_error(), Shared failure logger for PostToolUse hooks. Hooks intentionally swallow…, check_auto_fix_log(), check_cron_health(), check_daily_digest(), _check_digest() (+45 more)

### Community 3 - "Community 3"
Cohesion: 0.06
Nodes (33): _default_list_worktrees(), _default_remove_worktree(), _extract_issue_number(), find_orphaned_worktrees(), find_stale_claims(), datetime, Path, Cron entry point. Runs both sweeps, logs what was removed/released (same… (+25 more)

### Community 4 - "Community 4"
Cohesion: 0.32
Nodes (15): _files_with_conflict_markers(), _git(), _git_ok(), _log(), main(), _merge_remote(), pull(), push() (+7 more)

### Community 5 - "Community 5"
Cohesion: 0.07
Nodes (26): ai(), animateVisualElement(), dn(), fi(), fn(), Fs(), gi(), Is() (+18 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (37): append_to_queue(), extract_project(), find_project_path(), format_issue(), main(), Path, Returns True if the block was appended, False if safety-monitor quarantined it…, top_issues() (+29 more)

### Community 7 - "Community 7"
Cohesion: 0.07
Nodes (43): aggregate_runs(), _check_quota(), _fmt_multi(), _fmt_single(), fmt_table(), _is_infra_error(), judge_run(), _load_marvin_context() (+35 more)

### Community 8 - "Community 8"
Cohesion: 0.07
Nodes (10): ba(), co(), ei(), Eo(), hi(), So(), update(), vr() (+2 more)

### Community 9 - "Community 9"
Cohesion: 0.08
Nodes (22): ArgumentParser, _classify_row(), run_ambiguous(), run_clean(), Genuinely held-out validation fixture v3 for route.py's embedding classifier…, run(), Tests for route.py's --embed flag and keyword-classifier fallback. Run via:…, Namespace (+14 more)

### Community 10 - "Community 10"
Cohesion: 0.10
Nodes (27): compare(), _direction(), index(), latest(), _load_snapshots(), _narrative_path(), Path, Recompute, from every per-subsystem JSON file, a subsystem -> latest metrics… (+19 more)

### Community 11 - "Community 11"
Cohesion: 0.14
Nodes (27): build_argument_map(), enrich_missing_titles(), extract_core_claim(), fetch_title(), main(), ollama_chat(), _openalex_work_id(), OpenAlex's /works/{id} path accepts either its own W-prefixed id (already a… (+19 more)

### Community 12 - "Community 12"
Cohesion: 0.11
Nodes (17): Any, Bool, AppDelegate, DesktopWebView, Cocoa, Date, Notification, NSApplicationDelegate (+9 more)

### Community 13 - "Community 13"
Cohesion: 0.11
Nodes (13): Ao(), ar(), At(), bi(), In(), Je(), Li(), lr() (+5 more)

### Community 14 - "Community 14"
Cohesion: 0.10
Nodes (19): ca(), ci(), cr, e(), er(), Gr(), ha(), Ie() (+11 more)

### Community 15 - "Community 15"
Cohesion: 0.12
Nodes (22): judge_all(), judge_extraction(), Judges a type-adaptive extraction (from extract_structure) against its type-…, papers: {slug: (extraction_dict, paper_type)}. Returns {slug: findings_list}., render_markdown(), Tests for logic_auditor.py. Run via: ~/.agents/venv/bin/python -m pytest…, test_judge_all_handles_empty_input(), test_judge_all_judges_each_paper_by_its_own_type() (+14 more)

### Community 16 - "Community 16"
Cohesion: 0.11
Nodes (14): build_collection(), classify(), embed_text(), _get_collection(), main(), Embed via Ollama nomic-embed-text. task='query' for classify() input,…, (Re)embed every reference example into the intent-routing collection. Uses…, Return {"status": "ok"|"no_match"|"unavailable", "intent": str|None, "score":… (+6 more)

### Community 17 - "Community 17"
Cohesion: 0.14
Nodes (23): _metric(), metrics_dir(), fixture, Tests for metrics_registry.py. Run via: ~/.agents/venv/bin/python -m pytest…, test_compare_all_improved_or_unchanged_is_passing(), test_compare_all_unchanged_is_not_passing(), test_compare_detects_improvement_higher_is_better(), test_compare_detects_improvement_lower_is_better() (+15 more)

### Community 18 - "Community 18"
Cohesion: 0.25
Nodes (25): build_embeddings(), clone_resume_tailor(), configure_claude(), configure_hook(), deploy_brain_map(), deploy_retrospective_log(), detect_gpu(), detect_os() (+17 more)

### Community 20 - "Community 20"
Cohesion: 0.17
Nodes (22): _load_registry(), This machine's stable id in marvin-network.json, resolved by matching hardware…, All registered devices that aren't this one, keyed by device id., registry_id(), remote_devices(), _build_wrapper_script(), _candidates(), dispatch() (+14 more)

### Community 21 - "Community 21"
Cohesion: 0.12
Nodes (13): _already_fired(), classify(), main(), _mark_fired(), Return the routing message for prompt, or None to stay silent (architecture/no-…, _resolve_intent(), Tests for auto_route_hook.py. Run via: ~/.agents/venv/bin/python -m pytest…, _run_main() (+5 more)

### Community 22 - "Community 22"
Cohesion: 0.19
Nodes (22): build_agent_children(), build_device_children(), build_hook_children(), build_skill_node(), build_synapses(), build_tree(), collect_ids(), discover_devices() (+14 more)

### Community 23 - "Community 23"
Cohesion: 0.19
Nodes (22): analyze_python_file(), Return complexity/principles issues for a single .py file., make_project(), Path, Tests for qa-agent scripts. Run via: ~/.agents/venv/bin/python -m pytest…, test_clean_function_no_flags(), test_detect_stack_javascript(), test_detect_stack_multi() (+14 more)

### Community 24 - "Community 24"
Cohesion: 0.13
Nodes (17): Al(), cl(), dl(), Es(), fl(), gl(), hl(), j() (+9 more)

### Community 25 - "Community 25"
Cohesion: 0.15
Nodes (3): Cn, ke, zt()

### Community 26 - "Community 26"
Cohesion: 0.19
Nodes (20): analyze_comment_quality(), analyze_complexity(), analyze_quality(), detect_stack(), extract_dependencies(), extract_imports(), extract_markers(), infer_domain() (+12 more)

### Community 27 - "Community 27"
Cohesion: 0.11
Nodes (9): bo(), br(), Go(), jn(), $r(), ur, vo(), xo() (+1 more)

### Community 28 - "Community 28"
Cohesion: 0.16
Nodes (15): _iso(), _issue(), log_path(), fixture, Tests for cleanup_sweep.py. Run via: ~/.agents/venv/bin/python -m pytest…, test_does_not_flag_claim_under_threshold(), test_does_not_flag_worktree_with_active_claim(), test_does_not_remove_worktree_with_active_claim() (+7 more)

### Community 29 - "Community 29"
Cohesion: 0.17
Nodes (18): build_entry(), infer_pattern_type(), main(), Return True if new, False if already existed (dedup by id)., Return best-guess pattern_type from document content and tags., store_entry(), extract_decisions(), extract_outcome() (+10 more)

### Community 30 - "Community 30"
Cohesion: 0.13
Nodes (13): de(), fe(), ge(), Gt(), Ht(), le(), Ls(), me() (+5 more)

### Community 31 - "Community 31"
Cohesion: 0.17
Nodes (16): _failing_result(), _passing_result(), fixture, Tests for mr_raiser.py. Run via: ~/.agents/venv/bin/python -m pytest…, A bare 'origin' remote, a main-repo clone with one commit, and a worktree…, repo_with_worktree(), _run(), test_comment_on_ticket_called_with_ticket_and_pr_url() (+8 more)

### Community 32 - "Community 32"
Cohesion: 0.15
Nodes (6): _analyze_function_body(), ComplexityVisitor, QualityVisitor, Single-pass structural read of a function: cyclomatic complexity + concern…, Walk an AST and collect complexity signals., Detect verbosity, naming, and logic anti-patterns via AST.

### Community 33 - "Community 33"
Cohesion: 0.17
Nodes (13): decode(), DecodedEvent, datetime, Event decoder — deserialises events from the internal JSON wire format., Parse a raw JSON event string and return a DecodedEvent. Raises ValueError on…, encode(), Event encoder — serialises events to the internal JSON wire format., Return a JSON string representing a single event. Version 2 wire format: {… (+5 more)

### Community 34 - "Community 34"
Cohesion: 0.13
Nodes (5): _FakeCompleted, Tests for network_reachability.py. Run via: ~/.agents/venv/bin/python -m pytest…, test_arp_mac_parses_non_zero_padded_octets(), test_arp_mac_parses_zero_padded_octets(), test_arp_mac_returns_none_when_no_entry()

### Community 35 - "Community 35"
Cohesion: 0.14
Nodes (7): _issue(), Tests for ticket_claim.py. Run via: ~/.agents/venv/bin/python -m pytest…, test_cap_is_exactly_three(), test_claims_lowest_issue_number_first(), test_claims_nothing_when_at_cap(), test_claims_when_under_cap(), test_count_claimed_only_counts_this_machines_claims()

### Community 36 - "Community 36"
Cohesion: 0.16
Nodes (16): adopt(), As(), collectTargets(), constructor(), finalize(), getRoot(), il(), ms() (+8 more)

### Community 37 - "Community 37"
Cohesion: 0.18
Nodes (16): _archive_previous_latest(), check_job(), check_organize_sync(), check_repo_convergence(), check_repo_integrity(), _load_state(), main(), _new_content() (+8 more)

### Community 38 - "Community 38"
Cohesion: 0.15
Nodes (10): _promoting_evaluator(), Tests for ticket_promotion.py. Run via: ~/.agents/venv/bin/python -m pytest…, _skipping_evaluator(), test_creates_ticket_when_evaluator_says_promote(), test_no_manual_approval_step_runs_synchronously_to_completion(), test_reasoning_captured_in_result_and_passed_to_ticket_creator(), test_reasoning_present_even_when_not_promoted(), test_skips_ticket_creation_when_evaluator_says_dont_promote() (+2 more)

### Community 39 - "Community 39"
Cohesion: 0.17
Nodes (7): $a(), ga, Ll(), ol(), reconcileRemovals(), Rr(), ys()

### Community 40 - "Community 40"
Cohesion: 0.24
Nodes (15): build_merged(), load_sync_state(), main(), profile_blurb(), Path, Identical shape to sync_qa_knowledge -- same deterministic-set-union- by-id…, Returns stdout on success, None on any failure (unreachable, non-zero exit,…, run_merge_authority() (+7 more)

### Community 41 - "Community 41"
Cohesion: 0.14
Nodes (15): check_inference_validity(), check_inference_validity_all(), _level_from_finding_count(), ollama_chat(), Symbolizes the paper's key inferential move and checks the argument's FORM --…, papers: {slug: (title, abstract)}. Returns {slug: inference_check_dict}., _worse_of(), test_check_inference_validity_all_handles_empty_input() (+7 more)

### Community 42 - "Community 42"
Cohesion: 0.25
Nodes (13): _chromium_executable(), cmd_click(), cmd_fill(), cmd_html(), cmd_navigate(), cmd_screenshot(), cmd_start(), cmd_status() (+5 more)

### Community 43 - "Community 43"
Cohesion: 0.17
Nodes (7): LRUCache, LRU cache for expensive database queries. Evicts the least-recently-used entry…, fetch_user_report(), Database access layer. Uses LRUCache to avoid hitting the DB on every call., Simulate an expensive DB query (real implementation would hit the DB)., Return the cached report for (user_id, report_type), hitting the DB if needed., _run_query()

### Community 45 - "Community 45"
Cohesion: 0.19
Nodes (9): Returns (summed_logprob, is_greedy) for `continuation` given `context`, using…, score_continuation(), model_and_tokenizer(), fixture, Tests for the in-process MLX loglikelihood adapter. Run via:…, Cross-checks score_continuation's single batched forward pass against a…, test_is_greedy_true_for_actual_argmax_continuation_false_otherwise(), test_logit_slicing_matches_independent_step_by_step_computation() (+1 more)

### Community 47 - "Community 47"
Cohesion: 0.14
Nodes (14): classify_all(), classify_paper_type(), Returns one of PAPER_TYPES, or "unknown" if the response can't be parsed into…, papers: {slug: (title, abstract)}. Returns {slug: type}., test_classify_all_classifies_every_paper_in_the_input_dict(), test_classify_all_handles_empty_input(), test_classify_paper_type_extracts_label_from_extra_prose(), test_classify_paper_type_falls_back_to_unknown_on_unparseable_response() (+6 more)

### Community 48 - "Community 48"
Cohesion: 0.15
Nodes (5): A sorted list that maintains elements in ascending order with O(log n)…, Insert value maintaining sorted order., Return True if value is present., Remove the first occurrence of value. Does nothing if value is absent., SortedList

### Community 49 - "Community 49"
Cohesion: 0.32
Nodes (12): backup_files(), build_prompt(), _core_files(), get_candidates(), log_run(), main(), Path, Fresh qa_scan.py pass (via its importable scan() function, same as… (+4 more)

### Community 50 - "Community 50"
Cohesion: 0.15
Nodes (13): compute_reliability_signal(), layer1_findings: from judge_extraction. layer2_result: from…, test_deductive_invalid_adds_its_own_finding(), test_deductive_invalid_does_not_improve_an_already_worse_paper(), test_deductive_invalid_floors_a_clean_paper_to_low_not_high(), test_deductive_valid_does_not_floor_or_add_a_finding(), test_four_or_more_findings_is_very_low(), test_inductive_weak_adds_a_finding_but_does_not_hard_floor() (+5 more)

### Community 52 - "Community 52"
Cohesion: 0.21
Nodes (12): build_audit_report(), needs_second_look(), Assembles the full per-paper audit -- type, both layers' visible extraction,…, _sample_report_inputs(), test_build_audit_report_entry_has_all_expected_fields(), test_build_audit_report_flags_low_reliability_papers(), test_build_audit_report_handles_empty_slug_list(), test_build_audit_report_includes_one_entry_per_slug_in_given_order() (+4 more)

### Community 53 - "Community 53"
Cohesion: 0.17
Nodes (12): extract_all(), extract_structure(), Extracts the type-appropriate structure as a reviewable intermediate artifact…, papers: {slug: (title, abstract, paper_type)}. Returns {slug: extraction_dict}., test_extract_all_handles_empty_input(), test_extract_all_routes_each_paper_by_its_own_type(), test_extract_structure_benchmark_uses_construct_validity_fields(), test_extract_structure_conceptual_uses_structural_claim_fields() (+4 more)

### Community 54 - "Community 54"
Cohesion: 0.26
Nodes (8): correlate(), roadmap_match(), fetch_arxiv(), fetch_github(), fetch_hackernews(), main(), save_raw_cache(), store_items()

### Community 55 - "Community 55"
Cohesion: 0.26
Nodes (11): _annotate_sections(), _build_fit_ladder(), _content_fill_ratio(), _make_fit_step(), md_to_html(), _override_css(), Wrap the header cluster (name + short metadata lines) in CSS-hookable…, Give Projects entries and Experience role headers a distinct visual weight from… (+3 more)

### Community 56 - "Community 56"
Cohesion: 0.18
Nodes (5): LRUCache, LRU (Least Recently Used) cache with a fixed capacity. Items are evicted in…, Return the cached value for key, or None if not present., Insert or update key. Evicts the LRU item if over capacity., Fixed-capacity LRU cache. Access order is maintained by the underlying…

### Community 57 - "Community 57"
Cohesion: 0.27
Nodes (9): main(), print_human(), Infer the problem's own domain (unless given), then fetch top-N transferable…, synthesize(), filter_results(), main(), query_kb(), test_filter_results_by_category() (+1 more)

### Community 58 - "Community 58"
Cohesion: 0.29
Nodes (10): bench_summary(), improvement_queue_summary(), main(), qa_kb_summary(), Computed directly from the log, not via an LLM guess at "does this look…, launchd's environment doesn't source .zshrc/.zprofile, so PATH may not include…, recent_handoffs_summary(), _resolve_claude_bin() (+2 more)

### Community 59 - "Community 59"
Cohesion: 0.35
Nodes (10): bm25_rerank(), embed_query(), _entry_tag_words(), get_threshold(), main(), _query_collection(), retrieve(), rrf_merge() (+2 more)

### Community 60 - "Community 60"
Cohesion: 0.29
Nodes (9): get_conn(), get_stock(), Inventory reservation system for a high-throughput e-commerce checkout service., Reserve `quantity` units of item_id. Returns True if the reservation succeeded., Return `quantity` units to inventory (e.g. on order cancellation)., release_item(), reserve_item(), setup_db() (+1 more)

### Community 61 - "Community 61"
Cohesion: 0.40
Nodes (9): build_profile(), _claude_install_method(), _hardware_uuid(), _label(), load_or_build(), _mobility_class(), Read the cached profile if fresh enough, else regenerate., _run() (+1 more)

### Community 62 - "Community 62"
Cohesion: 0.44
Nodes (9): arxiv_search(), fmt_paper(), get_requests(), main(), rank_papers(), recency_score(), s2_paper_by_doi(), s2_recommendations() (+1 more)

### Community 63 - "Community 63"
Cohesion: 0.36
Nodes (9): build_doc_text(), collection_for(), content_hash(), embed(), main(), Upsert changed entries and prune deleted ones. Returns (embedded, skipped,…, resolve_path(), strip_frontmatter() (+1 more)

### Community 64 - "Community 64"
Cohesion: 0.25
Nodes (4): Ae(), sn(), vn(), xn

### Community 65 - "Community 65"
Cohesion: 0.47
Nodes (8): extract_pdf(), extract_url(), main(), parse_metadata(), Path, Best-effort extraction of title, authors, DOI from raw text., save_session(), slugify()

### Community 66 - "Community 66"
Cohesion: 0.22
Nodes (9): _parse_findings(), qwen2.5:3b doesn't reliably put one FINDING per line -- seen live 2026-07-13…, test_parse_findings_extracts_each_finding_line(), test_parse_findings_filters_out_stray_none_captured_as_a_finding(), test_parse_findings_ignores_preamble_before_the_first_marker(), test_parse_findings_returns_empty_list_for_blank_response(), test_parse_findings_returns_empty_list_for_none_response(), test_parse_findings_splits_multiple_findings_crammed_onto_one_line() (+1 more)

### Community 68 - "Community 68"
Cohesion: 0.48
Nodes (6): _check_remote(), _load_state(), main(), Path, _save_state(), _surface_resume_prompt()

### Community 69 - "Community 69"
Cohesion: 0.52
Nodes (6): extract_recent_excerpt(), _extract_text(), main(), Path, Dispatched here via task_dispatch.py's plain-bash wrapper script over SSH — a…, _resolve_claude_bin()

### Community 70 - "Community 70"
Cohesion: 0.57
Nodes (6): file_at_commit(), is_append_only_extension(), main(), Path, True if `newer` == `older` + zero or more new lines at the end, with every line…, run_git()

### Community 71 - "Community 71"
Cohesion: 0.60
Nodes (5): check_content(), main(), Path, ssh_cat(), tail_log()

### Community 72 - "Community 72"
Cohesion: 0.33
Nodes (6): _parse_fields(), Parses a "FIELD: value" formatted response into {lowercase_field: value},…, test_parse_fields_accumulates_multiline_values_until_next_field(), test_parse_fields_extracts_single_line_values(), test_parse_fields_is_case_insensitive_on_labels(), test_parse_fields_missing_field_is_absent_not_empty_string()

### Community 73 - "Community 73"
Cohesion: 0.47
Nodes (5): insert_tags(), main(), patch_file(), Path, Insert tags (and calls) into YAML frontmatter before the closing ---.

### Community 74 - "Community 74"
Cohesion: 0.40
Nodes (4): add_order(), add_user(), Add an order for an existing user. Raises ValueError if user not found., Add a new user. Raises ValueError if email already registered.

### Community 75 - "Community 75"
Cohesion: 0.70
Nodes (4): append(), main(), pulse(), Path

### Community 76 - "Community 76"
Cohesion: 0.80
Nodes (4): extract(), _extract_docx(), _extract_pdf(), Path

### Community 77 - "Community 77"
Cohesion: 0.67
Nodes (3): build_events(), main(), (step_index, kind, arg) — spread across the loop by fraction, twice.

### Community 78 - "Community 78"
Cohesion: 0.83
Nodes (3): build_segment_b_events(), capture_loop(), main()

### Community 79 - "Community 79"
Cohesion: 0.83
Nodes (3): _sort_key(), sort_suggestions(), _split_entries()

### Community 80 - "Community 80"
Cohesion: 0.67
Nodes (3): main(), SSH's non-interactive shell doesn't source .zshrc/.zprofile, so PATH may not…, _resolve_claude_bin()

### Community 81 - "Community 81"
Cohesion: 0.50
Nodes (4): compute_all_reliability_signals(), layer1_findings: {slug: findings_list} from judge_all. layer2_results: {slug:…, test_compute_all_reliability_signals_combines_per_paper(), test_compute_all_reliability_signals_handles_empty_input()

### Community 89 - "Community 89"
Cohesion: 0.67
Nodes (3): Call, _call_root_name(), First identifier of a call chain: requests.get(...) -> 'requests'.

### Community 103 - "Community 103"
Cohesion: 0.25
Nodes (9): notify_mr_ready(), Fire both notification channels for a newly-raised MR. Never raises -- a…, _commit_and_push(), _current_branch(), _default_open_pr(), _format_comparison(), Path, raise_mr() (+1 more)

### Community 104 - "Community 104"
Cohesion: 0.31
Nodes (6): _applescript_quote(), notify(), AppleScript double-quoted string escaping — Python's repr() uses Python syntax,…, terminal-notifier's -open wants a URL; accept a local path too., Fire a macOS notification. If open_target (a URL or local file path) is given…, _to_open_url()

### Community 106 - "Community 106"
Cohesion: 0.43
Nodes (7): _fmt_item(), generate(), load_correlated_from_chroma(), load_today_cache(), Path, launchd's environment doesn't source .zshrc/.zprofile, so PATH may not include…, _resolve_claude_bin()

## Knowledge Gaps
- **5 isolated node(s):** `install.sh script`, `install.sh script`, `Cocoa`, `WebKit`, `install.sh script`
  These have ≤1 connection - possible missing edges or undocumented components.
- **19 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `notify()` connect `Community 104` to `Community 58`, `Community 4`, `Community 106`, `Community 103`?**
  _High betweenness centrality (0.015) - this node is a cross-community bridge._
- **Why does `scan()` connect `Community 26` to `Community 48`, `Community 49`, `Community 29`, `Community 6`?**
  _High betweenness centrality (0.013) - this node is a cross-community bridge._
- **Why does `machine_label()` connect `Community 4` to `Community 3`, `Community 61`, `Community 20`, `Community 54`, `Community 29`?**
  _High betweenness centrality (0.011) - this node is a cross-community bridge._
- **Are the 11 inferred relationships involving `e()` (e.g. with `ca()` and `dl()`) actually correct?**
  _`e()` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `n()` (e.g. with `er()` and `ha()`) actually correct?**
  _`n()` has 10 INFERRED edges - model-reasoned connections that need verification._
- **What connects `install.sh script`, `install.sh script`, `Cocoa` to the rest of the system?**
  _5 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.05126582278481013 - nodes in this community are weakly interconnected._