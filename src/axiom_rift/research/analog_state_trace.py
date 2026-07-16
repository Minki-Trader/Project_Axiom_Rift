"""Atomic historical analog replay trace and pure protocol recomputation.

The validator never accepts metric bindings reported by the runner.  It opens
the exact four-member trace, checks the historical member mapping and causal
cost rows, reconstructs explicit zero-entry calendars, reruns deterministic
concurrent-family inference, and derives every legacy criterion metric.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from hashlib import sha256
from math import ceil
from pathlib import Path
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.analog_state_family import (
    ANALOG_FAMILY_ALPHA_PPM,
    ANALOG_FAMILY_BASE_SEED,
    ANALOG_FAMILY_BLOCK_LENGTHS,
    ANALOG_FAMILY_BOOTSTRAP_SAMPLES,
    ANALOG_FAMILY_MONTE_CARLO_CONFIDENCE_PPM,
    AnalogFamilySpec,
    analog_family_executable,
    analog_family_executable_map,
    analog_family_implementation_sha256,
)
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    EXPECTED_FOLD_IDS,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    discovery_implementation_sha256,
    loader_implementation_sha256,
)
from axiom_rift.research.completed_period_atomic_trace import (
    completed_period_atomic_trace_implementation_sha256,
    validate_completed_period_fixed_hold_sources,
)
from axiom_rift.research.scientific_trace import (
    ANALOG_STATE_TRACE_PROTOCOL_ID,
    SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
    SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
    ScientificTraceError,
)
from axiom_rift.research.selection_inference import (
    HistoricalSearchContext,
    SelectionFamilyPlan,
    SelectionHypothesis,
    infer_concurrent_selection_family,
    selection_inference_implementation_sha256,
)


ANALOG_REPLAY_EVIDENCE_MODES = (
    "causal_contrast",
    "cost_and_execution",
    "sensitivity_or_stress",
    "temporal_stability",
)
ANALOG_REPLAY_CLAIMS = (
    "activity_and_concentration",
    "after_cost_fixed_lot_economics",
    "causal_feature_and_execution_validity",
    "registered_control_contrast",
    "selection_aware_signal_evidence",
    "temporal_and_regime_stability",
)
ANALOG_FAMILY_TRACE_SCHEMA = "analog_family_trace.v3"
ANALOG_FAMILY_TRACE_CACHE_MANIFEST_SCHEMA = (
    "analog_family_trace_cache_manifest.v1"
)
ANALOG_FAMILY_TRACE_DIRECT_BINDING_SCHEMA = (
    "analog_family_trace_direct_binding.v1"
)
ANALOG_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT = 492
ANALOG_REPLAY_PRIOR_GLOBAL_EXPOSURE_COUNT = 574
ANALOG_REPLAY_ORIGINAL_FAMILY_CONTEXT_ID = (
    "historical-search:stu0061-original-family-through-492"
)
ANALOG_REPLAY_HISTORICAL_CONTEXT_ID = (
    "historical-search:stu0061-prospective-replay-through-574"
)
ANALOG_REPLAY_TRACE_ATTRIBUTION = {
    "drawdown_attribution": "exit_order_within_exit_month",
    "economic_composite": False,
    "eligible_calendar": "observed_test_dates_with_explicit_zero_entry_days",
    "native_pnl_attribution": "decision_day",
    "stress_pnl_attribution": "decision_day",
}
ANALOG_REPLAY_CONTROLS = {
    "feature_control_rule": "other_profile_same_sign",
    "opposite_sign_rule": "same_profile_opposite_sign",
    "paired_control_family_scope": "exact_two_registered_controls",
    "selection_family_scope": "exact_ordered_four_configuration_family",
}

_THIS_FILE = Path(__file__).resolve()
_TRADE_FIELDS = {
    "availability_time",
    "configuration_id",
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
    "executable_id",
    "exit_bar_index",
    "exit_spread_source_bar_index",
    "exit_spread_source_bar_open_time",
    "exit_spread_information_complete_at",
    "exit_spread_known",
    "exit_time",
    "fold_id",
    "gross_pnl_micropoints",
    "historical_reference_executable_id",
    "native_cost_micropoints",
    "native_net_pnl_micropoints",
    "observation_id",
    "regime",
    "stress_cost_micropoints",
    "stress_net_pnl_micropoints",
    "spread_semantics",
}
_INTENT_FIELDS = {
    "availability_time",
    "configuration_id",
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
    "executable_id",
    "exit_bar_index",
    "exit_spread_source_bar_index",
    "exit_spread_source_bar_open_time",
    "exit_spread_information_complete_at",
    "exit_spread_known",
    "exit_time",
    "fold_id",
    "historical_reference_executable_id",
    "observation_id",
    "ordinal",
    "scope",
    "spread_semantics",
    "status",
}
_ELIGIBLE_FIELDS = {
    "configuration_id",
    "date",
    "entry_count",
    "executable_id",
    "fold_id",
    "native_net_pnl_micropoints",
    "stress_net_pnl_micropoints",
}
_WINDOW_FIELDS = {
    "eligible_dates",
    "fold_id",
    "test_end",
    "test_start",
    "train_end",
    "train_start",
}
_INVARIANCE_FIELDS = {
    "compared_row_count",
    "fold_id",
    "full_score_values_sha256",
    "prefix_score_values_sha256",
    "profile_id",
}
_FAMILY_MEMBER_FIELDS = {
    "configuration_id",
    "executable_id",
    "historical_reference_executable_id",
    "ordinal",
    "profile_id",
    "signal_sign",
}
_FAMILY_TRACE_FIELDS = {
    "attribution",
    "clock_contract",
    "controls",
    "cost_contract",
    "dataset_sha256",
    "eligible_day_observations",
    "family_id",
    "implementation_identities",
    "intent_observations",
    "invariance_comparisons",
    "material_identity",
    "ordered_family",
    "original_family_provenance",
    "protocol_id",
    "schema",
    "split_artifact_sha256",
    "trade_observations",
    "windows",
}
_SUBJECT_TRACE_FIELDS = {
    "adapter_implementation_sha256",
    "attribution",
    "controls",
    "dataset_sha256",
    "eligible_day_observations",
    "family_id",
    "invariance_comparisons",
    "intent_observations",
    "job_hash",
    "job_id",
    "material_identity",
    "mission_id",
    "ordered_family",
    "protocol_id",
    "schema",
    "split_artifact_sha256",
    "subject_executable_id",
    "trade_observations",
    "windows",
}
_SUBJECT_ATTRIBUTION_FIELDS = {
    "family_trace_binding",
    "protocol_attribution",
}
_FAMILY_TRACE_BINDING_FIELDS = {
    "cache_manifest",
    "clock_contract",
    "cost_contract",
    "family_trace_sha256",
    "implementation_identities",
    "original_family_provenance",
    "schema",
}
_DIRECT_BINDING_FIELDS = {"claim_authority", "schema", "source"}
_CACHE_MANIFEST_FIELDS = {
    "cache_output_name",
    "cache_schema",
    "cache_sha256",
    "claim_authority",
    "dataset_sha256",
    "family_id",
    "implementation_identities",
    "manifest_output_name",
    "material_identity",
    "mission_id",
    "producer_executable_id",
    "producer_execution",
    "schema",
    "split_artifact_sha256",
    "study_id",
}
_PRODUCER_EXECUTION_FIELDS = {
    "identity",
    "job_hash",
    "job_id",
    "job_permit_id",
    "start_record_id",
}
_IMPLEMENTATION_IDENTITY_FIELDS = {
    "analog_family_sha256",
    "analog_replay_sha256",
    "analog_trace_sha256",
    "completed_period_atomic_trace_sha256",
    "discovery_sha256",
    "loader_sha256",
    "selection_inference_sha256",
}
_ORIGINAL_FAMILY_PROVENANCE_FIELDS = {
    "context_id",
    "end_global_exposure_count",
    "family_id",
    "family_size",
    "role",
}
_CALCULATION_PARAMETER_FIELDS = {
    "alpha_ppm",
    "base_seed",
    "block_lengths",
    "bootstrap_samples",
    "exact_concurrent_family_adjustment_factor",
    "historical_context_adjustment_authority",
    "historical_context_prior_global_exposure_count",
    "monte_carlo_confidence_ppm",
    "original_family_end_global_exposure_count",
}
_CALCULATION_STATISTIC_FIELDS = {
    "exposure_semantics",
    "historical_context",
    "paired_control_family",
    "selection_family",
}
_ALLOWED_INTENT_STATUSES = frozenset(
    {
        "causality_violation",
        "entry_cancelled_unknown_cost",
        "executed",
        "gap_excluded",
        "unknown_cost",
    }
)
_ALLOWED_REGIMES = frozenset({"high", "low", "middle"})


def _legacy_family() -> AnalogFamilySpec:
    """Load the frozen compatibility family only on legacy call paths."""

    from axiom_rift.research.historical_analog_family_stu0061 import (
        STU0061_ANALOG_FAMILY,
    )

    return STU0061_ANALOG_FAMILY


def analog_trace_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def analog_family_trace_implementation_identities(
    *,
    replay_implementation_sha256: str | None = None,
) -> dict[str, str]:
    """Bind cache bytes to every implementation that can change their rows."""

    if replay_implementation_sha256 is None:
        # Reconstruction compatibility only. Prospective callers pass the
        # exact implementation bundle and never import the historical runner.
        from axiom_rift.research.analog_state_replay import (
            analog_replay_implementation_sha256,
        )

        replay_identity = analog_replay_implementation_sha256()
    else:
        replay_identity = _digest(
            "analog replay implementation",
            replay_implementation_sha256,
        )

    value = {
        "analog_family_sha256": analog_family_implementation_sha256(),
        "analog_replay_sha256": replay_identity,
        "analog_trace_sha256": analog_trace_implementation_sha256(),
        "completed_period_atomic_trace_sha256": (
            completed_period_atomic_trace_implementation_sha256()
        ),
        "discovery_sha256": discovery_implementation_sha256(),
        "loader_sha256": loader_implementation_sha256(),
        "selection_inference_sha256": (
            selection_inference_implementation_sha256()
        ),
    }
    if set(value) != _IMPLEMENTATION_IDENTITY_FIELDS:
        raise ScientificTraceError("analog implementation inventory drifted")
    return value


def analog_family_execution_contracts(
    family: AnalogFamilySpec | None = None,
) -> dict[str, str]:
    """Return the one clock and cost contract shared by all four members."""

    bound_family = _legacy_family() if family is None else family
    if not isinstance(bound_family, AnalogFamilySpec):
        raise ScientificTraceError("analog execution family is not typed")
    executables = tuple(
        analog_family_executable(configuration)
        for configuration in bound_family.configurations()
    )
    clocks = {item.clock_contract for item in executables}
    costs = {item.cost_contract for item in executables}
    if len(clocks) != 1 or len(costs) != 1:
        raise ScientificTraceError(
            "analog replay family clock or cost contract is not shared"
        )
    return {
        "clock_contract": next(iter(clocks)),
        "cost_contract": next(iter(costs)),
    }


def analog_original_family_provenance(
    family: AnalogFamilySpec | None = None,
    *,
    context_id: str = ANALOG_REPLAY_ORIGINAL_FAMILY_CONTEXT_ID,
    end_global_exposure_count: int = (
        ANALOG_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
    ),
) -> dict[str, object]:
    """Preserve the original Study boundary without reusing it for replay."""

    bound_family = _legacy_family() if family is None else family
    if (
        not isinstance(bound_family, AnalogFamilySpec)
        or type(context_id) is not str
        or not context_id
        or not context_id.isascii()
        or type(end_global_exposure_count) is not int
        or end_global_exposure_count < 0
    ):
        raise ScientificTraceError("analog original-family provenance is invalid")
    return {
        "context_id": context_id,
        "end_global_exposure_count": end_global_exposure_count,
        "family_id": bound_family.family_id,
        "family_size": len(bound_family.configurations()),
        "role": "immutable_original_family_provenance_not_adjustment_factor",
    }


def _criterion(
    criterion_id: str,
    claim_id: str,
    evidence_mode: str,
    metric: str,
    operator: str,
    threshold: int,
    decision_role: str,
) -> dict[str, object]:
    return {
        "claim_id": claim_id,
        "criterion_id": criterion_id,
        "decision_role": decision_role,
        "evidence_mode": evidence_mode,
        "metric": metric,
        "operator": operator,
        "threshold": threshold,
    }


ANALOG_REPLAY_CRITERIA = tuple(
    sorted(
        (
            _criterion("A01-minimum-trades", "activity_and_concentration", "cost_and_execution", "trade_count", "ge", 100, "component"),
            _criterion("A02-positive-density", "activity_and_concentration", "cost_and_execution", "entries_per_day_milli", "gt", 0, "component"),
            _criterion("A03-profit-day-concentration", "activity_and_concentration", "cost_and_execution", "top5_profit_day_share_ppm", "le", 400_000, "component"),
            _criterion("B01-positive-native-cost", "after_cost_fixed_lot_economics", "cost_and_execution", "net_profit_micropoints", "gt", 0, "component"),
            _criterion("B02-fold-profit-factor", "after_cost_fixed_lot_economics", "cost_and_execution", "median_fold_profit_factor_milli", "ge", 1_050, "component"),
            _criterion("B03-slippage-stress", "after_cost_fixed_lot_economics", "sensitivity_or_stress", "stress_net_profit_micropoints", "ge", 0, "component"),
            _criterion("B04-monthly-realized-drawdown-share", "after_cost_fixed_lot_economics", "cost_and_execution", "monthly_realized_exit_drawdown_share_of_gross_profit_ppm", "le", 500_000, "risk_diagnostic"),
            _criterion("C01-feature-prefix-invariance", "causal_feature_and_execution_validity", "causal_contrast", "prefix_invariance_mismatch_count", "eq", 0, "validity"),
            _criterion("C02-decision-append-invariance", "causal_feature_and_execution_validity", "causal_contrast", "append_invariance_mismatch_count", "eq", 0, "validity"),
            _criterion("C03-decision-time-causality", "causal_feature_and_execution_validity", "causal_contrast", "causality_violation_count", "eq", 0, "validity"),
            _criterion("C04-resolved-cost", "causal_feature_and_execution_validity", "cost_and_execution", "unknown_cost_unresolved_signal_count", "eq", 0, "validity"),
            _criterion("C05-finite-metrics", "causal_feature_and_execution_validity", "causal_contrast", "nonfinite_metric_count", "eq", 0, "validity"),
            _criterion("D01-opposite-sign-control", "registered_control_contrast", "causal_contrast", "opposite_sign_worst_delta_net_profit_micropoints", "gt", 0, "component"),
            _criterion("D02-opposite-sign-uncertainty", "registered_control_contrast", "causal_contrast", "opposite_sign_pvalue_upper_ppm", "le", 100_000, "multiplicity"),
            _criterion("D03-feature-control", "registered_control_contrast", "causal_contrast", "feature_control_worst_delta_net_profit_micropoints", "gt", 0, "component"),
            _criterion("D04-feature-control-uncertainty", "registered_control_contrast", "causal_contrast", "feature_control_worst_pvalue_upper_ppm", "le", 100_000, "component"),
            _criterion("E01-familywise-selection", "selection_aware_signal_evidence", "temporal_stability", "selection_aware_pvalue_ppm", "le", 100_000, "multiplicity"),
            _criterion("F01-evaluable-folds", "temporal_and_regime_stability", "temporal_stability", "evaluable_folds", "ge", 7, "component"),
            _criterion("F02-winning-folds", "temporal_and_regime_stability", "temporal_stability", "winning_fold_count", "ge", 5, "component"),
            _criterion("F03-positive-regimes", "temporal_and_regime_stability", "temporal_stability", "supported_positive_regime_count", "ge", 2, "component"),
        ),
        key=lambda item: (str(item["claim_id"]), str(item["criterion_id"])),
    )
)


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ScientificTraceError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise ScientificTraceError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _integer(name: str, value: object, *, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ScientificTraceError(f"{name} must be an integer")
    return value


def _mapping(name: str, value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ScientificTraceError(f"{name} must be a mapping")
    return value


def _sequence(name: str, value: object, *, allow_empty: bool = False) -> Sequence[Any]:
    if not isinstance(value, (list, tuple)) or (not value and not allow_empty):
        raise ScientificTraceError(f"{name} must be a sequence")
    return value


def _timestamp(name: str, value: object) -> datetime:
    text = _ascii(name, value)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ScientificTraceError(f"{name} is not ISO-8601") from exc
    if parsed.tzinfo is not None or parsed.isoformat() != text:
        raise ScientificTraceError(f"{name} must be canonical and timezone-naive")
    return parsed


def _date(name: str, value: object) -> date:
    text = _ascii(name, value)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ScientificTraceError(f"{name} is invalid") from exc
    if parsed.isoformat() != text:
        raise ScientificTraceError(f"{name} must be canonical")
    return parsed


def analog_observation_id(kind: str, value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "observation_id"}
    digest = canonical_digest(domain=f"analog-{kind}-observation", payload=payload)
    return f"observation:{digest}"


def expected_analog_family_inventory(
    family: AnalogFamilySpec | None = None,
) -> tuple[dict[str, object], ...]:
    bound_family = _legacy_family() if family is None else family
    if not isinstance(bound_family, AnalogFamilySpec):
        raise ScientificTraceError("analog inventory family is not typed")
    mapping = analog_family_executable_map(bound_family)
    by_configuration = {
        value.configuration_id: (executable_id, value)
        for executable_id, value in mapping.items()
    }
    inventory: list[dict[str, object]] = []
    for ordinal, configuration in enumerate(
        bound_family.configurations(), start=1
    ):
        executable_id, mapped = by_configuration[configuration.configuration_id]
        inventory.append(
            {
                "configuration_id": mapped.configuration_id,
                "executable_id": executable_id,
                "historical_reference_executable_id": (
                    mapped.historical_reference_executable_id
                ),
                "ordinal": ordinal,
                "profile_id": mapped.profile_id,
                "signal_sign": mapped.signal_sign,
            }
        )
    return tuple(inventory)


def analog_calculation_parameters() -> dict[str, object]:
    return {
        "alpha_ppm": ANALOG_FAMILY_ALPHA_PPM,
        "base_seed": ANALOG_FAMILY_BASE_SEED,
        "block_lengths": list(ANALOG_FAMILY_BLOCK_LENGTHS),
        "bootstrap_samples": ANALOG_FAMILY_BOOTSTRAP_SAMPLES,
        "exact_concurrent_family_adjustment_factor": 4,
        "historical_context_adjustment_authority": (
            "context_only_never_adjustment_factor"
        ),
        "historical_context_prior_global_exposure_count": (
            ANALOG_REPLAY_PRIOR_GLOBAL_EXPOSURE_COUNT
        ),
        "monte_carlo_confidence_ppm": (
            ANALOG_FAMILY_MONTE_CARLO_CONFIDENCE_PPM
        ),
        "original_family_end_global_exposure_count": (
            ANALOG_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
        ),
    }


def _validate_family(
    trace: Mapping[str, Any],
    *,
    family_spec: AnalogFamilySpec,
    expected_inventory: tuple[dict[str, object], ...],
) -> dict[str, dict[str, Any]]:
    if trace.get("family_id") != family_spec.family_id:
        raise ScientificTraceError("analog trace family does not match its bound family")
    raw = _sequence("analog ordered family", trace.get("ordered_family"))
    family: list[dict[str, Any]] = []
    for item in raw:
        member = _mapping("analog family member", item)
        if set(member) != _FAMILY_MEMBER_FIELDS:
            raise ScientificTraceError("analog family member schema is invalid")
        family.append(dict(member))
    if tuple(family) != expected_inventory:
        raise ScientificTraceError(
            "analog trace family or historical reference mapping drifted"
        )
    by_configuration = {str(item["configuration_id"]): item for item in family}
    return by_configuration


def _validate_windows(trace: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    raw = _sequence("analog windows", trace.get("windows"))
    windows: list[dict[str, Any]] = []
    for item in raw:
        window = _mapping("analog window", item)
        if set(window) != _WINDOW_FIELDS:
            raise ScientificTraceError("analog window schema is invalid")
        fold_id = _ascii("analog fold_id", window.get("fold_id"))
        train_start = _timestamp("analog train_start", window.get("train_start"))
        train_end = _timestamp("analog train_end", window.get("train_end"))
        test_start = _timestamp("analog test_start", window.get("test_start"))
        test_end = _timestamp("analog test_end", window.get("test_end"))
        if not train_start <= train_end < test_start <= test_end:
            raise ScientificTraceError("analog fold windows overlap or reverse")
        eligible_dates = tuple(
            _date("analog eligible date", value).isoformat()
            for value in _sequence("analog eligible dates", window.get("eligible_dates"))
        )
        if eligible_dates != tuple(sorted(set(eligible_dates))):
            raise ScientificTraceError("analog eligible dates are not exact and sorted")
        if any(
            not test_start.date() <= date.fromisoformat(value) <= test_end.date()
            for value in eligible_dates
        ):
            raise ScientificTraceError("analog eligible date is outside its test fold")
        windows.append(dict(window))
    if tuple(item["fold_id"] for item in windows) != EXPECTED_FOLD_IDS:
        raise ScientificTraceError("analog trace must retain the exact nine folds")
    calendars = [set(item["eligible_dates"]) for item in windows]
    if any(left.intersection(right) for index, left in enumerate(calendars) for right in calendars[index + 1 :]):
        raise ScientificTraceError("analog fold eligible calendars overlap")
    return tuple(windows)


def _validate_invariance(
    trace: Mapping[str, Any],
    *,
    family_spec: AnalogFamilySpec,
    windows: tuple[dict[str, Any], ...],
) -> int:
    raw = _sequence("analog invariance comparisons", trace.get("invariance_comparisons"))
    comparisons: list[tuple[str, str]] = []
    for item in raw:
        comparison = _mapping("analog invariance comparison", item)
        if set(comparison) != _INVARIANCE_FIELDS:
            raise ScientificTraceError("analog invariance comparison schema is invalid")
        fold_id = _ascii("invariance fold_id", comparison.get("fold_id"))
        profile_id = _ascii("invariance profile_id", comparison.get("profile_id"))
        family_spec.profile(profile_id)
        _integer("invariance compared rows", comparison.get("compared_row_count"), minimum=1)
        full = _digest(
            "full causal surface digest",
            comparison.get("full_score_values_sha256"),
        )
        prefix = _digest(
            "prefix causal surface digest",
            comparison.get("prefix_score_values_sha256"),
        )
        if full != prefix:
            raise ScientificTraceError(
                "analog causal surface prefix invariance failed"
            )
        comparisons.append((fold_id, profile_id))
    expected = tuple(
        (str(window["fold_id"]), profile.profile_id)
        for window in windows
        for profile in family_spec.profiles
    )
    if tuple(comparisons) != expected:
        raise ScientificTraceError("analog invariance inventory is incomplete")
    return 0


def _validate_execution_clock_sources(
    row: Mapping[str, Any],
    *,
    horizon: int,
    prefix: str,
    intent_status: str | None = None,
) -> tuple[datetime, datetime, datetime]:
    return validate_completed_period_fixed_hold_sources(
        row,
        holding_bars=horizon,
        prefix=prefix,
        intent_status=intent_status,
    )


def _validate_exact_test_window(
    row: Mapping[str, Any],
    *,
    window: Mapping[str, Any],
    prefix: str,
) -> None:
    test_start = _timestamp(f"{prefix} test_start", window.get("test_start"))
    test_end = _timestamp(f"{prefix} test_end", window.get("test_end"))
    eligible_dates = set(
        _sequence(f"{prefix} eligible_dates", window.get("eligible_dates"))
    )
    decision_bar_open = _timestamp(
        f"{prefix} decision_bar_open_time",
        row.get("decision_bar_open_time"),
    )
    exit_time = _timestamp(f"{prefix} exit_time", row.get("exit_time"))
    if (
        decision_bar_open < test_start
        or decision_bar_open > test_end
        or decision_bar_open.date().isoformat() not in eligible_dates
        or exit_time > test_end
    ):
        raise ScientificTraceError(
            f"{prefix} is outside its exact test calendar"
        )


def _validate_trades(
    trace: Mapping[str, Any],
    *,
    family: Mapping[str, Mapping[str, Any]],
    windows: tuple[dict[str, Any], ...],
    horizon: int,
) -> tuple[dict[str, Any], ...]:
    raw = _sequence("analog trades", trace.get("trade_observations"), allow_empty=True)
    window_by_fold = {str(item["fold_id"]): item for item in windows}
    trades: list[dict[str, Any]] = []
    sort_keys: list[tuple[object, ...]] = []
    seen: set[str] = set()
    for item in raw:
        trade = _mapping("analog trade", item)
        if set(trade) != _TRADE_FIELDS:
            raise ScientificTraceError("analog trade schema is invalid")
        configuration_id = _ascii("trade configuration_id", trade.get("configuration_id"))
        member = family.get(configuration_id)
        if member is None or any(
            trade.get(name) != member[name]
            for name in (
                "executable_id",
                "historical_reference_executable_id",
            )
        ):
            raise ScientificTraceError("analog trade belongs to another family member")
        fold_id = _ascii("trade fold_id", trade.get("fold_id"))
        window = window_by_fold.get(fold_id)
        if window is None:
            raise ScientificTraceError("analog trade fold is unknown")
        _validate_exact_test_window(
            trade,
            window=window,
            prefix="analog trade",
        )
        decision, _, _ = _validate_execution_clock_sources(
            trade,
            horizon=horizon,
            prefix="analog trade",
        )
        direction = _integer("trade direction", trade.get("direction"))
        if direction not in {-1, 1}:
            raise ScientificTraceError("analog trade direction is invalid")
        gross = _integer("trade gross", trade.get("gross_pnl_micropoints"))
        native_cost = _integer("trade native cost", trade.get("native_cost_micropoints"), minimum=0)
        stress_cost = _integer("trade stress cost", trade.get("stress_cost_micropoints"), minimum=0)
        native_net = _integer("trade native net", trade.get("native_net_pnl_micropoints"))
        stress_net = _integer("trade stress net", trade.get("stress_net_pnl_micropoints"))
        if stress_cost < native_cost or gross - native_cost != native_net or gross - stress_cost != stress_net:
            raise ScientificTraceError("analog trade cost arithmetic does not reconcile")
        if trade.get("regime") not in _ALLOWED_REGIMES:
            raise ScientificTraceError("analog trade regime is invalid")
        observation_id = _ascii("trade observation_id", trade.get("observation_id"))
        if observation_id != analog_observation_id("trade", trade) or observation_id in seen:
            raise ScientificTraceError("analog trade observation identity is invalid")
        seen.add(observation_id)
        trades.append(dict(trade))
        sort_keys.append((configuration_id, fold_id, decision.isoformat(), observation_id))
    if tuple(sort_keys) != tuple(sorted(sort_keys)):
        raise ScientificTraceError("analog trades are not canonical")
    return tuple(trades)


def _intent_comparison_tuple(intent: Mapping[str, Any]) -> tuple[object, ...]:
    return tuple(
        intent[name]
        for name in (
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
            "executable_id",
            "exit_bar_index",
            "exit_spread_source_bar_index",
            "exit_spread_source_bar_open_time",
            "exit_spread_information_complete_at",
            "exit_spread_known",
            "exit_time",
            "historical_reference_executable_id",
            "spread_semantics",
            "status",
        )
    )


def _execution_identity(row: Mapping[str, Any]) -> tuple[object, ...]:
    return tuple(
        row[name]
        for name in (
            "configuration_id",
            "executable_id",
            "historical_reference_executable_id",
            "fold_id",
            "decision_bar_index",
            "decision_spread_source_bar_index",
            "decision_spread_source_bar_open_time",
            "decision_spread_information_complete_at",
            "decision_spread_known",
            "decision_time",
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
            "direction",
            "spread_semantics",
        )
    )


def _validate_intents(
    trace: Mapping[str, Any],
    *,
    family: Mapping[str, Mapping[str, Any]],
    windows: tuple[dict[str, Any], ...],
    trades: tuple[dict[str, Any], ...],
    horizon: int,
) -> tuple[
    tuple[dict[str, Any], ...],
    dict[str, tuple[int, int, int]],
]:
    raw = _sequence("analog intents", trace.get("intent_observations"), allow_empty=True)
    window_by_fold = {str(item["fold_id"]): item for item in windows}
    intents: list[dict[str, Any]] = []
    seen: set[str] = set()
    sort_keys: list[tuple[object, ...]] = []
    for item in raw:
        intent = _mapping("analog intent", item)
        if set(intent) != _INTENT_FIELDS:
            raise ScientificTraceError("analog intent schema is invalid")
        configuration_id = _ascii("intent configuration_id", intent.get("configuration_id"))
        member = family.get(configuration_id)
        if member is None or any(
            intent.get(name) != member[name]
            for name in (
                "executable_id",
                "historical_reference_executable_id",
            )
        ):
            raise ScientificTraceError("analog intent belongs to another family member")
        fold_id = _ascii("intent fold_id", intent.get("fold_id"))
        window = window_by_fold.get(fold_id)
        if window is None:
            raise ScientificTraceError("analog intent fold is unknown")
        scope = intent.get("scope")
        if scope not in {"full", "prefix"}:
            raise ScientificTraceError("analog intent scope is invalid")
        ordinal = _integer("intent ordinal", intent.get("ordinal"), minimum=1)
        status = intent.get("status")
        if status not in _ALLOWED_INTENT_STATUSES:
            raise ScientificTraceError("analog intent status is invalid")
        _validate_exact_test_window(
            intent,
            window=window,
            prefix="analog intent",
        )
        _validate_execution_clock_sources(
            intent,
            horizon=horizon,
            prefix="analog intent",
            intent_status=str(status),
        )
        if _integer("intent direction", intent.get("direction")) not in {-1, 1}:
            raise ScientificTraceError("analog intent direction is invalid")
        observation_id = _ascii("intent observation_id", intent.get("observation_id"))
        if observation_id != analog_observation_id("intent", intent) or observation_id in seen:
            raise ScientificTraceError("analog intent observation identity is invalid")
        seen.add(observation_id)
        intents.append(dict(intent))
        sort_keys.append((configuration_id, fold_id, scope, ordinal, observation_id))
    if tuple(sort_keys) != tuple(sorted(sort_keys)):
        raise ScientificTraceError("analog intents are not canonical")
    by_scope: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for intent in intents:
        by_scope[(intent["configuration_id"], intent["fold_id"], intent["scope"])].append(intent)
    append_mismatches: dict[str, int] = {
        configuration_id: 0 for configuration_id in family
    }
    for configuration_id in family:
        for fold_id in window_by_fold:
            full = by_scope.get((configuration_id, fold_id, "full"), [])
            prefix = by_scope.get((configuration_id, fold_id, "prefix"), [])
            if tuple(item["ordinal"] for item in full) != tuple(range(1, len(full) + 1)) or tuple(item["ordinal"] for item in prefix) != tuple(range(1, len(prefix) + 1)):
                raise ScientificTraceError("analog intent ordinals are not contiguous")
            append_mismatches[configuration_id] += abs(len(full) - len(prefix)) + sum(
                _intent_comparison_tuple(left) != _intent_comparison_tuple(right)
                for left, right in zip(full, prefix, strict=False)
            )
    full_executed = tuple(
        _execution_identity(item)
        for item in intents
        if item["scope"] == "full" and item["status"] == "executed"
    )
    trade_identities = tuple(_execution_identity(item) for item in trades)
    if (
        len(full_executed) != len(set(full_executed))
        or len(trade_identities) != len(set(trade_identities))
        or set(full_executed) != set(trade_identities)
    ):
        raise ScientificTraceError("analog executed intents differ from trade rows")
    counts = {
        configuration_id: (
            append_mismatches[configuration_id],
            sum(
                item["configuration_id"] == configuration_id
                and item["scope"] == "full"
                and item["status"] == "causality_violation"
                for item in intents
            ),
            sum(
                item["configuration_id"] == configuration_id
                and item["scope"] == "full"
                and item["status"] == "unknown_cost"
                for item in intents
            ),
        )
        for configuration_id in family
    }
    return tuple(intents), counts


def _validate_eligible_days(
    trace: Mapping[str, Any],
    *,
    family: Mapping[str, Mapping[str, Any]],
    windows: tuple[dict[str, Any], ...],
    trades: tuple[dict[str, Any], ...],
) -> dict[str, dict[str, int]]:
    raw = _sequence("analog eligible days", trace.get("eligible_day_observations"))
    rows: list[dict[str, Any]] = []
    sort_keys: list[tuple[str, str, str]] = []
    for item in raw:
        row = _mapping("analog eligible day", item)
        if set(row) != _ELIGIBLE_FIELDS:
            raise ScientificTraceError("analog eligible-day schema is invalid")
        configuration_id = _ascii("eligible configuration_id", row.get("configuration_id"))
        member = family.get(configuration_id)
        if member is None or row.get("executable_id") != member["executable_id"]:
            raise ScientificTraceError("analog eligible day belongs to another member")
        fold_id = _ascii("eligible fold_id", row.get("fold_id"))
        day = _date("eligible date", row.get("date")).isoformat()
        _integer("eligible entry_count", row.get("entry_count"), minimum=0)
        _integer("eligible native pnl", row.get("native_net_pnl_micropoints"))
        _integer("eligible stress pnl", row.get("stress_net_pnl_micropoints"))
        rows.append(dict(row))
        sort_keys.append((configuration_id, fold_id, day))
    if tuple(sort_keys) != tuple(sorted(sort_keys)) or len(set(sort_keys)) != len(sort_keys):
        raise ScientificTraceError("analog eligible-day rows are not canonical")
    expected = {
        (configuration_id, str(window["fold_id"]), day)
        for configuration_id in family
        for window in windows
        for day in window["eligible_dates"]
    }
    if set(sort_keys) != expected:
        raise ScientificTraceError("analog explicit zero-entry calendar is incomplete")
    aggregate: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    for trade in trades:
        key = (
            trade["configuration_id"],
            trade["fold_id"],
            str(trade["decision_time"])[:10],
        )
        aggregate[key][0] += 1
        aggregate[key][1] += trade["native_net_pnl_micropoints"]
        aggregate[key][2] += trade["stress_net_pnl_micropoints"]
    daily_by_executable: dict[str, dict[str, int]] = {
        str(member["executable_id"]): {} for member in family.values()
    }
    for row in rows:
        key = (row["configuration_id"], row["fold_id"], row["date"])
        observed = aggregate.get(key, [0, 0, 0])
        if tuple(observed) != (
            row["entry_count"],
            row["native_net_pnl_micropoints"],
            row["stress_net_pnl_micropoints"],
        ):
            raise ScientificTraceError("analog eligible-day aggregation drifted")
        executable_id = str(row["executable_id"])
        if row["date"] in daily_by_executable[executable_id]:
            raise ScientificTraceError("analog eligible date appears in two folds")
        daily_by_executable[executable_id][row["date"]] = row[
            "native_net_pnl_micropoints"
        ]
    calendars = {tuple(sorted(values)) for values in daily_by_executable.values()}
    if len(calendars) != 1 or len(next(iter(calendars))) < 30:
        raise ScientificTraceError("analog selection calendar is not shared or sufficient")
    return daily_by_executable


def _validated_family_trace_parts(
    trace: Mapping[str, Any],
    *,
    family_spec: AnalogFamilySpec,
    expected_inventory: tuple[dict[str, object], ...],
    expected_implementation_identities: Mapping[str, str],
    expected_provenance: Mapping[str, object],
) -> dict[str, Any]:
    if not isinstance(family_spec, AnalogFamilySpec):
        raise ScientificTraceError("analog trace family binding is not typed")
    if not isinstance(trace, Mapping) or set(trace) != _FAMILY_TRACE_FIELDS:
        raise ScientificTraceError("analog family trace schema is invalid")
    try:
        normalized = parse_canonical(canonical_bytes(trace))
    except (TypeError, ValueError) as exc:
        raise ScientificTraceError("analog family trace is not canonical") from exc
    if not isinstance(normalized, dict):
        raise ScientificTraceError("analog family trace must be an object")
    if (
        normalized.get("schema") != ANALOG_FAMILY_TRACE_SCHEMA
        or normalized.get("protocol_id") != ANALOG_STATE_TRACE_PROTOCOL_ID
        or normalized.get("dataset_sha256") != DATASET_SHA256
        or normalized.get("material_identity") != OBSERVED_MATERIAL_ID
        or normalized.get("split_artifact_sha256") != ROLLING_SPLIT_SHA256
        or normalized.get("attribution") != ANALOG_REPLAY_TRACE_ATTRIBUTION
        or normalized.get("controls") != ANALOG_REPLAY_CONTROLS
    ):
        raise ScientificTraceError("analog family trace authority binding drifted")
    contracts = analog_family_execution_contracts(family_spec)
    if any(normalized.get(name) != value for name, value in contracts.items()):
        raise ScientificTraceError("analog family trace clock or cost drifted")
    implementations = normalized.get("implementation_identities")
    if (
        not isinstance(implementations, dict)
        or set(implementations) != _IMPLEMENTATION_IDENTITY_FIELDS
        or implementations != dict(expected_implementation_identities)
    ):
        raise ScientificTraceError("analog family trace implementation is stale")
    provenance = normalized.get("original_family_provenance")
    if (
        not isinstance(provenance, dict)
        or set(provenance) != _ORIGINAL_FAMILY_PROVENANCE_FIELDS
        or provenance != dict(expected_provenance)
    ):
        raise ScientificTraceError(
            "analog original-family exposure provenance drifted"
        )
    family = _validate_family(
        normalized,
        family_spec=family_spec,
        expected_inventory=expected_inventory,
    )
    windows = _validate_windows(normalized)
    prefix_mismatches = _validate_invariance(
        normalized,
        family_spec=family_spec,
        windows=windows,
    )
    trades = _validate_trades(
        normalized,
        family=family,
        windows=windows,
        horizon=family_spec.horizon,
    )
    _, intent_counts = _validate_intents(
        normalized,
        family=family,
        windows=windows,
        trades=trades,
        horizon=family_spec.horizon,
    )
    daily = _validate_eligible_days(
        normalized,
        family=family,
        windows=windows,
        trades=trades,
    )
    return {
        "daily": daily,
        "family": family,
        "intent_counts": intent_counts,
        "normalized": normalized,
        "prefix_mismatches": prefix_mismatches,
        "trades": trades,
        "windows": windows,
    }


def validate_analog_family_trace(
    trace: Mapping[str, Any],
) -> dict[str, object]:
    """Validate one frozen reconstruction artifact against legacy authority."""

    family = _legacy_family()
    return dict(
        _validated_family_trace_parts(
            trace,
            family_spec=family,
            expected_inventory=expected_analog_family_inventory(family),
            expected_implementation_identities=(
                analog_family_trace_implementation_identities()
            ),
            expected_provenance=analog_original_family_provenance(family),
        )["normalized"]
    )


def validate_bound_analog_family_trace(
    trace: Mapping[str, Any],
    *,
    family_spec: AnalogFamilySpec,
    expected_inventory: tuple[dict[str, object], ...],
    expected_implementation_identities: Mapping[str, str],
    expected_provenance: Mapping[str, object],
) -> dict[str, object]:
    """Validate prospective rows only against caller-bound typed authority."""

    return dict(
        _validated_family_trace_parts(
            trace,
            family_spec=family_spec,
            expected_inventory=expected_inventory,
            expected_implementation_identities=expected_implementation_identities,
            expected_provenance=expected_provenance,
        )["normalized"]
    )


def validate_analog_family_trace_cache_manifest(
    value: Mapping[str, Any],
) -> dict[str, object]:
    """Validate the exact first-Job provenance embedded in a durable trace."""

    if not isinstance(value, Mapping) or set(value) != _CACHE_MANIFEST_FIELDS:
        raise ScientificTraceError("analog family cache manifest schema is invalid")
    try:
        manifest = parse_canonical(canonical_bytes(value))
    except (TypeError, ValueError) as exc:
        raise ScientificTraceError(
            "analog family cache manifest is not canonical"
        ) from exc
    if not isinstance(manifest, dict):
        raise ScientificTraceError("analog family cache manifest is not an object")
    producer = manifest.get("producer_execution")
    if not isinstance(producer, dict) or set(producer) != (
        _PRODUCER_EXECUTION_FIELDS
    ):
        raise ScientificTraceError("analog family cache producer is invalid")
    producer_payload = {
        name: producer[name]
        for name in _PRODUCER_EXECUTION_FIELDS
        if name != "identity"
    }
    for name in ("job_hash", "job_permit_id", "start_record_id"):
        _digest(f"analog cache producer {name}", producer_payload[name])
    job_id = _ascii("analog cache producer job_id", producer_payload["job_id"])
    if not job_id.startswith("job:") or len(job_id) != 68:
        raise ScientificTraceError("analog family cache producer Job is invalid")
    if producer.get("identity") != canonical_digest(
        domain="running-job-execution",
        payload=producer_payload,
    ):
        raise ScientificTraceError("analog family cache producer identity drifted")
    inventory = expected_analog_family_inventory()
    expected_producer = str(inventory[0]["executable_id"])
    if (
        manifest.get("schema")
        != ANALOG_FAMILY_TRACE_CACHE_MANIFEST_SCHEMA
        or manifest.get("cache_schema") != ANALOG_FAMILY_TRACE_SCHEMA
        or manifest.get("claim_authority") is not False
        or manifest.get("dataset_sha256") != DATASET_SHA256
        or manifest.get("family_id") != _legacy_family().family_id
        or manifest.get("implementation_identities")
        != analog_family_trace_implementation_identities()
        or manifest.get("material_identity") != OBSERVED_MATERIAL_ID
        or manifest.get("producer_executable_id") != expected_producer
        or manifest.get("split_artifact_sha256") != ROLLING_SPLIT_SHA256
    ):
        raise ScientificTraceError("analog family cache manifest drifted")
    _ascii("analog cache output name", manifest.get("cache_output_name"))
    _digest("analog cache sha256", manifest.get("cache_sha256"))
    _ascii("analog cache manifest output", manifest.get("manifest_output_name"))
    _ascii("analog cache Mission", manifest.get("mission_id"))
    _ascii("analog cache Study", manifest.get("study_id"))
    return dict(manifest)


def _validated_cache_binding(
    value: object,
    *,
    family_trace_sha256: str,
) -> dict[str, object]:
    binding = _mapping("analog cache binding", value)
    schema = binding.get("schema")
    if schema == ANALOG_FAMILY_TRACE_DIRECT_BINDING_SCHEMA:
        if (
            set(binding) != _DIRECT_BINDING_FIELDS
            or binding.get("claim_authority") is not False
            or binding.get("source")
            != "direct_recomputation_no_reproducible_cache"
        ):
            raise ScientificTraceError("analog direct trace binding is invalid")
        return dict(binding)
    if schema == ANALOG_FAMILY_TRACE_CACHE_MANIFEST_SCHEMA:
        manifest = validate_analog_family_trace_cache_manifest(binding)
        if manifest["cache_sha256"] != family_trace_sha256:
            raise ScientificTraceError(
                "analog cache manifest differs from embedded family rows"
            )
        return manifest
    raise ScientificTraceError("analog trace cache binding is not typed")


def _subject_neutral_trace(trace: Mapping[str, Any]) -> dict[str, object]:
    attribution = _mapping(
        "analog subject attribution",
        trace.get("attribution"),
    )
    if set(attribution) != _SUBJECT_ATTRIBUTION_FIELDS:
        raise ScientificTraceError("analog subject attribution schema is invalid")
    binding = _mapping(
        "analog family trace binding",
        attribution.get("family_trace_binding"),
    )
    if set(binding) != _FAMILY_TRACE_BINDING_FIELDS:
        raise ScientificTraceError("analog family trace binding schema is invalid")
    common = (_FAMILY_TRACE_FIELDS & _SUBJECT_TRACE_FIELDS) - {
        "attribution",
        "schema",
    }
    return {
        **{name: trace[name] for name in common},
        "attribution": attribution["protocol_attribution"],
        "clock_contract": binding["clock_contract"],
        "cost_contract": binding["cost_contract"],
        "implementation_identities": binding["implementation_identities"],
        "original_family_provenance": binding[
            "original_family_provenance"
        ],
        "schema": binding["schema"],
    }


def _validated_subject_trace_parts(
    trace: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(trace, Mapping) or set(trace) != _SUBJECT_TRACE_FIELDS:
        raise ScientificTraceError("analog subject trace schema is invalid")
    if trace.get("schema") != SCIENTIFIC_EVALUATION_TRACE_SCHEMA:
        raise ScientificTraceError("analog subject trace schema is invalid")
    if trace.get("adapter_implementation_sha256") != (
        analog_trace_implementation_sha256()
    ):
        raise ScientificTraceError("analog subject trace adapter drifted")
    _ascii("analog trace mission_id", trace.get("mission_id"))
    _ascii("analog trace job_id", trace.get("job_id"))
    _digest("analog trace job_hash", trace.get("job_hash"))
    subject_id = _ascii(
        "analog trace subject_executable_id",
        trace.get("subject_executable_id"),
    )
    neutral = _subject_neutral_trace(trace)
    neutral_hash = sha256(canonical_bytes(neutral)).hexdigest()
    attribution = _mapping("analog subject attribution", trace["attribution"])
    binding = _mapping(
        "analog family trace binding",
        attribution["family_trace_binding"],
    )
    if binding.get("family_trace_sha256") != neutral_hash:
        raise ScientificTraceError("analog subject trace family binding drifted")
    _validated_cache_binding(
        binding.get("cache_manifest"),
        family_trace_sha256=neutral_hash,
    )
    family = _legacy_family()
    parts = _validated_family_trace_parts(
        neutral,
        family_spec=family,
        expected_inventory=expected_analog_family_inventory(family),
        expected_implementation_identities=(
            analog_family_trace_implementation_identities()
        ),
        expected_provenance=analog_original_family_provenance(family),
    )
    if subject_id not in {
        item["executable_id"] for item in parts["family"].values()
    }:
        raise ScientificTraceError("analog trace subject is outside its family")
    return {**parts, "subject_id": subject_id}


def extract_analog_family_trace_from_subject(
    trace: Mapping[str, Any],
) -> dict[str, object]:
    """Recover canonical family-neutral rows from one durable subject trace."""

    parts = _validated_subject_trace_parts(trace)
    neutral = dict(parts["normalized"])
    canonical_bytes(neutral)
    return neutral


def extract_analog_family_trace_cache_binding(
    trace: Mapping[str, Any],
) -> dict[str, object]:
    """Return the strict producer manifest carried by any valid subject trace."""

    _, manifest = extract_analog_family_trace_cache_material(trace)
    return manifest


def extract_analog_family_trace_cache_material(
    trace: Mapping[str, Any],
    *,
    require_producer: bool = False,
) -> tuple[dict[str, object], dict[str, object]]:
    """Open one cache-bound trace and recover its durable neutral material."""

    if type(require_producer) is not bool:
        raise ScientificTraceError("analog producer requirement must be boolean")
    parts = _validated_subject_trace_parts(trace)
    attribution = _mapping("analog subject attribution", trace["attribution"])
    family_binding = _mapping(
        "analog subject family binding",
        attribution["family_trace_binding"],
    )
    cache_binding = _mapping(
        "analog subject cache manifest",
        family_binding["cache_manifest"],
    )
    if cache_binding.get("schema") != ANALOG_FAMILY_TRACE_CACHE_MANIFEST_SCHEMA:
        raise ScientificTraceError(
            "analog subject trace does not bind a producer cache manifest"
        )
    manifest = validate_analog_family_trace_cache_manifest(cache_binding)
    if require_producer:
        producer = _mapping(
            "analog producer execution",
            manifest["producer_execution"],
        )
        if (
            trace.get("mission_id") != manifest["mission_id"]
            or trace.get("subject_executable_id")
            != manifest["producer_executable_id"]
            or trace.get("job_id") != producer["job_id"]
            or trace.get("job_hash") != producer["job_hash"]
        ):
            raise ScientificTraceError(
                "analog cache manifest belongs to another producer trace"
            )
    neutral = dict(parts["normalized"])
    if sha256(canonical_bytes(neutral)).hexdigest() != manifest["cache_sha256"]:
        raise ScientificTraceError(
            "analog producer cache hash differs from durable family rows"
        )
    return neutral, manifest


def extract_analog_family_trace_cache_manifest(
    trace: Mapping[str, Any],
) -> dict[str, object]:
    """Open a complete producer trace and return its strict cache manifest."""

    _, manifest = extract_analog_family_trace_cache_material(
        trace,
        require_producer=True,
    )
    return manifest


def bind_analog_family_trace(
    *,
    family_trace: Mapping[str, Any],
    mission_id: str,
    executable_id: str,
    job_id: str,
    job_hash: str,
    cache_manifest: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """Create a complete subject-bound proof from neutral cached family rows."""

    normalized = validate_analog_family_trace(family_trace)
    family_ids = {
        str(item["executable_id"])
        for item in normalized["ordered_family"]  # type: ignore[index]
    }
    subject_id = _ascii("analog replay executable_id", executable_id)
    if subject_id not in family_ids:
        raise ScientificTraceError("analog replay subject is outside its family")
    neutral_bytes = canonical_bytes(normalized)
    cache_binding = (
        {
            "claim_authority": False,
            "schema": ANALOG_FAMILY_TRACE_DIRECT_BINDING_SCHEMA,
            "source": "direct_recomputation_no_reproducible_cache",
        }
        if cache_manifest is None
        else validate_analog_family_trace_cache_manifest(cache_manifest)
    )
    family_binding = {
        "cache_manifest": cache_binding,
        "clock_contract": normalized["clock_contract"],
        "cost_contract": normalized["cost_contract"],
        "family_trace_sha256": sha256(neutral_bytes).hexdigest(),
        "implementation_identities": normalized[
            "implementation_identities"
        ],
        "original_family_provenance": normalized[
            "original_family_provenance"
        ],
        "schema": ANALOG_FAMILY_TRACE_SCHEMA,
    }
    common = (_FAMILY_TRACE_FIELDS & _SUBJECT_TRACE_FIELDS) - {
        "attribution",
        "schema",
    }
    value = {
        **{name: normalized[name] for name in common},
        "adapter_implementation_sha256": (
            analog_trace_implementation_sha256()
        ),
        "attribution": {
            "family_trace_binding": family_binding,
            "protocol_attribution": normalized["attribution"],
        },
        "job_hash": _digest("analog replay job_hash", job_hash),
        "job_id": _ascii("analog replay job_id", job_id),
        "mission_id": _ascii("analog replay mission_id", mission_id),
        "schema": SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
        "subject_executable_id": subject_id,
    }
    _validated_subject_trace_parts(value)
    canonical_bytes(value)
    return value


def _profit_factor(values: Sequence[int]) -> int:
    gain = sum(value for value in values if value > 0)
    loss = -sum(value for value in values if value < 0)
    if loss <= 0:
        return 1_000_000 if gain > 0 else 0
    return min(1_000_000, int(round(1000 * gain / loss)))


def _monthly_drawdown_share(trades: Sequence[Mapping[str, Any]]) -> int:
    by_month: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for trade in sorted(trades, key=lambda item: (item["exit_time"], item["observation_id"])):
        by_month[str(trade["exit_time"])[:7]].append(trade)
    worst_share = 0
    for values in by_month.values():
        equity = 0
        peak = 0
        drawdown = 0
        gross_profit = 0
        for trade in values:
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
            else min(1_000_000_000, ceil(1_000_000 * drawdown / gross_profit))
        )
        worst_share = max(worst_share, share)
    return worst_share


def _selection_plan(
    *,
    family_id: str,
    hypothesis_ids: tuple[str, ...],
    registration_ids: Mapping[str, str],
    parameters: Mapping[str, Any],
) -> SelectionFamilyPlan:
    return SelectionFamilyPlan(
        family_id=family_id,
        stage="discovery",
        hypotheses=tuple(
            SelectionHypothesis(
                hypothesis_id=hypothesis_id,
                registration_id=registration_ids[hypothesis_id],
            )
            for hypothesis_id in sorted(hypothesis_ids)
        ),
        alpha_ppm=int(parameters["alpha_ppm"]),
        bootstrap_samples=int(parameters["bootstrap_samples"]),
        block_lengths=tuple(parameters["block_lengths"]),
        monte_carlo_confidence_ppm=int(parameters["monte_carlo_confidence_ppm"]),
        base_seed=int(parameters["base_seed"]),
    )


def _derive_metrics_and_statistics(
    *,
    trace: Mapping[str, Any],
    parameters: Mapping[str, Any],
) -> tuple[dict[str, dict[str, int]], dict[str, object]]:
    if set(parameters) != _CALCULATION_PARAMETER_FIELDS or dict(parameters) != analog_calculation_parameters():
        raise ScientificTraceError("analog calculation parameters drifted")
    parts = _validated_subject_trace_parts(trace)
    family = parts["family"]
    prefix_mismatches = parts["prefix_mismatches"]
    trades = parts["trades"]
    intent_counts = parts["intent_counts"]
    daily = parts["daily"]
    subject_id = parts["subject_id"]
    subject_member = next(item for item in family.values() if item["executable_id"] == subject_id)
    subject_configuration = str(subject_member["configuration_id"])
    append_mismatches, causality, unknown_cost = intent_counts[
        subject_configuration
    ]
    subject_trades = tuple(item for item in trades if item["executable_id"] == subject_id)
    opposite = next(
        item
        for item in family.values()
        if item["profile_id"] == subject_member["profile_id"]
        and item["signal_sign"] == -subject_member["signal_sign"]
    )
    feature = next(
        item
        for item in family.values()
        if item["profile_id"] != subject_member["profile_id"]
        and item["signal_sign"] == subject_member["signal_sign"]
    )
    historical_context = HistoricalSearchContext(
        context_id=ANALOG_REPLAY_HISTORICAL_CONTEXT_ID,
        prior_global_exposure_count=int(
            parameters["historical_context_prior_global_exposure_count"]
        ),
    )
    family_ids = tuple(str(item["executable_id"]) for item in family.values())
    registration_ids = {
        str(item["executable_id"]): (
            f"historical-reference:{item['historical_reference_executable_id']}"
        )
        for item in family.values()
    }
    selection_result = infer_concurrent_selection_family(
        plan=_selection_plan(
            family_id=str(parts["normalized"]["family_id"]),
            hypothesis_ids=family_ids,
            registration_ids=registration_ids,
            parameters=parameters,
        ),
        daily_pnl_by_hypothesis=daily,
        historical_context=historical_context,
    )
    control_series = {
        "paired-control:feature": {
            day: daily[subject_id][day] - daily[str(feature["executable_id"])][day]
            for day in daily[subject_id]
        },
        "paired-control:opposite": {
            day: daily[subject_id][day] - daily[str(opposite["executable_id"])][day]
            for day in daily[subject_id]
        },
    }
    control_ids = tuple(control_series)
    control_result = infer_concurrent_selection_family(
        plan=_selection_plan(
            family_id=f"family:{subject_configuration}:paired-controls-v1",
            hypothesis_ids=control_ids,
            registration_ids={
                "paired-control:feature": str(feature["historical_reference_executable_id"]),
                "paired-control:opposite": str(opposite["historical_reference_executable_id"]),
            },
            parameters=parameters,
        ),
        daily_pnl_by_hypothesis=control_series,
        historical_context=historical_context,
    )
    subject_selection = selection_result.hypothesis(subject_id)
    feature_control = control_result.hypothesis("paired-control:feature")
    opposite_control = control_result.hypothesis("paired-control:opposite")
    native_values = [int(item["native_net_pnl_micropoints"]) for item in subject_trades]
    stress_values = [int(item["stress_net_pnl_micropoints"]) for item in subject_trades]
    subject_daily = daily[subject_id]
    positive_days = sorted((value for value in subject_daily.values() if value > 0), reverse=True)
    gross_positive = sum(positive_days)
    top5_share = 0 if gross_positive <= 0 else min(1_000_000, int(round(1_000_000 * sum(positive_days[:5]) / gross_positive)))
    fold_values = {
        fold_id: [
            int(item["native_net_pnl_micropoints"])
            for item in subject_trades
            if item["fold_id"] == fold_id
        ]
        for fold_id in EXPECTED_FOLD_IDS
    }
    fold_profit_factors = sorted(_profit_factor(values) for values in fold_values.values())
    regime_values: dict[str, dict[str, list[int]]] = {
        regime: {fold_id: [] for fold_id in EXPECTED_FOLD_IDS}
        for regime in sorted(_ALLOWED_REGIMES)
    }
    for trade in subject_trades:
        regime_values[str(trade["regime"])][str(trade["fold_id"])].append(
            int(trade["native_net_pnl_micropoints"])
        )
    supported_regimes = 0
    for by_fold in regime_values.values():
        trade_count = sum(len(values) for values in by_fold.values())
        evaluable = sum(bool(values) for values in by_fold.values())
        winning = sum(sum(values) > 0 for values in by_fold.values() if values)
        if (
            sum(sum(values) for values in by_fold.values()) > 0
            and trade_count >= 30
            and evaluable >= 5
            and winning >= 3
            and 2 * winning > evaluable
        ):
            supported_regimes += 1
    opposite_net = sum(daily[str(opposite["executable_id"])].values())
    feature_net = sum(daily[str(feature["executable_id"])].values())
    net = sum(native_values)
    metrics = {
        "activity_and_concentration": {
            "entries_per_day_milli": int(round(1000 * len(subject_trades) / len(subject_daily))),
            "top5_profit_day_share_ppm": top5_share,
            "trade_count": len(subject_trades),
        },
        "after_cost_fixed_lot_economics": {
            "median_fold_profit_factor_milli": fold_profit_factors[len(fold_profit_factors) // 2],
            "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": _monthly_drawdown_share(subject_trades),
            "net_profit_micropoints": net,
            "stress_net_profit_micropoints": sum(stress_values),
        },
        "causal_feature_and_execution_validity": {
            "append_invariance_mismatch_count": append_mismatches,
            "causality_violation_count": causality,
            "nonfinite_metric_count": 0,
            "prefix_invariance_mismatch_count": prefix_mismatches,
            "unknown_cost_unresolved_signal_count": unknown_cost,
        },
        "registered_control_contrast": {
            "feature_control_worst_delta_net_profit_micropoints": net - feature_net,
            "feature_control_worst_pvalue_upper_ppm": feature_control.synchronized_max_monte_carlo_upper_pvalue_ppm,
            "opposite_sign_pvalue_upper_ppm": opposite_control.synchronized_max_monte_carlo_upper_pvalue_ppm,
            "opposite_sign_worst_delta_net_profit_micropoints": net - opposite_net,
        },
        "selection_aware_signal_evidence": {
            "selection_aware_pvalue_ppm": subject_selection.synchronized_max_monte_carlo_upper_pvalue_ppm,
        },
        "temporal_and_regime_stability": {
            "evaluable_folds": sum(bool(values) for values in fold_values.values()),
            "supported_positive_regime_count": supported_regimes,
            "winning_fold_count": sum(sum(values) > 0 for values in fold_values.values() if values),
        },
    }
    statistics = {
        "exposure_semantics": {
            "exact_concurrent_family_adjustment_factor": (
                selection_result.plan.family_size
            ),
            "historical_context_adjustment_authority": (
                historical_context.manifest()["adjustment_authority"]
            ),
            "original_family_end_global_exposure_count": (
                ANALOG_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
            ),
            "prospective_prior_global_exposure_count": (
                historical_context.prior_global_exposure_count
            ),
        },
        "historical_context": historical_context.manifest(),
        "paired_control_family": control_result.statistical_manifest(),
        "selection_family": selection_result.statistical_manifest(),
    }
    if (
        selection_result.plan.family_size
        != parameters["exact_concurrent_family_adjustment_factor"]
        or historical_context.manifest()["adjustment_authority"]
        != parameters["historical_context_adjustment_authority"]
        or parameters["original_family_end_global_exposure_count"]
        != ANALOG_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
    ):
        raise ScientificTraceError("analog exposure semantics drifted")
    canonical_bytes(metrics)
    canonical_bytes(statistics)
    return metrics, statistics


def build_analog_trace_calculation(
    *,
    trace: Mapping[str, Any],
    trace_output_name: str,
    trace_hash: str,
) -> dict[str, object]:
    parameters = analog_calculation_parameters()
    metrics, statistics = _derive_metrics_and_statistics(
        trace=trace,
        parameters=parameters,
    )
    value = {
        "evidence_modes": list(ANALOG_REPLAY_EVIDENCE_MODES),
        "executable_id": trace["subject_executable_id"],
        "job_hash": trace["job_hash"],
        "job_id": trace["job_id"],
        "metrics": metrics,
        "mission_id": trace["mission_id"],
        "parameters": parameters,
        "protocol_id": ANALOG_STATE_TRACE_PROTOCOL_ID,
        "schema": SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
        "statistics": statistics,
        "trace": {"output_name": trace_output_name, "sha256": trace_hash},
    }
    canonical_bytes(value)
    return value


def validate_analog_trace_calculation(
    *,
    trace: Mapping[str, Any],
    calculation: Mapping[str, Any],
) -> dict[str, dict[str, int]]:
    parameters = _mapping("analog calculation parameters", calculation.get("parameters"))
    statistics = _mapping("analog calculation statistics", calculation.get("statistics"))
    if set(statistics) != _CALCULATION_STATISTIC_FIELDS:
        raise ScientificTraceError("analog calculation statistics schema is invalid")
    metrics, expected_statistics = _derive_metrics_and_statistics(
        trace=trace,
        parameters=parameters,
    )
    if calculation.get("metrics") != metrics:
        raise ScientificTraceError("analog calculation metrics drifted from atomic rows")
    if dict(statistics) != expected_statistics:
        raise ScientificTraceError("analog deterministic resampling proof drifted")
    return metrics


__all__ = [
    "ANALOG_FAMILY_TRACE_CACHE_MANIFEST_SCHEMA",
    "ANALOG_FAMILY_TRACE_DIRECT_BINDING_SCHEMA",
    "ANALOG_FAMILY_TRACE_SCHEMA",
    "ANALOG_REPLAY_CLAIMS",
    "ANALOG_REPLAY_CONTROLS",
    "ANALOG_REPLAY_CRITERIA",
    "ANALOG_REPLAY_EVIDENCE_MODES",
    "ANALOG_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT",
    "ANALOG_REPLAY_PRIOR_GLOBAL_EXPOSURE_COUNT",
    "ANALOG_REPLAY_TRACE_ATTRIBUTION",
    "analog_calculation_parameters",
    "analog_family_execution_contracts",
    "analog_family_trace_implementation_identities",
    "analog_observation_id",
    "analog_original_family_provenance",
    "analog_trace_implementation_sha256",
    "bind_analog_family_trace",
    "build_analog_trace_calculation",
    "expected_analog_family_inventory",
    "extract_analog_family_trace_cache_binding",
    "extract_analog_family_trace_cache_manifest",
    "extract_analog_family_trace_cache_material",
    "extract_analog_family_trace_from_subject",
    "validate_analog_family_trace",
    "validate_bound_analog_family_trace",
    "validate_analog_family_trace_cache_manifest",
    "validate_analog_trace_calculation",
]
