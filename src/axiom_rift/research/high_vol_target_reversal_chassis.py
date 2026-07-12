"""High-volatility target-direction reversal recombination."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.session_dense_positive_sleeve_chassis import SELECTION_TOTAL_EXPOSURES as PRIOR_TOTAL_EXPOSURES, loader_implementation_sha256, session_dense_positive_sleeve_components, session_dense_positive_sleeve_configurations, session_dense_positive_sleeve_executable, simulate_session_dense_positive_sleeves


SELECTION_TOTAL_EXPOSURES = PRIOR_TOTAL_EXPOSURES + 4
_PROFILES = ("session_dense_control", "high_vol_target_reversal_subject")
_THIS_FILE = Path(__file__).resolve()


def high_vol_target_reversal_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class HighVolTargetReversalConfiguration:
    profile: str

    def __post_init__(self) -> None:
        if self.profile not in _PROFILES:
            raise ValueError("high-volatility target reversal profile invalid")

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
    def reverses_high_volatility(self) -> bool:
        return self.profile == "high_vol_target_reversal_subject"

    def semantic_parameters(self) -> dict[str, Any]:
        base = dict(session_dense_positive_sleeve_configurations()[1].semantic_parameters())
        base["portfolio_profile"] = self.profile
        base["target_high_volatility_role"] = "follow_control" if not self.reverses_high_volatility else "reverse_at_or_above_fold_train_second_tercile"
        return base


def high_vol_target_reversal_configurations() -> tuple[HighVolTargetReversalConfiguration, ...]:
    return tuple(HighVolTargetReversalConfiguration(value) for value in _PROFILES)


def _local(name: str) -> str:
    return f"axiom_rift.research.high_vol_target_reversal_chassis.{name}@sha256:{high_vol_target_reversal_chassis_implementation_sha256()}"


def high_vol_target_reversal_components() -> tuple[ComponentSpec, ...]:
    base = session_dense_positive_sleeve_components()
    role = ComponentSpec(
        display_name="fold-train high-volatility target-sleeve role router",
        protocol="portfolio.fold_train_high_volatility_target_role.v1",
        implementation=_local("simulate_high_vol_target_reversal"),
        spec={"cutoff": "fold_train_second_volatility_tercile_higher", "parameter_fields": ["target_high_volatility_role"], "policies": list(_PROFILES), "control": "follow", "subject": "reverse", "unchanged_roles": ["regime_router", "low_target_follow", "middle_target_follow"]},
        semantic_dependencies=(base[-1].identity,),
    )
    return (*base, role)


def high_vol_target_reversal_baseline() -> ExecutableSpec:
    return session_dense_positive_sleeve_executable(session_dense_positive_sleeve_configurations()[1])


def high_vol_target_reversal_executable(configuration: HighVolTargetReversalConfiguration) -> ExecutableSpec:
    if not configuration.reverses_high_volatility:
        return high_vol_target_reversal_baseline()
    baseline = high_vol_target_reversal_baseline()
    return ExecutableSpec(display_name="session-dense portfolio with high-volatility target reversal", components=high_vol_target_reversal_components(), parameters=configuration.semantic_parameters(), data_contract=baseline.data_contract, split_contract=baseline.split_contract, clock_contract=baseline.clock_contract, cost_contract=baseline.cost_contract, engine_contract=baseline.engine_contract)


def executable_configuration_map() -> dict[str, HighVolTargetReversalConfiguration]:
    return {high_vol_target_reversal_executable(value).identity: value for value in high_vol_target_reversal_configurations()}


def simulate_high_vol_target_reversal(*, frame: pd.DataFrame, score: np.ndarray, volatility: np.ndarray, run: np.ndarray, threshold: float, configuration: HighVolTargetReversalConfiguration, test_start: pd.Timestamp, test_end: pd.Timestamp, fold_id: str, regime_cutoffs: tuple[float, float], effective_spread: np.ndarray | None = None):
    values = np.asarray(score, float)
    if values.ndim != 2 or values.shape != (len(frame), 2):
        raise ValueError("high-volatility target reversal score matrix invalid")
    if configuration.reverses_high_volatility:
        values = values.copy()
        high = np.isfinite(volatility) & (np.asarray(volatility, float) >= regime_cutoffs[1])
        values[high, 1] *= -1.0
    return simulate_session_dense_positive_sleeves(frame=frame, score=values, volatility=volatility, run=run, threshold=threshold, configuration=session_dense_positive_sleeve_configurations()[1], test_start=test_start, test_end=test_end, fold_id=fold_id, regime_cutoffs=regime_cutoffs, effective_spread=effective_spread)


__all__ = ["SELECTION_TOTAL_EXPOSURES", "HighVolTargetReversalConfiguration", "executable_configuration_map", "high_vol_target_reversal_baseline", "high_vol_target_reversal_chassis_implementation_sha256", "high_vol_target_reversal_components", "high_vol_target_reversal_configurations", "high_vol_target_reversal_executable", "loader_implementation_sha256", "simulate_high_vol_target_reversal"]
