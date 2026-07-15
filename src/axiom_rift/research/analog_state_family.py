"""Typed analog-state families and their shared fold-trained algorithm.

The historical four-member family and the later path-geometry family differ in
their horizon, neighbour count, stride, and feature protocol.  They do not
need two implementations of nearest-neighbour training.  This module keeps
those choices in immutable family specifications and dispatches only the
small, closed set of repository-owned feature protocols.
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
from scipy.spatial import cKDTree

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research import data as data_module
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
    validate_controlled_executable,
)
from axiom_rift.research.discovery import (
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    DiscoveryBoundaryError,
    _consecutive_run,
    _time_ns,
    discovery_implementation_sha256,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.selection_inference import (
    selection_inference_implementation_sha256,
)


ANALOG_FAMILY_BOOTSTRAP_SAMPLES = 1_999
ANALOG_FAMILY_BLOCK_LENGTHS = (5, 10, 20)
ANALOG_FAMILY_BASE_SEED = 61_240_025
ANALOG_FAMILY_ALPHA_PPM = 100_000
ANALOG_FAMILY_MONTE_CARLO_CONFIDENCE_PPM = 990_000

MULTISCALE_STATE_FEATURE_PROTOCOL = "multiscale_state.v1"
RETURN_ONLY_FEATURE_PROTOCOL = "return_only.v1"
PATH_GEOMETRY_FEATURE_PROTOCOL = "path_geometry.v1"
RETURN_MAGNITUDE_FEATURE_PROTOCOL = "return_magnitude.v1"
_FEATURE_PROTOCOLS = frozenset(
    {
        MULTISCALE_STATE_FEATURE_PROTOCOL,
        RETURN_ONLY_FEATURE_PROTOCOL,
        PATH_GEOMETRY_FEATURE_PROTOCOL,
        RETURN_MAGNITUDE_FEATURE_PROTOCOL,
    }
)
_THIS_FILE = Path(__file__).resolve()
ANALOG_FAMILY_COMPARISON_ANCHOR_PROFILE = (
    "non_evaluated_family_comparison_anchor"
)
ANALOG_FAMILY_COMPARISON_ANCHOR_CONFIGURATION = (
    "non_evaluated-family-comparison-anchor"
)


def analog_family_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _identity(name: str, value: object, prefix: str) -> str:
    if type(value) is not str or not value.startswith(f"{prefix}:"):
        raise ValueError(f"{name} must be a {prefix} identity")
    digest = value.removeprefix(f"{prefix}:")
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError(f"{name} must contain a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class AnalogProfileSpec:
    profile_id: str
    feature_protocol: str
    positive_historical_reference_executable_id: str | None = None
    negative_historical_reference_executable_id: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.profile_id) is not str
            or not self.profile_id
            or not self.profile_id.isascii()
            or self.feature_protocol not in _FEATURE_PROTOCOLS
        ):
            raise ValueError("analog profile specification is invalid")
        references = (
            self.positive_historical_reference_executable_id,
            self.negative_historical_reference_executable_id,
        )
        if (references[0] is None) != (references[1] is None):
            raise ValueError("analog profile historical references are incomplete")
        for reference in references:
            if reference is not None:
                _identity("historical reference", reference, "executable")

    def historical_reference(self, signal_sign: int) -> str | None:
        if signal_sign == 1:
            return self.positive_historical_reference_executable_id
        if signal_sign == -1:
            return self.negative_historical_reference_executable_id
        raise ValueError("analog signal sign must be -1 or 1")

    def manifest(self) -> dict[str, object]:
        return {
            "feature_protocol": self.feature_protocol,
            "negative_historical_reference_executable_id": (
                self.negative_historical_reference_executable_id
            ),
            "positive_historical_reference_executable_id": (
                self.positive_historical_reference_executable_id
            ),
            "profile_id": self.profile_id,
        }


@dataclass(frozen=True, slots=True)
class AnalogFamilySpec:
    family_id: str
    horizon: int
    neighbors: int
    library_stride: int
    selector_quantile_bp: int
    profiles: tuple[AnalogProfileSpec, AnalogProfileSpec]

    def __post_init__(self) -> None:
        if type(self.family_id) is not str or not self.family_id.isascii():
            raise ValueError("analog family_id must be ASCII")
        if any(
            type(value) is not int or value < 1
            for value in (self.horizon, self.neighbors, self.library_stride)
        ):
            raise ValueError("analog family integer parameters are invalid")
        if not 0 < self.selector_quantile_bp < 10_000:
            raise ValueError("analog selector quantile is invalid")
        if (
            type(self.profiles) is not tuple
            or len(self.profiles) != 2
            or any(not isinstance(item, AnalogProfileSpec) for item in self.profiles)
        ):
            raise ValueError("analog family requires two typed profiles")
        profile_ids = tuple(item.profile_id for item in self.profiles)
        if profile_ids != tuple(sorted(set(profile_ids))):
            raise ValueError("analog profiles must be sorted and unique")
        references = tuple(
            profile.historical_reference(sign)
            for profile in self.profiles
            for sign in (1, -1)
        )
        if any(value is not None for value in references) and any(
            value is None for value in references
        ):
            raise ValueError("historical replay family references are incomplete")

    def profile(self, profile_id: str) -> AnalogProfileSpec:
        for profile in self.profiles:
            if profile.profile_id == profile_id:
                return profile
        raise KeyError(profile_id)

    def configurations(self) -> tuple["AnalogFamilyConfiguration", ...]:
        return tuple(
            AnalogFamilyConfiguration(
                family=self,
                profile_id=profile.profile_id,
                signal_sign=sign,
            )
            for profile in self.profiles
            for sign in (1, -1)
        )

    def manifest(self) -> dict[str, object]:
        return {
            "family_id": self.family_id,
            "horizon": self.horizon,
            "library_stride": self.library_stride,
            "neighbors": self.neighbors,
            "profiles": [item.manifest() for item in self.profiles],
            "selector_quantile_bp": self.selector_quantile_bp,
        }


@dataclass(frozen=True, slots=True)
class AnalogFamilyConfiguration:
    family: AnalogFamilySpec
    profile_id: str
    signal_sign: int

    def __post_init__(self) -> None:
        if self.signal_sign not in {-1, 1}:
            raise ValueError("analog signal sign must be -1 or 1")
        self.family.profile(self.profile_id)

    @property
    def holding_bars(self) -> int:
        return self.family.horizon

    @property
    def configuration_id(self) -> str:
        direction = "analog" if self.signal_sign == 1 else "inverse"
        return f"{self.profile_id}-{direction}-h{self.family.horizon}"

    @property
    def historical_reference_executable_id(self) -> str | None:
        return self.family.profile(self.profile_id).historical_reference(
            self.signal_sign
        )

    def semantic_parameters(self) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "configuration_id": self.configuration_id,
            "family_id": self.family.family_id,
            "holding_bars": self.family.horizon,
            "library_stride": self.family.library_stride,
            "neighbors": self.family.neighbors,
            "profile": self.profile_id,
            "selector_quantile_bp": self.family.selector_quantile_bp,
            "signal_sign": self.signal_sign,
        }
        if self.historical_reference_executable_id is not None:
            parameters["historical_reference_executable_id"] = (
                self.historical_reference_executable_id
            )
        return parameters


CURRENT_H48_N15_ANALOG_FAMILY = AnalogFamilySpec(
    family_id="family:path-geometry-analog-state-h48-n15-v1",
    horizon=48,
    library_stride=24,
    neighbors=15,
    profiles=(
        AnalogProfileSpec(
            profile_id="knn_path_geometry_15",
            feature_protocol=PATH_GEOMETRY_FEATURE_PROTOCOL,
        ),
        AnalogProfileSpec(
            profile_id="knn_return_magnitude_control_15",
            feature_protocol=RETURN_MAGNITUDE_FEATURE_PROTOCOL,
        ),
    ),
    selector_quantile_bp=8_500,
)


def raw_analog_features(
    frame: pd.DataFrame,
    *,
    feature_protocol: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build one registered feature space without family-specific training."""

    if feature_protocol not in _FEATURE_PROTOCOLS:
        raise ValueError("analog feature protocol is not registered")
    close = frame["close"].to_numpy(float)
    log_close = np.log(close)
    returns = np.full(len(close), np.nan)
    returns[1:] = np.diff(log_close)
    series = pd.Series(returns)
    vol192 = series.rolling(192, min_periods=192).std(ddof=1).to_numpy(float)
    columns: list[np.ndarray] = []
    if feature_protocol in {
        MULTISCALE_STATE_FEATURE_PROTOCOL,
        RETURN_ONLY_FEATURE_PROTOCOL,
        RETURN_MAGNITUDE_FEATURE_PROTOCOL,
    }:
        for period in (12, 48, 192):
            change = np.full(len(close), np.nan)
            change[period:] = log_close[period:] - log_close[:-period]
            columns.append(
                np.divide(
                    change,
                    vol192 * np.sqrt(period),
                    out=np.full(len(close), np.nan),
                    where=np.isfinite(vol192) & (vol192 > 0),
                )
            )
    if feature_protocol == MULTISCALE_STATE_FEATURE_PROTOCOL:
        vol48 = series.rolling(48, min_periods=48).std(ddof=1).to_numpy(float)
        columns.append(
            np.divide(
                vol48,
                vol192,
                out=np.full(len(close), np.nan),
                where=np.isfinite(vol192) & (vol192 > 0),
            )
            - 1.0
        )
        peak = pd.Series(close).rolling(576, min_periods=576).max().to_numpy(float)
        columns.append(
            np.divide(
                close,
                peak,
                out=np.full(len(close), np.nan),
                where=np.isfinite(peak) & (peak > 0),
            )
            - 1.0
        )
    elif feature_protocol == PATH_GEOMETRY_FEATURE_PROTOCOL:
        vol48 = series.rolling(48, min_periods=48).std(ddof=1).to_numpy(float)
        endpoint = np.full(len(close), np.nan)
        endpoint[48:] = log_close[48:] - log_close[:-48]
        path = (
            pd.Series(np.abs(returns))
            .rolling(48, min_periods=48)
            .sum()
            .to_numpy(float)
        )
        columns.append(
            np.divide(
                endpoint,
                path,
                out=np.full(len(close), np.nan),
                where=np.isfinite(path) & (path > 0),
            )
        )
        columns.append(series.rolling(96, min_periods=96).skew().to_numpy(float))
        span = frame["high"].to_numpy(float) - frame["low"].to_numpy(float)
        body = np.divide(
            close - frame["open"].to_numpy(float),
            span,
            out=np.full(len(close), np.nan),
            where=span > 0,
        )
        columns.append(
            pd.Series(body).rolling(24, min_periods=24).mean().to_numpy(float)
        )
        columns.append(
            np.divide(
                vol48,
                vol192,
                out=np.full(len(close), np.nan),
                where=np.isfinite(vol192) & (vol192 > 0),
            )
            - 1.0
        )
    return (
        np.column_stack(columns),
        vol192,
        _consecutive_run(_time_ns(frame)),
    )


def fit_fold_analog_family(
    frame: pd.DataFrame,
    *,
    family: AnalogFamilySpec,
    profile_id: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fit one family member using only labels ending inside the train fold."""

    profile = family.profile(profile_id)
    features, volatility, run = raw_analog_features(
        frame,
        feature_protocol=profile.feature_protocol,
    )
    time = pd.to_datetime(frame["time"], errors="raise")
    log_close = np.log(frame["close"].to_numpy(float))
    target = np.full(len(log_close), np.nan)
    target[:-family.horizon] = (
        log_close[family.horizon:] - log_close[:-family.horizon]
    )
    future_time = time.shift(-family.horizon)
    train = (
        ((time >= train_start) & (time <= train_end)).to_numpy()
        & np.isfinite(target)
        & np.isfinite(features).all(axis=1)
        & (future_time <= train_end).to_numpy()
    )
    indices = np.flatnonzero(train)[:: family.library_stride]
    if len(indices) < family.neighbors + 100:
        raise DiscoveryBoundaryError("analog library too small")
    library = features[indices]
    mean = library.mean(axis=0)
    standard = library.std(axis=0, ddof=0)
    standard = np.where(standard > 0, standard, 1.0)
    standardized_library = (library - mean) / standard
    valid = np.isfinite(features).all(axis=1)
    standardized = np.zeros_like(features, dtype=float)
    standardized[valid] = (features[valid] - mean) / standard
    tree = cKDTree(standardized_library)
    _, neighbors = tree.query(
        standardized,
        k=family.neighbors + 1,
        workers=1,
    )
    neighbor_rows = indices[neighbors]
    neighbor_targets = target[neighbor_rows]
    self_match = neighbor_rows == np.arange(len(features))[:, None]
    has_self = self_match.any(axis=1)
    neighbor_targets = np.where(self_match, np.nan, neighbor_targets)
    score = np.where(
        has_self,
        np.nanmean(neighbor_targets, axis=1),
        neighbor_targets[:, : family.neighbors].mean(axis=1),
    )
    score[~valid] = np.nan
    score[run < 193] = np.nan
    return score, volatility, run


def calibrate_analog_selector(
    score: np.ndarray,
    mask: np.ndarray,
    *,
    selector_quantile_bp: int,
) -> float:
    values = np.abs(score[mask & np.isfinite(score)])
    if len(values) < 1000:
        raise DiscoveryBoundaryError("analog selector too small")
    return float(
        np.quantile(
            values,
            selector_quantile_bp / 10_000,
            method="higher",
        )
    )


def analog_family_components(family: AnalogFamilySpec) -> tuple[ComponentSpec, ...]:
    local = (
        "axiom_rift.research.analog_state_family.{}@sha256:"
        + analog_family_implementation_sha256()
    )
    shared = (
        "axiom_rift.research.discovery.{}@sha256:"
        + discovery_implementation_sha256()
    )
    feature = ComponentSpec(
        display_name="registered completed-bar analog feature profile",
        protocol="feature.analog_family_registered_profile.v1",
        implementation=local.format("raw_analog_features"),
        spec={
            "availability": "completed_bar_only",
            "feature_protocol_binding": "typed_executable_profile_parameter",
            "non_evaluated_anchor_profile": (
                ANALOG_FAMILY_COMPARISON_ANCHOR_PROFILE
            ),
            "parameter_fields": ["profile"],
        },
    )
    label = ComponentSpec(
        display_name="fold-contained forward log-return analog label",
        protocol="label.forward_log_return_horizon.v1",
        implementation=local.format("fit_fold_analog_family"),
        spec={
            "future_end_must_be_inside_train": True,
            "horizon_bars": family.horizon,
            "parameter_fields": ["holding_bars"],
        },
    )
    model = ComponentSpec(
        display_name="typed fold-trained historical analog predictor",
        protocol="model.fold_train_knn_analog_family.v1",
        implementation=local.format("fit_fold_analog_family"),
        spec={
            "availability": "train_is_only",
            "library_stride": family.library_stride,
            "neighbors": family.neighbors,
            "parameter_fields": ["library_stride", "neighbors"],
            "self_neighbor": "excluded",
            "standardization": "train_mean_population_std",
        },
        semantic_dependencies=(feature.identity, label.identity),
    )
    selector = ComponentSpec(
        display_name="fold isolated analog selector",
        protocol="selector.fold_train_abs_quantile.v2",
        implementation=local.format("calibrate_analog_selector"),
        spec={
            "calibration_role": "train_is_only",
            "minimum_train_observations": 1000,
            "parameter_fields": ["selector_quantile_bp"],
            "quantile_basis_points": family.selector_quantile_bp,
            "quantile_method": "higher",
        },
        semantic_dependencies=(model.identity,),
    )
    trade = ComponentSpec(
        display_name="completed-bar next-open directional entry",
        protocol="trade.completed_bar_next_open_direction.v2",
        implementation=shared.format("simulate_fixed_hold"),
        spec={
            "decision_time": "bar_open_plus_5m",
            "direction": "signal_sign_times_score_sign",
            "entry_time": "next_exact_bar_open",
            "non_evaluated_anchor_signal_sign": 0,
            "parameter_fields": ["signal_sign"],
        },
        semantic_dependencies=(selector.identity,),
    )
    lifecycle = ComponentSpec(
        display_name="fixed-hold nonoverlap lifecycle",
        protocol="lifecycle.fixed_hold_no_overlap.v2",
        implementation=shared.format("simulate_fixed_hold"),
        spec={
            "entry_overlap": "reject_while_position_slot_is_occupied",
            "exit_surface": f"exact_bar_open_after_{family.horizon}_bars",
            "gap_action": "exclude_path",
        },
        semantic_dependencies=(trade.identity,),
    )
    risk = ComponentSpec(
        display_name="fixed one-lot risk",
        protocol="risk.fixed_one_lot.v1",
        implementation=shared.format("simulate_fixed_hold"),
        spec={"dynamic_sizing": False, "lot": 1, "positions_per_sleeve": 1},
        semantic_dependencies=(lifecycle.identity,),
    )
    execution = ComponentSpec(
        display_name="FPMarkets bid-bar spread execution",
        protocol="execution.fpmarkets_bid_bar_spread.v2",
        implementation=shared.format("execution_pnl"),
        spec={"point": "0.01", "stress": "half_effective_spread_each_side"},
        semantic_dependencies=(risk.identity,),
    )
    synthesis = ComponentSpec(
        display_name="registered analog replay family member",
        protocol="synthesis.registered_analog_family_member.v1",
        implementation=local.format("analog_family_executable"),
        spec={
            "exact_member_count": 4,
            "non_evaluated_anchor_configuration": (
                ANALOG_FAMILY_COMPARISON_ANCHOR_CONFIGURATION
            ),
            "parameter_fields": [
                "configuration_id",
                "historical_reference_executable_id",
            ],
        },
        semantic_dependencies=(execution.identity,),
    )
    portfolio = ComponentSpec(
        display_name="exact concurrent analog family inference",
        protocol="portfolio.concurrent_analog_family_inference.v1",
        implementation=(
            "axiom_rift.research.selection_inference."
            "infer_concurrent_selection_family@sha256:"
            + selection_inference_implementation_sha256()
        ),
        spec={
            "family_id": family.family_id,
            "inference_protocol": "concurrent_family_max_statistic_moving_block_v1",
            "parameter_fields": [
                "family_id",
                "selection_alpha_ppm",
                "selection_base_seed",
                "selection_block_lengths",
                "selection_bootstrap_samples",
                "selection_monte_carlo_confidence_ppm",
            ],
            "registered_member_count": len(family.configurations()),
            "selection_family_scope": "exact_ordered_four_configuration_family",
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
        risk,
        execution,
        synthesis,
        portfolio,
    )


def analog_family_executable(
    configuration: AnalogFamilyConfiguration,
) -> ExecutableSpec:
    family = configuration.family
    return _analog_family_executable(
        family=family,
        display_name=f"analog family {configuration.configuration_id}",
        parameters={
            **configuration.semantic_parameters(),
            **_analog_family_inference_parameters(),
        },
    )


def _analog_family_inference_parameters() -> dict[str, object]:
    return {
        "selection_alpha_ppm": ANALOG_FAMILY_ALPHA_PPM,
        "selection_base_seed": ANALOG_FAMILY_BASE_SEED,
        "selection_block_lengths": list(ANALOG_FAMILY_BLOCK_LENGTHS),
        "selection_bootstrap_samples": ANALOG_FAMILY_BOOTSTRAP_SAMPLES,
        "selection_monte_carlo_confidence_ppm": (
            ANALOG_FAMILY_MONTE_CARLO_CONFIDENCE_PPM
        ),
    }


def _analog_family_executable(
    *,
    family: AnalogFamilySpec,
    display_name: str,
    parameters: dict[str, object],
) -> ExecutableSpec:
    loader_hash = sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()
    return ExecutableSpec(
        display_name=display_name,
        components=analog_family_components(family),
        parameters=parameters,
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development"
        ),
        clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v2",
        cost_contract=(
            "cost:bid_bar_spread_point_0_01_causal_zero_repair_"
            "half_spread_stress_v2"
        ),
        engine_contract=(
            "engine:analog_family_v1:"
            f"python{'.'.join(str(v) for v in sys.version_info[:3])}:"
            f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
            f"family_{analog_family_implementation_sha256()}:"
            f"loader_{loader_hash}:shared_{discovery_implementation_sha256()}:"
            f"selection_{selection_inference_implementation_sha256()}"
        ),
    )


def analog_replay_baseline_executable(
    family: AnalogFamilySpec,
) -> ExecutableSpec:
    """Build the explicit non-evaluated anchor for one factorial replay Study."""

    if not isinstance(family, AnalogFamilySpec):
        raise TypeError("analog replay family must be an AnalogFamilySpec")
    parameters: dict[str, object] = {
        "configuration_id": ANALOG_FAMILY_COMPARISON_ANCHOR_CONFIGURATION,
        "family_id": family.family_id,
        "historical_reference_executable_id": "none",
        "holding_bars": family.horizon,
        "library_stride": family.library_stride,
        "neighbors": family.neighbors,
        "profile": ANALOG_FAMILY_COMPARISON_ANCHOR_PROFILE,
        "selector_quantile_bp": family.selector_quantile_bp,
        "signal_sign": 0,
        **_analog_family_inference_parameters(),
    }
    return _analog_family_executable(
        family=family,
        display_name="analog family non-evaluated comparison anchor",
        parameters=parameters,
    )


def analog_replay_architecture_chassis(
    family: AnalogFamilySpec,
) -> ArchitectureChassisSpec:
    """Return the canonical architecture used by replay Decision and Study APIs."""

    return ArchitectureChassisSpec.from_executable(
        analog_replay_baseline_executable(family)
    )


def analog_replay_controlled_chassis(
    family: AnalogFamilySpec,
) -> ControlledStudyChassis:
    """Return and self-check the exact factorial replay Study chassis.

    The family is not represented as a one-factor causal comparison.  Every
    evaluated member differs from a non-evaluated anchor in feature profile,
    trade direction, and registered family membership.  Label, trained model
    rule, selector, lifecycle, risk, execution, and family-inference protocol
    remain frozen; the atomic validator separately requires all four members
    and their paired controls in one trace.
    """

    baseline = analog_replay_baseline_executable(family)
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
    for configuration in family.configurations():
        validate_controlled_executable(
            payload,
            analog_family_executable(configuration),
        )
    return chassis


def analog_family_executable_map(
    family: AnalogFamilySpec,
) -> dict[str, AnalogFamilyConfiguration]:
    return {
        analog_family_executable(configuration).identity: configuration
        for configuration in family.configurations()
    }


__all__ = [
    "ANALOG_FAMILY_ALPHA_PPM",
    "ANALOG_FAMILY_BASE_SEED",
    "ANALOG_FAMILY_BLOCK_LENGTHS",
    "ANALOG_FAMILY_BOOTSTRAP_SAMPLES",
    "ANALOG_FAMILY_MONTE_CARLO_CONFIDENCE_PPM",
    "ANALOG_FAMILY_COMPARISON_ANCHOR_CONFIGURATION",
    "ANALOG_FAMILY_COMPARISON_ANCHOR_PROFILE",
    "CURRENT_H48_N15_ANALOG_FAMILY",
    "AnalogFamilyConfiguration",
    "AnalogFamilySpec",
    "AnalogProfileSpec",
    "analog_family_components",
    "analog_family_executable",
    "analog_family_executable_map",
    "analog_family_implementation_sha256",
    "analog_replay_architecture_chassis",
    "analog_replay_baseline_executable",
    "analog_replay_controlled_chassis",
    "calibrate_analog_selector",
    "fit_fold_analog_family",
    "raw_analog_features",
]
