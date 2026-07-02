"""R0004 proxy evidence for compression-breakout continuation."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from axiom_rift.paths import DATA_DIR, PROJECT_ROOT


TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
RUN_DIR = PROJECT_ROOT / "campaigns" / "C0001_regime_response_discovery" / "runs" / "R0004"
BASE_FRAME = DATA_DIR / "processed" / "datasets" / "us100_m5_base_frame.csv"
ROLLING_WINDOWS = DATA_DIR / "processed" / "coverage_audits" / "us100_m5_rolling_windows.csv"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
RUN_MANIFEST_PATH = RUN_DIR / "run_manifest.json"
GATE_REPORT_PATH = RUN_DIR / "gate_report.json"
ARTIFACT_LINEAGE_PATH = RUN_DIR / "artifact_lineage.json"

LOOKBACK_RANGE_BARS = 48
COMPRESSION_BARS = 12
COMPRESSION_RANGE_MULTIPLE = 4.0
BREAKOUT_RANGE_MULTIPLE = 1.0
MIN_BODY_RANGE_FRACTION = 0.45
STOP_ATR_MULTIPLE = 0.8
TARGET_ATR_MULTIPLE = 1.2
MAX_HOLD_BARS = 18
SPREAD_POINT_VALUE = 0.01
STARTING_BALANCE_USD = 500.0
PRICE_DIGITS = 2
MAX_CLOSED_BAR_EVALUATION_GAP_SECONDS = 600


@dataclass(frozen=True)
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    spread_points: float


@dataclass(frozen=True)
class Window:
    fold_id: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Trade:
    fold_id: str
    entry_time: datetime
    exit_time: datetime
    direction: int
    entry_price: float
    exit_price: float
    pnl_points: float
    bars_held: int
    exit_reason: str
    mfe_points: float
    mae_points: float
    spread_points: float


@dataclass(frozen=True)
class ActiveTrade:
    fold_id: str
    entry_index: int
    direction: int
    entry_price: float
    stop_price: float
    target_price: float
    spread_points: float


def run_r0004_proxy(write: bool = True) -> dict[str, object]:
    bars = load_bars(BASE_FRAME)
    windows = load_test_windows(ROLLING_WINDOWS)
    trades = simulate_trades(bars, windows)
    payload = build_proxy_payload(trades, windows)
    if write:
        write_proxy_evidence(payload)
    return payload


def load_bars(path: Path) -> list[Bar]:
    bars: list[Bar] = []
    modeling_start = datetime(2022, 5, 2, 1, 0, 0)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            timestamp = datetime.strptime(row["time"], TIME_FORMAT)
            if timestamp < modeling_start:
                continue
            bars.append(
                Bar(
                    time=timestamp,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    spread_points=float(row.get("spread") or 0.0) * SPREAD_POINT_VALUE,
                )
            )
    return bars


def load_test_windows(path: Path) -> list[Window]:
    windows: list[Window] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row["split"] != "test_oos":
                continue
            windows.append(
                Window(
                    fold_id=row["fold_id"],
                    start=datetime.strptime(row["start"], TIME_FORMAT),
                    end=datetime.strptime(row["end"], TIME_FORMAT),
                )
            )
    return windows


def simulate_trades(bars: list[Bar], windows: list[Window]) -> list[Trade]:
    ranges = [bar.high - bar.low for bar in bars]
    range_average = previous_rolling_average(ranges, LOOKBACK_RANGE_BARS)
    trades: list[Trade] = []
    pending_direction = 0
    pending_average_range = 0.0
    active: ActiveTrade | None = None
    active_bars_held = 0

    for window in windows:
        start_index = first_index_at_or_after(bars, window.start)
        end_index = last_index_at_or_before(bars, window.end)
        index = max(start_index, LOOKBACK_RANGE_BARS, COMPRESSION_BARS)
        while index <= end_index:
            if index > start_index:
                if active is not None:
                    active_bars_held += 1
                    if active_bars_held >= MAX_HOLD_BARS and has_evaluable_next_bar(bars, index, end_index):
                        trades.append(close_active_trade(bars, active, index, "max_hold"))
                        active = None
                        active_bars_held = 0
                        index += 1
                        continue

                if active is None and has_evaluable_next_bar(bars, index - 1, end_index):
                    closed_index = index - 1
                    next_direction = compression_breakout_direction(
                        bars,
                        closed_index,
                        ranges[closed_index],
                        range_average[closed_index],
                    )
                    if next_direction != 0:
                        pending_direction = next_direction
                        pending_average_range = range_average[closed_index] or 0.0

                if pending_direction != 0 and active is None:
                    active = open_active_trade(
                        bars,
                        window.fold_id,
                        index,
                        pending_direction,
                        pending_average_range,
                    )
                    active_bars_held = 0
                    pending_direction = 0
                    pending_average_range = 0.0

            if active is not None and has_evaluable_next_bar(bars, index, end_index):
                exit_reason = active_exit_reason(bars[index], active)
                if exit_reason:
                    trades.append(close_active_trade(bars, active, index, exit_reason))
                    active = None
                    active_bars_held = 0
            index += 1
    if active is not None:
        final_index = min(last_index_at_or_before(bars, windows[-1].end), len(bars) - 1)
        trades.append(close_active_trade(bars, active, final_index, "deinit"))
    return trades


def open_active_trade(
    bars: list[Bar],
    fold_id: str,
    entry_index: int,
    direction: int,
    average_range: float,
) -> ActiveTrade:
    entry_bar = bars[entry_index]
    entry_price = entry_bar.open
    stop_price = normalize_price(entry_price - direction * STOP_ATR_MULTIPLE * average_range)
    target_price = normalize_price(entry_price + direction * TARGET_ATR_MULTIPLE * average_range)
    return ActiveTrade(
        fold_id=fold_id,
        entry_index=entry_index,
        direction=direction,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        spread_points=entry_bar.spread_points,
    )


def normalize_price(value: float) -> float:
    quantum = Decimal("1").scaleb(-PRICE_DIGITS)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def active_exit_reason(bar: Bar, active: ActiveTrade) -> str | None:
    if active.direction == 1:
        if bar.low <= active.stop_price:
            return "stop"
        if bar.high >= active.target_price:
            return "target"
    else:
        if bar.high >= active.stop_price:
            return "stop"
        if bar.low <= active.target_price:
            return "target"
    return None


def has_evaluable_next_bar(bars: list[Bar], index: int, end_index: int) -> bool:
    if index >= end_index or index + 1 >= len(bars):
        return False
    gap_seconds = (bars[index + 1].time - bars[index].time).total_seconds()
    return 0 < gap_seconds <= MAX_CLOSED_BAR_EVALUATION_GAP_SECONDS


def close_active_trade(bars: list[Bar], active: ActiveTrade, exit_index: int, exit_reason: str) -> Trade:
    exit_price = bars[exit_index].close
    if exit_reason == "stop":
        exit_price = active.stop_price
    elif exit_reason == "target":
        exit_price = active.target_price
    path = bars[active.entry_index : exit_index + 1]
    if active.direction == 1:
        mfe = max(bar.high - active.entry_price for bar in path)
        mae = max(active.entry_price - bar.low for bar in path)
    else:
        mfe = max(active.entry_price - bar.low for bar in path)
        mae = max(bar.high - active.entry_price for bar in path)
    pnl = active.direction * (exit_price - active.entry_price) - active.spread_points
    return Trade(
        fold_id=active.fold_id,
        entry_time=bars[active.entry_index].time,
        exit_time=bars[exit_index].time,
        direction=active.direction,
        entry_price=active.entry_price,
        exit_price=exit_price,
        pnl_points=pnl,
        bars_held=exit_index - active.entry_index + 1,
        exit_reason=exit_reason,
        mfe_points=mfe,
        mae_points=mae,
        spread_points=active.spread_points,
    )


def previous_rolling_average(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) <= window:
        return result
    total = sum(values[:window])
    for index in range(window, len(values)):
        if index > window:
            total += values[index - 1] - values[index - window - 1]
        result[index] = total / window
    return result


def previous_extrema(bars: list[Bar], window: int) -> tuple[list[float | None], list[float | None]]:
    highs: list[float | None] = [None] * len(bars)
    lows: list[float | None] = [None] * len(bars)
    for index in range(window, len(bars)):
        previous = bars[index - window : index]
        highs[index] = max(bar.high for bar in previous)
        lows[index] = min(bar.low for bar in previous)
    return highs, lows


def compression_breakout_direction(
    bars: list[Bar],
    index: int,
    range_points: float,
    average_range: float | None,
) -> int:
    if average_range is None or average_range <= 0 or index <= COMPRESSION_BARS:
        return 0
    bar = bars[index]
    previous = bars[index - COMPRESSION_BARS : index]
    compression_high = max(item.high for item in previous)
    compression_low = min(item.low for item in previous)
    compression_width = compression_high - compression_low
    if compression_width <= 0:
        return 0
    if compression_width > COMPRESSION_RANGE_MULTIPLE * average_range:
        return 0
    if range_points < BREAKOUT_RANGE_MULTIPLE * average_range:
        return 0
    body = bar.close - bar.open
    if abs(body) < MIN_BODY_RANGE_FRACTION * range_points:
        return 0
    if body > 0 and bar.close > compression_high:
        return 1
    if body < 0 and bar.close < compression_low:
        return -1
    return 0


def build_trade(
    bars: list[Bar],
    fold_id: str,
    index_by_time: dict[datetime, int],
    entry_index: int,
    direction: int,
    average_range: float | None,
    end_index: int,
) -> Trade:
    entry_bar = bars[entry_index]
    entry_price = entry_bar.open
    stop_distance = STOP_ATR_MULTIPLE * (average_range or 0.0)
    target_distance = TARGET_ATR_MULTIPLE * (average_range or 0.0)
    stop_price = entry_price - direction * stop_distance
    target_price = entry_price + direction * target_distance
    max_exit_index = min(entry_index + MAX_HOLD_BARS, end_index)
    exit_index = max_exit_index
    exit_price = bars[max_exit_index].close
    exit_reason = "max_hold"

    for index in range(entry_index, max_exit_index + 1):
        bar = bars[index]
        if direction == 1:
            hit_stop = bar.low <= stop_price
            hit_target = bar.high >= target_price
            if hit_stop:
                exit_index = index
                exit_price = stop_price
                exit_reason = "stop"
                break
            if hit_target:
                exit_index = index
                exit_price = target_price
                exit_reason = "target"
                break
        else:
            hit_stop = bar.high >= stop_price
            hit_target = bar.low <= target_price
            if hit_stop:
                exit_index = index
                exit_price = stop_price
                exit_reason = "stop"
                break
            if hit_target:
                exit_index = index
                exit_price = target_price
                exit_reason = "target"
                break

    path = bars[entry_index : exit_index + 1]
    if direction == 1:
        mfe = max(bar.high - entry_price for bar in path)
        mae = max(entry_price - bar.low for bar in path)
    else:
        mfe = max(entry_price - bar.low for bar in path)
        mae = max(bar.high - entry_price for bar in path)
    pnl = direction * (exit_price - entry_price) - entry_bar.spread_points
    return Trade(
        fold_id=fold_id,
        entry_time=entry_bar.time,
        exit_time=bars[exit_index].time,
        direction=direction,
        entry_price=entry_price,
        exit_price=exit_price,
        pnl_points=pnl,
        bars_held=exit_index - entry_index + 1,
        exit_reason=exit_reason,
        mfe_points=mfe,
        mae_points=mae,
        spread_points=entry_bar.spread_points,
    )


def first_index_at_or_after(bars: list[Bar], timestamp: datetime) -> int:
    for index, bar in enumerate(bars):
        if bar.time >= timestamp:
            return index
    raise ValueError(f"No bar at or after {timestamp}")


def last_index_at_or_before(bars: list[Bar], timestamp: datetime) -> int:
    for index in range(len(bars) - 1, -1, -1):
        if bars[index].time <= timestamp:
            return index
    raise ValueError(f"No bar at or before {timestamp}")


def build_proxy_payload(trades: list[Trade], windows: list[Window]) -> dict[str, object]:
    fold_ids = [window.fold_id for window in windows]
    required = required_kpis(trades)
    fold_summary = grouped_summary(trades, lambda trade: trade.fold_id)
    month_summary = grouped_summary(trades, lambda trade: trade.entry_time.strftime("%Y-%m"))
    direction = direction_summary(trades)
    return {
        "schema": "axiom_rift_proxy_kpi_v1",
        "template": False,
        "requirement_policy": "required_and_conditional_required_with_deferred_reason",
        "created_at_utc": utc_now(),
        "work_unit_id": "C0001",
        "campaign_id": "C0001",
        "synthesis_id_when_applicable": None,
        "run_id": "R0004",
        "proxy_id": "PX0004",
        "dataset_identity": "data/processed/datasets/us100_m5_base_frame.csv",
        "split_policy": "rolling_window_test_oos_only",
        "fold_ids": fold_ids,
        "proxy_engine": "axiom_rift.proxies.r0004_compression_breakout_continuation",
        "proxy_config_path": "campaigns/C0001_regime_response_discovery/runs/R0004/run_manifest.json",
        "proxy_code_version_or_commit": "uncommitted_local_worktree_at_proxy_creation",
        "proxy_artifact_paths": [
            "campaigns/C0001_regime_response_discovery/runs/R0004/kpi/proxy.json"
        ],
        "proxy_artifact_hashes": [],
        "proxy_config": proxy_config(),
        "proxy_summary": {
            "evaluation_surface": "rolling_window_test_oos_only",
            "trade_count": required["proxy_trade_count"],
            "signal_count": required["proxy_signal_count"],
            "gross_profit_points": rounded(sum(trade.pnl_points for trade in trades if trade.pnl_points > 0)),
            "gross_loss_points": rounded(sum(trade.pnl_points for trade in trades if trade.pnl_points < 0)),
            "net_pnl_points": rounded(sum(trade.pnl_points for trade in trades)),
            "starting_balance_usd": STARTING_BALANCE_USD,
            "net_pnl_usd": None,
            "balance_after_proxy_usd": None,
            "money_model_status": "deferred_until_mt5_symbol_spec_and_fixed_lot_size",
            "long_trade_count": direction["long"]["trade_count"],
            "short_trade_count": direction["short"]["trade_count"],
            "target_exit_count": sum(1 for trade in trades if trade.exit_reason == "target"),
            "stop_exit_count": sum(1 for trade in trades if trade.exit_reason == "stop"),
            "max_hold_exit_count": sum(1 for trade in trades if trade.exit_reason == "max_hold"),
            "average_bars_in_trade": rounded(mean([trade.bars_held for trade in trades])),
        },
        "required_kpis": required,
        "conditional_profiles": {
            "score_surface_profile": {
                "applies": False,
                "fields": {},
            },
            "trade_excursion_profile": {
                "applies": True,
                "fields": excursion_summary(trades),
            },
            "direction_profile": {
                "applies": True,
                "fields": direction,
            },
            "stability_profile": {
                "applies": True,
                "fields": {
                    "fold_summary": fold_summary,
                    "month_summary": month_summary,
                    "losing_month_count": sum(1 for row in month_summary if row["net_pnl_points"] < 0),
                    "worst_month_pnl_points": min((row["net_pnl_points"] for row in month_summary), default=None),
                },
            },
            "cost_execution_profile": {
                "applies": True,
                "fields": {
                    "spread_source": "entry_bar_spread_column",
                    "spread_point_value": SPREAD_POINT_VALUE,
                    "round_trip_cost_model": "subtract_entry_spread_once",
                    "total_spread_cost_points": rounded(sum(trade.spread_points for trade in trades)),
                    "average_spread_cost_points": rounded(mean([trade.spread_points for trade in trades])),
                },
            },
        },
        "deferred_with_reason": [
            {
                "field": "proxy_net_pnl, proxy_max_drawdown_percent, proxy_expectancy_per_entry",
                "requirement_class": "deferred_with_reason",
                "reason": "R0004 proxy currently measures raw US100 index points only; USD conversion requires MT5 symbol contract, tick value, and fixed-lot discovery sizing",
                "blocking_condition": "record the matching MT5 symbol specification and fixed-lot sizing for the 500 USD account",
                "revisit_when": "during R0004 MT5 probe evidence production",
                "claim_boundary": {"claim_authority": False},
            },
            {
                "field": "proxy_artifact_hashes",
                "requirement_class": "deferred_with_reason",
                "reason": "self-hash is recorded in artifact_lineage after proxy.json is written",
                "blocking_condition": "proxy.json content must be stable before hashing",
                "revisit_when": "before R0004 closeout",
                "claim_boundary": {"claim_authority": False},
            }
        ],
        "claim_boundary": {
            "claim_authority": False,
            "selected": False,
            "runtime_authority": False,
            "live_ready": False,
        },
    }


def required_kpis(trades: list[Trade]) -> dict[str, int | float | None]:
    total_pnl = sum(trade.pnl_points for trade in trades)
    wins = [trade for trade in trades if trade.pnl_points > 0]
    return {
        "proxy_trade_count": len(trades),
        "proxy_signal_count": len(trades),
        "proxy_net_pnl": None,
        "proxy_profit_factor": profit_factor(trades),
        "proxy_max_drawdown_percent": None,
        "proxy_expectancy_per_entry": None,
        "proxy_win_rate": rounded(len(wins) / len(trades)) if trades else None,
        "proxy_net_pnl_points": rounded(total_pnl),
        "proxy_max_drawdown_points": max_drawdown_points(trades),
        "proxy_expectancy_points_per_entry": rounded(total_pnl / len(trades)) if trades else None,
    }


def grouped_summary(trades: list[Trade], key_fn: Any) -> list[dict[str, object]]:
    grouped: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        grouped[key_fn(trade)].append(trade)
    return [
        {
            "bucket": key,
            "trade_count": len(bucket_trades),
            "net_pnl_points": rounded(sum(trade.pnl_points for trade in bucket_trades)),
            "profit_factor": profit_factor(bucket_trades),
            "win_rate": rounded(sum(1 for trade in bucket_trades if trade.pnl_points > 0) / len(bucket_trades)),
            "max_drawdown_points": max_drawdown_points(bucket_trades),
        }
        for key, bucket_trades in sorted(grouped.items())
    ]


def direction_summary(trades: list[Trade]) -> dict[str, dict[str, int | float | None]]:
    return {
        "long": direction_bucket(trades, 1),
        "short": direction_bucket(trades, -1),
    }


def direction_bucket(trades: list[Trade], direction: int) -> dict[str, int | float | None]:
    bucket = [trade for trade in trades if trade.direction == direction]
    return {
        "trade_count": len(bucket),
        "net_pnl_points": rounded(sum(trade.pnl_points for trade in bucket)),
        "profit_factor": profit_factor(bucket),
        "win_rate": rounded(sum(1 for trade in bucket if trade.pnl_points > 0) / len(bucket)) if bucket else None,
        "max_drawdown_points": max_drawdown_points(bucket),
    }


def excursion_summary(trades: list[Trade]) -> dict[str, float | None]:
    return {
        "average_mfe_points": rounded(mean([trade.mfe_points for trade in trades])),
        "average_mae_points": rounded(mean([trade.mae_points for trade in trades])),
        "median_mfe_points": rounded(median([trade.mfe_points for trade in trades])),
        "median_mae_points": rounded(median([trade.mae_points for trade in trades])),
        "average_capture_ratio": rounded(mean(capture_ratios(trades))),
    }


def capture_ratios(trades: list[Trade]) -> list[float]:
    ratios: list[float] = []
    for trade in trades:
        if trade.mfe_points > 0:
            ratios.append(max(trade.pnl_points, 0.0) / trade.mfe_points)
    return ratios


def profit_factor(trades: list[Trade]) -> float | None:
    gross_profit = sum(trade.pnl_points for trade in trades if trade.pnl_points > 0)
    gross_loss = sum(trade.pnl_points for trade in trades if trade.pnl_points < 0)
    if gross_loss == 0:
        return None if gross_profit == 0 else round(gross_profit, 6)
    return rounded(gross_profit / abs(gross_loss))


def max_drawdown_points(trades: list[Trade]) -> float | None:
    if not trades:
        return None
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for trade in trades:
        equity += trade.pnl_points
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return rounded(max_drawdown)


def proxy_config() -> dict[str, object]:
    return {
        "bar_basis": "closed_m5",
        "entry_basis": "next_bar_open_after_compression_breakout_close",
        "evaluation_splits": "rolling_windows_test_oos",
        "lookback_range_bars": LOOKBACK_RANGE_BARS,
        "compression_bars": COMPRESSION_BARS,
        "compression_range_multiple": COMPRESSION_RANGE_MULTIPLE,
        "breakout_range_multiple": BREAKOUT_RANGE_MULTIPLE,
        "min_body_range_fraction": MIN_BODY_RANGE_FRACTION,
        "stop_atr_multiple": STOP_ATR_MULTIPLE,
        "target_atr_multiple": TARGET_ATR_MULTIPLE,
        "max_hold_bars": MAX_HOLD_BARS,
        "same_bar_stop_target_policy": "stop_first_conservative",
        "max_closed_bar_evaluation_gap_seconds": MAX_CLOSED_BAR_EVALUATION_GAP_SECONDS,
        "price_precision_digits": PRICE_DIGITS,
        "starting_balance_usd": STARTING_BALANCE_USD,
        "money_conversion_status": "deferred_until_mt5_symbol_spec_and_fixed_lot_size",
        "response_mode": "compression_breakout_continuation",
        "trade_direction_policy": "follow_compression_breakout_close_direction",
    }


def write_proxy_evidence(payload: dict[str, object]) -> None:
    PROXY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    proxy_hash = sha256_file(PROXY_PATH)
    update_artifact_lineage(proxy_hash)
    update_run_manifest_status()
    update_gate_report()


def update_artifact_lineage(proxy_hash: str) -> None:
    data = json.loads(ARTIFACT_LINEAGE_PATH.read_text(encoding="ascii"))
    for record in data.get("artifact_records", []):
        if record.get("artifact_id") == "A0001":
            record["sha256"] = proxy_hash
            record["produced_by"] = "axiom_rift.proxies.r0004_compression_breakout_continuation"
            record["mutable"] = False
    ARTIFACT_LINEAGE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_run_manifest_status() -> None:
    data = json.loads(RUN_MANIFEST_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_ready"
    data["gate_status"] = "proxy_recorded_pending_mt5"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_matching_mt5_probe_for_R0004"
    data["deferred_with_reason"] = [
        {
            "field": "decision",
            "reason": "proxy evidence is recorded but MT5 and proxy-vs-MT5 evidence are still missing",
            "blocking_condition": "R0004 cannot close until the mandatory MT5 probe and proxy-vs-MT5 comparison are recorded",
            "revisit_when": "after R0004 MT5 and proxy-vs-MT5 evidence files contain measured results",
        }
    ]
    GATE_REPORT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def mean(values: list[float | int]) -> float | None:
    return None if not values else sum(values) / len(values)


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2



