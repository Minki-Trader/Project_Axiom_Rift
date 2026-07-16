"""Fixed-clock control versus volatility-clock event-label chassis."""

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
    _labels as fixed_event_labels,
    event_label_implementation_sha256,
)


SELECTION_TOTAL_EXPOSURES = 532
SELECTOR_QUANTILE_BP = 8_500
VOLATILITY_BUDGET_BARS = 12
_PROFILES = ("fixed_first_passage_control_48", "volatility_clock_terminal_12_of_48")
_THIS_FILE = Path(__file__).resolve()


def volatility_clock_label_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def loader_implementation_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class VolatilityClockLabelConfiguration:
    profile: str
    signal_sign: int = 1
    holding_bars: int = HORIZON

    def __post_init__(self) -> None:
        if (
            self.profile not in _PROFILES
            or self.signal_sign != 1
            or self.holding_bars != HORIZON
        ):
            raise ValueError("volatility-clock label configuration invalid")

    @property
    def configuration_id(self) -> str:
        return f"{self.profile}-direct-h{HORIZON}"

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "barrier_multiple_milli": BARRIER_MULTIPLE_MILLI,
            "holding_bars": HORIZON,
            "label_profile": self.profile,
            "ridge_penalty_milli": RIDGE_PENALTY_MILLI,
            "selector_quantile_bp": SELECTOR_QUANTILE_BP,
            "signal_sign": self.signal_sign,
            "volatility_budget_bars": VOLATILITY_BUDGET_BARS,
        }


def volatility_clock_label_configurations(
) -> tuple[VolatilityClockLabelConfiguration, ...]:
    return tuple(VolatilityClockLabelConfiguration(profile=value) for value in _PROFILES)


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.volatility_clock_label_chassis.{name}"
        f"@sha256:{volatility_clock_label_chassis_implementation_sha256()}"
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


def volatility_clock_label_components() -> tuple[ComponentSpec, ...]:
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
        display_name="fixed first-passage or volatility-clock terminal label",
        protocol="label.fixed_first_passage_vs_volatility_clock.v1",
        implementation=_local("build_labels"),
        spec={
            "fixed_control_horizon_bars": HORIZON,
            "future_end_must_be_inside_train": True,
            "maximum_horizon_bars": HORIZON,
            "parameter_fields": ["label_profile"],
            "profiles": list(_PROFILES),
            "volatility_budget_bars": VOLATILITY_BUDGET_BARS,
        },
    )
    model = ComponentSpec(
        display_name="fixed fold-trained ridge score",
        protocol="model.fold_train_ridge_linear.v1",
        implementation=_event("fit_fold_model"),
        spec={
            "fit_role": "train_is_only",
            "penalty_milli": RIDGE_PENALTY_MILLI,
            "standardization": "train_mean_population_std",
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


def volatility_clock_label_executable(
    configuration: VolatilityClockLabelConfiguration,
) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=f"volatility clock label {configuration.configuration_id}",
        components=volatility_clock_label_components(),
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
            f"engine:volatility_clock_label_v1:python{'.'.join(str(v) for v in sys.version_info[:3])}:"
            f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
            f"chassis_{volatility_clock_label_chassis_implementation_sha256()}:"
            f"event_{event_label_implementation_sha256()}:"
            f"loader_{loader_implementation_sha256()}:"
            f"shared_{discovery_implementation_sha256()}:"
            f"bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:"
            f"bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}"
        ),
    )


def volatility_clock_label_baseline() -> ExecutableSpec:
    return volatility_clock_label_executable(volatility_clock_label_configurations()[0])


def executable_configuration_map() -> dict[str, VolatilityClockLabelConfiguration]:
    return {
        volatility_clock_label_executable(value).identity: value
        for value in volatility_clock_label_configurations()
    }


def build_labels(
    frame: pd.DataFrame,
    volatility: np.ndarray,
    run: np.ndarray,
) -> dict[str, np.ndarray]:
    fixed = fixed_event_labels(frame, volatility, run)["first_passage_label_48"]
    count = len(frame)
    adaptive = np.full(count, np.nan)
    last = count - HORIZON - 1
    if last <= 0:
        return {
            "fixed_first_passage_control_48": fixed,
            "volatility_clock_terminal_12_of_48": adaptive,
        }
    indices = np.arange(last)
    continuous = run[indices + HORIZON + 1] >= HORIZON + 2
    finite = continuous & np.isfinite(volatility[indices]) & (volatility[indices] > 0)
    log_open = np.log(frame["open"].to_numpy(float))
    entry = log_open[indices + 1]
    budget = volatility[indices] ** 2 * VOLATILITY_BUDGET_BARS
    accumulated = np.zeros(last, dtype=float)
    selected_step = np.full(last, HORIZON + 1, dtype=np.int64)
    reached = np.zeros(last, dtype=bool)
    for step in range(2, HORIZON + 2):
        increment = log_open[indices + step] - log_open[indices + step - 1]
        accumulated += increment * increment
        newly_reached = (~reached) & (accumulated >= budget)
        selected_step[newly_reached] = step
        reached |= newly_reached
    terminal = log_open[indices + selected_step] - entry
    adaptive[indices[finite]] = np.sign(terminal[finite])
    return {
        "fixed_first_passage_control_48": fixed,
        "volatility_clock_terminal_12_of_48": adaptive,
    }


def fit_label_model(
    *,
    features: np.ndarray,
    label: np.ndarray,
    train_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    return _fit_model(features=features, label=label, train_mask=train_mask)


__all__ = [
    "SELECTION_TOTAL_EXPOSURES",
    "VOLATILITY_BUDGET_BARS",
    "VolatilityClockLabelConfiguration",
    "build_labels",
    "executable_configuration_map",
    "fit_label_model",
    "loader_implementation_sha256",
    "volatility_clock_label_baseline",
    "volatility_clock_label_chassis_implementation_sha256",
    "volatility_clock_label_components",
    "volatility_clock_label_configurations",
    "volatility_clock_label_executable",
]
