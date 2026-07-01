# Axiom Rift KPI Ledger Contract

schema: axiom_rift_kpi_ledger_contract_v1
status: seed_draft
encoding: ascii_only
audience: codex_only

## Purpose

Capture what each experiment should record in its KPI ledger.

This file is intentionally rough. It preserves the need for broad experiment observability before
later refinement into strict ledger schemas, report formats, dashboards, and promotion gates.

Simple metrics such as profit factor, PnL, and drawdown are not enough for Axiom Rift because
discovery may explore many labels, features, model structures, trade logics, filters, and runtime
surfaces.

## Ledger Role

Every experiment should have a KPI ledger that explains:

- what was tested
- where it was tested
- how much data and trade evidence it produced
- how it made or lost money
- whether the behavior was stable across time, folds, direction, session, and market regime
- whether the result is robust enough to investigate further
- why it was kept, rejected, or queued for refinement

## Experiment Identity KPIs

Record enough identity fields to make the experiment reproducible:

- experiment_id
- campaign_id
- run_id
- candidate_id
- created_at_utc
- dataset_identity
- split_policy
- fold_ids
- code_version_or_commit
- config_path
- artifact_paths
- artifact_hashes

## Data Coverage KPIs

Record whether the experiment had enough valid data:

- row_count
- date_start
- date_end
- fold_coverage
- missing_bar_count
- suspicious_gap_count
- external_symbol_count
- external_symbol_freshness_status
- rejected_external_symbol_count

## Trade Activity KPIs

Record whether trade activity matches the project objective:

- entry_count_total
- entry_count_per_active_day
- entry_count_by_month
- entry_count_by_fold
- long_entry_count
- short_entry_count
- no_trade_day_count
- average_bars_in_trade
- median_bars_in_trade
- exposure_percent

## Core Economics KPIs

Record core trading performance:

- gross_profit
- gross_loss
- net_pnl
- profit_factor
- expectancy_per_entry
- average_win
- average_loss
- win_rate
- payoff_ratio
- max_drawdown_percent
- monthly_max_drawdown_percent
- recovery_factor
- return_to_drawdown

## Trade Excursion KPIs

Record what happened inside each trade before exit:

- mfe_points
- mfe_money
- mfe_r_multiple
- mae_points
- mae_money
- mae_r_multiple
- final_pnl_vs_mfe_ratio
- giveback_from_mfe
- capture_ratio
- adverse_excursion_before_profit
- favorable_excursion_before_loss
- time_to_mfe_bars
- time_to_mae_bars
- exit_efficiency

MFE means maximum favorable excursion during an open trade. MAE means maximum adverse excursion
during an open trade. These fields help explain whether the entry, exit, stop, target, hold time,
or filter logic is the likely source of performance or failure.

## Average And Distribution KPIs

Record averages, but do not rely on averages alone. Pair average values with median and tail
distribution fields when possible.

Suggested average fields:

- avg_pnl_per_entry
- avg_pnl_per_winning_entry
- avg_pnl_per_losing_entry
- avg_entry_count_per_active_day
- avg_entry_count_per_month
- avg_bars_in_trade
- avg_mfe_points
- avg_mfe_money
- avg_mfe_r_multiple
- avg_mae_points
- avg_mae_money
- avg_mae_r_multiple
- avg_giveback_from_mfe
- avg_capture_ratio
- avg_time_to_mfe_bars
- avg_time_to_mae_bars
- avg_spread_at_entry
- avg_slippage_when_modeled

Suggested companion distribution fields:

- median_pnl_per_entry
- median_bars_in_trade
- median_mfe_points
- median_mae_points
- p10_pnl_per_entry
- p90_pnl_per_entry
- p90_mae_points
- p90_giveback_from_mfe
- worst_5pct_trade_pnl

Average fields are diagnostic. They must not replace fold, monthly, direction, and tail-risk
checks.

## Stability KPIs

Record whether the result survives slicing:

- fold_pnl_distribution
- fold_profit_factor_distribution
- fold_drawdown_distribution
- monthly_pnl_distribution
- monthly_win_rate
- losing_month_count
- worst_month_pnl
- worst_month_drawdown_percent
- best_month_dependency_ratio
- single_trade_dependency_ratio

## Direction And Logic KPIs

Record whether performance depends on one side or one behavior:

- long_pnl
- short_pnl
- long_profit_factor
- short_profit_factor
- long_drawdown_percent
- short_drawdown_percent
- entry_model_contribution
- exit_model_contribution
- filter_contribution
- threshold_sensitivity

## Cost And Execution KPIs

Record how sensitive the candidate is to realistic trading friction:

- baseline_spread_assumption
- spread_stress_result
- slippage_stress_result
- commission_assumption
- failed_under_spread_stress
- failed_under_slippage_stress

Commission assumption must remain consistent with the evaluation contract.

## Model And Signal KPIs

When a model or score surface exists, record diagnostic behavior:

- score_distribution
- signal_count
- signal_to_entry_conversion_rate
- calibration_summary
- probability_bucket_performance
- feature_count
- feature_family_summary
- feature_importance_summary_when_available
- label_horizon
- label_balance
- train_validation_gap
- overfit_warning_flags

These diagnostics do not create model-selection authority by themselves.

## Runtime Reproducibility KPIs

Record whether the candidate can plausibly be materialized:

- python_to_runtime_feature_match_status
- onnx_export_status
- ea_integration_status
- mt5_tester_status
- runtime_data_availability_status
- mismatch_count
- known_runtime_blockers

These fields are diagnostic only until runtime-validation contracts define pass/fail gates.

## Decision KPIs

Record the interpretation of the run:

- keep_reject_status
- primary_failure_reason
- secondary_failure_reasons
- next_action
- promotion_candidate: false
- claim_authority: false

No KPI ledger row may claim winner, frozen selection, runtime authority, or live readiness without
the required downstream evidence and explicit claim-boundary update.

## Suggested Ledger Shape

The durable ledger should be machine-readable.

Allowed seed formats:

- CSV for flat summaries
- JSONL for per-run or per-fold events
- YAML for campaign-level selected summaries

Candidate future paths:

- campaigns/<campaign_id>/runs/<run_id>/kpi_summary.json
- campaigns/<campaign_id>/runs/<run_id>/kpi_by_fold.csv
- campaigns/<campaign_id>/runs/<run_id>/kpi_by_month.csv
- registries/alpha_run_ledger.csv

Exact paths are not frozen in this seed draft.

## Claim Boundary

This contract does not claim:

- kpi_schema_frozen: true
- evaluation_gate_frozen: true
- candidate_selected: true
- economics_pass: true
- runtime_authority: true
- live_ready: true

This seed preserves KPI management intent only.

## Refinement Needed

Later refinement should define:

- required ledger columns
- optional ledger columns by experiment type
- per-fold ledger schema
- per-month ledger schema
- pass/fail threshold mapping
- KPI dashboard summary shape
- promotion review packet shape
- how KPI rows connect to artifact hashes
