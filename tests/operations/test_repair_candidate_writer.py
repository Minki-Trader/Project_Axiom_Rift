from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.permits import (
    PermitAuthority,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.repair_candidate import build_repair_candidate
from axiom_rift.operations.repair_disposition_materializer import (
    materialize_engineering_repair_disposition,
)
from axiom_rift.operations.repair_observation_authority import (
    RepairObservationAuthorityError,
    require_repair_validation_observation_stream,
)
from axiom_rift.operations.repair_validation import (
    build_repair_candidate_validation_context,
    build_repair_candidate_validation_receipt,
    build_repair_validation_plan,
    repair_validation_binding,
)
from axiom_rift.operations.validation import (
    EngineeringRepairValidationRequest,
    EngineeringRepairFixtureValidator,
    EvidenceValidationError,
    EvidenceValidatorRegistry,
    ValidatedEvidence,
    validator_identity,
    validator_implementation_sha256,
)
from axiom_rift.operations.writer import StateWriter, TransitionError
from axiom_rift.storage.state import WriterLock
from tests.operations.test_writer import (
    FIXED_EXPIRY,
    FIXED_NOW,
    OBSERVED_MATERIAL_ID,
    REPO_ROOT,
    batch_spec,
    executable_spec,
    initiative_objective,
    job_spec,
    mission_goal,
    study_question,
)


_THIS_FILE = Path(__file__).resolve()
_PROTOCOL = "repair_candidate_writer_fixture.v1"
_VALIDATOR_ID = validator_identity(
    protocol=_PROTOCOL,
    domains=frozenset({"engineering"}),
    implementation_sha256=validator_implementation_sha256(
        implementation_path=_THIS_FILE
    ),
)


def _plain(value: object) -> object:
    if isinstance(value, dict) or hasattr(value, "items"):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value


class RepairCandidateWriterFixtureValidator:
    validator_id = _VALIDATOR_ID
    domains = frozenset({"engineering"})
    implementation_path = _THIS_FILE
    protocol = _PROTOCOL
    authority_scope = "fixture_only"

    def __init__(self, lock_probe_path: Path | None = None) -> None:
        self._lock_probe_path = lock_probe_path

    def validate(
        self,
        request: EngineeringRepairValidationRequest,
    ) -> ValidatedEvidence:
        if (
            not isinstance(request, EngineeringRepairValidationRequest)
            or not request.engineering_fixture
            or request.verification_kind != "candidate"
            or request.validator_id != self.validator_id
        ):
            raise EvidenceValidationError(
                "candidate Writer fixture request is unauthorized"
            )
        if self._lock_probe_path is not None:
            with WriterLock(self._lock_probe_path, timeout_seconds=1):
                pass
        by_name = {
            artifact.output_name: artifact for artifact in request.artifacts
        }
        if set(by_name) != {"validation_plan", "validation_result"}:
            raise EvidenceValidationError(
                "candidate Writer fixture artifacts are invalid"
            )
        plan = parse_canonical(by_name["validation_plan"].read_bytes())
        result = parse_canonical(by_name["validation_result"].read_bytes())
        binding = _plain(request.binding)
        if (
            not isinstance(binding, dict)
            or not isinstance(plan, dict)
            or not isinstance(result, dict)
            or plan.get("binding_sha256")
            != sha256(canonical_bytes(binding)).hexdigest()
            or result.get("schema")
            != "repair_candidate_writer_fixture_result.v1"
            or result.get("context_sha256")
            != sha256(canonical_bytes(binding.get("context"))).hexdigest()
        ):
            raise EvidenceValidationError(
                "candidate Writer fixture did not recompute its context"
            )
        mode = result.get("mode")
        result_hash = by_name["validation_result"].sha256
        if mode == "partial":
            return ValidatedEvidence(
                verdict="passed",
                measurement_artifact_hashes=(result_hash,),
                artifact_roles=(
                    (
                        "validation_plan",
                        by_name["validation_plan"].sha256,
                    ),
                    ("validation_result", result_hash),
                ),
                facts={"binding": binding, "cause_resolved": False},
            )
        facts_by_mode = {
            "failure_reproduced": (False, True, True, None),
            "invalid_change": (None, None, False, "fixture_invalid_change"),
            "not_evaluable": (
                None,
                None,
                None,
                "fixture_measurement_inconclusive",
            ),
            "repaired": (True, False, True, None),
        }
        if mode not in facts_by_mode:
            raise EvidenceValidationError(
                "candidate Writer fixture mode is invalid"
            )
        cause_resolved, failure_reproduced, material_change, reason = (
            facts_by_mode[mode]
        )
        verdict = {
            "failure_reproduced": "passed",
            "invalid_change": "failed",
            "not_evaluable": "not_evaluable",
            "repaired": "passed",
        }[mode]
        return ValidatedEvidence(
            verdict=verdict,
            measurement_artifact_hashes=(result_hash,),
            artifact_roles=(
                ("validation_plan", by_name["validation_plan"].sha256),
                ("validation_result", result_hash),
            ),
            facts={
                "binding": binding,
                "cause_resolved": cause_resolved,
                "failure_reproduced": failure_reproduced,
                "material_change": material_change,
                "mode": mode,
                "new_failure_manifest_hash": None,
                "reason_code": reason,
            },
        )


class RepairCandidateWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.writer = StateWriter(
            self.temporary.name,
            permit_authority=PermitAuthority(b"c" * 32),
            clock=lambda: FIXED_NOW,
            engineering_fixture=True,
            foundation_root=REPO_ROOT,
            validation_registry=EvidenceValidatorRegistry(
                (
                    RepairCandidateWriterFixtureValidator(),
                    EngineeringRepairFixtureValidator(),
                )
            ),
        )
        self.writer.initialize_ready()
        self.writer.open_mission(
            mission_id="MIS-CANDIDATE-WRITER",
            goal=mission_goal("outcome-free Repair candidates"),
            operation_id="candidate-writer-mission",
        )
        self.writer.open_initiative(
            initiative_id="INI-CANDIDATE-WRITER",
            objective=initiative_objective("outcome-free Repair candidates"),
            operation_id="candidate-writer-initiative",
        )
        question = study_question("outcome-free Repair candidates")
        study_hash = self.writer.study_input_hash(
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            semantic_proposal={"mechanism": "registered candidate evaluation"},
        )
        study_permit = self.writer.issue_permit(
            kind=PermitKind.STUDY,
            subject_kind=SubjectKind.INITIATIVE,
            subject_id="INI-CANDIDATE-WRITER",
            input_hash=study_hash,
            actions=("open_study",),
            scope=("study",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="candidate-writer-study-permit",
        )
        opened = self.writer.open_study(
            study_id="STU-CANDIDATE-WRITER",
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            material_display_name="candidate-writer-fixture",
            semantic_proposal={"mechanism": "registered candidate evaluation"},
            permit=study_permit,
            operation_id="candidate-writer-study",
        )
        batch = batch_spec(
            batch_id="BAT-CANDIDATE-WRITER",
            study_id="STU-CANDIDATE-WRITER",
            study_hash=opened.result["study_hash"],
        )
        batch_permit = self.writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id="STU-CANDIDATE-WRITER",
            input_hash=batch.identity.removeprefix("batch:"),
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="candidate-writer-batch-permit",
        )
        self.writer.open_batch(
            batch_spec=batch,
            permit=batch_permit,
            operation_id="candidate-writer-batch",
        )
        self.writer.register_trial(
            executable=executable_spec("candidate-writer"),
            operation_id="candidate-writer-trial",
        )
        declared = self.writer.declare_job(
            spec=job_spec(
                self.writer,
                evidence_subject={
                    "kind": "Study",
                    "id": "STU-CANDIDATE-WRITER",
                },
            ),
            operation_id="candidate-writer-job",
        )
        self.job_id = str(declared.result["job_id"])
        self.job_hash = str(declared.result["job_hash"])
        start_permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=self.job_id,
            input_hash=self.job_hash,
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="candidate-writer-start-permit",
        )
        repair_permit = self.writer.issue_permit(
            kind=PermitKind.REPAIR,
            subject_kind=SubjectKind.JOB,
            subject_id=self.job_id,
            input_hash=self.job_hash,
            actions=("open_repair",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="candidate-writer-repair-permit",
        )
        self.writer.start_job(
            permit=start_permit,
            operation_id="candidate-writer-start",
        )
        self.reproduction = self.writer.evidence.finalize(
            b"candidate Writer original failure reproduction"
        )
        opened_repair = self.writer.open_repair(
            permit=repair_permit,
            failure={
                "failure_kind": "engineering",
                "interrupted_action": "fixture.callable",
                "minimum_reproduction_evidence": [
                    self.reproduction.sha256
                ],
                "root_cause": "fixture parser boundary rejected input",
            },
            operation_id="candidate-writer-repair",
        )
        self.repair_id = str(opened_repair.result["repair_id"])

    def candidate(
        self,
        mode: str,
        *,
        changed_dimension: str = "cause",
    ) -> str:
        new_basis = self.writer.evidence.finalize(
            f"candidate material basis: {mode}".encode("ascii")
        )
        with self.writer.open_stable_index() as (control, index):
            repair = control["scientific"]["active_repair"]
            assert isinstance(repair, dict)
            opened = index.get("repair-open", self.repair_id)
            assert opened is not None
            attempt_records = []
            attempt_head = index.event_head(f"repair-attempt:{self.repair_id}")
            if attempt_head is not None:
                for sequence in range(1, attempt_head.sequence + 1):
                    attempt = index.event_record(
                        f"repair-attempt:{self.repair_id}", sequence
                    )
                    assert attempt is not None
                    attempt_records.append(attempt)
            observations, observation_head = (
                require_repair_validation_observation_stream(
                    index,
                    repair_id=self.repair_id,
                    job_id=self.job_id,
                    job_hash=self.job_hash,
                    cause_hash=str(repair["cause_hash"]),
                    reproduction_evidence_hashes=(
                        self.reproduction.sha256,
                    ),
                    resume_action=str(repair["resume_action"]),
                    mission_id=control["scientific"]["active_mission"],
                    expected_scope="fixture_only",
                    accepted_attempts=attempt_records,
                    evidence=self.writer.evidence,
                )
            )
        bound_observations = tuple(
            {
                "new_information_evidence_hashes": list(
                    item["new_information_evidence_hashes"]
                ),
                "observation_record_id": item["observation_record_id"],
            }
            for item in observations
        )
        new_evidence_hashes = tuple(
            sorted(
                {
                    new_basis.sha256,
                    *(
                        identity
                        for item in bound_observations
                        for identity in item[
                            "new_information_evidence_hashes"
                        ]
                    ),
                }
            )
        )
        context = build_repair_candidate_validation_context(
            bound_validation_observations=bound_observations,
            cause_hash=str(repair["cause_hash"]),
            changed_dimension=changed_dimension,
            explanation="change the measured parser cause basis",
            implementation_proof_hash=(
                new_basis.sha256
                if changed_dimension == "implementation"
                else None
            ),
            job_hash=self.job_hash,
            job_id=self.job_id,
            new_basis_hash=new_basis.sha256,
            new_evidence_hashes=new_evidence_hashes,
            previous_basis_hash=str(repair["latest_basis_hash"]),
            prior_attempt_record_id=repair["latest_attempt_record_id"],
            prior_validation_observation_head=observation_head,
            repair_axis_id=f"{changed_dimension}-fixture-axis",
            repair_id=self.repair_id,
            reproduction_evidence_hashes=(self.reproduction.sha256,),
            resume_action=str(repair["resume_action"]),
        )
        result = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "context_sha256": sha256(
                        canonical_bytes(context)
                    ).hexdigest(),
                    "mode": mode,
                    "schema": "repair_candidate_writer_fixture_result.v1",
                }
            )
        )
        binding = repair_validation_binding(
            verification_kind="candidate",
            mission_id="MIS-CANDIDATE-WRITER",
            protocol=_PROTOCOL,
            context=context,
            artifact_roles=(("validation_result", result.sha256),),
        )
        plan = self.writer.evidence.finalize(
            canonical_bytes(
                build_repair_validation_plan(
                    validator_id=_VALIDATOR_ID,
                    binding=binding,
                )
            )
        )
        receipt = self.writer.evidence.finalize(
            canonical_bytes(
                build_repair_candidate_validation_receipt(
                    validator_id=_VALIDATOR_ID,
                    validation_plan_hash=plan.sha256,
                    protocol=_PROTOCOL,
                    result_artifact_hashes=(result.sha256,),
                )
            )
        )
        candidate = self.writer.evidence.finalize(
            canonical_bytes(
                build_repair_candidate(
                    bound_validation_observations=bound_observations,
                    cause_hash=str(repair["cause_hash"]),
                    changed_dimension=changed_dimension,
                    explanation="change the measured parser cause basis",
                    implementation_proof_hash=(
                        new_basis.sha256
                        if changed_dimension == "implementation"
                        else None
                    ),
                    job_hash=self.job_hash,
                    job_id=self.job_id,
                    new_basis_hash=new_basis.sha256,
                    new_evidence_hashes=new_evidence_hashes,
                    previous_basis_hash=str(repair["latest_basis_hash"]),
                    prior_attempt_record_id=repair["latest_attempt_record_id"],
                    prior_validation_observation_head=observation_head,
                    repair_axis_id=f"{changed_dimension}-fixture-axis",
                    repair_id=self.repair_id,
                    reproduction_evidence_hashes=(self.reproduction.sha256,),
                    resume_action=str(repair["resume_action"]),
                    verification_evidence_hashes=(receipt.sha256,),
                )
            )
        )
        return candidate.sha256

    def test_registered_repaired_candidate_closes_repair(self) -> None:
        candidate_hash = self.candidate("repaired")
        result = self.writer.evaluate_repair_candidate(
            candidate_hash=candidate_hash,
            operation_id="evaluate-repaired-candidate",
        )
        control = self.writer.read_control()
        assert control is not None
        self.assertIsNone(control["scientific"]["active_repair"])
        self.assertEqual(control["next_action"]["kind"], "resume_job")
        self.assertEqual(result.result["repair_id"], self.repair_id)
        with self.writer.open_stable_index() as (_control, index):
            attempt = index.get(
                "repair-attempt", str(result.result["attempt_record_id"])
            )
        assert attempt is not None
        self.assertEqual(
            attempt.payload["repair_candidate_hash"], candidate_hash
        )
        self.assertEqual(
            attempt.payload["repair_evaluation"]["mode"], "repaired"
        )

    def test_candidate_validator_runs_after_writer_lock_is_released(self) -> None:
        self.writer.validation_registry = EvidenceValidatorRegistry(
            (
                RepairCandidateWriterFixtureValidator(
                    self.writer.lock_path
                ),
                EngineeringRepairFixtureValidator(),
            )
        )
        candidate_hash = self.candidate("repaired")
        result = self.writer.evaluate_repair_candidate(
            candidate_hash=candidate_hash,
            operation_id="evaluate-repaired-candidate-outside-lock",
        )
        control = self.writer.read_control()
        assert control is not None
        self.assertIsNone(control["scientific"]["active_repair"])
        self.assertEqual(result.result["repair_id"], self.repair_id)

    def test_not_evaluable_candidate_is_zero_credit_observation(self) -> None:
        candidate_hash = self.candidate("not_evaluable")
        before = self.writer.read_control()
        result = self.writer.evaluate_repair_candidate(
            candidate_hash=candidate_hash,
            operation_id="evaluate-inconclusive-candidate",
        )
        after = self.writer.read_control()
        assert before is not None and after is not None
        self.assertEqual(after["scientific"], before["scientific"])
        self.assertEqual(after["next_action"], before["next_action"])
        self.assertEqual(result.result["evaluation_mode"], "not_evaluable")
        with self.writer.open_stable_index() as (_control, index):
            observation = index.get(
                "repair-validation-observation",
                str(result.result["observation_record_id"]),
            )
        assert observation is not None
        self.assertFalse(observation.payload["basis_advance"])
        self.assertEqual(observation.payload["repair_attempt_delta"], 0)
        self.assertEqual(observation.payload["scientific_trial_delta"], 0)

    def test_later_candidate_binds_exact_observation_as_new_information(
        self,
    ) -> None:
        first = self.candidate("not_evaluable")
        observed = self.writer.evaluate_repair_candidate(
            candidate_hash=first,
            operation_id="observe-before-informed-candidate",
        )
        second = self.candidate("failure_reproduced")
        accepted = self.writer.evaluate_repair_candidate(
            candidate_hash=second,
            operation_id="evaluate-observation-informed-candidate",
        )
        with self.writer.open_stable_index() as (_control, index):
            attempt = index.get(
                "repair-attempt", str(accepted.result["attempt_record_id"])
            )
        assert attempt is not None
        candidate = attempt.payload["repair_candidate"]
        self.assertEqual(
            candidate["bound_validation_observations"][0][
                "observation_record_id"
            ],
            observed.result["observation_record_id"],
        )
        self.assertEqual(
            candidate["prior_validation_observation_head"]["record_id"],
            observed.result["observation_record_id"],
        )
        for identity in candidate["bound_validation_observations"][0][
            "new_information_evidence_hashes"
        ]:
            self.assertIn(identity, candidate["new_evidence_hashes"])

    def test_partial_validator_result_is_typed_zero_credit_observation(
        self,
    ) -> None:
        candidate_hash = self.candidate("partial")
        result = self.writer.evaluate_repair_candidate(
            candidate_hash=candidate_hash,
            operation_id="evaluate-partial-candidate",
        )
        self.assertEqual(
            result.result["evaluation_mode"],
            "validation_unavailable",
        )
        with self.writer.open_stable_index() as (_control, index):
            observation = index.get(
                "repair-validation-observation",
                str(result.result["observation_record_id"]),
            )
        assert observation is not None
        self.assertEqual(
            observation.payload["evaluation"]["reason_code"],
            "partial_validator_result",
        )
        self.assertEqual(observation.payload["repair_attempt_delta"], 0)

    def test_reproduced_original_failure_advances_only_attempt_basis(self) -> None:
        candidate_hash = self.candidate("failure_reproduced")
        before = self.writer.read_control()
        result = self.writer.evaluate_repair_candidate(
            candidate_hash=candidate_hash,
            operation_id="evaluate-reproduced-candidate",
        )
        after = self.writer.read_control()
        assert before is not None and after is not None
        repair = after["scientific"]["active_repair"]
        assert isinstance(repair, dict)
        self.assertNotEqual(
            repair["latest_basis_hash"],
            before["scientific"]["active_repair"]["latest_basis_hash"],
        )
        self.assertEqual(
            repair["latest_attempt_record_id"],
            result.result["attempt_record_id"],
        )
        self.assertEqual(after["next_action"]["kind"], "execute_repair")
        self.assertEqual(after["scientific"]["claim"], "none")

    def test_reproduced_failure_accepts_changed_implementation_basis(self) -> None:
        candidate_hash = self.candidate(
            "failure_reproduced",
            changed_dimension="implementation",
        )
        before = self.writer.read_control()
        result = self.writer.evaluate_repair_candidate(
            candidate_hash=candidate_hash,
            operation_id="evaluate-reproduced-implementation-candidate",
        )
        control = self.writer.read_control()
        assert control is not None
        repair = control["scientific"]["active_repair"]
        assert isinstance(repair, dict)
        assert before is not None
        self.assertEqual(
            repair["latest_attempt_record_id"],
            result.result["attempt_record_id"],
        )
        self.assertNotEqual(
            repair["latest_basis_hash"],
            before["scientific"]["active_repair"]["latest_basis_hash"],
        )
        self.assertEqual(control["next_action"]["kind"], "execute_repair")

    def test_unregistered_candidate_is_observed_without_abandonment(self) -> None:
        candidate_hash = self.candidate("repaired")
        self.writer.validation_registry = EvidenceValidatorRegistry()
        before = self.writer.read_control()
        result = self.writer.evaluate_repair_candidate(
            candidate_hash=candidate_hash,
            operation_id="evaluate-unregistered-candidate",
        )
        after = self.writer.read_control()
        assert before is not None and after is not None
        self.assertEqual(after["scientific"], before["scientific"])
        self.assertEqual(after["next_action"], before["next_action"])
        self.assertEqual(
            result.result["evaluation_mode"], "validation_unavailable"
        )
        with self.writer.open_stable_index() as (_control, index):
            observation = index.get(
                "repair-validation-observation",
                str(result.result["observation_record_id"]),
            )
        assert observation is not None
        self.assertEqual(
            observation.payload["evaluation"]["reason_code"],
            "validator_absent_or_unregistered",
        )

    def test_observation_writer_requires_evaluation_capability(self) -> None:
        with self.assertRaisesRegex(
            TransitionError,
            "requires an evaluated candidate capability",
        ):
            self.writer._record_repair_validation_observation(  # noqa: SLF001
                _candidate_capability=None,  # type: ignore[arg-type]
                operation_id="forged-direct-observation",
            )

    def test_observation_stream_rejects_bool_and_float_zero_deltas(self) -> None:
        candidate_hash = self.candidate("not_evaluable")
        self.writer.evaluate_repair_candidate(
            candidate_hash=candidate_hash,
            operation_id="observe-strict-zero-deltas",
        )
        with self.writer.open_stable_index() as (control, index):
            stream = f"repair-validation-observation:{self.repair_id}"
            head = index.event_head(stream)
            record = index.event_record(stream, 1)
            opened = index.get("repair-open", self.repair_id)
        assert head is not None and record is not None and opened is not None
        active_repair = control["scientific"]["active_repair"]
        assert isinstance(active_repair, dict)

        def require(forged_record: object) -> None:
            class FakeIndex:
                def event_head(self, value: str) -> object:
                    return head if value == stream else None

                def event_record(self, value: str, sequence: int) -> object:
                    if value == stream and sequence == 1:
                        return forged_record
                    return None

            require_repair_validation_observation_stream(
                FakeIndex(),  # type: ignore[arg-type]
                repair_id=self.repair_id,
                job_id=self.job_id,
                job_hash=self.job_hash,
                cause_hash=active_repair["cause_hash"],
                reproduction_evidence_hashes=(self.reproduction.sha256,),
                resume_action=opened.payload["resume_action"],
                mission_id=control["scientific"]["active_mission"],
                expected_scope="fixture_only",
                accepted_attempts=(),
                evidence=self.writer.evidence,
            )

        delta_fields = (
            "candidate_delta",
            "holdout_reveal_delta",
            "release_delta",
            "repair_attempt_delta",
            "scientific_failure_delta",
            "scientific_trial_delta",
        )
        for field in delta_fields:
            for forged_zero in (False, 0.0):
                with self.subTest(field=field, forged_zero=forged_zero):
                    payload = {**record.payload, field: forged_zero}
                    with self.assertRaisesRegex(
                        RepairObservationAuthorityError,
                        "stream is malformed",
                    ):
                        require(replace(record, payload=payload))

        with self.assertRaisesRegex(
            RepairObservationAuthorityError,
            "stream is malformed",
        ):
            require(replace(record, event_sequence=True))

    def test_unrecovered_disposition_binds_observations_without_attempt_credit(
        self,
    ) -> None:
        candidate_hash = self.candidate("not_evaluable")
        observed = self.writer.evaluate_repair_candidate(
            candidate_hash=candidate_hash,
            operation_id="observe-before-unrecovered-disposition",
        )
        inventory = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "axes": [
                        {
                            "accepted_attempt_record_ids": [],
                            "axis_id": "observation-bounded-infeasible-route",
                            "changed_dimension": "information",
                            "state": "infeasible",
                            "support_evidence_hashes": [
                                self.reproduction.sha256
                            ],
                            "value_assessment": None,
                        }
                    ],
                    "coverage_complete": True,
                    "no_identity_preserving_repair_route_remaining": True,
                    "schema": "engineering_repair_inventory_facts.v1",
                }
            )
        )
        disposition_hash = materialize_engineering_repair_disposition(
            self.writer,
            inventory_validator_id=(
                EngineeringRepairFixtureValidator.validator_id
            ),
            inventory_protocol=EngineeringRepairFixtureValidator.protocol,
            inventory_result_artifacts={
                "support:0000": self.reproduction.sha256,
                "validation_result": inventory.sha256,
            },
            rationale="the bounded fixture inventory is infeasible",
            resume_condition="complete the fixture engineering failure",
        )
        concluded = self.writer.conclude_repair_unrecovered(
            disposition_hash=disposition_hash,
            operation_id="conclude-after-zero-credit-observation",
        )
        control = self.writer.read_control()
        assert control is not None
        self.assertIsNone(control["scientific"]["active_repair"])
        self.assertEqual(
            control["next_action"]["kind"],
            "complete_engineering_failure",
        )
        with self.writer.open_stable_index() as (_control, index):
            close = index.get(
                "repair-close",
                str(concluded.result["repair_close_record_id"]),
            )
        assert close is not None
        context = close.payload["disposition_validation"]["derivation"][
            "context"
        ]
        self.assertEqual(context["repair_attempts"], [])
        self.assertEqual(
            context["repair_validation_observations"][0][
                "observation_record_id"
            ],
            observed.result["observation_record_id"],
        )
        self.assertEqual(
            context["repair_validation_observation_head"]["sequence"],
            1,
        )
        self.assertEqual(
            close.payload["disposition_validation"]["derivation"]["facts"][
                "observation_count"
            ],
            1,
        )


if __name__ == "__main__":
    unittest.main()
