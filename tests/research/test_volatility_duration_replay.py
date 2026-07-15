from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np
import pandas as pd

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.research.fixed_hold_family_trace import (
    FIXED_HOLD_REPLAY_EVIDENCE_MODES,
)
from axiom_rift.research.historical_family_replay import (
    STU0051_HISTORICAL_FAMILY,
)
from axiom_rift.research.scientific_trace import (
    VOLATILITY_DURATION_REPLAY_TRACE_PROTOCOL_ID,
    trace_proof_kinds,
)
from axiom_rift.research.volatility_duration_discovery import (
    calibrate_selector,
    causal_state_effective_spread,
    compute_volatility_duration_score,
)
from axiom_rift.research.volatility_duration_replay import (
    VOLATILITY_DURATION_REPLAY_HISTORICAL_CONTEXT_ID,
    calibrate_volatility_duration_replay_selector,
    causal_volatility_duration_replay_spread,
    compute_volatility_duration_replay_score,
    volatility_duration_replay_configurations,
    volatility_duration_replay_controlled_chassis,
    volatility_duration_replay_executable,
    volatility_duration_replay_protocol_definition,
)
from axiom_rift.research.volatility_duration_replay_job import (
    RUNTIME_ADAPTER,
    build_volatility_duration_replay_job_plan,
    materialize_volatility_duration_replay_job_implementation,
    volatility_duration_replay_job_implementation_artifact,
    volatility_duration_replay_job_implementation_sha256,
)
from axiom_rift.research.volatility_duration_replay_parity import (
    STU0051_REPAIRED_HISTORICAL_EVALUATION_HASHES,
)
from axiom_rift.storage.evidence import EvidenceStore


HISTORICAL_CONTEXT_COUNT = 582


class _EvidenceStore:
    def __init__(self) -> None:
        self.artifacts: dict[str, bytes] = {}

    def finalize(self, content: bytes) -> SimpleNamespace:
        identity = sha256(content).hexdigest()
        self.artifacts[identity] = content
        return SimpleNamespace(sha256=identity)


class _Writer:
    def __init__(self) -> None:
        self.evidence = _EvidenceStore()


class VolatilityDurationReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.configurations = volatility_duration_replay_configurations()
        cls.definition = volatility_duration_replay_protocol_definition(
            historical_context_prior_global_exposure_count=(
                HISTORICAL_CONTEXT_COUNT
            )
        )

    def test_exact_historical_family_is_reconstructed_without_global_inference(
        self,
    ) -> None:
        self.assertEqual(
            tuple(
                value.historical_reference_executable_id
                for value in self.configurations
            ),
            tuple(
                value.historical_reference_executable_id
                for value in STU0051_HISTORICAL_FAMILY.members
            ),
        )
        self.assertEqual(
            self.definition.protocol_id,
            VOLATILITY_DURATION_REPLAY_TRACE_PROTOCOL_ID,
        )
        self.assertEqual(
            self.definition.historical_context_id,
            VOLATILITY_DURATION_REPLAY_HISTORICAL_CONTEXT_ID,
        )
        self.assertEqual(
            self.definition.original_family_end_global_exposure_count,
            452,
        )
        self.assertEqual(
            self.definition.historical_prior_global_exposure_count,
            HISTORICAL_CONTEXT_COUNT,
        )
        self.assertEqual(len(self.definition.prospective_executable_ids), 4)
        self.assertEqual(
            self.definition.prospective_executable_ids,
            tuple(
                volatility_duration_replay_executable(
                    configuration,
                    historical_context_prior_global_exposure_count=(
                        HISTORICAL_CONTEXT_COUNT
                    ),
                ).identity
                for configuration in self.configurations
            ),
        )

    def test_repaired_parity_catalog_opens_exact_historical_evidence(self) -> None:
        store = EvidenceStore(
            Path(__file__).resolve().parents[2] / "local" / "evidence"
        )
        for configuration_id, identity in (
            STU0051_REPAIRED_HISTORICAL_EVALUATION_HASHES.items()
        ):
            value = parse_canonical(store.read_verified(identity))
            self.assertEqual(
                value["subject_configuration_id"],
                configuration_id,
            )
            self.assertEqual(
                value["schema"],
                "volatility_duration_evaluation.v2",
            )

    def test_readable_adapter_matches_legacy_feature_and_cost_primitives(
        self,
    ) -> None:
        time = pd.date_range(
            "2024-01-01T00:00:00Z",
            periods=1_500,
            freq="5min",
        )
        trend = np.linspace(0.0, 0.2, len(time))
        cycle = 0.015 * np.sin(np.arange(len(time)) / 17.0)
        frame = pd.DataFrame(
            {"time": time, "close": 15_000.0 * np.exp(trend + cycle)}
        )
        for profile in (
            "mature_state_age_24_47",
            "persistent_state_age_72_143",
        ):
            expected = compute_volatility_duration_score(frame, profile)
            observed = compute_volatility_duration_replay_score(frame, profile)
            for actual, prior in zip(observed, expected, strict=True):
                np.testing.assert_allclose(actual, prior, equal_nan=True)
        spread = np.array([2.0, 0.0, 0.0, 3.0, 0.0, 0.0])
        time_ns = np.array(
            [0, 300, 600, 1_200, 1_500, 1_800],
            dtype=np.int64,
        ) * 1_000_000_000
        np.testing.assert_allclose(
            causal_volatility_duration_replay_spread(spread, time_ns),
            causal_state_effective_spread(spread, time_ns),
            equal_nan=True,
        )
        score = np.ones(600)
        mask = np.ones(600, dtype=bool)
        self.assertEqual(
            calibrate_volatility_duration_replay_selector(score, mask),
            calibrate_selector(score, mask),
        )

    def test_factorial_chassis_keeps_a_non_evaluated_anchor(self) -> None:
        chassis = volatility_duration_replay_controlled_chassis(
            historical_context_prior_global_exposure_count=(
                HISTORICAL_CONTEXT_COUNT
            )
        )
        parameters = chassis.baseline_executable.parameter_values()
        self.assertEqual(parameters["configuration_id"], "comparison-anchor")
        self.assertEqual(parameters["signal_sign"], 0)
        self.assertNotIn(
            chassis.baseline_executable.identity,
            self.definition.prospective_executable_ids,
        )

    def test_shared_runtime_binds_adapter_entry_and_all_source_dependencies(
        self,
    ) -> None:
        artifact = parse_canonical(
            volatility_duration_replay_job_implementation_artifact()
        )
        self.assertIsInstance(artifact, dict)
        paths = {value["path"] for value in artifact["dependencies"]}
        self.assertIn(
            "axiom_rift/research/fixed_hold_replay_runtime.py",
            paths,
        )
        self.assertIn(
            "axiom_rift/research/volatility_duration_replay.py",
            paths,
        )
        self.assertIn(
            "axiom_rift/research/volatility_duration_replay_job.py",
            paths,
        )
        self.assertIn(
            "axiom_rift/research/volatility_duration_replay_parity.py",
            paths,
        )
        self.assertEqual(RUNTIME_ADAPTER.expected_family_size, 4)
        identity = volatility_duration_replay_job_implementation_sha256()
        self.assertEqual(len(identity), 64)
        writer = _Writer()
        self.assertEqual(
            materialize_volatility_duration_replay_job_implementation(
                writer  # type: ignore[arg-type]
            ),
            identity,
        )

    def test_each_member_gets_one_exact_generic_job_plan(self) -> None:
        plans = []
        for configuration in self.configurations:
            executable = volatility_duration_replay_executable(
                configuration,
                historical_context_prior_global_exposure_count=(
                    HISTORICAL_CONTEXT_COUNT
                ),
            )
            plans.append(
                build_volatility_duration_replay_job_plan(
                    mission_id="MIS-0006",
                    study_id="STU-0108",
                    executable_id=executable.identity,
                    historical_context_prior_global_exposure_count=(
                        HISTORICAL_CONTEXT_COUNT
                    ),
                )
            )
        self.assertTrue(plans[0].produces_family_cache)
        self.assertTrue(all(not value.produces_family_cache for value in plans[1:]))
        self.assertEqual(len(plans[0].expected_outputs()), 7)
        self.assertTrue(all(len(value.expected_outputs()) == 5 for value in plans[1:]))

    def test_closed_dispatcher_accepts_only_registered_replay_protocol(self) -> None:
        for mode in FIXED_HOLD_REPLAY_EVIDENCE_MODES:
            self.assertEqual(
                set(
                    trace_proof_kinds(
                        protocol_id=VOLATILITY_DURATION_REPLAY_TRACE_PROTOCOL_ID,
                        evidence_mode=mode,
                    )
                ),
                {
                    "atomic_evaluation_trace.v1",
                    "protocol_calculation_proof.v1",
                },
            )


if __name__ == "__main__":
    unittest.main()
