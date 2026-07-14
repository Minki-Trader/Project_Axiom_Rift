from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.writer import RunningJobExecution
from axiom_rift.research.fixed_hold_family_job import (
    FIXED_HOLD_CACHE_PROVENANCE_SCHEMA,
    build_fixed_hold_cache_provenance,
    build_fixed_hold_family_job_plan,
    build_fixed_hold_measurement,
    build_fixed_hold_result,
    fixed_hold_family_cache,
    fixed_hold_multiplicity_registrations,
    materialize_fixed_hold_cache,
    validate_fixed_hold_cache_provenance,
    verify_fixed_hold_cache_producer,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FIXED_HOLD_TRACE_VALIDATOR,
    bind_fixed_hold_family_trace,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_V2_SYNCHRONIZED_MAX_METHOD,
)
from tests.research.test_fixed_hold_family_trace import (
    calculation,
    definition,
    family_trace,
    subject_trace,
)


NAMESPACE = "test-fixed-hold-family"


class _EvidenceStore:
    def __init__(self) -> None:
        self.artifacts: dict[str, bytes] = {}

    def finalize(self, content: bytes) -> SimpleNamespace:
        from hashlib import sha256

        identity = sha256(content).hexdigest()
        self.artifacts[identity] = content
        return SimpleNamespace(sha256=identity)

    def read_verified(self, identity: str) -> bytes:
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


class FixedHoldFamilyJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.definition = definition()

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


if __name__ == "__main__":
    unittest.main()
