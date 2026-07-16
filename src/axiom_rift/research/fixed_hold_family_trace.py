"""Closed atomic proof for declarative fixed-hold replay families.

The durable trace contains data, never executable behavior.  Every public
validation helper receives a typed, repository-owned family definition and the
closed validator explicitly.  No callback name, module path, or import path is
read from durable payloads.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime
from hashlib import sha256
from math import ceil
from pathlib import Path
from types import MappingProxyType
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.completed_period_atomic_trace import (
    completed_period_atomic_trace_implementation_sha256,
    validate_completed_period_fixed_hold_sources,
)
from axiom_rift.research.fixed_hold_historical_projection import (
    derive_fixed_hold_semantic_surfaces,
    fixed_hold_historical_projection_implementation_sha256,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyBindingError,
    HistoricalFamilyLike,
    historical_family_from_manifest,
)
from axiom_rift.research.historical_semantic_transition import (
    HISTORICAL_COST_TIMING_TRANSITION_POLICY,
    NO_SEMANTIC_TRANSITION_POLICY,
    historical_semantic_transition_implementation_sha256,
    validate_historical_semantic_transition_inventory,
)
from axiom_rift.research.scientific_trace import (
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


FIXED_HOLD_FAMILY_TRACE_SCHEMA = "fixed_hold_family_trace.v4"
FIXED_HOLD_PROTOCOL_DEFINITION_SCHEMA = "fixed_hold_protocol_definition.v3"
FIXED_HOLD_TRACE_VALIDATOR_SCHEMA = "fixed_hold_trace_validator.v3"
FIXED_HOLD_MEMBER_SCHEMA = "fixed_hold_family_member.v1"
FIXED_HOLD_CONTROL_SCHEMA = "fixed_hold_control_binding.v1"

FIXED_HOLD_REPLAY_EVIDENCE_MODES = (
    "causal_contrast",
    "cost_and_execution",
    "sensitivity_or_stress",
    "temporal_stability",
)
FIXED_HOLD_REPLAY_CLAIMS = (
    "activity_and_concentration",
    "after_cost_fixed_lot_economics",
    "causal_feature_and_execution_validity",
    "registered_control_contrast",
    "selection_aware_signal_evidence",
    "temporal_and_regime_stability",
)

_THIS_FILE = Path(__file__).resolve()

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
    "semantic_transition_evidence",
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
    "semantic_transition_evidence",
    "split_artifact_sha256",
    "subject_executable_id",
    "trade_observations",
    "windows",
}
_CALCULATION_FIELDS = {
    "evidence_modes",
    "executable_id",
    "job_hash",
    "job_id",
    "metrics",
    "mission_id",
    "parameters",
    "protocol_definition",
    "protocol_id",
    "schema",
    "statistics",
    "trace",
}
_PROTOCOL_DEFINITION_FIELDS = {
    "allowed_regimes",
    "clock_contract",
    "cost_contract",
    "dataset_sha256",
    "family_id",
    "fold_ids",
    "historical_context_id",
    "historical_evaluation_artifacts",
    "historical_family",
    "historical_prior_global_exposure_count",
    "inference",
    "inference_family_id",
    "invariance_keys",
    "material_identity",
    "original_family_end_global_exposure_count",
    "producer_implementation_identities",
    "prospective_executable_ids",
    "protocol_id",
    "schema",
    "semantic_transition_policy",
    "split_artifact_sha256",
}
_PROTOCOL_INFERENCE_FIELDS = {
    "alpha_ppm",
    "base_seed",
    "block_lengths",
    "bootstrap_samples",
    "monte_carlo_confidence_ppm",
}
_HISTORICAL_EVALUATION_ARTIFACT_FIELDS = {
    "artifact_sha256",
    "configuration_id",
    "schema",
}
_FAMILY_MEMBER_FIELDS = {
    "configuration_id",
    "executable_id",
    "historical_reference_executable_id",
    "ordinal",
    "parameters",
    "schema",
}
_CONTROL_FIELDS = {
    "feature_executable_ids",
    "feature_historical_executable_ids",
    "opposite_executable_id",
    "opposite_historical_executable_id",
    "schema",
    "subject_executable_id",
    "subject_historical_executable_id",
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
    "full_feature_values_sha256",
    "invariance_key",
    "prefix_feature_values_sha256",
}
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
    "holding_bars",
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
    "holding_bars",
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
_SUBJECT_ATTRIBUTION_FIELDS = {
    "family_trace_binding",
    "protocol_attribution",
}
_FAMILY_TRACE_BINDING_FIELDS = {
    "clock_contract",
    "cost_contract",
    "definition_identity",
    "family_trace_sha256",
    "implementation_identities",
    "original_family_provenance",
    "schema",
    "validator_identity",
}
_CALCULATION_STATISTIC_FIELDS = {
    "exposure_semantics",
    "historical_context",
    "paired_control_family",
    "selection_family",
    "subject_controls",
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
_RESERVED_IMPLEMENTATION_KEYS = frozenset(
    {
        "completed_period_atomic_trace_sha256",
        "fixed_hold_trace_sha256",
        "fixed_hold_historical_projection_sha256",
        "historical_semantic_transition_sha256",
        "selection_inference_sha256",
    }
)


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


FIXED_HOLD_REPLAY_CRITERIA = tuple(
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

_CLAIM_METRIC_FIELDS = {
    claim_id: frozenset(
        str(item["metric"])
        for item in FIXED_HOLD_REPLAY_CRITERIA
        if item["claim_id"] == claim_id
    )
    for claim_id in FIXED_HOLD_REPLAY_CLAIMS
}


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ScientificTraceError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise ScientificTraceError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _identity(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    expected = f"{prefix}:"
    digest = text.removeprefix(expected)
    if text == digest:
        raise ScientificTraceError(f"{name} must start with {expected}")
    _digest(name, digest)
    return text


def _integer(name: str, value: object, *, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ScientificTraceError(f"{name} must be an integer")
    return value


def _mapping(name: str, value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ScientificTraceError(f"{name} must be a mapping")
    return value


def _sequence(
    name: str,
    value: object,
    *,
    allow_empty: bool = False,
) -> Sequence[Any]:
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


def fixed_hold_trace_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _historical_evaluation_artifact_entry(
    value: object,
) -> tuple[str, str, str]:
    artifact = _mapping("historical evaluation artifact", value)
    if set(artifact) != _HISTORICAL_EVALUATION_ARTIFACT_FIELDS:
        raise ScientificTraceError(
            "historical evaluation artifact schema is invalid"
        )
    return (
        _ascii(
            "historical artifact configuration_id",
            artifact.get("configuration_id"),
        ),
        _digest(
            "historical artifact sha256",
            artifact.get("artifact_sha256"),
        ),
        _ascii("historical artifact schema", artifact.get("schema")),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class FixedHoldProtocolDefinition:
    """Code-owned immutable family and inference boundary."""

    family: HistoricalFamilyLike
    prospective_executable_ids: tuple[str, ...]
    protocol_id: str
    fold_ids: tuple[str, ...]
    invariance_keys: tuple[str, ...]
    allowed_regimes: tuple[str, ...]
    dataset_sha256: str
    material_identity: str
    split_artifact_sha256: str
    clock_contract: str
    cost_contract: str
    producer_implementation_identities: tuple[tuple[str, str], ...]
    historical_context_id: str
    historical_prior_global_exposure_count: int
    original_family_end_global_exposure_count: int
    alpha_ppm: int
    bootstrap_samples: int
    block_lengths: tuple[int, ...]
    monte_carlo_confidence_ppm: int
    base_seed: int
    historical_evaluation_artifacts: tuple[tuple[str, str, str], ...] = ()
    semantic_transition_policy: str = NO_SEMANTIC_TRANSITION_POLICY
    family_id: str = field(init=False)
    inference_family_id: str = field(init=False)
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.family, HistoricalFamilyLike):
            raise ScientificTraceError("family must be a typed historical family")
        if (
            type(self.prospective_executable_ids) is not tuple
            or len(self.prospective_executable_ids) != self.family.family_size
        ):
            raise ScientificTraceError(
                "prospective Executable ids must exactly cover the family"
            )
        executables = tuple(
            _identity(
                f"prospective_executable_ids[{index}]",
                value,
                "executable",
            )
            for index, value in enumerate(self.prospective_executable_ids)
        )
        if len(executables) != len(set(executables)):
            raise ScientificTraceError(
                "prospective Executable ids must be unique"
            )
        _ascii("protocol_id", self.protocol_id)
        for name, values in (
            ("fold_ids", self.fold_ids),
            ("invariance_keys", self.invariance_keys),
            ("allowed_regimes", self.allowed_regimes),
        ):
            if type(values) is not tuple or not values:
                raise ScientificTraceError(f"{name} must be a non-empty tuple")
            normalized = tuple(_ascii(f"{name} value", value) for value in values)
            if normalized != tuple(sorted(set(normalized))):
                raise ScientificTraceError(f"{name} must be sorted and unique")
        _digest("dataset_sha256", self.dataset_sha256)
        _ascii("material_identity", self.material_identity)
        _digest("split_artifact_sha256", self.split_artifact_sha256)
        _ascii("clock_contract", self.clock_contract)
        _ascii("cost_contract", self.cost_contract)
        if self.semantic_transition_policy not in {
            NO_SEMANTIC_TRANSITION_POLICY,
            HISTORICAL_COST_TIMING_TRANSITION_POLICY,
        }:
            raise ScientificTraceError(
                "fixed-hold semantic transition policy is invalid"
            )
        if type(self.historical_evaluation_artifacts) is not tuple:
            raise ScientificTraceError(
                "historical evaluation artifacts must be a tuple"
            )
        artifacts: list[tuple[str, str, str]] = []
        for item in self.historical_evaluation_artifacts:
            if type(item) is not tuple or len(item) != 3:
                raise ScientificTraceError(
                    "historical evaluation artifact entries are invalid"
                )
            artifacts.append(
                (
                    _ascii("historical artifact configuration_id", item[0]),
                    _digest("historical artifact sha256", item[1]),
                    _ascii("historical artifact schema", item[2]),
                )
            )
        if tuple(artifacts) != tuple(sorted(set(artifacts))):
            raise ScientificTraceError(
                "historical evaluation artifacts must be sorted and unique"
            )
        artifact_configurations = tuple(item[0] for item in artifacts)
        family_configurations = tuple(
            member.configuration_id for member in self.family.members
        )
        if self.semantic_transition_policy == NO_SEMANTIC_TRANSITION_POLICY:
            if artifacts:
                raise ScientificTraceError(
                    "historical evaluation artifacts require a transition policy"
                )
        elif artifact_configurations != tuple(sorted(family_configurations)):
            raise ScientificTraceError(
                "historical evaluation artifacts must exactly cover the family"
            )
        if (
            type(self.producer_implementation_identities) is not tuple
            or not self.producer_implementation_identities
        ):
            raise ScientificTraceError(
                "producer implementation identities must be a non-empty tuple"
            )
        implementations: list[tuple[str, str]] = []
        for item in self.producer_implementation_identities:
            if type(item) is not tuple or len(item) != 2:
                raise ScientificTraceError(
                    "producer implementation identity entries are invalid"
                )
            key = _ascii("implementation identity key", item[0])
            if key in _RESERVED_IMPLEMENTATION_KEYS:
                raise ScientificTraceError(
                    "producer implementation identity uses a reserved key"
                )
            implementations.append(
                (key, _digest("implementation identity digest", item[1]))
            )
        implementation_keys = tuple(item[0] for item in implementations)
        if (
            tuple(implementations) != tuple(sorted(set(implementations)))
            or len(implementation_keys) != len(set(implementation_keys))
        ):
            raise ScientificTraceError(
                "producer implementation identities must be sorted and unique"
            )
        _ascii("historical_context_id", self.historical_context_id)
        _integer(
            "historical_prior_global_exposure_count",
            self.historical_prior_global_exposure_count,
            minimum=0,
        )
        _integer(
            "original_family_end_global_exposure_count",
            self.original_family_end_global_exposure_count,
            minimum=0,
        )
        holding_bars_by_historical: dict[str, int] = {}
        for member in self.family.members:
            parameters = _mapping(
                "fixed-hold historical member parameters",
                member.parameter_values(),
            )
            holding_bars_by_historical[
                member.historical_reference_executable_id
            ] = _integer(
                "fixed-hold historical member holding_bars",
                parameters.get("holding_bars"),
                minimum=1,
            )
        for control in self.family.controls:
            subject_holding = holding_bars_by_historical[
                control.subject_historical_executable_id
            ]
            matched_controls = (
                control.opposite_historical_executable_id,
                *control.feature_historical_executable_ids,
            )
            if any(
                holding_bars_by_historical[value] != subject_holding
                for value in matched_controls
            ):
                raise ScientificTraceError(
                    "fixed-hold controls must share the subject holding interval"
                )
        inventory = tuple(
            {
                "configuration_id": member.configuration_id,
                "executable_id": executable_id,
                "historical_reference_executable_id": (
                    member.historical_reference_executable_id
                ),
                "ordinal": member.ordinal,
                "parameters": member.parameter_values(),
                "schema": FIXED_HOLD_MEMBER_SCHEMA,
            }
            for member, executable_id in zip(
                self.family.members,
                executables,
                strict=True,
            )
        )
        family_digest = canonical_digest(
            domain="fixed-hold-prospective-family",
            payload={
                "historical_family_identity": self.family.identity,
                "ordered_family": list(inventory),
            },
        )
        object.__setattr__(self, "family_id", f"family:{family_digest}")
        inference_family_digest = canonical_digest(
            domain="fixed-hold-inference-family-registration",
            payload={
                "historical_context_id": self.historical_context_id,
                "historical_family_identity": self.family.identity,
                "protocol_id": self.protocol_id,
            },
        )
        object.__setattr__(
            self,
            "inference_family_id",
            f"family:{inference_family_digest}",
        )
        plan = SelectionFamilyPlan(
            family_id=self.inference_family_id,
            stage="discovery",
            hypotheses=tuple(
                SelectionHypothesis(
                    hypothesis_id=executable_id,
                    registration_id=(
                        "historical-reference:"
                        f"{member.historical_reference_executable_id}"
                    ),
                )
                for member, executable_id in sorted(
                    zip(self.family.members, executables, strict=True),
                    key=lambda item: item[1],
                )
            ),
            alpha_ppm=self.alpha_ppm,
            bootstrap_samples=self.bootstrap_samples,
            block_lengths=self.block_lengths,
            monte_carlo_confidence_ppm=self.monte_carlo_confidence_ppm,
            base_seed=self.base_seed,
        )
        if plan.family_size != self.family.family_size:
            raise RuntimeError("fixed-hold family plan lost a member")
        definition_digest = canonical_digest(
            domain="fixed-hold-protocol-definition",
            payload=self.manifest(),
        )
        object.__setattr__(
            self,
            "identity",
            f"fixed-hold-definition:{definition_digest}",
        )

    def manifest(self) -> dict[str, object]:
        return {
            "allowed_regimes": list(self.allowed_regimes),
            "clock_contract": self.clock_contract,
            "cost_contract": self.cost_contract,
            "dataset_sha256": self.dataset_sha256,
            "family_id": self.family_id,
            "fold_ids": list(self.fold_ids),
            "historical_context_id": self.historical_context_id,
            "historical_evaluation_artifacts": [
                {
                    "artifact_sha256": artifact_sha256,
                    "configuration_id": configuration_id,
                    "schema": schema,
                }
                for configuration_id, artifact_sha256, schema in (
                    self.historical_evaluation_artifacts
                )
            ],
            "historical_family": self.family.manifest(),
            "historical_prior_global_exposure_count": (
                self.historical_prior_global_exposure_count
            ),
            "inference": {
                "alpha_ppm": self.alpha_ppm,
                "base_seed": self.base_seed,
                "block_lengths": list(self.block_lengths),
                "bootstrap_samples": self.bootstrap_samples,
                "monte_carlo_confidence_ppm": (
                    self.monte_carlo_confidence_ppm
                ),
            },
            "inference_family_id": self.inference_family_id,
            "invariance_keys": list(self.invariance_keys),
            "material_identity": self.material_identity,
            "original_family_end_global_exposure_count": (
                self.original_family_end_global_exposure_count
            ),
            "producer_implementation_identities": dict(
                self.producer_implementation_identities
            ),
            "prospective_executable_ids": list(
                self.prospective_executable_ids
            ),
            "protocol_id": self.protocol_id,
            "schema": FIXED_HOLD_PROTOCOL_DEFINITION_SCHEMA,
            "semantic_transition_policy": self.semantic_transition_policy,
            "split_artifact_sha256": self.split_artifact_sha256,
        }

    def historical_artifacts_by_configuration(
        self,
    ) -> dict[str, dict[str, str]]:
        return {
            configuration_id: {
                "artifact_sha256": artifact_sha256,
                "schema": schema,
            }
            for configuration_id, artifact_sha256, schema in (
                self.historical_evaluation_artifacts
            )
        }


def fixed_hold_protocol_definition_from_manifest(
    value: object,
) -> FixedHoldProtocolDefinition:
    """Parse a complete ID-free protocol definition without producer imports."""

    if type(value) is not dict:
        raise ScientificTraceError(
            "fixed-hold protocol definition must be an object"
        )
    try:
        normalized = parse_canonical(canonical_bytes(value))
    except (TypeError, ValueError) as exc:
        raise ScientificTraceError(
            "fixed-hold protocol definition is not canonical"
        ) from exc
    if (
        type(normalized) is not dict
        or set(normalized) != _PROTOCOL_DEFINITION_FIELDS
        or normalized.get("schema") != FIXED_HOLD_PROTOCOL_DEFINITION_SCHEMA
    ):
        raise ScientificTraceError(
            "fixed-hold protocol definition schema is invalid"
        )
    inference = normalized.get("inference")
    implementations = normalized.get("producer_implementation_identities")
    historical_artifacts = normalized.get("historical_evaluation_artifacts")
    if (
        type(inference) is not dict
        or set(inference) != _PROTOCOL_INFERENCE_FIELDS
        or type(implementations) is not dict
        or not implementations
        or type(historical_artifacts) is not list
    ):
        raise ScientificTraceError(
            "fixed-hold protocol definition internals are invalid"
        )
    try:
        family = historical_family_from_manifest(
            normalized.get("historical_family")
        )
        definition = FixedHoldProtocolDefinition(
            family=family,
            prospective_executable_ids=tuple(
                _sequence(
                    "prospective_executable_ids",
                    normalized.get("prospective_executable_ids"),
                )
            ),
            protocol_id=_ascii("protocol_id", normalized.get("protocol_id")),
            fold_ids=tuple(
                _sequence("fold_ids", normalized.get("fold_ids"))
            ),
            invariance_keys=tuple(
                _sequence(
                    "invariance_keys",
                    normalized.get("invariance_keys"),
                )
            ),
            allowed_regimes=tuple(
                _sequence(
                    "allowed_regimes",
                    normalized.get("allowed_regimes"),
                )
            ),
            dataset_sha256=_digest(
                "dataset_sha256", normalized.get("dataset_sha256")
            ),
            material_identity=_ascii(
                "material_identity", normalized.get("material_identity")
            ),
            split_artifact_sha256=_digest(
                "split_artifact_sha256",
                normalized.get("split_artifact_sha256"),
            ),
            clock_contract=_ascii(
                "clock_contract", normalized.get("clock_contract")
            ),
            cost_contract=_ascii(
                "cost_contract", normalized.get("cost_contract")
            ),
            producer_implementation_identities=tuple(
                sorted(
                    (
                        _ascii("implementation identity key", key),
                        _digest("implementation identity digest", digest),
                    )
                    for key, digest in implementations.items()
                )
            ),
            historical_context_id=_ascii(
                "historical_context_id",
                normalized.get("historical_context_id"),
            ),
            historical_evaluation_artifacts=tuple(
                _historical_evaluation_artifact_entry(item)
                for item in historical_artifacts
            ),
            historical_prior_global_exposure_count=_integer(
                "historical_prior_global_exposure_count",
                normalized.get("historical_prior_global_exposure_count"),
                minimum=0,
            ),
            original_family_end_global_exposure_count=_integer(
                "original_family_end_global_exposure_count",
                normalized.get(
                    "original_family_end_global_exposure_count"
                ),
                minimum=0,
            ),
            alpha_ppm=_integer(
                "alpha_ppm", inference.get("alpha_ppm"), minimum=1
            ),
            bootstrap_samples=_integer(
                "bootstrap_samples",
                inference.get("bootstrap_samples"),
                minimum=1,
            ),
            block_lengths=tuple(
                _sequence(
                    "block_lengths", inference.get("block_lengths")
                )
            ),
            monte_carlo_confidence_ppm=_integer(
                "monte_carlo_confidence_ppm",
                inference.get("monte_carlo_confidence_ppm"),
                minimum=1,
            ),
            base_seed=_integer(
                "base_seed", inference.get("base_seed"), minimum=0
            ),
            semantic_transition_policy=_ascii(
                "semantic_transition_policy",
                normalized.get("semantic_transition_policy"),
            ),
        )
    except HistoricalFamilyBindingError as exc:
        raise ScientificTraceError(
            "fixed-hold historical family definition is invalid"
        ) from exc
    if (
        normalized.get("family_id") != definition.family_id
        or normalized.get("inference_family_id")
        != definition.inference_family_id
        or normalized != definition.manifest()
    ):
        raise ScientificTraceError(
            "fixed-hold protocol definition identity drifted"
        )
    return definition


@dataclass(frozen=True, slots=True)
class FixedHoldTraceValidator:
    """The one closed M5 next-open, fixed-row-hold validator."""

    @property
    def identity(self) -> str:
        digest = canonical_digest(
            domain="fixed-hold-trace-validator",
            payload=self.manifest(),
        )
        return f"fixed-hold-validator:{digest}"

    def manifest(self) -> dict[str, object]:
        return {
            "completed_period_atomic_trace_sha256": (
                completed_period_atomic_trace_implementation_sha256()
            ),
            "decision_availability": "completed_m5_bar_plus_5_minutes",
            "entry_index_rule": "entry_bar_index_equals_decision_bar_index_plus_1",
            "fixed_hold_rule": "exit_bar_index_minus_entry_bar_index_equals_holding_bars",
            "historical_semantic_transition_sha256": (
                historical_semantic_transition_implementation_sha256()
            ),
            "implementation_sha256": fixed_hold_trace_implementation_sha256(),
            "schema": FIXED_HOLD_TRACE_VALIDATOR_SCHEMA,
        }


FIXED_HOLD_TRACE_VALIDATOR = FixedHoldTraceValidator()


_TRACE_SNAPSHOT_AUTHORITY = object()


def _freeze_snapshot_value(value: Any) -> Any:
    """Detach validated derivations from every caller-mutable container."""

    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): _freeze_snapshot_value(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_snapshot_value(item) for item in value)
    return value


class _SealedTraceSnapshotPayload:
    """Indivisible normalized bytes projection and optional derived facts."""

    __slots__ = ("__bindings", "__normalized", "__parts")

    def __init__(
        self,
        *,
        authority: object,
        bindings: tuple[tuple[str, str], ...],
        normalized: dict[str, object],
        parts: Mapping[str, Any] | None = None,
    ) -> None:
        if (
            authority is not _TRACE_SNAPSHOT_AUTHORITY
            or type(normalized) is not dict
            or not bindings
            or tuple(name for name, _ in bindings)
            != tuple(sorted({name for name, _ in bindings}))
        ):
            raise ScientificTraceError(
                "fixed-hold snapshot payload lacks validation authority"
            )
        object.__setattr__(
            self,
            "_SealedTraceSnapshotPayload__bindings",
            bindings,
        )
        object.__setattr__(
            self,
            "_SealedTraceSnapshotPayload__normalized",
            normalized,
        )
        object.__setattr__(
            self,
            "_SealedTraceSnapshotPayload__parts",
            None if parts is None else _freeze_snapshot_value(parts),
        )

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("validated fixed-hold payloads are immutable")

    def require(
        self,
        bindings: tuple[tuple[str, str], ...],
    ) -> _SealedTraceSnapshotPayload:
        if self.__bindings != bindings:
            raise ScientificTraceError(
                "fixed-hold snapshot payload binding drifted"
            )
        return self

    def detached(self) -> dict[str, object]:
        return deepcopy(self.__normalized)

    def normalized(self, authority: object) -> dict[str, object]:
        if authority is not _TRACE_SNAPSHOT_AUTHORITY:
            raise ScientificTraceError(
                "fixed-hold snapshot projection lacks validation authority"
            )
        return self.__normalized

    def parts(self, authority: object) -> Mapping[str, Any]:
        if authority is not _TRACE_SNAPSHOT_AUTHORITY or self.__parts is None:
            raise ScientificTraceError(
                "fixed-hold snapshot derivation lacks validation authority"
            )
        return self.__parts


def _family_payload_bindings(
    *,
    content_sha256: str,
    definition_identity: str,
    validator_identity: str,
) -> tuple[tuple[str, str], ...]:
    return (
        ("content_sha256", _digest("fixed-hold payload hash", content_sha256)),
        (
            "definition_identity",
            _ascii("fixed-hold payload definition", definition_identity),
        ),
        (
            "validator_identity",
            _ascii("fixed-hold payload validator", validator_identity),
        ),
    )


def _subject_payload_bindings(
    *,
    content_sha256: str,
    definition_identity: str,
    validator_identity: str,
    family_sha256: str,
    subject_id: str,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (
                *_family_payload_bindings(
                    content_sha256=content_sha256,
                    definition_identity=definition_identity,
                    validator_identity=validator_identity,
                ),
                (
                    "family_sha256",
                    _digest("fixed-hold payload family hash", family_sha256),
                ),
                (
                    "subject_id",
                    _identity(
                        "fixed-hold payload subject",
                        subject_id,
                        "executable",
                    ),
                ),
            )
        )
    )


@dataclass(frozen=True, slots=True)
class FixedHoldFamilyTraceSnapshot:
    """One immutable, fully scanned family trace at one trust boundary.

    The constructor is intentionally capability-gated.  Durable bytes cannot
    claim that they are validated by carrying a snapshot-shaped payload.
    """

    content: bytes
    sha256: str
    definition_identity: str
    validator_identity: str
    _payload: _SealedTraceSnapshotPayload = field(
        repr=False,
        compare=False,
    )
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority is not _TRACE_SNAPSHOT_AUTHORITY:
            raise ScientificTraceError(
                "fixed-hold family snapshot lacks validation authority"
            )
        if type(self.content) is not bytes:
            raise ScientificTraceError(
                "fixed-hold family snapshot content must be bytes"
            )
        if not isinstance(self._payload, _SealedTraceSnapshotPayload):
            raise ScientificTraceError(
                "fixed-hold family snapshot payload is invalid"
            )
        observed = sha256(self.content).hexdigest()
        if _digest("fixed-hold family snapshot hash", self.sha256) != observed:
            raise ScientificTraceError(
                "fixed-hold family snapshot content hash drifted"
            )
        object.__setattr__(self, "sha256", observed)
        object.__setattr__(
            self,
            "definition_identity",
            _ascii(
                "fixed-hold family snapshot definition identity",
                self.definition_identity,
            ),
        )
        object.__setattr__(
            self,
            "validator_identity",
            _ascii(
                "fixed-hold family snapshot validator identity",
                self.validator_identity,
            ),
        )
        self._payload.require(
            _family_payload_bindings(
                content_sha256=observed,
                definition_identity=self.definition_identity,
                validator_identity=self.validator_identity,
            )
        )

    def to_dict(self) -> dict[str, object]:
        self._payload.require(
            _family_payload_bindings(
                content_sha256=self.sha256,
                definition_identity=self.definition_identity,
                validator_identity=self.validator_identity,
            )
        )
        return self._payload.detached()

    def require(
        self,
        *,
        definition: FixedHoldProtocolDefinition,
        validator: FixedHoldTraceValidator,
    ) -> FixedHoldFamilyTraceSnapshot:
        _require_validator(validator)
        if (
            self.definition_identity != definition.identity
            or self.validator_identity != validator.identity
        ):
            raise ScientificTraceError(
                "fixed-hold family snapshot authority drifted"
            )
        if sha256(self.content).hexdigest() != self.sha256:
            raise ScientificTraceError(
                "fixed-hold family snapshot content hash drifted"
            )
        self._payload.require(
            _family_payload_bindings(
                content_sha256=self.sha256,
                definition_identity=self.definition_identity,
                validator_identity=self.validator_identity,
            )
        )
        return self


@dataclass(frozen=True, slots=True)
class FixedHoldSubjectTraceSnapshot:
    """One subject envelope over an independently validated family snapshot."""

    content: bytes
    sha256: str
    subject_id: str
    family: FixedHoldFamilyTraceSnapshot = field(repr=False, compare=False)
    _payload: _SealedTraceSnapshotPayload = field(
        repr=False,
        compare=False,
    )
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority is not _TRACE_SNAPSHOT_AUTHORITY:
            raise ScientificTraceError(
                "fixed-hold subject snapshot lacks validation authority"
            )
        if type(self.content) is not bytes:
            raise ScientificTraceError(
                "fixed-hold subject snapshot content must be bytes"
            )
        if not isinstance(self.family, FixedHoldFamilyTraceSnapshot):
            raise ScientificTraceError(
                "fixed-hold subject snapshot family is invalid"
            )
        if not isinstance(self._payload, _SealedTraceSnapshotPayload):
            raise ScientificTraceError(
                "fixed-hold subject snapshot payload is invalid"
            )
        observed = sha256(self.content).hexdigest()
        if _digest("fixed-hold subject snapshot hash", self.sha256) != observed:
            raise ScientificTraceError(
                "fixed-hold subject snapshot content hash drifted"
        )
        object.__setattr__(self, "sha256", observed)
        self._payload.require(
            _subject_payload_bindings(
                content_sha256=observed,
                definition_identity=self.family.definition_identity,
                validator_identity=self.family.validator_identity,
                family_sha256=self.family.sha256,
                subject_id=self.subject_id,
            )
        )

    def to_dict(self) -> dict[str, object]:
        self._payload.require(
            _subject_payload_bindings(
                content_sha256=self.sha256,
                definition_identity=self.family.definition_identity,
                validator_identity=self.family.validator_identity,
                family_sha256=self.family.sha256,
                subject_id=self.subject_id,
            )
        )
        return self._payload.detached()

    def require(
        self,
        *,
        definition: FixedHoldProtocolDefinition,
        validator: FixedHoldTraceValidator,
    ) -> FixedHoldSubjectTraceSnapshot:
        self.family.require(definition=definition, validator=validator)
        if sha256(self.content).hexdigest() != self.sha256:
            raise ScientificTraceError(
                "fixed-hold subject snapshot content hash drifted"
            )
        self._payload.require(
            _subject_payload_bindings(
                content_sha256=self.sha256,
                definition_identity=definition.identity,
                validator_identity=validator.identity,
                family_sha256=self.family.sha256,
                subject_id=self.subject_id,
            )
        )
        return self


def _require_validator(validator: FixedHoldTraceValidator) -> None:
    if type(validator) is not FixedHoldTraceValidator:
        raise ScientificTraceError(
            "fixed-hold validator must be the closed code-owned validator"
        )


def fixed_hold_trace_implementation_identities(
    definition: FixedHoldProtocolDefinition,
) -> dict[str, str]:
    if not isinstance(definition, FixedHoldProtocolDefinition):
        raise ScientificTraceError(
            "definition must be FixedHoldProtocolDefinition"
        )
    return {
        **dict(definition.producer_implementation_identities),
        "completed_period_atomic_trace_sha256": (
            completed_period_atomic_trace_implementation_sha256()
        ),
        "fixed_hold_historical_projection_sha256": (
            fixed_hold_historical_projection_implementation_sha256()
        ),
        "fixed_hold_trace_sha256": fixed_hold_trace_implementation_sha256(),
        "historical_semantic_transition_sha256": (
            historical_semantic_transition_implementation_sha256()
        ),
        "selection_inference_sha256": (
            selection_inference_implementation_sha256()
        ),
    }


def expected_fixed_hold_family_inventory(
    definition: FixedHoldProtocolDefinition,
) -> tuple[dict[str, object], ...]:
    if not isinstance(definition, FixedHoldProtocolDefinition):
        raise ScientificTraceError(
            "definition must be FixedHoldProtocolDefinition"
        )
    return tuple(
        {
            "configuration_id": member.configuration_id,
            "executable_id": executable_id,
            "historical_reference_executable_id": (
                member.historical_reference_executable_id
            ),
            "ordinal": member.ordinal,
            "parameters": member.parameter_values(),
            "schema": FIXED_HOLD_MEMBER_SCHEMA,
        }
        for member, executable_id in zip(
            definition.family.members,
            definition.prospective_executable_ids,
            strict=True,
        )
    )


def expected_fixed_hold_control_inventory(
    definition: FixedHoldProtocolDefinition,
) -> tuple[dict[str, object], ...]:
    inventory = expected_fixed_hold_family_inventory(definition)
    executable_by_historical = {
        str(item["historical_reference_executable_id"]): str(
            item["executable_id"]
        )
        for item in inventory
    }
    return tuple(
        {
            "feature_executable_ids": [
                executable_by_historical[value]
                for value in control.feature_historical_executable_ids
            ],
            "feature_historical_executable_ids": list(
                control.feature_historical_executable_ids
            ),
            "opposite_executable_id": executable_by_historical[
                control.opposite_historical_executable_id
            ],
            "opposite_historical_executable_id": (
                control.opposite_historical_executable_id
            ),
            "schema": FIXED_HOLD_CONTROL_SCHEMA,
            "subject_executable_id": executable_by_historical[
                control.subject_historical_executable_id
            ],
            "subject_historical_executable_id": (
                control.subject_historical_executable_id
            ),
        }
        for control in definition.family.controls
    )


def fixed_hold_trace_controls(
    definition: FixedHoldProtocolDefinition,
) -> dict[str, object]:
    return {
        "bindings": list(expected_fixed_hold_control_inventory(definition)),
        "feature_control_delta_aggregation": "minimum_across_exact_feature_controls",
        "feature_control_uncertainty_aggregation": "maximum_familywise_upper_across_exact_feature_controls",
        "opposite_control_rule": "exact_subject_bound_reciprocal_opposite",
        "paired_control_family_scope": "opposite_union_all_exact_feature_controls",
        "selection_family_scope": "exact_preregistered_concurrent_family",
    }


def fixed_hold_trace_attribution() -> dict[str, object]:
    return {
        "drawdown_attribution": "exit_order_within_exit_month",
        "economic_composite": False,
        "eligible_calendar": "observed_test_dates_with_explicit_zero_entry_days",
        "fixed_hold_attribution": "entry_bar_index_plus_holding_bars",
        "native_pnl_attribution": "decision_day",
        "stress_pnl_attribution": "decision_day",
    }


def fixed_hold_original_family_provenance(
    definition: FixedHoldProtocolDefinition,
) -> dict[str, object]:
    family = definition.family
    return {
        "end_global_exposure_count": (
            definition.original_family_end_global_exposure_count
        ),
        "family_spec_identity": family.identity,
        "original_batch_id": family.original_batch_id,
        "original_study_id": family.original_study_id,
        "role": "immutable_original_family_provenance_not_adjustment_factor",
        "target_historical_executable_id": (
            family.target_historical_executable_id
        ),
    }


def fixed_hold_calculation_parameters(
    definition: FixedHoldProtocolDefinition,
    validator: FixedHoldTraceValidator,
) -> dict[str, object]:
    _require_validator(validator)
    return {
        "alpha_ppm": definition.alpha_ppm,
        "base_seed": definition.base_seed,
        "block_lengths": list(definition.block_lengths),
        "bootstrap_samples": definition.bootstrap_samples,
        "definition_identity": definition.identity,
        "exact_concurrent_family_adjustment_factor": (
            definition.family.family_size
        ),
        "historical_context_adjustment_authority": (
            "context_only_never_adjustment_factor"
        ),
        "historical_context_prior_global_exposure_count": (
            definition.historical_prior_global_exposure_count
        ),
        "monte_carlo_confidence_ppm": (
            definition.monte_carlo_confidence_ppm
        ),
        "original_family_end_global_exposure_count": (
            definition.original_family_end_global_exposure_count
        ),
        "validator_identity": validator.identity,
    }


def fixed_hold_observation_id(
    kind: str,
    value: Mapping[str, Any],
) -> str:
    if kind not in {"intent", "trade"}:
        raise ScientificTraceError("fixed-hold observation kind is invalid")
    payload = {
        key: item for key, item in value.items() if key != "observation_id"
    }
    digest = canonical_digest(
        domain=f"fixed-hold-{kind}-observation",
        payload=payload,
    )
    return f"observation:{digest}"


def _member_holding_bars(member: Mapping[str, Any]) -> int:
    parameters = _mapping("fixed-hold member parameters", member["parameters"])
    return _integer(
        "fixed-hold member holding_bars",
        parameters.get("holding_bars"),
        minimum=1,
    )


def _validate_family(
    trace: Mapping[str, Any],
    *,
    definition: FixedHoldProtocolDefinition,
) -> dict[str, dict[str, Any]]:
    if trace.get("family_id") != definition.family_id:
        raise ScientificTraceError("fixed-hold trace family identity drifted")
    raw = _sequence("fixed-hold ordered family", trace.get("ordered_family"))
    family: list[dict[str, Any]] = []
    for item in raw:
        member = _mapping("fixed-hold family member", item)
        if set(member) != _FAMILY_MEMBER_FIELDS:
            raise ScientificTraceError(
                "fixed-hold family member schema is invalid"
            )
        _member_holding_bars(member)
        family.append(dict(member))
    if tuple(family) != expected_fixed_hold_family_inventory(definition):
        raise ScientificTraceError(
            "fixed-hold family or historical reference mapping drifted"
        )
    return {str(item["configuration_id"]): item for item in family}


def _validate_windows(
    trace: Mapping[str, Any],
    *,
    definition: FixedHoldProtocolDefinition,
) -> tuple[dict[str, Any], ...]:
    raw = _sequence("fixed-hold windows", trace.get("windows"))
    windows: list[dict[str, Any]] = []
    for item in raw:
        window = _mapping("fixed-hold window", item)
        if set(window) != _WINDOW_FIELDS:
            raise ScientificTraceError("fixed-hold window schema is invalid")
        _ascii("fixed-hold fold_id", window.get("fold_id"))
        train_start = _timestamp("fixed-hold train_start", window.get("train_start"))
        train_end = _timestamp("fixed-hold train_end", window.get("train_end"))
        test_start = _timestamp("fixed-hold test_start", window.get("test_start"))
        test_end = _timestamp("fixed-hold test_end", window.get("test_end"))
        if not train_start <= train_end < test_start <= test_end:
            raise ScientificTraceError(
                "fixed-hold fold windows overlap or reverse"
            )
        eligible_dates = tuple(
            _date("fixed-hold eligible date", value).isoformat()
            for value in _sequence(
                "fixed-hold eligible dates",
                window.get("eligible_dates"),
            )
        )
        if eligible_dates != tuple(sorted(set(eligible_dates))):
            raise ScientificTraceError(
                "fixed-hold eligible dates are not exact and sorted"
            )
        if any(
            not test_start.date() <= date.fromisoformat(value) <= test_end.date()
            for value in eligible_dates
        ):
            raise ScientificTraceError(
                "fixed-hold eligible date is outside its test fold"
            )
        windows.append(dict(window))
    if tuple(str(item["fold_id"]) for item in windows) != definition.fold_ids:
        raise ScientificTraceError(
            "fixed-hold trace fold inventory is incomplete"
        )
    calendars = [set(item["eligible_dates"]) for item in windows]
    if any(
        left.intersection(right)
        for index, left in enumerate(calendars)
        for right in calendars[index + 1 :]
    ):
        raise ScientificTraceError(
            "fixed-hold fold eligible calendars overlap"
        )
    return tuple(windows)


def _validate_invariance(
    trace: Mapping[str, Any],
    *,
    definition: FixedHoldProtocolDefinition,
    windows: tuple[dict[str, Any], ...],
) -> int:
    raw = _sequence(
        "fixed-hold invariance comparisons",
        trace.get("invariance_comparisons"),
    )
    comparisons: list[tuple[str, str]] = []
    for item in raw:
        comparison = _mapping("fixed-hold invariance comparison", item)
        if set(comparison) != _INVARIANCE_FIELDS:
            raise ScientificTraceError(
                "fixed-hold invariance schema is invalid"
            )
        fold_id = _ascii("invariance fold_id", comparison.get("fold_id"))
        key = _ascii("invariance key", comparison.get("invariance_key"))
        _integer(
            "invariance compared rows",
            comparison.get("compared_row_count"),
            minimum=1,
        )
        full = _digest(
            "full causal surface digest",
            comparison.get("full_feature_values_sha256"),
        )
        prefix = _digest(
            "prefix causal surface digest",
            comparison.get("prefix_feature_values_sha256"),
        )
        if full != prefix:
            raise ScientificTraceError(
                "fixed-hold causal surface prefix invariance failed"
            )
        comparisons.append((fold_id, key))
    expected = tuple(
        (str(window["fold_id"]), key)
        for window in windows
        for key in definition.invariance_keys
    )
    if tuple(comparisons) != expected:
        raise ScientificTraceError(
            "fixed-hold invariance inventory is incomplete"
        )
    return 0


def _validate_fixed_hold_clock(
    row: Mapping[str, Any],
    *,
    member: Mapping[str, Any],
    prefix: str,
    intent_status: str | None = None,
) -> tuple[datetime, datetime, datetime]:
    holding_bars = _integer(
        f"{prefix} holding_bars",
        row.get("holding_bars"),
        minimum=1,
    )
    if holding_bars != _member_holding_bars(member):
        raise ScientificTraceError(f"{prefix} holding parameter drifted")
    return validate_completed_period_fixed_hold_sources(
        row,
        holding_bars=holding_bars,
        prefix=prefix,
        intent_status=intent_status,
    )


def _validate_trades(
    trace: Mapping[str, Any],
    *,
    definition: FixedHoldProtocolDefinition,
    family: Mapping[str, Mapping[str, Any]],
    windows: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    raw = _sequence(
        "fixed-hold trades",
        trace.get("trade_observations"),
        allow_empty=True,
    )
    window_by_fold = {str(item["fold_id"]): item for item in windows}
    trades: list[dict[str, Any]] = []
    sort_keys: list[tuple[object, ...]] = []
    seen: set[str] = set()
    for item in raw:
        trade = _mapping("fixed-hold trade", item)
        if set(trade) != _TRADE_FIELDS:
            raise ScientificTraceError("fixed-hold trade schema is invalid")
        configuration_id = _ascii(
            "trade configuration_id",
            trade.get("configuration_id"),
        )
        member = family.get(configuration_id)
        if member is None or any(
            trade.get(name) != member[name]
            for name in (
                "executable_id",
                "historical_reference_executable_id",
            )
        ):
            raise ScientificTraceError(
                "fixed-hold trade belongs to another family member"
            )
        fold_id = _ascii("trade fold_id", trade.get("fold_id"))
        window = window_by_fold.get(fold_id)
        if window is None:
            raise ScientificTraceError("fixed-hold trade fold is unknown")
        decision, _, _ = _validate_fixed_hold_clock(
            trade,
            member=member,
            prefix="fixed-hold trade",
        )
        if not (
            _timestamp("test_start", window["test_start"])
            <= decision
            <= _timestamp("test_end", window["test_end"])
            and decision.date().isoformat() in window["eligible_dates"]
        ):
            raise ScientificTraceError(
                "fixed-hold trade is outside its exact test calendar"
            )
        direction = _integer("trade direction", trade.get("direction"))
        if direction not in {-1, 1}:
            raise ScientificTraceError("fixed-hold trade direction is invalid")
        gross = _integer("trade gross", trade.get("gross_pnl_micropoints"))
        native_cost = _integer(
            "trade native cost",
            trade.get("native_cost_micropoints"),
            minimum=0,
        )
        stress_cost = _integer(
            "trade stress cost",
            trade.get("stress_cost_micropoints"),
            minimum=0,
        )
        native_net = _integer(
            "trade native net",
            trade.get("native_net_pnl_micropoints"),
        )
        stress_net = _integer(
            "trade stress net",
            trade.get("stress_net_pnl_micropoints"),
        )
        if (
            stress_cost < native_cost
            or gross - native_cost != native_net
            or gross - stress_cost != stress_net
        ):
            raise ScientificTraceError(
                "fixed-hold trade cost arithmetic does not reconcile"
            )
        if trade.get("regime") not in definition.allowed_regimes:
            raise ScientificTraceError("fixed-hold trade regime is invalid")
        observation_id = _identity(
            "trade observation_id",
            trade.get("observation_id"),
            "observation",
        )
        if (
            observation_id != fixed_hold_observation_id("trade", trade)
            or observation_id in seen
        ):
            raise ScientificTraceError(
                "fixed-hold trade observation identity is invalid"
            )
        seen.add(observation_id)
        trades.append(dict(trade))
        sort_keys.append(
            (configuration_id, fold_id, decision.isoformat(), observation_id)
        )
    if tuple(sort_keys) != tuple(sorted(sort_keys)):
        raise ScientificTraceError("fixed-hold trades are not canonical")
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
    )


def _execution_identity(row: Mapping[str, Any]) -> tuple[object, ...]:
    return tuple(
        row[name]
        for name in (
            "configuration_id",
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
            "holding_bars",
            "spread_semantics",
        )
    )


def _validate_intents(
    trace: Mapping[str, Any],
    *,
    family: Mapping[str, Mapping[str, Any]],
    windows: tuple[dict[str, Any], ...],
    trades: tuple[dict[str, Any], ...],
) -> tuple[tuple[dict[str, Any], ...], dict[str, tuple[int, int, int]]]:
    raw = _sequence(
        "fixed-hold intents",
        trace.get("intent_observations"),
        allow_empty=True,
    )
    window_by_fold = {str(item["fold_id"]): item for item in windows}
    intents: list[dict[str, Any]] = []
    seen: set[str] = set()
    sort_keys: list[tuple[object, ...]] = []
    for item in raw:
        intent = _mapping("fixed-hold intent", item)
        if set(intent) != _INTENT_FIELDS:
            raise ScientificTraceError("fixed-hold intent schema is invalid")
        configuration_id = _ascii(
            "intent configuration_id",
            intent.get("configuration_id"),
        )
        member = family.get(configuration_id)
        if member is None or any(
            intent.get(name) != member[name]
            for name in (
                "executable_id",
                "historical_reference_executable_id",
            )
        ):
            raise ScientificTraceError(
                "fixed-hold intent belongs to another family member"
            )
        fold_id = _ascii("intent fold_id", intent.get("fold_id"))
        window = window_by_fold.get(fold_id)
        if window is None:
            raise ScientificTraceError("fixed-hold intent fold is unknown")
        scope = intent.get("scope")
        if scope not in {"full", "prefix"}:
            raise ScientificTraceError("fixed-hold intent scope is invalid")
        ordinal = _integer(
            "intent ordinal",
            intent.get("ordinal"),
            minimum=1,
        )
        status = intent.get("status")
        if status not in _ALLOWED_INTENT_STATUSES:
            raise ScientificTraceError("fixed-hold intent status is invalid")
        decision, _, _ = _validate_fixed_hold_clock(
            intent,
            member=member,
            prefix="fixed-hold intent",
            intent_status=str(status),
        )
        decision_bar_open = _timestamp(
            "fixed-hold intent decision_bar_open_time",
            intent.get("decision_bar_open_time"),
        )
        if not (
            _timestamp("test_start", window["test_start"])
            <= decision_bar_open
            <= _timestamp("test_end", window["test_end"])
            and decision_bar_open.date().isoformat()
            in window["eligible_dates"]
        ):
            raise ScientificTraceError(
                "fixed-hold intent decision bar is outside its exact test "
                f"calendar: {configuration_id}/{fold_id}/"
                f"{decision_bar_open.isoformat()}"
            )
        if _integer("intent direction", intent.get("direction")) not in {-1, 1}:
            raise ScientificTraceError("fixed-hold intent direction is invalid")
        observation_id = _identity(
            "intent observation_id",
            intent.get("observation_id"),
            "observation",
        )
        if (
            observation_id != fixed_hold_observation_id("intent", intent)
            or observation_id in seen
        ):
            raise ScientificTraceError(
                "fixed-hold intent observation identity is invalid"
            )
        seen.add(observation_id)
        intents.append(dict(intent))
        sort_keys.append(
            (configuration_id, fold_id, scope, ordinal, observation_id)
        )
    if tuple(sort_keys) != tuple(sorted(sort_keys)):
        raise ScientificTraceError("fixed-hold intents are not canonical")
    by_scope: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for intent in intents:
        by_scope[
            (
                str(intent["configuration_id"]),
                str(intent["fold_id"]),
                str(intent["scope"]),
            )
        ].append(intent)
    append_mismatches = {configuration_id: 0 for configuration_id in family}
    for configuration_id in family:
        for fold_id in window_by_fold:
            full = by_scope.get((configuration_id, fold_id, "full"), [])
            prefix = by_scope.get((configuration_id, fold_id, "prefix"), [])
            if tuple(item["ordinal"] for item in full) != tuple(
                range(1, len(full) + 1)
            ) or tuple(item["ordinal"] for item in prefix) != tuple(
                range(1, len(prefix) + 1)
            ):
                raise ScientificTraceError(
                    "fixed-hold intent ordinals are not contiguous"
                )
            append_mismatches[configuration_id] += abs(
                len(full) - len(prefix)
            ) + sum(
                _intent_comparison_tuple(left)
                != _intent_comparison_tuple(right)
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
        raise ScientificTraceError(
            "fixed-hold executed intents differ from trade rows"
        )
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
    raw = _sequence(
        "fixed-hold eligible days",
        trace.get("eligible_day_observations"),
    )
    rows: list[dict[str, Any]] = []
    sort_keys: list[tuple[str, str, str]] = []
    for item in raw:
        row = _mapping("fixed-hold eligible day", item)
        if set(row) != _ELIGIBLE_FIELDS:
            raise ScientificTraceError(
                "fixed-hold eligible-day schema is invalid"
            )
        configuration_id = _ascii(
            "eligible configuration_id",
            row.get("configuration_id"),
        )
        member = family.get(configuration_id)
        if member is None or row.get("executable_id") != member["executable_id"]:
            raise ScientificTraceError(
                "fixed-hold eligible day belongs to another member"
            )
        fold_id = _ascii("eligible fold_id", row.get("fold_id"))
        day = _date("eligible date", row.get("date")).isoformat()
        _integer("eligible entry_count", row.get("entry_count"), minimum=0)
        _integer("eligible native pnl", row.get("native_net_pnl_micropoints"))
        _integer("eligible stress pnl", row.get("stress_net_pnl_micropoints"))
        rows.append(dict(row))
        sort_keys.append((configuration_id, fold_id, day))
    if (
        tuple(sort_keys) != tuple(sorted(sort_keys))
        or len(set(sort_keys)) != len(sort_keys)
    ):
        raise ScientificTraceError(
            "fixed-hold eligible-day rows are not canonical"
        )
    expected = {
        (configuration_id, str(window["fold_id"]), day)
        for configuration_id in family
        for window in windows
        for day in window["eligible_dates"]
    }
    if set(sort_keys) != expected:
        raise ScientificTraceError(
            "fixed-hold explicit zero-entry calendar is incomplete"
        )
    aggregate: dict[tuple[str, str, str], list[int]] = defaultdict(
        lambda: [0, 0, 0]
    )
    for trade in trades:
        key = (
            str(trade["configuration_id"]),
            str(trade["fold_id"]),
            str(trade["decision_time"])[:10],
        )
        aggregate[key][0] += 1
        aggregate[key][1] += int(trade["native_net_pnl_micropoints"])
        aggregate[key][2] += int(trade["stress_net_pnl_micropoints"])
    if not set(aggregate).issubset(expected):
        raise ScientificTraceError(
            "fixed-hold trade aggregation escaped the eligible calendar"
        )
    daily_by_executable: dict[str, dict[str, int]] = {
        str(member["executable_id"]): {} for member in family.values()
    }
    for row in rows:
        key = (
            str(row["configuration_id"]),
            str(row["fold_id"]),
            str(row["date"]),
        )
        observed = aggregate.get(key, [0, 0, 0])
        if tuple(observed) != (
            row["entry_count"],
            row["native_net_pnl_micropoints"],
            row["stress_net_pnl_micropoints"],
        ):
            raise ScientificTraceError(
                "fixed-hold eligible-day aggregation drifted"
            )
        executable_id = str(row["executable_id"])
        day = str(row["date"])
        if day in daily_by_executable[executable_id]:
            raise ScientificTraceError(
                "fixed-hold eligible date appears in two folds"
            )
        daily_by_executable[executable_id][day] = int(
            row["native_net_pnl_micropoints"]
        )
    calendars = {
        tuple(sorted(values)) for values in daily_by_executable.values()
    }
    if len(calendars) != 1 or len(next(iter(calendars))) < 30:
        raise ScientificTraceError(
            "fixed-hold selection calendar is not shared or sufficient"
        )
    return daily_by_executable


def _validated_family_trace_parts(
    trace: Mapping[str, Any],
    *,
    definition: FixedHoldProtocolDefinition,
    validator: FixedHoldTraceValidator,
) -> dict[str, Any]:
    _require_validator(validator)
    if not isinstance(definition, FixedHoldProtocolDefinition):
        raise ScientificTraceError(
            "definition must be FixedHoldProtocolDefinition"
        )
    if not isinstance(trace, Mapping) or set(trace) != _FAMILY_TRACE_FIELDS:
        raise ScientificTraceError("fixed-hold family trace schema is invalid")
    try:
        content = canonical_bytes(trace)
        normalized = parse_canonical(content)
    except (TypeError, ValueError) as exc:
        raise ScientificTraceError(
            "fixed-hold family trace is not canonical"
        ) from exc
    if not isinstance(normalized, dict):
        raise ScientificTraceError("fixed-hold family trace must be an object")
    if (
        normalized.get("schema") != FIXED_HOLD_FAMILY_TRACE_SCHEMA
        or normalized.get("protocol_id") != definition.protocol_id
        or normalized.get("dataset_sha256") != definition.dataset_sha256
        or normalized.get("material_identity") != definition.material_identity
        or normalized.get("split_artifact_sha256")
        != definition.split_artifact_sha256
        or normalized.get("clock_contract") != definition.clock_contract
        or normalized.get("cost_contract") != definition.cost_contract
        or normalized.get("attribution") != fixed_hold_trace_attribution()
        or normalized.get("controls") != fixed_hold_trace_controls(definition)
        or normalized.get("implementation_identities")
        != fixed_hold_trace_implementation_identities(definition)
        or normalized.get("original_family_provenance")
        != fixed_hold_original_family_provenance(definition)
    ):
        raise ScientificTraceError(
            "fixed-hold family trace authority binding drifted"
        )
    family = _validate_family(normalized, definition=definition)
    windows = _validate_windows(normalized, definition=definition)
    prefix_mismatches = _validate_invariance(
        normalized,
        definition=definition,
        windows=windows,
    )
    trades = _validate_trades(
        normalized,
        definition=definition,
        family=family,
        windows=windows,
    )
    intents, intent_counts = _validate_intents(
        normalized,
        family=family,
        windows=windows,
        trades=trades,
    )
    daily = _validate_eligible_days(
        normalized,
        family=family,
        windows=windows,
        trades=trades,
    )
    corrected_surfaces = (
        {}
        if definition.semantic_transition_policy
        == NO_SEMANTIC_TRANSITION_POLICY
        else derive_fixed_hold_semantic_surfaces(
            ordered_family=expected_fixed_hold_family_inventory(definition),
            control_bindings=expected_fixed_hold_control_inventory(definition),
            windows=windows,
            trades=trades,
            intents=intents,
            prefix_invariance_mismatch_count=prefix_mismatches,
        )
    )
    semantic_transitions = validate_historical_semantic_transition_inventory(
        normalized.get("semantic_transition_evidence"),
        policy=definition.semantic_transition_policy,
        ordered_family=expected_fixed_hold_family_inventory(definition),
        historical_artifacts_by_configuration=(
            definition.historical_artifacts_by_configuration()
        ),
        corrected_surfaces_by_configuration=corrected_surfaces,
    )
    return {
        "content": content,
        "daily": daily,
        "family": family,
        "intent_counts": intent_counts,
        "normalized": normalized,
        "prefix_mismatches": prefix_mismatches,
        "semantic_transitions": semantic_transitions,
        "trades": trades,
        "windows": windows,
    }


def validate_fixed_hold_family_trace_snapshot(
    trace: Mapping[str, Any] | FixedHoldFamilyTraceSnapshot,
    *,
    definition: FixedHoldProtocolDefinition,
    validator: FixedHoldTraceValidator,
) -> FixedHoldFamilyTraceSnapshot:
    """Open one family boundary and retain its immutable derived facts."""

    if isinstance(trace, FixedHoldFamilyTraceSnapshot):
        return trace.require(definition=definition, validator=validator)
    parts = _validated_family_trace_parts(
        trace,
        definition=definition,
        validator=validator,
    )
    content = parts["content"]
    if type(content) is not bytes:
        raise RuntimeError("validated fixed-hold family lost canonical bytes")
    derived = {
        name: value
        for name, value in parts.items()
        if name not in {"content", "normalized"}
    }
    content_sha256 = sha256(content).hexdigest()
    payload = _SealedTraceSnapshotPayload(
        authority=_TRACE_SNAPSHOT_AUTHORITY,
        bindings=_family_payload_bindings(
            content_sha256=content_sha256,
            definition_identity=definition.identity,
            validator_identity=validator.identity,
        ),
        normalized=parts["normalized"],
        parts=derived,
    )
    return FixedHoldFamilyTraceSnapshot(
        content=content,
        sha256=content_sha256,
        definition_identity=definition.identity,
        validator_identity=validator.identity,
        _payload=payload,
        _authority=_TRACE_SNAPSHOT_AUTHORITY,
    )


def _fixed_hold_family_snapshot_parts(
    snapshot: FixedHoldFamilyTraceSnapshot,
    *,
    definition: FixedHoldProtocolDefinition,
    validator: FixedHoldTraceValidator,
) -> Mapping[str, Any]:
    snapshot.require(definition=definition, validator=validator)
    return snapshot._payload.parts(_TRACE_SNAPSHOT_AUTHORITY)


def _fixed_hold_family_snapshot_value(
    snapshot: FixedHoldFamilyTraceSnapshot,
    *,
    definition: FixedHoldProtocolDefinition,
    validator: FixedHoldTraceValidator,
) -> dict[str, object]:
    snapshot.require(definition=definition, validator=validator)
    return snapshot._payload.normalized(_TRACE_SNAPSHOT_AUTHORITY)


def build_fixed_hold_family_trace(
    *,
    definition: FixedHoldProtocolDefinition,
    validator: FixedHoldTraceValidator,
    windows: Sequence[Mapping[str, Any]],
    invariance_comparisons: Sequence[Mapping[str, Any]],
    trade_observations: Sequence[Mapping[str, Any]],
    intent_observations: Sequence[Mapping[str, Any]],
    eligible_day_observations: Sequence[Mapping[str, Any]],
    semantic_transition_evidence: Sequence[Mapping[str, Any]] = (),
) -> dict[str, object]:
    """Build and immediately validate one family-neutral atomic trace."""

    value = {
        "attribution": fixed_hold_trace_attribution(),
        "clock_contract": definition.clock_contract,
        "controls": fixed_hold_trace_controls(definition),
        "cost_contract": definition.cost_contract,
        "dataset_sha256": definition.dataset_sha256,
        "eligible_day_observations": [
            dict(item) for item in eligible_day_observations
        ],
        "family_id": definition.family_id,
        "implementation_identities": (
            fixed_hold_trace_implementation_identities(definition)
        ),
        "intent_observations": [dict(item) for item in intent_observations],
        "invariance_comparisons": [
            dict(item) for item in invariance_comparisons
        ],
        "material_identity": definition.material_identity,
        "ordered_family": list(expected_fixed_hold_family_inventory(definition)),
        "original_family_provenance": (
            fixed_hold_original_family_provenance(definition)
        ),
        "protocol_id": definition.protocol_id,
        "schema": FIXED_HOLD_FAMILY_TRACE_SCHEMA,
        "semantic_transition_evidence": [
            dict(item) for item in semantic_transition_evidence
        ],
        "split_artifact_sha256": definition.split_artifact_sha256,
        "trade_observations": [dict(item) for item in trade_observations],
        "windows": [dict(item) for item in windows],
    }
    return validate_fixed_hold_family_trace_snapshot(
        value,
        definition=definition,
        validator=validator,
    ).to_dict()


def validate_fixed_hold_family_trace(
    trace: Mapping[str, Any] | FixedHoldFamilyTraceSnapshot,
    *,
    definition: FixedHoldProtocolDefinition,
    validator: FixedHoldTraceValidator,
) -> dict[str, object]:
    return validate_fixed_hold_family_trace_snapshot(
        trace,
        definition=definition,
        validator=validator,
    ).to_dict()


def _subject_neutral_trace(
    trace: Mapping[str, Any],
) -> dict[str, object]:
    attribution = _mapping(
        "fixed-hold subject attribution",
        trace.get("attribution"),
    )
    if set(attribution) != _SUBJECT_ATTRIBUTION_FIELDS:
        raise ScientificTraceError(
            "fixed-hold subject attribution schema is invalid"
        )
    binding = _mapping(
        "fixed-hold family trace binding",
        attribution.get("family_trace_binding"),
    )
    if set(binding) != _FAMILY_TRACE_BINDING_FIELDS:
        raise ScientificTraceError(
            "fixed-hold family trace binding schema is invalid"
        )
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


def validate_fixed_hold_subject_trace_snapshot(
    trace: Mapping[str, Any] | FixedHoldSubjectTraceSnapshot,
    *,
    definition: FixedHoldProtocolDefinition,
    validator: FixedHoldTraceValidator,
) -> FixedHoldSubjectTraceSnapshot:
    """Open one subject boundary with exactly one neutral-family full scan."""

    _require_validator(validator)
    if isinstance(trace, FixedHoldSubjectTraceSnapshot):
        return trace.require(definition=definition, validator=validator)
    if not isinstance(trace, Mapping) or set(trace) != _SUBJECT_TRACE_FIELDS:
        raise ScientificTraceError("fixed-hold subject trace schema is invalid")
    try:
        content = canonical_bytes(trace)
        normalized = parse_canonical(content)
    except (TypeError, ValueError) as exc:
        raise ScientificTraceError(
            "fixed-hold subject trace is not canonical"
        ) from exc
    if not isinstance(normalized, dict):
        raise ScientificTraceError("fixed-hold subject trace must be an object")
    if (
        normalized.get("schema") != SCIENTIFIC_EVALUATION_TRACE_SCHEMA
        or normalized.get("protocol_id") != definition.protocol_id
        or normalized.get("adapter_implementation_sha256")
        != fixed_hold_trace_implementation_sha256()
    ):
        raise ScientificTraceError("fixed-hold subject trace binding drifted")
    _ascii("fixed-hold trace mission_id", normalized.get("mission_id"))
    _ascii("fixed-hold trace job_id", normalized.get("job_id"))
    _digest("fixed-hold trace job_hash", normalized.get("job_hash"))
    subject_id = _identity(
        "fixed-hold trace subject_executable_id",
        normalized.get("subject_executable_id"),
        "executable",
    )
    neutral = _subject_neutral_trace(normalized)
    family = validate_fixed_hold_family_trace_snapshot(
        neutral,
        definition=definition,
        validator=validator,
    )
    attribution = _mapping(
        "fixed-hold subject attribution",
        normalized["attribution"],
    )
    binding = _mapping(
        "fixed-hold family trace binding",
        attribution["family_trace_binding"],
    )
    if (
        binding.get("family_trace_sha256") != family.sha256
        or binding.get("definition_identity") != definition.identity
        or binding.get("validator_identity") != validator.identity
    ):
        raise ScientificTraceError(
            "fixed-hold subject family binding drifted"
        )
    parts = _fixed_hold_family_snapshot_parts(
        family,
        definition=definition,
        validator=validator,
    )
    if subject_id not in {
        item["executable_id"] for item in parts["family"].values()
    }:
        raise ScientificTraceError(
            "fixed-hold trace subject is outside its family"
        )
    content_sha256 = sha256(content).hexdigest()
    payload = _SealedTraceSnapshotPayload(
        authority=_TRACE_SNAPSHOT_AUTHORITY,
        bindings=_subject_payload_bindings(
            content_sha256=content_sha256,
            definition_identity=definition.identity,
            validator_identity=validator.identity,
            family_sha256=family.sha256,
            subject_id=subject_id,
        ),
        normalized=normalized,
    )
    return FixedHoldSubjectTraceSnapshot(
        content=content,
        sha256=content_sha256,
        subject_id=subject_id,
        family=family,
        _payload=payload,
        _authority=_TRACE_SNAPSHOT_AUTHORITY,
    )


def _fixed_hold_subject_snapshot_value(
    snapshot: FixedHoldSubjectTraceSnapshot,
    *,
    definition: FixedHoldProtocolDefinition,
    validator: FixedHoldTraceValidator,
) -> dict[str, object]:
    snapshot.require(definition=definition, validator=validator)
    return snapshot._payload.normalized(_TRACE_SNAPSHOT_AUTHORITY)


def bind_fixed_hold_family_trace_snapshot(
    *,
    family_trace: Mapping[str, Any] | FixedHoldFamilyTraceSnapshot,
    definition: FixedHoldProtocolDefinition,
    validator: FixedHoldTraceValidator,
    mission_id: str,
    executable_id: str,
    job_id: str,
    job_hash: str,
) -> FixedHoldSubjectTraceSnapshot:
    family = validate_fixed_hold_family_trace_snapshot(
        family_trace,
        definition=definition,
        validator=validator,
    )
    parts = _fixed_hold_family_snapshot_parts(
        family,
        definition=definition,
        validator=validator,
    )
    family_ids = {
        str(item["executable_id"])
        for item in parts["family"].values()
    }
    subject_id = _identity(
        "fixed-hold replay executable_id",
        executable_id,
        "executable",
    )
    if subject_id not in family_ids:
        raise ScientificTraceError(
            "fixed-hold replay subject is outside its family"
        )
    normalized = _fixed_hold_family_snapshot_value(
        family,
        definition=definition,
        validator=validator,
    )
    family_binding = {
        "clock_contract": normalized["clock_contract"],
        "cost_contract": normalized["cost_contract"],
        "definition_identity": definition.identity,
        "family_trace_sha256": family.sha256,
        "implementation_identities": normalized[
            "implementation_identities"
        ],
        "original_family_provenance": normalized[
            "original_family_provenance"
        ],
        "schema": FIXED_HOLD_FAMILY_TRACE_SCHEMA,
        "validator_identity": validator.identity,
    }
    common = (_FAMILY_TRACE_FIELDS & _SUBJECT_TRACE_FIELDS) - {
        "attribution",
        "schema",
    }
    value = {
        **{name: normalized[name] for name in common},
        "adapter_implementation_sha256": (
            fixed_hold_trace_implementation_sha256()
        ),
        "attribution": {
            "family_trace_binding": family_binding,
            "protocol_attribution": normalized["attribution"],
        },
        "job_hash": _digest("fixed-hold replay job_hash", job_hash),
        "job_id": _ascii("fixed-hold replay job_id", job_id),
        "mission_id": _ascii("fixed-hold replay mission_id", mission_id),
        "schema": SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
        "subject_executable_id": subject_id,
    }
    content = canonical_bytes(value)
    content_sha256 = sha256(content).hexdigest()
    payload = _SealedTraceSnapshotPayload(
        authority=_TRACE_SNAPSHOT_AUTHORITY,
        bindings=_subject_payload_bindings(
            content_sha256=content_sha256,
            definition_identity=definition.identity,
            validator_identity=validator.identity,
            family_sha256=family.sha256,
            subject_id=subject_id,
        ),
        normalized=value,
    )
    return FixedHoldSubjectTraceSnapshot(
        content=content,
        sha256=content_sha256,
        subject_id=subject_id,
        family=family,
        _payload=payload,
        _authority=_TRACE_SNAPSHOT_AUTHORITY,
    )


def bind_fixed_hold_family_trace(
    *,
    family_trace: Mapping[str, Any] | FixedHoldFamilyTraceSnapshot,
    definition: FixedHoldProtocolDefinition,
    validator: FixedHoldTraceValidator,
    mission_id: str,
    executable_id: str,
    job_id: str,
    job_hash: str,
) -> dict[str, object]:
    return bind_fixed_hold_family_trace_snapshot(
        family_trace=family_trace,
        definition=definition,
        validator=validator,
        mission_id=mission_id,
        executable_id=executable_id,
        job_id=job_id,
        job_hash=job_hash,
    ).to_dict()


def extract_fixed_hold_family_trace_from_subject(
    trace: Mapping[str, Any] | FixedHoldSubjectTraceSnapshot,
    *,
    definition: FixedHoldProtocolDefinition,
    validator: FixedHoldTraceValidator,
) -> dict[str, object]:
    snapshot = validate_fixed_hold_subject_trace_snapshot(
        trace,
        definition=definition,
        validator=validator,
    )
    return snapshot.family.to_dict()


def _profit_factor(values: Sequence[int]) -> int:
    gain = sum(value for value in values if value > 0)
    loss = -sum(value for value in values if value < 0)
    if loss <= 0:
        return 1_000_000 if gain > 0 else 0
    return min(1_000_000, int(round(1000 * gain / loss)))


def _monthly_drawdown_share(trades: Sequence[Mapping[str, Any]]) -> int:
    by_month: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for trade in sorted(
        trades,
        key=lambda item: (item["exit_time"], item["observation_id"]),
    ):
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
            else min(
                1_000_000_000,
                ceil(1_000_000 * drawdown / gross_profit),
            )
        )
        worst_share = max(worst_share, share)
    return worst_share


def _selection_plan(
    *,
    family_id: str,
    hypothesis_ids: tuple[str, ...],
    registration_ids: Mapping[str, str],
    definition: FixedHoldProtocolDefinition,
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
        alpha_ppm=definition.alpha_ppm,
        bootstrap_samples=definition.bootstrap_samples,
        block_lengths=definition.block_lengths,
        monte_carlo_confidence_ppm=(
            definition.monte_carlo_confidence_ppm
        ),
        base_seed=definition.base_seed,
    )


def _subject_control_binding(
    *,
    definition: FixedHoldProtocolDefinition,
    subject_id: str,
) -> dict[str, object]:
    matches = tuple(
        item
        for item in expected_fixed_hold_control_inventory(definition)
        if item["subject_executable_id"] == subject_id
    )
    if len(matches) != 1:
        raise ScientificTraceError(
            "fixed-hold subject control binding is ambiguous"
        )
    return matches[0]


def _control_hypothesis_id(role: str, executable_id: str) -> str:
    if role not in {"feature", "opposite"}:
        raise RuntimeError("fixed-hold control role is invalid")
    return f"paired-control:{role}:{executable_id}"


def fixed_hold_subject_inference_families(
    definition: FixedHoldProtocolDefinition,
    subject_executable_id: str,
) -> dict[str, dict[str, object]]:
    """Return the exact code-owned families preregistered for one subject."""

    subject_id = _identity(
        "fixed-hold inference subject_executable_id",
        subject_executable_id,
        "executable",
    )
    controls = _subject_control_binding(
        definition=definition,
        subject_id=subject_id,
    )
    selection_members = tuple(sorted(definition.prospective_executable_ids))
    opposite_member = _control_hypothesis_id(
        "opposite",
        str(controls["opposite_executable_id"]),
    )
    feature_members = tuple(
        _control_hypothesis_id("feature", str(value))
        for value in controls["feature_executable_ids"]
    )
    paired_members = tuple(sorted((opposite_member, *feature_members)))
    paired_digest = canonical_digest(
        domain="fixed-hold-subject-control-family",
        payload={
            "feature_historical_executable_ids": controls[
                "feature_historical_executable_ids"
            ],
            "inference_family_id": definition.inference_family_id,
            "opposite_historical_executable_id": controls[
                "opposite_historical_executable_id"
            ],
            "protocol_id": definition.protocol_id,
            "subject_historical_executable_id": controls[
                "subject_historical_executable_id"
            ],
        },
    )
    value = {
        "paired_control_family": {
            "family_id": f"family:{paired_digest}",
            "feature_member_ids": list(feature_members),
            "member_id": opposite_member,
            "ordered_member_ids": list(paired_members),
        },
        "selection_family": {
            "family_id": definition.inference_family_id,
            "member_id": subject_id,
            "ordered_member_ids": list(selection_members),
        },
    }
    canonical_bytes(value)
    return value


def _validate_metric_inventory(
    metrics: Mapping[str, Mapping[str, int]],
) -> None:
    if set(metrics) != set(FIXED_HOLD_REPLAY_CLAIMS):
        raise RuntimeError("fixed-hold claim metric inventory drifted")
    for claim_id, expected in _CLAIM_METRIC_FIELDS.items():
        values = metrics[claim_id]
        if set(values) != expected or any(type(value) is not int for value in values.values()):
            raise RuntimeError(
                f"fixed-hold claim metrics drifted for {claim_id}"
            )


def _derive_metrics_and_statistics(
    *,
    trace: Mapping[str, Any] | FixedHoldSubjectTraceSnapshot,
    definition: FixedHoldProtocolDefinition,
    validator: FixedHoldTraceValidator,
    parameters: Mapping[str, Any],
) -> tuple[dict[str, dict[str, int]], dict[str, object]]:
    if dict(parameters) != fixed_hold_calculation_parameters(
        definition,
        validator,
    ):
        raise ScientificTraceError(
            "fixed-hold calculation parameters drifted"
        )
    snapshot = validate_fixed_hold_subject_trace_snapshot(
        trace,
        definition=definition,
        validator=validator,
    )
    parts = _fixed_hold_family_snapshot_parts(
        snapshot.family,
        definition=definition,
        validator=validator,
    )
    family = parts["family"]
    trades = parts["trades"]
    daily = parts["daily"]
    subject_id = snapshot.subject_id
    subject_member = next(
        item for item in family.values() if item["executable_id"] == subject_id
    )
    subject_configuration = str(subject_member["configuration_id"])
    append_mismatches, causality, unknown_cost = parts["intent_counts"][
        subject_configuration
    ]
    subject_trades = tuple(
        item for item in trades if item["executable_id"] == subject_id
    )
    controls = _subject_control_binding(
        definition=definition,
        subject_id=subject_id,
    )
    inference_families = fixed_hold_subject_inference_families(
        definition,
        subject_id,
    )
    opposite_id = str(controls["opposite_executable_id"])
    feature_ids = tuple(str(value) for value in controls["feature_executable_ids"])
    if not feature_ids:
        raise RuntimeError("validated fixed-hold family lost feature controls")
    historical_context = HistoricalSearchContext(
        context_id=definition.historical_context_id,
        prior_global_exposure_count=(
            definition.historical_prior_global_exposure_count
        ),
    )
    family_ids = tuple(
        str(item["executable_id"]) for item in family.values()
    )
    registration_ids = {
        str(item["executable_id"]): (
            "historical-reference:"
            f"{item['historical_reference_executable_id']}"
        )
        for item in family.values()
    }
    selection_result = infer_concurrent_selection_family(
        plan=_selection_plan(
            family_id=str(
                inference_families["selection_family"]["family_id"]
            ),
            hypothesis_ids=family_ids,
            registration_ids=registration_ids,
            definition=definition,
        ),
        daily_pnl_by_hypothesis=daily,
        historical_context=historical_context,
    )
    control_series: dict[str, dict[str, int]] = {}
    control_registration: dict[str, str] = {}
    opposite_hypothesis = _control_hypothesis_id("opposite", opposite_id)
    control_series[opposite_hypothesis] = {
        day: daily[subject_id][day] - daily[opposite_id][day]
        for day in daily[subject_id]
    }
    opposite_historical = str(
        controls["opposite_historical_executable_id"]
    )
    control_registration[opposite_hypothesis] = (
        f"historical-reference:{opposite_historical}"
    )
    feature_historical_ids = tuple(
        str(value)
        for value in controls["feature_historical_executable_ids"]
    )
    feature_hypotheses: list[str] = []
    for feature_id, historical_id in zip(
        feature_ids,
        feature_historical_ids,
        strict=True,
    ):
        hypothesis_id = _control_hypothesis_id("feature", feature_id)
        feature_hypotheses.append(hypothesis_id)
        control_series[hypothesis_id] = {
            day: daily[subject_id][day] - daily[feature_id][day]
            for day in daily[subject_id]
        }
        control_registration[hypothesis_id] = (
            f"historical-reference:{historical_id}"
        )
    if tuple(sorted(control_series)) != tuple(
        inference_families["paired_control_family"]["ordered_member_ids"]
    ):
        raise RuntimeError("fixed-hold control inference family drifted")
    control_result = infer_concurrent_selection_family(
        plan=_selection_plan(
            family_id=str(
                inference_families["paired_control_family"]["family_id"]
            ),
            hypothesis_ids=tuple(control_series),
            registration_ids=control_registration,
            definition=definition,
        ),
        daily_pnl_by_hypothesis=control_series,
        historical_context=historical_context,
    )
    subject_selection = selection_result.hypothesis(subject_id)
    opposite_control = control_result.hypothesis(opposite_hypothesis)
    feature_controls = tuple(
        control_result.hypothesis(hypothesis_id)
        for hypothesis_id in feature_hypotheses
    )
    native_values = [
        int(item["native_net_pnl_micropoints"]) for item in subject_trades
    ]
    stress_values = [
        int(item["stress_net_pnl_micropoints"]) for item in subject_trades
    ]
    subject_daily = daily[subject_id]
    positive_days = sorted(
        (value for value in subject_daily.values() if value > 0),
        reverse=True,
    )
    gross_positive = sum(positive_days)
    top5_share = (
        0
        if gross_positive <= 0
        else min(
            1_000_000,
            int(
                round(
                    1_000_000 * sum(positive_days[:5]) / gross_positive
                )
            ),
        )
    )
    fold_values = {
        fold_id: [
            int(item["native_net_pnl_micropoints"])
            for item in subject_trades
            if item["fold_id"] == fold_id
        ]
        for fold_id in definition.fold_ids
    }
    fold_profit_factors = sorted(
        _profit_factor(values) for values in fold_values.values()
    )
    regime_values: dict[str, dict[str, list[int]]] = {
        regime: {fold_id: [] for fold_id in definition.fold_ids}
        for regime in definition.allowed_regimes
    }
    for trade in subject_trades:
        regime_values[str(trade["regime"])][str(trade["fold_id"])].append(
            int(trade["native_net_pnl_micropoints"])
        )
    supported_regimes = 0
    for by_fold in regime_values.values():
        trade_count = sum(len(values) for values in by_fold.values())
        evaluable = sum(bool(values) for values in by_fold.values())
        winning = sum(
            sum(values) > 0 for values in by_fold.values() if values
        )
        if (
            sum(sum(values) for values in by_fold.values()) > 0
            and trade_count >= 30
            and evaluable >= 5
            and winning >= 3
            and 2 * winning > evaluable
        ):
            supported_regimes += 1
    net = sum(native_values)
    opposite_net = sum(daily[opposite_id].values())
    feature_deltas = tuple(
        net - sum(daily[feature_id].values()) for feature_id in feature_ids
    )
    metrics = {
        "activity_and_concentration": {
            "entries_per_day_milli": int(
                round(1000 * len(subject_trades) / len(subject_daily))
            ),
            "top5_profit_day_share_ppm": top5_share,
            "trade_count": len(subject_trades),
        },
        "after_cost_fixed_lot_economics": {
            "median_fold_profit_factor_milli": fold_profit_factors[
                len(fold_profit_factors) // 2
            ],
            "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": (
                _monthly_drawdown_share(subject_trades)
            ),
            "net_profit_micropoints": net,
            "stress_net_profit_micropoints": sum(stress_values),
        },
        "causal_feature_and_execution_validity": {
            "append_invariance_mismatch_count": append_mismatches,
            "causality_violation_count": causality,
            "nonfinite_metric_count": 0,
            "prefix_invariance_mismatch_count": parts["prefix_mismatches"],
            "unknown_cost_unresolved_signal_count": unknown_cost,
        },
        "registered_control_contrast": {
            "feature_control_worst_delta_net_profit_micropoints": min(
                feature_deltas
            ),
            "feature_control_worst_pvalue_upper_ppm": max(
                item.synchronized_max_monte_carlo_upper_pvalue_ppm
                for item in feature_controls
            ),
            "opposite_sign_pvalue_upper_ppm": (
                opposite_control.synchronized_max_monte_carlo_upper_pvalue_ppm
            ),
            "opposite_sign_worst_delta_net_profit_micropoints": (
                net - opposite_net
            ),
        },
        "selection_aware_signal_evidence": {
            "selection_aware_pvalue_ppm": (
                subject_selection.synchronized_max_monte_carlo_upper_pvalue_ppm
            ),
        },
        "temporal_and_regime_stability": {
            "evaluable_folds": sum(bool(values) for values in fold_values.values()),
            "supported_positive_regime_count": supported_regimes,
            "winning_fold_count": sum(
                sum(values) > 0 for values in fold_values.values() if values
            ),
        },
    }
    _validate_metric_inventory(metrics)
    context_manifest = historical_context.manifest()
    statistics = {
        "exposure_semantics": {
            "exact_concurrent_family_adjustment_factor": (
                selection_result.plan.family_size
            ),
            "exact_subject_control_family_adjustment_factor": (
                control_result.plan.family_size
            ),
            "historical_context_adjustment_authority": context_manifest[
                "adjustment_authority"
            ],
            "original_family_end_global_exposure_count": (
                definition.original_family_end_global_exposure_count
            ),
            "prospective_prior_global_exposure_count": (
                historical_context.prior_global_exposure_count
            ),
        },
        "historical_context": context_manifest,
        "paired_control_family": control_result.statistical_manifest(),
        "selection_family": selection_result.statistical_manifest(),
        "subject_controls": controls,
    }
    if (
        selection_result.plan.family_size
        != parameters["exact_concurrent_family_adjustment_factor"]
        or context_manifest["adjustment_authority"]
        != parameters["historical_context_adjustment_authority"]
    ):
        raise ScientificTraceError(
            "fixed-hold exposure semantics drifted"
        )
    canonical_bytes(metrics)
    canonical_bytes(statistics)
    return metrics, statistics


def build_fixed_hold_trace_calculation(
    *,
    trace: Mapping[str, Any] | FixedHoldSubjectTraceSnapshot,
    definition: FixedHoldProtocolDefinition,
    validator: FixedHoldTraceValidator,
    trace_output_name: str,
    trace_hash: str,
) -> dict[str, object]:
    snapshot = validate_fixed_hold_subject_trace_snapshot(
        trace,
        definition=definition,
        validator=validator,
    )
    expected_hash = snapshot.sha256
    if _digest("fixed-hold trace hash", trace_hash) != expected_hash:
        raise ScientificTraceError(
            "fixed-hold trace hash differs from the opened trace"
        )
    parameters = fixed_hold_calculation_parameters(definition, validator)
    metrics, statistics = _derive_metrics_and_statistics(
        trace=snapshot,
        definition=definition,
        validator=validator,
        parameters=parameters,
    )
    subject = _fixed_hold_subject_snapshot_value(
        snapshot,
        definition=definition,
        validator=validator,
    )
    value = {
        "evidence_modes": list(FIXED_HOLD_REPLAY_EVIDENCE_MODES),
        "executable_id": subject["subject_executable_id"],
        "job_hash": subject["job_hash"],
        "job_id": subject["job_id"],
        "metrics": metrics,
        "mission_id": subject["mission_id"],
        "parameters": parameters,
        "protocol_definition": definition.manifest(),
        "protocol_id": definition.protocol_id,
        "schema": SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
        "statistics": statistics,
        "trace": {
            "output_name": _ascii(
                "fixed-hold trace output name",
                trace_output_name,
            ),
            "sha256": expected_hash,
        },
    }
    canonical_bytes(value)
    return value


def validate_fixed_hold_trace_calculation(
    *,
    trace: Mapping[str, Any] | FixedHoldSubjectTraceSnapshot,
    calculation: Mapping[str, Any],
    definition: FixedHoldProtocolDefinition,
    validator: FixedHoldTraceValidator,
) -> dict[str, dict[str, int]]:
    if (
        not isinstance(calculation, Mapping)
        or set(calculation) != _CALCULATION_FIELDS
        or calculation.get("schema") != SCIENTIFIC_CALCULATION_PROOF_SCHEMA
        or calculation.get("protocol_id") != definition.protocol_id
    ):
        raise ScientificTraceError(
            "fixed-hold calculation proof schema is invalid"
        )
    parsed_definition = fixed_hold_protocol_definition_from_manifest(
        calculation.get("protocol_definition")
    )
    if parsed_definition.manifest() != definition.manifest():
        raise ScientificTraceError(
            "fixed-hold calculation protocol definition drifted"
        )
    snapshot = validate_fixed_hold_subject_trace_snapshot(
        trace,
        definition=definition,
        validator=validator,
    )
    subject = _fixed_hold_subject_snapshot_value(
        snapshot,
        definition=definition,
        validator=validator,
    )
    if any(
        calculation.get(name) != subject.get(trace_name)
        for name, trace_name in (
            ("executable_id", "subject_executable_id"),
            ("job_hash", "job_hash"),
            ("job_id", "job_id"),
            ("mission_id", "mission_id"),
        )
    ):
        raise ScientificTraceError(
            "fixed-hold calculation belongs to another execution"
        )
    if tuple(calculation.get("evidence_modes", ())) != (
        FIXED_HOLD_REPLAY_EVIDENCE_MODES
    ):
        raise ScientificTraceError(
            "fixed-hold calculation evidence modes drifted"
        )
    trace_reference = _mapping(
        "fixed-hold calculation trace reference",
        calculation.get("trace"),
    )
    if set(trace_reference) != {"output_name", "sha256"}:
        raise ScientificTraceError(
            "fixed-hold calculation trace reference is invalid"
        )
    _ascii("fixed-hold trace output name", trace_reference.get("output_name"))
    if trace_reference.get("sha256") != snapshot.sha256:
        raise ScientificTraceError(
            "fixed-hold calculation is not bound to the opened trace"
        )
    parameters = _mapping(
        "fixed-hold calculation parameters",
        calculation.get("parameters"),
    )
    statistics = _mapping(
        "fixed-hold calculation statistics",
        calculation.get("statistics"),
    )
    if set(statistics) != _CALCULATION_STATISTIC_FIELDS:
        raise ScientificTraceError(
            "fixed-hold calculation statistics schema is invalid"
        )
    metrics, expected_statistics = _derive_metrics_and_statistics(
        trace=snapshot,
        definition=definition,
        validator=validator,
        parameters=parameters,
    )
    if calculation.get("metrics") != metrics:
        raise ScientificTraceError(
            "fixed-hold metrics drifted from atomic rows"
        )
    if dict(statistics) != expected_statistics:
        raise ScientificTraceError(
            "fixed-hold deterministic inference proof drifted"
        )
    if snapshot.subject_id != calculation["executable_id"]:
        raise RuntimeError("fixed-hold subject identity changed during validation")
    return metrics


__all__ = [
    "FIXED_HOLD_CONTROL_SCHEMA",
    "FIXED_HOLD_FAMILY_TRACE_SCHEMA",
    "FIXED_HOLD_MEMBER_SCHEMA",
    "FIXED_HOLD_PROTOCOL_DEFINITION_SCHEMA",
    "FIXED_HOLD_REPLAY_CLAIMS",
    "FIXED_HOLD_REPLAY_CRITERIA",
    "FIXED_HOLD_REPLAY_EVIDENCE_MODES",
    "FIXED_HOLD_TRACE_VALIDATOR",
    "FIXED_HOLD_TRACE_VALIDATOR_SCHEMA",
    "FixedHoldFamilyTraceSnapshot",
    "FixedHoldProtocolDefinition",
    "FixedHoldSubjectTraceSnapshot",
    "FixedHoldTraceValidator",
    "bind_fixed_hold_family_trace",
    "bind_fixed_hold_family_trace_snapshot",
    "build_fixed_hold_family_trace",
    "build_fixed_hold_trace_calculation",
    "expected_fixed_hold_control_inventory",
    "expected_fixed_hold_family_inventory",
    "extract_fixed_hold_family_trace_from_subject",
    "fixed_hold_calculation_parameters",
    "fixed_hold_protocol_definition_from_manifest",
    "fixed_hold_observation_id",
    "fixed_hold_original_family_provenance",
    "fixed_hold_subject_inference_families",
    "fixed_hold_trace_attribution",
    "fixed_hold_trace_controls",
    "fixed_hold_trace_implementation_identities",
    "fixed_hold_trace_implementation_sha256",
    "validate_fixed_hold_family_trace",
    "validate_fixed_hold_family_trace_snapshot",
    "validate_fixed_hold_subject_trace_snapshot",
    "validate_fixed_hold_trace_calculation",
]
