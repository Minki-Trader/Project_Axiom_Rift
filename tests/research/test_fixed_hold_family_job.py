from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.writer import RunningJobExecution
from axiom_rift.research.evidence_proofs import (
    FIXED_HOLD_FAMILY_TRACE_PROOF_KIND,
    FIXED_HOLD_FAMILY_TRACE_SCHEMA,
)
from axiom_rift.research.adjudication import scientific_adjudication_manifest
from axiom_rift.research.fixed_hold_family_job import (
    FIXED_HOLD_CACHE_PROVENANCE_SCHEMA,
    build_fixed_hold_cache_provenance,
    build_fixed_hold_family_job_plan,
    build_fixed_hold_measurement,
    build_fixed_hold_result,
    build_fixed_hold_shared_trace_calculation,
    fixed_hold_family_cache,
    fixed_hold_multiplicity_registrations,
    materialize_fixed_hold_cache,
    materialize_fixed_hold_evidence,
    validate_fixed_hold_cache_provenance,
    validate_fixed_hold_shared_trace_calculation,
    validated_fixed_hold_recomputed_criterion_ids,
    verify_fixed_hold_cache_producer,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FIXED_HOLD_REPLAY_CRITERIA,
    FIXED_HOLD_REPLAY_EVIDENCE_MODES,
    FIXED_HOLD_TRACE_VALIDATOR,
    FixedHoldFamilyTraceSnapshot,
    FixedHoldSubjectTraceSnapshot,
    bind_fixed_hold_family_trace,
    build_fixed_hold_trace_calculation,
    validate_fixed_hold_family_trace_snapshot,
)
import axiom_rift.research.fixed_hold_family_trace as fixed_hold_trace_module
import axiom_rift.research.fixed_hold_shared_trace as fixed_hold_shared_trace_module
from axiom_rift.research.fixed_hold_shared_trace import (
    validate_fixed_hold_shared_trace_pair,
)
from axiom_rift.research.scientific_trace import (
    ANALOG_FIXED_HOLD_REPLAY_TRACE_PROTOCOL_ID,
    ScientificTraceError,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_V2_SYNCHRONIZED_MAX_METHOD,
    adjudicate_validation_measurement_v2,
)
from tests.research.test_fixed_hold_family_trace import (
    calculation,
    definition,
    family_trace,
    subject_trace,
)


NAMESPACE = "test-fixed-hold-family"

EXPECTED_METRICS_SHA256 = (
    "67c3c851d99dc0f222f5e958776ad4826a0ca59835f70276148ce823f12f5d87",
    "a4a5a3a6ce722deb1e634103c5946fa8f5c0d22634802149b7eb2ca43b1720dc",
    "b849bcf6f12a755ba8a2af31c67c85844a20e1e6aed61212a682956b5d252242",
    "d0be2e2cfee874f287efb65704b0f5a81edad015f81058f69853dde1ca66346a",
)
EXPECTED_STATISTICS_SHA256 = (
    "47882d1b3b4dc308fa92a01d2cde8f5910e1c35b8a0984f04c2b71d9e8789dfd",
    "b86908b8fa6c933194731957c42ff203f80985019acc17f34047eceef7713fb2",
    "0ab34023a1cc2f39f0f44f9135d63cc87a65b9999ff8c517ff4ce4df607ff5e0",
    "af4d3b1b826fb158b17b9f757727d6055a3f6e39b9739f13495fab87356f31e4",
)


class _EvidenceStore:
    def __init__(self) -> None:
        self.artifacts: dict[str, bytes] = {}
        self.read_counts: dict[str, int] = {}

    def finalize(self, content: bytes) -> SimpleNamespace:
        from hashlib import sha256

        identity = sha256(content).hexdigest()
        self.artifacts[identity] = content
        return SimpleNamespace(sha256=identity)

    def read_verified(self, identity: str) -> bytes:
        self.read_counts[identity] = self.read_counts.get(identity, 0) + 1
        try:
            return self.artifacts[identity]
        except KeyError as exc:
            raise FileNotFoundError(identity) from exc


class _Writer:
    def __init__(self) -> None:
        self.evidence = _EvidenceStore()
        self.producer_calls: list[
            tuple[RunningJobExecution, dict[str, object]]
        ] = []

    def verify_reproducible_cache_producer(
        self,
        producer: RunningJobExecution,
        **kwargs: object,
    ) -> None:
        self.producer_calls.append((producer, dict(kwargs)))


def execution() -> RunningJobExecution:
    return RunningJobExecution(
        job_id="job:" + "1" * 64,
        job_hash="2" * 64,
        start_record_id="3" * 64,
        job_permit_id="4" * 64,
    )


def scoped_execution(ordinal: int) -> RunningJobExecution:
    def digest(label: str) -> str:
        return sha256(f"{label}-{ordinal}".encode("ascii")).hexdigest()

    job_hash = digest("job")
    return RunningJobExecution(
        job_id=f"job:{job_hash}",
        job_hash=job_hash,
        start_record_id=digest("start"),
        job_permit_id=digest("permit"),
    )


def validate_shared_pair(
    *,
    trace: object,
    calculation_proof: dict[str, object],
    plan: object,
    job_execution: RunningJobExecution,
    trace_hash: str,
) -> tuple[str, ...]:
    return validate_fixed_hold_shared_trace_pair(
        trace=trace,
        trace_output_name=plan.output_names["trace"],
        trace_hash=trace_hash,
        calculation=calculation_proof,
        expected_evidence_modes=FIXED_HOLD_REPLAY_EVIDENCE_MODES,
        expected_metric_bindings_by_mode={
            mode: () for mode in FIXED_HOLD_REPLAY_EVIDENCE_MODES
        },
        mission_id=plan.mission_id,
        executable_id=plan.executable_id,
        job_id=job_execution.job_id,
        job_hash=job_execution.job_hash,
    )


class FixedHoldFamilyJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.definition = replace(
            definition(),
            protocol_id=ANALOG_FIXED_HOLD_REPLAY_TRACE_PROTOCOL_ID,
        )

    def plan(self, executable_id: str):
        return build_fixed_hold_family_job_plan(
            definition=self.definition,
            artifact_namespace=NAMESPACE,
            mission_id="MIS-9001",
            study_id="STU-9001",
            executable_id=executable_id,
        )

    def test_plan_registers_real_selection_and_control_families(self) -> None:
        subject_id = self.definition.prospective_executable_ids[3]
        plan = self.plan(subject_id)
        registrations = fixed_hold_multiplicity_registrations(
            definition=self.definition,
            subject_executable_id=subject_id,
        )
        self.assertEqual(
            tuple(item["criterion_id"] for item in registrations),
            (
                "D02-opposite-sign-uncertainty",
                "E01-familywise-selection",
            ),
        )
        self.assertEqual(
            {item["method"] for item in registrations},
            {SCIENTIFIC_V2_SYNCHRONIZED_MAX_METHOD},
        )
        self.assertEqual(registrations[0]["family_size"], 3)
        self.assertEqual(registrations[1]["family_size"], 4)
        self.assertIn(subject_id, registrations[1]["ordered_member_ids"])
        self.assertEqual(
            plan.plan["adjudication_profile"]["multiplicity"],
            list(registrations),
        )
        trace_requirements = tuple(
            item
            for item in plan.plan["proof_requirements"]
            if item["proof_kind"] == FIXED_HOLD_FAMILY_TRACE_PROOF_KIND
        )
        self.assertEqual(len(trace_requirements), 4)
        self.assertTrue(
            all(
                item["artifact_schema"] == FIXED_HOLD_FAMILY_TRACE_SCHEMA
                for item in trace_requirements
            )
        )
        self.assertFalse(plan.produces_family_cache)
        self.assertEqual(len(plan.expected_outputs()), 5)
        self.assertTrue(all(len(value) == 64 for value in plan.job_input_hashes()))
        with self.assertRaisesRegex(ValueError, "inseparable"):
            plan.job_input_hashes(cache_sha256="a" * 64)

    def test_only_first_member_produces_one_typed_cache_and_provenance(self) -> None:
        producer = self.plan(self.definition.prospective_executable_ids[0])
        self.assertTrue(producer.produces_family_cache)
        self.assertEqual(len(producer.expected_outputs()), 7)
        self.assertEqual(
            producer.expected_output_classes()[producer.cache_output_name],
            "reproducible_cache",
        )
        provenance = build_fixed_hold_cache_provenance(
            scoped_plan=producer,
            execution=execution(),
            cache_sha256="5" * 64,
            producer_trace_sha256="6" * 64,
        )
        self.assertEqual(
            provenance["schema"],
            FIXED_HOLD_CACHE_PROVENANCE_SCHEMA,
        )
        self.assertEqual(
            validate_fixed_hold_cache_provenance(provenance),
            provenance,
        )
        forged = dict(provenance)
        forged["producer_executable_id"] = (
            self.definition.prospective_executable_ids[1]
        )
        # The generic schema remains data-only; exact producer scope is checked
        # by the consumer against its code-owned plan.
        self.assertEqual(
            validate_fixed_hold_cache_provenance(forged),
            forged,
        )

    def test_measurement_preserves_raw_and_synchronized_familywise_values(
        self,
    ) -> None:
        subject_id = self.definition.prospective_executable_ids[3]
        plan = self.plan(subject_id)
        _, subject = subject_trace(self.definition)
        proof = calculation(self.definition, subject)
        measurement = build_fixed_hold_measurement(
            scoped_plan=plan,
            job_id=str(proof["job_id"]),
            job_hash=str(proof["job_hash"]),
            calculation=proof,
            trace_sha256="9" * 64,
            calculation_sha256="a" * 64,
        )
        self.assertEqual(len(measurement["multiplicity"]), 2)
        for item in measurement["multiplicity"]:
            self.assertEqual(
                item["method"],
                SCIENTIFIC_V2_SYNCHRONIZED_MAX_METHOD,
            )
            self.assertLessEqual(
                item["raw_pvalue_ppm"],
                item["adjusted_pvalue_ppm"],
            )
        result = build_fixed_hold_result(
            scoped_plan=plan,
            job_id=str(proof["job_id"]),
            job_hash=str(proof["job_hash"]),
            measurement_sha256="b" * 64,
        )
        self.assertEqual(len(result["observations"]), 6)
        adjudication = adjudicate_validation_measurement_v2(
            plan.plan,
            measurement,
        )
        facts = {
            "executed_evidence_modes": list(
                FIXED_HOLD_REPLAY_EVIDENCE_MODES
            ),
            "scientific_adjudication": scientific_adjudication_manifest(
                adjudication
            ),
        }
        self.assertEqual(
            validated_fixed_hold_recomputed_criterion_ids(facts),
            tuple(
                sorted(
                    str(item["criterion_id"])
                    for item in FIXED_HOLD_REPLAY_CRITERIA
                )
            ),
        )
        forged = {
            **facts,
            "scientific_adjudication": {
                **facts["scientific_adjudication"],
                "evaluable": False,
            },
        }
        with self.assertRaisesRegex(ValueError, "not fully evaluable"):
            validated_fixed_hold_recomputed_criterion_ids(forged)

    def test_cache_materialization_is_atomic_and_conflict_intolerant(self) -> None:
        producer = self.plan(self.definition.prospective_executable_ids[0])
        neutral = family_trace(self.definition)
        cache = fixed_hold_family_cache(
            scoped_plan=producer,
            neutral_trace=neutral,
            produced=True,
        )
        with TemporaryDirectory() as root:
            materialize_fixed_hold_cache(
                root,
                scoped_plan=producer,
                content=cache.content,
            )
            target = Path(root) / producer.cache_output_name
            self.assertEqual(target.read_bytes(), cache.content)
            materialize_fixed_hold_cache(
                root,
                scoped_plan=producer,
                content=cache.content,
            )
            target.write_bytes(b"forged")
            with self.assertRaisesRegex(ValueError, "different bytes"):
                materialize_fixed_hold_cache(
                    root,
                    scoped_plan=producer,
                    content=cache.content,
                )

    def test_consumer_reconstructs_and_verifies_exact_producer_execution(
        self,
    ) -> None:
        writer = _Writer()
        producer = self.plan(self.definition.prospective_executable_ids[0])
        consumer = self.plan(self.definition.prospective_executable_ids[1])
        neutral = family_trace(self.definition)
        producer_trace = bind_fixed_hold_family_trace(
            family_trace=neutral,
            definition=self.definition,
            validator=FIXED_HOLD_TRACE_VALIDATOR,
            mission_id="MIS-9001",
            executable_id=producer.executable_id,
            job_id=execution().job_id,
            job_hash=execution().job_hash,
        )
        trace_hash = writer.evidence.finalize(
            canonical_bytes(producer_trace)
        ).sha256
        cache = fixed_hold_family_cache(
            scoped_plan=producer,
            neutral_trace=neutral,
            produced=True,
        )
        provenance = build_fixed_hold_cache_provenance(
            scoped_plan=producer,
            execution=execution(),
            cache_sha256=cache.sha256,
            producer_trace_sha256=trace_hash,
        )
        provenance_hash = writer.evidence.finalize(
            canonical_bytes(provenance)
        ).sha256
        inputs = consumer.job_input_hashes(
            cache_sha256=cache.sha256,
            cache_provenance_sha256=provenance_hash,
            producer_trace_sha256=trace_hash,
        )
        verified, observed_provenance, observed_trace, _ = (
            verify_fixed_hold_cache_producer(
                writer,  # type: ignore[arg-type]
                scoped_plan=consumer,
                repository_root=Path("unused"),
                input_hashes=inputs,
                expected_callable_identity="fixture.fixed_hold.job",
                materialize_missing=False,
            )
        )
        self.assertEqual(verified.sha256, cache.sha256)
        self.assertEqual(observed_provenance, provenance_hash)
        self.assertEqual(observed_trace, trace_hash)
        self.assertEqual(writer.evidence.read_counts[provenance_hash], 1)
        self.assertEqual(writer.evidence.read_counts[trace_hash], 1)
        self.assertEqual(len(writer.producer_calls), 1)
        producer_execution, arguments = writer.producer_calls[0]
        self.assertEqual(producer_execution, execution())
        self.assertEqual(
            arguments["expected_output_classes"],
            producer.expected_output_classes(),
        )

        forged = dict(provenance)
        forged["producer_executable_id"] = consumer.executable_id
        forged_hash = writer.evidence.finalize(canonical_bytes(forged)).sha256
        forged_inputs = consumer.job_input_hashes(
            cache_sha256=cache.sha256,
            cache_provenance_sha256=forged_hash,
            producer_trace_sha256=trace_hash,
        )
        with self.assertRaisesRegex(ValueError, "out of scope"):
            verify_fixed_hold_cache_producer(
                writer,  # type: ignore[arg-type]
                scoped_plan=consumer,
                repository_root=Path("unused"),
                input_hashes=forged_inputs,
                expected_callable_identity="fixture.fixed_hold.job",
                materialize_missing=False,
            )

    def test_consumer_accepts_exact_shared_trace_cache_identity(self) -> None:
        writer = _Writer()
        producer = self.plan(self.definition.prospective_executable_ids[0])
        consumer = self.plan(self.definition.prospective_executable_ids[1])
        neutral = family_trace(self.definition)
        trace_hash = writer.evidence.finalize(canonical_bytes(neutral)).sha256
        cache = fixed_hold_family_cache(
            scoped_plan=producer,
            neutral_trace=neutral,
            produced=True,
        )
        self.assertEqual(trace_hash, cache.sha256)
        provenance = build_fixed_hold_cache_provenance(
            scoped_plan=producer,
            execution=execution(),
            cache_sha256=cache.sha256,
            producer_trace_sha256=trace_hash,
        )
        provenance_hash = writer.evidence.finalize(
            canonical_bytes(provenance)
        ).sha256
        inputs = consumer.job_input_hashes(
            cache_sha256=cache.sha256,
            cache_provenance_sha256=provenance_hash,
            producer_trace_sha256=trace_hash,
        )
        self.assertEqual(inputs.count(cache.sha256), 1)
        verified, _, observed_trace, _ = verify_fixed_hold_cache_producer(
            writer,  # type: ignore[arg-type]
            scoped_plan=consumer,
            repository_root=Path("unused"),
            input_hashes=inputs,
            expected_callable_identity="fixture.fixed_hold.job",
            materialize_missing=False,
        )
        self.assertEqual(verified.sha256, cache.sha256)
        self.assertEqual(observed_trace, cache.sha256)
        self.assertEqual(writer.evidence.read_counts[provenance_hash], 1)
        self.assertEqual(writer.evidence.read_counts[trace_hash], 1)

    def test_family_trace_is_stored_once_without_changing_calculation(self) -> None:
        writer = _Writer()
        neutral = family_trace(self.definition)
        neutral_content = canonical_bytes(neutral)
        shared_hash = sha256(neutral_content).hexdigest()
        trace_hashes: set[str] = set()
        legacy_trace_bytes = 0

        for ordinal, executable_id in enumerate(
            self.definition.prospective_executable_ids,
            start=1,
        ):
            plan = self.plan(executable_id)
            job_execution = scoped_execution(ordinal)
            subject = bind_fixed_hold_family_trace(
                family_trace=neutral,
                definition=self.definition,
                validator=FIXED_HOLD_TRACE_VALIDATOR,
                mission_id=plan.mission_id,
                executable_id=executable_id,
                job_id=job_execution.job_id,
                job_hash=job_execution.job_hash,
            )
            legacy_trace_bytes += len(canonical_bytes(subject))
            outputs, _ = materialize_fixed_hold_evidence(
                writer=writer,  # type: ignore[arg-type]
                scoped_plan=plan,
                execution=job_execution,
                neutral_trace=neutral,
                shared_trace_sha256=shared_hash,
            )
            trace_hash = outputs[plan.output_names["trace"]]
            trace_hashes.add(trace_hash)
            calculation_value = parse_canonical(
                writer.evidence.read_verified(
                    outputs[plan.output_names["calculation"]]
                )
            )
            self.assertIsInstance(calculation_value, dict)
            calculation_proof = dict(calculation_value)
            legacy = build_fixed_hold_trace_calculation(
                trace=subject,
                definition=self.definition,
                validator=FIXED_HOLD_TRACE_VALIDATOR,
                trace_output_name=plan.output_names["trace"],
                trace_hash=sha256(canonical_bytes(subject)).hexdigest(),
            )
            self.assertEqual(calculation_proof["metrics"], legacy["metrics"])
            self.assertEqual(
                calculation_proof["statistics"],
                legacy["statistics"],
            )
            expected_shared = {
                **legacy,
                "trace": {
                    "output_name": plan.output_names["trace"],
                    "sha256": shared_hash,
                },
            }
            self.assertEqual(
                canonical_bytes(calculation_proof),
                canonical_bytes(expected_shared),
            )
            self.assertEqual(
                sha256(canonical_bytes(calculation_proof["metrics"])).hexdigest(),
                EXPECTED_METRICS_SHA256[ordinal - 1],
            )
            self.assertEqual(
                sha256(
                    canonical_bytes(calculation_proof["statistics"])
                ).hexdigest(),
                EXPECTED_STATISTICS_SHA256[ordinal - 1],
            )
            self.assertEqual(
                validate_fixed_hold_shared_trace_calculation(
                    trace=neutral,
                    calculation=calculation_proof,
                    definition=self.definition,
                ),
                legacy["metrics"],
            )

        self.assertEqual(trace_hashes, {shared_hash})
        self.assertEqual(writer.evidence.artifacts[shared_hash], neutral_content)
        self.assertGreater(legacy_trace_bytes, len(neutral_content) * 3)
        self.assertLess(
            len(writer.evidence.artifacts[shared_hash]),
            legacy_trace_bytes // 3,
        )

        plan = self.plan(self.definition.prospective_executable_ids[-1])
        proof = build_fixed_hold_shared_trace_calculation(
            trace=neutral,
            definition=self.definition,
            mission_id=plan.mission_id,
            executable_id=plan.executable_id,
            job_id=execution().job_id,
            job_hash=execution().job_hash,
            trace_output_name=plan.output_names["trace"],
            trace_hash=shared_hash,
        )
        forged = {
            **proof,
            "trace": {
                **proof["trace"],
                "sha256": "0" * 64,
            },
        }
        with self.assertRaisesRegex(ScientificTraceError, "shared family trace"):
            validate_fixed_hold_shared_trace_calculation(
                trace=neutral,
                calculation=forged,
                definition=self.definition,
            )

    def test_each_producer_and_validator_boundary_scans_family_once(self) -> None:
        writer = _Writer()
        neutral = family_trace(self.definition)
        trace_hash = sha256(canonical_bytes(neutral)).hexdigest()
        plan = self.plan(self.definition.prospective_executable_ids[-1])
        job_execution = scoped_execution(4)
        snapshots = []
        bind_snapshot = (
            fixed_hold_shared_trace_module.bind_fixed_hold_family_trace_snapshot
        )

        def capture_snapshot(**kwargs):
            snapshot = bind_snapshot(**kwargs)
            snapshots.append(snapshot.family)
            return snapshot

        with (
            patch.object(
                fixed_hold_trace_module,
                "_validated_family_trace_parts",
                wraps=fixed_hold_trace_module._validated_family_trace_parts,
            ) as full_scan,
            patch.object(
                fixed_hold_shared_trace_module,
                "bind_fixed_hold_family_trace_snapshot",
                side_effect=capture_snapshot,
            ),
            patch.object(
                FixedHoldFamilyTraceSnapshot,
                "to_dict",
                autospec=True,
                wraps=FixedHoldFamilyTraceSnapshot.to_dict,
            ) as family_to_dict,
            patch.object(
                FixedHoldSubjectTraceSnapshot,
                "to_dict",
                autospec=True,
                wraps=FixedHoldSubjectTraceSnapshot.to_dict,
            ) as subject_to_dict,
        ):
            cache = fixed_hold_family_cache(
                scoped_plan=plan,
                neutral_trace=neutral,
                produced=False,
            )
            outputs, _ = materialize_fixed_hold_evidence(
                writer=writer,  # type: ignore[arg-type]
                scoped_plan=plan,
                execution=job_execution,
                neutral_trace=cache.trace(self.definition),
                shared_trace_sha256=trace_hash,
            )
            self.assertEqual(full_scan.call_count, 1)
            self.assertEqual(family_to_dict.call_count, 0)
            self.assertEqual(subject_to_dict.call_count, 0)
            opened_trace = parse_canonical(
                writer.evidence.read_verified(outputs[plan.output_names["trace"]])
            )
            calculation_proof = parse_canonical(
                writer.evidence.read_verified(
                    outputs[plan.output_names["calculation"]]
                )
            )
            self.assertIsInstance(opened_trace, dict)
            self.assertIsInstance(calculation_proof, dict)
            validated_modes = validate_shared_pair(
                trace=opened_trace,
                calculation_proof=calculation_proof,
                plan=plan,
                job_execution=job_execution,
                trace_hash=trace_hash,
            )
            self.assertEqual(full_scan.call_count, 2)
            self.assertEqual(family_to_dict.call_count, 0)
            self.assertEqual(subject_to_dict.call_count, 0)

        self.assertEqual(
            validated_modes,
            FIXED_HOLD_REPLAY_EVIDENCE_MODES,
        )
        self.assertEqual(len(snapshots), 2)
        self.assertIsNot(snapshots[0], snapshots[1])
        self.assertEqual(snapshots[0].sha256, snapshots[1].sha256)

        forged = deepcopy(neutral)
        forged["trade_observations"][0][
            "native_net_pnl_micropoints"
        ] += 1
        with self.assertRaises(ScientificTraceError):
            validate_shared_pair(
                trace=forged,
                calculation_proof=calculation_proof,
                plan=plan,
                job_execution=job_execution,
                trace_hash=trace_hash,
            )

        detached = snapshots[0].to_dict()
        detached["trade_observations"][0][
            "native_net_pnl_micropoints"
        ] += 1
        with self.assertRaises(TypeError):
            replace(snapshots[0], _normalized=detached)
        with self.assertRaises(TypeError):
            replace(snapshots[0], _parts={"daily": {}})
        with self.assertRaisesRegex(ScientificTraceError, "payload is invalid"):
            replace(snapshots[0], _payload={"parts": {}})

        other_definition = replace(
            self.definition,
            dataset_sha256=sha256(b"different-valid-dataset").hexdigest(),
        )
        other_snapshot = validate_fixed_hold_family_trace_snapshot(
            family_trace(other_definition),
            definition=other_definition,
            validator=FIXED_HOLD_TRACE_VALIDATOR,
        )
        self.assertNotEqual(snapshots[0].sha256, other_snapshot.sha256)
        with self.assertRaisesRegex(ScientificTraceError, "payload binding"):
            replace(snapshots[0], _payload=other_snapshot._payload)
        self.assertEqual(
            validate_shared_pair(
                trace=snapshots[0],
                calculation_proof=calculation_proof,
                plan=plan,
                job_execution=job_execution,
                trace_hash=trace_hash,
            ),
            FIXED_HOLD_REPLAY_EVIDENCE_MODES,
        )


if __name__ == "__main__":
    unittest.main()
