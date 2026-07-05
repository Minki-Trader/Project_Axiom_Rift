import unittest

from axiom_rift.mt5.sc0007_sr0001_probe import (
    active_missing_fields,
    zero_trade_divergence_not_applicable_fields,
    zero_trade_tick_not_applicable_fields,
)


class SC0007ZeroTradeFoldTest(unittest.TestCase):
    def test_zero_trade_tick_metrics_are_not_applicable_not_missing(self) -> None:
        required = {
            "mt5_trade_count": 0,
            "mt5_net_pnl": 0,
            "mt5_profit_factor": None,
            "mt5_max_drawdown_percent": None,
            "mt5_expectancy_per_entry": None,
            "mt5_win_rate": None,
        }
        missing = [
            "mt5_profit_factor",
            "mt5_max_drawdown_percent",
            "mt5_expectancy_per_entry",
            "mt5_win_rate",
        ]

        not_applicable = zero_trade_tick_not_applicable_fields(required, missing)

        self.assertEqual(not_applicable, missing)
        self.assertEqual(active_missing_fields(missing, not_applicable), [])

    def test_nonzero_trade_tick_missing_fields_remain_missing(self) -> None:
        required = {"mt5_trade_count": 1, "mt5_net_pnl": 0, "mt5_profit_factor": None}
        missing = ["mt5_profit_factor"]

        not_applicable = zero_trade_tick_not_applicable_fields(required, missing)

        self.assertEqual(not_applicable, [])
        self.assertEqual(active_missing_fields(missing, not_applicable), missing)

    def test_zero_trade_divergence_rates_are_not_applicable_not_missing(self) -> None:
        required = {
            "logic_trade_count": 0,
            "tick_trade_count": 0,
            "logic_net_pnl": 0,
            "tick_net_pnl": 0,
            "entry_key_match_rate": None,
            "exit_time_direction_match_rate": None,
            "exit_reason_match_rate": None,
        }
        missing = [
            "entry_key_match_rate",
            "exit_time_direction_match_rate",
            "exit_reason_match_rate",
        ]

        not_applicable = zero_trade_divergence_not_applicable_fields(required, missing)

        self.assertEqual(not_applicable, missing)
        self.assertEqual(active_missing_fields(missing, not_applicable), [])


if __name__ == "__main__":
    unittest.main()
