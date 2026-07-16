"""Independent historical/corrected projections for fixed-hold transitions.

The transition producer is not authority for either side of the comparison.
Historical values are projected from one content-addressed evaluation artifact;
corrected values are rederived from the validated atomic family trace.  Keeping
that projection here also prevents the generic trace validator from growing a
second embedded discovery engine.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from hashlib import sha256
from math import ceil, floor
from pathlib import Path
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.research.scientific_trace import ScientificTraceError


HISTORICAL_DRAWDOWN_EVALUATION_SCHEMA = "drawdown_state_evaluation.v1"
_THIS_FILE = Path(__file__).resolve()
_LEGACY_INFERENCE_METRICS = frozenset(
    {
        "feature_control_worst_pvalue_upper_ppm",
        "opposite_sign_pvalue_upper_ppm",
        "selection_aware_pvalue_ppm",
    }
)
_STRUCTURAL_FIELDS = {
    "metrics": frozenset(
        {
            "append_invariance_mismatch_count",
            "causality_violation_count",
            "eligible_day_count",
            "evaluable_folds",
            "gap_excluded_signal_count",
            "nonfinite_metric_count",
            "prefix_invariance_mismatch_count",
        }
    ),
    "fold_metrics": frozenset({"fold_id"}),
    "regime_metrics": frozenset({"evaluable_fold_count", "regime"}),
    "session_metrics": frozenset({"session"}),
    "direction_metrics": frozenset({"direction"}),
}
_ECONOMIC_FIELDS = {
    "metrics": frozenset(
        {
            "daily_entries_max_milli",
            "daily_entries_median_milli",
            "daily_entries_p10_milli",
            "daily_entries_p90_milli",
            "entries_per_day_milli",
            "feature_control_worst_delta_net_profit_micropoints",
            "median_fold_profit_factor_milli",
            "monthly_realized_exit_drawdown_micropoints",
            "monthly_realized_exit_drawdown_share_of_gross_profit_ppm",
            "net_profit_micropoints",
            "opposite_sign_worst_delta_net_profit_micropoints",
            "positive_regime_count",
            "stress_net_profit_micropoints",
            "supported_positive_regime_count",
            "top5_profit_day_share_ppm",
            "trade_count",
            "unknown_cost_unresolved_signal_count",
            "winning_fold_count",
            "zero_entry_day_rate_ppm",
        }
    ),
    "fold_metrics": frozenset(
        {
            "net_profit_micropoints",
            "profit_factor_milli",
            "stress_net_profit_micropoints",
            "trade_count",
            "unresolved_cost_signal_count",
        }
    ),
    "regime_metrics": frozenset(
        {"net_profit_micropoints", "trade_count", "winning_fold_count"}
    ),
    "session_metrics": frozenset(
        {"net_profit_micropoints", "trade_count"}
    ),
    "direction_metrics": frozenset(
        {"net_profit_micropoints", "trade_count"}
    ),
}
_SURFACE_NAMES = (
    "metrics",
    "fold_metrics",
    "regime_metrics",
    "session_metrics",
    "direction_metrics",
)
_INTENT_COMPARISON_FIELDS = (
    "availability_time",
    "decision_bar_index",
    "decision_bar_open_time",
    "decision_spread_source_bar_index",
    "decision_spread_source_bar_open_time",
    "decision_spread_information_complete_at",
    "decision_spread_known",
    "decision_time",
    "direction",
    "entry_bar_index",
    "entry_spread_source_bar_index",
    "entry_spread_source_bar_open_time",
    "entry_spread_information_complete_at",
    "entry_spread_known",
    "entry_time",
    "exit_bar_index",
    "exit_spread_source_bar_index",
    "exit_spread_source_bar_open_time",
    "exit_spread_information_complete_at",
    "exit_spread_known",
    "exit_time",
    "historical_reference_executable_id",
    "holding_bars",
    "spread_semantics",
    "status",
)
_REGIME_ORDER = ("low", "middle", "high")
_SESSION_ORDER = (
    "broker_01_07",
    "broker_08_14",
    "broker_15_22",
    "broker_23_00",
)
_DIRECTION_ORDER = ((1, "long"), (-1, "short"))


def fixed_hold_historical_projection_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _canonical_mapping(name: str, value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ScientificTraceError(f"{name} must be a mapping")
    try:
        normalized = parse_canonical(canonical_bytes(dict(value)))
    except (TypeError, ValueError) as exc:
        raise ScientificTraceError(f"{name} is not canonical") from exc
    if type(normalized) is not dict:
        raise ScientificTraceError(f"{name} must be an object")
    return normalized


def _partition_surface(
    *,
    configuration_id: str,
    surface: str,
    value: object,
) -> tuple[object, object]:
    structural_fields = _STRUCTURAL_FIELDS[surface]
    economic_fields = _ECONOMIC_FIELDS[surface]
    allowed = structural_fields | economic_fields
    if surface == "metrics":
        if not isinstance(value, Mapping) or set(value) != allowed:
            raise ScientificTraceError(
                f"{configuration_id} historical metrics field scope drifted"
            )
        return (
            {name: value[name] for name in sorted(structural_fields)},
            {name: value[name] for name in sorted(economic_fields)},
        )
    if not isinstance(value, list) or any(
        not isinstance(row, Mapping) or set(row) != allowed for row in value
    ):
        raise ScientificTraceError(
            f"{configuration_id} historical {surface} row scope drifted"
        )
    return (
        [
            {name: row[name] for name in sorted(structural_fields)}
            for row in value
        ],
        [
            {name: row[name] for name in sorted(economic_fields)}
            for row in value
        ],
    )


def project_historical_drawdown_evaluation(
    evaluation: object,
    *,
    expected_configuration_id: str,
    expected_historical_executable_id: str,
    expected_schema: str = HISTORICAL_DRAWDOWN_EVALUATION_SCHEMA,
) -> dict[str, dict[str, object]]:
    """Project exact transition surfaces from one authenticated old artifact."""

    normalized = _canonical_mapping("historical evaluation artifact", evaluation)
    if (
        normalized.get("schema") != expected_schema
        or normalized.get("subject_configuration_id")
        != expected_configuration_id
        or normalized.get("subject_executable_id")
        != expected_historical_executable_id
    ):
        raise ScientificTraceError(
            "historical evaluation artifact member binding drifted"
        )
    metrics = normalized.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ScientificTraceError("historical evaluation metrics are invalid")
    surfaces: dict[str, object] = {
        "metrics": {
            name: value
            for name, value in metrics.items()
            if name not in _LEGACY_INFERENCE_METRICS
        },
        **{
            name: normalized.get(name)
            for name in _SURFACE_NAMES
            if name != "metrics"
        },
    }
    structural: dict[str, object] = {}
    economic: dict[str, object] = {}
    for name in _SURFACE_NAMES:
        structural[name], economic[name] = _partition_surface(
            configuration_id=expected_configuration_id,
            surface=name,
            value=surfaces[name],
        )
    return {"economic": economic, "structural": structural}


def _profit_factor(values: Sequence[int]) -> int:
    gain = sum(value for value in values if value > 0)
    loss = -sum(value for value in values if value < 0)
    if loss <= 0:
        return 1_000_000 if gain > 0 else 0
    return min(1_000_000, int(round(1000 * gain / loss)))


def _quantile(values: Sequence[int], probability: float, *, method: str) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    index = floor(position) if method == "lower" else ceil(position)
    return ordered[index]


def _median(values: Sequence[int]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def _monthly_drawdown(values: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    by_month: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for trade in sorted(
        values,
        key=lambda item: (str(item["exit_time"]), str(item["observation_id"])),
    ):
        by_month[str(trade["exit_time"])[:7]].append(trade)
    worst = 0
    worst_share = 0
    for trades in by_month.values():
        equity = 0
        peak = 0
        drawdown = 0
        gross_profit = 0
        for trade in trades:
            pnl = int(trade["native_net_pnl_micropoints"])
            equity += pnl
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
            gross_profit += max(0, pnl)
        share = (
            0
            if drawdown <= 0
            else 1_000_000_000
            if gross_profit <= 0
            else min(
                1_000_000_000,
                ceil(1_000_000 * drawdown / gross_profit),
            )
        )
        worst = max(worst, drawdown)
        worst_share = max(worst_share, share)
    return worst, worst_share


def _session(entry_time: object) -> str:
    hour = int(str(entry_time)[11:13])
    if 1 <= hour <= 7:
        return "broker_01_07"
    if 8 <= hour <= 14:
        return "broker_08_14"
    if 15 <= hour <= 22:
        return "broker_15_22"
    return "broker_23_00"


def _intent_tuple(intent: Mapping[str, Any]) -> tuple[object, ...]:
    return tuple(intent[name] for name in _INTENT_COMPARISON_FIELDS)


def derive_fixed_hold_semantic_surfaces(
    *,
    ordered_family: Sequence[Mapping[str, Any]],
    control_bindings: Sequence[Mapping[str, Any]],
    windows: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]],
    intents: Sequence[Mapping[str, Any]],
    prefix_invariance_mismatch_count: int,
) -> dict[str, dict[str, dict[str, object]]]:
    """Rederive transition surfaces solely from atomic family observations."""

    if prefix_invariance_mismatch_count != 0:
        raise ScientificTraceError(
            "historical transition requires exact prefix invariance"
        )
    family = tuple(ordered_family)
    configuration_ids = tuple(str(item["configuration_id"]) for item in family)
    executable_by_configuration = {
        str(item["configuration_id"]): str(item["executable_id"])
        for item in family
    }
    configuration_by_executable = {
        executable_id: configuration_id
        for configuration_id, executable_id in executable_by_configuration.items()
    }
    if (
        not family
        or len(configuration_ids) != len(set(configuration_ids))
        or len(configuration_by_executable) != len(family)
    ):
        raise ScientificTraceError(
            "historical transition family projection is ambiguous"
        )
    fold_ids = tuple(str(item["fold_id"]) for item in windows)
    eligible_dates = tuple(
        sorted(
            {
                str(day)
                for window in windows
                for day in window["eligible_dates"]
            }
        )
    )
    by_configuration: dict[str, list[Mapping[str, Any]]] = {
        configuration_id: [] for configuration_id in configuration_ids
    }
    intent_by_configuration: dict[str, list[Mapping[str, Any]]] = {
        configuration_id: [] for configuration_id in configuration_ids
    }
    for trade in trades:
        by_configuration[str(trade["configuration_id"])].append(trade)
    for intent in intents:
        intent_by_configuration[str(intent["configuration_id"])].append(intent)

    controls = {
        str(item["subject_executable_id"]): item for item in control_bindings
    }
    if set(controls) != set(configuration_by_executable):
        raise ScientificTraceError(
            "historical transition control projection is incomplete"
        )
    net_by_executable = {
        executable_by_configuration[configuration_id]: sum(
            int(item["native_net_pnl_micropoints"])
            for item in by_configuration[configuration_id]
        )
        for configuration_id in configuration_ids
    }
    result: dict[str, dict[str, dict[str, object]]] = {}
    for configuration_id in configuration_ids:
        executable_id = executable_by_configuration[configuration_id]
        subject_trades = by_configuration[configuration_id]
        subject_intents = intent_by_configuration[configuration_id]
        full_by_fold: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        prefix_by_fold: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for intent in subject_intents:
            target = (
                full_by_fold
                if intent["scope"] == "full"
                else prefix_by_fold
            )
            target[str(intent["fold_id"])].append(intent)
        append_mismatches = 0
        for fold_id in fold_ids:
            full = full_by_fold[fold_id]
            prefix = prefix_by_fold[fold_id]
            append_mismatches += abs(len(full) - len(prefix)) + sum(
                _intent_tuple(left) != _intent_tuple(right)
                for left, right in zip(full, prefix, strict=False)
            )
        full_intents = tuple(
            item for item in subject_intents if item["scope"] == "full"
        )
        status_counts = {
            status: sum(item["status"] == status for item in full_intents)
            for status in (
                "causality_violation",
                "gap_excluded",
                "unknown_cost",
            )
        }
        daily_entries = {day: 0 for day in eligible_dates}
        daily_net = {day: 0 for day in eligible_dates}
        for trade in subject_trades:
            day = str(trade["decision_time"])[:10]
            daily_entries[day] += 1
            daily_net[day] += int(trade["native_net_pnl_micropoints"])
        entry_values = tuple(daily_entries.values())
        positive_days = sorted(
            (value for value in daily_net.values() if value > 0), reverse=True
        )
        gross_positive = sum(positive_days)
        top5_share = (
            0
            if gross_positive <= 0
            else min(
                1_000_000,
                int(round(1_000_000 * sum(positive_days[:5]) / gross_positive)),
            )
        )
        fold_metrics: list[dict[str, object]] = []
        for fold_id in fold_ids:
            selected = [
                item for item in subject_trades if item["fold_id"] == fold_id
            ]
            native = [
                int(item["native_net_pnl_micropoints"]) for item in selected
            ]
            fold_metrics.append(
                {
                    "fold_id": fold_id,
                    "net_profit_micropoints": sum(native),
                    "profit_factor_milli": _profit_factor(native),
                    "stress_net_profit_micropoints": sum(
                        int(item["stress_net_pnl_micropoints"])
                        for item in selected
                    ),
                    "trade_count": len(selected),
                    "unresolved_cost_signal_count": sum(
                        item["fold_id"] == fold_id
                        and item["status"] == "unknown_cost"
                        for item in full_intents
                    ),
                }
            )
        regime_metrics: list[dict[str, object]] = []
        for regime in _REGIME_ORDER:
            selected = [
                item for item in subject_trades if item["regime"] == regime
            ]
            fold_net = {
                fold_id: sum(
                    int(item["native_net_pnl_micropoints"])
                    for item in selected
                    if item["fold_id"] == fold_id
                )
                for fold_id in fold_ids
                if any(item["fold_id"] == fold_id for item in selected)
            }
            regime_metrics.append(
                {
                    "evaluable_fold_count": len(fold_net),
                    "regime": regime,
                    "net_profit_micropoints": sum(fold_net.values()),
                    "trade_count": len(selected),
                    "winning_fold_count": sum(
                        value > 0 for value in fold_net.values()
                    ),
                }
            )
        session_metrics = [
            {
                "session": session,
                "net_profit_micropoints": sum(
                    int(item["native_net_pnl_micropoints"])
                    for item in subject_trades
                    if _session(item["entry_time"]) == session
                ),
                "trade_count": sum(
                    _session(item["entry_time"]) == session
                    for item in subject_trades
                ),
            }
            for session in _SESSION_ORDER
        ]
        direction_metrics = [
            {
                "direction": name,
                "net_profit_micropoints": sum(
                    int(item["native_net_pnl_micropoints"])
                    for item in subject_trades
                    if item["direction"] == direction
                ),
                "trade_count": sum(
                    item["direction"] == direction for item in subject_trades
                ),
            }
            for direction, name in _DIRECTION_ORDER
        ]
        drawdown, drawdown_share = _monthly_drawdown(subject_trades)
        net = net_by_executable[executable_id]
        control = controls[executable_id]
        feature_deltas = tuple(
            net - net_by_executable[str(value)]
            for value in control["feature_executable_ids"]
        )
        opposite_delta = net - net_by_executable[
            str(control["opposite_executable_id"])
        ]
        fold_profit_factors = sorted(
            int(item["profit_factor_milli"]) for item in fold_metrics
        )
        structural_metrics = {
            "append_invariance_mismatch_count": append_mismatches,
            "causality_violation_count": status_counts["causality_violation"],
            "eligible_day_count": len(eligible_dates),
            "evaluable_folds": sum(
                int(item["trade_count"]) > 0 for item in fold_metrics
            ),
            "gap_excluded_signal_count": status_counts["gap_excluded"],
            "nonfinite_metric_count": 0,
            "prefix_invariance_mismatch_count": 0,
        }
        economic_metrics = {
            "daily_entries_max_milli": max(entry_values, default=0) * 1000,
            "daily_entries_median_milli": (
                0
                if not entry_values
                else int(round(1000 * _median(entry_values)))
            ),
            "daily_entries_p10_milli": 1000
            * _quantile(entry_values, 0.10, method="lower"),
            "daily_entries_p90_milli": 1000
            * _quantile(entry_values, 0.90, method="higher"),
            "entries_per_day_milli": (
                0
                if not eligible_dates
                else int(round(1000 * len(subject_trades) / len(eligible_dates)))
            ),
            "feature_control_worst_delta_net_profit_micropoints": min(
                feature_deltas
            ),
            "median_fold_profit_factor_milli": fold_profit_factors[
                len(fold_profit_factors) // 2
            ],
            "monthly_realized_exit_drawdown_micropoints": drawdown,
            "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": (
                drawdown_share
            ),
            "net_profit_micropoints": net,
            "opposite_sign_worst_delta_net_profit_micropoints": opposite_delta,
            "positive_regime_count": sum(
                int(item["net_profit_micropoints"]) > 0
                for item in regime_metrics
            ),
            "stress_net_profit_micropoints": sum(
                int(item["stress_net_pnl_micropoints"])
                for item in subject_trades
            ),
            "supported_positive_regime_count": sum(
                int(item["net_profit_micropoints"]) > 0
                and int(item["trade_count"]) >= 30
                and int(item["evaluable_fold_count"]) >= 5
                and int(item["winning_fold_count"]) >= 3
                and 2 * int(item["winning_fold_count"])
                > int(item["evaluable_fold_count"])
                for item in regime_metrics
            ),
            "top5_profit_day_share_ppm": top5_share,
            "trade_count": len(subject_trades),
            "unknown_cost_unresolved_signal_count": status_counts["unknown_cost"],
            "winning_fold_count": sum(
                int(item["net_profit_micropoints"]) > 0
                for item in fold_metrics
            ),
            "zero_entry_day_rate_ppm": (
                0
                if not entry_values
                else int(
                    round(
                        1_000_000
                        * sum(value == 0 for value in entry_values)
                        / len(entry_values)
                    )
                )
            ),
        }
        corrected = {
            "metrics": {**structural_metrics, **economic_metrics},
            "fold_metrics": fold_metrics,
            "regime_metrics": regime_metrics,
            "session_metrics": session_metrics,
            "direction_metrics": direction_metrics,
        }
        structural: dict[str, object] = {}
        economic: dict[str, object] = {}
        for name in _SURFACE_NAMES:
            structural[name], economic[name] = _partition_surface(
                configuration_id=configuration_id,
                surface=name,
                value=corrected[name],
            )
        result[configuration_id] = {
            "economic": economic,
            "structural": structural,
        }
    canonical_bytes(result)
    return result


__all__ = [
    "HISTORICAL_DRAWDOWN_EVALUATION_SCHEMA",
    "derive_fixed_hold_semantic_surfaces",
    "fixed_hold_historical_projection_implementation_sha256",
    "project_historical_drawdown_evaluation",
]
