"""US500 systemic-versus-idiosyncratic routing over a fixed reversal frontier."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.fold_train_target_role_chassis import (
    SELECTION_TOTAL_EXPOSURES as PRIOR_TOTAL_EXPOSURES,
)
from axiom_rift.research.external_observed_development import (
    US500_OBSERVED_DEVELOPMENT_SPEC,
    external_observed_development_loader_implementation_sha256,
)
from axiom_rift.research.high_vol_target_reversal_chassis import (
    high_vol_target_reversal_configurations,
    high_vol_target_reversal_executable,
)
from axiom_rift.research.session_dense_positive_sleeve_chassis import (
    session_dense_positive_sleeve_configurations,
    simulate_session_dense_positive_sleeves,
)
from axiom_rift.research.us500_source import (
    US500_HISTORICAL_SNAPSHOT_SHA256,
    us500_source_contract,
)


SELECTION_TOTAL_EXPOSURES = PRIOR_TOTAL_EXPOSURES + 2
US500_RAW_SHA256 = US500_HISTORICAL_SNAPSHOT_SHA256
_PROFILES = ("fixed_high_reversal_control", "us500_sign_coherence_subject")
_THIS_FILE = Path(__file__).resolve()


def us500_market_coherence_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def frontier_executable() -> ExecutableSpec:
    return high_vol_target_reversal_executable(
        high_vol_target_reversal_configurations()[1]
    )


@dataclass(frozen=True, slots=True)
class US500MarketCoherenceConfiguration:
    profile: str

    def __post_init__(self) -> None:
        if self.profile not in _PROFILES:
            raise ValueError("US500 market coherence profile is invalid")

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
    def uses_market_coherence(self) -> bool:
        return self.profile == "us500_sign_coherence_subject"

    def semantic_parameters(self) -> dict[str, Any]:
        values = dict(frontier_executable().parameter_values())
        values["market_coherence_policy"] = (
            "fixed_high_reversal_control"
            if not self.uses_market_coherence
            else "follow_when_us100_us500_signs_agree_reverse_when_they_disagree"
        )
        return values


def us500_market_coherence_configurations() -> tuple[US500MarketCoherenceConfiguration, ...]:
    return tuple(US500MarketCoherenceConfiguration(profile) for profile in _PROFILES)


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.us500_market_coherence_chassis.{name}@sha256:"
        f"{us500_market_coherence_chassis_implementation_sha256()}"
    )


def us500_market_coherence_components() -> tuple[ComponentSpec, ...]:
    frontier = frontier_executable()
    contract = us500_source_contract()
    target_feature = next(
        component
        for component in frontier.components
        if component.protocol == "feature.us100_direction_12_sigma48.v2"
    )
    source = ComponentSpec(
        display_name="exact FPMarkets US500 completed M5 broad-market input",
        protocol="external_source.fpmarkets_us500_m5.v2",
        implementation=_local("simulate_us500_market_coherence"),
        spec={
            "raw_sha256": US500_RAW_SHA256,
            "raw_sha256_role": "acquisition_identity_only",
            "development_prefix_sha256": (
                US500_OBSERVED_DEVELOPMENT_SPEC.prefix_sha256
            ),
            "development_prefix_byte_count": (
                US500_OBSERVED_DEVELOPMENT_SPEC.prefix_byte_count
            ),
            "development_prefix_row_count": (
                US500_OBSERVED_DEVELOPMENT_SPEC.row_count
            ),
            "development_material_identity": (
                US500_OBSERVED_DEVELOPMENT_SPEC.material_identity
            ),
            "development_source_key": "US500",
            "development_loader_implementation_sha256": (
                external_observed_development_loader_implementation_sha256()
            ),
            "source_contract_id": contract.source_contract_id,
            "mapping_identity": contract.mapping_identity,
            "schema_identity": contract.schema_identity,
            "field_identity": contract.field_identity,
            "clock_identity": contract.clock_identity,
            "availability_identity": contract.availability_identity,
            "join": "exact_timestamp_no_fill_no_asof_no_offset_inference",
            "dependent_sleeve_missing_action": "fail_closed",
        },
        semantic_dependencies=(
            contract.source_contract_id,
            f"external-development-material:{US500_OBSERVED_DEVELOPMENT_SPEC.material_identity}",
        ),
    )
    regime = ComponentSpec(
        display_name="fixed US100-US500 sign coherence state",
        protocol="regime.us500_us100_completed_12bar_sign_coherence.v1",
        implementation=_local("simulate_us500_market_coherence"),
        spec={
            "source_horizon_bars": 12,
            "systemic_state": "nonzero_US100_and_US500_signs_agree",
            "idiosyncratic_state": "nonzero_US100_and_US500_signs_disagree",
            "missing_or_zero_state": "dependent_high_target_sleeve_fail_closed",
            "fit": "none",
            "thresholds": "none",
        },
        semantic_dependencies=(source.identity, target_feature.identity),
    )
    frontier_execution = next(
        component
        for component in frontier.components
        if component.protocol.startswith("execution.")
    )
    engine_binding = ComponentSpec(
        display_name="content-bound US500 coherence chassis engine",
        protocol="execution.chassis_artifact_binding.v1",
        implementation=_local("simulate_us500_market_coherence"),
        spec={
            "artifact_sha256": (
                us500_market_coherence_chassis_implementation_sha256()
            ),
            "baseline_execution_semantics": "preserved",
            "identity_policy": "any_artifact_byte_change_creates_new_identity",
        },
        semantic_dependencies=(frontier_execution.identity,),
    )
    portfolio = ComponentSpec(
        display_name="US500 coherence high-target role router",
        protocol="portfolio.us500_market_coherence_high_target_role.v1",
        implementation=_local("simulate_us500_market_coherence"),
        spec={
            "parameter_fields": ["market_coherence_policy"],
            "systemic_high_target_role": "follow",
            "idiosyncratic_high_target_role": "reverse",
            "low_and_middle_target_roles": "unchanged_follow",
            "existing_regime_router": "unchanged",
            "activity_quota": False,
        },
        semantic_dependencies=(
            frontier.components[-1].identity,
            regime.identity,
            engine_binding.identity,
        ),
    )
    return (*frontier.components, source, regime, engine_binding, portfolio)


def us500_market_coherence_executable(
    configuration: US500MarketCoherenceConfiguration,
) -> ExecutableSpec:
    if not configuration.uses_market_coherence:
        return frontier_executable()
    baseline = frontier_executable()
    implementation = us500_market_coherence_chassis_implementation_sha256()
    return ExecutableSpec(
        display_name="fixed reversal frontier with US500 sign-coherence role routing",
        components=us500_market_coherence_components(),
        parameters=configuration.semantic_parameters(),
        data_contract=baseline.data_contract,
        split_contract=baseline.split_contract,
        clock_contract=baseline.clock_contract,
        cost_contract=baseline.cost_contract,
        engine_contract=(
            f"{baseline.engine_contract}:"
            f"us500_market_coherence_chassis_sha256_{implementation}:"
            "external_development_material_"
            f"{US500_OBSERVED_DEVELOPMENT_SPEC.material_identity}:"
            "external_development_prefix_"
            f"{US500_OBSERVED_DEVELOPMENT_SPEC.prefix_sha256}:"
            "external_development_loader_"
            f"{external_observed_development_loader_implementation_sha256()}"
        ),
        source_contracts=(us500_source_contract().source_contract_id,),
    )


def executable_configuration_map() -> dict[str, US500MarketCoherenceConfiguration]:
    return {
        us500_market_coherence_executable(configuration).identity: configuration
        for configuration in us500_market_coherence_configurations()
    }


def _route_scores(
    values: np.ndarray,
    volatility: np.ndarray,
    regime_cutoffs: tuple[float, float],
    *,
    uses_market_coherence: bool,
) -> np.ndarray:
    routed = np.asarray(values[:, :2], dtype=float).copy()
    high = np.isfinite(volatility) & (
        np.asarray(volatility, dtype=float) >= regime_cutoffs[1]
    )
    if uses_market_coherence:
        source = values[:, 2]
        available = np.isfinite(source) & (source != 0.0)
        target = routed[:, 1]
        coherent = available & (np.sign(target) == np.sign(source))
        routed[high & available & ~coherent, 1] *= -1.0
        routed[high & ~available, 1] = 0.0
    else:
        routed[high, 1] *= -1.0
    return routed


def simulate_us500_market_coherence(
    *,
    frame: pd.DataFrame,
    score: np.ndarray,
    volatility: np.ndarray,
    run: np.ndarray,
    threshold: float,
    configuration: US500MarketCoherenceConfiguration,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    fold_id: str,
    regime_cutoffs: tuple[float, float],
    effective_spread: np.ndarray | None = None,
):
    values = np.asarray(score, dtype=float)
    if values.ndim != 2 or values.shape != (len(frame), 3):
        raise ValueError("US500 market coherence score matrix is invalid")
    routed = _route_scores(
        values,
        volatility,
        regime_cutoffs,
        uses_market_coherence=configuration.uses_market_coherence,
    )
    return simulate_session_dense_positive_sleeves(
        frame=frame,
        score=routed,
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
    "SELECTION_TOTAL_EXPOSURES",
    "US500MarketCoherenceConfiguration",
    "US500_RAW_SHA256",
    "_route_scores",
    "executable_configuration_map",
    "frontier_executable",
    "simulate_us500_market_coherence",
    "us500_market_coherence_chassis_implementation_sha256",
    "us500_market_coherence_components",
    "us500_market_coherence_configurations",
    "us500_market_coherence_executable",
]
