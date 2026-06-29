# Stage 0

schema: axiom_rift_stage_brief_v1
stage_id: 00_reentry__clean_market_data_baseline
status: open
audience: codex_only
encoding: ascii_only

question:
  primary: rebuild_clean_us100_m5_research_base
  secondary: start_without_preselected_label_or_feature_set

scope:
  - inventory_available_raw_mt5_m5_bars
  - inventory_available_us100_real_ticks
  - decide_raw_data_link_copy_or_fresh_export
  - rebuild_us100_m5_base_frame
  - record_fpmarkets_v2_label_and_feature_set_as_archive_refs_only
  - draft_active_axiom_contract_plan

out_of_scope:
  - model_training
  - label_freeze
  - feature_set_freeze
  - baseline_selection
  - mt5_runtime_authority
  - operating_promotion
  - live_readiness

completion_evidence:
  - data_inventory_report
  - source_path_decision_record
  - us100_m5_coverage_summary
  - no_label_or_feature_set_selected_note
  - active_axiom_contract_draft_plan
  - known_gaps
  - next_stage_recommendation
