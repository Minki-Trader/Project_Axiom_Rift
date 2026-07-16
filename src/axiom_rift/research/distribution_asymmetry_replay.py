"""Prospective exact-family replay adapter for historical STU-0032.

The adapter reconstructs the original twelve distribution-asymmetry members
while keeping historical artifact addresses outside scientific Executable
semantics.  It contains no Mission, Initiative, or successor Study identity.
"""

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
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
    validate_controlled_executable,
)
from axiom_rift.research.completed_period_atomic_trace import (
    completed_period_proxy_execution_spec,
)
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    EXPECTED_FOLD_IDS,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    SELECTION_BLOCK_LENGTHS,
    SELECTION_BOOTSTRAP_SAMPLES,
    SELECTION_MONTE_CARLO_CONFIDENCE_PPM,
    SELECTION_SEED,
    DiscoveryBoundaryError,
    _consecutive_run,
    _time_ns,
    causal_effective_spread,
    discovery_implementation_sha256,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FixedHoldProtocolDefinition,
    fixed_hold_trace_implementation_sha256,
)
from axiom_rift.research.fixed_hold_trace_engine import (
    fixed_hold_trace_engine_implementation_sha256,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.historical_family_replay import (
    P1_HISTORICAL_FAMILY_CATALOG_DIGEST,
    STU0032_HISTORICAL_FAMILY,
    HistoricalMemberSpec,
)
from axiom_rift.research.scientific_trace import (
    DISTRIBUTION_ASYMMETRY_REPLAY_TRACE_PROTOCOL_ID,
)
from axiom_rift.research.selection_inference import (
    selection_inference_implementation_sha256,
)


DISTRIBUTION_ASYMMETRY_REPLAY_ALPHA_PPM = 100_000
DISTRIBUTION_ASYMMETRY_REPLAY_SELECTOR_QUANTILE_BP = 9_000
DISTRIBUTION_ASYMMETRY_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT = 356
DISTRIBUTION_ASYMMETRY_REPLAY_HISTORICAL_CONTEXT_ID = (
    "historical-replay-obligation:"
    "2fba53f243135ffb9836d1859f3ee11bbab99c9b6a5e6087ffdb2e122036994e"
)
DISTRIBUTION_ASYMMETRY_REPLAY_PROFILES = (
    "semivariance_96",
    "skew_192",
    "skew_96",
)
DISTRIBUTION_ASYMMETRY_REPLAY_HOLDING_BARS = (48, 96)
DISTRIBUTION_ASYMMETRY_REPLAY_COMPARISON_ANCHOR_PROFILE = (
    "comparison_anchor_none"
)
DISTRIBUTION_ASYMMETRY_REPLAY_CLOCK_CONTRACT = (
    "clock:fpmarkets_m5_bar_open_completed_plus_5m_v2"
)
DISTRIBUTION_ASYMMETRY_REPLAY_COST_CONTRACT = (
    "cost:fpmarkets_completed_bar_spread_proxy_point_0_01_causal_zero_repair_"
    "half_spread_stress_v2"
)
_THIS_FILE = Path(__file__).resolve()


def distribution_asymmetry_replay_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def distribution_asymmetry_replay_loader_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


def distribution_asymmetry_replay_producer_implementation_identities(
) -> dict[str, str]:
    return {
        "adapter_sha256": distribution_asymmetry_replay_implementation_sha256(),
        "catalog_sha256": P1_HISTORICAL_FAMILY_CATALOG_DIGEST,
        "discovery_sha256": discovery_implementation_sha256(),
        "loader_sha256": distribution_asymmetry_replay_loader_sha256(),
        "trace_engine_sha256": fixed_hold_trace_engine_implementation_sha256(),
    }


@dataclass(frozen=True, slots=True)
class DistributionAsymmetryReplayConfiguration:
    ordinal: int
    configuration_id: str
    historical_reference_executable_id: str
    profile: str
    signal_sign: int
    holding_bars: int
    selector_quantile_bp: int = (
        DISTRIBUTION_ASYMMETRY_REPLAY_SELECTOR_QUANTILE_BP
    )

    def __post_init__(self) -> None:
        if (
            type(self.ordinal) is not int
            or self.ordinal < 1
            or type(self.configuration_id) is not str
            or not self.configuration_id.isascii()
            or self.profile not in DISTRIBUTION_ASYMMETRY_REPLAY_PROFILES
            or self.signal_sign not in {-1, 1}
            or self.holding_bars
            not in DISTRIBUTION_ASYMMETRY_REPLAY_HOLDING_BARS
            or self.selector_quantile_bp
            != DISTRIBUTION_ASYMMETRY_REPLAY_SELECTOR_QUANTILE_BP
            or not self.historical_reference_executable_id.startswith(
                "executable:"
            )
        ):
            raise ValueError("distribution-asymmetry replay configuration invalid")

    def semantic_parameters(self) -> dict[str, object]:
        return {
            "configuration_id": self.configuration_id,
            "historical_reference_executable_id": (
                self.historical_reference_executable_id
            ),
            "holding_bars": self.holding_bars,
            "profile": self.profile,
            "selector_quantile_bp": self.selector_quantile_bp,
            "signal_sign": self.signal_sign,
        }


def _configuration_from_member(
    member: HistoricalMemberSpec,
) -> DistributionAsymmetryReplayConfiguration:
    parameters = member.parameter_values()
    return DistributionAsymmetryReplayConfiguration(
        ordinal=member.ordinal,
        configuration_id=member.configuration_id,
        historical_reference_executable_id=(
            member.historical_reference_executable_id
        ),
        profile=str(parameters["profile"]),
        signal_sign=int(parameters["signal_sign"]),
        holding_bars=int(parameters["holding_bars"]),
        selector_quantile_bp=int(parameters["selector_quantile_bp"]),
    )


def distribution_asymmetry_replay_configurations(
) -> tuple[DistributionAsymmetryReplayConfiguration, ...]:
    values = tuple(
        _configuration_from_member(member)
        for member in STU0032_HISTORICAL_FAMILY.members
    )
    if tuple(value.ordinal for value in values) != tuple(range(1, 13)):
        raise RuntimeError("STU-0032 distribution family order drifted")
    return values


def _local(name: str) -> str:
    return (
        "axiom_rift.research.distribution_asymmetry_replay."
        f"{name}@sha256:{distribution_asymmetry_replay_implementation_sha256()}"
    )


def _shared(name: str) -> str:
    return (
        f"axiom_rift.research.discovery.{name}@sha256:"
        f"{discovery_implementation_sha256()}"
    )


def distribution_asymmetry_replay_components() -> tuple[ComponentSpec, ...]:
    feature = ComponentSpec(
        display_name="causal distribution-asymmetry replay feature",
        protocol="feature.causal_distribution_asymmetry.replay.v1",
        implementation=_local("compute_distribution_asymmetry_replay_score"),
        spec={
            "availability": "completed_bar_only",
            "parameter_fields": ["profile"],
            "profiles": list(DISTRIBUTION_ASYMMETRY_REPLAY_PROFILES),
        },
    )
    label = ComponentSpec(
        display_name="realized fixed-hold after-cost replay label",
        protocol="label.realized_fixed_hold_native_net_pnl.replay.v1",
        implementation=_shared("_evaluate_configuration"),
        spec={
            "availability": "exit_bar_open_after_registered_holding_interval",
            "cost_basis": "native_entry_and_exit_execution_cost",
            "parameter_fields": ["holding_bars"],
            "target": "native_net_pnl_micropoints",
        },
    )
    model = ComponentSpec(
        display_name="registered distribution-asymmetry outcome hypothesis",
        protocol="model.deterministic_distribution_asymmetry.replay.v1",
        implementation=_local("compute_distribution_asymmetry_replay_score"),
        spec={
            "fit": "none",
            "label_role": "scientific_outcome_never_runtime_input",
            "score_role": "causal_completed_bar_distribution_state",
        },
        semantic_dependencies=(feature.identity, label.identity),
    )
    selector = ComponentSpec(
        display_name="fold isolated sparse replay selector",
        protocol="selector.fold_train_abs_quantile.replay.v1",
        implementation=_local("calibrate_distribution_asymmetry_replay_selector"),
        spec={
            "calibration_role": "train_is_only",
            "minimum_train_observations": 1_000,
            "parameter_fields": ["selector_quantile_bp"],
            "quantile_basis_points": (
                DISTRIBUTION_ASYMMETRY_REPLAY_SELECTOR_QUANTILE_BP
            ),
            "quantile_method": "higher",
        },
        semantic_dependencies=(model.identity,),
    )
    trade = ComponentSpec(
        display_name="completed-bar next-open directional replay entry",
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
        display_name="fixed-hold nonoverlap replay lifecycle",
        protocol="lifecycle.fixed_hold_no_overlap.replay.v2",
        implementation=_shared("simulate_fixed_hold"),
        spec={
            "entry_overlap": "reject_while_position_slot_is_occupied",
            "gap_action": "exclude_path",
            "parameter_fields": ["holding_bars"],
        },
        semantic_dependencies=(trade.identity,),
    )
    execution = ComponentSpec(
        display_name="completed-period spread-proxy replay execution",
        protocol="execution.fpmarkets_completed_period_spread_proxy.v2",
        implementation=_local("causal_distribution_asymmetry_replay_spread"),
        spec=completed_period_proxy_execution_spec(
            repair_policy=(
                "same_contiguous_segment_strict_prior_positive_288_bar_"
                "median_min_24_else_unknown"
            )
        ),
        semantic_dependencies=(lifecycle.identity,),
    )
    risk = ComponentSpec(
        display_name="fixed one-lot replay risk",
        protocol="risk.fixed_one_lot.v1",
        implementation=_shared("simulate_fixed_hold"),
        spec={"dynamic_sizing": False, "lot": 1, "positions_per_sleeve": 1},
        semantic_dependencies=(execution.identity,),
    )
    synthesis = ComponentSpec(
        display_name="registered STU-0032 replay member",
        protocol="synthesis.historical_fixed_hold_member.v2",
        implementation=_local("distribution_asymmetry_replay_executable"),
        spec={
            "catalog_digest": P1_HISTORICAL_FAMILY_CATALOG_DIGEST,
            "exact_member_count": 12,
            "historical_family_identity": STU0032_HISTORICAL_FAMILY.identity,
            "parameter_fields": [
                "configuration_id",
                "historical_reference_executable_id",
            ],
        },
        semantic_dependencies=(risk.identity,),
    )
    portfolio = ComponentSpec(
        display_name="exact concurrent STU-0032 replay inference",
        protocol="portfolio.concurrent_fixed_hold_family_inference.v2",
        implementation=(
            "axiom_rift.research.fixed_hold_family_trace."
            "build_fixed_hold_trace_calculation@sha256:"
            f"{fixed_hold_trace_implementation_sha256()}"
        ),
        spec={
            "historical_context_adjustment_authority": (
                "context_only_never_adjustment_factor"
            ),
            "parameter_fields": [
                "alpha_ppm",
                "base_seed",
                "block_lengths",
                "bootstrap_samples",
                "historical_context_prior_global_exposure_count",
                "monte_carlo_confidence_ppm",
            ],
            "selection_family_scope": "exact_registered_concurrent_family",
        },
        semantic_dependencies=(synthesis.identity,),
    )
    return (
        feature,
        label,
        model,
        selector,
        trade,
        lifecycle,
        execution,
        risk,
        synthesis,
        portfolio,
    )


def _shared_parameters(
    historical_context_prior_global_exposure_count: int,
) -> dict[str, object]:
    if (
        type(historical_context_prior_global_exposure_count) is not int
        or historical_context_prior_global_exposure_count
        < DISTRIBUTION_ASYMMETRY_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
    ):
        raise ValueError(
            "historical context cannot precede the original STU-0032 family"
        )
    return {
        "alpha_ppm": DISTRIBUTION_ASYMMETRY_REPLAY_ALPHA_PPM,
        "base_seed": SELECTION_SEED,
        "block_lengths": list(SELECTION_BLOCK_LENGTHS),
        "bootstrap_samples": SELECTION_BOOTSTRAP_SAMPLES,
        "historical_context_prior_global_exposure_count": (
            historical_context_prior_global_exposure_count
        ),
        "monte_carlo_confidence_ppm": SELECTION_MONTE_CARLO_CONFIDENCE_PPM,
    }


def _engine_contract() -> str:
    return (
        "engine:stu0032_distribution_asymmetry_replay_v1:"
        f"python{'.'.join(str(value) for value in sys.version_info[:3])}:"
        f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
        f"adapter_{distribution_asymmetry_replay_implementation_sha256()}:"
        f"trace_engine_{fixed_hold_trace_engine_implementation_sha256()}:"
        f"loader_{distribution_asymmetry_replay_loader_sha256()}:"
        f"shared_{discovery_implementation_sha256()}:"
        f"selection_{selection_inference_implementation_sha256()}:"
        f"catalog_{P1_HISTORICAL_FAMILY_CATALOG_DIGEST}"
    )


def distribution_asymmetry_replay_executable(
    configuration: DistributionAsymmetryReplayConfiguration,
    *,
    historical_context_prior_global_exposure_count: int,
) -> ExecutableSpec:
    if configuration not in distribution_asymmetry_replay_configurations():
        raise ValueError("configuration is outside the exact STU-0032 family")
    return ExecutableSpec(
        display_name=f"STU-0032 replay {configuration.configuration_id}",
        components=distribution_asymmetry_replay_components(),
        parameters={
            **configuration.semantic_parameters(),
            **_shared_parameters(
                historical_context_prior_global_exposure_count
            ),
        },
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:"
            "rolling_windows_9_observed_development"
        ),
        clock_contract=DISTRIBUTION_ASYMMETRY_REPLAY_CLOCK_CONTRACT,
        cost_contract=DISTRIBUTION_ASYMMETRY_REPLAY_COST_CONTRACT,
        engine_contract=_engine_contract(),
    )


def distribution_asymmetry_replay_baseline_executable(
    *,
    historical_context_prior_global_exposure_count: int,
) -> ExecutableSpec:
    return ExecutableSpec(
        display_name="STU-0032 non-evaluated comparison anchor",
        components=distribution_asymmetry_replay_components(),
        parameters={
            **_shared_parameters(
                historical_context_prior_global_exposure_count
            ),
            "configuration_id": "comparison-anchor",
            "historical_reference_executable_id": "none",
            "holding_bars": 0,
            "profile": DISTRIBUTION_ASYMMETRY_REPLAY_COMPARISON_ANCHOR_PROFILE,
            "selector_quantile_bp": (
                DISTRIBUTION_ASYMMETRY_REPLAY_SELECTOR_QUANTILE_BP
            ),
            "signal_sign": 0,
        },
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:"
            "rolling_windows_9_observed_development"
        ),
        clock_contract=DISTRIBUTION_ASYMMETRY_REPLAY_CLOCK_CONTRACT,
        cost_contract=DISTRIBUTION_ASYMMETRY_REPLAY_COST_CONTRACT,
        engine_contract=_engine_contract(),
    )


def distribution_asymmetry_replay_controlled_chassis(
    *,
    historical_context_prior_global_exposure_count: int,
) -> ControlledStudyChassis:
    baseline = distribution_asymmetry_replay_baseline_executable(
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        )
    )
    chassis = ControlledStudyChassis(
        baseline_executable=baseline,
        changed_domains=(
            ResearchLayer.FEATURE,
            ResearchLayer.LABEL,
            ResearchLayer.LIFECYCLE,
            ResearchLayer.SYNTHESIS,
            ResearchLayer.TRADE,
        ),
        controlled_domains=(
            ResearchLayer.EXECUTION,
            ResearchLayer.MODEL,
            ResearchLayer.PORTFOLIO,
            ResearchLayer.RISK,
            ResearchLayer.SELECTOR,
        ),
        architecture=ArchitectureChassisSpec.from_executable(baseline),
    )
    payload = chassis.to_identity_payload()
    for configuration in distribution_asymmetry_replay_configurations():
        validate_controlled_executable(
            payload,
            distribution_asymmetry_replay_executable(
                configuration,
                historical_context_prior_global_exposure_count=(
                    historical_context_prior_global_exposure_count
                ),
            ),
        )
    return chassis


def distribution_asymmetry_replay_executable_map(
    *,
    historical_context_prior_global_exposure_count: int,
) -> dict[str, DistributionAsymmetryReplayConfiguration]:
    return {
        distribution_asymmetry_replay_executable(
            configuration,
            historical_context_prior_global_exposure_count=(
                historical_context_prior_global_exposure_count
            ),
        ).identity: configuration
        for configuration in distribution_asymmetry_replay_configurations()
    }


def distribution_asymmetry_replay_protocol_definition(
    *,
    historical_context_prior_global_exposure_count: int,
) -> FixedHoldProtocolDefinition:
    configurations = distribution_asymmetry_replay_configurations()
    return FixedHoldProtocolDefinition(
        family=STU0032_HISTORICAL_FAMILY,
        prospective_executable_ids=tuple(
            distribution_asymmetry_replay_executable(
                configuration,
                historical_context_prior_global_exposure_count=(
                    historical_context_prior_global_exposure_count
                ),
            ).identity
            for configuration in configurations
        ),
        protocol_id=DISTRIBUTION_ASYMMETRY_REPLAY_TRACE_PROTOCOL_ID,
        fold_ids=EXPECTED_FOLD_IDS,
        invariance_keys=DISTRIBUTION_ASYMMETRY_REPLAY_PROFILES,
        allowed_regimes=("high", "low", "middle"),
        dataset_sha256=DATASET_SHA256,
        material_identity=OBSERVED_MATERIAL_ID,
        split_artifact_sha256=ROLLING_SPLIT_SHA256,
        clock_contract=DISTRIBUTION_ASYMMETRY_REPLAY_CLOCK_CONTRACT,
        cost_contract=DISTRIBUTION_ASYMMETRY_REPLAY_COST_CONTRACT,
        producer_implementation_identities=tuple(
            sorted(
                distribution_asymmetry_replay_producer_implementation_identities().items()
            )
        ),
        historical_context_id=(
            DISTRIBUTION_ASYMMETRY_REPLAY_HISTORICAL_CONTEXT_ID
        ),
        historical_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
        original_family_end_global_exposure_count=(
            DISTRIBUTION_ASYMMETRY_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
        ),
        alpha_ppm=DISTRIBUTION_ASYMMETRY_REPLAY_ALPHA_PPM,
        bootstrap_samples=SELECTION_BOOTSTRAP_SAMPLES,
        block_lengths=SELECTION_BLOCK_LENGTHS,
        monte_carlo_confidence_ppm=SELECTION_MONTE_CARLO_CONFIDENCE_PPM,
        base_seed=SELECTION_SEED,
    )


def compute_distribution_asymmetry_replay_score(
    frame: pd.DataFrame,
    profile: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if profile not in DISTRIBUTION_ASYMMETRY_REPLAY_PROFILES:
        raise ValueError("distribution-asymmetry replay profile is invalid")
    close = frame["close"].to_numpy(float)
    if np.any(~np.isfinite(close)) or np.any(close <= 0):
        raise ValueError("distribution-asymmetry replay close is invalid")
    returns = np.full(len(close), np.nan)
    returns[1:] = np.diff(np.log(close))
    series = pd.Series(returns)
    window = 192 if profile == "skew_192" else 96
    volatility = (
        series.rolling(window, min_periods=window)
        .std(ddof=1)
        .to_numpy(float)
    )
    if profile.startswith("skew_"):
        score = (
            series.rolling(window, min_periods=window)
            .skew()
            .to_numpy(float)
        )
    else:
        positive = (
            series.clip(lower=0)
            .pow(2)
            .rolling(window, min_periods=window)
            .mean()
        )
        negative = (
            (-series.clip(upper=0))
            .pow(2)
            .rolling(window, min_periods=window)
            .mean()
        )
        denominator = positive + negative
        score = (
            (positive - negative) / denominator.where(denominator > 0)
        ).to_numpy(float)
    run = _consecutive_run(_time_ns(frame))
    score[run < window + 1] = np.nan
    return score, volatility, run


def calibrate_distribution_asymmetry_replay_selector(
    score: np.ndarray,
    mask: np.ndarray,
) -> float:
    values = np.abs(score[mask & np.isfinite(score)])
    if len(values) < 1_000:
        raise DiscoveryBoundaryError(
            "distribution-asymmetry selector calibration is too small"
        )
    return float(
        np.quantile(
            values,
            DISTRIBUTION_ASYMMETRY_REPLAY_SELECTOR_QUANTILE_BP / 10_000,
            method="higher",
        )
    )


def causal_distribution_asymmetry_replay_spread(
    spread: np.ndarray,
    time_ns: np.ndarray,
) -> np.ndarray:
    return causal_effective_spread(spread, time_ns)


__all__ = [
    "DISTRIBUTION_ASYMMETRY_REPLAY_HISTORICAL_CONTEXT_ID",
    "DISTRIBUTION_ASYMMETRY_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT",
    "DISTRIBUTION_ASYMMETRY_REPLAY_PROFILES",
    "DistributionAsymmetryReplayConfiguration",
    "calibrate_distribution_asymmetry_replay_selector",
    "causal_distribution_asymmetry_replay_spread",
    "compute_distribution_asymmetry_replay_score",
    "distribution_asymmetry_replay_configurations",
    "distribution_asymmetry_replay_controlled_chassis",
    "distribution_asymmetry_replay_executable",
    "distribution_asymmetry_replay_executable_map",
    "distribution_asymmetry_replay_implementation_sha256",
    "distribution_asymmetry_replay_loader_sha256",
    "distribution_asymmetry_replay_producer_implementation_identities",
    "distribution_asymmetry_replay_protocol_definition",
]
