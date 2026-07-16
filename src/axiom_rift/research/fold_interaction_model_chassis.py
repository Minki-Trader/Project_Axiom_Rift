"""Controlled linear versus pairwise-interaction ridge model chassis."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd
import scipy

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research import data as data_module
from axiom_rift.research.discovery import (
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    SELECTION_BOOTSTRAP_SAMPLES,
    SELECTION_SEED,
    discovery_implementation_sha256,
)
from axiom_rift.research.event_label_discovery import (
    BARRIER_MULTIPLE_MILLI,
    HORIZON,
    RIDGE_PENALTY_MILLI,
    _fit_model,
    event_label_implementation_sha256,
)


SELECTION_TOTAL_EXPOSURES = 530
SELECTOR_QUANTILE_BP = 8_500
_PROFILES = ("linear_ridge_control", "pairwise_interaction_ridge")
_THIS_FILE = Path(__file__).resolve()


def fold_interaction_model_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def loader_implementation_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class FoldInteractionModelConfiguration:
    profile: str
    signal_sign: int = 1
    holding_bars: int = HORIZON

    def __post_init__(self) -> None:
        if (
            self.profile not in _PROFILES
            or self.signal_sign != 1
            or self.holding_bars != HORIZON
        ):
            raise ValueError("fold-interaction model configuration invalid")

    @property
    def configuration_id(self) -> str:
        return f"{self.profile}-direct-h{HORIZON}"

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "barrier_multiple_milli": BARRIER_MULTIPLE_MILLI,
            "holding_bars": HORIZON,
            "label_profile": "first_passage_label_48",
            "model_profile": self.profile,
            "ridge_penalty_milli": RIDGE_PENALTY_MILLI,
            "selector_quantile_bp": SELECTOR_QUANTILE_BP,
            "signal_sign": self.signal_sign,
        }


def fold_interaction_model_configurations(
) -> tuple[FoldInteractionModelConfiguration, ...]:
    return tuple(FoldInteractionModelConfiguration(profile=value) for value in _PROFILES)


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.fold_interaction_model_chassis.{name}"
        f"@sha256:{fold_interaction_model_chassis_implementation_sha256()}"
    )


def _event(name: str) -> str:
    return (
        f"axiom_rift.research.event_label_discovery.{name}"
        f"@sha256:{event_label_implementation_sha256()}"
    )


def _shared(name: str) -> str:
    return (
        f"axiom_rift.research.discovery.{name}"
        f"@sha256:{discovery_implementation_sha256()}"
    )


def fold_interaction_model_components() -> tuple[ComponentSpec, ...]:
    feature = ComponentSpec(
        display_name="fixed completed-bar multiscale predictor inputs",
        protocol="feature.fixed_multiscale_return_path.v1",
        implementation=_event("raw_features"),
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
        protocol="label.first_passage_path_event.v1",
        implementation=_event("build_labels"),
        spec={
            "barrier_multiple_milli": BARRIER_MULTIPLE_MILLI,
            "future_end_must_be_inside_train": True,
            "horizon_bars": HORIZON,
        },
    )
    model = ComponentSpec(
        display_name="fold-trained linear or pairwise-interaction ridge score",
        protocol="model.fold_train_pairwise_interaction_ridge.v1",
        implementation=_local("fit_model_profile"),
        spec={
            "fit_role": "train_is_only",
            "interaction_terms": "all_ten_unique_pairwise_products_no_squares",
            "parameter_fields": ["model_profile"],
            "penalty_milli": RIDGE_PENALTY_MILLI,
            "profiles": list(_PROFILES),
            "standardization": "train_mean_population_std_after_profile_expansion",
        },
        semantic_dependencies=(feature.identity, label.identity),
    )
    selector = ComponentSpec(
        display_name="fixed train-only absolute score selector",
        protocol="selector.fold_train_abs_quantile.v3",
        implementation=_event("calibrate_selector"),
        spec={
            "calibration_role": "train_is_only",
            "minimum_train_observations": 1000,
            "quantile_basis_points": SELECTOR_QUANTILE_BP,
            "quantile_method": "higher",
        },
        semantic_dependencies=(model.identity,),
    )
    trade = ComponentSpec(
        display_name="fixed completed-bar next-open directional entry",
        protocol="trade.completed_bar_next_open_direction.v3",
        implementation=_shared("simulate_fixed_hold"),
        spec={
            "decision_time": "bar_open_plus_5m",
            "direction": "signal_sign_times_score_sign",
            "parameter_fields": ["signal_sign"],
        },
        semantic_dependencies=(selector.identity,),
    )
    lifecycle = ComponentSpec(
        display_name="fixed 48-bar nonoverlap lifecycle",
        protocol="lifecycle.fixed_hold_no_overlap.v3",
        implementation=_shared("simulate_fixed_hold"),
        spec={
            "entry_overlap": "reject_while_position_slot_is_occupied",
            "exit_surface": "exact_bar_open_after_48_bars",
            "gap_action": "exclude_path",
        },
        semantic_dependencies=(trade.identity,),
    )
    risk = ComponentSpec(
        display_name="fixed one-lot risk",
        protocol="risk.fixed_one_lot.v2",
        implementation=_shared("simulate_fixed_hold"),
        spec={"dynamic_sizing": False, "lot": 1, "positions_per_sleeve": 1},
        semantic_dependencies=(lifecycle.identity,),
    )
    execution = ComponentSpec(
        display_name="fixed FPMarkets completed-period spread proxy execution",
        protocol="execution.fpmarkets_completed_bar_spread_proxy.v3",
        implementation=_shared("execution_pnl"),
        spec={"point": "0.01", "stress": "half_effective_spread_each_side"},
        semantic_dependencies=(risk.identity,),
    )
    return feature, label, model, selector, trade, lifecycle, risk, execution


def fold_interaction_model_executable(
    configuration: FoldInteractionModelConfiguration,
) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=f"fold interaction model {configuration.configuration_id}",
        components=fold_interaction_model_components(),
        parameters=configuration.semantic_parameters(),
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development"
        ),
        clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v3",
        cost_contract=(
            "cost:fpmarkets_completed_bar_spread_proxy_point_0_01_causal_zero_repair_"
            "half_spread_stress_v3"
        ),
        engine_contract=(
            f"engine:fold_interaction_model_v1:python{'.'.join(str(v) for v in sys.version_info[:3])}:"
            f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
            f"chassis_{fold_interaction_model_chassis_implementation_sha256()}:"
            f"event_{event_label_implementation_sha256()}:"
            f"loader_{loader_implementation_sha256()}:"
            f"shared_{discovery_implementation_sha256()}:"
            f"bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:"
            f"bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}"
        ),
    )


def fold_interaction_model_baseline() -> ExecutableSpec:
    return fold_interaction_model_executable(fold_interaction_model_configurations()[0])


def executable_configuration_map() -> dict[str, FoldInteractionModelConfiguration]:
    return {
        fold_interaction_model_executable(value).identity: value
        for value in fold_interaction_model_configurations()
    }


def model_design(features: np.ndarray, profile: str) -> np.ndarray:
    if profile == "linear_ridge_control":
        return features
    if profile != "pairwise_interaction_ridge":
        raise ValueError("model profile is invalid")
    interactions = [
        features[:, left] * features[:, right]
        for left in range(features.shape[1])
        for right in range(left + 1, features.shape[1])
    ]
    return np.column_stack((features, *interactions))


def fit_model_profile(
    *,
    features: np.ndarray,
    label: np.ndarray,
    train_mask: np.ndarray,
    profile: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    return _fit_model(
        features=model_design(features, profile),
        label=label,
        train_mask=train_mask,
    )


__all__ = [
    "FoldInteractionModelConfiguration",
    "SELECTION_TOTAL_EXPOSURES",
    "executable_configuration_map",
    "fit_model_profile",
    "fold_interaction_model_baseline",
    "fold_interaction_model_chassis_implementation_sha256",
    "fold_interaction_model_components",
    "fold_interaction_model_configurations",
    "fold_interaction_model_executable",
    "loader_implementation_sha256",
    "model_design",
]
