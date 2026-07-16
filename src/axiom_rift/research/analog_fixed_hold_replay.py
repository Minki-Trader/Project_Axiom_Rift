"""Prospective fixed-hold adapter for the exact historical STU-0061 family.

The scientific computation remains the decision-scoped analog v2 engine.  This
module gives its neutral family trace the common fixed-hold proof envelope so
the current strict clock, familywise-selection, and subject-control validators
can adjudicate the replay without the historical monolithic runner.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import pandas as pd

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.analog_state_family import (
    ANALOG_FAMILY_ALPHA_PPM,
    ANALOG_FAMILY_BASE_SEED,
    ANALOG_FAMILY_BLOCK_LENGTHS,
    ANALOG_FAMILY_BOOTSTRAP_SAMPLES,
    ANALOG_FAMILY_COMPARISON_ANCHOR_CONFIGURATION,
    ANALOG_FAMILY_COMPARISON_ANCHOR_PROFILE,
    ANALOG_FAMILY_MONTE_CARLO_CONFIDENCE_PPM,
    AnalogFamilyConfiguration,
    AnalogFamilySpec,
    AnalogProfileSpec,
    MULTISCALE_STATE_FEATURE_PROTOCOL,
    RETURN_ONLY_FEATURE_PROTOCOL,
    analog_replay_baseline_executable,
)
from axiom_rift.research.analog_state_replay_v2 import (
    ANALOG_SCOPED_QUERY_SCOPE_ID,
    analog_family_components_scoped_v2,
    analog_family_executable_scoped_v2,
    analog_replay_numerical_environment_identity,
    analog_replay_v2_bundle_sha256,
    compute_analog_family_trace_scoped_v2,
    validate_analog_family_trace_scoped_v2,
)
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
    component_domain,
    validate_controlled_executable,
)
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    EXPECTED_FOLD_IDS,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    loader_implementation_sha256,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FIXED_HOLD_TRACE_VALIDATOR,
    FixedHoldProtocolDefinition,
    build_fixed_hold_family_trace,
    expected_fixed_hold_family_inventory,
    fixed_hold_observation_id,
    fixed_hold_trace_implementation_sha256,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
    HistoricalFamilySpec,
)
from axiom_rift.research.scientific_trace import (
    ANALOG_FIXED_HOLD_REPLAY_TRACE_PROTOCOL_ID,
)
from axiom_rift.research.analog_state_trace import (
    analog_original_family_provenance,
)


ANALOG_FIXED_HOLD_REPLAY_CONTEXT_PARAMETER = (
    "historical_context_prior_global_exposure_count"
)
ANALOG_FIXED_HOLD_REPLAY_ORIGINAL_END_PARAMETER = (
    "original_family_end_global_exposure_count"
)
_THIS_FILE = Path(__file__).resolve()


def analog_fixed_hold_replay_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _analog_family_spec(
    historical_family: HistoricalFamilySpec,
) -> AnalogFamilySpec:
    """Derive algorithm parameters from Writer-bound family data."""

    if not isinstance(historical_family, HistoricalFamilySpec):
        raise TypeError("analog replay historical family is not Writer-bound")
    expected_parameter_keys = {
        "family_id",
        "holding_bars",
        "library_stride",
        "neighbors",
        "profile",
        "selector_quantile_bp",
        "signal_sign",
    }
    profile_protocols = {
        "knn_multiscale_state_25": MULTISCALE_STATE_FEATURE_PROTOCOL,
        "knn_return_control_25": RETURN_ONLY_FEATURE_PROTOCOL,
    }
    parameters = tuple(member.parameter_values() for member in historical_family.members)
    if (
        historical_family.family_size != 4
        or any(set(value) != expected_parameter_keys for value in parameters)
    ):
        raise ValueError("analog replay family parameter surface is invalid")
    shared_fields = (
        "family_id",
        "holding_bars",
        "library_stride",
        "neighbors",
        "selector_quantile_bp",
    )
    shared = {
        name: {value[name] for value in parameters}
        for name in shared_fields
    }
    if any(len(values) != 1 for values in shared.values()):
        raise ValueError("analog replay family shared parameters drifted")
    references: dict[tuple[str, int], str] = {}
    for member, value in zip(
        historical_family.members,
        parameters,
        strict=True,
    ):
        profile_id = value["profile"]
        signal_sign = value["signal_sign"]
        if (
            type(profile_id) is not str
            or profile_id not in profile_protocols
            or signal_sign not in {-1, 1}
            or (profile_id, signal_sign) in references
        ):
            raise ValueError("analog replay profile/sign surface is invalid")
        references[(profile_id, signal_sign)] = (
            member.historical_reference_executable_id
        )
    expected_keys = {
        (profile_id, signal_sign)
        for profile_id in profile_protocols
        for signal_sign in (-1, 1)
    }
    if set(references) != expected_keys:
        raise ValueError("analog replay profile/sign surface is incomplete")
    family = AnalogFamilySpec(
        family_id=next(iter(shared["family_id"])),
        horizon=next(iter(shared["holding_bars"])),
        library_stride=next(iter(shared["library_stride"])),
        neighbors=next(iter(shared["neighbors"])),
        selector_quantile_bp=next(iter(shared["selector_quantile_bp"])),
        profiles=tuple(
            AnalogProfileSpec(
                profile_id=profile_id,
                feature_protocol=profile_protocols[profile_id],
                positive_historical_reference_executable_id=(
                    references[(profile_id, 1)]
                ),
                negative_historical_reference_executable_id=(
                    references[(profile_id, -1)]
                ),
            )
            for profile_id in sorted(profile_protocols)
        ),
    )
    configurations = family.configurations()
    for member, configuration in zip(
        historical_family.members,
        configurations,
        strict=True,
    ):
        semantic = configuration.semantic_parameters()
        configuration_id = semantic.pop("configuration_id", None)
        reference = semantic.pop("historical_reference_executable_id", None)
        if (
            configuration_id != configuration.configuration_id
            or member.configuration_id != configuration_id
            or member.parameter_values() != semantic
            or member.historical_reference_executable_id != reference
        ):
            raise ValueError("analog replay family mapping drifted")
    return family


def _validate_historical_context(
    *,
    prior_global_exposure_count: object,
    original_family_end_global_exposure_count: object,
    historical_family: HistoricalFamilySpec,
) -> tuple[int, int]:
    if (
        type(prior_global_exposure_count) is not int
        or type(original_family_end_global_exposure_count) is not int
        or original_family_end_global_exposure_count
        < historical_family.family_size
        or prior_global_exposure_count
        < original_family_end_global_exposure_count
    ):
        raise ValueError(
            "analog replay historical exposure context is invalid for "
            f"{historical_family.original_study_id}"
        )
    return (
        prior_global_exposure_count,
        original_family_end_global_exposure_count,
    )


def analog_fixed_hold_replay_configurations(
    historical_family: HistoricalFamilySpec,
) -> tuple[AnalogFamilyConfiguration, ...]:
    return _analog_family_spec(historical_family).configurations()


def _local(name: str) -> str:
    return (
        "axiom_rift.research.analog_fixed_hold_replay."
        f"{name}@sha256:{analog_fixed_hold_replay_implementation_sha256()}"
    )


def analog_fixed_hold_replay_components(
    historical_family: HistoricalFamilySpec,
) -> tuple[ComponentSpec, ...]:
    """Rebind only synthesis and inference around the scoped-v2 chain."""

    identity_map: dict[str, str] = {}
    components: list[ComponentSpec] = []
    replacement_count = 0
    analog_family = _analog_family_spec(historical_family)
    for previous in analog_family_components_scoped_v2(analog_family):
        domain = component_domain(previous)
        protocol = previous.protocol
        implementation = previous.implementation
        specification = previous.specification()
        if domain is ResearchLayer.SYNTHESIS:
            protocol = "synthesis.registered_analog_fixed_hold_replay_member.v3"
            implementation = _local("analog_fixed_hold_replay_executable")
            specification = {
                "exact_member_count": historical_family.family_size,
                "historical_family_identity": (
                    historical_family.identity
                ),
                "parameter_fields": [
                    "configuration_id",
                    "historical_reference_executable_id",
                ],
            }
            replacement_count += 1
        elif domain is ResearchLayer.PORTFOLIO:
            protocol = "portfolio.concurrent_analog_fixed_hold_replay.v3"
            implementation = _local("analog_fixed_hold_replay_protocol_definition")
            specification = {
                "historical_context_adjustment_authority": (
                    "context_only_never_adjustment_factor"
                ),
                "parameter_fields": [
                    "family_id",
                    ANALOG_FIXED_HOLD_REPLAY_CONTEXT_PARAMETER,
                    ANALOG_FIXED_HOLD_REPLAY_ORIGINAL_END_PARAMETER,
                    "selection_alpha_ppm",
                    "selection_base_seed",
                    "selection_block_lengths",
                    "selection_bootstrap_samples",
                    "selection_monte_carlo_confidence_ppm",
                ],
                "selection_family_scope": (
                    "exact_registered_concurrent_family"
                ),
            }
            replacement_count += 1
        current = ComponentSpec(
            display_name=previous.display_name,
            protocol=protocol,
            implementation=implementation,
            spec=specification,
            semantic_dependencies=tuple(
                identity_map.get(dependency, dependency)
                for dependency in previous.semantic_dependencies
            ),
        )
        identity_map[previous.identity] = current.identity
        components.append(current)
    if replacement_count != 2:
        raise RuntimeError("analog fixed-hold component boundary drifted")
    return tuple(components)


def _engine_contract(historical_family: HistoricalFamilySpec) -> str:
    base = analog_family_executable_scoped_v2(
        analog_fixed_hold_replay_configurations(historical_family)[0]
    )
    return (
        f"{base.engine_contract}:fixed_hold_adapter_"
        f"{analog_fixed_hold_replay_implementation_sha256()}:"
        f"fixed_hold_trace_{fixed_hold_trace_implementation_sha256()}"
    )


def analog_fixed_hold_replay_executable(
    configuration: AnalogFamilyConfiguration,
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> ExecutableSpec:
    if configuration not in analog_fixed_hold_replay_configurations(
        historical_family
    ):
        raise ValueError(
            "configuration is outside the exact "
            f"{historical_family.original_study_id} family"
        )
    context, original_end = _validate_historical_context(
        prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
        original_family_end_global_exposure_count=(
            original_family_end_global_exposure_count
        ),
        historical_family=historical_family,
    )
    scoped = analog_family_executable_scoped_v2(configuration)
    return ExecutableSpec(
        display_name=(
            f"{historical_family.original_study_id} fixed-hold replay "
            f"{configuration.configuration_id}"
        ),
        components=analog_fixed_hold_replay_components(historical_family),
        parameters={
            **scoped.parameter_values(),
            ANALOG_FIXED_HOLD_REPLAY_CONTEXT_PARAMETER: context,
            ANALOG_FIXED_HOLD_REPLAY_ORIGINAL_END_PARAMETER: original_end,
        },
        data_contract=scoped.data_contract,
        split_contract=scoped.split_contract,
        clock_contract=scoped.clock_contract,
        cost_contract=scoped.cost_contract,
        engine_contract=_engine_contract(historical_family),
    )


def analog_fixed_hold_replay_baseline_executable(
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> ExecutableSpec:
    context, original_end = _validate_historical_context(
        prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
        original_family_end_global_exposure_count=(
            original_family_end_global_exposure_count
        ),
        historical_family=historical_family,
    )
    original = analog_replay_baseline_executable(
        _analog_family_spec(historical_family)
    )
    scoped = analog_family_executable_scoped_v2(
        analog_fixed_hold_replay_configurations(historical_family)[0]
    )
    return ExecutableSpec(
        display_name=(
            f"{historical_family.original_study_id} fixed-hold "
            "non-evaluated comparison anchor"
        ),
        components=analog_fixed_hold_replay_components(historical_family),
        parameters={
            **original.parameter_values(),
            "configuration_id": ANALOG_FAMILY_COMPARISON_ANCHOR_CONFIGURATION,
            "historical_reference_executable_id": "none",
            "profile": ANALOG_FAMILY_COMPARISON_ANCHOR_PROFILE,
            "query_scope_id": ANALOG_SCOPED_QUERY_SCOPE_ID,
            "signal_sign": 0,
            ANALOG_FIXED_HOLD_REPLAY_CONTEXT_PARAMETER: context,
            ANALOG_FIXED_HOLD_REPLAY_ORIGINAL_END_PARAMETER: original_end,
        },
        data_contract=scoped.data_contract,
        split_contract=scoped.split_contract,
        clock_contract=scoped.clock_contract,
        cost_contract=scoped.cost_contract,
        engine_contract=_engine_contract(historical_family),
    )


def analog_fixed_hold_replay_controlled_chassis(
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> ControlledStudyChassis:
    baseline = analog_fixed_hold_replay_baseline_executable(
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
        original_family_end_global_exposure_count=(
            original_family_end_global_exposure_count
        ),
        historical_family=historical_family,
    )
    chassis = ControlledStudyChassis(
        baseline_executable=baseline,
        changed_domains=(
            ResearchLayer.FEATURE,
            ResearchLayer.SYNTHESIS,
            ResearchLayer.TRADE,
        ),
        controlled_domains=(
            ResearchLayer.EXECUTION,
            ResearchLayer.LABEL,
            ResearchLayer.LIFECYCLE,
            ResearchLayer.MODEL,
            ResearchLayer.PORTFOLIO,
            ResearchLayer.RISK,
            ResearchLayer.SELECTOR,
        ),
        architecture=ArchitectureChassisSpec.from_executable(baseline),
    )
    payload = chassis.to_identity_payload()
    for configuration in analog_fixed_hold_replay_configurations(
        historical_family
    ):
        validate_controlled_executable(
            payload,
            analog_fixed_hold_replay_executable(
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


def analog_fixed_hold_replay_producer_implementation_identities(
) -> dict[str, str]:
    return {
        "analog_fixed_hold_adapter_sha256": (
            analog_fixed_hold_replay_implementation_sha256()
        ),
        "analog_scoped_v2_bundle_sha256": analog_replay_v2_bundle_sha256(),
        "loader_sha256": loader_implementation_sha256(),
        "numerical_environment_sha256": (
            analog_replay_numerical_environment_identity()
        ),
    }


def analog_fixed_hold_replay_protocol_definition(
    context: HistoricalFamilyReplayContext,
) -> FixedHoldProtocolDefinition:
    if not isinstance(context, HistoricalFamilyReplayContext):
        raise TypeError("analog fixed-hold replay context is not typed")
    historical_family = context.family
    historical_count, original_end = _validate_historical_context(
        prior_global_exposure_count=context.prior_global_exposure_count,
        original_family_end_global_exposure_count=(
            context.original_family_end_global_exposure_count
        ),
        historical_family=historical_family,
    )
    analog_family = _analog_family_spec(historical_family)
    configurations = analog_fixed_hold_replay_configurations(
        historical_family
    )
    executables = tuple(
        analog_fixed_hold_replay_executable(
            configuration,
            historical_family=historical_family,
            historical_context_prior_global_exposure_count=historical_count,
            original_family_end_global_exposure_count=original_end,
        )
        for configuration in configurations
    )
    clocks = {executable.clock_contract for executable in executables}
    costs = {executable.cost_contract for executable in executables}
    if len(clocks) != 1 or len(costs) != 1:
        raise RuntimeError(
            f"{historical_family.original_study_id} fixed-hold "
            "execution contracts drifted"
        )
    return FixedHoldProtocolDefinition(
        family=historical_family,
        prospective_executable_ids=tuple(
            executable.identity for executable in executables
        ),
        protocol_id=ANALOG_FIXED_HOLD_REPLAY_TRACE_PROTOCOL_ID,
        fold_ids=EXPECTED_FOLD_IDS,
        invariance_keys=tuple(
            profile.profile_id
            for profile in analog_family.profiles
        ),
        allowed_regimes=("high", "low", "middle"),
        dataset_sha256=DATASET_SHA256,
        material_identity=OBSERVED_MATERIAL_ID,
        split_artifact_sha256=ROLLING_SPLIT_SHA256,
        clock_contract=next(iter(clocks)),
        cost_contract=next(iter(costs)),
        producer_implementation_identities=tuple(
            sorted(
                analog_fixed_hold_replay_producer_implementation_identities().items()
            )
        ),
        historical_context_id=context.family_authority_id,
        historical_prior_global_exposure_count=historical_count,
        original_family_end_global_exposure_count=original_end,
        alpha_ppm=ANALOG_FAMILY_ALPHA_PPM,
        bootstrap_samples=ANALOG_FAMILY_BOOTSTRAP_SAMPLES,
        block_lengths=ANALOG_FAMILY_BLOCK_LENGTHS,
        monte_carlo_confidence_ppm=(
            ANALOG_FAMILY_MONTE_CARLO_CONFIDENCE_PPM
        ),
        base_seed=ANALOG_FAMILY_BASE_SEED,
    )


def _frame_time_index(values: Sequence[object]) -> dict[str, int]:
    source = (
        values.reset_index(drop=True)
        if isinstance(values, pd.Series)
        else pd.Series(values, copy=False)
    )
    parsed = pd.to_datetime(source, errors="raise")
    if parsed.dt.tz is not None:
        raise ValueError("analog fixed-hold frame times must be timezone-naive")
    texts = tuple(value.isoformat() for value in parsed)
    if len(texts) != len(set(texts)):
        raise ValueError("analog fixed-hold frame times must be unique")
    return {value: index for index, value in enumerate(texts)}


def _time_row_index(
    time_index: Mapping[str, int],
    *,
    name: str,
    value: object,
) -> int:
    if type(value) is not str:
        raise ValueError(f"{name} must be an ISO-8601 timestamp")
    index = time_index.get(value)
    if type(index) is not int or index < 0:
        raise ValueError(f"{name} is absent from observed development rows")
    return index


def _member_maps(
    definition: FixedHoldProtocolDefinition,
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str]]:
    inventory = expected_fixed_hold_family_inventory(definition)
    by_configuration = {
        str(item["configuration_id"]): item for item in inventory
    }
    if len(by_configuration) != definition.family.family_size:
        raise RuntimeError("analog fixed-hold member inventory is ambiguous")
    executable_by_configuration = {
        configuration_id: str(item["executable_id"])
        for configuration_id, item in by_configuration.items()
    }
    return by_configuration, executable_by_configuration


def _convert_trade(
    row: Mapping[str, Any],
    *,
    member: Mapping[str, Any],
    time_index: Mapping[str, int],
) -> dict[str, object]:
    holding_bars = int(member["parameters"]["holding_bars"])
    value = {
        "availability_time": row["availability_time"],
        "configuration_id": member["configuration_id"],
        "decision_bar_index": _time_row_index(
            time_index,
            name="trade decision bar",
            value=row["decision_bar_open_time"],
        ),
        "decision_bar_open_time": row["decision_bar_open_time"],
        "decision_spread_source_bar_index": _time_row_index(
            time_index,
            name="trade decision spread source",
            value=row["decision_spread_source_bar_open_time"],
        ),
        "decision_spread_source_bar_open_time": row[
            "decision_spread_source_bar_open_time"
        ],
        "decision_spread_information_complete_at": row[
            "decision_spread_information_complete_at"
        ],
        "decision_spread_known": row["decision_spread_known"],
        "decision_time": row["decision_time"],
        "direction": row["direction"],
        "entry_bar_index": _time_row_index(
            time_index,
            name="trade entry",
            value=row["entry_time"],
        ),
        "entry_spread_source_bar_index": _time_row_index(
            time_index,
            name="trade entry spread source",
            value=row["entry_spread_source_bar_open_time"],
        ),
        "entry_spread_source_bar_open_time": row[
            "entry_spread_source_bar_open_time"
        ],
        "entry_spread_information_complete_at": row[
            "entry_spread_information_complete_at"
        ],
        "entry_spread_known": row["entry_spread_known"],
        "entry_time": row["entry_time"],
        "executable_id": member["executable_id"],
        "exit_bar_index": _time_row_index(
            time_index,
            name="trade exit",
            value=row["exit_time"],
        ),
        "exit_spread_source_bar_index": _time_row_index(
            time_index,
            name="trade exit spread source",
            value=row["exit_spread_source_bar_open_time"],
        ),
        "exit_spread_source_bar_open_time": row[
            "exit_spread_source_bar_open_time"
        ],
        "exit_spread_information_complete_at": row[
            "exit_spread_information_complete_at"
        ],
        "exit_spread_known": row["exit_spread_known"],
        "exit_time": row["exit_time"],
        "fold_id": row["fold_id"],
        "gross_pnl_micropoints": row["gross_pnl_micropoints"],
        "historical_reference_executable_id": member[
            "historical_reference_executable_id"
        ],
        "holding_bars": holding_bars,
        "native_cost_micropoints": row["native_cost_micropoints"],
        "native_net_pnl_micropoints": row[
            "native_net_pnl_micropoints"
        ],
        "observation_id": "pending",
        "regime": row["regime"],
        "stress_cost_micropoints": row["stress_cost_micropoints"],
        "stress_net_pnl_micropoints": row[
            "stress_net_pnl_micropoints"
        ],
        "spread_semantics": row["spread_semantics"],
    }
    value["observation_id"] = fixed_hold_observation_id("trade", value)
    return value


def _convert_intent(
    row: Mapping[str, Any],
    *,
    member: Mapping[str, Any],
    time_index: Mapping[str, int],
) -> dict[str, object]:
    decision_bar_open = str(row["decision_bar_open_time"])
    holding_bars = int(member["parameters"]["holding_bars"])
    value = {
        "availability_time": row["availability_time"],
        "configuration_id": member["configuration_id"],
        "decision_bar_index": _time_row_index(
            time_index,
            name="intent decision bar",
            value=decision_bar_open,
        ),
        "decision_bar_open_time": decision_bar_open,
        "decision_spread_source_bar_index": _time_row_index(
            time_index,
            name="intent decision spread source",
            value=row["decision_spread_source_bar_open_time"],
        ),
        "decision_spread_source_bar_open_time": row[
            "decision_spread_source_bar_open_time"
        ],
        "decision_spread_information_complete_at": row[
            "decision_spread_information_complete_at"
        ],
        "decision_spread_known": row["decision_spread_known"],
        "decision_time": row["decision_time"],
        "direction": row["direction"],
        "entry_bar_index": _time_row_index(
            time_index,
            name="intent entry",
            value=row["entry_time"],
        ),
        "entry_spread_source_bar_index": _time_row_index(
            time_index,
            name="intent entry spread source",
            value=row["entry_spread_source_bar_open_time"],
        ),
        "entry_spread_source_bar_open_time": row[
            "entry_spread_source_bar_open_time"
        ],
        "entry_spread_information_complete_at": row[
            "entry_spread_information_complete_at"
        ],
        "entry_spread_known": row["entry_spread_known"],
        "entry_time": row["entry_time"],
        "executable_id": member["executable_id"],
        "exit_bar_index": _time_row_index(
            time_index,
            name="intent exit",
            value=row["exit_time"],
        ),
        "exit_spread_source_bar_index": _time_row_index(
            time_index,
            name="intent exit spread source",
            value=row["exit_spread_source_bar_open_time"],
        ),
        "exit_spread_source_bar_open_time": row[
            "exit_spread_source_bar_open_time"
        ],
        "exit_spread_information_complete_at": row[
            "exit_spread_information_complete_at"
        ],
        "exit_spread_known": row["exit_spread_known"],
        "exit_time": row["exit_time"],
        "fold_id": row["fold_id"],
        "historical_reference_executable_id": member[
            "historical_reference_executable_id"
        ],
        "holding_bars": holding_bars,
        "observation_id": "pending",
        "ordinal": row["ordinal"],
        "scope": row["scope"],
        "spread_semantics": row["spread_semantics"],
        "status": row["status"],
    }
    value["observation_id"] = fixed_hold_observation_id("intent", value)
    return value


def convert_analog_scoped_trace_to_fixed_hold(
    trace: Mapping[str, object],
    *,
    definition: FixedHoldProtocolDefinition,
    observed_frame_times: Sequence[object],
) -> dict[str, object]:
    """Convert current scoped-v2 rows and immediately run strict validation."""

    if not isinstance(definition.family, HistoricalFamilySpec):
        raise ValueError("analog fixed-hold definition family is not Writer-bound")
    analog_family = _analog_family_spec(definition.family)
    provenance = analog_original_family_provenance(
        analog_family,
        context_id=definition.historical_context_id,
        end_global_exposure_count=(
            definition.original_family_end_global_exposure_count
        ),
    )
    neutral = validate_analog_family_trace_scoped_v2(
        trace,
        family=analog_family,
        original_family_provenance=provenance,
    )
    time_index = _frame_time_index(observed_frame_times)
    members, executable_by_configuration = _member_maps(definition)
    source_members = {
        str(item["configuration_id"]): item
        for item in neutral["ordered_family"]
    }
    if set(source_members) != set(members):
        raise ValueError("analog scoped trace family membership drifted")
    for configuration_id, member in members.items():
        source = source_members[configuration_id]
        if source.get("historical_reference_executable_id") != member.get(
            "historical_reference_executable_id"
        ):
            raise ValueError("analog historical member mapping drifted")

    # The analog field names are historical. Their values are opaque digests of
    # the complete causal simulation surface and must pass through unchanged.
    invariance = tuple(
        {
            "compared_row_count": item["compared_row_count"],
            "fold_id": item["fold_id"],
            "full_feature_values_sha256": item[
                "full_score_values_sha256"
            ],
            "invariance_key": item["profile_id"],
            "prefix_feature_values_sha256": item[
                "prefix_score_values_sha256"
            ],
        }
        for item in neutral["invariance_comparisons"]
    )
    trades = [
        _convert_trade(
            item,
            member=members[str(item["configuration_id"])],
            time_index=time_index,
        )
        for item in neutral["trade_observations"]
    ]
    trades.sort(
        key=lambda item: (
            str(item["configuration_id"]),
            str(item["fold_id"]),
            str(item["decision_time"]),
            str(item["observation_id"]),
        )
    )
    intents = [
        _convert_intent(
            item,
            member=members[str(item["configuration_id"])],
            time_index=time_index,
        )
        for item in neutral["intent_observations"]
    ]
    intents.sort(
        key=lambda item: (
            str(item["configuration_id"]),
            str(item["fold_id"]),
            str(item["scope"]),
            int(item["ordinal"]),
            str(item["observation_id"]),
        )
    )
    eligible_days = tuple(
        {
            **item,
            "executable_id": executable_by_configuration[
                str(item["configuration_id"])
            ],
        }
        for item in neutral["eligible_day_observations"]
    )
    return build_fixed_hold_family_trace(
        definition=definition,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
        windows=neutral["windows"],
        invariance_comparisons=invariance,
        trade_observations=trades,
        intent_observations=intents,
        eligible_day_observations=eligible_days,
    )


def compute_analog_fixed_hold_family_trace(
    repository_root: str | Path,
    definition: FixedHoldProtocolDefinition,
) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
    """Compute scoped-v2 once, convert its rows, and preserve raw metrics."""

    root = Path(repository_root).resolve()
    if not isinstance(definition.family, HistoricalFamilySpec):
        raise ValueError("analog fixed-hold trace family is not Writer-bound")
    analog_family = _analog_family_spec(definition.family)
    provenance = analog_original_family_provenance(
        analog_family,
        context_id=definition.historical_context_id,
        end_global_exposure_count=(
            definition.original_family_end_global_exposure_count
        ),
    )
    scoped_trace, raw_metrics = compute_analog_family_trace_scoped_v2(
        root,
        family=analog_family,
        original_family_provenance=provenance,
    )
    data = load_observed_development(root)
    converted = convert_analog_scoped_trace_to_fixed_hold(
        scoped_trace,
        definition=definition,
        observed_frame_times=data.frame["time"],
    )
    source_ids = {
        str(item["configuration_id"]): str(item["executable_id"])
        for item in scoped_trace["ordered_family"]
    }
    target_ids = {
        str(item["configuration_id"]): str(item["executable_id"])
        for item in converted["ordered_family"]
    }
    if set(raw_metrics) != set(source_ids.values()):
        raise RuntimeError("analog scoped raw metric inventory drifted")
    remapped_metrics = {
        target_ids[configuration_id]: dict(raw_metrics[source_id])
        for configuration_id, source_id in source_ids.items()
    }
    return converted, remapped_metrics


__all__ = [
    "ANALOG_FIXED_HOLD_REPLAY_CONTEXT_PARAMETER",
    "ANALOG_FIXED_HOLD_REPLAY_ORIGINAL_END_PARAMETER",
    "analog_fixed_hold_replay_baseline_executable",
    "analog_fixed_hold_replay_components",
    "analog_fixed_hold_replay_configurations",
    "analog_fixed_hold_replay_controlled_chassis",
    "analog_fixed_hold_replay_executable",
    "analog_fixed_hold_replay_implementation_sha256",
    "analog_fixed_hold_replay_producer_implementation_identities",
    "analog_fixed_hold_replay_protocol_definition",
    "compute_analog_fixed_hold_family_trace",
    "convert_analog_scoped_trace_to_fixed_hold",
]
