"""Prospective two-policy cost-aware execution replay composition.

The historical source module is reconstruction data, not an executable runner.
This module accepts its Writer-bound family as typed input and builds
new Executables whose engine identity binds the corrected atomic trace,
protocol, and exact concurrent-family inference.  Historical search exposure
is retained only as context; it is never an adjustment factor.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import scipy

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research import (
    cost_aware_execution_protocol as protocol_module,
    data as data_module,
)
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
    validate_controlled_executable,
)
from axiom_rift.research.cost_aware_execution_protocol import (
    COST_AWARE_EXECUTION_ALPHA_PPM,
    COST_AWARE_EXECUTION_BASE_SEED,
    COST_AWARE_EXECUTION_BLOCK_LENGTHS,
    COST_AWARE_EXECUTION_BOOTSTRAP_SAMPLES,
    COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID,
    COST_AWARE_EXECUTION_HISTORICAL_CONTEXT_ADJUSTMENT_AUTHORITY,
    COST_AWARE_EXECUTION_MONTE_CARLO_CONFIDENCE_PPM,
    COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
    COST_AWARE_EXECUTION_PROTOCOL_ID,
    COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID,
    CostAwareExecutionProtocolDefinition,
    cost_aware_execution_protocol_definition,
)
from axiom_rift.research.cost_aware_execution_trace import (
    cost_aware_execution_trace_implementation_sha256,
)
from axiom_rift.research.discovery import (
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    discovery_implementation_sha256,
)
from axiom_rift.research.event_label_discovery import (
    BARRIER_MULTIPLE_MILLI,
    event_label_implementation_sha256,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
    HistoricalFamilySpec,
    HistoricalMemberSpec,
    PrimaryControlBinding,
)
from axiom_rift.research.selection_inference import (
    HistoricalSearchContext,
    selection_inference_implementation_sha256,
)


COST_AWARE_EXECUTION_PAIR_HOLDING_BARS = 48
COST_AWARE_EXECUTION_PAIR_SELECTOR_QUANTILE_BP = 8_500
COST_AWARE_EXECUTION_PAIR_SPREAD_REFERENCE_BARS = 288
COST_AWARE_EXECUTION_PAIR_SPREAD_REFERENCE_MIN_OBSERVATIONS = 24
COST_AWARE_EXECUTION_PAIR_SPREAD_LIMIT_MILLI = 1_200
COST_AWARE_EXECUTION_PAIR_CLOCK_CONTRACT = (
    "clock:fpmarkets_m5_completed_decision_plus_5m_strict_prior_gate_v1"
)
COST_AWARE_EXECUTION_PAIR_COST_CONTRACT = (
    "cost:fpmarkets_completed_period_spread_proxy_segment_prior_positive_"
    "288_min_24_entry_exit_minus_1_half_spread_stress_v1"
)
COST_AWARE_EXECUTION_PAIR_CONTEXT_PARAMETER = (
    "historical_context_prior_global_exposure_count"
)
COST_AWARE_EXECUTION_PAIR_ORIGINAL_END_PARAMETER = (
    "original_family_end_global_exposure_count"
)
_POLICIES = ("unconditional_next_open", "causal_spread_abstention")
_THIS_FILE = Path(__file__).resolve()
_PAIR_ENGINE_FILE = _THIS_FILE.with_name(
    "cost_aware_execution_pair_engine.py"
)


class CostAwareExecutionPairError(ValueError):
    """The Writer-bound prospective pair is invalid."""


def cost_aware_execution_pair_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def cost_aware_execution_pair_loader_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


def cost_aware_execution_protocol_implementation_sha256() -> str:
    return sha256(Path(protocol_module.__file__).resolve().read_bytes()).hexdigest()


def cost_aware_execution_pair_engine_implementation_sha256() -> str:
    """Bind Executable identity to the concrete producer without importing it.

    The producer imports this composition module, so reading the sibling source
    bytes here keeps the dependency acyclic while still making any engine change
    produce a new prospective Executable identity.
    """

    return sha256(_PAIR_ENGINE_FILE.read_bytes()).hexdigest()


def cost_aware_execution_pair_producer_implementation_identities(
) -> dict[str, str]:
    return {
        "adapter_sha256": cost_aware_execution_pair_implementation_sha256(),
        "discovery_sha256": discovery_implementation_sha256(),
        "pair_engine_sha256": (
            cost_aware_execution_pair_engine_implementation_sha256()
        ),
        "event_label_sha256": event_label_implementation_sha256(),
        "loader_sha256": cost_aware_execution_pair_loader_sha256(),
        "protocol_sha256": cost_aware_execution_protocol_implementation_sha256(),
        "selection_sha256": selection_inference_implementation_sha256(),
        "trace_sha256": cost_aware_execution_trace_implementation_sha256(),
    }


@dataclass(frozen=True, slots=True)
class CostAwareExecutionPairConfiguration:
    ordinal: int
    configuration_id: str
    historical_reference_executable_id: str
    execution_policy: str
    holding_bars: int = COST_AWARE_EXECUTION_PAIR_HOLDING_BARS
    label_profile: str = "first_passage_label_48"
    selector_quantile_bp: int = COST_AWARE_EXECUTION_PAIR_SELECTOR_QUANTILE_BP
    signal_sign: int = 1
    spread_limit_milli: int = COST_AWARE_EXECUTION_PAIR_SPREAD_LIMIT_MILLI
    spread_reference_bars: int = COST_AWARE_EXECUTION_PAIR_SPREAD_REFERENCE_BARS

    def __post_init__(self) -> None:
        expected_reference = {
            "unconditional_next_open": (
                COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID
            ),
            "causal_spread_abstention": (
                COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID
            ),
        }
        if (
            type(self.ordinal) is not int
            or self.ordinal not in (1, 2)
            or type(self.configuration_id) is not str
            or not self.configuration_id
            or not self.configuration_id.isascii()
            or self.execution_policy not in _POLICIES
            or self.historical_reference_executable_id
            != expected_reference[self.execution_policy]
            or self.holding_bars != COST_AWARE_EXECUTION_PAIR_HOLDING_BARS
            or self.label_profile != "first_passage_label_48"
            or self.selector_quantile_bp
            != COST_AWARE_EXECUTION_PAIR_SELECTOR_QUANTILE_BP
            or self.signal_sign != 1
            or self.spread_limit_milli
            != COST_AWARE_EXECUTION_PAIR_SPREAD_LIMIT_MILLI
            or self.spread_reference_bars
            != COST_AWARE_EXECUTION_PAIR_SPREAD_REFERENCE_BARS
        ):
            raise CostAwareExecutionPairError(
                "cost-aware execution family member is invalid"
            )

    def semantic_parameters(self) -> dict[str, object]:
        return {
            "configuration_id": self.configuration_id,
            "execution_policy": self.execution_policy,
            "historical_reference_executable_id": (
                self.historical_reference_executable_id
            ),
            "holding_bars": self.holding_bars,
            "label_profile": self.label_profile,
            "selector_quantile_bp": self.selector_quantile_bp,
            "signal_sign": self.signal_sign,
            "spread_limit_milli": self.spread_limit_milli,
            "spread_reference_bars": self.spread_reference_bars,
        }


def _configuration_from_member(
    member: HistoricalMemberSpec,
) -> CostAwareExecutionPairConfiguration:
    parameters = member.parameter_values()
    expected = {
        "execution_policy",
        "holding_bars",
        "label_profile",
        "selector_quantile_bp",
        "signal_sign",
        "spread_limit_milli",
        "spread_reference_bars",
    }
    if set(parameters) != expected:
        raise CostAwareExecutionPairError(
            "historical cost-aware parameter surface is invalid"
        )
    return CostAwareExecutionPairConfiguration(
        ordinal=member.ordinal,
        configuration_id=member.configuration_id,
        historical_reference_executable_id=(
            member.historical_reference_executable_id
        ),
        execution_policy=parameters["execution_policy"],
        holding_bars=parameters["holding_bars"],
        label_profile=parameters["label_profile"],
        selector_quantile_bp=parameters["selector_quantile_bp"],
        signal_sign=parameters["signal_sign"],
        spread_limit_milli=parameters["spread_limit_milli"],
        spread_reference_bars=parameters["spread_reference_bars"],
    )


def cost_aware_execution_pair_configurations(
    historical_family: HistoricalFamilySpec,
) -> tuple[CostAwareExecutionPairConfiguration, ...]:
    if not isinstance(historical_family, HistoricalFamilySpec):
        raise TypeError("cost-aware family is not Writer-bound")
    values = tuple(
        _configuration_from_member(member)
        for member in historical_family.members
    )
    controls = tuple(historical_family.controls)
    expected_control_pairs = {
        (
            COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID,
            COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID,
        ),
        (
            COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID,
            COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID,
        ),
    }
    actual_control_pairs = {
        (
            item.subject_historical_executable_id,
            item.primary_control_historical_executable_id,
        )
        for item in controls
        if isinstance(item, PrimaryControlBinding)
    }
    if (
        historical_family.family_size != 2
        or tuple(value.ordinal for value in values) != (1, 2)
        or tuple(value.execution_policy for value in values) != _POLICIES
        or historical_family.target_historical_executable_id
        != COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID
        or len(controls) != 2
        or actual_control_pairs != expected_control_pairs
    ):
        raise CostAwareExecutionPairError(
            "Writer-bound family is not the exact registered policy pair"
        )
    return values


def _local(name: str) -> str:
    return (
        "axiom_rift.research.cost_aware_execution_pair."
        f"{name}@sha256:{cost_aware_execution_pair_implementation_sha256()}"
    )


def _event(name: str) -> str:
    return (
        f"axiom_rift.research.event_label_discovery.{name}@sha256:"
        f"{event_label_implementation_sha256()}"
    )


def _shared(name: str) -> str:
    return (
        f"axiom_rift.research.discovery.{name}@sha256:"
        f"{discovery_implementation_sha256()}"
    )


def _trace(name: str) -> str:
    return (
        f"axiom_rift.research.cost_aware_execution_trace.{name}@sha256:"
        f"{cost_aware_execution_trace_implementation_sha256()}"
    )


def _selection(name: str) -> str:
    return (
        f"axiom_rift.research.selection_inference.{name}@sha256:"
        f"{selection_inference_implementation_sha256()}"
    )


def cost_aware_execution_pair_components(
    historical_family: HistoricalFamilySpec,
) -> tuple[ComponentSpec, ...]:
    cost_aware_execution_pair_configurations(historical_family)
    feature = ComponentSpec(
        display_name="fixed completed-bar multiscale predictor inputs",
        protocol="feature.fixed_multiscale_return_path.replay.v1",
        implementation=_event("_raw_features"),
        spec={
            "availability": "completed_bar_only",
            "fields": [
                "normalized_return_12",
                "normalized_return_48",
                "normalized_return_192",
                "path_efficiency_48",
                "volatility_ratio_48_192",
            ],
        },
    )
    label = ComponentSpec(
        display_name="fixed first-passage path label",
        protocol="label.first_passage_path_event.replay.v1",
        implementation=_event("_labels"),
        spec={
            "barrier_multiple_milli": BARRIER_MULTIPLE_MILLI,
            "future_end_must_be_inside_train": True,
            "horizon_bars": COST_AWARE_EXECUTION_PAIR_HOLDING_BARS,
        },
    )
    model = ComponentSpec(
        display_name="fixed fold-trained ridge score",
        protocol="model.fold_train_ridge_linear.replay.v1",
        implementation=_event("_fit_model"),
        spec={
            "fit_role": "train_is_only",
            "penalty_milli": 1_000,
            "standardization": "train_mean_population_std",
        },
        semantic_dependencies=(feature.identity, label.identity),
    )
    calibration = ComponentSpec(
        display_name="fixed identity score calibration",
        protocol="calibration.identity_score.replay.v1",
        implementation=_local("identity_score_calibration"),
        spec={"fit_required": False, "mapping": "identity"},
        semantic_dependencies=(model.identity,),
    )
    selector = ComponentSpec(
        display_name="fixed train-only absolute score selector",
        protocol="selector.fold_train_abs_quantile.replay.v1",
        implementation=_event("calibrate_selector"),
        spec={
            "calibration_role": "train_is_only",
            "minimum_train_observations": 1_000,
            "parameter_fields": ["selector_quantile_bp"],
            "quantile_method": "higher",
        },
        semantic_dependencies=(calibration.identity,),
    )
    trade = ComponentSpec(
        display_name="fixed completed-bar directional intent",
        protocol="trade.completed_bar_next_open_direction.replay.v2",
        implementation=_shared("simulate_fixed_hold"),
        spec={
            "decision_time": "bar_open_plus_5m",
            "direction": "signal_sign_times_score_sign",
            "entry_time": "next_exact_bar_open",
            "parameter_fields": ["signal_sign"],
        },
        semantic_dependencies=(selector.identity,),
    )
    lifecycle = ComponentSpec(
        display_name="fixed 48-bar nonoverlap lifecycle",
        protocol="lifecycle.fixed_hold_no_overlap.replay.v2",
        implementation=_trace("compute_cost_aware_execution_pair_trace"),
        spec={
            "entry_overlap": "reject_while_policy_slot_is_occupied",
            "exit_surface": "exact_bar_open_after_48_bars",
            "gap_action": "exclude_path_without_source_read",
            "parameter_fields": ["holding_bars"],
        },
        semantic_dependencies=(trade.identity,),
    )
    risk = ComponentSpec(
        display_name="fixed one-lot pair risk",
        protocol="risk.fixed_one_lot.replay.v1",
        implementation=_trace("compute_cost_aware_execution_pair_trace"),
        spec={"dynamic_sizing": False, "lot": 1, "positions_per_policy": 1},
        semantic_dependencies=(lifecycle.identity,),
    )
    execution = ComponentSpec(
        display_name="causal completed-bar spread policy pair",
        protocol="execution.causal_completed_bar_spread_policy_pair.replay.v1",
        implementation=_trace("compute_cost_aware_execution_pair_trace"),
        spec={
            "cost_proxy_sources": {
                "entry": "entry_index_minus_1",
                "exit": "exit_index_minus_1",
            },
            "gate_input": "completed_decision_bar_effective_spread",
            "historical_context_adjustment_authority": (
                COST_AWARE_EXECUTION_HISTORICAL_CONTEXT_ADJUSTMENT_AUTHORITY
            ),
            "historical_family_identity": historical_family.identity,
            "parameter_fields": [
                "execution_policy",
                "spread_limit_milli",
                "spread_reference_bars",
            ],
            "policies": list(_POLICIES),
            "read_mask": "null_not_read_false_read_but_unavailable",
            "spread_gate_reference": (
                "same_segment_strict_prior_effective_spread_288_median_min_24"
            ),
            "spread_zero_repair": (
                "same_segment_strict_prior_positive_raw_288_median_min_24"
            ),
            "stress": "half_effective_spread_each_side",
            "unknown_gate_action": "cancel_before_entry_without_exit_read",
        },
        semantic_dependencies=(risk.identity,),
    )
    synthesis = ComponentSpec(
        display_name="registered historical paired-policy replay member",
        protocol="synthesis.historical_cost_aware_execution_pair_member.v1",
        implementation=_local("cost_aware_execution_pair_executable"),
        spec={
            "exact_member_count": historical_family.family_size,
            "historical_family_identity": historical_family.identity,
            "parameter_fields": [
                "configuration_id",
                "historical_reference_executable_id",
            ],
        },
        semantic_dependencies=(execution.identity,),
    )
    portfolio = ComponentSpec(
        display_name="exact paired-policy concurrent selection inference",
        protocol="portfolio.concurrent_cost_aware_execution_pair_inference.v1",
        implementation=_selection("infer_concurrent_selection_family"),
        spec={
            "alpha_ppm": COST_AWARE_EXECUTION_ALPHA_PPM,
            "base_seed": COST_AWARE_EXECUTION_BASE_SEED,
            "block_lengths": list(COST_AWARE_EXECUTION_BLOCK_LENGTHS),
            "bootstrap_samples": COST_AWARE_EXECUTION_BOOTSTRAP_SAMPLES,
            "historical_context_adjustment_authority": (
                COST_AWARE_EXECUTION_HISTORICAL_CONTEXT_ADJUSTMENT_AUTHORITY
            ),
            "monte_carlo_confidence_ppm": (
                COST_AWARE_EXECUTION_MONTE_CARLO_CONFIDENCE_PPM
            ),
            "parameter_fields": [
                COST_AWARE_EXECUTION_PAIR_CONTEXT_PARAMETER,
                COST_AWARE_EXECUTION_PAIR_ORIGINAL_END_PARAMETER,
            ],
            "primary_control_contrast_family_size": 1,
            "selection_family_size": historical_family.family_size,
        },
        semantic_dependencies=(synthesis.identity,),
    )
    return (
        feature,
        label,
        model,
        calibration,
        selector,
        trade,
        lifecycle,
        risk,
        execution,
        synthesis,
        portfolio,
    )


def _engine_contract() -> str:
    identities = cost_aware_execution_pair_producer_implementation_identities()
    return (
        "engine:cost_aware_execution_paired_policy_v1:"
        f"python{'.'.join(str(value) for value in sys.version_info[:3])}:"
        f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
        f"adapter_{identities['adapter_sha256']}:"
        f"pair_engine_{identities['pair_engine_sha256']}:"
        f"trace_{identities['trace_sha256']}:"
        f"protocol_{identities['protocol_sha256']}:"
        f"event_{identities['event_label_sha256']}:"
        f"loader_{identities['loader_sha256']}:"
        f"shared_{identities['discovery_sha256']}:"
        f"selection_{identities['selection_sha256']}:"
        "d04_family_1:e01_family_2"
    )


def _executable(
    *,
    display_name: str,
    components: tuple[ComponentSpec, ...],
    parameters: dict[str, object],
) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=display_name,
        components=components,
        parameters=parameters,
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:"
            "rolling_windows_9_observed_development"
        ),
        clock_contract=COST_AWARE_EXECUTION_PAIR_CLOCK_CONTRACT,
        cost_contract=COST_AWARE_EXECUTION_PAIR_COST_CONTRACT,
        engine_contract=_engine_contract(),
    )


def _shared_exposure_parameters(
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> dict[str, int]:
    if (
        type(historical_context_prior_global_exposure_count) is not int
        or type(original_family_end_global_exposure_count) is not int
        or original_family_end_global_exposure_count
        != COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
        or original_family_end_global_exposure_count
        < historical_family.family_size
        or historical_context_prior_global_exposure_count
        < original_family_end_global_exposure_count
    ):
        raise CostAwareExecutionPairError(
            "cost-aware historical exposure context is invalid"
        )
    return {
        COST_AWARE_EXECUTION_PAIR_CONTEXT_PARAMETER: (
            historical_context_prior_global_exposure_count
        ),
        COST_AWARE_EXECUTION_PAIR_ORIGINAL_END_PARAMETER: (
            original_family_end_global_exposure_count
        ),
    }


def cost_aware_execution_pair_executable(
    configuration: CostAwareExecutionPairConfiguration,
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> ExecutableSpec:
    if configuration not in cost_aware_execution_pair_configurations(
        historical_family
    ):
        raise CostAwareExecutionPairError(
            "configuration is outside the Writer-bound pair"
        )
    return _executable(
        display_name=(
            f"{historical_family.original_study_id} prospective execution "
            f"{configuration.configuration_id}"
        ),
        components=cost_aware_execution_pair_components(historical_family),
        parameters={
            **configuration.semantic_parameters(),
            **_shared_exposure_parameters(
                historical_family=historical_family,
                historical_context_prior_global_exposure_count=(
                    historical_context_prior_global_exposure_count
                ),
                original_family_end_global_exposure_count=(
                    original_family_end_global_exposure_count
                ),
            ),
        },
    )


def cost_aware_execution_pair_baseline_executable(
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> ExecutableSpec:
    components = cost_aware_execution_pair_components(historical_family)
    return _executable(
        display_name=(
            f"{historical_family.original_study_id} prospective execution "
            "non-evaluated comparison anchor"
        ),
        components=components,
        parameters={
            "configuration_id": "comparison-anchor",
            "execution_policy": "comparison_anchor",
            "historical_reference_executable_id": "none",
            "holding_bars": COST_AWARE_EXECUTION_PAIR_HOLDING_BARS,
            **_shared_exposure_parameters(
                historical_family=historical_family,
                historical_context_prior_global_exposure_count=(
                    historical_context_prior_global_exposure_count
                ),
                original_family_end_global_exposure_count=(
                    original_family_end_global_exposure_count
                ),
            ),
            "label_profile": "first_passage_label_48",
            "selector_quantile_bp": (
                COST_AWARE_EXECUTION_PAIR_SELECTOR_QUANTILE_BP
            ),
            "signal_sign": 1,
            "spread_limit_milli": COST_AWARE_EXECUTION_PAIR_SPREAD_LIMIT_MILLI,
            "spread_reference_bars": (
                COST_AWARE_EXECUTION_PAIR_SPREAD_REFERENCE_BARS
            ),
        },
    )


def cost_aware_execution_pair_controlled_chassis(
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> ControlledStudyChassis:
    baseline = cost_aware_execution_pair_baseline_executable(
        historical_family=historical_family,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
        original_family_end_global_exposure_count=(
            original_family_end_global_exposure_count
        ),
    )
    chassis = ControlledStudyChassis(
        baseline_executable=baseline,
        changed_domains=(
            ResearchLayer.EXECUTION,
            ResearchLayer.SYNTHESIS,
        ),
        controlled_domains=(
            ResearchLayer.CALIBRATION,
            ResearchLayer.FEATURE,
            ResearchLayer.LABEL,
            ResearchLayer.LIFECYCLE,
            ResearchLayer.MODEL,
            ResearchLayer.PORTFOLIO,
            ResearchLayer.RISK,
            ResearchLayer.SELECTOR,
            ResearchLayer.TRADE,
        ),
        architecture=ArchitectureChassisSpec.from_executable(baseline),
    )
    payload = chassis.to_identity_payload()
    for configuration in cost_aware_execution_pair_configurations(
        historical_family
    ):
        validate_controlled_executable(
            payload,
            cost_aware_execution_pair_executable(
                configuration,
                historical_family=historical_family,
                historical_context_prior_global_exposure_count=(
                    historical_context_prior_global_exposure_count
                ),
                original_family_end_global_exposure_count=(
                    original_family_end_global_exposure_count
                ),
            ),
        )
    return chassis


def cost_aware_execution_pair_executable_map(
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> dict[str, CostAwareExecutionPairConfiguration]:
    return {
        cost_aware_execution_pair_executable(
            configuration,
            historical_family=historical_family,
            historical_context_prior_global_exposure_count=(
                historical_context_prior_global_exposure_count
            ),
            original_family_end_global_exposure_count=(
                original_family_end_global_exposure_count
            ),
        ).identity: configuration
        for configuration in cost_aware_execution_pair_configurations(
            historical_family
        )
    }


def _validate_replay_context(
    context: HistoricalFamilyReplayContext,
) -> HistoricalFamilySpec:
    if not isinstance(context, HistoricalFamilyReplayContext):
        raise TypeError("cost-aware replay context is not typed")
    family = context.family
    cost_aware_execution_pair_configurations(family)
    if (
        context.original_family_end_global_exposure_count
        != COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
        or context.prior_global_exposure_count
        < context.original_family_end_global_exposure_count
    ):
        raise CostAwareExecutionPairError(
            "cost-aware historical exposure context is invalid"
        )
    return family


def cost_aware_execution_pair_protocol_definition(
    context: HistoricalFamilyReplayContext,
) -> CostAwareExecutionProtocolDefinition:
    family = _validate_replay_context(context)
    by_policy = {
        configuration.execution_policy: (
            cost_aware_execution_pair_executable(
                configuration,
                historical_family=family,
                historical_context_prior_global_exposure_count=(
                    context.prior_global_exposure_count
                ),
                original_family_end_global_exposure_count=(
                    context.original_family_end_global_exposure_count
                ),
            ).identity
        )
        for configuration in cost_aware_execution_pair_configurations(family)
    }
    return cost_aware_execution_protocol_definition(
        historical_family=family,
        prospective_control_executable_id=by_policy["unconditional_next_open"],
        prospective_target_executable_id=by_policy["causal_spread_abstention"],
    )


def cost_aware_execution_pair_historical_context(
    context: HistoricalFamilyReplayContext,
) -> HistoricalSearchContext:
    _validate_replay_context(context)
    return HistoricalSearchContext(
        context_id=context.family_authority_id,
        prior_global_exposure_count=context.prior_global_exposure_count,
    )


__all__ = [
    "COST_AWARE_EXECUTION_PAIR_CLOCK_CONTRACT",
    "COST_AWARE_EXECUTION_PAIR_CONTEXT_PARAMETER",
    "COST_AWARE_EXECUTION_PAIR_COST_CONTRACT",
    "COST_AWARE_EXECUTION_PAIR_HOLDING_BARS",
    "COST_AWARE_EXECUTION_PAIR_ORIGINAL_END_PARAMETER",
    "COST_AWARE_EXECUTION_PAIR_SELECTOR_QUANTILE_BP",
    "COST_AWARE_EXECUTION_PAIR_SPREAD_LIMIT_MILLI",
    "COST_AWARE_EXECUTION_PAIR_SPREAD_REFERENCE_BARS",
    "COST_AWARE_EXECUTION_PAIR_SPREAD_REFERENCE_MIN_OBSERVATIONS",
    "CostAwareExecutionPairConfiguration",
    "CostAwareExecutionPairError",
    "cost_aware_execution_pair_baseline_executable",
    "cost_aware_execution_pair_components",
    "cost_aware_execution_pair_configurations",
    "cost_aware_execution_pair_controlled_chassis",
    "cost_aware_execution_pair_engine_implementation_sha256",
    "cost_aware_execution_pair_executable",
    "cost_aware_execution_pair_executable_map",
    "cost_aware_execution_pair_historical_context",
    "cost_aware_execution_pair_implementation_sha256",
    "cost_aware_execution_pair_loader_sha256",
    "cost_aware_execution_pair_producer_implementation_identities",
    "cost_aware_execution_pair_protocol_definition",
    "cost_aware_execution_protocol_implementation_sha256",
]
