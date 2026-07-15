from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.validation import (
    validator_identity,
    validator_implementation_sha256,
)
from axiom_rift.operations.writer import _hardcoded_control_ids
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
from axiom_rift.research.fixed_hold_replay_runtime import (
    fixed_hold_replay_runtime_dependency_paths,
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
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    SCIENTIFIC_VALIDATION_V2_DEPENDENCIES,
    SCIENTIFIC_VALIDATION_V2_DOMAINS,
    SCIENTIFIC_VALIDATION_V2_PROTOCOL,
    ScientificAdjudicationValidatorV2,
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
                "axiom_rift/research/historical_family_stu0016.py",
                "axiom_rift/research/historical_family_stu0017.py",
                "STU-0016",
            ),
            (
                CONSENSUS_RUNTIME_ADAPTER,
                composite_consensus_replay_job_implementation_artifact,
                composite_consensus_replay_job_implementation_sha256,
                materialize_composite_consensus_replay_job_implementation,
                "axiom_rift/research/composite_consensus_replay.py",
                "axiom_rift/research/composite_consensus_replay_job.py",
                "axiom_rift/research/composite_consensus_study.py",
                "axiom_rift/research/historical_family_stu0017.py",
                "axiom_rift/research/historical_family_stu0016.py",
                "STU-0017",
            ),
        )
        for (
            runtime,
            artifact_builder,
            identity_builder,
            materialize,
            adapter,
            job,
            old,
            binding,
            foreign_binding,
            allowed_study_id,
        ) in cases:
            artifact = parse_canonical(artifact_builder())
            paths = {value["path"] for value in artifact["dependencies"]}
            self.assertIn(adapter, paths)
            self.assertIn(job, paths)
            self.assertIn(binding, paths)
            self.assertNotIn(foreign_binding, paths)
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
            manifest = parse_canonical(writer.evidence.artifacts[identity])
            manifest_hashes = set(manifest["artifact_hashes"])
            dependency_hashes = {
                value["sha256"] for value in artifact["dependencies"]
            }
            self.assertTrue(dependency_hashes.issubset(manifest_hashes))
            self.assertTrue(
                dependency_hashes.issubset(writer.evidence.artifacts)
            )
            hardcoded = {
                control_id
                for source_hash in manifest_hashes
                for control_id in _hardcoded_control_ids(
                    writer.evidence.artifacts[source_hash]
                )
            }
            self.assertEqual(hardcoded, {allowed_study_id})

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

    def test_foreign_frozen_reconstruction_drift_is_identity_neutral(self) -> None:
        configuration = composite_router_replay_configurations()[0]
        executable = composite_router_replay_executable(
            configuration,
            historical_context_prior_global_exposure_count=(
                HISTORICAL_CONTEXT_COUNT
            ),
        )
        plan = build_composite_router_replay_job_plan(
            mission_id="MIS-0006",
            study_id="STU-0110",
            executable_id=executable.identity,
            historical_context_prior_global_exposure_count=(
                HISTORICAL_CONTEXT_COUNT
            ),
        )
        baseline_job_implementation = (
            composite_router_replay_job_implementation_sha256()
        )
        baseline_plan_hash = plan.plan_hash
        baseline_binding = plan.scientific_binding()
        baseline_inputs = plan.job_input_hashes()
        foreign = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "axiom_rift"
            / "research"
            / "historical_family_stu0017.py"
        ).resolve()
        generic_binding = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "axiom_rift"
            / "research"
            / "historical_family_binding.py"
        ).resolve()
        self.assertIn(generic_binding, SCIENTIFIC_VALIDATION_V2_DEPENDENCIES)
        self.assertNotIn(foreign, SCIENTIFIC_VALIDATION_V2_DEPENDENCIES)
        self.assertNotIn(
            foreign,
            fixed_hold_replay_runtime_dependency_paths(
                ROUTER_RUNTIME_ADAPTER
            ),
        )
        original_read_bytes = Path.read_bytes

        def perturb(path: Path) -> bytes:
            content = original_read_bytes(path)
            if path.resolve() == foreign:
                return content + b"\n# foreign frozen reconstruction drift\n"
            return content

        with patch.object(Path, "read_bytes", perturb):
            validator = ScientificAdjudicationValidatorV2()
            changed_validator_id = validator_identity(
                protocol=SCIENTIFIC_VALIDATION_V2_PROTOCOL,
                domains=SCIENTIFIC_VALIDATION_V2_DOMAINS,
                implementation_sha256=validator_implementation_sha256(
                    implementation_path=validator.implementation_path,
                    dependency_paths=SCIENTIFIC_VALIDATION_V2_DEPENDENCIES,
                ),
            )
            changed_job_implementation = (
                composite_router_replay_job_implementation_sha256()
            )
        self.assertEqual(
            changed_validator_id,
            SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        )
        self.assertEqual(
            changed_job_implementation,
            baseline_job_implementation,
        )
        self.assertEqual(plan.plan_hash, baseline_plan_hash)
        self.assertEqual(plan.job_input_hashes(), baseline_inputs)

        changed_binding = {
            **baseline_binding,
            "validator_id": changed_validator_id,
        }

        def identities(binding: dict[str, object]) -> tuple[str, str]:
            spec = {
                "callable_identity": ROUTER_RUNTIME_ADAPTER.callable_identity,
                "evidence_subject": {
                    "kind": "Executable",
                    "id": executable.identity,
                },
                "implementation_identity": baseline_job_implementation,
                "scientific_binding": binding,
            }
            job_identity = canonical_digest(
                domain="job",
                payload={"mission_id": "MIS-0006", "spec": spec},
            )
            work = canonical_digest(
                domain="job-work",
                payload={
                    "mission_id": "MIS-0006",
                    "work": {
                        "callable_identity": spec["callable_identity"],
                        "evidence_subject": spec["evidence_subject"],
                        "scientific_binding": binding,
                    },
                },
            )
            success = canonical_digest(
                domain="job-success-cache",
                payload={
                    "implementation_identity": baseline_job_implementation,
                    "mission_id": "MIS-0006",
                    "work_fingerprint": work,
                },
            )
            return job_identity, success

        baseline_identities = identities(baseline_binding)
        changed_identities = identities(changed_binding)
        self.assertEqual(baseline_identities, changed_identities)
        self.assertEqual(
            sha256(canonical_bytes(plan.plan)).hexdigest(),
            baseline_plan_hash,
        )
        self.assertEqual(
            plan.cache_output_name,
            build_composite_router_replay_job_plan(
                mission_id="MIS-0006",
                study_id="STU-0110",
                executable_id=executable.identity,
                historical_context_prior_global_exposure_count=(
                    HISTORICAL_CONTEXT_COUNT
                ),
            ).cache_output_name,
        )

    def test_router_calculation_drift_reidentifies_job_implementation(self) -> None:
        target = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "axiom_rift"
            / "research"
            / "routed_sleeve_trace_engine.py"
        ).resolve()
        self.assertIn(
            target,
            fixed_hold_replay_runtime_dependency_paths(
                ROUTER_RUNTIME_ADAPTER
            ),
        )
        baseline = composite_router_replay_job_implementation_sha256()
        original_read_bytes = Path.read_bytes

        def perturb(path: Path) -> bytes:
            content = original_read_bytes(path)
            if path.resolve() == target:
                return content + b"\n# routed calculation drift\n"
            return content

        with patch.object(Path, "read_bytes", perturb):
            changed = composite_router_replay_job_implementation_sha256()
        self.assertNotEqual(changed, baseline)

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
