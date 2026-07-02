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

## KPI Requirement Policy

Axiom KPI fields use three requirement classes:

- required
- conditional_required
- deferred_with_reason

Do not use `optional` as a silent omission class.

`required` fields must be present for every run closeout.

`conditional_required` fields must be present when their condition applies to the run surface,
available evidence, or selected KPI profile.

`deferred_with_reason` is allowed only when a field cannot be produced in the current run. The
defer record must name the field, reason, blocking condition, and revisit trigger.

Required defer fields:

- field
- requirement_class
- reason
- blocking_condition
- revisit_when
- claim_boundary

Allowed requirement classes:

- required
- conditional_required
- deferred_with_reason

Run closeout must not treat an unrecorded conditional field as passed, not applicable, or optional.

## Required KPI Baseline

Every completed run must record these baseline fields across the three KPI families:

- work_unit_id
- campaign_id
- synthesis_id_when_applicable
- run_id
- dataset_identity
- split_policy
- fold_ids
- proxy_id
- mt5_probe_id
- proxy_trade_count
- mt5_trade_count
- proxy_net_pnl
- mt5_net_pnl
- proxy_profit_factor
- mt5_profit_factor
- proxy_max_drawdown_percent
- mt5_max_drawdown_percent
- proxy_win_rate
- mt5_win_rate
- trade_count_delta
- mechanical_parity_status
- intent_parity_status
- mismatch_count
- mismatch_summary
- repair_required
- next_action
- evidence_paths
- proxy_artifact_hashes
- mt5_report_hashes
- deferred_with_reason
- claim_authority: false

## Conditional KPI Profiles

Use KPI profiles to make extra diagnostics mandatory when they apply.

`score_surface_profile` applies when the run has model scores, probabilities, or ranked signals.
Required when applicable:

- score_distribution
- signal_count
- signal_to_entry_conversion_rate
- calibration_summary_when_probability_like
- probability_bucket_performance_when_probability_like

`trade_excursion_profile` applies when trade path or excursion data is available from proxy or MT5.
Required when applicable:

- mfe_summary
- mae_summary
- final_pnl_vs_mfe_summary
- giveback_from_mfe_summary
- capture_ratio_summary

`direction_profile` applies when long and short behavior can differ or is part of the hypothesis.
Required when applicable:

- long_pnl
- short_pnl
- long_profit_factor
- short_profit_factor
- long_drawdown_percent
- short_drawdown_percent

`stability_profile` applies when fold or month slicing exists for the run.
Required when applicable:

- fold_pnl_distribution
- fold_profit_factor_distribution
- fold_drawdown_distribution
- monthly_pnl_distribution
- losing_month_count
- worst_month_pnl

`cost_execution_profile` applies when spread, slippage, commission, or execution realism is in
scope.
Required when applicable:

- baseline_spread_assumption
- spread_stress_result
- slippage_stress_result
- commission_assumption
- execution_cost_summary

`runtime_reproducibility_profile` applies when runtime portability, EA handoff, ONNX export, or MT5
materialization is in scope.
Required when applicable:

- python_to_runtime_feature_match_status
- onnx_export_status
- ea_integration_status
- mt5_tester_status
- runtime_data_availability_status
- known_runtime_blockers

## Run KPI Families

Each run should manage KPI evidence in explicit non-overwriting families:

- proxy
- mt5_logic_parity
- mt5_tick
- proxy_vs_mt5_logic_parity
- execution_divergence

These families must not overwrite each other.

`proxy` records what the Axiom proxy observed before MT5 probing.

`mt5_logic_parity` records closed-bar MT5 evidence for proxy-vs-EA logic parity.

`mt5_tick` records tick-mode MT5 execution KPI evidence.

`proxy_vs_mt5_logic_parity` records comparison and parity evidence between the proxy and closed-bar MT5 surfaces.

`execution_divergence` records the gap between closed-bar logic behavior and tick execution behavior.

The default run-level layout is:

- campaigns/<work_unit_id>/runs/<run_id>/kpi/proxy.json
- campaigns/<work_unit_id>/runs/<run_id>/kpi/mt5_logic_parity.json
- campaigns/<work_unit_id>/runs/<run_id>/kpi/mt5_tick.json
- campaigns/<work_unit_id>/runs/<run_id>/kpi/proxy_vs_mt5_logic_parity.json
- campaigns/<work_unit_id>/runs/<run_id>/kpi/execution_divergence.json

`work_unit_id` may be a campaign id such as `C0001` or a synthesis id such as `SC0001`.
Campaign runs use `R0001` style ids. Synthesis runs may use `SR0001` style ids.

Conditional breakdown files may sit beside the three summaries when their profile applies:

- campaigns/<work_unit_id>/runs/<run_id>/kpi/proxy_by_fold.csv
- campaigns/<work_unit_id>/runs/<run_id>/kpi/proxy_by_month.csv
- campaigns/<work_unit_id>/runs/<run_id>/kpi/mt5_by_period.csv
- campaigns/<work_unit_id>/runs/<run_id>/kpi/proxy_vs_mt5_trade_match.csv

The KPI families are evidence records only. They do not create selected model, selected
feature set, selected label, runtime authority, economics pass, or live readiness claims.

## Proxy KPI Family

The proxy KPI family records proxy-side evidence:

- campaign_id
- run_id
- proxy_id
- proxy_config_path
- dataset_identity
- split_policy
- fold_ids
- proxy_engine
- proxy_code_version_or_commit
- proxy_artifact_paths
- proxy_artifact_hashes
- proxy_trade_count
- proxy_signal_count
- proxy_entry_count_by_fold
- proxy_entry_count_by_month
- proxy_net_pnl
- proxy_profit_factor
- proxy_max_drawdown_percent
- proxy_expectancy_per_entry
- proxy_win_rate
- proxy_mfe_summary
- proxy_mae_summary
- proxy_stability_summary
- proxy_failure_flags
- proxy_gate_status
- deferred_with_reason

## MT5 KPI Family

The MT5 KPI family records MT5 probe-attempt evidence:

- campaign_id
- run_id
- mt5_probe_id
- mt5_terminal_identity
- mt5_symbol
- mt5_timeframe
- mt5_tester_model
- mt5_date_start
- mt5_date_end
- mt5_report_paths
- mt5_report_hashes
- mt5_trade_count
- mt5_net_pnl
- mt5_profit_factor
- mt5_max_drawdown_percent
- mt5_expectancy_per_entry
- mt5_win_rate
- mt5_mfe_summary_when_available
- mt5_mae_summary_when_available
- mt5_execution_cost_summary
- mt5_probe_status
- mt5_known_blockers
- deferred_with_reason

MT5 KPI records in this contract are probe-attempt evidence only. They must not be used as
runtime authority without the downstream runtime contract requirements.

## Proxy Vs MT5 Logic Parity KPI Family

The proxy_vs_mt5_logic_parity KPI family records closed-bar comparison and parity evidence:

- campaign_id
- run_id
- parity_id
- proxy_id
- mt5_probe_id
- compared_period
- trade_count_delta
- entry_time_match_rate
- entry_price_delta_summary
- exit_time_match_rate
- exit_price_delta_summary
- exit_reason_match_rate
- sl_tp_point_unit_match
- bid_ask_mid_basis_match
- closed_bar_timestamp_match
- spread_slippage_semantics_match
- entry_exit_order_match
- position_lifecycle_match
- mechanical_parity_status
- intent_parity_status
- mismatch_count
- mismatch_summary
- repair_required
- repair_type
- next_action
- deferred_with_reason

Mechanical mismatch fields explain whether proxy and MT5 executed the same rules with the same
meaning. Intent mismatch fields explain whether MT5 behavior matched the original run hypothesis.

## Experiment Identity KPIs

Record enough identity fields to make the experiment reproducible:

- experiment_id
- work_unit_id
- campaign_id
- synthesis_id_when_applicable
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

When runtime portability or materialization is in scope, these fields are conditional_required, not
optional. They still do not create runtime authority by themselves.

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

Default run-level KPI summary paths:

- campaigns/<work_unit_id>/runs/<run_id>/kpi/proxy.json
- campaigns/<work_unit_id>/runs/<run_id>/kpi/mt5_logic_parity.json
- campaigns/<work_unit_id>/runs/<run_id>/kpi/mt5_tick.json
- campaigns/<work_unit_id>/runs/<run_id>/kpi/proxy_vs_mt5_logic_parity.json
- campaigns/<work_unit_id>/runs/<run_id>/kpi/execution_divergence.json

Conditional index paths:

- registries/run_kpi_index.csv
- registries/run_kpi_index.jsonl

Registry rows are indexes only. The run-level KPI files remain the evidence surface.

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
- conditional required ledger columns by experiment type
- per-fold ledger schema
- per-month ledger schema
- pass/fail threshold mapping
- KPI dashboard summary shape
- promotion review packet shape
- how KPI rows connect to artifact hashes
