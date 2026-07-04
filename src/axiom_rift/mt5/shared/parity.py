"""Shared MT5 parity and divergence helpers."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from axiom_rift.mt5.shared.kpi import rounded


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def event_bar_time(row: dict[str, str]) -> datetime | None:
    return parse_time(row.get("bar_time") or row.get("time"))


def direction_value(value: str | None) -> int:
    if value == "long":
        return 1
    if value == "short":
        return -1
    return 0


def time_text(value: datetime | None) -> str | None:
    return None if value is None else value.strftime("%Y-%m-%d %H:%M:%S")


def match_rate(matches: int, denominator: int) -> float | None:
    return rounded(matches / denominator) if denominator else None


def counter_match_count(left: Counter[Any], right: Counter[Any]) -> int:
    return sum((left & right).values())


def parity_mismatch_summary(
    proxy_trade_count: int,
    mt5_trade_count: int,
    entry_compare: dict[str, object],
    exit_compare: dict[str, object],
) -> str:
    if proxy_trade_count == mt5_trade_count and entry_compare["key_match_rate"] == 1.0 and exit_compare["reason_match_rate"] == 1.0:
        return "No key mismatch detected"
    return (
        f"entry_key_match={entry_compare['key_match_rate']} "
        f"exit_time_direction_match={exit_compare['time_direction_match_rate']} "
        f"exit_reason_match={exit_compare['reason_match_rate']} "
        f"proxy_trades={proxy_trade_count} mt5_trades={mt5_trade_count}"
    )


def compare_entry_sequence(proxy_trades: list[Any], mt5_entries: list[dict[str, str]]) -> dict[str, object]:
    mismatch_samples: list[dict[str, object]] = []
    proxy_time_keys = Counter(trade.entry_time for trade in proxy_trades)
    mt5_time_keys = Counter(event_bar_time(row) for row in mt5_entries)
    proxy_direction_keys = Counter(int(trade.direction) for trade in proxy_trades)
    mt5_direction_keys = Counter(direction_value(row.get("direction")) for row in mt5_entries)
    proxy_entry_keys = Counter((trade.entry_time, int(trade.direction)) for trade in proxy_trades)
    mt5_entry_keys = Counter((event_bar_time(row), direction_value(row.get("direction"))) for row in mt5_entries)
    time_matches = counter_match_count(proxy_time_keys, mt5_time_keys)
    direction_matches = counter_match_count(proxy_direction_keys, mt5_direction_keys)
    key_matches = counter_match_count(proxy_entry_keys, mt5_entry_keys)
    sequence_time_matches = 0
    sequence_direction_matches = 0
    compared = min(len(proxy_trades), len(mt5_entries))
    for index in range(compared):
        proxy_trade = proxy_trades[index]
        mt5_row = mt5_entries[index]
        if proxy_trade.entry_time == event_bar_time(mt5_row):
            sequence_time_matches += 1
        if int(proxy_trade.direction) == direction_value(mt5_row.get("direction")):
            sequence_direction_matches += 1
    for key in list((proxy_entry_keys - mt5_entry_keys).elements())[:5]:
        mismatch_samples.append({"side": "proxy_only", "entry_time": time_text(key[0]), "direction": key[1]})
    for key in list((mt5_entry_keys - proxy_entry_keys).elements())[:5]:
        mismatch_samples.append({"side": "mt5_only", "entry_time": time_text(key[0]), "direction": key[1]})
    return {
        "time_match_rate": match_rate(time_matches, len(proxy_trades)),
        "direction_match_rate": match_rate(direction_matches, len(proxy_trades)),
        "key_match_rate": match_rate(key_matches, len(proxy_trades)),
        "sequence_time_match_rate": match_rate(sequence_time_matches, len(proxy_trades)),
        "sequence_direction_match_rate": match_rate(sequence_direction_matches, len(proxy_trades)),
        "mismatch_count": (len(proxy_trades) - key_matches) + (len(mt5_entries) - key_matches),
        "mismatch_samples": mismatch_samples,
    }


def compare_exit_sequence(proxy_trades: list[Any], mt5_exits: list[dict[str, str]]) -> dict[str, object]:
    mismatch_samples: list[dict[str, object]] = []
    proxy_time_keys = Counter(trade.exit_time for trade in proxy_trades)
    mt5_time_keys = Counter(event_bar_time(row) for row in mt5_exits)
    proxy_time_direction_keys = Counter((trade.exit_time, int(trade.direction)) for trade in proxy_trades)
    mt5_time_direction_keys = Counter((event_bar_time(row), direction_value(row.get("direction"))) for row in mt5_exits)
    proxy_reason_keys = Counter((trade.exit_time, int(trade.direction), trade.exit_reason) for trade in proxy_trades)
    mt5_reason_keys = Counter((event_bar_time(row), direction_value(row.get("direction")), row.get("reason") or "") for row in mt5_exits)
    time_matches = counter_match_count(proxy_time_keys, mt5_time_keys)
    time_direction_matches = counter_match_count(proxy_time_direction_keys, mt5_time_direction_keys)
    reason_matches = counter_match_count(proxy_reason_keys, mt5_reason_keys)
    sequence_time_matches = 0
    sequence_reason_matches = 0
    compared = min(len(proxy_trades), len(mt5_exits))
    for index in range(compared):
        proxy_trade = proxy_trades[index]
        mt5_row = mt5_exits[index]
        if proxy_trade.exit_time == event_bar_time(mt5_row):
            sequence_time_matches += 1
        if str(proxy_trade.exit_reason) == (mt5_row.get("reason") or ""):
            sequence_reason_matches += 1
    for key in list((proxy_reason_keys - mt5_reason_keys).elements())[:5]:
        mismatch_samples.append(
            {"side": "proxy_only", "exit_time": time_text(key[0]), "direction": key[1], "reason": key[2]}
        )
    for key in list((mt5_reason_keys - proxy_reason_keys).elements())[:5]:
        mismatch_samples.append(
            {"side": "mt5_only", "exit_time": time_text(key[0]), "direction": key[1], "reason": key[2]}
        )
    return {
        "time_match_rate": match_rate(time_matches, len(proxy_trades)),
        "time_direction_match_rate": match_rate(time_direction_matches, len(proxy_trades)),
        "reason_match_rate": match_rate(reason_matches, len(proxy_trades)),
        "sequence_time_match_rate": match_rate(sequence_time_matches, len(proxy_trades)),
        "sequence_reason_match_rate": match_rate(sequence_reason_matches, len(proxy_trades)),
        "mismatch_count": (len(proxy_trades) - reason_matches) + (len(mt5_exits) - reason_matches),
        "mismatch_samples": mismatch_samples,
    }


def compare_mt5_entry_events(logic_entries: list[dict[str, str]], tick_entries: list[dict[str, str]]) -> dict[str, object]:
    mismatch_samples: list[dict[str, object]] = []
    logic_time_keys = Counter(event_bar_time(row) for row in logic_entries)
    tick_time_keys = Counter(event_bar_time(row) for row in tick_entries)
    logic_direction_keys = Counter(direction_value(row.get("direction")) for row in logic_entries)
    tick_direction_keys = Counter(direction_value(row.get("direction")) for row in tick_entries)
    logic_entry_keys = Counter((event_bar_time(row), direction_value(row.get("direction"))) for row in logic_entries)
    tick_entry_keys = Counter((event_bar_time(row), direction_value(row.get("direction"))) for row in tick_entries)
    time_matches = counter_match_count(logic_time_keys, tick_time_keys)
    direction_matches = counter_match_count(logic_direction_keys, tick_direction_keys)
    key_matches = counter_match_count(logic_entry_keys, tick_entry_keys)
    sequence_time_matches = 0
    sequence_direction_matches = 0
    compared = min(len(logic_entries), len(tick_entries))
    for index in range(compared):
        logic_row = logic_entries[index]
        tick_row = tick_entries[index]
        if event_bar_time(logic_row) == event_bar_time(tick_row):
            sequence_time_matches += 1
        if direction_value(logic_row.get("direction")) == direction_value(tick_row.get("direction")):
            sequence_direction_matches += 1
    for key in list((logic_entry_keys - tick_entry_keys).elements())[:5]:
        mismatch_samples.append({"side": "logic_only", "entry_time": time_text(key[0]), "direction": key[1]})
    for key in list((tick_entry_keys - logic_entry_keys).elements())[:5]:
        mismatch_samples.append({"side": "tick_only", "entry_time": time_text(key[0]), "direction": key[1]})
    return {
        "time_match_rate": match_rate(time_matches, len(logic_entries)),
        "direction_match_rate": match_rate(direction_matches, len(logic_entries)),
        "key_match_rate": match_rate(key_matches, len(logic_entries)),
        "sequence_time_match_rate": match_rate(sequence_time_matches, len(logic_entries)),
        "sequence_direction_match_rate": match_rate(sequence_direction_matches, len(logic_entries)),
        "mismatch_count": (len(logic_entries) - key_matches) + (len(tick_entries) - key_matches),
        "mismatch_samples": mismatch_samples,
    }


def compare_mt5_exit_events(logic_exits: list[dict[str, str]], tick_exits: list[dict[str, str]]) -> dict[str, object]:
    mismatch_samples: list[dict[str, object]] = []
    logic_time_keys = Counter(event_bar_time(row) for row in logic_exits)
    tick_time_keys = Counter(event_bar_time(row) for row in tick_exits)
    logic_time_direction_keys = Counter((event_bar_time(row), direction_value(row.get("direction"))) for row in logic_exits)
    tick_time_direction_keys = Counter((event_bar_time(row), direction_value(row.get("direction"))) for row in tick_exits)
    logic_reason_keys = Counter(
        (event_bar_time(row), direction_value(row.get("direction")), row.get("reason") or "") for row in logic_exits
    )
    tick_reason_keys = Counter(
        (event_bar_time(row), direction_value(row.get("direction")), row.get("reason") or "") for row in tick_exits
    )
    time_matches = counter_match_count(logic_time_keys, tick_time_keys)
    time_direction_matches = counter_match_count(logic_time_direction_keys, tick_time_direction_keys)
    reason_matches = counter_match_count(logic_reason_keys, tick_reason_keys)
    sequence_time_matches = 0
    sequence_reason_matches = 0
    compared = min(len(logic_exits), len(tick_exits))
    for index in range(compared):
        logic_row = logic_exits[index]
        tick_row = tick_exits[index]
        if event_bar_time(logic_row) == event_bar_time(tick_row):
            sequence_time_matches += 1
        if (logic_row.get("reason") or "") == (tick_row.get("reason") or ""):
            sequence_reason_matches += 1
    for key in list((logic_reason_keys - tick_reason_keys).elements())[:5]:
        mismatch_samples.append(
            {"side": "logic_only", "exit_time": time_text(key[0]), "direction": key[1], "reason": key[2]}
        )
    for key in list((tick_reason_keys - logic_reason_keys).elements())[:5]:
        mismatch_samples.append(
            {"side": "tick_only", "exit_time": time_text(key[0]), "direction": key[1], "reason": key[2]}
        )
    return {
        "time_match_rate": match_rate(time_matches, len(logic_exits)),
        "time_direction_match_rate": match_rate(time_direction_matches, len(logic_exits)),
        "reason_match_rate": match_rate(reason_matches, len(logic_exits)),
        "sequence_time_match_rate": match_rate(sequence_time_matches, len(logic_exits)),
        "sequence_reason_match_rate": match_rate(sequence_reason_matches, len(logic_exits)),
        "mismatch_count": (len(logic_exits) - reason_matches) + (len(tick_exits) - reason_matches),
        "mismatch_samples": mismatch_samples,
    }


def execution_divergence_status(
    entry_compare: dict[str, object],
    exit_compare: dict[str, object],
    logic_net: float | None,
    tick_net: float | None,
) -> str:
    if (
        entry_compare.get("key_match_rate") == 1.0
        and exit_compare.get("time_direction_match_rate") == 1.0
        and exit_compare.get("reason_match_rate") == 1.0
        and logic_net == tick_net
    ):
        return "no_divergence_detected"
    return "recorded_with_divergence"


def economics_shift_status(logic_net: float | None, tick_net: float | None) -> str:
    if logic_net is None or tick_net is None:
        return "unknown_missing_net_pnl"
    if tick_net < logic_net:
        return "tick_worse_than_logic"
    if tick_net > logic_net:
        return "tick_better_than_logic"
    return "tick_equal_to_logic"
