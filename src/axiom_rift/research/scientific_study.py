"""Mission-neutral scientific measurement and verdict primitives."""

from __future__ import annotations

from typing import Any, Mapping


PLANNED_CLAIMS = (
    "activity_and_concentration",
    "after_cost_fixed_lot_economics",
    "causal_feature_and_execution_validity",
    "registered_control_contrast",
    "selection_aware_signal_evidence",
    "temporal_and_regime_stability",
)
EVIDENCE_MODES = (
    "causal_contrast",
    "cost_and_execution",
    "extreme_or_boundary",
    "regime_stability",
    "sensitivity_or_stress",
    "temporal_stability",
)


def _criterion(
    criterion_id: str,
    claim_id: str,
    evidence_mode: str,
    metric: str,
    operator: str,
    threshold: int,
) -> dict[str, object]:
    return {
        "claim_id": claim_id,
        "criterion_id": criterion_id,
        "evidence_mode": evidence_mode,
        "metric": metric,
        "operator": operator,
        "threshold": threshold,
    }


def discovery_criteria(
    *,
    control_delta_metric: str,
    control_pvalue_metric: str,
    include_opposite_sign: bool,
) -> tuple[dict[str, object], ...]:
    criteria = [
        _criterion("A01-minimum-trades", "activity_and_concentration", "extreme_or_boundary", "trade_count", "ge", 100),
        _criterion("A02-positive-density", "activity_and_concentration", "extreme_or_boundary", "entries_per_day_milli", "gt", 0),
        _criterion("A03-profit-day-concentration", "activity_and_concentration", "extreme_or_boundary", "top5_profit_day_share_ppm", "le", 400_000),
        _criterion("B01-positive-native-cost", "after_cost_fixed_lot_economics", "cost_and_execution", "net_profit_micropoints", "gt", 0),
        _criterion("B02-fold-profit-factor", "after_cost_fixed_lot_economics", "cost_and_execution", "median_fold_profit_factor_milli", "ge", 1_050),
        _criterion("B03-slippage-stress", "after_cost_fixed_lot_economics", "sensitivity_or_stress", "stress_net_profit_micropoints", "ge", 0),
        _criterion("B04-monthly-realized-drawdown-share", "after_cost_fixed_lot_economics", "extreme_or_boundary", "monthly_realized_exit_drawdown_share_of_gross_profit_ppm", "le", 500_000),
        _criterion("C01-feature-prefix-invariance", "causal_feature_and_execution_validity", "causal_contrast", "prefix_invariance_mismatch_count", "eq", 0),
        _criterion("C02-decision-append-invariance", "causal_feature_and_execution_validity", "causal_contrast", "append_invariance_mismatch_count", "eq", 0),
        _criterion("C03-decision-time-causality", "causal_feature_and_execution_validity", "causal_contrast", "causality_violation_count", "eq", 0),
        _criterion("C04-resolved-cost", "causal_feature_and_execution_validity", "cost_and_execution", "unknown_cost_unresolved_signal_count", "eq", 0),
        _criterion("C05-finite-metrics", "causal_feature_and_execution_validity", "causal_contrast", "nonfinite_metric_count", "eq", 0),
    ]
    if include_opposite_sign:
        criteria.extend(
            (
                _criterion("D01-opposite-sign-control", "registered_control_contrast", "causal_contrast", "opposite_sign_worst_delta_net_profit_micropoints", "gt", 0),
                _criterion("D02-opposite-sign-uncertainty", "registered_control_contrast", "causal_contrast", "opposite_sign_pvalue_upper_ppm", "le", 100_000),
            )
        )
    criteria.extend(
        (
            _criterion("D03-primary-control", "registered_control_contrast", "causal_contrast", control_delta_metric, "gt", 0),
            _criterion("D04-primary-control-uncertainty", "registered_control_contrast", "causal_contrast", control_pvalue_metric, "le", 100_000),
            _criterion("E01-familywise-selection", "selection_aware_signal_evidence", "temporal_stability", "selection_aware_pvalue_ppm", "le", 100_000),
            _criterion("F01-evaluable-folds", "temporal_and_regime_stability", "temporal_stability", "evaluable_folds", "ge", 7),
            _criterion("F02-winning-folds", "temporal_and_regime_stability", "temporal_stability", "winning_fold_count", "ge", 5),
            _criterion("F03-positive-regimes", "temporal_and_regime_stability", "regime_stability", "supported_positive_regime_count", "ge", 2),
        )
    )
    return tuple(criteria)


def claim_metrics(
    evaluation: Mapping[str, Any],
    *,
    control_delta_metric: str,
    control_pvalue_metric: str,
    include_opposite_sign: bool,
) -> dict[str, dict[str, int | None]]:
    raw = evaluation.get("metrics")
    if not isinstance(raw, Mapping):
        raise ValueError("scientific evaluation has no metrics")
    metrics = dict(raw)
    if any(type(name) is not str or type(value) is not int for name, value in metrics.items()):
        raise ValueError("scientific evaluation metrics must be integer scalars")
    evaluable = evaluation.get("evaluable") is True

    def values(*names: str, null_when_not_evaluable: bool = False) -> dict[str, int | None]:
        result: dict[str, int | None] = {}
        for name in names:
            if name not in metrics:
                raise ValueError(f"scientific evaluation metric is absent: {name}")
            result[name] = None if null_when_not_evaluable and not evaluable else metrics[name]
        return result

    control_names = [control_delta_metric, control_pvalue_metric]
    if include_opposite_sign:
        control_names.extend(
            (
                "opposite_sign_pvalue_upper_ppm",
                "opposite_sign_worst_delta_net_profit_micropoints",
            )
        )
    return {
        "activity_and_concentration": values(
            "daily_entries_max_milli", "daily_entries_median_milli",
            "daily_entries_p10_milli", "daily_entries_p90_milli",
            "eligible_day_count", "entries_per_day_milli",
            "monthly_realized_exit_drawdown_micropoints",
            "top5_profit_day_share_ppm", "trade_count", "zero_entry_day_rate_ppm",
            null_when_not_evaluable=True,
        ),
        "after_cost_fixed_lot_economics": values(
            "median_fold_profit_factor_milli",
            "monthly_realized_exit_drawdown_share_of_gross_profit_ppm",
            "net_profit_micropoints", "stress_net_profit_micropoints",
            null_when_not_evaluable=True,
        ),
        "causal_feature_and_execution_validity": values(
            "append_invariance_mismatch_count", "causality_violation_count",
            "gap_excluded_signal_count", "nonfinite_metric_count",
            "prefix_invariance_mismatch_count", "unknown_cost_unresolved_signal_count",
        ),
        "registered_control_contrast": values(
            *control_names, null_when_not_evaluable=True
        ),
        "selection_aware_signal_evidence": values(
            "selection_aware_pvalue_ppm", null_when_not_evaluable=True
        ),
        "temporal_and_regime_stability": values(
            "evaluable_folds", "positive_regime_count",
            "supported_positive_regime_count", "winning_fold_count",
            null_when_not_evaluable=True,
        ),
    }


def planned_verdict(
    plan: Mapping[str, Any], measurement: Mapping[str, Any]
) -> str:
    metrics = measurement["metrics"]
    unavailable = False
    failed = False
    comparisons = {
        "eq": lambda value, threshold: value == threshold,
        "ge": lambda value, threshold: value >= threshold,
        "gt": lambda value, threshold: value > threshold,
        "le": lambda value, threshold: value <= threshold,
        "lt": lambda value, threshold: value < threshold,
    }
    for criterion in plan["criteria"]:
        value = metrics[criterion["claim_id"]][criterion["metric"]]
        if value is None:
            unavailable = True
            continue
        if not comparisons[criterion["operator"]](value, criterion["threshold"]):
            failed = True
    return "not_evaluable" if unavailable else "failed" if failed else "passed"


__all__ = [
    "EVIDENCE_MODES",
    "PLANNED_CLAIMS",
    "claim_metrics",
    "discovery_criteria",
    "planned_verdict",
]
