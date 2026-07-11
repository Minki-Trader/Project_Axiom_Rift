"""Causal fixed-lot discovery for the registered US100 M5 trend surface.

The production entry point accepts only the quarantine-safe Foundation data
object.  It never reads or writes control state.  Every trade-rule contrast in
the evaluation belongs to one of the twelve returned Executable identities.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import ceil, sqrt
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import scipy
from scipy.stats import beta

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec, canonical_digest
from axiom_rift.research.data import ObservedDevelopmentData, load_observed_development
from axiom_rift.research import data as data_module


OBSERVED_MATERIAL_ID = (
    "36caaaeef95d4bfeac4e3df7b2108702a4e64632c94e88d46528ac0cccbd2065"
)
DATASET_SHA256 = (
    "fb02fe8754b8b9643a346982367813238d11475ca39de46f1cd8d4d0e33a2aa5"
)
ROLLING_SPLIT_SHA256 = (
    "21830ac109c810cf2b463106127090d586d90de96472c3d043990246d75aa606"
)
SOURCE_ROW_COUNT = 571_771
DEVELOPMENT_ROW_COUNT = 560_552
QUARANTINED_ROW_COUNT = 11_219
DEVELOPMENT_FIRST_TIME = pd.Timestamp("2018-05-07 01:00:00")
DEVELOPMENT_LAST_TIME = pd.Timestamp("2026-04-30 23:55:00")
EXPECTED_FOLD_IDS = tuple(f"rw_{value:03d}" for value in range(1, 10))

POINT = 0.01
MICROPOINTS_PER_POINT = 1_000_000
SELECTOR_QUANTILE_BP = 8_000
SELECTION_BOOTSTRAP_SAMPLES = 41_999
SELECTION_BLOCK_LENGTHS = (5, 10, 20)
SELECTION_TOTAL_EXPOSURES = 42
SELECTION_SEED = 612_337_279
SELECTION_MONTE_CARLO_CONFIDENCE_PPM = 990_000

_PROFILE_LOOKBACKS = {
    "single_12": (12,),
    "multi_fast": (3, 12),
    "multi_slow": (12, 48),
}
_FIVE_MINUTES_NS = 5 * 60 * 1_000_000_000
_DISCOVERY_FILE = Path(__file__).resolve()


class DiscoveryBoundaryError(ValueError):
    """Raised before unregistered data or semantics can reach evaluation."""


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def discovery_implementation_sha256() -> str:
    return _file_sha256(_DISCOVERY_FILE)


def loader_implementation_sha256() -> str:
    return _file_sha256(Path(data_module.__file__).resolve())


@dataclass(frozen=True, slots=True)
class TrendConfiguration:
    """One exact configuration; aliases never enter scientific identity."""

    profile: str
    signal_sign: int
    holding_bars: int

    def __post_init__(self) -> None:
        if self.profile not in _PROFILE_LOOKBACKS:
            raise ValueError("profile is not registered")
        if self.signal_sign not in {-1, 1}:
            raise ValueError("signal_sign must be -1 or 1")
        if self.holding_bars not in {3, 12}:
            raise ValueError("holding_bars is not registered")

    @property
    def lookbacks(self) -> tuple[int, ...]:
        return _PROFILE_LOOKBACKS[self.profile]

    @property
    def configuration_id(self) -> str:
        sign = "continuation" if self.signal_sign == 1 else "reversal"
        return f"{self.profile}-{sign}-h{self.holding_bars}"

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "direction_policy": "both",
            "holding_bars": self.holding_bars,
            "lookbacks": list(self.lookbacks),
            "signal_sign": self.signal_sign,
            "threshold_quantile_bp": SELECTOR_QUANTILE_BP,
        }


def trend_configurations() -> tuple[TrendConfiguration, ...]:
    return tuple(
        TrendConfiguration(
            profile=profile,
            signal_sign=signal_sign,
            holding_bars=holding_bars,
        )
        for profile in ("single_12", "multi_fast", "multi_slow")
        for signal_sign in (1, -1)
        for holding_bars in (3, 12)
    )


def _implementation(function_name: str) -> str:
    return (
        f"axiom_rift.research.discovery.{function_name}@sha256:"
        f"{discovery_implementation_sha256()}"
    )


def trend_components() -> tuple[ComponentSpec, ...]:
    """Build components whose identities bind the current source bytes."""

    return (
        ComponentSpec(
            display_name="causal normalized price-path score",
            protocol="feature.normalized_price_path.v2",
            implementation=_implementation("compute_trend_score"),
            spec={
                "availability": "bar_open_plus_5m_after_completed_bar",
                "formula": (
                    "mean completed log close return over declared lookbacks "
                    "divided by trailing one-bar volatility times square root lookback"
                ),
                "realized_volatility_window_bars": 48,
                "realized_volatility_ddof": 1,
                "nonconsecutive_lookback_action": "invalid_until_rewarmed",
                "parameter_fields": ["lookbacks"],
            },
        ),
        ComponentSpec(
            display_name="fold isolated absolute score selector",
            protocol="selector.fold_train_abs_quantile.v2",
            implementation=_implementation("calibrate_selector"),
            spec={
                "calibration_role": "train_is_only",
                "decision_rule": "absolute_score_at_least_threshold",
                "minimum_train_observations": 1000,
                "quantile_basis_points": SELECTOR_QUANTILE_BP,
                "quantile_method": "higher",
            },
        ),
        ComponentSpec(
            display_name="completed-bar next-open directional entry",
            protocol="trade.completed_bar_next_open_direction.v2",
            implementation=_implementation("simulate_fixed_hold"),
            spec={
                "bar_timestamp_semantics": "bar_open",
                "decision_time": "bar_open_plus_5m",
                "entry_time": "decision_time_at_next_exact_bar_open",
                "direction": "signal_sign_times_score_sign",
                "direction_policy": "both",
                "order_type": "market",
                "parameter_fields": ["signal_sign"],
            },
        ),
        ComponentSpec(
            display_name="fixed-hold nonoverlap lifecycle",
            protocol="lifecycle.fixed_hold_no_overlap.v2",
            implementation=_implementation("simulate_fixed_hold"),
            spec={
                "entry_overlap": "reject_while_position_slot_is_occupied",
                "exit_surface": "exact_bar_open_after_holding_bars",
                "gap_action": "exclude_path",
                "unknown_cost_action": "reserve_position_slot_and_mark_not_evaluable",
                "parameter_fields": ["holding_bars"],
            },
        ),
        ComponentSpec(
            display_name="FPMarkets bid-bar spread execution",
            protocol="execution.fpmarkets_bid_bar_spread.v2",
            implementation=_implementation("execution_pnl"),
            spec={
                "bar_quote_basis": "bid_ohlc_with_spread_points",
                "point": "0.01",
                "long_entry": "ask",
                "long_exit": "bid",
                "short_entry": "bid",
                "short_exit": "ask",
                "zero_spread_lag_bars": 1,
                "zero_spread_positive_window_bars": 288,
                "zero_spread_minimum_positive_observations": 24,
                "zero_spread_gap_action": "reset_history",
                "stress": "half_effective_spread_each_side",
            },
        ),
        ComponentSpec(
            display_name="fixed one-lot single-sleeve risk",
            protocol="risk.fixed_one_lot.v1",
            implementation=_implementation("simulate_fixed_hold"),
            spec={
                "dynamic_sizing": False,
                "lot": 1,
                "positions_per_sleeve": 1,
            },
        ),
    )


def trend_executable(configuration: TrendConfiguration) -> ExecutableSpec:
    discovery_hash = discovery_implementation_sha256()
    loader_hash = loader_implementation_sha256()
    return ExecutableSpec(
        display_name=f"trend contrast {configuration.configuration_id}",
        components=trend_components(),
        parameters=configuration.semantic_parameters(),
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:"
            "rolling_windows_9_observed_development"
        ),
        clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v2",
        cost_contract=(
            "cost:bid_bar_spread_point_0_01_zero_lag1_positive_median_"
            "window288_min24_gap_reset_half_spread_stress_v2"
        ),
        engine_contract=(
            "engine:trend_discovery_v2:python3_13_9:numpy2_3_4:pandas2_3_3:"
            f"scipy1_16_3:discovery_sha256_{discovery_hash}:"
            f"loader_sha256_{loader_hash}:selector_higher:regime_higher:"
            f"bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:"
            f"mc_upper_{SELECTION_MONTE_CARLO_CONFIDENCE_PPM}:"
            f"bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}"
        ),
    )


def executable_configuration_map() -> dict[str, TrendConfiguration]:
    return {
        trend_executable(configuration).identity: configuration
        for configuration in trend_configurations()
    }


def _time_ns(frame: pd.DataFrame) -> np.ndarray:
    return (
        pd.to_datetime(frame["time"], errors="raise")
        .to_numpy(dtype="datetime64[ns]")
        .astype("int64")
    )


def _consecutive_run(time_ns: np.ndarray) -> np.ndarray:
    run = np.ones(len(time_ns), dtype=np.int32)
    for index in range(1, len(time_ns)):
        run[index] = (
            run[index - 1] + 1
            if time_ns[index] - time_ns[index - 1] == _FIVE_MINUTES_NS
            else 1
        )
    return run


def compute_trend_score(
    frame: pd.DataFrame,
    lookbacks: Sequence[int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return completed-bar score, trailing volatility, and M5 run length."""

    normalized_lookbacks = tuple(lookbacks)
    if (
        not normalized_lookbacks
        or tuple(sorted(set(normalized_lookbacks))) != normalized_lookbacks
        or any(type(value) is not int or value <= 0 for value in normalized_lookbacks)
    ):
        raise ValueError("lookbacks must be sorted unique positive integers")
    close = pd.to_numeric(frame["close"], errors="raise").to_numpy(dtype=float)
    if np.any(~np.isfinite(close)) or np.any(close <= 0):
        raise ValueError("close must be finite and positive")
    run = _consecutive_run(_time_ns(frame))
    log_close = np.log(close)
    one_bar = np.full(len(close), np.nan)
    one_bar[1:] = np.diff(log_close)
    volatility = (
        pd.Series(one_bar)
        .rolling(48, min_periods=48)
        .std(ddof=1)
        .to_numpy(dtype=float)
    )
    pieces: list[np.ndarray] = []
    for lookback in normalized_lookbacks:
        cumulative = np.full(len(close), np.nan)
        cumulative[lookback:] = log_close[lookback:] - log_close[:-lookback]
        value = cumulative / (volatility * sqrt(lookback))
        value[run < max(49, lookback + 1)] = np.nan
        pieces.append(value)
    matrix = np.column_stack(pieces)
    finite = np.isfinite(matrix)
    count = finite.sum(axis=1)
    score = np.divide(
        np.where(finite, matrix, 0.0).sum(axis=1),
        count,
        out=np.full(len(frame), np.nan),
        where=count > 0,
    )
    return score, volatility, run


def calibrate_selector(
    score: np.ndarray,
    train_mask: np.ndarray,
) -> float:
    values = np.abs(score[train_mask & np.isfinite(score)])
    if len(values) < 1000:
        raise ValueError("selector calibration has fewer than 1000 observations")
    return float(
        np.quantile(
            values,
            SELECTOR_QUANTILE_BP / 10_000,
            method="higher",
        )
    )


def causal_effective_spread(
    spread: Sequence[float],
    time_ns: Sequence[int],
) -> np.ndarray:
    """Use observed positive spread or a gap-reset lagged positive median."""

    values = np.asarray(spread, dtype=float)
    times = np.asarray(time_ns, dtype=np.int64)
    if len(values) != len(times):
        raise ValueError("spread and time lengths differ")
    if np.any(~np.isfinite(values)) or np.any(values < 0):
        raise ValueError("spread must be finite and nonnegative")
    segment = np.zeros(len(times), dtype=np.int64)
    if len(times) > 1:
        segment[1:] = np.cumsum(np.diff(times) != _FIVE_MINUTES_NS)
    positive = pd.Series(np.where(values > 0, values, np.nan))
    groups = pd.Series(segment)
    lagged = positive.groupby(groups, sort=False).transform(
        lambda part: part.shift(1).rolling(288, min_periods=24).median()
    )
    return np.where(values > 0, values, lagged.to_numpy(dtype=float))


def execution_pnl(
    *,
    direction: int,
    entry_bid: float,
    exit_bid: float,
    entry_spread_points: float,
    exit_spread_points: float,
) -> tuple[float, float]:
    if direction == 1:
        native = exit_bid - (entry_bid + entry_spread_points * POINT)
    elif direction == -1:
        native = entry_bid - (exit_bid + exit_spread_points * POINT)
    else:
        raise ValueError("direction must be -1 or 1")
    stress = native - 0.5 * (
        entry_spread_points + exit_spread_points
    ) * POINT
    return native, stress


@dataclass(slots=True)
class SimulationResult:
    trades: pd.DataFrame
    intent_rows: tuple[tuple[Any, ...], ...]
    unresolved_cost_signal_count: int
    gap_excluded_signal_count: int
    causality_violation_count: int


def simulate_fixed_hold(
    *,
    frame: pd.DataFrame,
    score: np.ndarray,
    volatility: np.ndarray,
    run: np.ndarray,
    threshold: float,
    configuration: TrendConfiguration,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    fold_id: str,
    regime_cutoffs: tuple[float, float],
    effective_spread: np.ndarray | None = None,
) -> SimulationResult:
    """Run one exact registered configuration sequentially."""

    time = pd.to_datetime(frame["time"], errors="raise")
    time_ns = _time_ns(frame)
    opens = pd.to_numeric(frame["open"], errors="raise").to_numpy(dtype=float)
    spreads = (
        causal_effective_spread(
            pd.to_numeric(frame["spread"], errors="raise").to_numpy(dtype=float),
            time_ns,
        )
        if effective_spread is None
        else np.asarray(effective_spread, dtype=float)
    )
    if len(spreads) != len(frame):
        raise ValueError("effective spread length differs from frame")
    candidates = np.flatnonzero(
        ((time >= test_start) & (time <= test_end)).to_numpy()
        & np.isfinite(score)
    )
    records: list[dict[str, Any]] = []
    intents: list[tuple[Any, ...]] = []
    next_decision_index = -1
    unresolved = 0
    gap_excluded = 0
    causality_violations = 0
    for decision_index in candidates:
        if decision_index < next_decision_index:
            continue
        if abs(score[decision_index]) < threshold:
            continue
        direction = int(np.sign(score[decision_index])) * configuration.signal_sign
        if direction == 0:
            continue
        entry_index = decision_index + 1
        exit_index = entry_index + configuration.holding_bars
        if exit_index >= len(frame) or time.iloc[exit_index] > test_end:
            continue
        decision_bar_open_time = time.iloc[decision_index]
        decision_time = decision_bar_open_time + pd.Timedelta(minutes=5)
        entry_time = time.iloc[entry_index]
        exit_time = time.iloc[exit_index]
        if (
            time_ns[entry_index] - time_ns[decision_index] != _FIVE_MINUTES_NS
            or run[exit_index] < configuration.holding_bars + 2
        ):
            gap_excluded += 1
            intents.append(
                (decision_time, entry_time, exit_time, direction, "gap_excluded")
            )
            continue
        if decision_time != entry_time:
            causality_violations += 1
            intents.append(
                (
                    decision_time,
                    entry_time,
                    exit_time,
                    direction,
                    "causality_violation",
                )
            )
            continue
        next_decision_index = exit_index
        if not (
            np.isfinite(spreads[entry_index])
            and np.isfinite(spreads[exit_index])
        ):
            unresolved += 1
            intents.append(
                (decision_time, entry_time, exit_time, direction, "unknown_cost")
            )
            continue
        native, stress = execution_pnl(
            direction=direction,
            entry_bid=float(opens[entry_index]),
            exit_bid=float(opens[exit_index]),
            entry_spread_points=float(spreads[entry_index]),
            exit_spread_points=float(spreads[exit_index]),
        )
        entry_volatility = float(volatility[decision_index])
        regime = (
            "low"
            if entry_volatility <= regime_cutoffs[0]
            else "high"
            if entry_volatility >= regime_cutoffs[1]
            else "middle"
        )
        records.append(
            {
                "decision_bar_open_time": decision_bar_open_time,
                "decision_time": decision_time,
                "entry_time": entry_time,
                "exit_time": exit_time,
                "direction": direction,
                "pnl": native,
                "stress_pnl": stress,
                "fold_id": fold_id,
                "regime": regime,
            }
        )
        intents.append((decision_time, entry_time, exit_time, direction, "executed"))
    trades = pd.DataFrame.from_records(records)
    if trades.empty:
        trades = pd.DataFrame(
            columns=(
                "decision_bar_open_time",
                "decision_time",
                "entry_time",
                "exit_time",
                "direction",
                "pnl",
                "stress_pnl",
                "fold_id",
                "regime",
            )
        )
    return SimulationResult(
        trades=trades,
        intent_rows=tuple(intents),
        unresolved_cost_signal_count=unresolved,
        gap_excluded_signal_count=gap_excluded,
        causality_violation_count=causality_violations,
    )


def _window_payload(window: Any) -> dict[str, Any]:
    return {
        "start": pd.Timestamp(window.start),
        "end": pd.Timestamp(window.end),
        "row_count": int(window.row_count),
    }


def _fold_payloads(data: ObservedDevelopmentData) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "fold_id": fold.fold_id,
            "train_is": _window_payload(fold.train_is),
            "validation_oos": _window_payload(fold.validation_oos),
            "test_oos": _window_payload(fold.test_oos),
        }
        for fold in data.metadata.folds
    )


def _validate_production_data(data: ObservedDevelopmentData) -> None:
    if not isinstance(data, ObservedDevelopmentData):
        raise DiscoveryBoundaryError(
            "production discovery requires ObservedDevelopmentData"
        )
    metadata = data.metadata
    expected = {
        "material_identity": OBSERVED_MATERIAL_ID,
        "dataset_sha256": DATASET_SHA256,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "source_row_count": SOURCE_ROW_COUNT,
        "development_row_count": DEVELOPMENT_ROW_COUNT,
        "quarantined_row_count": QUARANTINED_ROW_COUNT,
        "first_time": DEVELOPMENT_FIRST_TIME,
        "last_development_time": DEVELOPMENT_LAST_TIME,
        "fields": (
            "time",
            "open",
            "high",
            "low",
            "close",
            "tick_volume",
            "spread",
        ),
    }
    for name, value in expected.items():
        if getattr(metadata, name) != value:
            raise DiscoveryBoundaryError(f"production {name} differs from Foundation")
    if tuple(fold.fold_id for fold in metadata.folds) != EXPECTED_FOLD_IDS:
        raise DiscoveryBoundaryError("production rolling-fold identities differ")
    if len(data.frame) != DEVELOPMENT_ROW_COUNT:
        raise DiscoveryBoundaryError("production frame row count differs")


def _validate_engine_environment() -> None:
    observed = {
        "python": ".".join(str(value) for value in sys.version_info[:3]),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
    }
    expected = {
        "python": "3.13.9",
        "numpy": "2.3.4",
        "pandas": "2.3.3",
        "scipy": "1.16.3",
    }
    if observed != expected:
        raise DiscoveryBoundaryError("production engine environment differs")


def _validate_fold_payloads(
    frame: pd.DataFrame,
    folds: Sequence[Mapping[str, Any]],
) -> None:
    if len(folds) != 9:
        raise DiscoveryBoundaryError("production evaluation requires nine folds")
    time = pd.to_datetime(frame["time"], errors="raise")
    previous_test_end: pd.Timestamp | None = None
    seen: set[str] = set()
    for index, fold in enumerate(folds):
        fold_id = str(fold["fold_id"])
        if fold_id != EXPECTED_FOLD_IDS[index] or fold_id in seen:
            raise DiscoveryBoundaryError("rolling-fold order or identity differs")
        seen.add(fold_id)
        windows = [fold[role] for role in ("train_is", "validation_oos", "test_oos")]
        for window in windows:
            start = pd.Timestamp(window["start"])
            end = pd.Timestamp(window["end"])
            observed = int(((time >= start) & (time <= end)).sum())
            if start > end or observed != int(window["row_count"]):
                raise DiscoveryBoundaryError("rolling-fold boundary or row count differs")
        train, validation, test = windows
        if not (
            pd.Timestamp(train["end"]) < pd.Timestamp(validation["start"])
            and pd.Timestamp(validation["end"]) < pd.Timestamp(test["start"])
        ):
            raise DiscoveryBoundaryError("rolling-fold roles overlap")
        test_start = pd.Timestamp(test["start"])
        test_end = pd.Timestamp(test["end"])
        if previous_test_end is not None and test_start <= previous_test_end:
            raise DiscoveryBoundaryError("rolling test windows overlap")
        previous_test_end = test_end


def _profit_factor(values: np.ndarray) -> int:
    gain = float(values[values > 0].sum())
    loss = float(-values[values < 0].sum())
    if loss <= 0:
        return 1_000_000 if gain > 0 else 0
    return min(1_000_000, int(round(1000 * gain / loss)))


def _micropoints(value: float) -> int:
    return int(round(value * MICROPOINTS_PER_POINT))


def _daily_series(
    trades: pd.DataFrame,
    eligible_days: pd.DatetimeIndex,
    column: str,
) -> pd.Series:
    if trades.empty:
        return pd.Series(0.0, index=eligible_days)
    grouped = (
        trades.assign(day=pd.to_datetime(trades["decision_time"]).dt.normalize())
        .groupby("day", sort=True)[column]
        .sum()
    )
    return grouped.reindex(eligible_days, fill_value=0.0).astype(float)


def _monthly_realized_exit_drawdown(trades: pd.DataFrame) -> tuple[float, int]:
    if trades.empty:
        return 0.0, 0
    ordered = trades.sort_values("exit_time").copy()
    ordered["month"] = pd.to_datetime(ordered["exit_time"]).dt.to_period("M")
    worst = 0.0
    worst_share = 0
    for _, values in ordered.groupby("month", sort=True):
        pnl = values["pnl"].to_numpy(dtype=float)
        equity = np.concatenate(([0.0], pnl.cumsum()))
        drawdown = float(
            (np.maximum.accumulate(equity) - equity).max(initial=0.0)
        )
        gross_profit = float(pnl[pnl > 0].sum())
        share = (
            0
            if drawdown <= 0
            else 1_000_000_000
            if gross_profit <= 0
            else min(
                1_000_000_000,
                int(ceil(1_000_000 * drawdown / gross_profit)),
            )
        )
        worst = max(worst, drawdown)
        worst_share = max(worst_share, share)
    return worst, worst_share


def _trade_identity_rows(trades: pd.DataFrame) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        tuple(row)
        for row in trades.loc[
            :,
            ("decision_time", "entry_time", "exit_time", "direction"),
        ].itertuples(index=False, name=None)
    )


@dataclass(slots=True)
class _ConfigurationResult:
    configuration: TrendConfiguration
    executable_id: str
    metrics: dict[str, int]
    fold_metrics: list[dict[str, int | str]]
    regime_metrics: list[dict[str, int | str]]
    session_metrics: list[dict[str, int | str]]
    direction_metrics: list[dict[str, int | str]]
    daily_pnl: pd.Series


def _evaluate_configuration(
    *,
    frame: pd.DataFrame,
    folds: Sequence[Mapping[str, Any]],
    configuration: TrendConfiguration,
    effective_spread: np.ndarray,
    features: tuple[np.ndarray, np.ndarray, np.ndarray],
    prefix_features: Mapping[
        str, tuple[np.ndarray, np.ndarray, np.ndarray]
    ],
    prefix_spreads: Mapping[str, np.ndarray],
    calibrations: Mapping[
        str, tuple[float, tuple[float, float], float]
    ],
    time: pd.Series,
) -> _ConfigurationResult:
    score, volatility, run = features
    simulations: list[SimulationResult] = []
    fold_metrics: list[dict[str, int | str]] = []
    eligible_parts: list[pd.DatetimeIndex] = []
    append_mismatches = 0
    prefix_mismatches = 0
    for fold in folds:
        test = fold["test_oos"]
        fold_id = str(fold["fold_id"])
        threshold, cutoffs, prefix_threshold = calibrations[fold_id]
        simulation = simulate_fixed_hold(
            frame=frame,
            score=score,
            volatility=volatility,
            run=run,
            threshold=threshold,
            configuration=configuration,
            test_start=pd.Timestamp(test["start"]),
            test_end=pd.Timestamp(test["end"]),
            fold_id=fold_id,
            regime_cutoffs=cutoffs,
            effective_spread=effective_spread,
        )
        simulations.append(simulation)
        values = simulation.trades["pnl"].to_numpy(dtype=float)
        fold_metrics.append(
            {
                "fold_id": fold_id,
                "net_profit_micropoints": _micropoints(float(values.sum())),
                "profit_factor_milli": _profit_factor(values),
                "stress_net_profit_micropoints": _micropoints(
                    float(simulation.trades["stress_pnl"].sum())
                ),
                "trade_count": int(len(simulation.trades)),
                "unresolved_cost_signal_count": (
                    simulation.unresolved_cost_signal_count
                ),
            }
        )
        eligible_parts.append(
            pd.DatetimeIndex(
                time[
                    (time >= pd.Timestamp(test["start"]))
                    & (time <= pd.Timestamp(test["end"]))
                ]
            )
            .normalize()
            .unique()
        )
        prefix_end = int(time.searchsorted(pd.Timestamp(test["end"]), side="right"))
        prefix_frame = frame.iloc[:prefix_end]
        prefix_score, prefix_volatility, prefix_run = prefix_features[fold_id]
        prefix_mismatches += int(
            (~np.isclose(
                prefix_score,
                score[:prefix_end],
                rtol=0.0,
                atol=0.0,
                equal_nan=True,
            )).sum()
        )
        prefix_simulation = simulate_fixed_hold(
            frame=prefix_frame,
            score=prefix_score,
            volatility=prefix_volatility,
            run=prefix_run,
            threshold=prefix_threshold,
            configuration=configuration,
            test_start=pd.Timestamp(test["start"]),
            test_end=pd.Timestamp(test["end"]),
            fold_id=fold_id,
            regime_cutoffs=cutoffs,
            effective_spread=prefix_spreads[fold_id],
        )
        left = simulation.intent_rows
        right = prefix_simulation.intent_rows
        append_mismatches += abs(len(left) - len(right)) + sum(
            left_item != right_item
            for left_item, right_item in zip(left, right, strict=False)
        )
    trades = pd.concat([item.trades for item in simulations], ignore_index=True)
    eligible_days = pd.DatetimeIndex(
        sorted(set().union(*(set(value) for value in eligible_parts)))
    )
    daily_pnl = _daily_series(trades, eligible_days, "pnl")
    daily_entries = (
        pd.Series(0, index=eligible_days, dtype=int)
        if trades.empty
        else (
            trades.assign(
                day=pd.to_datetime(trades["decision_time"]).dt.normalize()
            )
            .groupby("day", sort=True)
            .size()
            .reindex(eligible_days, fill_value=0)
            .astype(int)
        )
    )
    net = float(trades["pnl"].sum()) if not trades.empty else 0.0
    stress = float(trades["stress_pnl"].sum()) if not trades.empty else 0.0
    realized_drawdown, realized_drawdown_share = (
        _monthly_realized_exit_drawdown(trades)
    )
    positive_daily = daily_pnl[daily_pnl > 0].sort_values(ascending=False)
    gross_positive = float(positive_daily.sum())
    top5_share = (
        0
        if gross_positive <= 0
        else min(
            1_000_000,
            int(
                round(
                    1_000_000
                    * float(positive_daily.head(5).sum())
                    / gross_positive
                )
            ),
        )
    )
    regime_metrics: list[dict[str, int | str]] = []
    for regime in ("low", "middle", "high"):
        selected = trades[trades["regime"] == regime]
        by_fold = (
            selected.groupby("fold_id", sort=True)["pnl"].sum()
            if not selected.empty
            else pd.Series(dtype=float)
        )
        regime_metrics.append(
            {
                "evaluable_fold_count": int(len(by_fold)),
                "regime": regime,
                "net_profit_micropoints": _micropoints(
                    float(selected["pnl"].sum())
                ),
                "trade_count": int(len(selected)),
                "winning_fold_count": int((by_fold > 0).sum()),
            }
        )
    hours = (
        pd.to_datetime(trades["entry_time"]).dt.hour
        if not trades.empty
        else pd.Series(dtype=int)
    )
    labels = (
        pd.Series(
            np.select(
                [
                    hours.between(1, 7),
                    hours.between(8, 14),
                    hours.between(15, 22),
                ],
                ["broker_01_07", "broker_08_14", "broker_15_22"],
                default="broker_23_00",
            ),
            index=trades.index,
        )
        if not trades.empty
        else pd.Series(dtype=object)
    )
    session_metrics: list[dict[str, int | str]] = []
    for session in (
        "broker_01_07",
        "broker_08_14",
        "broker_15_22",
        "broker_23_00",
    ):
        selected = trades[labels == session] if not trades.empty else trades
        session_metrics.append(
            {
                "session": session,
                "net_profit_micropoints": _micropoints(
                    float(selected["pnl"].sum())
                ),
                "trade_count": int(len(selected)),
            }
        )
    direction_metrics: list[dict[str, int | str]] = []
    for direction, name in ((1, "long"), (-1, "short")):
        selected = trades[trades["direction"] == direction]
        direction_metrics.append(
            {
                "direction": name,
                "net_profit_micropoints": _micropoints(
                    float(selected["pnl"].sum())
                ),
                "trade_count": int(len(selected)),
            }
        )
    fold_profit_factors = sorted(
        int(item["profit_factor_milli"]) for item in fold_metrics
    )
    unresolved = sum(item.unresolved_cost_signal_count for item in simulations)
    causality = sum(item.causality_violation_count for item in simulations)
    gap_excluded = sum(item.gap_excluded_signal_count for item in simulations)
    metrics = {
        "append_invariance_mismatch_count": append_mismatches,
        "causality_violation_count": causality,
        "daily_entries_max_milli": (
            0 if daily_entries.empty else int(daily_entries.max()) * 1000
        ),
        "daily_entries_median_milli": (
            0
            if daily_entries.empty
            else int(round(1000 * float(daily_entries.median())))
        ),
        "daily_entries_p10_milli": (
            0
            if daily_entries.empty
            else int(
                round(1000 * float(np.quantile(daily_entries, 0.10, method="lower")))
            )
        ),
        "daily_entries_p90_milli": (
            0
            if daily_entries.empty
            else int(
                round(1000 * float(np.quantile(daily_entries, 0.90, method="higher")))
            )
        ),
        "eligible_day_count": int(len(eligible_days)),
        "entries_per_day_milli": (
            0
            if not len(eligible_days)
            else int(round(1000 * len(trades) / len(eligible_days)))
        ),
        "evaluable_folds": sum(int(item["trade_count"]) > 0 for item in fold_metrics),
        "gap_excluded_signal_count": gap_excluded,
        "median_fold_profit_factor_milli": (
            fold_profit_factors[len(fold_profit_factors) // 2]
            if fold_profit_factors
            else 0
        ),
        "monthly_realized_exit_drawdown_micropoints": _micropoints(
            realized_drawdown
        ),
        "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": (
            realized_drawdown_share
        ),
        "net_profit_micropoints": _micropoints(net),
        "nonfinite_metric_count": 0,
        "positive_regime_count": sum(
            int(item["net_profit_micropoints"]) > 0 for item in regime_metrics
        ),
        "prefix_invariance_mismatch_count": prefix_mismatches,
        "selection_aware_pvalue_ppm": 1_000_000,
        "stress_net_profit_micropoints": _micropoints(stress),
        "supported_positive_regime_count": sum(
            int(item["net_profit_micropoints"]) > 0
            and int(item["trade_count"]) >= 30
            and int(item["evaluable_fold_count"]) >= 5
            and int(item["winning_fold_count"]) >= 3
            and 2 * int(item["winning_fold_count"])
            > int(item["evaluable_fold_count"])
            for item in regime_metrics
        ),
        "top5_profit_day_share_ppm": top5_share,
        "trade_count": int(len(trades)),
        "unknown_cost_unresolved_signal_count": unresolved,
        "winning_fold_count": sum(
            int(item["net_profit_micropoints"]) > 0 for item in fold_metrics
        ),
        "zero_entry_day_rate_ppm": (
            0
            if daily_entries.empty
            else int(
                round(
                    1_000_000
                    * int((daily_entries == 0).sum())
                    / len(daily_entries)
                )
            )
        ),
    }
    return _ConfigurationResult(
        configuration=configuration,
        executable_id=trend_executable(configuration).identity,
        metrics=metrics,
        fold_metrics=fold_metrics,
        regime_metrics=regime_metrics,
        session_metrics=session_metrics,
        direction_metrics=direction_metrics,
        daily_pnl=daily_pnl,
    )


def _overlapping_block_sums(values: np.ndarray, length: int) -> np.ndarray:
    cumulative = np.concatenate(([0.0], np.cumsum(values, dtype=float)))
    return cumulative[length:] - cumulative[:-length]


def _adjusted_bootstrap_upper_pvalue(
    values: np.ndarray,
    *,
    seed_label: str,
) -> int:
    """Return the worst 99% MC-upper p-value across registered block lengths."""

    if type(seed_label) is not str or not seed_label or not seed_label.isascii():
        raise ValueError("bootstrap seed label must be non-empty ASCII")
    sample = np.asarray(values, dtype=float)
    if len(sample) < 30 or np.any(~np.isfinite(sample)):
        raise DiscoveryBoundaryError("bootstrap series is invalid or too short")
    standard = float(sample.std(ddof=1))
    if standard <= 0 or float(sample.mean()) <= 0:
        return 1_000_000
    observed = float(sample.mean() * sqrt(len(sample)) / standard)
    centered = sample - sample.mean()
    centered_square = centered * centered
    confidence = SELECTION_MONTE_CARLO_CONFIDENCE_PPM / 1_000_000
    worst_adjusted = 0.0
    for block_length in SELECTION_BLOCK_LENGTHS:
        seed_bytes = sha256(
            f"{SELECTION_SEED}:{seed_label}:{block_length}".encode("ascii")
        ).digest()
        rng = np.random.default_rng(int.from_bytes(seed_bytes[:8], "big"))
        full_count, remainder = divmod(len(centered), block_length)
        full_sums = _overlapping_block_sums(centered, block_length)
        full_squares = _overlapping_block_sums(centered_square, block_length)
        partial_sums = (
            None if remainder == 0 else _overlapping_block_sums(centered, remainder)
        )
        partial_squares = (
            None
            if remainder == 0
            else _overlapping_block_sums(centered_square, remainder)
        )
        exceedances = 0
        generated = 0
        while generated < SELECTION_BOOTSTRAP_SAMPLES:
            count = min(256, SELECTION_BOOTSTRAP_SAMPLES - generated)
            starts = rng.integers(
                0,
                len(full_sums),
                size=(count, full_count),
            )
            draw_sum = full_sums[starts].sum(axis=1)
            draw_square = full_squares[starts].sum(axis=1)
            if partial_sums is not None and partial_squares is not None:
                partial_starts = rng.integers(0, len(partial_sums), size=count)
                draw_sum += partial_sums[partial_starts]
                draw_square += partial_squares[partial_starts]
            draw_variance = np.maximum(
                0.0,
                (
                    draw_square
                    - (draw_sum * draw_sum) / len(centered)
                )
                / (len(centered) - 1),
            )
            statistics = np.divide(
                (draw_sum / len(centered)) * sqrt(len(centered)),
                np.sqrt(draw_variance),
                out=np.zeros(count, dtype=float),
                where=draw_variance > 0,
            )
            exceedances += int((statistics >= observed).sum())
            generated += count
        point_pvalue = (1 + exceedances) / (
            SELECTION_BOOTSTRAP_SAMPLES + 1
        )
        monte_carlo_upper = (
            1.0
            if exceedances >= SELECTION_BOOTSTRAP_SAMPLES
            else float(
                beta.ppf(
                    confidence,
                    exceedances + 1,
                    SELECTION_BOOTSTRAP_SAMPLES - exceedances,
                )
            )
        )
        worst_adjusted = max(
            worst_adjusted,
            min(
                1.0,
                max(point_pvalue, monte_carlo_upper)
                * SELECTION_TOTAL_EXPOSURES,
            ),
        )
    return min(1_000_000, int(ceil(1_000_000 * worst_adjusted)))


def _selection_adjusted_pvalues(
    results: Sequence[_ConfigurationResult],
) -> dict[str, int]:
    days = pd.DatetimeIndex(
        sorted(set().union(*(set(result.daily_pnl.index) for result in results)))
    )
    if len(days) < 30:
        raise DiscoveryBoundaryError("selection context has fewer than 30 days")
    return {
        result.executable_id: _adjusted_bootstrap_upper_pvalue(
            result.daily_pnl.reindex(days, fill_value=0.0).to_numpy(dtype=float),
            seed_label=f"selection:{result.executable_id}",
        )
        for result in results
    }


def _paired_control_pvalue(
    subject: _ConfigurationResult,
    control: _ConfigurationResult,
    *,
    role: str,
) -> int:
    if not subject.daily_pnl.index.equals(control.daily_pnl.index):
        raise DiscoveryBoundaryError("paired controls have different eligible days")
    difference = (
        subject.daily_pnl.to_numpy(dtype=float)
        - control.daily_pnl.to_numpy(dtype=float)
    )
    return _adjusted_bootstrap_upper_pvalue(
        difference,
        seed_label=(
            f"control:{role}:{subject.executable_id}:{control.executable_id}"
        ),
    )


def _matched_result(
    results: Sequence[_ConfigurationResult],
    *,
    profile: str,
    signal_sign: int,
    holding_bars: int,
) -> _ConfigurationResult:
    matches = [
        result
        for result in results
        if result.configuration.profile == profile
        and result.configuration.signal_sign == signal_sign
        and result.configuration.holding_bars == holding_bars
    ]
    if len(matches) != 1:
        raise DiscoveryBoundaryError("registered contrast match is not unique")
    return matches[0]


def _selection_method() -> dict[str, Any]:
    return {
        "bootstrap_samples": SELECTION_BOOTSTRAP_SAMPLES,
        "block_days": list(SELECTION_BLOCK_LENGTHS),
        "method": (
            "centered_non_circular_moving_block_studentized_one_sided_"
            "then_bonferroni"
        ),
        "monte_carlo_upper_confidence_ppm": (
            SELECTION_MONTE_CARLO_CONFIDENCE_PPM
        ),
        "multiple_block_rule": "maximum_adjusted_pvalue",
        "paired_control_rule": (
            "same_eligible_decision_day_intersection_union_worst_control"
        ),
        "seed": SELECTION_SEED,
        "seed_derivation": "sha256_base_seed_label_block_length_first_u64",
        "total_exposures": SELECTION_TOTAL_EXPOSURES,
    }


def _claim_limits() -> list[str]:
    return [
        "discovery_only",
        "daily_pnl_is_attributed_to_decision_day",
        "monthly_drawdown_is_exit_realized_not_mark_to_market",
        "monthly_drawdown_share_gate_is_for_dense_trend_surfaces_only",
        "regime_support_requires_30_trades_5_folds_3_winning_folds",
        "regime_support_requires_strict_majority_winning_evaluable_folds",
        "session_bins_are_broker_clock_descriptions_only",
        "controls_are_registered_executables_in_the_same_batch",
    ]


def _populate_registered_control_metrics(
    results: Sequence[_ConfigurationResult],
) -> None:
    for subject in results:
        opposite = _matched_result(
            results,
            profile=subject.configuration.profile,
            signal_sign=-subject.configuration.signal_sign,
            holding_bars=subject.configuration.holding_bars,
        )
        if subject.configuration.profile == "single_12":
            feature_controls = [
                _matched_result(
                    results,
                    profile=profile,
                    signal_sign=subject.configuration.signal_sign,
                    holding_bars=subject.configuration.holding_bars,
                )
                for profile in ("multi_fast", "multi_slow")
            ]
        else:
            feature_controls = [
                _matched_result(
                    results,
                    profile="single_12",
                    signal_sign=subject.configuration.signal_sign,
                    holding_bars=subject.configuration.holding_bars,
                )
            ]
        subject.metrics[
            "opposite_sign_worst_delta_net_profit_micropoints"
        ] = (
            subject.metrics["net_profit_micropoints"]
            - opposite.metrics["net_profit_micropoints"]
        )
        subject.metrics[
            "opposite_sign_pvalue_upper_ppm"
        ] = _paired_control_pvalue(
            subject,
            opposite,
            role="opposite_sign",
        )
        subject.metrics[
            "feature_control_worst_delta_net_profit_micropoints"
        ] = min(
            subject.metrics["net_profit_micropoints"]
            - control.metrics["net_profit_micropoints"]
            for control in feature_controls
        )
        subject.metrics[
            "feature_control_worst_pvalue_upper_ppm"
        ] = max(
            _paired_control_pvalue(subject, control, role="feature")
            for control in feature_controls
        )
        if any(type(value) is not int for value in subject.metrics.values()):
            raise DiscoveryBoundaryError(
                "scientific metrics are not fixed-point integers"
            )


def _compute_registered_trend_surface(
    repository_root: str | Path,
) -> dict[str, Any]:
    """Compute the registered surface behind a writer-gated Job entry."""

    if not isinstance(repository_root, (str, Path)):
        raise DiscoveryBoundaryError("trend surface requires a repository path")
    _validate_engine_environment()
    data = load_observed_development(Path(repository_root).resolve())
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    effective_spread = causal_effective_spread(
        pd.to_numeric(data.frame["spread"], errors="raise").to_numpy(dtype=float),
        _time_ns(data.frame),
    )
    time = pd.to_datetime(data.frame["time"], errors="raise")
    prefix_spreads: dict[str, np.ndarray] = {}
    prefix_frames: dict[str, pd.DataFrame] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        prefix_end = int(
            time.searchsorted(
                pd.Timestamp(fold["test_oos"]["end"]),
                side="right",
            )
        )
        prefix_frame = data.frame.iloc[:prefix_end]
        prefix_frames[fold_id] = prefix_frame
        prefix_spreads[fold_id] = causal_effective_spread(
            pd.to_numeric(prefix_frame["spread"], errors="raise").to_numpy(
                dtype=float
            ),
            _time_ns(prefix_frame),
        )
    feature_cache: dict[
        str, tuple[np.ndarray, np.ndarray, np.ndarray]
    ] = {}
    prefix_feature_cache: dict[
        str, dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]
    ] = {}
    calibration_cache: dict[
        str, dict[str, tuple[float, tuple[float, float], float]]
    ] = {}
    for profile, lookbacks in _PROFILE_LOOKBACKS.items():
        score, volatility, run = compute_trend_score(data.frame, lookbacks)
        feature_cache[profile] = (score, volatility, run)
        prefix_feature_cache[profile] = {}
        calibration_cache[profile] = {}
        for fold in folds:
            fold_id = str(fold["fold_id"])
            train = fold["train_is"]
            train_mask = (
                (time >= pd.Timestamp(train["start"]))
                & (time <= pd.Timestamp(train["end"]))
            ).to_numpy()
            threshold = calibrate_selector(score, train_mask)
            train_volatility = volatility[
                train_mask & np.isfinite(score) & np.isfinite(volatility)
            ]
            if len(train_volatility) < 1000:
                raise DiscoveryBoundaryError("regime calibration is too small")
            cutoffs = (
                float(
                    np.quantile(
                        train_volatility,
                        1 / 3,
                        method="higher",
                    )
                ),
                float(
                    np.quantile(
                        train_volatility,
                        2 / 3,
                        method="higher",
                    )
                ),
            )
            prefix_frame = prefix_frames[fold_id]
            prefix_features = compute_trend_score(prefix_frame, lookbacks)
            prefix_feature_cache[profile][fold_id] = prefix_features
            prefix_time = pd.to_datetime(prefix_frame["time"], errors="raise")
            prefix_train_mask = (
                (prefix_time >= pd.Timestamp(train["start"]))
                & (prefix_time <= pd.Timestamp(train["end"]))
            ).to_numpy()
            prefix_threshold = calibrate_selector(
                prefix_features[0],
                prefix_train_mask,
            )
            calibration_cache[profile][fold_id] = (
                threshold,
                cutoffs,
                prefix_threshold,
            )
    results = [
        _evaluate_configuration(
            calibrations=calibration_cache[configuration.profile],
            frame=data.frame,
            features=feature_cache[configuration.profile],
            folds=folds,
            configuration=configuration,
            effective_spread=effective_spread,
            prefix_features=prefix_feature_cache[configuration.profile],
            prefix_spreads=prefix_spreads,
            time=time,
        )
        for configuration in trend_configurations()
    ]
    pvalues = _selection_adjusted_pvalues(results)
    for result in results:
        result.metrics["selection_aware_pvalue_ppm"] = pvalues[
            result.executable_id
        ]
    _populate_registered_control_metrics(results)
    surface: dict[str, Any] = {
        "claim_limits": _claim_limits(),
        "dataset_sha256": DATASET_SHA256,
        "discovery_implementation_sha256": discovery_implementation_sha256(),
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
                "subject_configuration_id": (
                    result.configuration.configuration_id
                ),
                "subject_executable_id": result.executable_id,
            }
            for result in results
        ],
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "schema": "trend_discovery_surface.v1",
        "selection_context": [
            {
                "configuration_id": result.configuration.configuration_id,
                "executable_id": result.executable_id,
                "net_profit_micropoints": result.metrics[
                    "net_profit_micropoints"
                ],
                "selection_aware_pvalue_ppm": result.metrics[
                    "selection_aware_pvalue_ppm"
                ],
            }
            for result in results
        ],
        "selection_method": _selection_method(),
        "session_semantics": (
            "broker_clock_fixed_bins_no_dst_or_cash_session_claim"
        ),
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
    }
    canonical_bytes(surface)
    return surface


def project_trend_evaluation(
    surface: Mapping[str, Any],
    *,
    job_execution: Mapping[str, str],
    subject_executable_id: str,
    surface_artifact_hash: str,
    surface_manifest_hash: str,
) -> dict[str, Any]:
    """Project one subject without rerunning or expanding scientific work."""

    if (
        type(surface_artifact_hash) is not str
        or len(surface_artifact_hash) != 64
        or any(character not in "0123456789abcdef" for character in surface_artifact_hash)
    ):
        raise DiscoveryBoundaryError("surface artifact hash is invalid")
    if (
        type(surface_manifest_hash) is not str
        or len(surface_manifest_hash) != 64
        or any(character not in "0123456789abcdef" for character in surface_manifest_hash)
    ):
        raise DiscoveryBoundaryError("surface manifest hash is invalid")
    if not isinstance(job_execution, Mapping) or set(job_execution) != {
        "identity",
        "job_hash",
        "job_id",
        "job_permit_id",
        "start_record_id",
    }:
        raise DiscoveryBoundaryError("Job execution binding is invalid")
    execution_payload = {
        name: job_execution[name]
        for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")
    }
    if job_execution["identity"] != canonical_digest(
        domain="running-job-execution",
        payload=execution_payload,
    ):
        raise DiscoveryBoundaryError("Job execution identity is invalid")
    value = dict(surface)
    if sha256(canonical_bytes(value)).hexdigest() != surface_artifact_hash:
        raise DiscoveryBoundaryError("surface bytes differ from their artifact hash")
    expected_fields = {
        "claim_limits",
        "dataset_sha256",
        "discovery_implementation_sha256",
        "engine_environment",
        "evaluations",
        "loader_implementation_sha256",
        "material_identity",
        "schema",
        "selection_context",
        "selection_method",
        "session_semantics",
        "split_artifact_sha256",
    }
    if set(value) != expected_fields or value.get("schema") != (
        "trend_discovery_surface.v1"
    ):
        raise DiscoveryBoundaryError("trend surface schema is invalid")
    if {
        "dataset_sha256": value.get("dataset_sha256"),
        "discovery_implementation_sha256": value.get(
            "discovery_implementation_sha256"
        ),
        "engine_environment": value.get("engine_environment"),
        "loader_implementation_sha256": value.get(
            "loader_implementation_sha256"
        ),
        "material_identity": value.get("material_identity"),
        "split_artifact_sha256": value.get("split_artifact_sha256"),
    } != {
        "dataset_sha256": DATASET_SHA256,
        "discovery_implementation_sha256": discovery_implementation_sha256(),
        "engine_environment": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "python": ".".join(str(item) for item in sys.version_info[:3]),
            "scipy": scipy.__version__,
        },
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
    }:
        raise DiscoveryBoundaryError("trend surface provenance differs")
    evaluations = value.get("evaluations")
    expected = executable_configuration_map()
    if not isinstance(evaluations, list) or len(evaluations) != len(expected):
        raise DiscoveryBoundaryError("trend surface evaluation count is invalid")
    by_identity: dict[str, Mapping[str, Any]] = {}
    for item in evaluations:
        if not isinstance(item, Mapping):
            raise DiscoveryBoundaryError("trend surface evaluation is invalid")
        identity = item.get("subject_executable_id")
        if type(identity) is not str or identity in by_identity:
            raise DiscoveryBoundaryError("trend surface subjects are duplicated")
        by_identity[identity] = item
    if set(by_identity) != set(expected) or subject_executable_id not in expected:
        raise DiscoveryBoundaryError("trend surface subjects differ from registration")
    for identity, configuration in expected.items():
        if by_identity[identity].get("subject_configuration_id") != (
            configuration.configuration_id
        ):
            raise DiscoveryBoundaryError("trend surface configuration binding differs")
    subject = by_identity[subject_executable_id]
    evaluation = {
        **dict(subject),
        "claim_limits": value["claim_limits"],
        "job_execution": dict(job_execution),
        "schema": "trend_discovery_evaluation.v3",
        "selection_context": value["selection_context"],
        "selection_method": value["selection_method"],
        "session_semantics": value["session_semantics"],
        "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(evaluation)
    return evaluation


__all__ = [
    "DATASET_SHA256",
    "DEVELOPMENT_ROW_COUNT",
    "DiscoveryBoundaryError",
    "OBSERVED_MATERIAL_ID",
    "ROLLING_SPLIT_SHA256",
    "SELECTION_BLOCK_LENGTHS",
    "SELECTION_BOOTSTRAP_SAMPLES",
    "SELECTION_MONTE_CARLO_CONFIDENCE_PPM",
    "SELECTION_SEED",
    "SELECTION_TOTAL_EXPOSURES",
    "SELECTOR_QUANTILE_BP",
    "SimulationResult",
    "TrendConfiguration",
    "calibrate_selector",
    "causal_effective_spread",
    "compute_trend_score",
    "discovery_implementation_sha256",
    "executable_configuration_map",
    "execution_pnl",
    "loader_implementation_sha256",
    "project_trend_evaluation",
    "simulate_fixed_hold",
    "trend_components",
    "trend_configurations",
    "trend_executable",
]
