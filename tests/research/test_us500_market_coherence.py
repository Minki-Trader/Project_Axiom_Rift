from __future__ import annotations

import unittest
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
    validate_controlled_executable,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research import us500_market_coherence_chassis as chassis_module
from axiom_rift.research.us500_market_coherence_chassis import (
    _route_scores,
    executable_configuration_map,
    frontier_executable,
    us500_market_coherence_chassis_implementation_sha256,
    us500_market_coherence_configurations,
    us500_market_coherence_executable,
)
from axiom_rift.research.us500_market_coherence_discovery import (
    project_us500_market_coherence_evaluation,
)
from axiom_rift.research.us500_source import us500_source_contract
from axiom_rift.research.us500_market_coherence_study import (
    build_us500_market_coherence_validation_plan,
)
from axiom_rift.research.validation import require_supported_evaluation_schema


class US500MarketCoherenceTests(unittest.TestCase):
    def test_subject_changes_only_declared_multilayer_surface(self) -> None:
        baseline = frontier_executable()
        subject = us500_market_coherence_executable(
            us500_market_coherence_configurations()[1]
        )
        chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(
                ResearchLayer.DATA_SOURCE,
                ResearchLayer.EXECUTION,
                ResearchLayer.REGIME,
                ResearchLayer.PORTFOLIO,
            ),
            controlled_domains=(
                ResearchLayer.CALIBRATION,
                ResearchLayer.FEATURE,
                ResearchLayer.LABEL,
                ResearchLayer.LIFECYCLE,
                ResearchLayer.MODEL,
                ResearchLayer.RISK,
                ResearchLayer.SELECTOR,
                ResearchLayer.SYNTHESIS,
                ResearchLayer.TRADE,
            ),
            architecture=ArchitectureChassisSpec.from_executable(baseline),
        )
        validate_controlled_executable(chassis.to_identity_payload(), subject)
        self.assertEqual(
            subject.source_contracts,
            (us500_source_contract().source_contract_id,),
        )
        self.assertNotEqual(subject.engine_contract, baseline.engine_contract)
        self.assertIn(
            us500_market_coherence_chassis_implementation_sha256(),
            subject.engine_contract,
        )

    def test_implementation_identity_tracks_artifact_bytes(self) -> None:
        implementation_path = Path(chassis_module.__file__).resolve()
        self.assertEqual(
            us500_market_coherence_chassis_implementation_sha256(),
            sha256(implementation_path.read_bytes()).hexdigest(),
        )
        with TemporaryDirectory() as temporary:
            candidate = Path(temporary) / "chassis.py"
            candidate.write_bytes(b"semantic-manifest-a")
            with patch.object(chassis_module, "_THIS_FILE", candidate):
                left = us500_market_coherence_chassis_implementation_sha256()
                left_executable = us500_market_coherence_executable(
                    us500_market_coherence_configurations()[1]
                )
                candidate.write_bytes(b"semantic-manifest-b")
                right = us500_market_coherence_chassis_implementation_sha256()
                right_executable = us500_market_coherence_executable(
                    us500_market_coherence_configurations()[1]
                )
        self.assertNotEqual(left, right)
        self.assertNotEqual(left_executable.identity, right_executable.identity)
        self.assertNotEqual(
            left_executable.engine_contract,
            right_executable.engine_contract,
        )

    def test_systemic_follows_idiosyncratic_reverses_and_missing_fails_closed(self) -> None:
        values = np.asarray(
            [
                [1.0, 2.0, 0.5],
                [1.0, 2.0, -0.5],
                [1.0, -2.0, -0.5],
                [1.0, -2.0, 0.5],
                [1.0, 2.0, np.nan],
                [1.0, 2.0, -0.5],
            ]
        )
        volatility = np.asarray([3.0, 3.0, 3.0, 3.0, 3.0, 1.0])
        routed = _route_scores(
            values,
            volatility,
            (1.0, 2.0),
            uses_market_coherence=True,
        )
        self.assertEqual(routed[:, 1].tolist(), [2.0, -2.0, -2.0, 2.0, 0.0, 2.0])

    def test_fixed_control_reverses_every_high_volatility_target(self) -> None:
        values = np.asarray([[1.0, 2.0, 0.5], [1.0, -2.0, 0.5], [1.0, 2.0, -0.5]])
        volatility = np.asarray([3.0, 3.0, 1.0])
        routed = _route_scores(
            values,
            volatility,
            (1.0, 2.0),
            uses_market_coherence=False,
        )
        self.assertEqual(routed[:, 1].tolist(), [-2.0, 2.0, 2.0])

    def test_scientific_validator_profile_is_registered_before_engine_work(self) -> None:
        subject = us500_market_coherence_executable(
            us500_market_coherence_configurations()[1]
        )
        plan = build_us500_market_coherence_validation_plan(
            subject.identity,
            mission_id="MIS-0006",
        )
        self.assertEqual(plan["executable_id"], subject.identity)
        self.assertEqual(
            require_supported_evaluation_schema(
                "us500_market_coherence_evaluation.v1"
            ),
            "us500_market_coherence_evaluation.v1",
        )

    def test_evaluation_projects_common_session_semantics_not_source_counts(self) -> None:
        surface = {
            "schema": "us500_market_coherence_surface.v1",
            "evaluations": [
                {"subject_executable_id": executable_id}
                for executable_id in executable_configuration_map()
            ],
            "claim_limits": [],
            "selection_context": [],
            "selection_method": {},
            "session_semantics": (
                "broker_clock_fixed_bins_no_dst_or_cash_session_claim"
            ),
            "state_counts": {"systemic": 1},
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
        subject_id = us500_market_coherence_executable(
            us500_market_coherence_configurations()[1]
        ).identity
        evaluation = project_us500_market_coherence_evaluation(
            surface,
            job_execution=execution,
            subject_executable_id=subject_id,
            surface_artifact_hash=surface_hash,
            surface_manifest_hash="5" * 64,
        )
        self.assertEqual(
            evaluation["session_semantics"],
            "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
        )
        self.assertNotIn("state_counts", evaluation)


if __name__ == "__main__":
    unittest.main()
