from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.permits import (
    PermitAuthority,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.job_contract import build_job_identity_plan
from axiom_rift.operations.job_retry_family import (
    JobRetryFamilyError,
    derive_job_retry_family,
    derive_runtime_source_retry_resolution,
    parse_job_retry_resume_authority,
    retry_family_attempt_identity,
    retry_family_attempt_payload,
)
from axiom_rift.operations.job_retry_history import (
    JobRetryHistoryError,
    latest_legacy_family_completion,
    resolve_job_retry_history,
)
from axiom_rift.operations.job_retry_admission import (
    JobRetryAdmission,
    JobRetryAdmissionIntegrityError,
    build_retry_family_completion_record,
    build_retry_family_declaration_record,
)
from axiom_rift.operations.validation import (
    ENGINEERING_REPAIR_FIXTURE_PROTOCOL,
    ENGINEERING_REPAIR_FIXTURE_VALIDATOR_ID,
    ENGINEERING_RETRY_VALIDATOR_ID,
    EvidenceValidationError,
    EvidenceValidatorRegistry,
)
from axiom_rift.operations.repair_disposition_materializer import (
    materialize_engineering_repair_disposition,
)
from axiom_rift.operations.writer import (
    IdenticalFailedRetryError,
    RecoveryRequired,
    StateWriter,
    TransitionError,
)
from axiom_rift.storage.index import EventHead, IndexRecord, LocalIndex
from axiom_rift.storage.state import WriterLock
from tests.operations.test_writer import (
    FIXED_EXPIRY,
    FIXED_NOW,
    OBSERVED_MATERIAL_ID,
    REPO_ROOT,
    batch_spec,
    initiative_objective,
    job_spec,
    mission_goal,
    study_question,
)


class JobRetryFamilyWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.writer = StateWriter(
            self.root,
            permit_authority=PermitAuthority(b"r" * 32),
            clock=lambda: FIXED_NOW,
            engineering_fixture=True,
            foundation_root=REPO_ROOT,
        )
        self.writer.initialize_ready()

    def test_production_writer_default_retry_registry_is_empty(self) -> None:
        with TemporaryDirectory() as root:
            writer = StateWriter(
                root,
                permit_authority=PermitAuthority(b"p" * 32),
                clock=lambda: FIXED_NOW,
                foundation_root=REPO_ROOT,
            )
            with self.assertRaisesRegex(
                EvidenceValidationError,
                "no registered validator",
            ):
                writer.validation_registry.require_registered(
                    validator_id=ENGINEERING_RETRY_VALIDATOR_ID,
                    domain="engineering",
                )

    def _open_mission(self, mission_id: str) -> None:
        self.writer.open_mission(
            mission_id=mission_id,
            goal=mission_goal("retry family fixture"),
            operation_id=f"{mission_id}-open",
        )

    def _legacy_identity_plan(
        self,
        *,
        mission_id: str,
        spec: dict[str, object],
    ):
        normalized = self.writer._normalize_job_spec(spec)
        work_basis = {
            "callable_identity": normalized["callable_identity"],
            "component_parity_binding": normalized.get(
                "component_parity_binding"
            ),
            "evidence_subject": normalized["evidence_subject"],
            "external_dependency_binding": normalized.get(
                "external_dependency_binding"
            ),
            "input_hashes": normalized["input_hashes"],
            "holdout_binding": normalized.get("holdout_binding"),
            "runtime_binding": normalized.get("runtime_binding"),
            "scientific_binding": normalized.get("scientific_binding"),
            "source_binding": normalized.get("source_binding"),
        }
        return normalized, build_job_identity_plan(
            spec=normalized,
            work_basis=work_basis,
            mission_id=mission_id,
            candidate_execution_context=None,
            observed_development_binding=None,
            implementation_source_authority=None,
            external_observed_development_binding=None,
        )

    def _append_legacy_record(
        self,
        *,
        record: IndexRecord,
        tag: str,
    ) -> None:
        def prepare(current, _index):
            assert current is not None
            return self.writer._body(current), [record], {"tag": tag}

        self.writer._commit(
            event_kind=f"legacy_retry_fixture_{record.kind}",
            operation_id=f"legacy-retry-fixture-{tag}-{record.kind}",
            subject=record.subject,
            payload={"tag": tag},
            prepare=prepare,
        )

    def _seed_legacy_completion(
        self,
        *,
        mission_id: str,
        spec: dict[str, object],
        outcome: str,
        tag: str,
    ) -> tuple[IndexRecord, IndexRecord]:
        normalized, identity = self._legacy_identity_plan(
            mission_id=mission_id,
            spec=spec,
        )
        stream = f"job-attempt:{identity.work_fingerprint}"
        declaration = IndexRecord(
            kind="job-declared",
            record_id=identity.job_id,
            subject=f"Job:{identity.job_id}",
            status="declared",
            fingerprint=identity.job_hash,
            payload={
                "batch_id": None,
                "candidate_execution_context": None,
                "initiative_id": None,
                "mission_id": mission_id,
                "return_next_action": {"kind": "legacy_fixture"},
                "spec": normalized,
                "study_id": None,
                "success_fingerprint": identity.success_fingerprint,
                "work_fingerprint": identity.work_fingerprint,
            },
            event_stream=stream,
            event_sequence=1,
        )
        self._append_legacy_record(record=declaration, tag=f"{tag}-declare")
        completion_id = canonical_digest(
            domain="legacy-job-completion-fixture",
            payload={"job_id": identity.job_id, "outcome": outcome, "tag": tag},
        )
        completion = IndexRecord(
            kind="job-completed",
            record_id=completion_id,
            subject=f"Job:{identity.job_id}",
            status=outcome,
            fingerprint=identity.job_hash,
            payload={
                "failure": (
                    {
                        "failure_kind": "engineering",
                        "failure_signature": canonical_digest(
                            domain="legacy-failure-fixture",
                            payload={"job_id": identity.job_id, "tag": tag},
                        ),
                        "minimum_reproduction_evidence": [],
                    }
                    if outcome != "success"
                    else None
                ),
                "job_id": identity.job_id,
            },
            event_stream=stream,
            event_sequence=2,
        )
        self._append_legacy_record(record=completion, tag=f"{tag}-complete")
        return declaration, completion

    def _open_batch(self, *, max_compute_seconds: int) -> str:
        self._open_mission("MIS-RETRY-BATCH")
        self.writer.open_initiative(
            initiative_id="INI-RETRY-BATCH",
            objective=initiative_objective("retry family Batch fixture"),
            operation_id="retry-batch-initiative",
        )
        study_id = "STU-RETRY-BATCH"
        question = study_question("retry family Batch ceiling")
        proposal = {"mechanism": "typed retry budget"}
        study_hash = self.writer.study_input_hash(
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            semantic_proposal=proposal,
        )
        study_permit = self.writer.issue_permit(
            kind=PermitKind.STUDY,
            subject_kind=SubjectKind.INITIATIVE,
            subject_id="INI-RETRY-BATCH",
            input_hash=study_hash,
            actions=("open_study",),
            scope=("study",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="retry-batch-study-permit",
        )
        opened = self.writer.open_study(
            study_id=study_id,
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            material_display_name="retry-family-material",
            semantic_proposal=proposal,
            permit=study_permit,
            operation_id="retry-batch-study-open",
        )
        frozen_batch = batch_spec(
            batch_id="BAT-RETRY-FAMILY",
            study_id=study_id,
            study_hash=opened.result["study_hash"],
            max_trials=2,
            max_compute_seconds=max_compute_seconds,
        )
        batch_permit = self.writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id=study_id,
            input_hash=frozen_batch.identity.removeprefix("batch:"),
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="retry-batch-permit",
        )
        self.writer.open_batch(
            batch_spec=frozen_batch,
            permit=batch_permit,
            operation_id="retry-batch-open",
        )
        return study_id

    def _complete_engineering_failure(
        self,
        *,
        spec: dict[str, object],
        tag: str,
        continue_batch: bool = False,
        disposition: str = "repair_infeasible",
    ) -> tuple[object, object]:
        declared = self.writer.declare_job(
            spec=spec,
            operation_id=f"{tag}-declare",
        )
        permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=declared.result["job_id"],
            input_hash=declared.result["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id=f"{tag}-permit",
        )
        self.writer.start_job(
            permit=permit,
            operation_id=f"{tag}-start",
        )
        reproduction = self.writer.evidence.finalize(
            f"{tag} minimum reproduction".encode("ascii")
        )
        cause = {
            "failure_kind": "engineering",
            "minimum_reproduction_evidence": [reproduction.sha256],
            "root_cause": "fixture operational cause remained unresolved",
            "interrupted_action": spec["callable_identity"],
        }
        if disposition != "repair_infeasible":
            raise AssertionError(
                "the current fixture helper supports only registered "
                "repair_infeasible inventory"
            )
        repair_permit = self.writer.issue_permit(
            kind=PermitKind.REPAIR,
            subject_kind=SubjectKind.JOB,
            subject_id=declared.result["job_id"],
            input_hash=declared.result["job_hash"],
            actions=("open_repair",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id=f"{tag}-repair-permit",
        )
        self.writer.open_repair(
            permit=repair_permit,
            failure=cause,
            operation_id=f"{tag}-repair-open",
        )
        support = self.writer.evidence.finalize(
            f"{tag} complete registered route inventory".encode("ascii")
        )
        inventory = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "axes": [
                        {
                            "accepted_attempt_record_ids": [],
                            "axis_id": "fixture-bounded-route",
                            "changed_dimension": "implementation",
                            "state": "infeasible",
                            "support_evidence_hashes": [support.sha256],
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
            inventory_validator_id=ENGINEERING_REPAIR_FIXTURE_VALIDATOR_ID,
            inventory_protocol=ENGINEERING_REPAIR_FIXTURE_PROTOCOL,
            inventory_result_artifacts={
                "support:0000": support.sha256,
                "validation_result": inventory.sha256,
            },
            rationale="complete fixture route inventory is infeasible",
            resume_condition="complete the typed fixture engineering failure",
        )
        self.writer.conclude_repair_unrecovered(
            disposition_hash=disposition_hash,
            operation_id=f"{tag}-repair-conclude",
        )
        completed = self.writer.complete_job(
            outcome="failed",
            output_manifest={},
            failure={
                **cause,
                "repair_disposition_hash": disposition_hash,
                "resume_action": spec["resume_action"],
            },
            operation_id=f"{tag}-complete",
        )
        if continue_batch:
            self.writer.judge_job_evidence(
                completion_record_id=completed.result[
                    "completion_record_id"
                ],
                disposition="continue_batch",
                operation_id=f"{tag}-continue-batch",
            )
        return declared, completed

    def _retry_authority(
        self,
        *,
        completion_record_id: str,
        changed_dimension: str,
        new_work_fingerprint: str,
        tag: str,
        resolved: bool = True,
    ) -> str:
        with LocalIndex(self.writer.index_path) as index:
            completion = index.get(
                "job-completed",
                completion_record_id,
            )
            assert completion is not None
            declaration = index.get(
                "job-declared",
                completion.payload["job_id"],
            )
            assert declaration is not None
        failure = completion.payload["failure"]
        disposition = completion.payload["engineering_disposition"]
        family = declaration.payload["retry_family_fingerprint"]
        new_basis = self.writer.evidence.finalize(
            f"{tag} changed operational basis".encode("ascii")
        )
        check_plan = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "operation": "canonical_required_transition",
                    "schema": "engineering_retry_fixture_plan.v1",
                }
            )
        )
        validation_binding = {
            "authority_kind": "same_implementation_retry",
            "changed_dimension": changed_dimension,
            "engineering_disposition_hash": failure[
                "repair_disposition_hash"
            ],
            "failure_signature": failure["failure_signature"],
            "new_basis_hash": new_basis.sha256,
            "new_work_fingerprint": new_work_fingerprint,
            "previous_basis_hash": disposition["basis_manifest_hash"],
            "prior_completion_record_id": completion.record_id,
            "prior_job_hash": declaration.fingerprint,
            "prior_job_id": declaration.record_id,
            "prior_work_fingerprint": declaration.payload[
                "work_fingerprint"
            ],
            "resume_condition": disposition["resume_condition"],
            "retry_family_fingerprint": family,
            "schema": "engineering_retry_validation_binding.v1",
            "scientific_semantics_changed": False,
        }
        result = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "binding_sha256": sha256(
                        canonical_bytes(validation_binding)
                    ).hexdigest(),
                    "current_measurement": {
                        "basis_hash": (
                            new_basis.sha256
                            if resolved
                            else disposition["basis_manifest_hash"]
                        )
                    },
                    "prior_measurement": {
                        "basis_hash": disposition["basis_manifest_hash"]
                    },
                    "required_measurement": {
                        "basis_hash": new_basis.sha256
                    },
                    "schema": "engineering_retry_fixture_measurement.v1",
                }
            )
        )
        receipt = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "changed_dimension": changed_dimension,
                    "check_plan_hash": check_plan.sha256,
                    "engineering_disposition_hash": failure[
                        "repair_disposition_hash"
                    ],
                    "failure_signature": failure["failure_signature"],
                    "new_basis_hash": new_basis.sha256,
                    "new_work_fingerprint": new_work_fingerprint,
                    "prior_completion_record_id": completion.record_id,
                    "prior_job_hash": declaration.fingerprint,
                    "prior_job_id": declaration.record_id,
                    "result_artifact_hashes": [result.sha256],
                    "resume_condition": disposition["resume_condition"],
                    "retry_family_fingerprint": family,
                    "schema": "job_retry_resume_verification.v1",
                    "scientific_semantics_changed": False,
                    "validator_id": ENGINEERING_RETRY_VALIDATOR_ID,
                    "verdict": "passed",
                    "verification_method": "independent fixture rerun",
                }
            )
        )
        authority = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "changed_dimension": changed_dimension,
                    "engineering_disposition_hash": failure[
                        "repair_disposition_hash"
                    ],
                    "failure_signature": failure["failure_signature"],
                    "new_basis_hash": new_basis.sha256,
                    "new_evidence_hashes": [new_basis.sha256],
                    "new_work_fingerprint": new_work_fingerprint,
                    "previous_basis_hash": disposition[
                        "basis_manifest_hash"
                    ],
                    "prior_completion_record_id": completion.record_id,
                    "prior_job_hash": declaration.fingerprint,
                    "prior_job_id": declaration.record_id,
                    "prior_work_fingerprint": declaration.payload[
                        "work_fingerprint"
                    ],
                    "resume_condition": disposition["resume_condition"],
                    "retry_family_fingerprint": family,
                    "schema": "job_retry_resume_authority.v1",
                    "scientific_semantics_changed": False,
                    "verification_receipt_hashes": [receipt.sha256],
                }
            )
        )
        return authority.sha256

    def _implementation_retry_proof(
        self,
        *,
        completion_record_id: str,
        current_spec: dict[str, object],
        resolved: bool,
        tag: str,
    ) -> str:
        with LocalIndex(self.writer.index_path) as index:
            completion = index.get("job-completed", completion_record_id)
            assert completion is not None
            declaration = index.get(
                "job-declared",
                completion.payload["job_id"],
            )
            assert declaration is not None
        previous_spec = declaration.payload["spec"]
        previous_manifest = parse_canonical(
            self.writer.evidence.read_verified(
                previous_spec["implementation_identity"]
            )
        )
        current_manifest = parse_canonical(
            self.writer.evidence.read_verified(
                current_spec["implementation_identity"]
            )
        )
        assert isinstance(previous_manifest, dict)
        assert isinstance(current_manifest, dict)
        family = declaration.payload["retry_family_fingerprint"]
        work_fingerprint = declaration.payload["work_fingerprint"]
        basis_material = {
            "authority_kind": "implementation_cause_resolution",
            "changed_dimension": "implementation",
            "failure_signature": completion.payload["failure"][
                "failure_signature"
            ],
            "new_artifact_hashes": list(current_manifest["artifact_hashes"]),
            "new_implementation_identity": current_spec[
                "implementation_identity"
            ],
            "new_work_fingerprint": work_fingerprint,
            "previous_artifact_hashes": list(
                previous_manifest["artifact_hashes"]
            ),
            "previous_implementation_identity": previous_spec[
                "implementation_identity"
            ],
            "prior_completion_record_id": completion.record_id,
            "prior_job_hash": declaration.fingerprint,
            "prior_job_id": declaration.record_id,
            "prior_work_fingerprint": work_fingerprint,
            "retry_family_fingerprint": family,
            "schema": "engineering_retry_validation_binding.v1",
            "scientific_semantics_changed": False,
        }
        plan = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "operation": "canonical_required_transition",
                    "schema": "engineering_retry_fixture_plan.v1",
                }
            )
        )
        prior_measurement = {
            "failure_signature": completion.payload["failure"][
                "failure_signature"
            ],
            "status": "failed",
        }
        required_measurement = {
            "implementation_identity": current_spec[
                "implementation_identity"
            ],
            "status": "passed",
        }
        measurement = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "binding_sha256": sha256(
                        canonical_bytes(basis_material)
                    ).hexdigest(),
                    "current_measurement": (
                        required_measurement
                        if resolved
                        else prior_measurement
                    ),
                    "prior_measurement": prior_measurement,
                    "required_measurement": required_measurement,
                    "schema": "engineering_retry_fixture_measurement.v1",
                }
            )
        )
        new_evidence_hashes = sorted(
            {
                current_spec["implementation_identity"],
                *current_manifest["artifact_hashes"],
            }
        )
        proof = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "changed_dimension": "implementation",
                    "explanation": f"{tag} exact failed cause was repaired",
                    "new_evidence_hashes": new_evidence_hashes,
                    "new_implementation_identity": current_spec[
                        "implementation_identity"
                    ],
                    "prior_failure_signature": completion.payload["failure"][
                        "failure_signature"
                    ],
                    "previous_implementation_identity": previous_spec[
                        "implementation_identity"
                    ],
                    "result_artifact_hashes": [measurement.sha256],
                    "schema": "job_changed_cause.v1",
                    "validation_plan_hash": plan.sha256,
                    "validator_id": ENGINEERING_RETRY_VALIDATOR_ID,
                }
            )
        )
        return proof.sha256

    def test_legacy_arbitrary_input_cannot_launder_failed_family(self) -> None:
        mission_id = "MIS-LEGACY-RETRY-INPUT"
        self._open_mission(mission_id)
        subject = {"kind": "Mission", "id": mission_id}
        original = job_spec(self.writer, subject)
        self._seed_legacy_completion(
            mission_id=mission_id,
            spec=original,
            outcome="failed",
            tag="legacy-input-failure",
        )
        added = self.writer.evidence.finalize(
            b"legacy arbitrary input must not reset retry history"
        )
        bypass = job_spec(self.writer, subject)
        bypass["input_hashes"] = sorted(
            [*bypass["input_hashes"], added.sha256]
        )
        with self.assertRaisesRegex(
            IdenticalFailedRetryError,
            "changed-cause proof",
        ):
            self.writer.declare_job(
                spec=bypass,
                operation_id="reject-legacy-input-family-bypass",
            )

    def test_legacy_latest_success_supersedes_older_family_failure(self) -> None:
        mission_id = "MIS-LEGACY-RETRY-SUCCESS"
        self._open_mission(mission_id)
        subject = {"kind": "Mission", "id": mission_id}
        failed_spec = job_spec(self.writer, subject)
        self._seed_legacy_completion(
            mission_id=mission_id,
            spec=failed_spec,
            outcome="failed",
            tag="legacy-older-failure",
        )
        success_input = self.writer.evidence.finalize(
            b"legacy family later successful operational basis"
        )
        success_spec = job_spec(self.writer, subject)
        success_spec["input_hashes"] = sorted(
            [*success_spec["input_hashes"], success_input.sha256]
        )
        self._seed_legacy_completion(
            mission_id=mission_id,
            spec=success_spec,
            outcome="success",
            tag="legacy-latest-success",
        )
        next_input = self.writer.evidence.finalize(
            b"post-migration exact work basis"
        )
        current = job_spec(self.writer, subject)
        current["input_hashes"] = sorted(
            [*current["input_hashes"], next_input.sha256]
        )
        declared = self.writer.declare_job(
            spec=current,
            operation_id="allow-latest-legacy-success",
        )
        self.assertTrue(declared.result["job_id"].startswith("job:"))

    def test_legacy_lookup_ignores_other_family_and_mission(self) -> None:
        mission_id = "MIS-LEGACY-RETRY-SCOPE"
        self._open_mission(mission_id)
        subject = {"kind": "Mission", "id": mission_id}
        other_family = job_spec(self.writer, subject)
        other_family["callable_identity"] = "python:tests.unrelated_legacy_job"
        self._seed_legacy_completion(
            mission_id=mission_id,
            spec=other_family,
            outcome="failed",
            tag="legacy-other-family",
        )
        other_mission_id = "MIS-LEGACY-OTHER-MISSION"
        other_mission = job_spec(
            self.writer,
            {"kind": "Mission", "id": other_mission_id},
        )
        self._seed_legacy_completion(
            mission_id=other_mission_id,
            spec=other_mission,
            outcome="failed",
            tag="legacy-other-mission",
        )
        declared = self.writer.declare_job(
            spec=job_spec(self.writer, subject),
            operation_id="allow-unrelated-legacy-history",
        )
        self.assertTrue(declared.result["job_id"].startswith("job:"))

    def test_malformed_legacy_declaration_fails_closed(self) -> None:
        mission_id = "MIS-LEGACY-RETRY-MALFORMED"
        self._open_mission(mission_id)
        job_hash = canonical_digest(
            domain="malformed-legacy-job-fixture",
            payload={"mission_id": mission_id},
        )
        malformed = IndexRecord(
            kind="job-declared",
            record_id=f"job:{job_hash}",
            subject=f"Job:job:{job_hash}",
            status="declared",
            fingerprint=job_hash,
            payload={"mission_id": mission_id},
        )
        self._append_legacy_record(record=malformed, tag="malformed")
        with self.assertRaisesRegex(RecoveryRequired, "spec is malformed"):
            self.writer.declare_job(
                spec=job_spec(
                    self.writer,
                    {"kind": "Mission", "id": mission_id},
                ),
                operation_id="reject-malformed-legacy-history",
            )

    def test_legacy_lookup_is_one_indexed_mission_query(self) -> None:
        mission_id = "MIS-LEGACY-RETRY-QUERY"
        self._open_mission(mission_id)
        original_lookup = LocalIndex.records_by_payload_text
        observed: list[tuple[str, str, str]] = []

        def counted(index, kind, lookup_name, value):
            if (kind, lookup_name, value) == (
                "job-declared",
                "mission_id",
                mission_id,
            ):
                observed.append((kind, lookup_name, value))
            return original_lookup(index, kind, lookup_name, value)

        with patch.object(LocalIndex, "records_by_payload_text", counted):
            self.writer.declare_job(
                spec=job_spec(
                    self.writer,
                    {"kind": "Mission", "id": mission_id},
                ),
                operation_id="prove-one-legacy-mission-query",
            )
        self.assertEqual(
            observed,
            [("job-declared", "mission_id", mission_id)],
        )
        with LocalIndex(self.writer.index_path) as index:
            access_shape = index.records_by_payload_text_access_shape(
                "job-declared",
                "mission_id",
                mission_id,
            )
        self.assertTrue(
            any(
                "ix_records_kind_payload_mission_id" in detail
                for detail in access_shape
            )
        )

    def test_legacy_batch_family_prefers_one_indexed_batch_query(self) -> None:
        family = derive_job_retry_family(
            mission_id="MIS-LEGACY-RETRY-BATCH-QUERY",
            initiative_id="INI-LEGACY-RETRY-BATCH-QUERY",
            study_id="STU-LEGACY-RETRY-BATCH-QUERY",
            batch_id="BAT-LEGACY-RETRY-BATCH-QUERY",
            spec={
                "callable_identity": "axiom_rift.fixture:run",
                "evidence_subject": {
                    "kind": "Study",
                    "id": "STU-LEGACY-RETRY-BATCH-QUERY",
                },
            },
        )
        observed: list[tuple[str, str, str]] = []

        class EmptyIndex:
            @staticmethod
            def records_by_payload_text(kind, lookup_name, value):
                observed.append((kind, lookup_name, value))
                return ()

        self.assertIsNone(
            latest_legacy_family_completion(
                index=EmptyIndex(),
                family=family,
            )
        )
        self.assertEqual(
            observed,
            [
                (
                    "job-declared",
                    "batch_id",
                    "BAT-LEGACY-RETRY-BATCH-QUERY",
                )
            ],
        )

    def test_current_family_head_requires_exact_canonical_attempt(self) -> None:
        family = derive_job_retry_family(
            mission_id="MIS-RETRY-HEAD",
            initiative_id=None,
            study_id=None,
            batch_id=None,
            spec={
                "callable_identity": "axiom_rift.fixture:run",
                "evidence_subject": {"kind": "Mission", "id": "MIS-RETRY-HEAD"},
            },
        )
        payload = retry_family_attempt_payload(
            family=family,
            phase="declared",
            job_id="job:" + "1" * 64,
            job_hash="2" * 64,
            work_fingerprint="3" * 64,
        )
        payload["unexpected"] = "projection-drift"
        record = IndexRecord(
            kind="job-retry-family-attempt",
            record_id=retry_family_attempt_identity(payload),
            subject="Mission:MIS-RETRY-HEAD",
            status="declared",
            fingerprint=family.fingerprint,
            payload=payload,
            event_stream=family.stream,
            event_sequence=1,
        )
        head = EventHead(
            stream=family.stream,
            sequence=1,
            record_kind=record.kind,
            record_id=record.record_id,
            fingerprint=record.fingerprint,
        )

        class DriftedIndex:
            @staticmethod
            def event_head(stream):
                return head if stream == family.stream else None

            @staticmethod
            def get(kind, record_id):
                if (kind, record_id) == (record.kind, record.record_id):
                    return record
                return None

        with self.assertRaisesRegex(
            JobRetryHistoryError,
            "family head is invalid",
        ):
            resolve_job_retry_history(index=DriftedIndex(), family=family)

    def test_runtime_source_retry_requires_an_exact_fresh_state(self) -> None:
        prior_state = "4" * 64
        current_state = "5" * 64
        spec = {
            "budget": {"compute_seconds": 10, "wall_seconds": 20},
            "implementation_identity": "6" * 64,
        }
        resolution = derive_runtime_source_retry_resolution(
            failure={
                "failure_kind": "runtime_source_ineligibility",
                "source_contract_id": "SRC-RETRY",
                "source_state_record_id": prior_state,
            },
            previous_candidate_context={
                "source_state_record_ids": [prior_state],
            },
            current_candidate_context={
                "source_snapshot_rows": [
                    {
                        "source_contract_id": "SRC-RETRY",
                        "source_receipt_id": "receipt:current",
                        "source_state_record_id": current_state,
                    }
                ],
                "source_state_record_ids": [current_state],
            },
            previous_spec=spec,
            current_spec=dict(spec),
        )
        self.assertIsNotNone(resolution)
        assert resolution is not None
        self.assertEqual(resolution.prior_source_state_record_id, prior_state)
        self.assertEqual(resolution.current_source_state_record_id, current_state)

        with self.assertRaisesRegex(
            ValueError,
            "does not advance the failed source state",
        ):
            derive_runtime_source_retry_resolution(
                failure={
                    "failure_kind": "runtime_source_ineligibility",
                    "source_contract_id": "SRC-RETRY",
                    "source_state_record_id": prior_state,
                },
                previous_candidate_context={
                    "source_state_record_ids": [prior_state],
                },
                current_candidate_context={
                    "source_snapshot_rows": [
                        {
                            "source_contract_id": "SRC-RETRY",
                            "source_receipt_id": "receipt:stale",
                            "source_state_record_id": prior_state,
                        }
                    ],
                    "source_state_record_ids": [prior_state],
                },
                previous_spec=spec,
                current_spec=dict(spec),
            )

    def test_retry_projection_builder_rejoins_exact_declaration(self) -> None:
        family = derive_job_retry_family(
            mission_id="MIS-RETRY-PROJECTION",
            initiative_id=None,
            study_id=None,
            batch_id=None,
            spec={
                "callable_identity": "axiom_rift.fixture:run",
                "evidence_subject": {
                    "kind": "Mission",
                    "id": "MIS-RETRY-PROJECTION",
                },
            },
        )
        admission = JobRetryAdmission(
            family=family,
            stream_head=None,
            basis_records=(),
        )
        job_id = "job:" + "7" * 64
        job_hash = "7" * 64
        work_fingerprint = "8" * 64
        family_declaration = build_retry_family_declaration_record(
            admission=admission,
            job_id=job_id,
            job_hash=job_hash,
            work_fingerprint=work_fingerprint,
        )
        head = EventHead(
            stream=family.stream,
            sequence=1,
            record_kind=family_declaration.kind,
            record_id=family_declaration.record_id,
            fingerprint=family_declaration.fingerprint,
        )

        class ProjectionIndex:
            @staticmethod
            def event_head(stream):
                return head if stream == family.stream else None

            @staticmethod
            def get(kind, record_id):
                if (kind, record_id) == (
                    family_declaration.kind,
                    family_declaration.record_id,
                ):
                    return family_declaration
                return None

        declaration = IndexRecord(
            kind="job-declared",
            record_id=job_id,
            subject=f"Job:{job_id}",
            status="declared",
            fingerprint=job_hash,
            payload={
                "mission_id": family.mission_id,
                "retry_family": family.payload(),
                "retry_family_fingerprint": family.fingerprint,
                "work_fingerprint": work_fingerprint,
            },
        )
        completion = build_retry_family_completion_record(
            index=ProjectionIndex(),
            declaration=declaration,
            outcome="failed",
            completion_record_id="9" * 64,
        )
        self.assertIsNotNone(completion)
        assert completion is not None
        self.assertEqual(completion.status, "failed")
        self.assertEqual(completion.event_sequence, 2)
        self.assertEqual(completion.payload["completion_record_id"], "9" * 64)

        incomplete = IndexRecord(
            kind=declaration.kind,
            record_id=declaration.record_id,
            subject=declaration.subject,
            status=declaration.status,
            fingerprint=declaration.fingerprint,
            payload={
                **declaration.payload,
                "retry_family": None,
            },
        )
        with self.assertRaisesRegex(
            JobRetryAdmissionIntegrityError,
            "projection is incomplete",
        ):
            build_retry_family_completion_record(
                index=ProjectionIndex(),
                declaration=incomplete,
                outcome="failed",
                completion_record_id="9" * 64,
            )

    def test_arbitrary_input_hash_does_not_reset_failed_family(self) -> None:
        self._open_mission("MIS-RETRY-INPUT")
        subject = {"kind": "Mission", "id": "MIS-RETRY-INPUT"}
        original = job_spec(self.writer, subject)
        _declared, completed = self._complete_engineering_failure(
            spec=original,
            tag="retry-input",
        )
        bypass = job_spec(self.writer, subject)
        bypass["input_hashes"] = sorted(
            [*bypass["input_hashes"], "f" * 64]
        )
        with self.assertRaisesRegex(
            IdenticalFailedRetryError,
            "changed-cause proof",
        ):
            self.writer.declare_job(
                spec=bypass,
                operation_id="reject-arbitrary-input-family-bypass",
            )
        prior_manifest = parse_canonical(
            self.writer.evidence.read_verified(
                original["implementation_identity"]
            )
        )
        assert isinstance(prior_manifest, dict)
        changed_source = self.writer.evidence.finalize(
            b"changed implementation cannot launder an arbitrary Job input"
        )
        changed_implementation = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    **prior_manifest,
                    "artifact_hashes": [changed_source.sha256],
                }
            )
        )
        with LocalIndex(self.writer.index_path) as index:
            completion = index.get(
                "job-completed",
                completed.result["completion_record_id"],
            )
        assert completion is not None
        implementation_proof = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "changed_dimension": "implementation",
                    "explanation": "implementation changed but inputs must stay semantic",
                    "new_evidence_hashes": [
                        changed_implementation.sha256,
                        changed_source.sha256,
                    ],
                    "new_implementation_identity": (
                        changed_implementation.sha256
                    ),
                    "prior_failure_signature": completion.payload[
                        "failure"
                    ]["failure_signature"],
                    "previous_implementation_identity": original[
                        "implementation_identity"
                    ],
                    "schema": "job_changed_cause.v1",
                }
            )
        )
        bypass["implementation_identity"] = changed_implementation.sha256
        bypass["changed_cause_proof_hash"] = implementation_proof.sha256
        with self.assertRaisesRegex(
            IdenticalFailedRetryError,
            "semantic Job inputs",
        ):
            self.writer.declare_job(
                spec=bypass,
                operation_id="reject-proof-laundered-input-family-bypass",
            )

    def test_implementation_proof_cannot_rewrite_frozen_job_contract(self) -> None:
        self._open_mission("MIS-RETRY-IMPLEMENTATION-CONTRACT")
        subject = {
            "kind": "Mission",
            "id": "MIS-RETRY-IMPLEMENTATION-CONTRACT",
        }
        original = job_spec(self.writer, subject)
        _declared, completed = self._complete_engineering_failure(
            spec=original,
            tag="retry-implementation-contract",
        )
        prior_manifest = parse_canonical(
            self.writer.evidence.read_verified(
                original["implementation_identity"]
            )
        )
        assert isinstance(prior_manifest, dict)
        changed_source = self.writer.evidence.finalize(
            b"implementation-only retry changed source"
        )
        changed_implementation = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    **prior_manifest,
                    "artifact_hashes": [changed_source.sha256],
                }
            )
        )
        with LocalIndex(self.writer.index_path) as index:
            completion = index.get(
                "job-completed",
                completed.result["completion_record_id"],
            )
        assert completion is not None
        implementation_proof = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "changed_dimension": "implementation",
                    "explanation": "only implementation evidence changed",
                    "new_evidence_hashes": [
                        changed_implementation.sha256,
                        changed_source.sha256,
                    ],
                    "new_implementation_identity": (
                        changed_implementation.sha256
                    ),
                    "prior_failure_signature": completion.payload[
                        "failure"
                    ]["failure_signature"],
                    "previous_implementation_identity": original[
                        "implementation_identity"
                    ],
                    "schema": "job_changed_cause.v1",
                }
            )
        )
        base_retry = job_spec(self.writer, subject)
        base_retry["implementation_identity"] = changed_implementation.sha256
        base_retry["changed_cause_proof_hash"] = implementation_proof.sha256
        mutations = {
            "output-name": {
                "expected_outputs": [
                    "local/jobs/fixture/renamed.json"
                ],
                "output_classes": {
                    "local/jobs/fixture/renamed.json": "transient"
                },
            },
            "output-class": {
                "expected_outputs": [
                    "local/cache/fixture/fixture.json"
                ],
                "output_classes": {
                    "local/cache/fixture/fixture.json": "reproducible_cache"
                },
            },
            "log-path": {"log_path": "local/jobs/changed-fixture.log"},
            "stop-rule": {
                "timeout_or_stop_rule": "stop_at_31_seconds"
            },
            "resume-action": {"resume_action": "resume_changed_job"},
            "worker-claims": {
                "worker_claims": [
                    {
                        "worker_id": "worker-a",
                        "inputs": ["input-a"],
                        "outputs": ["output-a"],
                        "resources": ["gpu-a"],
                    },
                    {
                        "worker_id": "worker-b",
                        "inputs": ["input-b"],
                        "outputs": ["output-b"],
                        "resources": ["cpu-b"],
                    },
                ]
            },
            "budget": {
                "budget": {
                    "compute_seconds": 31,
                    "wall_seconds": 31,
                    "trials": 1,
                }
            },
        }
        for label, changed_fields in mutations.items():
            retry = parse_canonical(canonical_bytes(base_retry))
            assert isinstance(retry, dict)
            retry.update(changed_fields)
            with self.subTest(field=label):
                with self.assertRaisesRegex(
                    IdenticalFailedRetryError,
                    "operational contract",
                ):
                    self.writer.declare_job(
                        spec=retry,
                        operation_id=(
                            "reject-implementation-contract-laundering-"
                            + label
                        ),
                    )

    def test_implementation_byte_change_requires_validated_cause_resolution(
        self,
    ) -> None:
        self._open_mission("MIS-RETRY-IMPLEMENTATION-VALIDATION")
        subject = {
            "kind": "Mission",
            "id": "MIS-RETRY-IMPLEMENTATION-VALIDATION",
        }
        original = job_spec(self.writer, subject)
        _declared, completed = self._complete_engineering_failure(
            spec=original,
            tag="retry-implementation-validation",
        )
        previous_manifest = parse_canonical(
            self.writer.evidence.read_verified(
                original["implementation_identity"]
            )
        )
        assert isinstance(previous_manifest, dict)
        comment_only_source = self.writer.evidence.finalize(
            b"# unrelated comment-only implementation variation\n"
        )
        changed_implementation = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    **previous_manifest,
                    "artifact_hashes": [comment_only_source.sha256],
                }
            )
        )
        retry = job_spec(self.writer, subject)
        retry["implementation_identity"] = changed_implementation.sha256
        unresolved_proof = self._implementation_retry_proof(
            completion_record_id=completed.result["completion_record_id"],
            current_spec=retry,
            resolved=False,
            tag="comment-only-change",
        )
        retry["changed_cause_proof_hash"] = unresolved_proof
        with self.assertRaisesRegex(
            IdenticalFailedRetryError,
            "registered engineering retry validation failed",
        ):
            self.writer.declare_job(
                spec=retry,
                operation_id="reject-comment-only-implementation-retry",
            )
        with LocalIndex(self.writer.index_path) as index:
            self.assertEqual(index.records_by_kind("job-retry-basis"), ())

        resolved_proof = self._implementation_retry_proof(
            completion_record_id=completed.result["completion_record_id"],
            current_spec=retry,
            resolved=True,
            tag="measured-cause-resolution",
        )
        retry["changed_cause_proof_hash"] = resolved_proof
        validator_calls = 0
        registered_validate = self.writer.validation_registry.validate

        def validate_after_lock_release(request):
            nonlocal validator_calls
            with WriterLock(self.writer.lock_path, timeout_seconds=1):
                pass
            validator_calls += 1
            return registered_validate(request)

        with patch.object(
            self.writer.validation_registry,
            "validate",
            side_effect=validate_after_lock_release,
        ):
            retried = self.writer.declare_job(
                spec=retry,
                operation_id="allow-validated-implementation-retry",
            )
        self.assertEqual(validator_calls, 1)
        with LocalIndex(self.writer.index_path) as index:
            declaration = index.get(
                "job-declared",
                retried.result["job_id"],
            )
            bases = index.records_by_kind("job-retry-basis")
        assert declaration is not None
        self.assertEqual(len(bases), 1)
        basis = bases[0]
        self.assertEqual(basis.status, "consumed")
        self.assertEqual(
            basis.payload["consumed_by_job_id"],
            declaration.record_id,
        )
        self.assertEqual(
            basis.authority_sequence,
            declaration.authority_sequence,
        )
        self.assertEqual(
            declaration.payload["retry_basis_record_ids"],
            [basis.record_id],
        )
        validation = basis.payload["validations"][0]
        self.assertEqual(validation["validated_verdict"], "passed")
        self.assertTrue(validation["facts"]["cause_resolved"])
        self.assertEqual(
            validation["declared_artifact_count"],
            validation["opened_artifact_count"],
        )

    def test_caller_passed_and_empty_registry_fail_closed_without_consumption(
        self,
    ) -> None:
        self._open_mission("MIS-RETRY-VALIDATOR-AUTHORITY")
        subject = {
            "kind": "Mission",
            "id": "MIS-RETRY-VALIDATOR-AUTHORITY",
        }
        original = job_spec(self.writer, subject)
        declared, completed = self._complete_engineering_failure(
            spec=original,
            tag="retry-validator-authority",
        )
        with LocalIndex(self.writer.index_path) as index:
            prior = index.get("job-declared", declared.result["job_id"])
        assert prior is not None
        forged_passed = self._retry_authority(
            completion_record_id=completed.result["completion_record_id"],
            changed_dimension="cause",
            new_work_fingerprint=prior.payload["work_fingerprint"],
            tag="forged-caller-passed",
            resolved=False,
        )
        retry = job_spec(self.writer, subject)
        retry["changed_cause_proof_hash"] = forged_passed
        with self.assertRaisesRegex(
            IdenticalFailedRetryError,
            "registered engineering retry validation failed",
        ):
            self.writer.declare_job(
                spec=retry,
                operation_id="reject-caller-authored-passed",
            )
        self.writer.validation_registry = EvidenceValidatorRegistry()
        valid_but_unregistered = self._retry_authority(
            completion_record_id=completed.result["completion_record_id"],
            changed_dimension="cause",
            new_work_fingerprint=prior.payload["work_fingerprint"],
            tag="empty-registry",
        )
        retry["changed_cause_proof_hash"] = valid_but_unregistered
        with self.assertRaisesRegex(
            IdenticalFailedRetryError,
            "registered engineering retry validation failed",
        ):
            self.writer.declare_job(
                spec=retry,
                operation_id="reject-empty-engineering-registry",
            )
        with LocalIndex(self.writer.index_path) as index:
            self.assertEqual(index.records_by_kind("job-retry-basis"), ())

    def test_source_retry_family_separates_transition_evidence(self) -> None:
        mission_id = "MIS-SOURCE-RETRY-FAMILY"
        subject = {"kind": "Mission", "id": mission_id}
        plan_hash = "e" * 64
        source_contract_id = "source:" + "a" * 64
        result_output = "evidence/source/result.json"
        measurement_output = "evidence/source/measurement.json"

        def source_spec(transition_evidence: str) -> dict[str, object]:
            spec = job_spec(self.writer, subject)
            spec["input_hashes"] = sorted(
                [*spec["input_hashes"], plan_hash]
            )
            spec["expected_outputs"] = [
                measurement_output,
                result_output,
            ]
            spec["output_classes"] = {
                measurement_output: "durable_evidence",
                result_output: "durable_evidence",
            }
            spec["source_binding"] = {
                "result_manifest_output": result_output,
                "source_contract_id": source_contract_id,
                "transition_evidence": transition_evidence,
                "validation_plan_hash": plan_hash,
                "validator_id": "validator:" + "b" * 64,
            }
            normalized = self.writer._normalize_job_spec(spec)
            self.writer._validate_job_spec(normalized)
            return normalized

        historical = derive_job_retry_family(
            mission_id=mission_id,
            initiative_id=None,
            study_id=None,
            batch_id=None,
            spec=source_spec("historical_audit"),
        )
        runtime = derive_job_retry_family(
            mission_id=mission_id,
            initiative_id=None,
            study_id=None,
            batch_id=None,
            spec=source_spec("runtime_availability_proof"),
        )
        drift = derive_job_retry_family(
            mission_id=mission_id,
            initiative_id=None,
            study_id=None,
            batch_id=None,
            spec=source_spec("drift"),
        )
        recertification = derive_job_retry_family(
            mission_id=mission_id,
            initiative_id=None,
            study_id=None,
            batch_id=None,
            spec=source_spec("same_semantics_recertification"),
        )
        families = (historical, runtime, drift, recertification)
        self.assertEqual(
            {family.target["source_contract_id"] for family in families},
            {source_contract_id},
        )
        self.assertEqual(
            {family.target["transition_evidence"] for family in families},
            {
                "historical_audit",
                "runtime_availability_proof",
                "drift",
                "same_semantics_recertification",
            },
        )
        self.assertEqual(len({family.fingerprint for family in families}), 4)

    def test_typed_cause_release_retries_same_implementation(self) -> None:
        self._open_mission("MIS-RETRY-CAUSE")
        subject = {"kind": "Mission", "id": "MIS-RETRY-CAUSE"}
        original = job_spec(self.writer, subject)
        declared, completed = self._complete_engineering_failure(
            spec=original,
            tag="retry-cause",
        )
        with LocalIndex(self.writer.index_path) as index:
            prior = index.get("job-declared", declared.result["job_id"])
        assert prior is not None
        authority_hash = self._retry_authority(
            completion_record_id=completed.result["completion_record_id"],
            changed_dimension="cause",
            new_work_fingerprint=prior.payload["work_fingerprint"],
            tag="retry-cause",
        )
        retry = job_spec(self.writer, subject)
        retry["changed_cause_proof_hash"] = authority_hash
        retried = self.writer.declare_job(
            spec=retry,
            operation_id="allow-typed-cause-family-release",
        )
        with LocalIndex(self.writer.index_path) as index:
            current = index.get("job-declared", retried.result["job_id"])
            bases = index.records_by_kind("job-retry-basis")
            family_head = index.event_head(
                "job-retry-family:"
                + prior.payload["retry_family_fingerprint"]
            )
        assert current is not None and family_head is not None
        self.assertEqual(
            current.payload["spec"]["implementation_identity"],
            prior.payload["spec"]["implementation_identity"],
        )
        self.assertEqual(
            current.payload["work_fingerprint"],
            prior.payload["work_fingerprint"],
        )
        self.assertEqual(len(bases), 1)
        basis = bases[0]
        self.assertEqual(basis.status, "consumed")
        self.assertEqual(
            basis.payload["consumed_by_job_id"],
            current.record_id,
        )
        self.assertEqual(basis.authority_sequence, current.authority_sequence)
        self.assertEqual(
            current.payload["retry_basis_record_ids"],
            [basis.record_id],
        )
        validation = basis.payload["validations"][0]
        self.assertEqual(validation["validated_verdict"], "passed")
        self.assertEqual(
            validation["declared_artifact_count"],
            validation["opened_artifact_count"],
        )
        self.assertEqual(family_head.record_kind, "job-retry-family-attempt")

    def test_compute_retry_keeps_cumulative_original_batch_ceiling(self) -> None:
        study_id = self._open_batch(max_compute_seconds=50)
        subject = {"kind": "Study", "id": study_id}
        original = job_spec(self.writer, subject)
        declared, completed = self._complete_engineering_failure(
            spec=original,
            tag="retry-budget",
            continue_batch=True,
        )
        with LocalIndex(self.writer.index_path) as index:
            prior = index.get("job-declared", declared.result["job_id"])
        assert prior is not None
        retry = job_spec(self.writer, subject)
        retry["budget"] = {
            "compute_seconds": 25,
            "wall_seconds": 25,
            "trials": 1,
        }
        authority_hash = self._retry_authority(
            completion_record_id=completed.result["completion_record_id"],
            changed_dimension="compute_budget",
            new_work_fingerprint=prior.payload["work_fingerprint"],
            tag="retry-budget",
        )
        retry["changed_cause_proof_hash"] = authority_hash
        with self.assertRaisesRegex(
            TransitionError,
            "exceeds the frozen Batch",
        ):
            self.writer.declare_job(
                spec=retry,
                operation_id="reject-retry-over-original-batch-ceiling",
            )
        with LocalIndex(self.writer.index_path) as index:
            reservations = index.records_by_kind(
                "batch-budget-reservation"
            )
            retry_bases = index.records_by_kind("job-retry-basis")
        self.assertEqual(len(reservations), 1)
        self.assertEqual(
            reservations[0].payload["compute_seconds"],
            30,
        )
        self.assertEqual(retry_bases, ())

    def test_historical_scientific_change_terminal_cannot_release_same_family(
        self,
    ) -> None:
        self._open_mission("MIS-RETRY-SCIENCE")
        subject = {"kind": "Mission", "id": "MIS-RETRY-SCIENCE"}
        original = job_spec(self.writer, subject)
        declared, completed = self._complete_engineering_failure(
            spec=original,
            tag="retry-science",
        )
        with LocalIndex(self.writer.index_path) as index:
            prior = index.get("job-declared", declared.result["job_id"])
            completion = index.get(
                "job-completed",
                completed.result["completion_record_id"],
            )
        assert prior is not None
        assert completion is not None
        authority_hash = self._retry_authority(
            completion_record_id=completed.result["completion_record_id"],
            changed_dimension="information",
            new_work_fingerprint=prior.payload["work_fingerprint"],
            tag="retry-science",
        )
        retry = job_spec(self.writer, subject)
        retry["changed_cause_proof_hash"] = authority_hash
        with self.assertRaisesRegex(
            JobRetryFamilyError,
            "scientific-change disposition cannot release the same Job family",
        ):
            parse_job_retry_resume_authority(
                self.writer.evidence.read_verified(authority_hash),
                mission_id="MIS-RETRY-SCIENCE",
                evidence_subject=dict(retry["evidence_subject"]),
                retry_family_fingerprint=prior.payload[
                    "retry_family_fingerprint"
                ],
                prior_completion_record_id=completion.record_id,
                prior_job_id=prior.record_id,
                prior_job_hash=prior.fingerprint,
                prior_work_fingerprint=prior.payload["work_fingerprint"],
                new_work_fingerprint=prior.payload["work_fingerprint"],
                failure=completion.payload["failure"],
                engineering_disposition={
                    **completion.payload["engineering_disposition"],
                    "disposition": "requires_scientific_change",
                },
                previous_spec=prior.payload["spec"],
                current_spec=retry,
                read_evidence=self.writer.evidence.read_verified,
                verify_evidence=self.writer.evidence.verify,
                evidence_path=self.writer.evidence.verified_path,
                validation_registry=self.writer.validation_registry,
                engineering_fixture=True,
            )


if __name__ == "__main__":
    unittest.main()
