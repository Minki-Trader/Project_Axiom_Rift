from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
    validate_controlled_executable,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.usdjpy_carry_exit_chassis import (
    CARRY_STATE_BARS,
    frontier_executable,
    simulate_usdjpy_carry_exit,
    usdjpy_carry_exit_configurations,
    usdjpy_carry_exit_executable,
)
from axiom_rift.research.usdjpy_source import usdjpy_source_contract


def fixture() -> tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    time = pd.date_range("2026-01-05 15:00:00", periods=20, freq="5min")
    frame = pd.DataFrame(
        {
            "time": time,
            "open": np.linspace(100.0, 101.9, len(time)),
            "high": np.linspace(100.1, 102.0, len(time)),
            "low": np.linspace(99.9, 101.8, len(time)),
            "close": np.linspace(100.05, 101.95, len(time)),
            "tick_volume": np.full(len(time), 10),
            "spread": np.ones(len(time)),
        }
    )
    score = np.zeros((len(time), 3), dtype=float)
    score[2, 1] = 2.0
    score[4, 1] = 2.0
    volatility = np.full(len(time), 2.0)
    run = np.arange(1, len(time) + 1, dtype=np.int32)
    spread = np.ones(len(time), dtype=float)
    return frame, score, volatility, run, spread


class USDJPYCarryExitChassisTests(unittest.TestCase):
    def test_subject_is_new_lifecycle_architecture_with_exact_source(self) -> None:
        control, subject = usdjpy_carry_exit_configurations()
        control_executable = usdjpy_carry_exit_executable(control)
        subject_executable = usdjpy_carry_exit_executable(subject)
        self.assertEqual(control_executable.identity, frontier_executable().identity)
        self.assertNotEqual(subject_executable.identity, control_executable.identity)
        self.assertEqual(
            subject_executable.source_contracts,
            (usdjpy_source_contract().source_contract_id,),
        )
        self.assertEqual(CARRY_STATE_BARS, 288)
        self.assertNotEqual(
            ArchitectureChassisSpec.from_executable(subject_executable).identity,
            ArchitectureChassisSpec.from_executable(control_executable).identity,
        )

    def test_subject_changes_only_source_lifecycle_and_composition_domains(self) -> None:
        baseline = frontier_executable()
        subject = usdjpy_carry_exit_executable(
            usdjpy_carry_exit_configurations()[1]
        )
        controlled = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(
                ResearchLayer.DATA_SOURCE,
                ResearchLayer.LIFECYCLE,
                ResearchLayer.PORTFOLIO,
            ),
            controlled_domains=(
                ResearchLayer.CALIBRATION,
                ResearchLayer.EXECUTION,
                ResearchLayer.FEATURE,
                ResearchLayer.LABEL,
                ResearchLayer.MODEL,
                ResearchLayer.OBJECTIVE,
                ResearchLayer.REGIME,
                ResearchLayer.RISK,
                ResearchLayer.SELECTOR,
                ResearchLayer.SYNTHESIS,
                ResearchLayer.TRADE,
            ),
            architecture=ArchitectureChassisSpec.from_executable(baseline),
        )
        validate_controlled_executable(controlled.to_identity_payload(), subject)
        self.assertEqual(subject.engine_contract, baseline.engine_contract)

    def test_carry_unwind_exits_target_early_but_reserves_original_slot(self) -> None:
        frame, score, volatility, run, spread = fixture()
        score[3:, 2] = -0.01
        control, subject = usdjpy_carry_exit_configurations()
        common = {
            "frame": frame,
            "score": score,
            "volatility": volatility,
            "run": run,
            "threshold": 1.0,
            "test_start": frame["time"].iloc[0],
            "test_end": frame["time"].iloc[-1],
            "fold_id": "rw_fixture",
            "regime_cutoffs": (0.5, 1.5),
            "effective_spread": spread,
        }
        fixed = simulate_usdjpy_carry_exit(configuration=control, **common)
        macro = simulate_usdjpy_carry_exit(configuration=subject, **common)
        fixed_target = fixed.trades[fixed.trades["slot"] == "target_direction"]
        macro_target = macro.trades[macro.trades["slot"] == "target_direction"]
        self.assertEqual(len(fixed_target), 1)
        self.assertEqual(len(macro_target), 1)
        self.assertEqual(
            fixed_target.iloc[0]["entry_time"], macro_target.iloc[0]["entry_time"]
        )
        self.assertEqual(
            fixed_target.iloc[0]["direction"], macro_target.iloc[0]["direction"]
        )
        self.assertEqual(
            macro_target.iloc[0]["exit_time"] - macro_target.iloc[0]["entry_time"],
            pd.Timedelta(minutes=5),
        )
        self.assertEqual(
            fixed_target.iloc[0]["exit_time"] - fixed_target.iloc[0]["entry_time"],
            pd.Timedelta(minutes=30),
        )
        self.assertTrue(bool(macro_target.iloc[0]["carry_early_exit"]))

    def test_missing_carry_state_retains_fixed_exit(self) -> None:
        frame, score, volatility, run, spread = fixture()
        score[:, 2] = np.nan
        subject = usdjpy_carry_exit_configurations()[1]
        result = simulate_usdjpy_carry_exit(
            frame=frame,
            score=score,
            volatility=volatility,
            run=run,
            threshold=1.0,
            configuration=subject,
            test_start=frame["time"].iloc[0],
            test_end=frame["time"].iloc[-1],
            fold_id="rw_fixture",
            regime_cutoffs=(0.5, 1.5),
            effective_spread=spread,
        )
        target = result.trades[result.trades["slot"] == "target_direction"]
        self.assertEqual(len(target), 1)
        self.assertEqual(
            target.iloc[0]["exit_time"] - target.iloc[0]["entry_time"],
            pd.Timedelta(minutes=30),
        )
        self.assertFalse(bool(target.iloc[0]["carry_early_exit"]))


if __name__ == "__main__":
    unittest.main()
