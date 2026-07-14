"""Prospective exact-family replay engine for historical STU-0048.

The historical source and evidence remain immutable.  This module restates the
registered causal drawdown depth/duration mechanism under new Component and
Executable identities, captures atomic fixed-hold rows, and proves raw parity
against all four historical evaluation artifacts.  Concurrent-family and
paired-control uncertainty are intentionally left to the atomic trace
recomputer; the obsolete project-history Bonferroni values are never copied.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any, Mapping

import numpy as np
import pandas as pd
import scipy

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research import data as data_module
from axiom_rift.research.data import load_observed_development
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
    _evaluate_configuration,
    _fold_payloads,
    _time_ns,
    _validate_engine_environment,
    _validate_fold_payloads,
    _validate_production_data,
    discovery_implementation_sha256,
    simulate_fixed_hold,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FIXED_HOLD_TRACE_VALIDATOR,
    FixedHoldProtocolDefinition,
    build_fixed_hold_family_trace,
    expected_fixed_hold_family_inventory,
    fixed_hold_observation_id,
    fixed_hold_trace_implementation_sha256,
)
from axiom_rift.research.historical_family_replay import (
    P1_HISTORICAL_FAMILY_CATALOG_DIGEST,
    STU0048_HISTORICAL_FAMILY,
    HistoricalMemberSpec,
)
from axiom_rift.research.selection_inference import (
    selection_inference_implementation_sha256,
)
from axiom_rift.research.scientific_trace import (
    DRAWDOWN_REPLAY_TRACE_PROTOCOL_ID,
)
from axiom_rift.storage.evidence import EvidenceStore


DRAWDOWN_REPLAY_ALPHA_PPM = 100_000
DRAWDOWN_REPLAY_LOOKBACK_BARS = 288
DRAWDOWN_REPLAY_SELECTOR_QUANTILE_BP = 7_000
DRAWDOWN_REPLAY_HOLDING_BARS = 24
DRAWDOWN_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT = 440
DRAWDOWN_REPLAY_HISTORICAL_CONTEXT_ID = (
    "historical-replay-obligation:"
    "c537b4ebc7085331cd21e52c26fbc994728c0520d5474473cc246f4e8c85322e"
)
DRAWDOWN_REPLAY_PROFILES = (
    "drawdown_depth_288",
    "drawdown_duration_288",
)
DRAWDOWN_REPLAY_CLOCK_CONTRACT = (
    "clock:fpmarkets_m5_bar_open_completed_plus_5m_v2"
)
DRAWDOWN_REPLAY_COST_CONTRACT = (
    "cost:bid_bar_segment_positive_median_min_1_unknown_entry_cancel_"
    "half_spread_stress_v1"
)
_THIS_FILE = Path(__file__).resolve()

STU0048_HISTORICAL_EVALUATION_HASHES = {
    "drawdown_depth_288-deterioration-h24": (
        "e08c4e8a131160a35f86c166f55a79f2d93cfa36fd613a4f9e0afc846980c1fc"
    ),
    "drawdown_depth_288-recovery-h24": (
        "13bd4f0940566038250db1eabcdd1466252761227e463ad2cff1e78b523e4c19"
    ),
    "drawdown_duration_288-deterioration-h24": (
        "e00a596d85c6639bf02e095cdedb0d7caac0e5def7239d35c4e1bbdf3d390dbd"
    ),
    "drawdown_duration_288-recovery-h24": (
        "bda62dbf52f937dc7723199d10adaefd52994a241056d6542cd56883b2fbe02d"
    ),
}

_LEGACY_INFERENCE_METRICS = frozenset(
    {
        "feature_control_worst_pvalue_upper_ppm",
        "opposite_sign_pvalue_upper_ppm",
        "selection_aware_pvalue_ppm",
    }
)


def drawdown_replay_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def drawdown_replay_loader_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


def drawdown_replay_producer_implementation_identities() -> dict[str, str]:
    return {
        "catalog_sha256": P1_HISTORICAL_FAMILY_CATALOG_DIGEST,
        "discovery_sha256": discovery_implementation_sha256(),
        "drawdown_replay_sha256": drawdown_replay_implementation_sha256(),
        "loader_sha256": drawdown_replay_loader_sha256(),
    }


@dataclass(frozen=True, slots=True)
class DrawdownReplayConfiguration:
    ordinal: int
    configuration_id: str
    historical_reference_executable_id: str
    profile: str
    signal_sign: int
    holding_bars: int = DRAWDOWN_REPLAY_HOLDING_BARS
    lookback_bars: int = DRAWDOWN_REPLAY_LOOKBACK_BARS
    selector_quantile_bp: int = DRAWDOWN_REPLAY_SELECTOR_QUANTILE_BP
    unknown_entry_action: str = "cancel_before_open"

    def __post_init__(self) -> None:
        if (
            type(self.ordinal) is not int
            or self.ordinal < 1
            or type(self.configuration_id) is not str
            or not self.configuration_id.isascii()
            or self.profile not in DRAWDOWN_REPLAY_PROFILES
            or self.signal_sign not in {-1, 1}
            or self.holding_bars != DRAWDOWN_REPLAY_HOLDING_BARS
            or self.lookback_bars != DRAWDOWN_REPLAY_LOOKBACK_BARS
            or self.selector_quantile_bp
            != DRAWDOWN_REPLAY_SELECTOR_QUANTILE_BP
            or self.unknown_entry_action != "cancel_before_open"
            or not self.historical_reference_executable_id.startswith(
                "executable:"
            )
        ):
            raise ValueError("drawdown replay configuration is invalid")

    def semantic_parameters(self) -> dict[str, object]:
        return {
            "configuration_id": self.configuration_id,
            "historical_reference_executable_id": (
                self.historical_reference_executable_id
            ),
            "holding_bars": self.holding_bars,
            "lookback_bars": self.lookback_bars,
            "profile": self.profile,
            "selector_quantile_bp": self.selector_quantile_bp,
            "signal_sign": self.signal_sign,
            "unknown_entry_action": self.unknown_entry_action,
        }


def _configuration_from_member(
    member: HistoricalMemberSpec,
) -> DrawdownReplayConfiguration:
    parameters = member.parameter_values()
    return DrawdownReplayConfiguration(
        ordinal=member.ordinal,
        configuration_id=member.configuration_id,
        historical_reference_executable_id=(
            member.historical_reference_executable_id
        ),
        profile=str(parameters["profile"]),
        signal_sign=int(parameters["signal_sign"]),
        holding_bars=int(parameters["holding_bars"]),
        lookback_bars=int(parameters["lookback_bars"]),
        selector_quantile_bp=int(parameters["selector_quantile_bp"]),
        unknown_entry_action=str(parameters["unknown_entry_action"]),
    )


def drawdown_replay_configurations() -> tuple[DrawdownReplayConfiguration, ...]:
    values = tuple(
        _configuration_from_member(member)
        for member in STU0048_HISTORICAL_FAMILY.members
    )
    if tuple(value.ordinal for value in values) != (1, 2, 3, 4):
        raise RuntimeError("STU-0048 drawdown family order drifted")
    return values


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.drawdown_state_replay.{name}@sha256:"
        f"{drawdown_replay_implementation_sha256()}"
    )


def _shared(name: str) -> str:
    return (
        f"axiom_rift.research.discovery.{name}@sha256:"
        f"{discovery_implementation_sha256()}"
    )


def drawdown_replay_components() -> tuple[ComponentSpec, ...]:
    feature = ComponentSpec(
        display_name="causal historical drawdown state replay",
        protocol="feature.causal_drawdown_state.replay.v2",
        implementation=_local("compute_drawdown_replay_score"),
        spec={
            "availability": "completed_bar_close",
            "lookback_bars": DRAWDOWN_REPLAY_LOOKBACK_BARS,
            "parameter_fields": ["lookback_bars", "profile"],
            "profiles": list(DRAWDOWN_REPLAY_PROFILES),
        },
    )
    selector = ComponentSpec(
        display_name="fold isolated historical drawdown selector",
        protocol="selector.fold_train_abs_quantile.replay.v2",
        implementation=_local("calibrate_drawdown_replay_selector"),
        spec={
            "calibration_role": "train_is_only",
            "minimum_train_observations": 1000,
            "parameter_fields": ["selector_quantile_bp"],
            "quantile_method": "higher",
        },
        semantic_dependencies=(feature.identity,),
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
            "parameter_fields": ["holding_bars", "unknown_entry_action"],
        },
        semantic_dependencies=(trade.identity,),
    )
    execution = ComponentSpec(
        display_name="causal segment spread replay execution",
        protocol="execution.fpmarkets_segment_spread.replay.v2",
        implementation=_local("causal_drawdown_replay_spread"),
        spec={
            "point": "0.01",
            "stress": "half_effective_spread_each_side",
            "zero_spread": "lagged_positive_segment_median_min_1_else_unknown",
        },
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
        display_name="registered STU-0048 replay member",
        protocol="synthesis.historical_fixed_hold_member.v2",
        implementation=_local("drawdown_replay_executable"),
        spec={
            "catalog_digest": P1_HISTORICAL_FAMILY_CATALOG_DIGEST,
            "exact_member_count": 4,
            "historical_family_identity": STU0048_HISTORICAL_FAMILY.identity,
            "parameter_fields": [
                "configuration_id",
                "historical_reference_executable_id",
            ],
        },
        semantic_dependencies=(risk.identity,),
    )
    portfolio = ComponentSpec(
        display_name="exact concurrent STU-0048 replay inference",
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
        selector,
        trade,
        lifecycle,
        execution,
        risk,
        synthesis,
        portfolio,
    )


def drawdown_replay_executable(
    configuration: DrawdownReplayConfiguration,
    *,
    historical_context_prior_global_exposure_count: int,
) -> ExecutableSpec:
    if configuration not in drawdown_replay_configurations():
        raise ValueError("configuration is outside the exact STU-0048 family")
    if (
        type(historical_context_prior_global_exposure_count) is not int
        or historical_context_prior_global_exposure_count
        < DRAWDOWN_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
    ):
        raise ValueError(
            "historical context cannot precede the original STU-0048 family"
        )
    return ExecutableSpec(
        display_name=f"STU-0048 replay {configuration.configuration_id}",
        components=drawdown_replay_components(),
        parameters={
            **configuration.semantic_parameters(),
            "alpha_ppm": DRAWDOWN_REPLAY_ALPHA_PPM,
            "base_seed": SELECTION_SEED,
            "block_lengths": list(SELECTION_BLOCK_LENGTHS),
            "bootstrap_samples": SELECTION_BOOTSTRAP_SAMPLES,
            "historical_context_prior_global_exposure_count": (
                historical_context_prior_global_exposure_count
            ),
            "monte_carlo_confidence_ppm": (
                SELECTION_MONTE_CARLO_CONFIDENCE_PPM
            ),
        },
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:"
            "rolling_windows_9_observed_development"
        ),
        clock_contract=DRAWDOWN_REPLAY_CLOCK_CONTRACT,
        cost_contract=DRAWDOWN_REPLAY_COST_CONTRACT,
        engine_contract=(
            "engine:stu0048_drawdown_replay_v2:"
            f"python{'.'.join(str(value) for value in sys.version_info[:3])}:"
            f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
            f"adapter_{drawdown_replay_implementation_sha256()}:"
            f"loader_{drawdown_replay_loader_sha256()}:"
            f"shared_{discovery_implementation_sha256()}:"
            f"selection_{selection_inference_implementation_sha256()}:"
            f"catalog_{P1_HISTORICAL_FAMILY_CATALOG_DIGEST}"
        ),
    )


def drawdown_replay_executable_map(
    *,
    historical_context_prior_global_exposure_count: int,
) -> dict[str, DrawdownReplayConfiguration]:
    return {
        drawdown_replay_executable(
            configuration,
            historical_context_prior_global_exposure_count=(
                historical_context_prior_global_exposure_count
            ),
        ).identity: configuration
        for configuration in drawdown_replay_configurations()
    }


def drawdown_replay_protocol_definition(
    *,
    historical_context_prior_global_exposure_count: int,
) -> FixedHoldProtocolDefinition:
    configurations = drawdown_replay_configurations()
    return FixedHoldProtocolDefinition(
        family=STU0048_HISTORICAL_FAMILY,
        prospective_executable_ids=tuple(
            drawdown_replay_executable(
                configuration,
                historical_context_prior_global_exposure_count=(
                    historical_context_prior_global_exposure_count
                ),
            ).identity
            for configuration in configurations
        ),
        protocol_id=DRAWDOWN_REPLAY_TRACE_PROTOCOL_ID,
        fold_ids=EXPECTED_FOLD_IDS,
        invariance_keys=DRAWDOWN_REPLAY_PROFILES,
        allowed_regimes=("high", "low", "middle"),
        dataset_sha256=DATASET_SHA256,
        material_identity=OBSERVED_MATERIAL_ID,
        split_artifact_sha256=ROLLING_SPLIT_SHA256,
        clock_contract=DRAWDOWN_REPLAY_CLOCK_CONTRACT,
        cost_contract=DRAWDOWN_REPLAY_COST_CONTRACT,
        producer_implementation_identities=tuple(
            sorted(
                drawdown_replay_producer_implementation_identities().items()
            )
        ),
        historical_context_id=DRAWDOWN_REPLAY_HISTORICAL_CONTEXT_ID,
        historical_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
        original_family_end_global_exposure_count=(
            DRAWDOWN_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
        ),
        alpha_ppm=DRAWDOWN_REPLAY_ALPHA_PPM,
        bootstrap_samples=SELECTION_BOOTSTRAP_SAMPLES,
        block_lengths=SELECTION_BLOCK_LENGTHS,
        monte_carlo_confidence_ppm=SELECTION_MONTE_CARLO_CONFIDENCE_PPM,
        base_seed=SELECTION_SEED,
    )


def _rolling_peak_age(close: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    peak = np.full(len(close), np.nan)
    age = np.full(len(close), np.nan)
    queue: deque[int] = deque()
    for index, value in enumerate(close):
        while queue and close[queue[-1]] <= value:
            queue.pop()
        queue.append(index)
        while queue and queue[0] <= index - DRAWDOWN_REPLAY_LOOKBACK_BARS:
            queue.popleft()
        if index >= DRAWDOWN_REPLAY_LOOKBACK_BARS - 1:
            peak[index] = close[queue[0]]
            age[index] = index - queue[0]
    return peak, age


def compute_drawdown_replay_score(
    frame: pd.DataFrame,
    profile: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if profile not in DRAWDOWN_REPLAY_PROFILES:
        raise ValueError("drawdown replay profile is invalid")
    close = frame["close"].to_numpy(float)
    if np.any(~np.isfinite(close)) or np.any(close <= 0):
        raise ValueError("drawdown replay close is invalid")
    peak, age = _rolling_peak_age(close)
    score = (
        np.divide(
            close,
            peak,
            out=np.full(len(close), np.nan),
            where=np.isfinite(peak) & (peak > 0),
        )
        - 1
        if profile == "drawdown_depth_288"
        else -age
    )
    returns = np.full(len(close), np.nan)
    returns[1:] = np.diff(np.log(close))
    volatility = (
        pd.Series(returns)
        .rolling(96, min_periods=96)
        .std(ddof=1)
        .to_numpy(float)
    )
    return score, volatility, _consecutive_run(_time_ns(frame))


def causal_drawdown_replay_spread(
    spread: np.ndarray,
    time_ns: np.ndarray,
) -> np.ndarray:
    values = np.asarray(spread, float)
    times = np.asarray(time_ns, np.int64)
    if (
        len(values) != len(times)
        or np.any(~np.isfinite(values))
        or np.any(values < 0)
    ):
        raise ValueError("drawdown replay spread is invalid")
    segment = np.zeros(len(times), np.int64)
    if len(times) > 1:
        segment[1:] = np.cumsum(np.diff(times) != 300_000_000_000)
    positive = pd.Series(np.where(values > 0, values, np.nan))
    groups = pd.Series(segment)
    lagged = positive.groupby(groups, sort=False).transform(
        lambda part: part.shift(1).rolling(288, min_periods=1).median()
    )
    return np.where(values > 0, values, lagged.to_numpy(float))


def calibrate_drawdown_replay_selector(
    score: np.ndarray,
    mask: np.ndarray,
) -> float:
    values = np.abs(score[mask & np.isfinite(score)])
    if len(values) < 1000:
        raise DiscoveryBoundaryError("drawdown replay selector is too small")
    return float(
        np.quantile(
            values,
            DRAWDOWN_REPLAY_SELECTOR_QUANTILE_BP / 10_000,
            method="higher",
        )
    )


def _iso(value: object) -> str:
    return pd.Timestamp(value).isoformat()


def _micropoints(value: object) -> int:
    return int(round(float(value) * 1_000_000))


def _score_digest(values: np.ndarray) -> str:
    array = np.asarray(values, dtype="<f8").copy()
    array[np.isnan(array)] = np.nan
    material = (
        b"fixed-hold-score-vector.v1\0"
        + len(array).to_bytes(8, "big")
        + array.tobytes(order="C")
    )
    return sha256(material).hexdigest()


def _time_position_map(frame: pd.DataFrame) -> dict[int, int]:
    values = _time_ns(frame)
    if len(values) != len(set(int(value) for value in values)):
        raise ValueError("drawdown replay time index is not unique")
    return {int(value): index for index, value in enumerate(values)}


def _trade_rows(
    *,
    configuration: DrawdownReplayConfiguration,
    executable_id: str,
    simulations: Mapping[tuple[str, str], Any],
    frame: pd.DataFrame,
) -> list[dict[str, object]]:
    positions = _time_position_map(frame)
    rows: list[dict[str, object]] = []
    for (fold_id, scope), simulation in simulations.items():
        if scope != "full":
            continue
        for raw in simulation.trades.to_dict(orient="records"):
            decision_bar = pd.Timestamp(raw["decision_bar_open_time"])
            entry = pd.Timestamp(raw["entry_time"])
            exit_time = pd.Timestamp(raw["exit_time"])
            decision_index = positions[int(decision_bar.value)]
            entry_index = positions[int(entry.value)]
            exit_index = positions[int(exit_time.value)]
            gross = _micropoints(raw["gross_pnl"])
            native_cost = _micropoints(raw["native_cost"])
            stress_cost = _micropoints(raw["stress_cost"])
            row: dict[str, object] = {
                "availability_time": _iso(raw["decision_time"]),
                "configuration_id": configuration.configuration_id,
                "decision_bar_index": decision_index,
                "decision_bar_open_time": _iso(decision_bar),
                "decision_time": _iso(raw["decision_time"]),
                "direction": int(raw["direction"]),
                "entry_bar_index": entry_index,
                "entry_time": _iso(entry),
                "executable_id": executable_id,
                "exit_bar_index": exit_index,
                "exit_time": _iso(exit_time),
                "fold_id": fold_id,
                "gross_pnl_micropoints": gross,
                "historical_reference_executable_id": (
                    configuration.historical_reference_executable_id
                ),
                "holding_bars": configuration.holding_bars,
                "native_cost_micropoints": native_cost,
                "native_net_pnl_micropoints": gross - native_cost,
                "observation_id": "pending",
                "regime": str(raw["regime"]),
                "stress_cost_micropoints": stress_cost,
                "stress_net_pnl_micropoints": gross - stress_cost,
            }
            if not (
                entry_index == decision_index + 1
                and exit_index - entry_index == configuration.holding_bars
            ):
                raise RuntimeError("captured fixed-hold trade indices drifted")
            row["observation_id"] = fixed_hold_observation_id("trade", row)
            rows.append(row)
    return rows


def _intent_rows(
    *,
    configuration: DrawdownReplayConfiguration,
    executable_id: str,
    simulations: Mapping[tuple[str, str], Any],
    frame: pd.DataFrame,
) -> list[dict[str, object]]:
    positions = _time_position_map(frame)
    rows: list[dict[str, object]] = []
    for (fold_id, scope), simulation in simulations.items():
        for ordinal, raw in enumerate(simulation.intent_rows, start=1):
            decision, entry, exit_time, direction, status = raw
            decision_timestamp = pd.Timestamp(decision)
            entry_timestamp = pd.Timestamp(entry)
            exit_timestamp = pd.Timestamp(exit_time)
            decision_bar_timestamp = decision_timestamp - pd.Timedelta(
                minutes=5
            )
            decision_index = positions[int(decision_bar_timestamp.value)]
            entry_index = positions[int(entry_timestamp.value)]
            row: dict[str, object] = {
                "availability_time": _iso(decision_timestamp),
                "configuration_id": configuration.configuration_id,
                "decision_bar_index": decision_index,
                "decision_bar_open_time": _iso(decision_bar_timestamp),
                "decision_time": _iso(decision_timestamp),
                "direction": int(direction),
                "entry_bar_index": entry_index,
                "entry_time": _iso(entry_timestamp),
                "executable_id": executable_id,
                "exit_bar_index": positions[int(exit_timestamp.value)],
                "exit_time": _iso(exit_timestamp),
                "fold_id": fold_id,
                "historical_reference_executable_id": (
                    configuration.historical_reference_executable_id
                ),
                "holding_bars": configuration.holding_bars,
                "observation_id": "pending",
                "ordinal": ordinal,
                "scope": scope,
                "status": str(status),
            }
            if not (
                entry_index == decision_index + 1
                and row["exit_bar_index"] - entry_index
                == configuration.holding_bars
            ):
                raise RuntimeError("captured fixed-hold intent indices drifted")
            row["observation_id"] = fixed_hold_observation_id("intent", row)
            rows.append(row)
    return rows


def expected_drawdown_replay_inventory(
    *,
    historical_context_prior_global_exposure_count: int,
) -> tuple[dict[str, object], ...]:
    return expected_fixed_hold_family_inventory(
        drawdown_replay_protocol_definition(
            historical_context_prior_global_exposure_count=(
                historical_context_prior_global_exposure_count
            )
        )
    )


def _load_historical_evaluations(
    repository_root: Path,
) -> dict[str, dict[str, Any]]:
    store = EvidenceStore(repository_root / "local" / "evidence")
    evaluations: dict[str, dict[str, Any]] = {}
    for configuration_id, identity in (
        STU0048_HISTORICAL_EVALUATION_HASHES.items()
    ):
        value = parse_canonical(store.read_verified(identity))
        if (
            not isinstance(value, dict)
            or value.get("schema") != "drawdown_state_evaluation.v1"
            or value.get("subject_configuration_id") != configuration_id
        ):
            raise RuntimeError("historical STU-0048 evaluation binding drifted")
        evaluations[configuration_id] = value
    return evaluations


def _assert_historical_raw_parity(
    *,
    repository_root: Path,
    results: Mapping[str, Any],
) -> None:
    historical = _load_historical_evaluations(repository_root)
    by_reference = {
        configuration.historical_reference_executable_id: results[
            configuration.configuration_id
        ]
        for configuration in drawdown_replay_configurations()
    }
    for configuration in drawdown_replay_configurations():
        result = results[configuration.configuration_id]
        control = STU0048_HISTORICAL_FAMILY.control_for_historical_executable(
            configuration.historical_reference_executable_id
        )
        opposite = by_reference[control.opposite_historical_executable_id]
        features = tuple(
            by_reference[value]
            for value in control.feature_historical_executable_ids
        )
        observed_metrics = {
            **{
                name: value
                for name, value in result.metrics.items()
                if name not in _LEGACY_INFERENCE_METRICS
            },
            "feature_control_worst_delta_net_profit_micropoints": min(
                result.metrics["net_profit_micropoints"]
                - value.metrics["net_profit_micropoints"]
                for value in features
            ),
            "opposite_sign_worst_delta_net_profit_micropoints": (
                result.metrics["net_profit_micropoints"]
                - opposite.metrics["net_profit_micropoints"]
            ),
        }
        expected = historical[configuration.configuration_id]
        expected_metrics = {
            name: value
            for name, value in expected["metrics"].items()
            if name not in _LEGACY_INFERENCE_METRICS
        }
        surfaces = {
            "metrics": (observed_metrics, expected_metrics),
            "fold_metrics": (result.fold_metrics, expected["fold_metrics"]),
            "regime_metrics": (
                result.regime_metrics,
                expected["regime_metrics"],
            ),
            "session_metrics": (
                result.session_metrics,
                expected["session_metrics"],
            ),
            "direction_metrics": (
                result.direction_metrics,
                expected["direction_metrics"],
            ),
        }
        mismatches = {
            name: {
                "expected": expected_value,
                "observed": observed_value,
            }
            for name, (observed_value, expected_value) in surfaces.items()
            if observed_value != expected_value
        }
        if mismatches:
            raise RuntimeError(
                "prospective STU-0048 raw results differ from historical "
                f"evidence for {configuration.configuration_id}: "
                f"{mismatches}"
            )


def compute_stu0048_drawdown_family_trace(
    repository_root: str | Path,
    *,
    historical_context_prior_global_exposure_count: int,
) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
    """Compute one exact four-member neutral trace and prove raw parity."""

    root = Path(repository_root).resolve()
    definition = drawdown_replay_protocol_definition(
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        )
    )
    inventory = expected_fixed_hold_family_inventory(definition)
    executable_by_configuration = {
        str(item["configuration_id"]): str(item["executable_id"])
        for item in inventory
    }
    _validate_engine_environment()
    data = load_observed_development(root)
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    frame = data.frame
    time = pd.to_datetime(frame["time"], errors="raise")
    spread = causal_drawdown_replay_spread(
        frame["spread"].to_numpy(float),
        _time_ns(frame),
    )
    prefix_frames: dict[str, pd.DataFrame] = {}
    prefix_spreads: dict[str, np.ndarray] = {}
    windows: list[dict[str, object]] = []
    for fold in folds:
        fold_id = str(fold["fold_id"])
        test = fold["test_oos"]
        prefix_end = int(
            time.searchsorted(pd.Timestamp(test["end"]), side="right")
        )
        prefix_frames[fold_id] = frame.iloc[:prefix_end]
        prefix_spreads[fold_id] = causal_drawdown_replay_spread(
            prefix_frames[fold_id]["spread"].to_numpy(float),
            _time_ns(prefix_frames[fold_id]),
        )
        eligible_dates = tuple(
            sorted(
                pd.DatetimeIndex(
                    time[
                        (time >= pd.Timestamp(test["start"]))
                        & (time <= pd.Timestamp(test["end"]))
                    ]
                )
                .normalize()
                .strftime("%Y-%m-%d")
                .unique()
            )
        )
        windows.append(
            {
                "eligible_dates": list(eligible_dates),
                "fold_id": fold_id,
                "test_end": _iso(test["end"]),
                "test_start": _iso(test["start"]),
                "train_end": _iso(fold["train_is"]["end"]),
                "train_start": _iso(fold["train_is"]["start"]),
            }
        )

    features: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefixes: dict[
        str, dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]
    ] = {}
    calibrations: dict[
        str, dict[str, tuple[float, tuple[float, float], float]]
    ] = {}
    comparisons: list[dict[str, object]] = []
    for profile in DRAWDOWN_REPLAY_PROFILES:
        full = compute_drawdown_replay_score(frame, profile)
        features[profile] = full
        prefixes[profile] = {}
        calibrations[profile] = {}
        for fold in folds:
            fold_id = str(fold["fold_id"])
            train = fold["train_is"]
            train_start = pd.Timestamp(train["start"])
            train_end = pd.Timestamp(train["end"])
            train_mask = (
                (time >= train_start) & (time <= train_end)
            ).to_numpy()
            volatility = full[1][train_mask & np.isfinite(full[1])]
            prefix_frame = prefix_frames[fold_id]
            prefix = compute_drawdown_replay_score(prefix_frame, profile)
            prefixes[profile][fold_id] = prefix
            prefix_time = pd.to_datetime(prefix_frame["time"], errors="raise")
            prefix_mask = (
                (prefix_time >= train_start) & (prefix_time <= train_end)
            ).to_numpy()
            calibrations[profile][fold_id] = (
                calibrate_drawdown_replay_selector(full[0], train_mask),
                (
                    float(np.quantile(volatility, 1 / 3, method="higher")),
                    float(np.quantile(volatility, 2 / 3, method="higher")),
                ),
                calibrate_drawdown_replay_selector(prefix[0], prefix_mask),
            )
            compared = len(prefix[0])
            comparisons.append(
                {
                    "compared_row_count": compared,
                    "fold_id": fold_id,
                    "full_feature_values_sha256": _score_digest(
                        full[0][:compared]
                    ),
                    "invariance_key": profile,
                    "prefix_feature_values_sha256": _score_digest(prefix[0]),
                }
            )
    comparisons.sort(
        key=lambda item: (
            str(item["fold_id"]),
            str(item["invariance_key"]),
        )
    )

    results: dict[str, Any] = {}
    captures_by_configuration: dict[
        str, dict[tuple[str, str], Any]
    ] = {}
    raw_metrics: dict[str, dict[str, int]] = {}
    for configuration in drawdown_replay_configurations():
        executable_id = executable_by_configuration[
            configuration.configuration_id
        ]
        captures: dict[tuple[str, str], Any] = {}

        def capture_simulation(**kwargs: Any) -> Any:
            simulation = simulate_fixed_hold(**kwargs)
            fold_id = str(kwargs["fold_id"])
            scope = "full" if kwargs["frame"] is frame else "prefix"
            key = (fold_id, scope)
            if key in captures:
                raise RuntimeError("drawdown replay simulation capture duplicated")
            captures[key] = simulation
            return simulation

        result = _evaluate_configuration(
            calibrations=calibrations[configuration.profile],
            configuration=configuration,
            effective_spread=spread,
            executable_id=executable_id,
            features=features[configuration.profile],
            folds=folds,
            frame=frame,
            prefix_features=prefixes[configuration.profile],
            prefix_spreads=prefix_spreads,
            simulation_fn=capture_simulation,
            time=time,
        )
        expected_capture_keys = {
            (str(fold["fold_id"]), scope)
            for fold in folds
            for scope in ("full", "prefix")
        }
        if set(captures) != expected_capture_keys:
            raise RuntimeError("drawdown replay simulation capture is incomplete")
        results[configuration.configuration_id] = result
        captures_by_configuration[configuration.configuration_id] = captures
        raw_metrics[executable_id] = dict(result.metrics)

    _assert_historical_raw_parity(repository_root=root, results=results)

    all_trades: list[dict[str, object]] = []
    all_intents: list[dict[str, object]] = []
    for configuration in drawdown_replay_configurations():
        executable_id = executable_by_configuration[
            configuration.configuration_id
        ]
        captures = captures_by_configuration[configuration.configuration_id]
        all_trades.extend(
            _trade_rows(
                configuration=configuration,
                executable_id=executable_id,
                simulations=captures,
                frame=frame,
            )
        )
        all_intents.extend(
            _intent_rows(
                configuration=configuration,
                executable_id=executable_id,
                simulations=captures,
                frame=frame,
            )
        )
    all_trades.sort(
        key=lambda item: (
            str(item["configuration_id"]),
            str(item["fold_id"]),
            str(item["decision_time"]),
            str(item["observation_id"]),
        )
    )
    all_intents.sort(
        key=lambda item: (
            str(item["configuration_id"]),
            str(item["fold_id"]),
            str(item["scope"]),
            int(item["ordinal"]),
            str(item["observation_id"]),
        )
    )
    aggregates: dict[tuple[str, str, str], list[int]] = {}
    for trade in all_trades:
        key = (
            str(trade["configuration_id"]),
            str(trade["fold_id"]),
            str(trade["decision_time"])[:10],
        )
        values = aggregates.setdefault(key, [0, 0, 0])
        values[0] += 1
        values[1] += int(trade["native_net_pnl_micropoints"])
        values[2] += int(trade["stress_net_pnl_micropoints"])
    by_configuration = {
        str(item["configuration_id"]): item for item in inventory
    }
    eligible_rows: list[dict[str, object]] = []
    for configuration_id in sorted(by_configuration):
        member = by_configuration[configuration_id]
        for window in windows:
            for day in window["eligible_dates"]:
                values = aggregates.get(
                    (configuration_id, str(window["fold_id"]), str(day)),
                    [0, 0, 0],
                )
                eligible_rows.append(
                    {
                        "configuration_id": configuration_id,
                        "date": day,
                        "entry_count": values[0],
                        "executable_id": member["executable_id"],
                        "fold_id": window["fold_id"],
                        "native_net_pnl_micropoints": values[1],
                        "stress_net_pnl_micropoints": values[2],
                    }
                )
    normalized = build_fixed_hold_family_trace(
        definition=definition,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
        windows=windows,
        invariance_comparisons=comparisons,
        trade_observations=all_trades,
        intent_observations=all_intents,
        eligible_day_observations=eligible_rows,
    )
    return normalized, raw_metrics


__all__ = [
    "DRAWDOWN_REPLAY_ALPHA_PPM",
    "DRAWDOWN_REPLAY_HISTORICAL_CONTEXT_ID",
    "DRAWDOWN_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT",
    "DRAWDOWN_REPLAY_PROFILES",
    "DRAWDOWN_REPLAY_TRACE_PROTOCOL_ID",
    "DrawdownReplayConfiguration",
    "STU0048_HISTORICAL_EVALUATION_HASHES",
    "calibrate_drawdown_replay_selector",
    "causal_drawdown_replay_spread",
    "compute_drawdown_replay_score",
    "compute_stu0048_drawdown_family_trace",
    "drawdown_replay_components",
    "drawdown_replay_configurations",
    "drawdown_replay_executable",
    "drawdown_replay_executable_map",
    "drawdown_replay_implementation_sha256",
    "drawdown_replay_producer_implementation_identities",
    "drawdown_replay_protocol_definition",
    "expected_drawdown_replay_inventory",
]
