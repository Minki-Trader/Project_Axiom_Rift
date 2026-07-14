from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import unittest

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.research.composite_consensus_replay import (
    COMPOSITE_CONSENSUS_REPLAY_HISTORICAL_CONTEXT_ID,
    composite_consensus_replay_configurations,
    composite_consensus_replay_controlled_chassis,
    composite_consensus_replay_executable,
    composite_consensus_replay_protocol_definition,
)
from axiom_rift.research.composite_consensus_replay_job import (
    RUNTIME_ADAPTER as CONSENSUS_RUNTIME_ADAPTER,
    build_composite_consensus_replay_job_plan,
    composite_consensus_replay_job_implementation_artifact,
    composite_consensus_replay_job_implementation_sha256,
    materialize_composite_consensus_replay_job_implementation,
)
from axiom_rift.research.composite_consensus_replay_parity import (
    STU0017_HISTORICAL_EVALUATION_HASHES,
)
from axiom_rift.research.composite_router_replay import (
    COMPOSITE_ROUTER_REPLAY_HISTORICAL_CONTEXT_ID,
    composite_router_replay_configurations,
    composite_router_replay_controlled_chassis,
    composite_router_replay_executable,
    composite_router_replay_protocol_definition,
)
from axiom_rift.research.composite_router_replay_job import (
    RUNTIME_ADAPTER as ROUTER_RUNTIME_ADAPTER,
    build_composite_router_replay_job_plan,
    composite_router_replay_job_implementation_artifact,
    composite_router_replay_job_implementation_sha256,
    materialize_composite_router_replay_job_implementation,
)
from axiom_rift.research.composite_router_replay_parity import (
    STU0016_HISTORICAL_EVALUATION_HASHES,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FIXED_HOLD_REPLAY_EVIDENCE_MODES,
)
from axiom_rift.research.historical_family_replay import (
    STU0016_HISTORICAL_FAMILY,
    STU0017_HISTORICAL_FAMILY,
)
from axiom_rift.research.scientific_trace import (
    COMPOSITE_CONSENSUS_REPLAY_TRACE_PROTOCOL_ID,
    COMPOSITE_ROUTER_REPLAY_TRACE_PROTOCOL_ID,
    trace_proof_kinds,
)
from axiom_rift.storage.evidence import EvidenceStore


HISTORICAL_CONTEXT_COUNT = 600


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


class RoutedSleeveReplayTests(unittest.TestCase):
    def test_both_exact_historical_families_are_reconstructed(self) -> None:
        cases = (
            (
                composite_router_replay_configurations(),
                STU0016_HISTORICAL_FAMILY,
                composite_router_replay_protocol_definition(
                    historical_context_prior_global_exposure_count=(
                        HISTORICAL_CONTEXT_COUNT
                    )
                ),
                COMPOSITE_ROUTER_REPLAY_TRACE_PROTOCOL_ID,
                COMPOSITE_ROUTER_REPLAY_HISTORICAL_CONTEXT_ID,
                210,
            ),
            (
                composite_consensus_replay_configurations(),
                STU0017_HISTORICAL_FAMILY,
                composite_consensus_replay_protocol_definition(
                    historical_context_prior_global_exposure_count=(
                        HISTORICAL_CONTEXT_COUNT
                    )
                ),
                COMPOSITE_CONSENSUS_REPLAY_TRACE_PROTOCOL_ID,
                COMPOSITE_CONSENSUS_REPLAY_HISTORICAL_CONTEXT_ID,
                222,
            ),
        )
        for configurations, family, definition, protocol, context, end in cases:
            with self.subTest(study=family.original_study_id):
                self.assertEqual(len(configurations), 12)
                self.assertEqual(
                    tuple(
                        value.historical_reference_executable_id
                        for value in configurations
                    ),
                    tuple(
                        value.historical_reference_executable_id
                        for value in family.members
                    ),
                )
                self.assertEqual(definition.family, family)
                self.assertEqual(definition.protocol_id, protocol)
                self.assertEqual(definition.historical_context_id, context)
                self.assertEqual(
                    definition.original_family_end_global_exposure_count,
                    end,
                )
                self.assertEqual(
                    definition.historical_prior_global_exposure_count,
                    HISTORICAL_CONTEXT_COUNT,
                )
                self.assertEqual(len(set(definition.prospective_executable_ids)), 12)

    def test_parity_catalogs_open_every_exact_historical_evaluation(self) -> None:
        root = Path(__file__).resolve().parents[2]
        store = EvidenceStore(root / "local" / "evidence")
        cases = (
            (
                STU0016_HISTORICAL_EVALUATION_HASHES,
                "composite_router_evaluation.v1",
                STU0016_HISTORICAL_FAMILY,
            ),
            (
                STU0017_HISTORICAL_EVALUATION_HASHES,
                "composite_consensus_evaluation.v1",
                STU0017_HISTORICAL_FAMILY,
            ),
        )
        for catalog, schema, family in cases:
            self.assertEqual(len(catalog), 12)
            references = {
                member.configuration_id: member.historical_reference_executable_id
                for member in family.members
            }
            for configuration_id, identity in catalog.items():
                value = parse_canonical(store.read_verified(identity))
                self.assertEqual(value["schema"], schema)
                self.assertEqual(
                    value["subject_configuration_id"], configuration_id
                )
                self.assertEqual(
                    value["subject_executable_id"],
                    references[configuration_id],
                )

    def test_factorial_chassis_keeps_non_evaluated_anchors(self) -> None:
        cases = (
            (
                composite_router_replay_controlled_chassis,
                composite_router_replay_protocol_definition,
            ),
            (
                composite_consensus_replay_controlled_chassis,
                composite_consensus_replay_protocol_definition,
            ),
        )
        for chassis_builder, definition_builder in cases:
            chassis = chassis_builder(
                historical_context_prior_global_exposure_count=(
                    HISTORICAL_CONTEXT_COUNT
                )
            )
            definition = definition_builder(
                historical_context_prior_global_exposure_count=(
                    HISTORICAL_CONTEXT_COUNT
                )
            )
            parameters = chassis.baseline_executable.parameter_values()
            self.assertEqual(parameters["configuration_id"], "comparison-anchor")
            self.assertEqual(parameters["signal_sign"], 0)
            self.assertNotIn(
                chassis.baseline_executable.identity,
                definition.prospective_executable_ids,
            )

    def test_shared_runtime_binds_code_without_historical_study_runners(
        self,
    ) -> None:
        cases = (
            (
                ROUTER_RUNTIME_ADAPTER,
                composite_router_replay_job_implementation_artifact,
                composite_router_replay_job_implementation_sha256,
                materialize_composite_router_replay_job_implementation,
                "axiom_rift/research/composite_router_replay.py",
                "axiom_rift/research/composite_router_replay_job.py",
                "axiom_rift/research/composite_router_study.py",
            ),
            (
                CONSENSUS_RUNTIME_ADAPTER,
                composite_consensus_replay_job_implementation_artifact,
                composite_consensus_replay_job_implementation_sha256,
                materialize_composite_consensus_replay_job_implementation,
                "axiom_rift/research/composite_consensus_replay.py",
                "axiom_rift/research/composite_consensus_replay_job.py",
                "axiom_rift/research/composite_consensus_study.py",
            ),
        )
        for runtime, artifact_builder, identity_builder, materialize, adapter, job, old in cases:
            artifact = parse_canonical(artifact_builder())
            paths = {value["path"] for value in artifact["dependencies"]}
            self.assertIn(adapter, paths)
            self.assertIn(job, paths)
            self.assertIn(
                "axiom_rift/research/routed_sleeve_trace_engine.py",
                paths,
            )
            self.assertNotIn(old, paths)
            self.assertEqual(runtime.expected_family_size, 12)
            identity = identity_builder()
            writer = _Writer()
            self.assertEqual(
                materialize(writer),  # type: ignore[arg-type]
                identity,
            )

    def test_each_member_gets_one_shared_cache_job_plan(self) -> None:
        cases = (
            (
                composite_router_replay_configurations,
                composite_router_replay_executable,
                build_composite_router_replay_job_plan,
            ),
            (
                composite_consensus_replay_configurations,
                composite_consensus_replay_executable,
                build_composite_consensus_replay_job_plan,
            ),
        )
        for configurations, executable_builder, plan_builder in cases:
            plans = []
            for configuration in configurations():
                executable = executable_builder(
                    configuration,
                    historical_context_prior_global_exposure_count=(
                        HISTORICAL_CONTEXT_COUNT
                    ),
                )
                plans.append(
                    plan_builder(
                        mission_id="MIS-0006",
                        study_id="STU-0110",
                        executable_id=executable.identity,
                        historical_context_prior_global_exposure_count=(
                            HISTORICAL_CONTEXT_COUNT
                        ),
                    )
                )
            self.assertTrue(plans[0].produces_family_cache)
            self.assertTrue(
                all(not value.produces_family_cache for value in plans[1:])
            )
            self.assertEqual(len(plans[0].expected_outputs()), 7)
            self.assertTrue(
                all(len(value.expected_outputs()) == 5 for value in plans[1:])
            )

    def test_closed_dispatcher_accepts_both_registered_protocols(self) -> None:
        for protocol in (
            COMPOSITE_ROUTER_REPLAY_TRACE_PROTOCOL_ID,
            COMPOSITE_CONSENSUS_REPLAY_TRACE_PROTOCOL_ID,
        ):
            for mode in FIXED_HOLD_REPLAY_EVIDENCE_MODES:
                self.assertEqual(
                    set(
                        trace_proof_kinds(
                            protocol_id=protocol,
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
