from __future__ import annotations

import unittest
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
import pandas as pd

from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
    validate_controlled_executable,
)
from axiom_rift.research import usdjpy_carry_exit_chassis as chassis_module
from axiom_rift.research.discovery import execution_pnl
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.usdjpy_carry_exit_chassis import (
    CARRY_STATE_BARS,
    frontier_executable,
    simulate_usdjpy_carry_exit,
    usdjpy_carry_exit_chassis_implementation_sha256,
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
                ResearchLayer.EXECUTION,
                ResearchLayer.LIFECYCLE,
                ResearchLayer.PORTFOLIO,
            ),
            controlled_domains=(
                ResearchLayer.CALIBRATION,
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
        self.assertNotEqual(subject.engine_contract, baseline.engine_contract)
        self.assertIn(
            usdjpy_carry_exit_chassis_implementation_sha256(),
            subject.engine_contract,
        )

    def test_implementation_identity_tracks_artifact_bytes(self) -> None:
        implementation_path = Path(chassis_module.__file__).resolve()
        self.assertEqual(
            usdjpy_carry_exit_chassis_implementation_sha256(),
            sha256(implementation_path.read_bytes()).hexdigest(),
        )
        with TemporaryDirectory() as temporary:
            candidate = Path(temporary) / "chassis.py"
            candidate.write_bytes(b"semantic-manifest-a")
            with patch.object(chassis_module, "_THIS_FILE", candidate):
                left = usdjpy_carry_exit_chassis_implementation_sha256()
                left_executable = usdjpy_carry_exit_executable(
                    usdjpy_carry_exit_configurations()[1]
                )
                candidate.write_bytes(b"semantic-manifest-b")
                right = usdjpy_carry_exit_chassis_implementation_sha256()
                right_executable = usdjpy_carry_exit_executable(
                    usdjpy_carry_exit_configurations()[1]
                )
        self.assertNotEqual(left, right)
        self.assertNotEqual(left_executable.identity, right_executable.identity)
        self.assertNotEqual(
            left_executable.engine_contract,
            right_executable.engine_contract,
        )

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
        self.assertEqual(
            macro_target.iloc[0]["carry_exit_reason"],
            "negative_carry_unwind_exit",
        )

    def test_missing_entry_state_prevents_dependent_target_entry(self) -> None:
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
        self.assertTrue(target.empty)
        missing_intents = [
            row
            for row in result.intent_rows
            if row[-1] == "source_state_missing_no_entry"
        ]
        self.assertEqual(
            len(missing_intents),
            1,
        )

    def test_gap_precedes_missing_state_and_preserves_control_entry_set(self) -> None:
        frame, score, volatility, run, spread = fixture()
        frame.loc[3:, "time"] += pd.Timedelta(minutes=5)
        run[:3] = np.arange(1, 4, dtype=np.int32)
        run[3:] = np.arange(1, len(run) - 2, dtype=np.int32)
        score[:, 2] = 0.01
        score[2, 2] = np.nan
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
        self.assertEqual(
            fixed_target[["decision_time", "entry_time", "direction"]].to_dict(
                "records"
            ),
            macro_target[["decision_time", "entry_time", "direction"]].to_dict(
                "records"
            ),
        )
        self.assertEqual(
            sum(row[-1] == "gap_excluded" for row in macro.intent_rows),
            1,
        )
        self.assertFalse(
            any(
                row[-1] == "source_state_missing_no_entry"
                for row in macro.intent_rows
            )
        )

    def test_session_gate_uses_scheduled_entry_clock_not_future_row(self) -> None:
        frame, score, volatility, run, spread = fixture()
        frame["time"] = pd.date_range(
            "2026-01-05 14:50:00", periods=len(frame), freq="5min"
        )
        frame.loc[1:, "time"] += pd.Timedelta(minutes=5)
        score[:] = np.nan
        score[0, 1] = 2.0
        score[:, 2] = 0.01
        result = simulate_usdjpy_carry_exit(
            frame=frame,
            score=score,
            volatility=volatility,
            run=run,
            threshold=1.0,
            configuration=usdjpy_carry_exit_configurations()[1],
            test_start=frame["time"].iloc[0],
            test_end=frame["time"].iloc[-1],
            fold_id="rw_fixture",
            regime_cutoffs=(0.5, 1.5),
            effective_spread=spread,
        )
        self.assertFalse(
            any(row[0] == "target_direction" for row in result.intent_rows)
        )

    def test_missing_holding_state_safe_exits_and_bounds_pnl(self) -> None:
        frame, score, volatility, run, spread = fixture()
        score[:, 2] = 0.01
        score[3, 2] = np.nan
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
        trade = target.iloc[0]
        self.assertEqual(
            trade["exit_time"] - trade["entry_time"],
            pd.Timedelta(minutes=5),
        )
        self.assertEqual(
            trade["carry_exit_reason"],
            "missing_or_stale_state_safe_exit",
        )
        self.assertTrue(bool(trade["carry_state_fail_closed"]))
        expected_native, _ = execution_pnl(
            direction=int(trade["direction"]),
            entry_bid=float(frame["open"].iloc[3]),
            exit_bid=float(frame["open"].iloc[4]),
            entry_spread_points=1.0,
            exit_spread_points=1.0,
        )
        self.assertAlmostEqual(float(trade["pnl"]), expected_native)


if __name__ == "__main__":
    unittest.main()
