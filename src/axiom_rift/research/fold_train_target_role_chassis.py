"""Fold-train selector for the high-volatility target-sleeve role."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.high_vol_target_reversal_chassis import SELECTION_TOTAL_EXPOSURES as PRIOR_TOTAL_EXPOSURES, high_vol_target_reversal_components, high_vol_target_reversal_configurations, high_vol_target_reversal_executable, simulate_high_vol_target_reversal
from axiom_rift.research.session_dense_positive_sleeve_chassis import loader_implementation_sha256, session_dense_positive_sleeve_configurations, simulate_session_dense_positive_sleeves


SELECTION_TOTAL_EXPOSURES = PRIOR_TOTAL_EXPOSURES + 2
_PROFILES = ("fixed_high_reverse_control", "fold_train_high_role_subject")
_THIS_FILE = Path(__file__).resolve()


def fold_train_target_role_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class FoldTrainTargetRoleConfiguration:
    profile: str

    def __post_init__(self) -> None:
        if self.profile not in _PROFILES:
            raise ValueError("fold-train target-role profile invalid")

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
    def adaptive(self) -> bool:
        return self.profile == "fold_train_high_role_subject"

    def semantic_parameters(self) -> dict[str, Any]:
        base = dict(high_vol_target_reversal_configurations()[1].semantic_parameters())
        base["portfolio_profile"] = self.profile
        base["target_high_volatility_role"] = "fixed_reverse_control" if not self.adaptive else "fold_train_native_net_best_of_follow_or_reverse"
        return base


def fold_train_target_role_configurations() -> tuple[FoldTrainTargetRoleConfiguration, ...]:
    return tuple(FoldTrainTargetRoleConfiguration(value) for value in _PROFILES)


def _local(name: str) -> str:
    return f"axiom_rift.research.fold_train_target_role_chassis.{name}@sha256:{fold_train_target_role_chassis_implementation_sha256()}"


def fold_train_target_role_components() -> tuple[ComponentSpec, ...]:
    base = high_vol_target_reversal_components()
    selector = ComponentSpec(display_name="fold-train high-volatility target-role selector", protocol="portfolio.fold_train_high_target_role_selector.v1", implementation=_local("simulate_fold_train_target_role"), spec={"candidate_roles": ["follow", "reverse"], "fit_metric": "native_net_profit", "fit_scope": "fold_train_high_volatility_target_slot_only", "parameter_fields": ["target_high_volatility_role"], "profiles": list(_PROFILES)}, semantic_dependencies=(base[-1].identity,))
    return (*base, selector)


def fold_train_target_role_baseline() -> ExecutableSpec:
    return high_vol_target_reversal_executable(high_vol_target_reversal_configurations()[1])


def fold_train_target_role_executable(configuration: FoldTrainTargetRoleConfiguration) -> ExecutableSpec:
    if not configuration.adaptive:
        return fold_train_target_role_baseline()
    baseline = fold_train_target_role_baseline()
    return ExecutableSpec(display_name="fold-train selected high-volatility target role", components=fold_train_target_role_components(), parameters=configuration.semantic_parameters(), data_contract=baseline.data_contract, split_contract=baseline.split_contract, clock_contract=baseline.clock_contract, cost_contract=baseline.cost_contract, engine_contract=baseline.engine_contract)


def executable_configuration_map() -> dict[str, FoldTrainTargetRoleConfiguration]:
    return {fold_train_target_role_executable(value).identity: value for value in fold_train_target_role_configurations()}


def simulate_fold_train_target_role(*, frame: pd.DataFrame, score: np.ndarray, volatility: np.ndarray, run: np.ndarray, threshold: float, configuration: FoldTrainTargetRoleConfiguration, test_start: pd.Timestamp, test_end: pd.Timestamp, fold_id: str, regime_cutoffs: tuple[float, float], effective_spread: np.ndarray | None = None):
    if configuration.adaptive:
        return simulate_session_dense_positive_sleeves(frame=frame, score=score, volatility=volatility, run=run, threshold=threshold, configuration=session_dense_positive_sleeve_configurations()[1], test_start=test_start, test_end=test_end, fold_id=fold_id, regime_cutoffs=regime_cutoffs, effective_spread=effective_spread)
    return simulate_high_vol_target_reversal(frame=frame, score=score, volatility=volatility, run=run, threshold=threshold, configuration=high_vol_target_reversal_configurations()[1], test_start=test_start, test_end=test_end, fold_id=fold_id, regime_cutoffs=regime_cutoffs, effective_spread=effective_spread)


__all__ = ["SELECTION_TOTAL_EXPOSURES", "FoldTrainTargetRoleConfiguration", "executable_configuration_map", "fold_train_target_role_baseline", "fold_train_target_role_chassis_implementation_sha256", "fold_train_target_role_components", "fold_train_target_role_configurations", "fold_train_target_role_executable", "loader_implementation_sha256", "simulate_fold_train_target_role"]
