from __future__ import annotations

from types import SimpleNamespace
import unittest

import numpy as np
import pandas as pd

from axiom_rift.research.drawdown_state_replay import (
    _drawdown_causal_surface_digest,
)
from axiom_rift.research.fixed_hold_trace_engine import (
    _causal_surface_digest,
    _intent_rows,
    _trade_rows,
    fixed_hold_trace_engine_implementation_sha256,
)


class FixedHoldTraceEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = pd.DataFrame(
            {
                "time": pd.date_range(
                    "2025-01-01T00:00:00Z",
                    periods=3,
                    freq="5min",
                )
            }
        )
        self.configuration = SimpleNamespace(
            configuration_id="synthetic-follow-h1",
            historical_reference_executable_id="executable:" + "1" * 64,
            holding_bars=1,
        )
        trade = {
            "decision_bar_open_time": self.frame.loc[0, "time"],
            "decision_time": self.frame.loc[1, "time"],
            "direction": 1,
            "entry_time": self.frame.loc[1, "time"],
            "exit_time": self.frame.loc[2, "time"],
            "gross_pnl": 2.5,
            "native_cost": 0.25,
            "regime": "middle",
            "stress_cost": 0.5,
        }
        self.simulation = SimpleNamespace(
            trades=pd.DataFrame((trade,)),
            intent_rows=(
                (
                    self.frame.loc[1, "time"],
                    self.frame.loc[1, "time"],
                    self.frame.loc[2, "time"],
                    1,
                    "executed",
                ),
            ),
        )

    def test_trade_and_intent_rows_share_exact_clock_identity(self) -> None:
        captures = {
            ("fold-01", "full"): self.simulation,
            ("fold-01", "prefix"): self.simulation,
        }
        trades = _trade_rows(
            configuration=self.configuration,
            executable_id="executable:" + "2" * 64,
            simulations=captures,
            frame=self.frame,
        )
        intents = _intent_rows(
            configuration=self.configuration,
            executable_id="executable:" + "2" * 64,
            simulations=captures,
            frame=self.frame,
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(len(intents), 2)
        self.assertEqual(trades[0]["decision_bar_index"], 0)
        self.assertEqual(trades[0]["entry_bar_index"], 1)
        self.assertEqual(trades[0]["exit_bar_index"], 2)
        self.assertEqual(trades[0]["native_net_pnl_micropoints"], 2_250_000)
        self.assertEqual(
            {value["scope"] for value in intents},
            {"full", "prefix"},
        )
        self.assertTrue(
            all(
                str(value["observation_id"]).startswith("observation:")
                and len(str(value["observation_id"]).removeprefix("observation:"))
                == 64
                for value in trades + intents
            )
        )

    def test_engine_identity_is_exact_source_digest(self) -> None:
        identity = fixed_hold_trace_engine_implementation_sha256()
        self.assertEqual(len(identity), 64)
        self.assertTrue(all(value in "0123456789abcdef" for value in identity))

    def test_causal_surface_digest_covers_every_simulation_input(self) -> None:
        names = ("score", "volatility", "run", "effective_spread")
        baseline = tuple(
            (name, np.array([1.0, 2.0, np.nan])) for name in names
        )
        baseline_digest = _causal_surface_digest(baseline)

        for changed_name in names:
            changed = tuple(
                (
                    name,
                    np.array([1.0, 9.0, np.nan])
                    if name == changed_name
                    else np.array([1.0, 2.0, np.nan]),
                )
                for name in names
            )
            with self.subTest(changed_name=changed_name):
                self.assertNotEqual(
                    _causal_surface_digest(changed),
                    baseline_digest,
                )

    def test_drawdown_digest_covers_every_simulation_input(self) -> None:
        names = ("score", "volatility", "run", "effective_spread")
        baseline = tuple(
            (name, np.array([1.0, 2.0, np.nan])) for name in names
        )
        baseline_digest = _drawdown_causal_surface_digest(baseline)

        for changed_name in names:
            changed = tuple(
                (
                    name,
                    np.array([1.0, 9.0, np.nan])
                    if name == changed_name
                    else np.array([1.0, 2.0, np.nan]),
                )
                for name in names
            )
            with self.subTest(changed_name=changed_name):
                self.assertNotEqual(
                    _drawdown_causal_surface_digest(changed),
                    baseline_digest,
                )


if __name__ == "__main__":
    unittest.main()
