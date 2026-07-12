"""Exact low-volatility abstention ablation for the session-dense portfolio."""

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
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256, SELECTION_BOOTSTRAP_SAMPLES, SELECTION_SEED, SimulationResult, discovery_implementation_sha256
from axiom_rift.research.session_dense_positive_sleeve_chassis import SELECTION_TOTAL_EXPOSURES as PRIOR_TOTAL_EXPOSURES, loader_implementation_sha256, session_dense_positive_sleeve_components, session_dense_positive_sleeve_configurations, session_dense_positive_sleeve_executable, simulate_session_dense_positive_sleeves


SELECTION_TOTAL_EXPOSURES = PRIOR_TOTAL_EXPOSURES + 2
_PROFILES = ("session_dense_control", "low_vol_abstention_subject")
_THIS_FILE = Path(__file__).resolve()


def low_vol_abstention_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class LowVolAbstentionConfiguration:
    profile: str

    def __post_init__(self) -> None:
        if self.profile not in _PROFILES:
            raise ValueError("low-volatility abstention profile invalid")

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
    def abstains_low_volatility(self) -> bool:
        return self.profile == "low_vol_abstention_subject"

    @property
    def target_quantile_bp(self) -> int:
        return 9000

    def semantic_parameters(self) -> dict[str, Any]:
        base = dict(session_dense_positive_sleeve_configurations()[1].semantic_parameters())
        base["low_volatility_policy"] = "all_regimes_control" if not self.abstains_low_volatility else "abstain_at_or_below_fold_train_first_tercile"
        base["portfolio_profile"] = self.profile
        return base


def low_vol_abstention_configurations() -> tuple[LowVolAbstentionConfiguration, ...]:
    return tuple(LowVolAbstentionConfiguration(value) for value in _PROFILES)


def _local(name: str) -> str:
    return f"axiom_rift.research.low_vol_abstention_chassis.{name}@sha256:{low_vol_abstention_chassis_implementation_sha256()}"


def low_vol_abstention_components() -> tuple[ComponentSpec, ...]:
    base = session_dense_positive_sleeve_components()
    gate = ComponentSpec(
        display_name="fold-train low-volatility full-portfolio abstention",
        protocol="risk.fold_train_low_volatility_abstention.v1",
        implementation=_local("simulate_low_vol_abstention"),
        spec={"cutoff": "fold_train_first_volatility_tercile_higher", "parameter_fields": ["low_volatility_policy"], "policies": list(_PROFILES), "applies_to": ["regime_router", "target_direction"]},
        semantic_dependencies=(base[-1].identity,),
    )
    return (*base, gate)


def low_vol_abstention_baseline() -> ExecutableSpec:
    return session_dense_positive_sleeve_executable(session_dense_positive_sleeve_configurations()[1])


def low_vol_abstention_executable(configuration: LowVolAbstentionConfiguration) -> ExecutableSpec:
    if not configuration.abstains_low_volatility:
        return low_vol_abstention_baseline()
    return ExecutableSpec(
        display_name="session-dense portfolio with low-volatility abstention",
        components=low_vol_abstention_components(),
        parameters=configuration.semantic_parameters(),
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development",
        clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v6",
        cost_contract="cost:bid_bar_spread_point_0_01_causal_zero_repair_half_spread_stress_v6",
        engine_contract=low_vol_abstention_baseline().engine_contract,
    )


def executable_configuration_map() -> dict[str, LowVolAbstentionConfiguration]:
    return {low_vol_abstention_executable(value).identity: value for value in low_vol_abstention_configurations()}


def simulate_low_vol_abstention(*, frame: pd.DataFrame, score: np.ndarray, volatility: np.ndarray, run: np.ndarray, threshold: float, configuration: LowVolAbstentionConfiguration, test_start: pd.Timestamp, test_end: pd.Timestamp, fold_id: str, regime_cutoffs: tuple[float, float], effective_spread: np.ndarray | None = None) -> SimulationResult:
    values = np.asarray(score, float)
    if values.ndim != 2 or values.shape != (len(frame), 2):
        raise ValueError("low-volatility abstention score matrix invalid")
    if configuration.abstains_low_volatility:
        values = values.copy()
        values[np.isfinite(volatility) & (np.asarray(volatility, float) <= regime_cutoffs[0]), :] = np.nan
    return simulate_session_dense_positive_sleeves(frame=frame, score=values, volatility=volatility, run=run, threshold=threshold, configuration=session_dense_positive_sleeve_configurations()[1], test_start=test_start, test_end=test_end, fold_id=fold_id, regime_cutoffs=regime_cutoffs, effective_spread=effective_spread)


__all__ = ["SELECTION_TOTAL_EXPOSURES", "LowVolAbstentionConfiguration", "executable_configuration_map", "low_vol_abstention_baseline", "low_vol_abstention_chassis_implementation_sha256", "low_vol_abstention_components", "low_vol_abstention_configurations", "low_vol_abstention_executable", "simulate_low_vol_abstention"]
