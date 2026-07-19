"""Engineering Repair evaluation, disposition, semantic proof, and close transitions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.permits import Permit, PermitKind, SubjectKind
from axiom_rift.operations.repair_candidate import (
    VALIDATION_UNAVAILABLE_REASON_CODES,
    RepairCandidate,
    RepairCandidateError,
    RepairEvaluation,
    build_repair_evaluation,
    parse_repair_candidate,
    parse_repair_evaluation,
)
from axiom_rift.operations.repair_observation_authority import (
    REPAIR_VALIDATION_OBSERVATION_SCHEMA,
    RepairObservationAuthorityError,
    require_repair_validation_observation_stream,
)
from axiom_rift.operations.repair_protocol import (
    EngineeringFailureDisposition,
    RepairAttemptProof,
    repair_attempt_intervention_fingerprint,
)
from axiom_rift.operations.repair_semantic_equivalence import (
    FIXED_HOLD_AUTHORITY_CORRECTION_PROTOCOL,
    IMPLEMENTATION_REPAIR_V2_SCHEMA,
    RepairSemanticEquivalenceError,
    SEMANTIC_EQUIVALENCE_PROTOCOL,
    SEMANTIC_EQUIVALENCE_VALIDATOR_ID,
    build_semantic_equivalence_binding,
    build_semantic_equivalence_plan,
    require_passed_fixed_hold_authority_correction_facts,
    require_passed_semantic_equivalence_facts,
)
from axiom_rift.operations.repair_validation import (
    DISPOSITION_TRACE_SCHEMA,
    REGISTERED_REPAIR_AUTHORITY_SCHEMA,
    RepairValidationError,
    build_repair_candidate_validation_context,
    build_repair_validation_plan,
    parse_repair_candidate_validation_receipt,
    repair_validation_binding,
    repair_validation_capabilities,
    require_stored_accepted_repair_candidate_attempt,
    require_stored_engineering_disposition_validation,
    require_stored_repair_attempt_validation,
    require_stored_repair_candidate_validation,
    validate_repair_candidate,
)
from axiom_rift.operations.validation import (
    EvidenceValidationError,
    EvidenceValidationRequest,
    ValidationArtifact,
)
from axiom_rift.operations.writer_support import (
    IdenticalFailedRetryError,
    RecoveryRequired,
    TransitionError,
    TransitionResult,
    _copy,
    _digest,
    _record,
    _require_ascii,
    _require_digest,
    _require_manifest,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex
from axiom_rift.storage.state import WriterLock


class RepairSemanticEquivalenceUnavailable(TransitionError):
    """A Repair candidate lacks positive semantic-equivalence authority."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


_REPAIR_EVALUATION_CAPABILITY_TOKEN = object()
_REPAIR_DISPOSITION_CAPABILITY_TOKEN = object()
_REPAIR_DISPOSITION_MATERIALIZATION_TOKEN = object()


@dataclass(frozen=True, slots=True)
class _RepairEvaluationCapability:
    """Unforgeable in-process handoff from one dispatch to one Writer event."""

    token: object
    control_hash: str
    candidate: RepairCandidate
    evaluation: RepairEvaluation
    repair_validation: Mapping[str, Any]
    semantic_equivalence_validation: Mapping[str, Any] | None
    semantic_equivalence_validation_hash: str | None


@dataclass(frozen=True, slots=True)
class _RepairDispositionCapability:
    """One registered terminal derivation bound to one stable control head."""

    token: object
    control_hash: str
    disposition_hash: str
    disposition: EngineeringFailureDisposition
    disposition_validation: Mapping[str, Any]
    disposition_validation_hash: str


_EXPECTED_FIXED_HOLD_AUTHORITY_CORRECTION_VALIDATOR_ID = (
    "validator:78193d66002ab49722aff28814cbb1120c4a81953a4d8b446e108bc664411bfe"
)
_EXPECTED_FIXED_HOLD_REPAIR_ATTEMPT_VALIDATOR_ID = (
    "validator:9008a7b6bdb676c71d7bf34b4a1f02f38b4dbfc73b3093261708358673887ad7"
)


def _fixed_hold_authority_correction_validator_id() -> str:
    """Lazy-load and pin the one registered production correction capability."""

    from axiom_rift.operations.fixed_hold_repair_equivalence import (
        FIXED_HOLD_AUTHORITY_CORRECTION_VALIDATOR_ID,
    )

    if (
        FIXED_HOLD_AUTHORITY_CORRECTION_VALIDATOR_ID
        != _EXPECTED_FIXED_HOLD_AUTHORITY_CORRECTION_VALIDATOR_ID
    ):
        raise EvidenceValidationError(
            "fixed-hold correction validator differs from its registered capability"
        )
    return FIXED_HOLD_AUTHORITY_CORRECTION_VALIDATOR_ID


def _fixed_hold_repair_attempt_validator() -> tuple[str, str]:
    """Lazy-load and pin the production engineering Repair capability."""

    from axiom_rift.operations.fixed_hold_repair_validation import (
        FIXED_HOLD_REPAIR_ATTEMPT_PROTOCOL,
        FIXED_HOLD_REPAIR_ATTEMPT_VALIDATOR_ID,
    )

    if (
        FIXED_HOLD_REPAIR_ATTEMPT_VALIDATOR_ID
        != _EXPECTED_FIXED_HOLD_REPAIR_ATTEMPT_VALIDATOR_ID
    ):
        raise EvidenceValidationError(
            "fixed-hold Repair validator differs from its registered capability"
        )
    return (
        FIXED_HOLD_REPAIR_ATTEMPT_VALIDATOR_ID,
        FIXED_HOLD_REPAIR_ATTEMPT_PROTOCOL,
    )


class RepairWriterMixin:
    """Own engineering Repair state transitions behind the atomic Writer facade."""

    def _engineering_failure_cause(
        self,
        failure: Mapping[str, Any],
    ) -> tuple[dict[str, Any], str]:
        failure_manifest = _require_manifest(
            "repair failure",
            failure,
            required={
                "failure_kind",
                "minimum_reproduction_evidence",
                "root_cause",
                "interrupted_action",
            },
        )
        if set(failure_manifest) != {
            "failure_kind",
            "minimum_reproduction_evidence",
            "root_cause",
            "interrupted_action",
        } or failure_manifest.get("failure_kind") != "engineering":
            raise TransitionError(
                "Repair requires one exact engineering failure manifest"
            )
        for name in ("root_cause", "interrupted_action"):
            _require_ascii(name, failure_manifest[name])
        references = failure_manifest["minimum_reproduction_evidence"]
        if (
            not isinstance(references, list)
            or not references
            or references != sorted(set(references))
        ):
            raise TransitionError(
                "Repair requires sorted unique minimum reproduction evidence"
            )
        for reference in references:
            self.evidence.verify(reference)
        cause_hash = _digest(failure_manifest, domain="repair-cause")
        return failure_manifest, cause_hash

    def open_repair(
        self,
        *,
        permit: Permit,
        failure: Mapping[str, Any],
        operation_id: str,
    ) -> TransitionResult:
        failure_manifest, cause_hash = self._engineering_failure_cause(
            failure
        )

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            job = science["active_job"]
            if not isinstance(job, dict) or job["status"] != "running":
                raise TransitionError("Repair requires a running Job")
            if science["active_repair"] is not None:
                raise TransitionError("another Repair is active")
            if job.get("required_repair_resume_record_id") is not None:
                raise TransitionError(
                    "a repaired Job must re-enter its engine before another Repair"
                )
            declaration = index.get("job-declared", job["id"])
            if declaration is None:
                raise TransitionError("interrupted Job declaration is absent")
            job_spec = declaration.payload["spec"]
            if failure_manifest["interrupted_action"] != job_spec["callable_identity"]:
                raise TransitionError("Repair interrupted action differs from the Job")
            resume_action = job_spec["resume_action"]
            self._validate_permit_locked(
                control=current,
                index=index,
                permit=permit,
                expected_kind=PermitKind.REPAIR,
                action="open_repair",
                subject_kind=SubjectKind.JOB,
                subject_id=job["id"],
                expected_input_hash=job["hash"],
            )
            repair_stream = f"job-repair:{job['id']}"
            predecessor_head = index.event_head(repair_stream)
            predecessor = (
                None
                if predecessor_head is None
                else index.get(
                    predecessor_head.record_kind,
                    predecessor_head.record_id,
                )
            )
            if predecessor_head is not None and (
                predecessor is None
                or predecessor.kind != "repair-close"
                or predecessor.status != "repaired"
                or predecessor.subject != f"Job:{job['id']}"
            ):
                raise RecoveryRequired(
                    "running Job Repair predecessor is invalid"
                )
            repair_episode = (
                1
                if predecessor_head is None
                else predecessor_head.sequence + 1
            )
            predecessor_id = (
                None if predecessor is None else predecessor.record_id
            )
            repair_id = (
                "repair:"
                + canonical_digest(
                    domain="repair",
                    payload={
                        "cause_hash": cause_hash,
                        "episode": repair_episode,
                        "job_id": job["id"],
                        "predecessor_repair_close_record_id": predecessor_id,
                    },
                )
            )
            job["status"] = "interrupted_repair"
            science["active_repair"] = {
                "id": repair_id,
                "job_id": job["id"],
                "cause_hash": cause_hash,
                "episode": repair_episode,
                "latest_attempt_record_id": None,
                "latest_basis_hash": cause_hash,
                "predecessor_repair_close_record_id": predecessor_id,
                "repair_authority_schema": REGISTERED_REPAIR_AUTHORITY_SCHEMA,
                "repair_validation_scope": (
                    "fixture_only" if self.engineering_fixture else "production"
                ),
                "resume_action": resume_action,
            }
            body["next_action"] = {"kind": "execute_repair", "repair_id": repair_id}
            consumption = self._permit_consumption_record(permit, operation_id)
            record = _record(
                kind="repair-open",
                record_id=repair_id,
                subject=f"Job:{job['id']}",
                status="open",
                fingerprint=cause_hash,
                payload={
                    **failure_manifest,
                    "episode": repair_episode,
                    "predecessor_repair_close_record_id": predecessor_id,
                    "repair_authority_schema": REGISTERED_REPAIR_AUTHORITY_SCHEMA,
                    "repair_validation_scope": (
                        "fixture_only"
                        if self.engineering_fixture
                        else "production"
                    ),
                    "resume_action": resume_action,
                    "scientific_trial_delta": 0,
                },
            )
            return body, [consumption, record], {"repair_id": repair_id}

        return self._commit(
            event_kind="repair_opened",
            operation_id=operation_id,
            subject=f"Job:{permit.subject.subject_id}",
            payload={"cause_hash": cause_hash, "failure": failure_manifest},
            prepare=prepare,
        )

    def _repair_attempt_context(
        self,
        index: LocalIndex,
        *,
        repair: Mapping[str, Any],
        job: Mapping[str, Any],
    ) -> tuple[
        IndexRecord,
        IndexRecord | None,
        str | None,
        str,
        int,
        tuple[str, ...],
    ]:
        repair_id = repair.get("id")
        if not isinstance(repair_id, str):
            raise TransitionError("active Repair identity is invalid")
        opened = index.get("repair-open", repair_id)
        if (
            opened is None
            or opened.status != "open"
            or opened.subject != f"Job:{job.get('id')}"
            or opened.fingerprint != repair.get("cause_hash")
            or opened.payload.get("episode") != repair.get("episode")
            or opened.payload.get("failure_kind") != "engineering"
            or opened.payload.get(
                "predecessor_repair_close_record_id"
            )
            != repair.get("predecessor_repair_close_record_id")
            or opened.payload.get("resume_action")
            != repair.get("resume_action")
            or opened.payload.get("repair_authority_schema")
            != REGISTERED_REPAIR_AUTHORITY_SCHEMA
            or repair.get("repair_authority_schema")
            != REGISTERED_REPAIR_AUTHORITY_SCHEMA
            or opened.payload.get("repair_validation_scope")
            != repair.get("repair_validation_scope")
            or repair.get("repair_validation_scope")
            != ("fixture_only" if self.engineering_fixture else "production")
        ):
            raise TransitionError("Repair cause record is absent")
        stream = f"repair-attempt:{repair_id}"
        head = index.event_head(stream)
        prior: IndexRecord | None = None
        prior_record_id: str | None = None
        previous_basis = repair.get("cause_hash")
        if not isinstance(previous_basis, str):
            raise RecoveryRequired("Repair cause basis is unavailable")
        used_bases = [previous_basis]
        if head is not None:
            for ordinal in range(1, head.sequence + 1):
                record = index.event_record(stream, ordinal)
                if record is None:
                    raise RecoveryRequired("Repair attempt stream has a gap")
                new_basis = record.payload.get("new_basis_hash")
                if (
                    record.kind != "repair-attempt"
                    or record.status != "failed"
                    or record.subject != f"Repair:{repair_id}"
                    or record.payload.get("job_id") != job.get("id")
                    or record.payload.get("repair_id") != repair_id
                    or record.payload.get("cause_hash")
                    != repair.get("cause_hash")
                    or record.payload.get("prior_attempt_record_id")
                    != prior_record_id
                    or record.payload.get("previous_basis_hash")
                    != previous_basis
                    or not isinstance(new_basis, str)
                ):
                    raise RecoveryRequired(
                        "Repair attempt stream does not form one changed-basis chain"
                    )
                prior = record
                prior_record_id = record.record_id
                previous_basis = new_basis
                used_bases.append(new_basis)
            if (
                prior is None
                or head.record_kind != prior.kind
                or head.record_id != prior.record_id
            ):
                raise RecoveryRequired("Repair attempt head is invalid")
        sequence = 1 if head is None else head.sequence + 1
        if (
            repair.get("latest_attempt_record_id") != prior_record_id
            or repair.get("latest_basis_hash") != previous_basis
        ):
            raise RecoveryRequired("active Repair trails its attempt stream")
        return (
            opened,
            prior,
            prior_record_id,
            previous_basis,
            sequence,
            tuple(used_bases),
        )

    def _parse_active_repair_candidate(
        self,
        *,
        index: LocalIndex,
        candidate_hash: str,
        repair: Mapping[str, Any],
        job: Mapping[str, Any],
        opened: IndexRecord,
        prior_record_id: str | None,
        previous_basis: str,
        used_basis_hashes: Sequence[str],
    ) -> RepairCandidate:
        """Bind one outcome-free candidate to the exact active Repair head."""

        try:
            attempt_records: list[IndexRecord] = []
            accepted_changed_evidence: set[str] = set()
            attempt_head = index.event_head(f"repair-attempt:{repair['id']}")
            if attempt_head is not None:
                for sequence in range(1, attempt_head.sequence + 1):
                    attempt_record = index.event_record(
                        f"repair-attempt:{repair['id']}", sequence
                    )
                    if attempt_record is None:
                        raise RepairObservationAuthorityError(
                            "accepted Repair attempt stream has a gap"
                        )
                    attempt_records.append(attempt_record)
                    changed_evidence = attempt_record.payload.get(
                        "new_evidence_hashes"
                    )
                    if (
                        not isinstance(changed_evidence, (list, tuple))
                        or any(type(identity) is not str for identity in changed_evidence)
                    ):
                        raise RepairObservationAuthorityError(
                            "accepted Repair attempt changed evidence is malformed"
                        )
                    accepted_changed_evidence.update(changed_evidence)
            declaration = index.get("job-declared", str(job["id"]))
            mission_id = (
                None
                if declaration is None
                else declaration.payload.get("mission_id")
            )
            if type(mission_id) is not str:
                raise RepairObservationAuthorityError(
                    "Repair candidate Mission authority is unavailable"
                )
            observations, observation_head = (
                require_repair_validation_observation_stream(
                    index,
                    repair_id=str(repair["id"]),
                    job_id=str(job["id"]),
                    job_hash=str(job["hash"]),
                    cause_hash=str(repair["cause_hash"]),
                    reproduction_evidence_hashes=opened.payload[
                        "minimum_reproduction_evidence"
                    ],
                    resume_action=str(repair["resume_action"]),
                    mission_id=mission_id,
                    expected_scope=(
                        "fixture_only"
                        if self.engineering_fixture
                        else "production"
                    ),
                    accepted_attempts=attempt_records,
                    evidence=self.evidence,
                )
            )
            bound_observations = tuple(
                {
                    "new_information_evidence_hashes": list(
                        item["new_information_evidence_hashes"]
                    ),
                    "observation_record_id": item[
                        "observation_record_id"
                    ],
                }
                for item in observations
            )
            candidate = parse_repair_candidate(
                self.evidence.read_verified(candidate_hash),
                repair_id=str(repair["id"]),
                job_id=str(job["id"]),
                job_hash=str(job["hash"]),
                cause_hash=str(repair["cause_hash"]),
                previous_basis_hash=previous_basis,
                prior_attempt_record_id=prior_record_id,
                reproduction_evidence_hashes=opened.payload[
                    "minimum_reproduction_evidence"
                ],
                resume_action=str(repair["resume_action"]),
                expected_prior_validation_observation_head=(
                    observation_head
                ),
                expected_bound_validation_observations=bound_observations,
                verify_evidence=self.evidence.verify,
            )
        except (
            FileNotFoundError,
            OSError,
            RepairCandidateError,
            RepairObservationAuthorityError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            raise TransitionError(str(exc)) from exc
        if candidate.sha256 != candidate_hash:
            raise TransitionError("Repair candidate identity differs from its bytes")
        reused_basis = (
            candidate.new_basis_hash == previous_basis
            or candidate.new_basis_hash in set(used_basis_hashes)
        )
        genuinely_new_changed_evidence = (
            set(candidate.new_evidence_hashes)
            - accepted_changed_evidence
            - set(used_basis_hashes)
        )
        if reused_basis and not genuinely_new_changed_evidence:
            raise IdenticalFailedRetryError(
                "reused Repair basis requires genuinely new changed evidence"
            )
        return candidate

    @staticmethod
    def _repair_candidate_attempt_proof(
        candidate: RepairCandidate,
        evaluation: RepairEvaluation,
    ) -> RepairAttemptProof:
        if evaluation.mode not in {"failure_reproduced", "repaired"}:
            raise TransitionError(
                "zero-credit Repair evaluation cannot enter the attempt stream"
            )
        if (
            evaluation.mode == "repaired"
            and candidate.changed_dimension == "input"
        ):
            raise TransitionError(
                "a changed Job input requires a new Job identity, not in-place Repair"
            )
        return RepairAttemptProof(
            repair_id=candidate.repair_id,
            job_id=candidate.job_id,
            job_hash=candidate.job_hash,
            cause_hash=candidate.cause_hash,
            outcome=(
                "repaired" if evaluation.mode == "repaired" else "failed"
            ),
            changed_dimension=candidate.changed_dimension,
            previous_basis_hash=candidate.previous_basis_hash,
            new_basis_hash=candidate.new_basis_hash,
            prior_attempt_record_id=candidate.prior_attempt_record_id,
            reproduction_evidence_hashes=(
                candidate.reproduction_evidence_hashes
            ),
            new_evidence_hashes=candidate.new_evidence_hashes,
            verification_evidence_hashes=(
                candidate.verification_evidence_hashes
            ),
            implementation_proof_hash=candidate.implementation_proof_hash,
            explanation=candidate.explanation,
            failure_observation=(
                None
                if evaluation.mode == "repaired"
                else "registered_original_failure_reproduced"
            ),
            resume_action=candidate.resume_action,
        )

    @staticmethod
    def _stored_repair_candidate_from_attempt(
        record: IndexRecord,
    ) -> RepairCandidate | None:
        value = record.payload.get("repair_candidate")
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise RepairValidationError(
                "stored Repair candidate payload is invalid"
            )
        try:
            candidate = parse_repair_candidate(
                canonical_bytes(dict(value)),
                repair_id=str(record.payload.get("repair_id")),
                job_id=str(record.payload.get("job_id")),
                job_hash=str(record.payload.get("job_hash")),
                cause_hash=str(record.payload.get("cause_hash")),
                previous_basis_hash=str(
                    record.payload.get("previous_basis_hash")
                ),
                prior_attempt_record_id=record.payload.get(
                    "prior_attempt_record_id"
                ),
                reproduction_evidence_hashes=record.payload.get(
                    "reproduction_evidence_hashes", ()
                ),
                resume_action=str(record.payload.get("resume_action")),
            )
        except (RepairCandidateError, TypeError, ValueError) as exc:
            raise RepairValidationError(str(exc)) from exc
        if (
            record.payload.get("repair_candidate_hash") != candidate.sha256
            or record.payload.get("attempt_proof_hash") != candidate.sha256
        ):
            raise RepairValidationError(
                "stored Repair candidate identity differs"
            )
        return candidate

    def _require_repair_evaluation_capability(
        self,
        *,
        capability: _RepairEvaluationCapability,
        current: Mapping[str, Any],
        candidate: RepairCandidate,
        mission_id: str,
        expected_mode: str,
    ) -> dict[str, Any]:
        if (
            capability.token is not _REPAIR_EVALUATION_CAPABILITY_TOKEN
            or capability.control_hash != current.get("control_hash")
            or capability.candidate != candidate
            or capability.evaluation.candidate_hash != candidate.sha256
            or capability.evaluation.mode != expected_mode
            or (
                capability.semantic_equivalence_validation is None
                and capability.semantic_equivalence_validation_hash
                is not None
            )
            or (
                capability.semantic_equivalence_validation is not None
                and (
                    capability.semantic_equivalence_validation_hash
                    != sha256(
                        canonical_bytes(
                            dict(
                                capability.semantic_equivalence_validation
                            )
                        )
                    ).hexdigest()
                )
            )
        ):
            raise TransitionError(
                "Repair evaluation capability differs from the stable head"
            )
        try:
            return require_stored_repair_candidate_validation(
                candidate=candidate,
                repair_validation=capability.repair_validation,
                mission_id=mission_id,
                evidence=self.evidence,
                expected_scope=(
                    "fixture_only" if self.engineering_fixture else "production"
                ),
            )
        except (RepairValidationError, TypeError, ValueError) as exc:
            raise TransitionError(str(exc)) from exc

    @staticmethod
    def _repair_validation_unavailable_reason(detail: object) -> str:
        reason_code = getattr(detail, "reason_code", None)
        if reason_code in VALIDATION_UNAVAILABLE_REASON_CODES:
            return str(reason_code)
        if isinstance(detail, (FileNotFoundError, OSError)):
            return "declared_artifact_absent_drifted_or_unopened"
        if isinstance(
            detail,
            (
                RepairCandidateError,
                RepairValidationError,
                TypeError,
                ValueError,
            ),
        ):
            return "plan_or_context_binding_mismatch"
        return "validator_execution_failed"

    def _repair_evaluation_from_validation(
        self,
        *,
        candidate: RepairCandidate,
        repair_validation: Mapping[str, Any],
    ) -> RepairEvaluation:
        registered = repair_validation.get("registered_trace")
        evaluation = repair_validation.get("evaluation")
        if not isinstance(registered, Mapping) or not isinstance(
            evaluation, Mapping
        ):
            raise TransitionError("Repair candidate evaluation trace is absent")
        registry = registered.get("registry_trace")
        if not isinstance(registry, Mapping):
            raise TransitionError("Repair candidate registry trace is absent")
        try:
            return parse_repair_evaluation(
                canonical_bytes(dict(evaluation)),
                candidate_hash=candidate.sha256,
                validator_id=str(registry.get("validator_id")),
                validation_plan_hash=str(
                    registered.get("validation_plan_hash")
                ),
                registry_trace_hash=str(
                    repair_validation.get("registered_trace_hash")
                ),
                read_evidence=self.evidence.read_verified,
            )
        except (RepairCandidateError, TypeError, ValueError) as exc:
            raise TransitionError(str(exc)) from exc

    def _record_repair_validation_observation(
        self,
        *,
        _candidate_capability: _RepairEvaluationCapability,
        operation_id: str,
    ) -> TransitionResult:
        if (
            not isinstance(_candidate_capability, _RepairEvaluationCapability)
            or _candidate_capability.token
            is not _REPAIR_EVALUATION_CAPABILITY_TOKEN
        ):
            raise TransitionError(
                "Repair observation requires an evaluated candidate capability"
            )
        candidate_hash = _candidate_capability.candidate.sha256
        evaluation = _candidate_capability.evaluation
        if not evaluation.zero_credit_observation:
            raise TransitionError(
                "accepted Repair evaluation cannot enter the observation stream"
            )

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            repair = science.get("active_repair")
            job = science.get("active_job")
            if not isinstance(repair, dict) or not isinstance(job, dict):
                raise TransitionError(
                    "Repair observation requires one active Repair"
                )
            if (
                job.get("status") != "interrupted_repair"
                or repair.get("job_id") != job.get("id")
            ):
                raise TransitionError("Repair and interrupted Job diverge")
            (
                opened,
                _prior,
                prior_record_id,
                previous_basis,
                _attempt_sequence,
                used_basis_hashes,
            ) = self._repair_attempt_context(index, repair=repair, job=job)
            candidate = self._parse_active_repair_candidate(
                index=index,
                candidate_hash=candidate_hash,
                repair=repair,
                job=job,
                opened=opened,
                prior_record_id=prior_record_id,
                previous_basis=previous_basis,
                used_basis_hashes=used_basis_hashes,
            )
            if (
                _candidate_capability.control_hash
                != current.get("control_hash")
                or _candidate_capability.candidate != candidate
                or evaluation.candidate_hash != candidate.sha256
            ):
                raise TransitionError(
                    "Repair observation capability differs from the stable head"
                )
            declaration = index.get("job-declared", str(job["id"]))
            mission_id = (
                None
                if declaration is None
                else declaration.payload.get("mission_id")
            )
            if type(mission_id) is not str:
                raise TransitionError(
                    "Repair observation lost its Job Mission authority"
                )
            registered_candidate_validation = (
                _candidate_capability.repair_validation
            )
            validation_payload: dict[str, Any] | None = None
            if registered_candidate_validation:
                validation_payload = require_stored_repair_candidate_validation(
                    candidate=candidate,
                    repair_validation=registered_candidate_validation,
                    mission_id=mission_id,
                    evidence=self.evidence,
                    expected_scope=(
                        "fixture_only"
                        if self.engineering_fixture
                        else "production"
                    ),
                )
                stored_evaluation = self._repair_evaluation_from_validation(
                    candidate=candidate,
                    repair_validation=validation_payload,
                )
                if stored_evaluation != evaluation:
                    raise TransitionError(
                        "Repair observation differs from registered evaluation"
                    )
            elif (
                evaluation.mode != "validation_unavailable"
                or evaluation.registry_trace_hash is not None
            ):
                raise TransitionError(
                    "unregistered Repair observation must be validation_unavailable"
                )
            identity_payload = {
                "candidate_hash": candidate.sha256,
                "evaluation": evaluation.payload(),
                "registered_candidate_validation": validation_payload,
                "repair_id": candidate.repair_id,
                "schema": REPAIR_VALIDATION_OBSERVATION_SCHEMA,
            }
            record_id = canonical_digest(
                domain="repair-validation-observation",
                payload=identity_payload,
            )
            if index.get("repair-validation-observation", record_id) is not None:
                raise IdenticalFailedRetryError(
                    "identical Repair validation observation already exists"
                )
            stream = f"repair-validation-observation:{candidate.repair_id}"
            head = index.event_head(stream)
            record = _record(
                kind="repair-validation-observation",
                record_id=record_id,
                subject=f"Repair:{candidate.repair_id}",
                status=evaluation.mode,
                fingerprint=candidate.sha256,
                payload={
                    **identity_payload,
                    "basis_advance": False,
                    "candidate": candidate.payload(),
                    "candidate_delta": 0,
                    "holdout_reveal_delta": 0,
                    "release_delta": 0,
                    "repair_attempt_delta": 0,
                    "repair_authority_schema": (
                        REGISTERED_REPAIR_AUTHORITY_SCHEMA
                    ),
                    "scientific_failure_delta": 0,
                    "scientific_trial_delta": 0,
                },
                event_stream=stream,
                event_sequence=1 if head is None else head.sequence + 1,
            )
            return body, [record], {
                "candidate_hash": candidate.sha256,
                "evaluation_mode": evaluation.mode,
                "observation_record_id": record_id,
                "repair_id": candidate.repair_id,
            }

        return self._commit(
            event_kind="repair_validation_observed",
            operation_id=operation_id,
            subject="Repair:active",
            payload={
                "candidate_hash": candidate_hash,
                "evaluation": evaluation.payload(),
            },
            prepare=prepare,
        )

    def _existing_repair_candidate_operation(
        self,
        *,
        candidate_hash: str,
        operation_id: str,
    ) -> TransitionResult | None:
        """Return an exact prior candidate evaluation without redispatch."""

        with WriterLock(self.lock_path):
            with self._open_authoritative_index() as index:
                self._require_stable_locked(index)
                existing = index.get("operation", operation_id)
                if existing is None:
                    return None
                event_kind = existing.payload.get("event_kind")
                expected_field = {
                    "repair_attempt_failed": "attempt_proof_hash",
                    "repair_closed": "changed_cause_proof_hash",
                    "repair_validation_observed": "candidate_hash",
                }.get(event_kind)
                if (
                    existing.status != "success"
                    or expected_field is None
                    or existing.authority_sequence is None
                    or existing.authority_event_id is None
                    or existing.authority_offset is None
                ):
                    raise TransitionError(
                        "existing Repair candidate operation is invalid"
                    )
                event = self.journal.read_event_at(
                    offset=existing.authority_offset,
                    expected_sequence=existing.authority_sequence,
                    expected_event_id=existing.authority_event_id,
                )
                payload = event.get("payload")
                if (
                    event.get("operation_id") != operation_id
                    or event.get("event_kind") != event_kind
                    or not isinstance(payload, Mapping)
                    or payload.get(expected_field) != candidate_hash
                ):
                    raise TransitionError(
                        "idempotency key reused with different Repair candidate"
                    )
                return TransitionResult(
                    event_id=existing.authority_event_id,
                    revision=existing.authority_sequence,
                    reused=True,
                    result=existing.payload.get("result", {}),
                )

    def evaluate_repair_candidate(
        self,
        *,
        candidate_hash: str,
        operation_id: str,
    ) -> TransitionResult:
        """Dispatch once outside the Writer lock, then consume at one head."""

        _require_digest("Repair candidate", candidate_hash)
        _require_ascii("operation_id", operation_id)
        existing = self._existing_repair_candidate_operation(
            candidate_hash=candidate_hash,
            operation_id=operation_id,
        )
        if existing is not None:
            return existing
        with WriterLock(self.lock_path):
            with self._open_authoritative_index() as index:
                current = self._require_stable_locked(index)
                assert current is not None
                science = current["scientific"]
                repair = science.get("active_repair")
                job = science.get("active_job")
                if not isinstance(repair, Mapping) or not isinstance(
                    job, Mapping
                ):
                    raise TransitionError(
                        "Repair candidate evaluation requires an active Repair"
                    )
                (
                    opened,
                    _prior,
                    prior_record_id,
                    previous_basis,
                    _attempt_sequence,
                    used_basis_hashes,
                ) = self._repair_attempt_context(
                    index,
                    repair=repair,
                    job=job,
                )
                candidate = self._parse_active_repair_candidate(
                    index=index,
                    candidate_hash=candidate_hash,
                    repair=repair,
                    job=job,
                    opened=opened,
                    prior_record_id=prior_record_id,
                    previous_basis=previous_basis,
                    used_basis_hashes=used_basis_hashes,
                )
                declaration = index.get("job-declared", candidate.job_id)
                mission_id = (
                    None
                    if declaration is None
                    else declaration.payload.get("mission_id")
                )
                if type(mission_id) is not str:
                    raise TransitionError(
                        "Repair candidate lost its Job Mission authority"
                    )
                stable_control_hash = str(current["control_hash"])

        if len(candidate.verification_evidence_hashes) != 1:
            raise TransitionError(
                "Repair candidate requires one routing receipt"
            )
        try:
            route = parse_repair_candidate_validation_receipt(
                self.evidence.read_verified(
                    candidate.verification_evidence_hashes[0]
                )
            )
        except (
            FileNotFoundError,
            OSError,
            RepairValidationError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            raise TransitionError(str(exc)) from exc
        repair_validation: dict[str, Any] | None
        try:
            repair_validation = validate_repair_candidate(
                candidate=candidate,
                mission_id=mission_id,
                evidence=self.evidence,
                registry=self.validation_registry,
                engineering_fixture=self.engineering_fixture,
            )
            evaluation = self._repair_evaluation_from_validation(
                candidate=candidate,
                repair_validation=repair_validation,
            )
        except (
            EvidenceValidationError,
            FileNotFoundError,
            OSError,
            RepairValidationError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            repair_validation = None
            reason_code = self._repair_validation_unavailable_reason(exc)
            try:
                evaluation_payload = build_repair_evaluation(
                    candidate_hash=candidate.sha256,
                    validator_id=route["validator_id"],
                    validation_plan_hash=route["check_plan_hash"],
                    registry_trace_hash=None,
                    mode="validation_unavailable",
                    cause_resolved=None,
                    failure_reproduced=None,
                    material_change=None,
                    new_failure_manifest_hash=None,
                    reason_code=reason_code,
                )
                evaluation = parse_repair_evaluation(
                    canonical_bytes(evaluation_payload),
                    candidate_hash=candidate.sha256,
                    validator_id=route["validator_id"],
                    validation_plan_hash=route["check_plan_hash"],
                    registry_trace_hash=None,
                )
            except RepairCandidateError as candidate_exc:
                raise TransitionError(str(candidate_exc)) from candidate_exc
        semantic_equivalence_validation: dict[str, Any] | None = None
        if evaluation.mode == "repaired":
            try:
                semantic_dispatch = (
                    self._prepare_candidate_semantic_equivalence_dispatch(
                        candidate=candidate,
                        expected_control_hash=stable_control_hash,
                    )
                )
                if semantic_dispatch is not None:
                    semantic_equivalence_validation = (
                        self._run_implementation_repair_semantic_equivalence(
                            **semantic_dispatch
                        )
                    )
            except TransitionError:
                # The close boundary converts an absent positive semantic
                # capability into one typed zero-credit observation.  No
                # validator is retried while holding the Writer lock.
                semantic_equivalence_validation = None
        semantic_validation_hash = (
            None
            if semantic_equivalence_validation is None
            else sha256(
                canonical_bytes(semantic_equivalence_validation)
            ).hexdigest()
        )
        capability = _RepairEvaluationCapability(
            token=_REPAIR_EVALUATION_CAPABILITY_TOKEN,
            control_hash=stable_control_hash,
            candidate=candidate,
            evaluation=evaluation,
            repair_validation=(
                {} if repair_validation is None else repair_validation
            ),
            semantic_equivalence_validation=(
                semantic_equivalence_validation
            ),
            semantic_equivalence_validation_hash=semantic_validation_hash,
        )
        if evaluation.zero_credit_observation:
            return self._record_repair_validation_observation(
                _candidate_capability=capability,
                operation_id=operation_id,
            )
        if evaluation.mode == "failure_reproduced":
            return self.record_failed_repair_attempt(
                attempt_proof_hash=candidate_hash,
                operation_id=operation_id,
                _candidate_capability=capability,
            )
        try:
            return self.close_repair(
                changed_cause_proof_hash=candidate_hash,
                operation_id=operation_id,
                _candidate_capability=capability,
            )
        except RepairSemanticEquivalenceUnavailable as exc:
            inner = parse_canonical(
                self.evidence.read_verified(
                    str(candidate.implementation_proof_hash)
                )
            )
            if not isinstance(inner, Mapping):
                raise
            semantic_validator_id = inner.get(
                "semantic_equivalence_validator_id"
            )
            semantic_plan_hash = inner.get(
                "semantic_equivalence_validation_plan_hash"
            )
            unavailable_payload = build_repair_evaluation(
                candidate_hash=candidate.sha256,
                validator_id=str(semantic_validator_id),
                validation_plan_hash=str(semantic_plan_hash),
                registry_trace_hash=None,
                mode="validation_unavailable",
                cause_resolved=None,
                failure_reproduced=None,
                material_change=None,
                new_failure_manifest_hash=None,
                reason_code=self._repair_validation_unavailable_reason(exc),
            )
            unavailable = parse_repair_evaluation(
                canonical_bytes(unavailable_payload),
                candidate_hash=candidate.sha256,
                validator_id=str(semantic_validator_id),
                validation_plan_hash=str(semantic_plan_hash),
                registry_trace_hash=None,
            )
            unavailable_capability = _RepairEvaluationCapability(
                token=_REPAIR_EVALUATION_CAPABILITY_TOKEN,
                control_hash=capability.control_hash,
                candidate=capability.candidate,
                evaluation=unavailable,
                repair_validation={},
                semantic_equivalence_validation=None,
                semantic_equivalence_validation_hash=None,
            )
            return self._record_repair_validation_observation(
                _candidate_capability=unavailable_capability,
                operation_id=operation_id,
            )

    def record_failed_repair_attempt(
        self,
        *,
        attempt_proof_hash: str,
        operation_id: str,
        _candidate_capability: _RepairEvaluationCapability | None = None,
    ) -> TransitionResult:
        """Preserve one failed changed-basis attempt without abandoning Repair."""

        _require_digest("Repair attempt proof", attempt_proof_hash)

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            repair = science.get("active_repair")
            job = science.get("active_job")
            if not isinstance(repair, dict) or not isinstance(job, dict):
                raise TransitionError("failed attempt requires an active Repair")
            if (
                job.get("status") != "interrupted_repair"
                or repair.get("job_id") != job.get("id")
            ):
                raise TransitionError("Repair and interrupted Job diverge")
            (
                opened,
                _prior,
                prior_record_id,
                previous_basis,
                sequence,
                used_basis_hashes,
            ) = self._repair_attempt_context(index, repair=repair, job=job)
            if _candidate_capability is None:
                raise TransitionError(
                    "Repair requires outcome-free candidate evaluation"
                )
            candidate = self._parse_active_repair_candidate(
                index=index,
                candidate_hash=attempt_proof_hash,
                repair=repair,
                job=job,
                opened=opened,
                prior_record_id=prior_record_id,
                previous_basis=previous_basis,
                used_basis_hashes=used_basis_hashes,
            )
            declaration = index.get("job-declared", str(job["id"]))
            mission_id = (
                None
                if declaration is None
                else declaration.payload.get("mission_id")
            )
            if type(mission_id) is not str:
                raise TransitionError(
                    "Repair candidate lost its Job Mission authority"
                )
            repair_validation = self._require_repair_evaluation_capability(
                capability=_candidate_capability,
                current=current,
                candidate=candidate,
                mission_id=mission_id,
                expected_mode="failure_reproduced",
            )
            proof = self._repair_candidate_attempt_proof(
                candidate,
                _candidate_capability.evaluation,
            )
            attempt_fingerprint = repair_attempt_intervention_fingerprint(
                proof,
                verification_capabilities=repair_validation_capabilities(
                    repair_validation
                ),
            )
            fingerprint_record_id = canonical_digest(
                domain="repair-attempt-fingerprint",
                payload={
                    "attempt_fingerprint": attempt_fingerprint,
                    "repair_id": repair["id"],
                },
            )
            if index.get(
                "repair-attempt-fingerprint", fingerprint_record_id
            ) is not None:
                raise IdenticalFailedRetryError(
                    "identical Repair intervention requires new evidence or protocol"
                )
            candidate_authority = {
                "repair_candidate": candidate.payload(),
                "repair_candidate_hash": candidate.sha256,
                "repair_evaluation": _candidate_capability.evaluation.payload(),
            }
            record_id = canonical_digest(
                domain="repair-attempt",
                payload={
                    "attempt_proof_hash": attempt_proof_hash,
                    "attempt_fingerprint": attempt_fingerprint,
                    **proof.payload(),
                    "repair_authority_schema": (
                        REGISTERED_REPAIR_AUTHORITY_SCHEMA
                    ),
                    "repair_validation": repair_validation,
                    **candidate_authority,
                },
            )
            record = _record(
                kind="repair-attempt",
                record_id=record_id,
                subject=f"Repair:{repair['id']}",
                status="failed",
                fingerprint=attempt_proof_hash,
                payload={
                    "attempt_proof_hash": attempt_proof_hash,
                    "attempt_fingerprint": attempt_fingerprint,
                    **proof.payload(),
                    "repair_authority_schema": (
                        REGISTERED_REPAIR_AUTHORITY_SCHEMA
                    ),
                    "repair_validation": repair_validation,
                    **candidate_authority,
                    "scientific_failure_delta": 0,
                    "scientific_trial_delta": 0,
                },
                event_stream=f"repair-attempt:{repair['id']}",
                event_sequence=sequence,
            )
            fingerprint_record = _record(
                kind="repair-attempt-fingerprint",
                record_id=fingerprint_record_id,
                subject=f"Repair:{repair['id']}",
                status="failed",
                fingerprint=attempt_fingerprint,
                payload={
                    "attempt_fingerprint": attempt_fingerprint,
                    "attempt_record_id": record_id,
                    "repair_id": repair["id"],
                },
            )
            repair["latest_attempt_record_id"] = record_id
            repair["latest_basis_hash"] = proof.new_basis_hash
            body["next_action"] = {
                "kind": "execute_repair",
                "repair_id": repair["id"],
                "prior_attempt_record_id": record_id,
                "required_previous_basis_hash": proof.new_basis_hash,
            }
            return body, [fingerprint_record, record], {
                "attempt_record_id": record_id,
                "job_id": job["id"],
                "repair_id": repair["id"],
            }

        return self._commit(
            event_kind="repair_attempt_failed",
            operation_id=operation_id,
            subject="Repair:active",
            payload={"attempt_proof_hash": attempt_proof_hash},
            prepare=prepare,
        )

    def materialize_engineering_repair_disposition(
        self,
        *,
        inventory_validator_id: str,
        inventory_protocol: str,
        inventory_result_artifacts: Mapping[str, str],
        rationale: str,
        resume_condition: str,
        semantic_change_successor_artifact_hash: str | None = None,
    ) -> str:
        """Run terminal domain validation once, outside the Writer lock.

        The materializer freezes the current information set under the stable
        read boundary, releases it, dispatches registered validators, and
        installs an unforgeable capability for the later Journal commit.
        """

        from axiom_rift.operations.repair_disposition_materializer import (
            _materialize_engineering_repair_disposition,
        )

        return _materialize_engineering_repair_disposition(
            self,
            _writer_token=_REPAIR_DISPOSITION_MATERIALIZATION_TOKEN,
            inventory_validator_id=inventory_validator_id,
            inventory_protocol=inventory_protocol,
            inventory_result_artifacts=inventory_result_artifacts,
            rationale=rationale,
            resume_condition=resume_condition,
            semantic_change_successor_artifact_hash=(
                semantic_change_successor_artifact_hash
            ),
        )

    def _install_engineering_repair_disposition_capability(
        self,
        *,
        _writer_token: object,
        expected_control_hash: str,
        disposition_hash: str,
        disposition: EngineeringFailureDisposition,
        disposition_validation: Mapping[str, Any],
    ) -> str:
        """Seal one Writer-owned handoff after registered validation."""

        if _writer_token is not _REPAIR_DISPOSITION_MATERIALIZATION_TOKEN:
            raise TransitionError(
                "engineering disposition capability issuer is unauthorized"
            )
        _require_digest("engineering disposition control", expected_control_hash)
        _require_digest("engineering disposition", disposition_hash)
        if not isinstance(disposition, EngineeringFailureDisposition):
            raise TransitionError(
                "engineering disposition capability payload is untyped"
            )
        self.evidence.verify(disposition_hash)
        validation = _copy(disposition_validation)
        trace_body = {
            key: value
            for key, value in validation.items()
            if key != "trace_sha256"
        }
        if (
            validation.get("schema") != DISPOSITION_TRACE_SCHEMA
            or validation.get("trace_sha256")
            != sha256(canonical_bytes(trace_body)).hexdigest()
        ):
            raise TransitionError(
                "engineering disposition validation trace is invalid"
            )
        validation_hash = sha256(canonical_bytes(validation)).hexdigest()
        capability = _RepairDispositionCapability(
            token=_REPAIR_DISPOSITION_CAPABILITY_TOKEN,
            control_hash=expected_control_hash,
            disposition_hash=disposition_hash,
            disposition=disposition,
            disposition_validation=validation,
            disposition_validation_hash=validation_hash,
        )
        self._repair_disposition_capabilities[disposition_hash] = capability
        return disposition_hash

    def _require_engineering_repair_disposition_capability(
        self,
        *,
        current: Mapping[str, Any],
        disposition_hash: str,
        job_id: str,
        job_hash: str,
        repair_id: str,
        cause_hash: str,
    ) -> tuple[EngineeringFailureDisposition, dict[str, Any]]:
        capability = self._repair_disposition_capabilities.get(
            disposition_hash
        )
        if (
            capability is None
            or capability.token is not _REPAIR_DISPOSITION_CAPABILITY_TOKEN
            or capability.control_hash != current.get("control_hash")
            or capability.disposition_hash != disposition_hash
            or capability.disposition.job_id != job_id
            or capability.disposition.repair_id != repair_id
            or capability.disposition.cause_hash != cause_hash
            or sha256(
                canonical_bytes(dict(capability.disposition_validation))
            ).hexdigest()
            != capability.disposition_validation_hash
        ):
            raise TransitionError(
                "engineering disposition requires one prepared validation "
                "capability for the exact stable head"
            )
        if job_hash != current["scientific"]["active_job"].get("hash"):
            raise TransitionError(
                "engineering disposition capability names another Job head"
            )
        return capability.disposition, _copy(
            capability.disposition_validation
        )

    def _recorded_engineering_failure_disposition(
        self,
        index: LocalIndex,
        *,
        job_id: str,
        job_hash: str,
        repair_id: str | None,
        cause_hash: str,
        disposition_hash: str,
        disposition_record_id: str,
    ) -> tuple[dict[str, Any], str]:
        expected_kind = (
            "engineering-failure-disposition"
            if repair_id is None
            else "repair-close"
        )
        record = index.get(expected_kind, disposition_record_id)
        disposition = None if record is None else record.payload.get("disposition")
        validation = (
            None if record is None else record.payload.get("disposition_validation")
        )
        cause = None if record is None else record.payload.get("cause")
        if not isinstance(validation, Mapping):
            raise RecoveryRequired(
                "engineering failure disposition validation record is invalid"
            )
        identity_payload = (
            {
                "cause_hash": cause_hash,
                "disposition_hash": disposition_hash,
                "disposition_validation": validation,
                "job_id": job_id,
                "repair_authority_schema": REGISTERED_REPAIR_AUTHORITY_SCHEMA,
                "repair_id": None,
            }
            if repair_id is None
            else {
                "disposition_hash": disposition_hash,
                "disposition_validation": validation,
                "repair_authority_schema": REGISTERED_REPAIR_AUTHORITY_SCHEMA,
                "repair_id": repair_id,
            }
        )
        expected_record_id = canonical_digest(
            domain=(
                "engineering-failure-disposition"
                if repair_id is None
                else "repair-unrecovered"
            ),
            payload=identity_payload,
        )
        expected_keys = {
            "cause",
            "cause_hash",
            "disposition",
            "disposition_hash",
            "disposition_validation",
            "job_id",
            "repair_authority_schema",
            "repair_id",
            "scientific_failure_delta",
            "scientific_trial_delta",
        }
        if repair_id is not None:
            expected_keys.add("resume_action")
        if (
            record is None
            or disposition_record_id != expected_record_id
            or record.record_id != disposition_record_id
            or record.kind != expected_kind
            or record.subject != f"Job:{job_id}"
            or record.fingerprint != disposition_hash
            or set(record.payload) != expected_keys
            or record.payload.get("job_id") != job_id
            or record.payload.get("repair_id") != repair_id
            or record.payload.get("disposition_hash") != disposition_hash
            or record.payload.get("cause_hash") != cause_hash
            or record.payload.get("repair_authority_schema")
            != REGISTERED_REPAIR_AUTHORITY_SCHEMA
            or type(record.payload.get("scientific_failure_delta")) is not int
            or record.payload.get("scientific_failure_delta") != 0
            or type(record.payload.get("scientific_trial_delta")) is not int
            or record.payload.get("scientific_trial_delta") != 0
            or not isinstance(cause, Mapping)
            or set(cause)
            != {
                "failure_kind",
                "interrupted_action",
                "minimum_reproduction_evidence",
                "root_cause",
            }
            or _digest(cause, domain="repair-cause") != cause_hash
            or not isinstance(disposition, Mapping)
            or disposition.get("schema")
            != "engineering_failure_disposition.v1"
            or disposition.get("job_id") != job_id
            or disposition.get("repair_id") != repair_id
            or disposition.get("cause_hash") != cause_hash
            or record.status != disposition.get("disposition")
            and not (expected_kind == "repair-close" and record.status == "unrecovered")
        ):
            raise RecoveryRequired(
                "engineering failure disposition validation record is invalid"
            )
        declaration = index.get("job-declared", job_id)
        mission_id = (
            None if declaration is None else declaration.payload.get("mission_id")
        )
        if (
            declaration is None
            or declaration.subject != f"Job:{job_id}"
            or declaration.fingerprint != job_hash
            or type(mission_id) is not str
        ):
            raise RecoveryRequired(
                "engineering disposition lost its Job declaration"
            )
        attempts: list[dict[str, Any]] = []
        attempt_records: list[IndexRecord] = []
        if repair_id is not None:
            stream = f"repair-attempt:{repair_id}"
            head = index.event_head(stream)
            if head is not None:
                for sequence in range(1, head.sequence + 1):
                    attempt_record = index.event_record(stream, sequence)
                    if (
                        attempt_record is None
                        or attempt_record.status != "failed"
                        or attempt_record.event_sequence != sequence
                    ):
                        raise RecoveryRequired(
                            "stored failed Repair attempt stream is invalid"
                        )
                    try:
                        candidate = self._stored_repair_candidate_from_attempt(
                            attempt_record
                        )
                        if candidate is None:
                            if not self.engineering_fixture:
                                raise RepairValidationError(
                                    "production Repair attempt lacks its "
                                    "outcome-free candidate authority"
                                )
                            require_stored_repair_attempt_validation(
                                attempt_payload=attempt_record.payload,
                                repair_validation=attempt_record.payload.get(
                                    "repair_validation"
                                ),
                                mission_id=mission_id,
                                expected_scope=(
                                    "fixture_only"
                                    if self.engineering_fixture
                                    else "production"
                                ),
                            )
                        else:
                            require_stored_repair_candidate_validation(
                                candidate=candidate,
                                repair_validation=attempt_record.payload.get(
                                    "repair_validation"
                                ),
                                mission_id=mission_id,
                                evidence=self.evidence,
                                expected_scope=(
                                    "fixture_only"
                                    if self.engineering_fixture
                                    else "production"
                                ),
                            )
                    except (RepairValidationError, TypeError, ValueError) as exc:
                        raise RecoveryRequired(
                            "stored failed Repair attempt trace is invalid"
                        ) from exc
                    attempts.append(
                        {
                            "attempt_proof_hash": attempt_record.payload.get(
                                "attempt_proof_hash"
                            ),
                            "changed_dimension": attempt_record.payload.get(
                                "changed_dimension"
                            ),
                            "new_basis_hash": attempt_record.payload.get(
                                "new_basis_hash"
                            ),
                            "repair_attempt_record_id": attempt_record.record_id,
                            "repair_axis_id": (
                                None
                                if candidate is None
                                else candidate.repair_axis_id
                            ),
                            "repair_validation": dict(
                                attempt_record.payload["repair_validation"]
                            ),
                            "verification_receipt_hashes": list(
                                attempt_record.payload.get(
                                    "verification_evidence_hashes", []
                                )
                            ),
                        }
                    )
                    attempt_records.append(attempt_record)
        if disposition.get("repair_attempt_record_ids") != [
            item["repair_attempt_record_id"] for item in attempts
        ]:
            raise RecoveryRequired(
                "stored disposition differs from its Repair attempt stream"
            )
        validation_observations: tuple[dict[str, Any], ...] = ()
        validation_observation_head: dict[str, Any] | None = None
        if repair_id is not None:
            opened = index.get("repair-open", repair_id)
            if (
                opened is None
                or opened.fingerprint != cause_hash
                or not isinstance(opened.payload.get("resume_action"), str)
            ):
                raise RecoveryRequired(
                    "stored Repair observations lost their open authority"
                )
            try:
                (
                    validation_observations,
                    validation_observation_head,
                ) = require_repair_validation_observation_stream(
                    index,
                    repair_id=repair_id,
                    job_id=job_id,
                    job_hash=job_hash,
                    cause_hash=cause_hash,
                    reproduction_evidence_hashes=cause[
                        "minimum_reproduction_evidence"
                    ],
                    resume_action=str(opened.payload["resume_action"]),
                    mission_id=mission_id,
                    expected_scope=(
                        "fixture_only"
                        if self.engineering_fixture
                        else "production"
                    ),
                    accepted_attempts=attempt_records,
                    evidence=self.evidence,
                )
            except (
                RepairObservationAuthorityError,
                TypeError,
                ValueError,
            ) as exc:
                raise RecoveryRequired(str(exc)) from exc
        if not self.engineering_fixture:
            if repair_id is None:
                raise RecoveryRequired(
                    "prospective stored disposition lacks Repair authority"
                )
            observation_stream = (
                f"repair-validation-observation:{repair_id}"
            )
            for ordinal, attempt_record in enumerate(attempt_records):
                bound_observations: list[dict[str, Any]] = []
                prior_observation_head: dict[str, Any] | None = None
                for observation in validation_observations:
                    observation_record = index.event_record(
                        observation_stream,
                        int(observation["observation_sequence"]),
                    )
                    if (
                        observation_record is None
                        or type(observation_record.authority_sequence) is not int
                        or type(attempt_record.authority_sequence) is not int
                    ):
                        raise RecoveryRequired(
                            "stored Repair disposition chronology is malformed"
                        )
                    if (
                        observation_record.authority_sequence
                        >= attempt_record.authority_sequence
                    ):
                        break
                    bound_observations.append(
                        {
                            "new_information_evidence_hashes": list(
                                observation[
                                    "new_information_evidence_hashes"
                                ]
                            ),
                            "observation_record_id": (
                                observation_record.record_id
                            ),
                        }
                    )
                    prior_observation_head = {
                        "fingerprint": observation_record.fingerprint,
                        "record_id": observation_record.record_id,
                        "sequence": observation_record.event_sequence,
                    }
                try:
                    candidate, stored_validation = (
                        require_stored_accepted_repair_candidate_attempt(
                            attempt_payload=attempt_record.payload,
                            mission_id=mission_id,
                            expected_scope="production",
                            evidence=self.evidence,
                            expected_prior_validation_observation_head=(
                                prior_observation_head
                            ),
                            expected_bound_validation_observations=(
                                bound_observations
                            ),
                        )
                    )
                except (RepairValidationError, TypeError, ValueError) as exc:
                    raise RecoveryRequired(
                        "stored Repair disposition attempt lost its exact "
                        "observation binding"
                    ) from exc
                attempts[ordinal]["repair_axis_id"] = candidate.repair_axis_id
                attempts[ordinal]["repair_validation"] = stored_validation
        try:
            require_stored_engineering_disposition_validation(
                disposition_payload=disposition,
                disposition_validation=validation,
                mission_id=mission_id,
                job_hash=job_hash,
                reproduction_evidence_hashes=cause[
                    "minimum_reproduction_evidence"
                ],
                repair_attempts=attempts,
                repair_validation_observations=validation_observations,
                repair_validation_observation_head=(
                    validation_observation_head
                ),
                evidence=self.evidence,
                expected_scope=(
                    "fixture_only" if self.engineering_fixture else "production"
                ),
            )
        except (RepairValidationError, TypeError, ValueError) as exc:
            raise RecoveryRequired(
                "stored engineering disposition trace is invalid"
            ) from exc
        trace_sha256 = validation.get("trace_sha256")
        if not isinstance(trace_sha256, str):
            raise RecoveryRequired("stored disposition trace digest is absent")
        return dict(disposition), trace_sha256

    def record_engineering_failure_disposition(
        self,
        *,
        failure: Mapping[str, Any],
        disposition_hash: str,
        operation_id: str,
    ) -> TransitionResult:
        """Reject prospective terminal judgement before a Repair is opened."""

        raise TransitionError(
            "engineering failure must open Repair before any terminal "
            "disposition can be evaluated"
        )

    def conclude_repair_unrecovered(
        self,
        *,
        disposition_hash: str,
        operation_id: str,
    ) -> TransitionResult:
        """End Repair only on a typed infeasibility, value, exhaustion, or scope basis."""

        _require_digest("engineering disposition", disposition_hash)

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            repair = science.get("active_repair")
            job = science.get("active_job")
            if not isinstance(repair, dict) or not isinstance(job, dict):
                raise TransitionError("unrecovered conclusion requires active Repair")
            if (
                job.get("status") != "interrupted_repair"
                or repair.get("job_id") != job.get("id")
            ):
                raise TransitionError("Repair and interrupted Job diverge")
            opened, _prior, _prior_id, _basis, _sequence, _used_bases = (
                self._repair_attempt_context(index, repair=repair, job=job)
            )
            disposition, disposition_validation = (
                self._require_engineering_repair_disposition_capability(
                    current=current,
                    disposition_hash=disposition_hash,
                    job_id=job["id"],
                    job_hash=job["hash"],
                    repair_id=repair["id"],
                    cause_hash=repair["cause_hash"],
                )
            )
            stream = f"job-repair:{job['id']}"
            head = index.event_head(stream)
            record_id = canonical_digest(
                domain="repair-unrecovered",
                payload={
                    "disposition_hash": disposition_hash,
                    "repair_id": repair["id"],
                    "repair_authority_schema": (
                        REGISTERED_REPAIR_AUTHORITY_SCHEMA
                    ),
                    "disposition_validation": disposition_validation,
                },
            )
            record = _record(
                kind="repair-close",
                record_id=record_id,
                subject=f"Job:{job['id']}",
                status="unrecovered",
                fingerprint=disposition_hash,
                payload={
                    "cause": {
                        "failure_kind": opened.payload["failure_kind"],
                        "interrupted_action": opened.payload[
                            "interrupted_action"
                        ],
                        "minimum_reproduction_evidence": list(
                            opened.payload["minimum_reproduction_evidence"]
                        ),
                        "root_cause": opened.payload["root_cause"],
                    },
                    "cause_hash": repair["cause_hash"],
                    "disposition": disposition.payload(),
                    "disposition_hash": disposition_hash,
                    "disposition_validation": disposition_validation,
                    "job_id": job["id"],
                    "repair_id": repair["id"],
                    "repair_authority_schema": (
                        REGISTERED_REPAIR_AUTHORITY_SCHEMA
                    ),
                    "resume_action": repair["resume_action"],
                    "scientific_failure_delta": 0,
                    "scientific_trial_delta": 0,
                },
                event_stream=stream,
                event_sequence=(1 if head is None else head.sequence + 1),
            )
            science["active_repair"] = None
            job["status"] = "running"
            job["required_engineering_disposition_hash"] = disposition_hash
            job["required_engineering_disposition_record_id"] = record_id
            job["required_engineering_failure_cause_hash"] = repair[
                "cause_hash"
            ]
            job["required_engineering_repair_id"] = repair["id"]
            body["next_action"] = {
                "disposition_hash": disposition_hash,
                "disposition_record_id": record_id,
                "job_id": job["id"],
                "kind": "complete_engineering_failure",
            }
            return body, [record], {
                "disposition_hash": disposition_hash,
                "job_id": job["id"],
                "repair_id": repair["id"],
                "repair_close_record_id": record_id,
            }

        return self._commit(
            event_kind="repair_concluded_unrecovered",
            operation_id=operation_id,
            subject="Repair:active",
            payload={"disposition_hash": disposition_hash},
            prepare=prepare,
        )

    @staticmethod
    def _semantic_equivalence_repair_error(
        detail: object,
    ) -> RepairSemanticEquivalenceUnavailable:
        reason_code = getattr(detail, "reason_code", None)
        if reason_code not in VALIDATION_UNAVAILABLE_REASON_CODES:
            reason_code = (
                "declared_artifact_absent_drifted_or_unopened"
                if isinstance(detail, (FileNotFoundError, OSError))
                else "plan_or_context_binding_mismatch"
            )
        return RepairSemanticEquivalenceUnavailable(
            "in-place implementation Repair lacks fully passed registered "
            "semantic-equivalence; keep Repair active and record only a "
            "zero-credit validation observation. This rejection cannot "
            "authorize requires_scientific_change without a separate positive "
            "registered semantic-change proof: "
            f"{detail}",
            reason_code=reason_code,
        )

    def _implementation_repair_semantic_plan_locked(
        self,
        index: LocalIndex,
        *,
        repair: Mapping[str, Any],
        job: Mapping[str, Any],
        declaration: IndexRecord,
        spec: Mapping[str, Any],
        new_implementation_identity: str,
        validator_id: str,
    ) -> tuple[dict[str, Any], str]:
        """Rebuild the exact production Executable Repair plan from authority."""

        if validator_id == SEMANTIC_EQUIVALENCE_VALIDATOR_ID:
            validation_protocol = SEMANTIC_EQUIVALENCE_PROTOCOL
        else:
            fixed_validator_id = (
                _fixed_hold_authority_correction_validator_id()
            )
            if validator_id == fixed_validator_id:
                validation_protocol = FIXED_HOLD_AUTHORITY_CORRECTION_PROTOCOL
            else:
                raise self._semantic_equivalence_repair_error(
                    "validator does not implement the registered equivalence protocol"
                )
        try:
            self.validation_registry.require_plannable_protocol(
                validator_id=validator_id,
                domain="scientific",
                protocol=validation_protocol,
            )
        except EvidenceValidationError as exc:
            raise self._semantic_equivalence_repair_error(exc) from exc
        subject = spec.get("evidence_subject")
        if (
            not isinstance(subject, Mapping)
            or subject.get("kind") != "Executable"
            or type(subject.get("id")) is not str
        ):
            raise self._semantic_equivalence_repair_error(
                "Repair is not bound to one exact Executable"
            )
        executable_id = str(subject["id"])
        trial = index.get("trial", executable_id)
        executable = None if trial is None else trial.payload.get("executable")
        if not isinstance(executable, Mapping):
            raise self._semantic_equivalence_repair_error(
                "Executable trial manifest is unavailable"
            )
        old_identity, _repair_record_id = (
            self._effective_running_job_implementation(
                index,
                job_id=str(job["id"]),
                declared_implementation_identity=str(
                    spec["implementation_identity"]
                ),
            )
        )
        old_manifest = self._require_job_implementation_evidence(
            {**dict(spec), "implementation_identity": old_identity},
            _index=index,
        )
        new_manifest = self._require_job_implementation_evidence(
            {
                **dict(spec),
                "implementation_identity": new_implementation_identity,
            },
            _index=index,
        )
        try:
            from axiom_rift.research.implementation_closure import (
                ImplementationClosureError,
                require_job_implementation_closure,
            )

            for manifest in (old_manifest, new_manifest):
                require_job_implementation_closure(
                    executable_manifest=executable,
                    job_artifact_hashes=manifest["artifact_hashes"],
                    artifact_reader=self.evidence.read_verified,
                )
            plan = build_semantic_equivalence_plan(
                validator_id=validator_id,
                validation_protocol=validation_protocol,
                repair_id=str(repair["id"]),
                job_id=str(job["id"]),
                job_hash=str(job["hash"]),
                executable_id=executable_id,
                job_spec=spec,
                executable_manifest=executable,
                old_implementation_identity=old_identity,
                old_implementation_manifest=old_manifest,
                new_implementation_identity=new_implementation_identity,
                new_implementation_manifest=new_manifest,
                artifact_reader=self.evidence.read_verified,
            )
        except (
            ImplementationClosureError,
            RepairSemanticEquivalenceError,
        ) as exc:
            raise self._semantic_equivalence_repair_error(exc) from exc
        return plan, old_identity

    def plan_implementation_repair_semantic_equivalence(
        self,
        *,
        new_implementation_identity: str,
        validator_id: str = SEMANTIC_EQUIVALENCE_VALIDATOR_ID,
    ) -> dict[str, Any]:
        """Return the exact read-only plan required for a production close."""

        _require_digest(
            "new implementation identity", new_implementation_identity
        )
        if self.engineering_fixture:
            raise TransitionError(
                "engineering fixtures do not acquire production semantic authority"
            )
        with WriterLock(self.lock_path):
            with self._open_authoritative_index() as index:
                current = self._require_stable_locked(index)
                assert current is not None
                science = current["scientific"]
                repair = science.get("active_repair")
                job = science.get("active_job")
                if not isinstance(repair, Mapping) or not isinstance(job, Mapping):
                    raise TransitionError(
                        "semantic-equivalence plan requires an active Repair"
                    )
                if (
                    job.get("status") != "interrupted_repair"
                    or repair.get("job_id") != job.get("id")
                ):
                    raise TransitionError("Repair and interrupted Job diverge")
                declaration = index.get("job-declared", str(job["id"]))
                spec = (
                    None
                    if declaration is None
                    else declaration.payload.get("spec")
                )
                if declaration is None or not isinstance(spec, Mapping):
                    raise TransitionError("Repair Job declaration is unavailable")
                plan, _old_identity = (
                    self._implementation_repair_semantic_plan_locked(
                        index,
                        repair=repair,
                        job=job,
                        declaration=declaration,
                        spec=spec,
                        new_implementation_identity=(
                            new_implementation_identity
                        ),
                        validator_id=validator_id,
                    )
                )
                return plan

    def plan_fixed_hold_authority_correction_repair(
        self,
        *,
        new_implementation_identity: str,
    ) -> dict[str, Any]:
        """Plan the exact protocol-specific fixed-hold in-place Repair."""

        return self.plan_implementation_repair_semantic_equivalence(
            new_implementation_identity=new_implementation_identity,
            validator_id=_fixed_hold_authority_correction_validator_id(),
        )

    def resolve_fixed_hold_authority_correction_verification(
        self,
        *,
        new_implementation_identity: str,
        evidence_hashes: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Materialize or authenticate one recomputable engineering receipt."""

        from axiom_rift.operations.fixed_hold_repair_equivalence import (
            fixed_hold_authority_correction_verification_claim_manifest,
            require_fixed_hold_authority_correction_verification_claim,
        )
        fixed_validator_id = _fixed_hold_authority_correction_validator_id()

        _require_digest(
            "fixed-hold corrected implementation",
            new_implementation_identity,
        )
        self.validation_registry.require_registered_protocol(
            validator_id=fixed_validator_id,
            domain="scientific",
            protocol=FIXED_HOLD_AUTHORITY_CORRECTION_PROTOCOL,
        )
        if type(evidence_hashes) is not tuple:
            raise TransitionError(
                "fixed-hold correction verification hashes must be a tuple"
            )
        if evidence_hashes:
            if (
                len(evidence_hashes) != 1
                or evidence_hashes != tuple(sorted(set(evidence_hashes)))
            ):
                raise TransitionError(
                    "fixed-hold correction requires one exact verification"
                )
            evidence_hash = evidence_hashes[0]
            _require_digest(
                "fixed-hold correction verification",
                evidence_hash,
            )
            content = self.evidence.read_verified(evidence_hash)
        else:
            content = canonical_bytes(
                fixed_hold_authority_correction_verification_claim_manifest(
                    new_implementation_identity=new_implementation_identity,
                )
            )
            evidence_hash = self.evidence.finalize(content).sha256
        try:
            require_fixed_hold_authority_correction_verification_claim(
                content,
                new_implementation_identity=new_implementation_identity,
            )
        except EvidenceValidationError as exc:
            raise TransitionError(str(exc)) from exc
        return (evidence_hash,)

    def materialize_fixed_hold_repair_candidate_validation_plan(
        self,
        *,
        explanation: str,
        new_basis_hash: str,
        new_evidence_hashes: tuple[str, ...],
        implementation_proof_hash: str,
        result_artifact_hashes: tuple[str, ...],
        repair_axis_id: str,
        prior_validation_observation_head: Mapping[str, Any] | None,
        bound_validation_observations: tuple[Mapping[str, Any], ...],
    ) -> tuple[str, str, str, tuple[str, ...]]:
        """Bind a fixed-hold result to one outcome-free Repair candidate."""

        reason = _require_ascii("fixed-hold Repair explanation", explanation)
        _require_digest("fixed-hold Repair basis", new_basis_hash)
        _require_digest(
            "fixed-hold Repair implementation proof",
            implementation_proof_hash,
        )
        if (
            type(new_evidence_hashes) is not tuple
            or not new_evidence_hashes
            or new_evidence_hashes != tuple(sorted(set(new_evidence_hashes)))
            or new_basis_hash not in new_evidence_hashes
            or implementation_proof_hash not in new_evidence_hashes
        ):
            raise TransitionError(
                "fixed-hold Repair changed evidence is not exact"
            )
        if (
            type(result_artifact_hashes) is not tuple
            or len(result_artifact_hashes) != 1
            or result_artifact_hashes
            != tuple(sorted(set(result_artifact_hashes)))
        ):
            raise TransitionError(
                "fixed-hold Repair requires one exact validation result"
            )
        for identity in (*new_evidence_hashes, *result_artifact_hashes):
            _require_digest("fixed-hold Repair evidence", identity)
            self.evidence.read_verified(identity)
        with self.open_stable_index() as (control, index):
            science = control.get("scientific")
            job = (
                None
                if not isinstance(science, Mapping)
                else science.get("active_job")
            )
            repair = (
                None
                if not isinstance(science, Mapping)
                else science.get("active_repair")
            )
            mission_id = (
                None
                if not isinstance(science, Mapping)
                else science.get("active_mission")
            )
            if (
                not isinstance(job, Mapping)
                or not isinstance(repair, Mapping)
                or job.get("status") != "interrupted_repair"
                or repair.get("job_id") != job.get("id")
                or type(mission_id) is not str
            ):
                raise TransitionError(
                    "fixed-hold Repair validation requires one interrupted Job"
                )
            opened = index.get("repair-open", str(repair.get("id")))
        reproduction = (
            None
            if opened is None
            else opened.payload.get("minimum_reproduction_evidence")
        )
        if (
            not isinstance(reproduction, list)
            or not reproduction
            or reproduction != sorted(set(reproduction))
        ):
            raise TransitionError(
                "fixed-hold Repair reproduction evidence is unavailable"
            )
        context = build_repair_candidate_validation_context(
            bound_validation_observations=bound_validation_observations,
            cause_hash=str(repair["cause_hash"]),
            changed_dimension="implementation",
            explanation=reason,
            implementation_proof_hash=implementation_proof_hash,
            job_hash=str(job["hash"]),
            job_id=str(job["id"]),
            new_basis_hash=new_basis_hash,
            new_evidence_hashes=new_evidence_hashes,
            previous_basis_hash=str(repair["latest_basis_hash"]),
            prior_attempt_record_id=repair.get("latest_attempt_record_id"),
            prior_validation_observation_head=(
                prior_validation_observation_head
            ),
            repair_axis_id=repair_axis_id,
            repair_id=str(repair["id"]),
            reproduction_evidence_hashes=reproduction,
            resume_action=str(repair["resume_action"]),
        )
        validator_id, protocol = _fixed_hold_repair_attempt_validator()
        try:
            self.validation_registry.require_plannable_protocol(
                validator_id=validator_id,
                domain="engineering",
                protocol=protocol,
            )
        except EvidenceValidationError as exc:
            raise TransitionError(str(exc)) from exc
        artifact_roles = tuple(
            sorted(
                (
                    ("implementation_proof", implementation_proof_hash),
                    ("new_implementation_manifest", new_basis_hash),
                    ("validation_result", result_artifact_hashes[0]),
                    *(
                        (f"reproduction:{ordinal:04d}", identity)
                        for ordinal, identity in enumerate(reproduction)
                    ),
                )
            )
        )
        if len({identity for _name, identity in artifact_roles}) != len(
            artifact_roles
        ):
            raise TransitionError(
                "fixed-hold Repair validation artifact roles overlap"
            )
        binding = repair_validation_binding(
            verification_kind="candidate",
            mission_id=mission_id,
            protocol=protocol,
            context=context,
            artifact_roles=artifact_roles,
        )
        plan = build_repair_validation_plan(
            validator_id=validator_id,
            binding=binding,
        )
        plan_artifact = self.evidence.finalize(canonical_bytes(plan))
        return (
            plan_artifact.sha256,
            validator_id,
            protocol,
            tuple(sorted(identity for _name, identity in artifact_roles)),
        )

    def _run_implementation_repair_semantic_equivalence(
        self,
        *,
        plan: Mapping[str, Any],
        validation_plan_hash: str,
        result_manifest_hash: str,
        measurement_artifact_hashes: Sequence[str],
        mission_id: str,
        job_id: str,
        job_hash: str,
        executable_id: str,
    ) -> dict[str, Any]:
        """Dispatch exact Repair evidence through the immutable registry."""

        try:
            plan_artifact = parse_canonical(
                self.evidence.read_verified(validation_plan_hash)
            )
            if not isinstance(plan_artifact, Mapping) or dict(plan_artifact) != dict(
                plan
            ):
                raise RepairSemanticEquivalenceError(
                    "validation plan differs from Writer-derived authority"
                )
            result_manifest = parse_canonical(
                self.evidence.read_verified(result_manifest_hash)
            )
            if not isinstance(result_manifest, Mapping):
                raise RepairSemanticEquivalenceError(
                    "result manifest is not an object"
                )
            binding = build_semantic_equivalence_binding(
                plan=plan,
                validation_plan_hash=validation_plan_hash,
                result_manifest_hash=result_manifest_hash,
                measurement_artifact_hashes=measurement_artifact_hashes,
            )
            artifacts: list[ValidationArtifact] = []
            for ordinal, identity in enumerate(
                binding["declared_artifact_hashes"]
            ):
                artifacts.append(
                    ValidationArtifact(
                        output_name=f"repair-semantic-artifact-{ordinal:04d}",
                        sha256=identity,
                        _source=self.evidence.verified_path(identity),
                    )
                )
            request = EvidenceValidationRequest(
                domain="scientific",
                validator_id=str(binding["validator_id"]),
                validation_plan_hash=validation_plan_hash,
                job_id=job_id,
                job_hash=job_hash,
                mission_id=mission_id,
                evidence_subject={"kind": "Executable", "id": executable_id},
                binding=binding,
                result_manifest=result_manifest,
                artifacts=tuple(artifacts),
                engineering_fixture=False,
            )
            validated, trace = self.validation_registry.validate(request)
            facts = parse_canonical(canonical_bytes(dict(validated.facts)))
        except (
            EvidenceValidationError,
            FileNotFoundError,
            OSError,
            RepairSemanticEquivalenceError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            raise self._semantic_equivalence_repair_error(exc) from exc
        expected_claims = tuple(plan["claims"])
        expected_measurements = tuple(sorted(measurement_artifact_hashes))
        try:
            fixed_validator_id = (
                _fixed_hold_authority_correction_validator_id()
            )

            if (
                plan.get("validator_id") == SEMANTIC_EQUIVALENCE_VALIDATOR_ID
                and plan.get("protocol") == SEMANTIC_EQUIVALENCE_PROTOCOL
            ):
                require_passed_semantic_equivalence_facts(
                    binding=binding,
                    facts=facts,
                )
            elif (
                plan.get("validator_id")
                == fixed_validator_id
                and plan.get("protocol")
                == FIXED_HOLD_AUTHORITY_CORRECTION_PROTOCOL
            ):
                require_passed_fixed_hold_authority_correction_facts(
                    binding=binding,
                    facts=facts,
                )
            else:
                raise RepairSemanticEquivalenceError(
                    "implementation Repair validation protocol is unsupported"
                )
        except RepairSemanticEquivalenceError as exc:
            raise self._semantic_equivalence_repair_error(exc) from exc
        if (
            validated.verdict != "passed"
            or validated.claims != expected_claims
            or validated.measurement_artifact_hashes
            != expected_measurements
            or validated.scientific_eligible
            or validated.candidate_eligible
            or validated.release_eligible
            or trace.validator_id != plan["validator_id"]
            or trace.declared_artifact_count
            != len(binding["declared_artifact_hashes"])
            or trace.opened_artifact_count
            != trace.declared_artifact_count
        ):
            raise self._semantic_equivalence_repair_error(
                "validator verdict, coverage, claims, facts, or trace is partial"
            )
        return {
            "binding": binding,
            "claims": list(validated.claims),
            "facts": facts,
            "measurement_artifact_hashes": list(
                validated.measurement_artifact_hashes
            ),
            "registry_trace": {
                "declared_artifact_count": trace.declared_artifact_count,
                "opened_artifact_count": trace.opened_artifact_count,
                "validator_id": trace.validator_id,
            },
            "schema": (
                "implementation_repair_semantic_equivalence_validation.v1"
            ),
            "verdict": validated.verdict,
        }

    def _prepare_candidate_semantic_equivalence_dispatch(
        self,
        *,
        candidate: RepairCandidate,
        expected_control_hash: str,
    ) -> dict[str, Any] | None:
        """Freeze the semantic-equivalence dispatch without running it."""

        if (
            self.engineering_fixture
            or candidate.changed_dimension != "implementation"
        ):
            return None
        if candidate.implementation_proof_hash is None:
            raise self._semantic_equivalence_repair_error(
                "implementation candidate omits its semantic proof"
            )
        try:
            inner = parse_canonical(
                self.evidence.read_verified(
                    candidate.implementation_proof_hash
                )
            )
        except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
            raise self._semantic_equivalence_repair_error(exc) from exc
        if not isinstance(inner, Mapping):
            raise self._semantic_equivalence_repair_error(
                "implementation semantic proof is not an object"
            )
        validator_id = inner.get("semantic_equivalence_validator_id")
        validation_plan_hash = inner.get(
            "semantic_equivalence_validation_plan_hash"
        )
        result_manifest_hash = inner.get(
            "semantic_equivalence_result_manifest_hash"
        )
        previous_implementation_identity = inner.get(
            "previous_implementation_identity"
        )
        new_implementation_identity = inner.get(
            "new_implementation_identity"
        )
        measurements = inner.get(
            "semantic_equivalence_measurement_artifact_hashes"
        )
        if (
            type(validator_id) is not str
            or type(validation_plan_hash) is not str
            or type(result_manifest_hash) is not str
            or type(previous_implementation_identity) is not str
            or type(new_implementation_identity) is not str
            or not isinstance(measurements, list)
            or not measurements
            or measurements != sorted(set(measurements))
        ):
            raise self._semantic_equivalence_repair_error(
                "implementation semantic dispatch is incomplete"
            )
        _require_digest("semantic validation plan", validation_plan_hash)
        _require_digest("semantic result manifest", result_manifest_hash)
        _require_digest(
            "previous implementation identity",
            previous_implementation_identity,
        )
        _require_digest(
            "new implementation identity",
            new_implementation_identity,
        )
        if new_implementation_identity != candidate.new_basis_hash:
            raise self._semantic_equivalence_repair_error(
                "candidate basis differs from its implementation proof"
            )
        for identity in measurements:
            _require_digest("semantic measurement", identity)
        with self.open_stable_index() as (control, index):
            if control.get("control_hash") != expected_control_hash:
                raise TransitionError(
                    "Repair head changed before semantic validation"
                )
            science = control.get("scientific")
            repair = (
                None
                if not isinstance(science, Mapping)
                else science.get("active_repair")
            )
            job = (
                None
                if not isinstance(science, Mapping)
                else science.get("active_job")
            )
            if (
                not isinstance(repair, Mapping)
                or not isinstance(job, Mapping)
                or repair.get("id") != candidate.repair_id
                or job.get("id") != candidate.job_id
                or job.get("hash") != candidate.job_hash
            ):
                raise TransitionError(
                    "Repair head changed before semantic validation"
                )
            declaration = index.get("job-declared", candidate.job_id)
            spec = (
                None
                if declaration is None
                else declaration.payload.get("spec")
            )
            subject = (
                None
                if not isinstance(spec, Mapping)
                else spec.get("evidence_subject")
            )
            if not isinstance(subject, Mapping) or subject.get(
                "kind"
            ) != "Executable":
                return None
            if (
                declaration is None
                or type(declaration.payload.get("mission_id")) is not str
                or type(subject.get("id")) is not str
            ):
                raise self._semantic_equivalence_repair_error(
                    "semantic validation lost its Job authority"
                )
            plan, planned_old_identity = (
                self._implementation_repair_semantic_plan_locked(
                    index,
                    repair=repair,
                    job=job,
                    declaration=declaration,
                    spec=spec,
                    new_implementation_identity=candidate.new_basis_hash,
                    validator_id=validator_id,
                )
            )
            if planned_old_identity != previous_implementation_identity:
                raise self._semantic_equivalence_repair_error(
                    "old implementation identity changed before validation"
                )
            mission_id = str(declaration.payload["mission_id"])
            executable_id = str(subject["id"])
        return {
            "executable_id": executable_id,
            "job_hash": candidate.job_hash,
            "job_id": candidate.job_id,
            "measurement_artifact_hashes": tuple(measurements),
            "mission_id": mission_id,
            "plan": plan,
            "result_manifest_hash": result_manifest_hash,
            "validation_plan_hash": validation_plan_hash,
        }

    def close_repair(
        self,
        *,
        changed_cause_proof_hash: str,
        operation_id: str,
        _candidate_capability: _RepairEvaluationCapability | None = None,
    ) -> TransitionResult:
        _require_digest("changed_cause_proof_hash", changed_cause_proof_hash)

        def prepare(current: dict[str, Any] | None, _index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            repair = science["active_repair"]
            job = science["active_job"]
            if not isinstance(repair, dict) or not isinstance(job, dict):
                raise TransitionError("no active Repair")
            if job["id"] != repair["job_id"] or job["status"] != "interrupted_repair":
                raise TransitionError("Repair and interrupted Job diverge")
            (
                opened,
                _prior,
                prior_attempt_record_id,
                previous_basis,
                attempt_sequence,
                used_basis_hashes,
            ) = self._repair_attempt_context(
                _index,
                repair=repair,
                job=job,
            )
            if _candidate_capability is None:
                raise TransitionError(
                    "Repair requires outcome-free candidate evaluation"
                )
            candidate = self._parse_active_repair_candidate(
                index=_index,
                candidate_hash=changed_cause_proof_hash,
                repair=repair,
                job=job,
                opened=opened,
                prior_record_id=prior_attempt_record_id,
                previous_basis=previous_basis,
                used_basis_hashes=used_basis_hashes,
            )
            proof = self._repair_candidate_attempt_proof(
                candidate,
                _candidate_capability.evaluation,
            )
            declaration = _index.get("job-declared", job["id"])
            spec = None if declaration is None else declaration.payload.get("spec")
            if not isinstance(spec, Mapping):
                raise TransitionError("Repair Job declaration is unavailable")
            prior_effective, _prior_repair_record_id = (
                self._effective_running_job_implementation(
                    _index,
                    job_id=job["id"],
                    declared_implementation_identity=spec[
                        "implementation_identity"
                    ],
                )
            )
            effective_implementation = prior_effective
            implementation_changed = False
            semantic_equivalence_validation: dict[str, Any] | None = None
            if proof.changed_dimension == "implementation":
                if proof.implementation_proof_hash is None:
                    raise TransitionError(
                        "implementation Repair omits its typed inner proof"
                    )
                try:
                    changed_manifest = parse_canonical(
                        self.evidence.read_verified(
                            proof.implementation_proof_hash
                        )
                    )
                except (OSError, TypeError, ValueError) as exc:
                    raise TransitionError(
                        "running Job implementation Repair proof is invalid"
                    ) from exc
                if not isinstance(changed_manifest, Mapping):
                    raise TransitionError(
                        "running Job implementation Repair proof is invalid"
                    )
                legacy_required = {
                    "changed_dimension",
                    "explanation",
                    "job_hash",
                    "job_id",
                    "new_evidence_hashes",
                    "new_implementation_identity",
                    "previous_implementation_identity",
                    "repair_id",
                    "reproduction_evidence_hashes",
                    "schema",
                }
                production_executable_repair = (
                    not self.engineering_fixture
                    and spec.get("evidence_subject", {}).get("kind")
                    == "Executable"
                )
                semantic_required = {
                    "semantic_equivalence_measurement_artifact_hashes",
                    "semantic_equivalence_result_manifest_hash",
                    "semantic_equivalence_validation_plan_hash",
                    "semantic_equivalence_validator_id",
                }
                required = (
                    legacy_required | semantic_required
                    if production_executable_repair
                    else legacy_required
                )
                new_evidence = changed_manifest.get("new_evidence_hashes")
                reproduction = changed_manifest.get(
                    "reproduction_evidence_hashes"
                )
                new_identity = changed_manifest.get(
                    "new_implementation_identity"
                )
                explanation = changed_manifest.get("explanation")
                if production_executable_repair and changed_manifest.get(
                    "schema"
                ) != IMPLEMENTATION_REPAIR_V2_SCHEMA:
                    raise self._semantic_equivalence_repair_error(
                        "production Executable implementation proof is not v2"
                    )
                if (
                    set(changed_manifest) != required
                    or (
                        not production_executable_repair
                        and changed_manifest.get("schema")
                        != "running_job_implementation_repair.v1"
                    )
                    or changed_manifest.get("changed_dimension")
                    != "implementation"
                    or changed_manifest.get("job_id") != job["id"]
                    or changed_manifest.get("job_hash") != job["hash"]
                    or changed_manifest.get("repair_id") != repair["id"]
                    or changed_manifest.get(
                        "previous_implementation_identity"
                    )
                    != prior_effective
                    or not isinstance(new_identity, str)
                    or new_identity == prior_effective
                    or type(explanation) is not str
                    or not explanation
                    or not explanation.isascii()
                    or not isinstance(new_evidence, list)
                    or not new_evidence
                    or new_evidence != sorted(set(new_evidence))
                    or not isinstance(reproduction, list)
                    or reproduction
                    != sorted(opened.payload["minimum_reproduction_evidence"])
                ):
                    raise TransitionError(
                        "running Job implementation Repair proof is invalid"
                    )
                _require_digest("repaired Job implementation", new_identity)
                if new_identity not in new_evidence:
                    raise TransitionError(
                        "running Job Repair omits its implementation manifest"
                    )
                if (
                    proof.new_basis_hash != new_identity
                    or list(proof.new_evidence_hashes)
                    != sorted(
                        {
                            proof.implementation_proof_hash,
                            *new_evidence,
                        }
                    )
                ):
                    raise TransitionError(
                        "implementation Repair attempt differs from its inner proof"
                    )
                for evidence_hash in new_evidence:
                    _require_digest("running Job Repair evidence", evidence_hash)
                    self.evidence.verify(evidence_hash)
                previous_manifest = self._require_job_implementation_evidence(
                    {
                        **dict(spec),
                        "implementation_identity": prior_effective,
                    },
                    _index=_index,
                )
                repaired_spec = {
                    **dict(spec),
                    "implementation_identity": new_identity,
                }
                repaired_manifest = self._require_job_implementation_evidence(
                    repaired_spec,
                    _index=_index,
                )
                if (
                    previous_manifest.get("protocol")
                    != repaired_manifest.get("protocol")
                    or any(
                        value not in new_evidence
                        for value in repaired_manifest["artifact_hashes"]
                    )
                ):
                    raise TransitionError(
                        "running Job Repair changes protocol or omits source bytes"
                    )
                if production_executable_repair:
                    from axiom_rift.research.implementation_closure import (
                        ImplementationClosureError,
                        require_job_implementation_closure,
                    )

                    subject = spec["evidence_subject"]["id"]
                    trial = _index.get("trial", subject)
                    executable = (
                        None
                        if trial is None
                        else trial.payload.get("executable")
                    )
                    if not isinstance(executable, dict):
                        raise TransitionError(
                            "running Job Repair lost its Executable trial"
                        )
                    try:
                        require_job_implementation_closure(
                            executable_manifest=executable,
                            job_artifact_hashes=repaired_manifest[
                                "artifact_hashes"
                            ],
                            artifact_reader=self.evidence.read_verified,
                        )
                    except ImplementationClosureError as exc:
                        raise TransitionError(str(exc)) from exc
                    validator_id = changed_manifest.get(
                        "semantic_equivalence_validator_id"
                    )
                    validation_plan_hash = changed_manifest.get(
                        "semantic_equivalence_validation_plan_hash"
                    )
                    result_manifest_hash = changed_manifest.get(
                        "semantic_equivalence_result_manifest_hash"
                    )
                    measurement_hashes = changed_manifest.get(
                        "semantic_equivalence_measurement_artifact_hashes"
                    )
                    try:
                        if type(validator_id) is not str:
                            raise RepairSemanticEquivalenceError(
                                "semantic-equivalence validator id is absent"
                            )
                        _require_digest(
                            "semantic-equivalence validation plan",
                            validation_plan_hash,
                        )
                        _require_digest(
                            "semantic-equivalence result manifest",
                            result_manifest_hash,
                        )
                        if (
                            not isinstance(measurement_hashes, list)
                            or measurement_hashes
                            != sorted(set(measurement_hashes))
                        ):
                            raise RepairSemanticEquivalenceError(
                                "semantic-equivalence measurement set is invalid"
                            )
                        for measurement_hash in measurement_hashes:
                            _require_digest(
                                "semantic-equivalence measurement",
                                measurement_hash,
                            )
                    except (
                        RepairSemanticEquivalenceError,
                        TransitionError,
                    ) as exc:
                        raise self._semantic_equivalence_repair_error(exc) from exc
                    expected_inner_evidence = sorted(
                        {
                            new_identity,
                            *repaired_manifest["artifact_hashes"],
                            validation_plan_hash,
                            result_manifest_hash,
                            *measurement_hashes,
                        }
                    )
                    if new_evidence != expected_inner_evidence:
                        raise self._semantic_equivalence_repair_error(
                            "implementation proof does not bind the exact plan, "
                            "result, measurement, manifest, and artifact set"
                        )
                    plan, planned_old_identity = (
                        self._implementation_repair_semantic_plan_locked(
                            _index,
                            repair=repair,
                            job=job,
                            declaration=declaration,
                            spec=spec,
                            new_implementation_identity=new_identity,
                            validator_id=validator_id,
                        )
                    )
                    if planned_old_identity != prior_effective:
                        raise self._semantic_equivalence_repair_error(
                            "old implementation identity changed during validation"
                        )
                    mission_id = declaration.payload.get("mission_id")
                    if type(mission_id) is not str:
                        raise self._semantic_equivalence_repair_error(
                            "Mission identity is unavailable"
                        )
                    prepared_semantic = (
                        _candidate_capability.semantic_equivalence_validation
                    )
                    if (
                        _candidate_capability.token
                        is not _REPAIR_EVALUATION_CAPABILITY_TOKEN
                        or _candidate_capability.control_hash
                        != current.get("control_hash")
                        or prepared_semantic is None
                    ):
                        raise self._semantic_equivalence_repair_error(
                            "positive semantic-equivalence capability is absent"
                        )
                    semantic_equivalence_validation = _copy(prepared_semantic)
                    expected_binding = build_semantic_equivalence_binding(
                        plan=plan,
                        validation_plan_hash=validation_plan_hash,
                        result_manifest_hash=result_manifest_hash,
                        measurement_artifact_hashes=measurement_hashes,
                    )
                    if (
                        semantic_equivalence_validation.get("binding")
                        != expected_binding
                        or semantic_equivalence_validation.get("claims")
                        != list(plan["claims"])
                        or semantic_equivalence_validation.get(
                            "measurement_artifact_hashes"
                        )
                        != sorted(measurement_hashes)
                        or semantic_equivalence_validation.get("verdict")
                        != "passed"
                    ):
                        raise self._semantic_equivalence_repair_error(
                            "prepared semantic-equivalence trace differs"
                        )
                effective_implementation = new_identity
                implementation_changed = True
            mission_id = declaration.payload.get("mission_id")
            if type(mission_id) is not str:
                raise TransitionError(
                    "Repair candidate lost its Job Mission authority"
                )
            repair_validation = self._require_repair_evaluation_capability(
                capability=_candidate_capability,
                current=current,
                candidate=candidate,
                mission_id=mission_id,
                expected_mode="repaired",
            )
            attempt_fingerprint = repair_attempt_intervention_fingerprint(
                proof,
                verification_capabilities=repair_validation_capabilities(
                    repair_validation
                ),
            )
            fingerprint_record_id = canonical_digest(
                domain="repair-attempt-fingerprint",
                payload={
                    "attempt_fingerprint": attempt_fingerprint,
                    "repair_id": repair["id"],
                },
            )
            if _index.get(
                "repair-attempt-fingerprint", fingerprint_record_id
            ) is not None:
                raise IdenticalFailedRetryError(
                    "identical Repair intervention requires new evidence or protocol"
                )
            candidate_authority = {
                "repair_candidate": candidate.payload(),
                "repair_candidate_hash": candidate.sha256,
                "repair_evaluation": _candidate_capability.evaluation.payload(),
            }
            attempt_identity_payload = {
                "attempt_proof_hash": changed_cause_proof_hash,
                "attempt_fingerprint": attempt_fingerprint,
                **proof.payload(),
                "repair_authority_schema": REGISTERED_REPAIR_AUTHORITY_SCHEMA,
                "repair_validation": repair_validation,
                **candidate_authority,
            }
            if semantic_equivalence_validation is not None:
                attempt_identity_payload["semantic_equivalence_validation"] = (
                    semantic_equivalence_validation
                )
            attempt_record_id = canonical_digest(
                domain="repair-attempt",
                payload=attempt_identity_payload,
            )
            attempt_record = _record(
                kind="repair-attempt",
                record_id=attempt_record_id,
                subject=f"Repair:{repair['id']}",
                status="repaired",
                fingerprint=changed_cause_proof_hash,
                payload={
                    "attempt_proof_hash": changed_cause_proof_hash,
                    "attempt_fingerprint": attempt_fingerprint,
                    **proof.payload(),
                    "repair_authority_schema": (
                        REGISTERED_REPAIR_AUTHORITY_SCHEMA
                    ),
                    "repair_validation": repair_validation,
                    **candidate_authority,
                    **(
                        {
                            "semantic_equivalence_validation": (
                                semantic_equivalence_validation
                            )
                        }
                        if semantic_equivalence_validation is not None
                        else {}
                    ),
                    "scientific_failure_delta": 0,
                    "scientific_trial_delta": 0,
                },
                event_stream=f"repair-attempt:{repair['id']}",
                event_sequence=attempt_sequence,
            )
            fingerprint_record = _record(
                kind="repair-attempt-fingerprint",
                record_id=fingerprint_record_id,
                subject=f"Repair:{repair['id']}",
                status="repaired",
                fingerprint=attempt_fingerprint,
                payload={
                    "attempt_fingerprint": attempt_fingerprint,
                    "attempt_record_id": attempt_record_id,
                    "repair_id": repair["id"],
                },
            )
            science["active_repair"] = None
            job["status"] = "running"
            repair_stream = f"job-repair:{job['id']}"
            repair_head = _index.event_head(repair_stream)
            repair_close_identity_payload = {
                "repair_id": repair["id"],
                "proof": changed_cause_proof_hash,
                "repair_authority_schema": REGISTERED_REPAIR_AUTHORITY_SCHEMA,
                "repair_validation": repair_validation,
                **candidate_authority,
            }
            if semantic_equivalence_validation is not None:
                repair_close_identity_payload[
                    "semantic_equivalence_validation"
                ] = semantic_equivalence_validation
            repair_close_id = canonical_digest(
                domain="repair-close",
                payload=repair_close_identity_payload,
            )
            job["required_repair_resume_record_id"] = repair_close_id
            body["next_action"] = {
                "job_id": job["id"],
                "kind": "resume_job",
                "repair_close_record_id": repair_close_id,
            }
            record = _record(
                kind="repair-close",
                record_id=repair_close_id,
                subject=f"Job:{job['id']}",
                status="repaired",
                fingerprint=changed_cause_proof_hash,
                payload={
                    "attempt_record_id": attempt_record_id,
                    "changed_dimension": proof.changed_dimension,
                    "resume_action": repair["resume_action"],
                    "changed_cause_proof_hash": changed_cause_proof_hash,
                    "effective_implementation_identity": (
                        effective_implementation
                    ),
                    "implementation_changed": implementation_changed,
                    "job_id": job["id"],
                    "previous_effective_implementation_identity": (
                        prior_effective
                    ),
                    "prior_attempt_record_id": prior_attempt_record_id,
                    "repair_id": repair["id"],
                    "repair_authority_schema": (
                        REGISTERED_REPAIR_AUTHORITY_SCHEMA
                    ),
                    "repair_validation": repair_validation,
                    **candidate_authority,
                    **(
                        {
                            "semantic_equivalence_validation": (
                                semantic_equivalence_validation
                            )
                        }
                        if semantic_equivalence_validation is not None
                        else {}
                    ),
                    "scientific_trial_delta": 0,
                    "scientific_failure_delta": 0,
                    "verification_evidence_hashes": list(
                        proof.verification_evidence_hashes
                    ),
                },
                event_stream=repair_stream,
                event_sequence=(
                    1 if repair_head is None else repair_head.sequence + 1
                ),
            )
            return body, [fingerprint_record, attempt_record, record], {
                "attempt_record_id": attempt_record_id,
                "effective_implementation_identity": (
                    effective_implementation
                ),
                "job_id": job["id"],
                "repair_id": repair["id"],
                "repair_close_record_id": repair_close_id,
                "resume_action": repair["resume_action"],
            }

        return self._commit(
            event_kind="repair_closed",
            operation_id=operation_id,
            subject="Repair:active",
            payload={"changed_cause_proof_hash": changed_cause_proof_hash},
            prepare=prepare,
        )
