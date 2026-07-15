from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.writer import RunningJobExecution
from axiom_rift.operations.running_job_context import (
    running_job_execution_context_dependency_paths,
)
from axiom_rift.research import analog_state_scoped_job as scoped_job
from axiom_rift.research.implementation_closure import (
    ImplementationClosureError,
    require_current_job_source_closure,
)
from axiom_rift.research.analog_state_family import (
    analog_family_executable,
)
from axiom_rift.research.historical_analog_family_stu0061 import (
    STU0061_ANALOG_FAMILY as P1_STU0061_ANALOG_FAMILY,
)
from axiom_rift.research.analog_state_replay_v2 import (
    ANALOG_SCOPED_QUERY_SCOPE_ID,
    analog_family_executable_scoped_v2,
    analog_family_trace_v2_implementation_identities,
    expected_analog_family_inventory_scoped_v2,
    validate_analog_family_trace_scoped_v2,
)
from axiom_rift.research.analog_state_trace import (
    ANALOG_FAMILY_TRACE_SCHEMA,
    ANALOG_REPLAY_CLAIMS,
    ANALOG_REPLAY_CONTROLS,
    ANALOG_REPLAY_CRITERIA,
    ANALOG_REPLAY_TRACE_ATTRIBUTION,
    analog_family_execution_contracts,
    analog_original_family_provenance,
    expected_analog_family_inventory,
)
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
)
from axiom_rift.research.scientific_trace import (
    ANALOG_SCOPED_TRACE_PROTOCOL_ID,
    ANALOG_STATE_TRACE_PROTOCOL_ID,
    ATOMIC_TRACE_PROOF_KIND,
    CALCULATION_PROOF_KIND,
    SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
    SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
    ScientificTraceError,
    trace_proof_kinds,
    validate_trace_calculation_pair,
)


MISSION_ID = "MIS-SCOPED-ANALOG"
STUDY_ID = "STU-SCOPED-ANALOG"


class _FakeEvidenceStore:
    def __init__(self) -> None:
        self.artifacts: dict[str, bytes] = {}

    def finalize(self, content: bytes) -> SimpleNamespace:
        identity = sha256(content).hexdigest()
        self.artifacts[identity] = content
        return SimpleNamespace(sha256=identity)

    def read_verified(self, identity: str) -> bytes:
        try:
            content = self.artifacts[identity]
        except KeyError as exc:
            raise FileNotFoundError(identity) from exc
        if sha256(content).hexdigest() != identity:
            raise RuntimeError("fake evidence hash drifted")
        return content


class _FakeWriter:
    def __init__(self) -> None:
        self.evidence = _FakeEvidenceStore()
        self.running_bindings: dict[str, dict[str, object]] = {}
        self.producer_calls: list[
            tuple[RunningJobExecution, dict[str, object]]
        ] = []

    def verify_running_job_execution(
        self,
        execution: RunningJobExecution,
        *,
        expected_callable_identity: str,
    ) -> dict[str, object]:
        if expected_callable_identity != scoped_job.CALLABLE_IDENTITY:
            raise AssertionError("callable identity drifted")
        return self.running_bindings[execution.job_id]

    def verify_reproducible_cache_producer(
        self,
        producer: RunningJobExecution,
        **kwargs: object,
    ) -> None:
        self.producer_calls.append((producer, dict(kwargs)))


def _neutral_scoped_trace() -> dict[str, object]:
    contracts = analog_family_execution_contracts(
        P1_STU0061_ANALOG_FAMILY
    )
    return {
        "attribution": ANALOG_REPLAY_TRACE_ATTRIBUTION,
        "clock_contract": contracts["clock_contract"],
        "controls": ANALOG_REPLAY_CONTROLS,
        "cost_contract": contracts["cost_contract"],
        "dataset_sha256": DATASET_SHA256,
        "eligible_day_observations": [],
        "family_id": P1_STU0061_ANALOG_FAMILY.family_id,
        "implementation_identities": (
            analog_family_trace_v2_implementation_identities()
        ),
        "intent_observations": [],
        "invariance_comparisons": [],
        "material_identity": OBSERVED_MATERIAL_ID,
        "ordered_family": list(
            expected_analog_family_inventory_scoped_v2(
                P1_STU0061_ANALOG_FAMILY
            )
        ),
        "original_family_provenance": analog_original_family_provenance(
            P1_STU0061_ANALOG_FAMILY
        ),
        "protocol_id": ANALOG_STATE_TRACE_PROTOCOL_ID,
        "schema": ANALOG_FAMILY_TRACE_SCHEMA,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "trade_observations": [],
        "windows": [],
    }


def _fixture_scoped_trace_validator(
    value: object,
    *,
    family: object,
    original_family_provenance: object,
) -> dict[str, object]:
    normalized = parse_canonical(canonical_bytes(value))
    if not isinstance(normalized, dict):
        raise ValueError("fixture scoped trace is not an object")
    if family != P1_STU0061_ANALOG_FAMILY:
        raise ValueError("fixture scoped family binding drifted")
    if original_family_provenance != analog_original_family_provenance(
        P1_STU0061_ANALOG_FAMILY
    ):
        raise ValueError("fixture scoped provenance drifted")
    if normalized.get("ordered_family") != list(
        expected_analog_family_inventory_scoped_v2(
            P1_STU0061_ANALOG_FAMILY
        )
    ):
        raise ValueError("fixture scoped inventory drifted")
    if normalized.get("implementation_identities") != (
        analog_family_trace_v2_implementation_identities()
    ):
        raise ValueError("fixture scoped implementation drifted")
    return normalized


def _passing_metrics() -> dict[str, dict[str, int]]:
    metrics: dict[str, dict[str, int]] = {
        claim_id: {} for claim_id in ANALOG_REPLAY_CLAIMS
    }
    for criterion in ANALOG_REPLAY_CRITERIA:
        operator = str(criterion["operator"])
        threshold = int(criterion["threshold"])
        if operator in {"gt", "ge"}:
            value = threshold + 1
        elif operator == "le":
            value = 0
        elif operator == "eq":
            value = threshold
        else:
            raise AssertionError(operator)
        metrics[str(criterion["claim_id"])][str(criterion["metric"])] = value
    return metrics


def _fixture_inference_manifest(
    *,
    family_id: str,
    member_ids: tuple[str, ...],
    subject_id: str,
    raw_pvalue_ppm: int = 0,
    adjusted_pvalue_ppm: int = 0,
) -> dict[str, object]:
    members = tuple(sorted(member_ids))
    if subject_id not in members:
        raise AssertionError("fixture inference subject is outside its family")
    hypotheses = [
        {
            "family_id": family_id,
            "family_size": len(members),
            "familywise": {
                "synchronized_max": {
                    "monte_carlo_upper_pvalue_ppm": (
                        adjusted_pvalue_ppm if member_id == subject_id else 0
                    )
                }
            },
            "hypothesis_id": member_id,
            "raw": {
                "monte_carlo_upper_pvalue_ppm": (
                    raw_pvalue_ppm if member_id == subject_id else 0
                )
            },
        }
        for member_id in members
    ]
    return {
        "hypotheses": hypotheses,
        "plan": {
            "family_id": family_id,
            "family_size": len(members),
            "hypotheses": [
                {"hypothesis_id": member_id} for member_id in members
            ],
        },
    }


def _fixture_calculation(
    *,
    trace: dict[str, object],
    trace_output_name: str,
    trace_hash: str,
) -> dict[str, object]:
    subject_id = str(trace["subject_executable_id"])
    configuration = next(
        configuration
        for configuration in P1_STU0061_ANALOG_FAMILY.configurations()
        if analog_family_executable_scoped_v2(configuration).identity
        == subject_id
    )
    projected_subject_id = analog_family_executable(configuration).identity
    projected_family_ids = tuple(
        analog_family_executable(item).identity
        for item in P1_STU0061_ANALOG_FAMILY.configurations()
    )
    metrics = _passing_metrics()
    return {
        "evidence_modes": list(scoped_job.ANALOG_REPLAY_EVIDENCE_MODES),
        "executable_id": subject_id,
        "job_hash": trace["job_hash"],
        "job_id": trace["job_id"],
        "metrics": metrics,
        "mission_id": trace["mission_id"],
        "parameters": {"fixture": True},
        "protocol_id": scoped_job.ANALOG_SCOPED_TRACE_PROTOCOL_ID,
        "schema": SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
        "statistics": {
            "paired_control_family": _fixture_inference_manifest(
                family_id=(
                    f"family:{configuration.configuration_id}:"
                    "paired-controls-v1"
                ),
                member_ids=(
                    "paired-control:feature",
                    "paired-control:opposite",
                ),
                subject_id="paired-control:opposite",
            ),
            "selection_family": _fixture_inference_manifest(
                family_id=P1_STU0061_ANALOG_FAMILY.family_id,
                member_ids=projected_family_ids,
                subject_id=projected_subject_id,
            ),
        },
        "trace": {
            "output_name": trace_output_name,
            "sha256": trace_hash,
        },
    }


def _execution(marker: str) -> RunningJobExecution:
    return RunningJobExecution(
        job_id="job:" + marker * 64,
        job_hash=chr(ord(marker) + 1) * 64,
        job_permit_id=chr(ord(marker) + 2) * 64,
        start_record_id=chr(ord(marker) + 3) * 64,
    )


def _binding(
    *,
    plan: scoped_job.AnalogStateScopedJobPlan,
    execution: RunningJobExecution,
    input_hashes: tuple[str, ...],
    produce_cache: bool,
) -> dict[str, object]:
    return {
        "execution": execution.payload(),
        "mission_id": plan.mission_id,
        "study_id": plan.study_id,
        "spec": {
            "callable_identity": scoped_job.CALLABLE_IDENTITY,
            "evidence_subject": {
                "kind": "Executable",
                "id": plan.executable_id,
            },
            "expected_outputs": list(
                plan.expected_outputs(produce_family_cache=produce_cache)
            ),
            "implementation_identity": (
                scoped_job.analog_scoped_job_implementation_sha256()
            ),
            "input_hashes": list(input_hashes),
            "output_classes": plan.expected_output_classes(
                produce_family_cache=produce_cache
            ),
            "scientific_binding": plan.scientific_binding(),
        },
    }


class AnalogStateScopedJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inventory = expected_analog_family_inventory_scoped_v2(
            P1_STU0061_ANALOG_FAMILY
        )
        self.producer_id = str(self.inventory[0]["executable_id"])
        self.consumer_id = str(self.inventory[1]["executable_id"])

    def test_plan_uses_only_scoped_v2_inventory_and_atomic_proofs(self) -> None:
        plan = scoped_job.build_analog_state_scoped_plan(
            mission_id=MISSION_ID,
            study_id=STUDY_ID,
            executable_id=self.producer_id,
        )
        scoped_ids = {str(item["executable_id"]) for item in self.inventory}
        v1_ids = {
            str(item["executable_id"])
            for item in expected_analog_family_inventory()
        }
        self.assertEqual(len(scoped_ids), 4)
        self.assertTrue(scoped_ids.isdisjoint(v1_ids))
        self.assertIn(plan.executable_id, scoped_ids)
        self.assertFalse(plan.plan["candidate_eligible_on_pass"])
        registrations = {
            item["criterion_id"]: item
            for item in plan.plan["adjudication_profile"]["multiplicity"]
        }
        paired = registrations["D02-opposite-sign-uncertainty"]
        selection = registrations["E01-familywise-selection"]
        self.assertEqual(paired["family_size"], 2)
        self.assertEqual(
            paired["ordered_member_ids"],
            ["paired-control:feature", "paired-control:opposite"],
        )
        self.assertEqual(selection["family_size"], 4)
        self.assertEqual(
            selection["ordered_member_ids"],
            [str(item["executable_id"]) for item in self.inventory],
        )
        self.assertEqual(selection["member_id"], self.producer_id)
        self.assertEqual(
            {item["method"] for item in registrations.values()},
            {"synchronized_max_moving_block_familywise.v1"},
        )
        self.assertEqual(len(plan.plan["proof_requirements"]), 8)
        self.assertEqual(
            {
                item["proof_kind"]
                for item in plan.plan["proof_requirements"]
            },
            {ATOMIC_TRACE_PROOF_KIND, CALCULATION_PROOF_KIND},
        )
        self.assertEqual(
            plan.expected_output_classes(produce_family_cache=True)[
                scoped_job.analog_scoped_family_trace_cache_output_name()
            ],
            "reproducible_cache",
        )
        self.assertEqual(len(plan.expected_outputs()), 5)
        self.assertEqual(len(plan.expected_outputs(produce_family_cache=True)), 6)
        self.assertIn(
            scoped_job.analog_scoped_job_implementation_sha256(),
            plan.job_input_hashes(),
        )

    def test_implementation_manifest_binds_narrow_running_job_context(
        self,
    ) -> None:
        writer = _FakeWriter()
        identity = scoped_job.materialize_analog_scoped_job_implementation(
            writer
        )
        self.assertEqual(
            identity,
            scoped_job.analog_scoped_job_implementation_sha256(),
        )
        manifest = parse_canonical(writer.evidence.read_verified(identity))
        self.assertEqual(
            manifest,
            parse_canonical(
                scoped_job.analog_scoped_job_implementation_artifact()
            ),
        )
        dependency_paths = set(scoped_job.analog_scoped_job_dependency_paths())
        self.assertTrue(
            set(running_job_execution_context_dependency_paths()).issubset(
                dependency_paths
            )
        )
        writer_path = (
            Path(scoped_job.__file__).resolve().parents[1]
            / "operations"
            / "writer.py"
        )
        self.assertNotIn(writer_path, dependency_paths)
        expected_hashes = {
            sha256(
                scoped_job.analog_scoped_job_source_closure_artifact()
            ).hexdigest(),
            *(
                sha256(path.read_bytes()).hexdigest()
                for path in dependency_paths
            ),
        }
        self.assertEqual(set(manifest["artifact_hashes"]), expected_hashes)
        self.assertTrue(expected_hashes.issubset(writer.evidence.artifacts))

        with self.assertRaisesRegex(
            ImplementationClosureError,
            "reconstruction-only.*analog_state_scoped_job.py",
        ):
            require_current_job_source_closure(
                callable_identity=scoped_job.CALLABLE_IDENTITY,
                job_artifact_hashes=tuple(manifest["artifact_hashes"]),
                artifact_reader=writer.evidence.read_verified,
                source_root=Path(__file__).resolve().parents[2] / "src",
            )

    def test_measurement_preserves_raw_and_adjusted_scoped_family_values(
        self,
    ) -> None:
        plan = scoped_job.build_analog_state_scoped_plan(
            mission_id=MISSION_ID,
            study_id=STUDY_ID,
            executable_id=self.producer_id,
        )
        execution = _execution("1")
        trace = {
            "job_hash": execution.job_hash,
            "job_id": execution.job_id,
            "mission_id": MISSION_ID,
            "subject_executable_id": self.producer_id,
        }
        calculation = _fixture_calculation(
            trace=trace,
            trace_output_name=plan.output_names["trace"],
            trace_hash="a" * 64,
        )
        statistics = calculation["statistics"]
        metrics = calculation["metrics"]
        expected = {
            "D02-opposite-sign-uncertainty": (12_345, 45_678),
            "E01-familywise-selection": (23_456, 56_789),
        }
        for criterion_id, (raw, adjusted) in expected.items():
            if criterion_id.startswith("D02"):
                manifest = statistics["paired_control_family"]
                member_id = "paired-control:opposite"
                metrics["registered_control_contrast"][
                    "opposite_sign_pvalue_upper_ppm"
                ] = adjusted
            else:
                manifest = statistics["selection_family"]
                configuration = P1_STU0061_ANALOG_FAMILY.configurations()[0]
                member_id = analog_family_executable(configuration).identity
                metrics["selection_aware_signal_evidence"][
                    "selection_aware_pvalue_ppm"
                ] = adjusted
            hypothesis = next(
                item
                for item in manifest["hypotheses"]
                if item["hypothesis_id"] == member_id
            )
            hypothesis["raw"]["monte_carlo_upper_pvalue_ppm"] = raw
            hypothesis["familywise"]["synchronized_max"][
                "monte_carlo_upper_pvalue_ppm"
            ] = adjusted
        measurement = scoped_job.build_analog_scoped_measurement(
            scoped_plan=plan,
            job_id=execution.job_id,
            job_hash=execution.job_hash,
            calculation=calculation,
            trace_hash="a" * 64,
            calculation_hash="b" * 64,
        )
        observed = {
            item["criterion_id"]: (
                item["raw_pvalue_ppm"],
                item["adjusted_pvalue_ppm"],
            )
            for item in measurement["multiplicity"]
        }
        self.assertEqual(observed, expected)

    def test_cache_and_producer_trace_hashes_are_one_atomic_input_pair(self) -> None:
        plan = scoped_job.build_analog_state_scoped_plan(
            mission_id=MISSION_ID,
            study_id=STUDY_ID,
            executable_id=self.consumer_id,
        )
        cache_hash = "a" * 64
        producer_trace_hash = "b" * 64
        inputs = plan.job_input_hashes(
            family_trace_cache_hash=cache_hash,
            producer_trace_hash=producer_trace_hash,
        )
        self.assertEqual(inputs.count(cache_hash), 1)
        self.assertEqual(inputs.count(producer_trace_hash), 1)
        with self.assertRaisesRegex(ValueError, "inseparable"):
            plan.job_input_hashes(family_trace_cache_hash=cache_hash)
        with self.assertRaisesRegex(ValueError, "must differ"):
            plan.job_input_hashes(
                family_trace_cache_hash=cache_hash,
                producer_trace_hash=cache_hash,
            )

    def test_frozen_v1_inventory_cannot_be_relabelled_as_scoped_v2(self) -> None:
        relabelled = _neutral_scoped_trace()
        relabelled["ordered_family"] = list(expected_analog_family_inventory())
        with self.assertRaisesRegex(ValueError, "scoped v2 family inventory"):
            validate_analog_family_trace_scoped_v2(
                relabelled,
                family=P1_STU0061_ANALOG_FAMILY,
                original_family_provenance=(
                    analog_original_family_provenance(
                        P1_STU0061_ANALOG_FAMILY
                    )
                ),
            )

    def test_calculation_projection_is_transparent_and_never_evidence(self) -> None:
        producer_plan = scoped_job.build_analog_state_scoped_plan(
            mission_id=MISSION_ID,
            study_id=STUDY_ID,
            executable_id=self.producer_id,
        )
        execution = _execution("1")
        neutral = _neutral_scoped_trace()
        content = canonical_bytes(neutral)
        with patch.object(
            scoped_job,
            "validate_analog_family_trace_scoped_v2",
            side_effect=_fixture_scoped_trace_validator,
        ):
            manifest = scoped_job.build_analog_scoped_cache_manifest(
                scoped_plan=producer_plan,
                execution=execution,
                cache_sha256=sha256(content).hexdigest(),
            )
            trace = scoped_job.bind_analog_scoped_family_trace(
                family_trace=neutral,
                mission_id=MISSION_ID,
                executable_id=self.producer_id,
                job_id=execution.job_id,
                job_hash=execution.job_hash,
                cache_manifest=manifest,
            )
            legacy_metrics = _passing_metrics()
            projected = {"schema": "internal-projected-v1"}
            with patch.object(
                scoped_job.replay_v2,
                "_project_analog_v2_trace_to_v1",
                return_value=projected,
            ) as project, patch.object(
                scoped_job,
                "bind_analog_family_trace",
                return_value={"schema": "internal-bound-v1"},
            ) as bind_v1, patch.object(
                scoped_job,
                "build_analog_trace_calculation",
                return_value={
                    "metrics": legacy_metrics,
                    "statistics": {"legacy_formula": "recomputed"},
                },
            ):
                trace_hash = sha256(canonical_bytes(trace)).hexdigest()
                calculation = scoped_job.build_analog_scoped_calculation(
                    trace=trace,
                    trace_output_name=producer_plan.output_names["trace"],
                    trace_hash=trace_hash,
                )
                validated = (
                    scoped_job.validate_analog_scoped_trace_calculation(
                        trace=trace,
                        calculation=calculation,
                    )
                )
        configuration = P1_STU0061_ANALOG_FAMILY.configurations()[0]
        projected_subject = analog_family_executable(configuration).identity
        self.assertEqual(calculation["executable_id"], self.producer_id)
        self.assertEqual(
            calculation["protocol_id"],
            scoped_job.ANALOG_SCOPED_TRACE_PROTOCOL_ID,
        )
        provenance = calculation["statistics"]["scoped_query_projection"]
        self.assertFalse(provenance["claim_authority"])
        self.assertFalse(provenance["emitted_as_evidence"])
        self.assertEqual(
            provenance["projected_v1_subject_executable_id"],
            projected_subject,
        )
        self.assertEqual(
            provenance["source_scoped_executable_id"],
            self.producer_id,
        )
        self.assertEqual(validated, legacy_metrics)
        self.assertTrue(all(call.kwargs["scoped"] for call in project.call_args_list))
        self.assertTrue(
            all(
                call.kwargs["executable_id"] == projected_subject
                for call in bind_v1.call_args_list
            )
        )
        drifted = {**calculation, "protocol_id": ANALOG_STATE_TRACE_PROTOCOL_ID}
        with self.assertRaises(ScientificTraceError):
            scoped_job.validate_analog_scoped_trace_calculation(
                trace=trace,
                calculation=drifted,
            )

    def test_producer_computes_once_and_consumer_recovers_only_from_trace(
        self,
    ) -> None:
        writer = _FakeWriter()
        neutral = _neutral_scoped_trace()
        producer_plan = scoped_job.build_analog_state_scoped_plan(
            mission_id=MISSION_ID,
            study_id=STUDY_ID,
            executable_id=self.producer_id,
        )
        producer_execution = _execution("1")
        writer.running_bindings[producer_execution.job_id] = _binding(
            plan=producer_plan,
            execution=producer_execution,
            input_hashes=producer_plan.job_input_hashes(),
            produce_cache=True,
        )
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with patch.object(
                scoped_job,
                "RunningJobExecutionContext",
                return_value=writer,
            ), patch.object(
                scoped_job,
                "validate_analog_family_trace_scoped_v2",
                side_effect=_fixture_scoped_trace_validator,
            ), patch.object(
                scoped_job,
                "compute_analog_family_trace_scoped_v2",
                return_value=(neutral, {}),
            ) as compute, patch.object(
                scoped_job,
                "build_analog_scoped_calculation",
                side_effect=_fixture_calculation,
            ):
                producer_packet = scoped_job.execute_analog_state_scoped_job(
                    repository_root=root,
                    execution=producer_execution,
                )
            self.assertEqual(compute.call_count, 1)
            producer_outputs = producer_packet.outputs()
            cache_name = scoped_job.analog_scoped_family_trace_cache_output_name()
            cache_hash = producer_outputs[cache_name]
            producer_trace_hash = producer_outputs[
                producer_plan.output_names["trace"]
            ]
            producer_trace = parse_canonical(
                writer.evidence.read_verified(producer_trace_hash)
            )
            self.assertIsInstance(producer_trace, dict)
            self.assertEqual(
                producer_trace["subject_executable_id"],
                self.producer_id,
            )
            self.assertEqual(
                {
                    item["executable_id"]
                    for item in producer_trace["ordered_family"]
                },
                {
                    item["executable_id"]
                    for item in expected_analog_family_inventory_scoped_v2(
                        P1_STU0061_ANALOG_FAMILY
                    )
                },
            )
            cache_target = root / cache_name
            self.assertTrue(cache_target.is_file())
            cache_target.unlink()

            consumer_plan = scoped_job.build_analog_state_scoped_plan(
                mission_id=MISSION_ID,
                study_id=STUDY_ID,
                executable_id=self.consumer_id,
            )
            consumer_execution = _execution("5")
            consumer_inputs = consumer_plan.job_input_hashes(
                family_trace_cache_hash=cache_hash,
                producer_trace_hash=producer_trace_hash,
            )
            writer.running_bindings[consumer_execution.job_id] = _binding(
                plan=consumer_plan,
                execution=consumer_execution,
                input_hashes=consumer_inputs,
                produce_cache=False,
            )
            with patch.object(
                scoped_job,
                "RunningJobExecutionContext",
                return_value=writer,
            ), patch.object(
                scoped_job,
                "validate_analog_family_trace_scoped_v2",
                side_effect=_fixture_scoped_trace_validator,
            ), patch.object(
                scoped_job,
                "compute_analog_family_trace_scoped_v2",
                side_effect=AssertionError("consumer recomputed scoped family"),
            ) as consumer_compute, patch.object(
                scoped_job,
                "build_analog_scoped_calculation",
                side_effect=_fixture_calculation,
            ):
                consumer_packet = scoped_job.execute_analog_state_scoped_job(
                    repository_root=root,
                    execution=consumer_execution,
                )
            consumer_compute.assert_not_called()
            self.assertTrue(cache_target.is_file())
            self.assertEqual(sha256(cache_target.read_bytes()).hexdigest(), cache_hash)

        self.assertEqual(len(writer.producer_calls), 1)
        observed_execution, arguments = writer.producer_calls[0]
        self.assertEqual(observed_execution, producer_execution)
        self.assertEqual(arguments["cache_hash"], cache_hash)
        self.assertEqual(arguments["manifest_hash"], producer_trace_hash)
        self.assertNotIn(cache_name, consumer_packet.outputs())
        self.assertEqual(
            set(consumer_packet.outputs()),
            set(consumer_plan.expected_outputs()),
        )

    def test_scoped_executable_identity_binds_query_scope(self) -> None:
        configurations = P1_STU0061_ANALOG_FAMILY.configurations()
        scoped_ids = {
            analog_family_executable_scoped_v2(configuration).identity
            for configuration in configurations
        }
        self.assertEqual(
            scoped_ids,
            {str(item["executable_id"]) for item in self.inventory},
        )
        for configuration in configurations:
            executable = analog_family_executable_scoped_v2(configuration)
            self.assertEqual(
                executable.parameter_values()["query_scope_id"],
                ANALOG_SCOPED_QUERY_SCOPE_ID,
            )

    def test_central_atomic_dispatcher_routes_the_scoped_protocol(self) -> None:
        trace_output_name = "scientific/test/scoped-trace.json"
        trace_hash = "a" * 64
        job_hash = "b" * 64
        trace = {
            "adapter_implementation_sha256": "c" * 64,
            "attribution": {},
            "controls": {},
            "dataset_sha256": DATASET_SHA256,
            "eligible_day_observations": [],
            "family_id": P1_STU0061_ANALOG_FAMILY.family_id,
            "invariance_comparisons": [],
            "intent_observations": [],
            "job_hash": job_hash,
            "job_id": "job:scoped-dispatch",
            "material_identity": OBSERVED_MATERIAL_ID,
            "mission_id": MISSION_ID,
            "ordered_family": [],
            "protocol_id": ANALOG_SCOPED_TRACE_PROTOCOL_ID,
            "schema": SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
            "split_artifact_sha256": ROLLING_SPLIT_SHA256,
            "subject_executable_id": self.producer_id,
            "trade_observations": [],
            "windows": [],
        }
        metrics = _passing_metrics()
        calculation = {
            "evidence_modes": list(scoped_job.ANALOG_REPLAY_EVIDENCE_MODES),
            "executable_id": self.producer_id,
            "job_hash": job_hash,
            "job_id": "job:scoped-dispatch",
            "metrics": metrics,
            "mission_id": MISSION_ID,
            "parameters": {},
            "protocol_id": ANALOG_SCOPED_TRACE_PROTOCOL_ID,
            "schema": SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
            "statistics": {},
            "trace": {"output_name": trace_output_name, "sha256": trace_hash},
        }
        self.assertEqual(
            set(
                trace_proof_kinds(
                    protocol_id=ANALOG_SCOPED_TRACE_PROTOCOL_ID,
                    evidence_mode="causal_contrast",
                )
            ),
            {ATOMIC_TRACE_PROOF_KIND, CALCULATION_PROOF_KIND},
        )
        binding = {
            "claim_id": "activity_and_concentration",
            "metric": "trade_count",
            "value": metrics["activity_and_concentration"]["trade_count"],
        }
        with patch.object(
            scoped_job,
            "validate_analog_scoped_trace_calculation",
            return_value=metrics,
        ) as validate:
            modes = validate_trace_calculation_pair(
                trace=trace,
                trace_output_name=trace_output_name,
                trace_hash=trace_hash,
                calculation=calculation,
                expected_evidence_modes=(
                    scoped_job.ANALOG_REPLAY_EVIDENCE_MODES
                ),
                expected_metric_bindings_by_mode={
                    "causal_contrast": (binding,),
                },
                mission_id=MISSION_ID,
                executable_id=self.producer_id,
                job_id="job:scoped-dispatch",
                job_hash=job_hash,
            )
        self.assertEqual(modes, scoped_job.ANALOG_REPLAY_EVIDENCE_MODES)
        validate.assert_called_once_with(trace=trace, calculation=calculation)


if __name__ == "__main__":
    unittest.main()
