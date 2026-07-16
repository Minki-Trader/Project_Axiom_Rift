"""Event-level direction meta-policy over the fixed STU-0092 frontier."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.discovery import SimulationResult
from axiom_rift.research.high_vol_target_reversal_chassis import (
    high_vol_target_reversal_configurations,
    high_vol_target_reversal_executable,
)
from axiom_rift.research.session_dense_positive_sleeve_chassis import (
    session_dense_positive_sleeve_configurations,
    simulate_session_dense_positive_sleeves,
)


SELECTION_TOTAL_EXPOSURES = 593
MODEL_MAX_DEPTH = 3
MODEL_MIN_SAMPLES_LEAF = 128
MODEL_RANDOM_SEED = 612337279
_PROFILES = ("stu0092_fixed_direction_control", "event_direction_tree_subject")
_THIS_FILE = Path(__file__).resolve()
_DISCOVERY_FILE = _THIS_FILE.with_name("event_direction_meta_discovery.py")


def event_direction_meta_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def event_direction_meta_discovery_source_sha256() -> str:
    """Bind the file that implements the subject label and fitted model."""

    return sha256(_DISCOVERY_FILE.read_bytes()).hexdigest()


def event_direction_meta_baseline() -> ExecutableSpec:
    return high_vol_target_reversal_executable(
        high_vol_target_reversal_configurations()[1]
    )


@dataclass(frozen=True, slots=True)
class EventDirectionMetaConfiguration:
    profile: str

    def __post_init__(self) -> None:
        if self.profile not in _PROFILES:
            raise ValueError("event direction meta-policy profile is invalid")

    @property
    def configuration_id(self) -> str:
        return self.profile

    @property
    def holding_bars(self) -> int:
        return 12

    @property
    def signal_sign(self) -> int:
        return 1

    @property
    def target_quantile_bp(self) -> int:
        return 9000

    @property
    def uses_event_model(self) -> bool:
        return self.profile == "event_direction_tree_subject"

    def semantic_parameters(self) -> dict[str, Any]:
        values = dict(event_direction_meta_baseline().parameter_values())
        values.update(
            {
                "event_direction_label_profile": (
                    "not_active_exact_stu0092_control"
                    if not self.uses_event_model
                    else "fold_train_native_best_of_follow_or_reverse_by_slot_horizon"
                ),
                "event_direction_model_profile": (
                    "not_active_exact_stu0092_control"
                    if not self.uses_event_model
                    else "depth3_minleaf128_joint_sleeve_state_tree"
                ),
                "event_direction_synthesis_profile": (
                    "exact_stu0092_fixed_roles"
                    if not self.uses_event_model
                    else "joint_sleeve_event_direction_meta_policy"
                ),
                "event_direction_trade_policy": (
                    "exact_stu0092_fixed_roles"
                    if not self.uses_event_model
                    else "mandatory_follow_or_reverse_no_abstention"
                ),
            }
        )
        return values


def event_direction_meta_configurations() -> tuple[EventDirectionMetaConfiguration, ...]:
    return tuple(EventDirectionMetaConfiguration(profile) for profile in _PROFILES)


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.event_direction_meta_chassis.{name}@sha256:"
        f"{event_direction_meta_chassis_implementation_sha256()}"
    )


def _discovery_local(name: str) -> str:
    return (
        f"axiom_rift.research.event_direction_meta_discovery.{name}@sha256:"
        f"{event_direction_meta_discovery_source_sha256()}"
    )


def _domain_identities(executable: ExecutableSpec, domain: str) -> tuple[str, ...]:
    return tuple(
        component.identity
        for component in executable.components
        if component.protocol.startswith(f"{domain}.")
    )


def event_direction_meta_components() -> tuple[ComponentSpec, ...]:
    baseline = event_direction_meta_baseline()
    base = baseline.components
    label = ComponentSpec(
        display_name="fold-train slot-horizon native direction-action label",
        protocol="label.event_native_follow_or_reverse_by_slot_horizon.v1",
        implementation=_discovery_local("fit_event_direction_model"),
        spec={
            "actions": ["follow_baseline", "reverse_baseline"],
            "cost_basis": (
                "completed_period_spread_proxy_with_native_directional_"
                "cost_formula"
            ),
            "fit_role": "train_is_only",
            "parameter_fields": ["event_direction_label_profile"],
            "router_holding_bars": 12,
            "target_holding_bars": 6,
            "tie_action": "follow_baseline",
        },
        semantic_dependencies=(
            *_domain_identities(baseline, "lifecycle"),
            *_domain_identities(baseline, "execution"),
        ),
    )
    model = ComponentSpec(
        display_name="fold-train shallow joint-sleeve event direction tree",
        protocol="model.fold_train_shallow_event_direction_tree.v1",
        implementation=_discovery_local("fit_event_direction_model"),
        spec={
            "criterion": "log_loss",
            "feature_state": [
                "existing_five_multiscale_path_features",
                "existing_router_score_and_availability",
                "existing_target_score_and_availability",
                "existing_volatility_tercile_and_availability",
                "slot_identity",
            ],
            "fit_role": "train_is_only",
            "max_depth": MODEL_MAX_DEPTH,
            "min_samples_leaf": MODEL_MIN_SAMPLES_LEAF,
            "parameter_fields": ["event_direction_model_profile"],
            "random_seed": MODEL_RANDOM_SEED,
            "sklearn_version": "1.8.0",
        },
        semantic_dependencies=(
            *_domain_identities(baseline, "feature"),
            *_domain_identities(baseline, "regime"),
            label.identity,
        ),
    )
    trade = ComponentSpec(
        display_name="mandatory event follow-or-reverse next-open direction",
        protocol="trade.event_direction_follow_or_reverse_no_abstention.v1",
        implementation=_local("apply_event_direction_actions"),
        spec={
            "action_set": [-1, 1],
            "activity_change_allowed": False,
            "entry_time": "unchanged_next_exact_bar_open",
            "parameter_fields": ["event_direction_trade_policy"],
            "zero_action_allowed": False,
        },
        semantic_dependencies=(
            *_domain_identities(baseline, "trade"),
            model.identity,
        ),
    )
    synthesis = ComponentSpec(
        display_name="joint-sleeve event direction meta-policy composition",
        protocol="synthesis.joint_sleeve_event_direction_meta_policy.v1",
        implementation=_local("simulate_event_direction_meta_policy"),
        spec={
            "controlled_activity": "exact_stu0092_event_schedule",
            "controlled_holding_bars": {
                "regime_router": 12,
                "target_direction": 6,
            },
            "controlled_lot_per_slot": 1,
            "parameter_fields": ["event_direction_synthesis_profile"],
        },
        semantic_dependencies=(
            *_domain_identities(baseline, "portfolio"),
            trade.identity,
        ),
    )
    return (*base, label, model, trade, synthesis)


def event_direction_meta_executable(
    configuration: EventDirectionMetaConfiguration,
) -> ExecutableSpec:
    if not configuration.uses_event_model:
        return event_direction_meta_baseline()
    baseline = event_direction_meta_baseline()
    return ExecutableSpec(
        display_name="STU0092 activity with shallow event direction meta-policy",
        components=event_direction_meta_components(),
        parameters=configuration.semantic_parameters(),
        data_contract=baseline.data_contract,
        split_contract=baseline.split_contract,
        clock_contract=baseline.clock_contract,
        cost_contract=baseline.cost_contract,
        engine_contract=baseline.engine_contract,
    )


def executable_configuration_map() -> dict[str, EventDirectionMetaConfiguration]:
    return {
        event_direction_meta_executable(configuration).identity: configuration
        for configuration in event_direction_meta_configurations()
    }


def apply_event_direction_actions(
    score: np.ndarray,
    router_actions: np.ndarray,
    target_actions: np.ndarray,
) -> np.ndarray:
    values = np.asarray(score, dtype=float)
    if values.ndim != 2 or values.shape[1] != 2:
        raise ValueError("event direction score matrix is invalid")
    actions = (np.asarray(router_actions), np.asarray(target_actions))
    if any(value.shape != (len(values),) for value in actions):
        raise ValueError("event direction action length differs")
    if any(not np.isin(value, (-1, 1)).all() for value in actions):
        raise ValueError("event direction action must be follow or reverse")
    result = values.copy()
    result[:, 0] *= actions[0]
    result[:, 1] *= actions[1]
    if not np.array_equal(np.abs(result), np.abs(values), equal_nan=True):
        raise ValueError("event direction policy changed score activity")
    return result


def simulate_event_direction_meta_policy(
    *,
    frame: pd.DataFrame,
    score: np.ndarray,
    volatility: np.ndarray,
    run: np.ndarray,
    threshold: float,
    configuration: EventDirectionMetaConfiguration,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    fold_id: str,
    regime_cutoffs: tuple[float, float],
    effective_spread: np.ndarray | None = None,
) -> SimulationResult:
    values = np.asarray(score, dtype=float)
    if values.shape != (len(frame), 2):
        raise ValueError("event direction meta-policy score matrix is invalid")
    return simulate_session_dense_positive_sleeves(
        frame=frame,
        score=values,
        volatility=volatility,
        run=run,
        threshold=threshold,
        configuration=session_dense_positive_sleeve_configurations()[1],
        test_start=test_start,
        test_end=test_end,
        fold_id=fold_id,
        regime_cutoffs=regime_cutoffs,
        effective_spread=effective_spread,
    )


__all__ = [
    "MODEL_MAX_DEPTH",
    "MODEL_MIN_SAMPLES_LEAF",
    "MODEL_RANDOM_SEED",
    "SELECTION_TOTAL_EXPOSURES",
    "EventDirectionMetaConfiguration",
    "apply_event_direction_actions",
    "event_direction_meta_baseline",
    "event_direction_meta_chassis_implementation_sha256",
    "event_direction_meta_discovery_source_sha256",
    "event_direction_meta_components",
    "event_direction_meta_configurations",
    "event_direction_meta_executable",
    "executable_configuration_map",
    "simulate_event_direction_meta_policy",
]
