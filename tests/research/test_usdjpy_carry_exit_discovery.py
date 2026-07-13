from __future__ import annotations

import unittest
from hashlib import sha256

import numpy as np
import pandas as pd

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.usdjpy_carry_exit_chassis import CARRY_STATE_BARS
from axiom_rift.research.usdjpy_carry_exit_chassis import (
    executable_configuration_map,
    usdjpy_carry_exit_configurations,
    usdjpy_carry_exit_executable,
)
from axiom_rift.research.usdjpy_carry_exit_discovery import (
    aligned_usdjpy_carry_return,
    project_usdjpy_carry_exit_evaluation,
    source_carry_return,
)
from axiom_rift.research.usdjpy_carry_exit_study import (
    build_usdjpy_carry_exit_validation_plan,
)
from axiom_rift.research.validation import require_supported_evaluation_schema


class USDJPYCarryExitDiscoveryTests(unittest.TestCase):
    def test_carry_return_requires_one_exact_consecutive_source_day(self) -> None:
        periods = CARRY_STATE_BARS + 3
        time = pd.date_range("2026-01-05 00:00:00", periods=periods, freq="5min")
        close = 150.0 * np.exp(np.arange(periods, dtype=float) / 100_000.0)
        state = source_carry_return(pd.DataFrame({"time": time, "close": close}))

        self.assertTrue(state.iloc[:CARRY_STATE_BARS].isna().all())
        self.assertAlmostEqual(
            float(state.iloc[CARRY_STATE_BARS]),
            float(np.log(close[CARRY_STATE_BARS]) - np.log(close[0])),
        )

    def test_gap_resets_state_and_exact_alignment_does_not_fill(self) -> None:
        periods = (CARRY_STATE_BARS * 2) + 4
        time = pd.date_range("2026-01-05 00:00:00", periods=periods, freq="5min")
        time = time.to_series(index=np.arange(periods))
        time.loc[CARRY_STATE_BARS:] += pd.Timedelta(minutes=5)
        source = pd.DataFrame(
            {
                "time": pd.DatetimeIndex(time),
                "close": np.linspace(150.0, 151.0, periods),
            }
        )
        state = source_carry_return(source)
        first_after_gap = CARRY_STATE_BARS
        rewarm = first_after_gap + CARRY_STATE_BARS

        self.assertTrue(state.iloc[first_after_gap:rewarm].isna().all())
        self.assertTrue(np.isfinite(state.iloc[rewarm]))

        target = pd.DataFrame(
            {
                "time": [
                    source["time"].iloc[rewarm],
                    source["time"].iloc[rewarm] + pd.Timedelta(minutes=1),
                ]
            }
        )
        aligned = aligned_usdjpy_carry_return(target, source)
        self.assertTrue(np.isfinite(aligned[0]))
        self.assertTrue(np.isnan(aligned[1]))

    def test_validator_profile_is_registered_before_performance_work(self) -> None:
        subject = usdjpy_carry_exit_executable(
            usdjpy_carry_exit_configurations()[1]
        )
        plan = build_usdjpy_carry_exit_validation_plan(
            subject.identity,
            mission_id="MIS-0006",
        )
        self.assertEqual(plan["executable_id"], subject.identity)
        self.assertFalse(plan["candidate_eligible_on_pass"])
        self.assertEqual(
            require_supported_evaluation_schema("usdjpy_carry_exit_evaluation.v1"),
            "usdjpy_carry_exit_evaluation.v1",
        )

    def test_projection_keeps_diagnostics_in_metrics_and_surface_only(self) -> None:
        surface = {
            "schema": "usdjpy_carry_exit_surface.v1",
            "evaluations": [
                {"subject_executable_id": executable_id}
                for executable_id in executable_configuration_map()
            ],
            "claim_limits": [],
            "lifecycle_diagnostics": {"entry_identity_mismatch_count": 0},
            "selection_context": [],
            "selection_method": {},
            "session_semantics": (
                "broker_clock_fixed_bins_no_dst_or_cash_session_claim"
            ),
            "state_counts": [{"fold_id": "rw01"}],
        }
        surface_hash = sha256(canonical_bytes(surface)).hexdigest()
        execution = {
            "job_hash": "1" * 64,
            "job_id": "job:" + "2" * 64,
            "job_permit_id": "3" * 64,
            "start_record_id": "4" * 64,
        }
        execution["identity"] = canonical_digest(
            domain="running-job-execution", payload=execution
        )
        subject_id = usdjpy_carry_exit_executable(
            usdjpy_carry_exit_configurations()[1]
        ).identity
        evaluation = project_usdjpy_carry_exit_evaluation(
            surface,
            job_execution=execution,
            subject_executable_id=subject_id,
            surface_artifact_hash=surface_hash,
            surface_manifest_hash="5" * 64,
        )
        self.assertNotIn("lifecycle_diagnostics", evaluation)
        self.assertNotIn("state_counts", evaluation)


if __name__ == "__main__":
    unittest.main()
