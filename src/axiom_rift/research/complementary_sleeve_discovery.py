"""Complementary label-sleeve netting under fixed fitted signals."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any, Mapping

import numpy as np
import pandas as pd
import scipy

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec, canonical_digest
from axiom_rift.research import data as data_module
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    SELECTION_BOOTSTRAP_SAMPLES,
    SELECTION_SEED,
    DiscoveryBoundaryError,
    _claim_limits,
    _evaluate_configuration,
    _fold_payloads,
    _paired_control_pvalue,
    _selection_adjusted_pvalues,
    _selection_method,
    _time_ns,
    _validate_engine_environment,
    _validate_fold_payloads,
    _validate_production_data,
    causal_effective_spread,
    discovery_implementation_sha256,
)
from axiom_rift.research.event_label_discovery import (
    HORIZON,
    _fit_model,
    _labels,
    _raw_features,
    _score,
    calibrate_selector,
    event_label_implementation_sha256,
)


SELECTION_TOTAL_EXPOSURES = 512
_PROFILES = ("dual_label_net_exposure", "single_event_label_control")
_THIS_FILE = Path(__file__).resolve()


def complementary_sleeve_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def loader_implementation_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class ComplementarySleeveConfiguration:
    profile: str
    signal_sign: int
    holding_bars: int = HORIZON

    def __post_init__(self) -> None:
        if (
            self.profile not in _PROFILES
            or self.signal_sign not in {-1, 1}
            or self.holding_bars != HORIZON
        ):
            raise ValueError("complementary-sleeve configuration invalid")

    @property
    def configuration_id(self) -> str:
        direction = "direct" if self.signal_sign == 1 else "inverse"
        return f"{self.profile}-{direction}-h{HORIZON}"

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "holding_bars": HORIZON,
            "portfolio_profile": self.profile,
            "signal_sign": self.signal_sign,
            "sleeve_a": "first_passage_label_48_direct",
            "sleeve_b": "terminal_return_label_48_inverse",
        }


def complementary_sleeve_configurations() -> tuple[
    ComplementarySleeveConfiguration, ...
]:
    return tuple(
        ComplementarySleeveConfiguration(profile=profile, signal_sign=sign)
        for profile in _PROFILES
        for sign in (1, -1)
    )


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.complementary_sleeve_discovery.{name}"
        f"@sha256:{complementary_sleeve_implementation_sha256()}"
    )


def _label(name: str) -> str:
    return (
        f"axiom_rift.research.event_label_discovery.{name}"
        f"@sha256:{event_label_implementation_sha256()}"
    )


def _shared(name: str) -> str:
    return (
        f"axiom_rift.research.discovery.{name}"
        f"@sha256:{discovery_implementation_sha256()}"
    )


def complementary_sleeve_components() -> tuple[ComponentSpec, ...]:
    return (
        ComponentSpec(
            display_name="fixed STU-0065 multiscale signal inputs",
            protocol="feature.fixed_multiscale_return_path.v2",
            implementation=_label("raw_features"),
            spec={"same_features_across_profiles": True, "source_study": "STU-0065"},
        ),
        ComponentSpec(
            display_name="fixed first-passage and terminal-return sleeve labels",
            protocol="label.fixed_complementary_pair.v1",
            implementation=_label("build_labels"),
            spec={
                "sleeve_a": "first_passage_label_48",
                "sleeve_b": "terminal_return_label_control_48",
                "source_study": "STU-0065",
            },
        ),
        ComponentSpec(
            display_name="fixed fold-trained ridge sleeve scores",
            protocol="model.fixed_dual_ridge_scores.v1",
            implementation=_label("fit_fold_model"),
            spec={"same_capacity_and_penalty": True, "source_study": "STU-0065"},
        ),
        ComponentSpec(
            display_name="fixed fold isolated sleeve selectors",
            protocol="selector.fixed_dual_abs_quantile.v1",
            implementation=_label("calibrate_selector"),
            spec={"quantile_basis_points": 8500, "source_study": "STU-0065"},
        ),
        ComponentSpec(
            display_name="dual-sleeve agreement and cancellation portfolio",
            protocol="portfolio.dual_label_sleeve_netting.v1",
            implementation=_local("combine_sleeves"),
            spec={
                "parameter_fields": ["portfolio_profile"],
                "profiles": list(_PROFILES),
                "sleeve_a_direction": "direct",
                "sleeve_b_direction": "inverse",
            },
        ),
        ComponentSpec(
            display_name="completed-bar next-open net direction",
            protocol="trade.completed_bar_next_open_net_direction.v1",
            implementation=_shared("simulate_fixed_hold"),
            spec={
                "decision_time": "bar_open_plus_5m",
                "entry_time": "next_exact_bar_open",
                "parameter_fields": ["signal_sign"],
            },
        ),
        ComponentSpec(
            display_name="fixed 48-bar nonoverlap lifecycle",
            protocol="lifecycle.fixed_hold_no_overlap.v4",
            implementation=_shared("simulate_fixed_hold"),
            spec={"holding_bars": HORIZON, "same_across_profiles": True},
        ),
        ComponentSpec(
            display_name="one-lot net exposure cap",
            protocol="risk.net_exposure_cap_one_lot.v1",
            implementation=_local("combine_sleeves"),
            spec={
                "gross_sleeve_votes": 2,
                "net_lot_cap": 1,
                "opposite_votes": "cancel",
            },
        ),
        ComponentSpec(
            display_name="FPMarkets bid-bar spread execution",
            protocol="execution.fpmarkets_bid_bar_spread.v4",
            implementation=_shared("execution_pnl"),
            spec={"point": "0.01", "stress": "half_effective_spread_each_side"},
        ),
    )


def complementary_sleeve_executable(
    configuration: ComplementarySleeveConfiguration,
) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=f"complementary sleeve {configuration.configuration_id}",
        components=complementary_sleeve_components(),
        parameters=configuration.semantic_parameters(),
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development"
        ),
        clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v4",
        cost_contract=(
            "cost:bid_bar_spread_point_0_01_causal_zero_repair_"
            "half_spread_stress_v4"
        ),
        engine_contract=(
            f"engine:complementary_sleeve_v1:"
            f"python{'.'.join(str(v) for v in sys.version_info[:3])}:"
            f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
            f"implementation_{complementary_sleeve_implementation_sha256()}:"
            f"label_{event_label_implementation_sha256()}:"
            f"loader_{loader_implementation_sha256()}:"
            f"shared_{discovery_implementation_sha256()}:"
            f"bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:"
            f"bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}"
        ),
    )


def executable_configuration_map() -> dict[str, ComplementarySleeveConfiguration]:
    return {
        complementary_sleeve_executable(configuration).identity: configuration
        for configuration in complementary_sleeve_configurations()
    }


def _selected_strength(score: np.ndarray, threshold: float, sign: int) -> np.ndarray:
    selected = np.zeros(len(score), dtype=float)
    mask = np.isfinite(score) & (np.abs(score) >= threshold)
    selected[mask] = sign * score[mask] / threshold
    return selected


def _combine_sleeves(
    first_passage_score: np.ndarray,
    terminal_score: np.ndarray,
    first_passage_threshold: float,
    terminal_threshold: float,
    profile: str,
) -> np.ndarray:
    sleeve_a = _selected_strength(
        first_passage_score, first_passage_threshold, 1
    )
    if profile == "single_event_label_control":
        return sleeve_a
    if profile != "dual_label_net_exposure":
        raise DiscoveryBoundaryError("complementary-sleeve profile is invalid")
    sleeve_b = _selected_strength(terminal_score, terminal_threshold, -1)
    return sleeve_a + sleeve_b


def _matched(results: list[Any], profile: str, signal_sign: int) -> Any:
    found = [
        result
        for result in results
        if result.configuration.profile == profile
        and result.configuration.signal_sign == signal_sign
    ]
    if len(found) != 1:
        raise DiscoveryBoundaryError("complementary-sleeve control is not unique")
    return found[0]


def _populate_controls(results: list[Any]) -> None:
    for subject in results:
        configuration = subject.configuration
        opposite = _matched(results, configuration.profile, -configuration.signal_sign)
        control_profile = next(
            profile for profile in _PROFILES if profile != configuration.profile
        )
        portfolio_control = _matched(
            results, control_profile, configuration.signal_sign
        )
        subject.metrics["opposite_sign_worst_delta_net_profit_micropoints"] = (
            subject.metrics["net_profit_micropoints"]
            - opposite.metrics["net_profit_micropoints"]
        )
        subject.metrics["opposite_sign_pvalue_upper_ppm"] = _paired_control_pvalue(
            subject,
            opposite,
            role="opposite_sign",
            total_exposures=SELECTION_TOTAL_EXPOSURES,
        )
        subject.metrics["feature_control_worst_delta_net_profit_micropoints"] = (
            subject.metrics["net_profit_micropoints"]
            - portfolio_control.metrics["net_profit_micropoints"]
        )
        subject.metrics["feature_control_worst_pvalue_upper_ppm"] = (
            _paired_control_pvalue(
                subject,
                portfolio_control,
                role="single_sleeve_portfolio_control",
                total_exposures=SELECTION_TOTAL_EXPOSURES,
            )
        )


def compute_registered_complementary_sleeve_surface(
    repository_root: str | Path,
) -> dict[str, Any]:
    _validate_engine_environment()
    data = load_observed_development(Path(repository_root).resolve())
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    frame = data.frame
    time = pd.to_datetime(frame["time"], errors="raise")
    spread = causal_effective_spread(
        frame["spread"].to_numpy(float), _time_ns(frame)
    )
    full_features, full_volatility, full_run = _raw_features(frame)
    labels = _labels(frame, full_volatility, full_run)
    prefix_frames: dict[str, pd.DataFrame] = {}
    prefix_raw: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefix_spreads: dict[str, np.ndarray] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        end = int(
            time.searchsorted(pd.Timestamp(fold["test_oos"]["end"]), side="right")
        )
        prefix = frame.iloc[:end]
        prefix_frames[fold_id] = prefix
        prefix_raw[fold_id] = _raw_features(prefix)
        prefix_spreads[fold_id] = causal_effective_spread(
            prefix["spread"].to_numpy(float), _time_ns(prefix)
        )
    fold_sets: dict[
        str, dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]
    ] = {profile: {} for profile in _PROFILES}
    prefix_sets: dict[
        str, dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]
    ] = {profile: {} for profile in _PROFILES}
    calibrations: dict[
        str, dict[str, tuple[float, tuple[float, float], float]]
    ] = {profile: {} for profile in _PROFILES}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        train = fold["train_is"]
        start = pd.Timestamp(train["start"])
        end = pd.Timestamp(train["end"])
        selector_mask = ((time >= start) & (time <= end)).to_numpy()
        model_mask = selector_mask.copy()
        future_time = time.shift(-(HORIZON + 1))
        model_mask &= (future_time <= end).fillna(False).to_numpy()
        first_model = _fit_model(
            features=full_features,
            label=labels["first_passage_label_48"],
            train_mask=model_mask,
        )
        terminal_model = _fit_model(
            features=full_features,
            label=labels["terminal_return_label_control_48"],
            train_mask=model_mask,
        )
        first_score = _score(full_features, first_model)
        terminal_score = _score(full_features, terminal_model)
        first_threshold = calibrate_selector(first_score, selector_mask)
        terminal_threshold = calibrate_selector(terminal_score, selector_mask)
        prefix_time = pd.to_datetime(prefix_frames[fold_id]["time"], errors="raise")
        prefix_mask = ((prefix_time >= start) & (prefix_time <= end)).to_numpy()
        prefix_first = _score(prefix_raw[fold_id][0], first_model)
        prefix_terminal = _score(prefix_raw[fold_id][0], terminal_model)
        prefix_first_threshold = calibrate_selector(prefix_first, prefix_mask)
        prefix_terminal_threshold = calibrate_selector(prefix_terminal, prefix_mask)
        if (
            prefix_first_threshold != first_threshold
            or prefix_terminal_threshold != terminal_threshold
        ):
            raise DiscoveryBoundaryError("complementary sleeve threshold drifted")
        volatility_values = full_volatility[
            selector_mask & np.isfinite(full_volatility)
        ]
        cutoffs = (
            float(np.quantile(volatility_values, 1 / 3, method="higher")),
            float(np.quantile(volatility_values, 2 / 3, method="higher")),
        )
        for profile in _PROFILES:
            combined = _combine_sleeves(
                first_score,
                terminal_score,
                first_threshold,
                terminal_threshold,
                profile,
            )
            prefix_combined = _combine_sleeves(
                prefix_first,
                prefix_terminal,
                prefix_first_threshold,
                prefix_terminal_threshold,
                profile,
            )
            fold_sets[profile][fold_id] = (
                combined,
                full_volatility,
                full_run,
            )
            prefix_sets[profile][fold_id] = (
                prefix_combined,
                prefix_raw[fold_id][1],
                prefix_raw[fold_id][2],
            )
            calibrations[profile][fold_id] = (1.0, cutoffs, 1.0)
    results = []
    for configuration in complementary_sleeve_configurations():
        first = fold_sets[configuration.profile][str(folds[0]["fold_id"])]
        results.append(
            _evaluate_configuration(
                calibrations=calibrations[configuration.profile],
                frame=frame,
                features=first,
                fold_features=fold_sets[configuration.profile],
                folds=folds,
                configuration=configuration,
                effective_spread=spread,
                prefix_features=prefix_sets[configuration.profile],
                prefix_spreads=prefix_spreads,
                time=time,
                executable_id=complementary_sleeve_executable(configuration).identity,
            )
        )
    adjusted = _selection_adjusted_pvalues(
        results, total_exposures=SELECTION_TOTAL_EXPOSURES
    )
    for result in results:
        result.metrics["selection_aware_pvalue_ppm"] = adjusted[result.executable_id]
    _populate_controls(results)
    surface = {
        "claim_limits": _claim_limits()
        + [
            "portfolio_and_risk_are_the_only_primary_changed_domains",
            "both_sleeve_scores_and_selectors_are_fixed_from_STU_0065_semantics",
            "opposite_sleeve_votes_cancel_and_net_exposure_is_one_lot",
            "dual_and_single_sleeve_profiles_only",
            "four_trial_surface",
        ],
        "complementary_sleeve_implementation_sha256": (
            complementary_sleeve_implementation_sha256()
        ),
        "dataset_sha256": DATASET_SHA256,
        "engine_environment": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "python": ".".join(str(value) for value in sys.version_info[:3]),
            "scipy": scipy.__version__,
        },
        "evaluations": [
            {
                "direction_metrics": result.direction_metrics,
                "evaluable": all(
                    result.metrics[name] == 0
                    for name in (
                        "unknown_cost_unresolved_signal_count",
                        "causality_violation_count",
                        "nonfinite_metric_count",
                        "prefix_invariance_mismatch_count",
                        "append_invariance_mismatch_count",
                    )
                ),
                "fold_metrics": result.fold_metrics,
                "metrics": dict(sorted(result.metrics.items())),
                "regime_metrics": result.regime_metrics,
                "session_metrics": result.session_metrics,
                "subject_configuration_id": result.configuration.configuration_id,
                "subject_executable_id": result.executable_id,
            }
            for result in results
        ],
        "event_label_implementation_sha256": event_label_implementation_sha256(),
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "schema": "complementary_sleeve_surface.v1",
        "selection_context": [
            {
                "configuration_id": result.configuration.configuration_id,
                "executable_id": result.executable_id,
                "net_profit_micropoints": result.metrics["net_profit_micropoints"],
                "selection_aware_pvalue_ppm": result.metrics[
                    "selection_aware_pvalue_ppm"
                ],
            }
            for result in results
        ],
        "selection_method": _selection_method(SELECTION_TOTAL_EXPOSURES),
        "session_semantics": "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
    }
    canonical_bytes(surface)
    return surface


def project_complementary_sleeve_evaluation(
    surface: Mapping[str, Any],
    *,
    job_execution: Mapping[str, str],
    subject_executable_id: str,
    surface_artifact_hash: str,
    surface_manifest_hash: str,
) -> dict[str, Any]:
    value = dict(surface)
    if (
        sha256(canonical_bytes(value)).hexdigest() != surface_artifact_hash
        or value.get("schema") != "complementary_sleeve_surface.v1"
    ):
        raise DiscoveryBoundaryError("complementary-sleeve surface invalid")
    expected = executable_configuration_map()
    by_executable = {
        item.get("subject_executable_id"): item for item in value["evaluations"]
    }
    if set(by_executable) != set(expected) or subject_executable_id not in expected:
        raise DiscoveryBoundaryError("complementary-sleeve subjects differ")
    payload = {
        name: job_execution[name]
        for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")
    }
    if job_execution.get("identity") != canonical_digest(
        domain="running-job-execution", payload=payload
    ):
        raise DiscoveryBoundaryError("complementary-sleeve Job invalid")
    result = {
        **dict(by_executable[subject_executable_id]),
        "claim_limits": value["claim_limits"],
        "job_execution": dict(job_execution),
        "schema": "complementary_sleeve_evaluation.v1",
        "selection_context": value["selection_context"],
        "selection_method": value["selection_method"],
        "session_semantics": value["session_semantics"],
        "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(result)
    return result


__all__ = [
    "ComplementarySleeveConfiguration",
    "complementary_sleeve_configurations",
    "complementary_sleeve_executable",
    "complementary_sleeve_implementation_sha256",
    "compute_registered_complementary_sleeve_surface",
    "executable_configuration_map",
    "loader_implementation_sha256",
    "project_complementary_sleeve_evaluation",
]
