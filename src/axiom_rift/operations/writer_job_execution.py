"""Job permit consumption, execution, validation, completion, and evidence judgment."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.diagnosis_authority_context import (
    DiagnosisAuthorityContext,
    DiagnosisAuthorityContextError,
)
from axiom_rift.operations.external_dependency import (
    ExternalDependencyContractError,
    external_plan_from_binding,
)
from axiom_rift.operations.external_observed_development_binding import (
    ExternalObservedDevelopmentJobBindingError,
    require_current_external_observed_development_job_binding,
)
from axiom_rift.operations.job_completion_entry_authority import (
    JobCompletionEntryAuthorityError,
    JobCompletionEntryIntegrityError,
    require_completion_engine_entry,
    require_repair_resume_entry,
)
from axiom_rift.operations.job_completion_projection import (
    JobCompletionProjectionError,
    JobCompletionProjectionIntegrityError,
    project_job_completion,
)
from axiom_rift.operations.job_contract import (
    JobContractError,
    normalize_job_failure_manifest,
    require_job_output_namespace,
)
from axiom_rift.operations.job_retry_admission import (
    JobRetryAdmissionIntegrityError,
    build_retry_family_completion_record,
)
from axiom_rift.operations.permits import (
    Permit,
    PermitError,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.running_job import RunningJobExecution
from axiom_rift.operations.runtime_completion import (
    RuntimeSuccessAuthorityError,
    candidate_job_execution_context,
    current_runtime_source_snapshot,
)
from axiom_rift.operations.scientific_multiplicity_authority import (
    ScientificMultiplicityAuthorityError,
    ScientificMultiplicityIntegrityError,
    validate_scientific_multiplicity_registrations,
)
from axiom_rift.operations.validation import (
    EvidenceValidationError,
    EvidenceValidationRequest,
    ValidationArtifact,
)
from axiom_rift.operations.writer_job_admission import (
    _job_implementation_source_closure_hashes,
    _job_requires_current_source_authority,
    _require_concurrent_family_registration,
)
from axiom_rift.operations.writer_support import (
    RecoveryRequired,
    TransitionError,
    TransitionResult,
    _copy,
    _record,
    _require_ascii,
    _require_digest,
    _require_study_evidence_modes,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


_JOB_COMPLETION_VALIDATION_CAPABILITY_TOKEN = object()


@dataclass(frozen=True, slots=True)
class _JobCompletionValidationCapability:
    """Registered Job evidence derived once outside the Writer lock."""

    token: object
    control_hash: str
    job_id: str
    job_hash: str
    request_hash: str
    manifests: Mapping[str, Mapping[str, Any]]
    manifests_hash: str


def _require_job_output_namespace(
    output_names: Sequence[object],
    *,
    output_classes: Mapping[object, object] | None = None,
    name: str = "Job outputs",
) -> None:
    try:
        require_job_output_namespace(
            output_names,
            output_classes=output_classes,
            name=name,
        )
    except JobContractError as exc:
        raise TransitionError(str(exc)) from exc


class JobExecutionWriterMixin:
    """Own bounded Job execution and evidence transitions behind StateWriter."""

    def _validate_permit_locked(
        self,
        *,
        control: Mapping[str, Any],
        index: LocalIndex,
        permit: Permit,
        expected_kind: PermitKind,
        action: str,
        subject_kind: SubjectKind,
        subject_id: str,
        expected_input_hash: str | None = None,
        required_scope: tuple[str, ...] = (),
    ) -> None:
        if self.permit_authority is None:
            raise PermitError("permit authority is unavailable")
        current_subject = self._current_subject(control, subject_kind, subject_id)
        self.permit_authority.validate(
            permit,
            expected_kind=expected_kind,
            action=action,
            current_subject=current_subject,
            status=self._permit_status(index, permit.permit_id),
            now_utc=self.clock(),
            expected_input_hash=expected_input_hash,
            required_scope=required_scope,
        )

    def validate_runtime_entry(
        self,
        *,
        permit: Permit,
        executable_id: str,
        input_hash: str,
        action: str,
        depth: Any,
        operation_id: str,
    ) -> TransitionResult:
        """Revalidate and durably attest the exact runtime engine entry."""

        from axiom_rift.runtime.guards import (
            CandidateBinding,
            EvidenceDepth,
            RuntimeClaimGuard,
        )

        if not isinstance(depth, EvidenceDepth):
            raise TransitionError("runtime depth must be an EvidenceDepth")
        if depth not in {
            EvidenceDepth.EXECUTION_PROOF,
            EvidenceDepth.MATERIALIZATION,
        }:
            raise PermitError("RuntimePermit cannot authorize this evidence depth")
        _require_ascii("executable_id", executable_id)
        _require_digest("input_hash", input_hash)

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            if science["active_executable"] != executable_id:
                raise TransitionError("runtime entry is not the active Executable")
            job = science["active_job"]
            if not isinstance(job, dict) or job.get("status") != "running":
                raise TransitionError("runtime entry requires the active running Job")
            if input_hash != job.get("hash"):
                raise PermitError("runtime entry input is not the active Job identity")
            if job.get("runtime_entry_record_id") is not None:
                raise TransitionError("runtime engine entry was already attested")
            declaration = index.get("job-declared", job["id"])
            start_record = index.get("job-started", job.get("start_record_id", ""))
            if declaration is None or start_record is None:
                raise TransitionError("runtime entry Job provenance is unavailable")
            runtime_binding = declaration.payload["spec"].get("runtime_binding")
            started_runtime = start_record.payload.get("runtime")
            if (
                not isinstance(runtime_binding, dict)
                or not isinstance(started_runtime, dict)
                or runtime_binding.get("action") != action
                or runtime_binding.get("evidence_depth") != depth.value
                or started_runtime.get("runtime_permit_id") != permit.permit_id
                or started_runtime.get("executable_id") != executable_id
                or started_runtime.get("mission_id") != science["active_mission"]
            ):
                raise PermitError("runtime entry differs from its started Job binding")
            candidate_head = index.event_head(f"candidate:{executable_id}")
            candidate_record = (
                None
                if candidate_head is None
                else index.get(candidate_head.record_kind, candidate_head.record_id)
            )
            allowed = {("candidate", "frozen")}
            if self.engineering_fixture:
                allowed.add(("engineering-executable-fixture", "bound_fixture"))
            if candidate_record is None or (
                candidate_record.kind,
                candidate_record.status,
            ) not in allowed:
                raise TransitionError("runtime entry has no durable candidate binding")
            source_contracts = tuple(
                candidate_record.payload["executable"].get("source_contracts", [])
            )
            try:
                current_source_snapshot = current_runtime_source_snapshot(
                    index=index,
                    source_contract_ids=source_contracts,
                    require_runtime_source=lambda source_index, source_id: (
                        self._require_runtime_source(
                            source_index,
                            source_id,
                            error_type=PermitError,
                        )
                    ),
                )
                expected_candidate_context = candidate_job_execution_context(
                    index=index,
                    candidate=candidate_record,
                    current=current_source_snapshot,
                    runtime_binding=runtime_binding,
                )
            except RuntimeSuccessAuthorityError as exc:
                raise PermitError(str(exc)) from exc
            if (
                candidate_record.record_id != started_runtime.get("candidate_id")
                or candidate_record.subject != f"Executable:{executable_id}"
                or candidate_record.payload.get("mission_id")
                != science["active_mission"]
                or declaration.payload.get("candidate_execution_context")
                != expected_candidate_context
                or {
                    name: started_runtime.get(name)
                    for name in current_source_snapshot.payload()
                }
                != current_source_snapshot.payload()
            ):
                raise PermitError(
                    "runtime entry candidate or source snapshot changed after Job start"
                )
            required_scope = (
                f"candidate:{candidate_record.record_id}",
                f"depth:{depth.value}",
                f"executable:{executable_id}",
                f"job:{job['id']}",
            ) + tuple(f"source:{source_id}" for source_id in source_contracts)
            self._validate_permit_locked(
                control=current,
                index=index,
                permit=permit,
                expected_kind=PermitKind.RUNTIME,
                action=action,
                subject_kind=SubjectKind.EXECUTABLE,
                subject_id=executable_id,
                expected_input_hash=input_hash,
                required_scope=required_scope,
            )
            candidate = CandidateBinding(
                candidate_id=candidate_record.record_id,
                executable_id=executable_id,
                frozen=True,
                source_bindings=source_contracts,
            )
            RuntimeClaimGuard.require_entry(depth=depth, candidate=candidate)
            executable_subject = self._current_subject(
                current, SubjectKind.EXECUTABLE, executable_id
            )
            entry_payload = {
                "action": action,
                "candidate_authorization_hash": executable_subject.authorization_hash,
                "candidate_id": candidate_record.record_id,
                "depth": depth.value,
                "engine_contract": candidate_record.payload["executable"]["engine_contract"],
                "executable_id": executable_id,
                "job_id": job["id"],
                "job_start_record_id": job["start_record_id"],
                "mission_id": science["active_mission"],
                "runtime_permit_id": permit.permit_id,
                **current_source_snapshot.payload(),
            }
            entry_id = canonical_digest(domain="runtime-engine-entry", payload=entry_payload)
            entry = _record(
                kind="runtime-engine-entry",
                record_id=entry_id,
                subject=f"Job:{job['id']}",
                status="validated",
                fingerprint=job["hash"],
                payload=entry_payload,
                event_stream=f"runtime-entry:{job['id']}",
                event_sequence=1,
            )
            job["runtime_entry_record_id"] = entry_id
            body["next_action"] = {"kind": "resume_job", "job_id": job["id"]}
            return body, [entry], {
                "runtime_entry_record_id": entry_id,
                "permit_id": permit.permit_id,
                "executable_id": executable_id,
                "depth": depth.value,
                "current_source_receipts": list(
                    current_source_snapshot.source_receipt_ids
                ),
                "current_source_state_records": list(
                    current_source_snapshot.source_state_record_ids
                ),
            }

        return self._commit(
            event_kind="runtime_engine_entered",
            operation_id=operation_id,
            subject=f"Executable:{executable_id}",
            payload={
                "permit_id": permit.permit_id,
                "input_hash": input_hash,
                "action": action,
                "depth": depth.value,
            },
            prepare=prepare,
        )

    @staticmethod
    def _permit_consumption_record(permit: Permit, operation_id: str) -> IndexRecord:
        record_id = canonical_digest(
            domain="permit-consumption",
            payload={"permit_id": permit.permit_id, "operation_id": operation_id},
        )
        return _record(
            kind="permit-consumed",
            record_id=record_id,
            subject=f"Permit:{permit.permit_id}",
            status="consumed",
            fingerprint=permit.permit_id,
            payload={"permit_id": permit.permit_id, "one_shot": permit.one_shot},
            event_stream=f"permit:{permit.permit_id}",
            event_sequence=2,
        )

    def start_job(
        self,
        *,
        permit: Permit,
        operation_id: str,
        runtime_permit: Permit | None = None,
    ) -> TransitionResult:
        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            job = body["scientific"]["active_job"]
            if not isinstance(job, dict) or job["status"] != "declared":
                raise TransitionError("no declared Job can start")
            self._validate_permit_locked(
                control=current,
                index=index,
                permit=permit,
                expected_kind=PermitKind.JOB,
                action="start_job",
                subject_kind=SubjectKind.JOB,
                subject_id=job["id"],
                expected_input_hash=job["hash"],
            )
            declaration = index.get("job-declared", job["id"])
            if declaration is None:
                raise TransitionError("Job declaration is unavailable at start")
            declared_spec = declaration.payload["spec"]
            if _job_requires_current_source_authority(
                engineering_fixture=self.engineering_fixture,
                evidence_subject_kind=declared_spec["evidence_subject"]["kind"],
            ):
                from axiom_rift.research.implementation_closure import (
                    ImplementationClosureError,
                    require_current_job_source_closure,
                    require_job_implementation_closure,
                )

                implementation_manifest = (
                    self._require_job_implementation_evidence(
                        declared_spec,
                        _index=index,
                    )
                )
                executable_manifest: dict[str, Any] | None = None
                try:
                    component_implementation_hashes: tuple[str, ...] = ()
                    if declared_spec["evidence_subject"]["kind"] == "Executable":
                        subject_trial = index.get(
                            "trial", declared_spec["evidence_subject"]["id"]
                        )
                        executable_manifest = (
                            None
                            if subject_trial is None
                            else subject_trial.payload.get("executable")
                        )
                        if not isinstance(executable_manifest, dict):
                            raise RecoveryRequired(
                                "Executable Job subject lost its exact trial manifest"
                            )
                        component_implementation_hashes = (
                            require_job_implementation_closure(
                                executable_manifest=executable_manifest,
                                job_artifact_hashes=implementation_manifest[
                                    "artifact_hashes"
                                ],
                                artifact_reader=self.evidence.read_verified,
                            )
                        )
                except ImplementationClosureError as exc:
                    raise TransitionError(str(exc)) from exc
                declared_component_hashes = declaration.payload.get(
                    "component_implementation_hashes"
                )
                if (
                    declared_component_hashes
                    != (
                        list(component_implementation_hashes)
                        if component_implementation_hashes
                        else None
                    )
                ):
                    raise RecoveryRequired(
                        "Job Component implementation closure drifted before start"
                    )
                source_closure_hashes = (
                    _job_implementation_source_closure_hashes(
                        implementation_manifest=implementation_manifest,
                        artifact_reader=self.evidence.read_verified,
                    )
                )
                declared_authority = declaration.payload.get(
                    "source_closure_authority"
                )
                if source_closure_hashes:
                    if not isinstance(declared_authority, Mapping):
                        raise RecoveryRequired(
                            "prospective Job lacks declared source-path authority"
                        )
                    try:
                        current_authority = (
                            require_current_job_source_closure(
                                callable_identity=declared_spec[
                                    "callable_identity"
                                ],
                                job_artifact_hashes=(
                                    implementation_manifest[
                                        "artifact_hashes"
                                    ]
                                ),
                                artifact_reader=self.evidence.read_verified,
                                source_root=self.foundation_root / "src",
                                verified_non_source_artifact_hashes=(
                                    component_implementation_hashes
                                ),
                            )
                        )
                    except ImplementationClosureError as exc:
                        raise TransitionError(str(exc)) from exc
                    if current_authority != declared_authority:
                        raise RecoveryRequired(
                            "Job source-path authority drifted before start"
                        )
                    try:
                        if executable_manifest is not None:
                            closure_payload = parse_canonical(
                                self.evidence.read_verified(
                                    source_closure_hashes[0]
                                )
                            )
                            if not isinstance(closure_payload, Mapping):
                                raise ExternalObservedDevelopmentJobBindingError(
                                    "Job source closure payload is malformed"
                                )
                            require_current_external_observed_development_job_binding(
                                executable_id=declared_spec[
                                    "evidence_subject"
                                ]["id"],
                                executable_manifest=executable_manifest,
                                job_spec=declared_spec,
                                source_closure_dependencies=closure_payload[
                                    "dependencies"
                                ],
                                durable_payload=declaration.payload.get(
                                    "external_observed_development_binding"
                                ),
                                repository_root=self.foundation_root,
                            )
                        elif declaration.payload.get(
                            "external_observed_development_binding"
                        ) is not None:
                            raise ExternalObservedDevelopmentJobBindingError(
                                "non-Executable Job has an external prefix binding"
                            )
                    except ExternalObservedDevelopmentJobBindingError as exc:
                        raise TransitionError(str(exc)) from exc
                else:
                    raise RecoveryRequired(
                        "production Job without a current recursive source closure "
                        "cannot start; historical evidence is read-only"
                    )
            batch_id = declaration.payload.get("batch_id")
            if isinstance(batch_id, str):
                active_batch = body["scientific"].get("active_batch")
                batch_record = index.get("batch-open", batch_id)
                if (
                    not isinstance(active_batch, dict)
                    or active_batch.get("id") != batch_id
                    or batch_record is None
                ):
                    raise RecoveryRequired(
                        "Job start lost its active frozen Batch declaration"
                    )
                _require_concurrent_family_registration(
                    index,
                    batch_record=batch_record,
                    evidence_subject=declared_spec["evidence_subject"],
                )
            runtime_binding = declared_spec.get("runtime_binding")
            for domain, binding_name in (
                ("scientific", "component_parity_binding"),
                ("external", "external_dependency_binding"),
                ("scientific", "scientific_binding"),
                ("source", "source_binding"),
                ("runtime", "runtime_binding"),
            ):
                binding = declared_spec.get(binding_name)
                if isinstance(binding, dict):
                    try:
                        self.validation_registry.preflight_binding(
                            validator_id=binding["validator_id"],
                            domain=domain,
                            binding=binding,
                        )
                    except EvidenceValidationError as exc:
                        raise TransitionError(str(exc)) from exc
            runtime_provenance: dict[str, Any] | None = None
            if runtime_binding is None:
                if runtime_permit is not None:
                    raise PermitError("a non-runtime Job cannot consume RuntimePermit authority")
            else:
                if runtime_permit is None:
                    raise PermitError("runtime-bound Job requires a RuntimePermit")
                science = body["scientific"]
                executable_id = science["active_executable"]
                if (
                    executable_id is None
                    or declaration.payload["spec"]["evidence_subject"]
                    != {"kind": "Executable", "id": executable_id}
                ):
                    raise TransitionError("runtime Job is not bound to the active Executable")
                candidate_head = index.event_head(f"candidate:{executable_id}")
                candidate = (
                    None
                    if candidate_head is None
                    else index.get(candidate_head.record_kind, candidate_head.record_id)
                )
                expected_kind = (
                    "engineering-executable-fixture"
                    if self.engineering_fixture
                    else "candidate"
                )
                expected_status = "bound_fixture" if self.engineering_fixture else "frozen"
                if (
                    candidate is None
                    or candidate.kind != expected_kind
                    or candidate.status != expected_status
                ):
                    raise TransitionError("runtime Job lacks the current candidate activation")
                source_contracts = tuple(
                    candidate.payload["executable"].get("source_contracts", [])
                )
                try:
                    source_snapshot = current_runtime_source_snapshot(
                        index=index,
                        source_contract_ids=source_contracts,
                        require_runtime_source=lambda source_index, source_id: (
                            self._require_runtime_source(
                                source_index,
                                source_id,
                                error_type=PermitError,
                            )
                        ),
                    )
                    expected_candidate_context = (
                        candidate_job_execution_context(
                            index=index,
                            candidate=candidate,
                            current=source_snapshot,
                            runtime_binding=runtime_binding,
                        )
                    )
                except RuntimeSuccessAuthorityError as exc:
                    raise PermitError(str(exc)) from exc
                if (
                    candidate.subject != f"Executable:{executable_id}"
                    or candidate.payload.get("mission_id")
                    != science["active_mission"]
                    or declaration.payload.get("candidate_execution_context")
                    != expected_candidate_context
                ):
                    raise PermitError(
                        "runtime Job candidate or source snapshot changed before start"
                    )
                required_scope = (
                    f"candidate:{candidate.record_id}",
                    f"depth:{runtime_binding['evidence_depth']}",
                    f"executable:{executable_id}",
                    f"job:{job['id']}",
                ) + tuple(f"source:{source_id}" for source_id in source_contracts)
                self._validate_permit_locked(
                    control=current,
                    index=index,
                    permit=runtime_permit,
                    expected_kind=PermitKind.RUNTIME,
                    action=runtime_binding["action"],
                    subject_kind=SubjectKind.EXECUTABLE,
                    subject_id=executable_id,
                    expected_input_hash=job["hash"],
                    required_scope=required_scope,
                )
                runtime_provenance = {
                    "action": runtime_binding["action"],
                    "candidate_id": candidate.record_id,
                    "evidence_depth": runtime_binding["evidence_depth"],
                    "executable_id": executable_id,
                    "mission_id": science["active_mission"],
                    "runtime_permit_id": runtime_permit.permit_id,
                    **source_snapshot.payload(),
                }
            start_id = canonical_digest(
                domain="job-start",
                payload={
                    "job_id": job["id"],
                    "job_permit": permit.permit_id,
                    "runtime_permit": (
                        None if runtime_permit is None else runtime_permit.permit_id
                    ),
                },
            )
            job["status"] = "running"
            job["start_record_id"] = start_id
            body["next_action"] = {"kind": "resume_job", "job_id": job["id"]}
            consumption = self._permit_consumption_record(permit, operation_id)
            record = _record(
                kind="job-started",
                record_id=start_id,
                subject=f"Job:{job['id']}",
                status="running",
                fingerprint=job["hash"],
                payload={
                    "job_permit_id": permit.permit_id,
                    "runtime": runtime_provenance,
                },
            )
            execution = RunningJobExecution(
                job_id=job["id"],
                job_hash=job["hash"],
                start_record_id=start_id,
                job_permit_id=permit.permit_id,
            )
            engine_records: list[IndexRecord] = []
            if runtime_binding is None:
                engine_entry_id = canonical_digest(
                    domain="job-engine-entry",
                    payload=execution.payload(),
                )
                job["engine_entry_record_id"] = engine_entry_id
                engine_records.append(
                    _record(
                        kind="job-engine-entry",
                        record_id=engine_entry_id,
                        subject=f"Job:{job['id']}",
                        status="validated",
                        fingerprint=job["hash"],
                        payload={
                            "execution": execution.payload(),
                            "permit_consumption_record_id": consumption.record_id,
                        },
                    )
                )
            return body, [consumption, record, *engine_records], {
                "execution": execution.payload(),
                "job_id": job["id"],
            }

        return self._commit(
            event_kind="job_started",
            operation_id=operation_id,
            subject=f"Job:{permit.subject.subject_id}",
            payload={
                "permit_id": permit.permit_id,
                "runtime_permit_id": (
                    None if runtime_permit is None else runtime_permit.permit_id
                ),
            },
            prepare=prepare,
        )

    def _run_registered_validator(
        self,
        *,
        domain: str,
        job_id: str,
        job_hash: str,
        mission_id: str,
        evidence_subject: Mapping[str, str],
        binding: Mapping[str, Any],
        result_manifest: Mapping[str, Any],
        output_manifest: Mapping[str, Any],
        output_classes: Mapping[str, Any],
        result_name: str,
        artifact_output_names: frozenset[str] | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        if artifact_output_names is not None and (
            not artifact_output_names
            or any(
                type(output_name) is not str or not output_name
                for output_name in artifact_output_names
            )
        ):
            raise TransitionError("validator artifact output scope is invalid")
        artifacts: list[ValidationArtifact] = []
        for output_name, output_hash in sorted(output_manifest.items()):
            if output_classes.get(output_name) != "durable_evidence":
                continue
            if (
                artifact_output_names is not None
                and output_name not in artifact_output_names
            ):
                continue
            artifacts.append(
                ValidationArtifact(
                    output_name=output_name,
                    sha256=output_hash,
                    _source=self.evidence.verified_path(output_hash),
                )
            )
        if not any(artifact.output_name == result_name for artifact in artifacts):
            raise TransitionError("result manifest is absent from validator artifacts")
        request = EvidenceValidationRequest(
            domain=domain,
            validator_id=binding["validator_id"],
            validation_plan_hash=binding["validation_plan_hash"],
            job_id=job_id,
            job_hash=job_hash,
            mission_id=mission_id,
            evidence_subject=evidence_subject,
            binding=binding,
            result_manifest=result_manifest,
            artifacts=tuple(artifacts),
            engineering_fixture=self.engineering_fixture,
        )
        try:
            validated, trace = self.validation_registry.validate(request)
        except EvidenceValidationError as exc:
            raise TransitionError(f"registered {domain} validation failed: {exc}") from exc
        return validated, {
            "validator_id": trace.validator_id,
            "declared_artifact_count": trace.declared_artifact_count,
            "opened_artifact_count": trace.opened_artifact_count,
        }

    def _scientific_validator_artifact_output_names(
        self,
        *,
        binding: Mapping[str, Any],
        result_name: str,
        measurement_hashes: set[str],
        output_manifest: Mapping[str, Any],
        output_classes: Mapping[str, Any],
    ) -> frozenset[str] | None:
        """Route only v2 core and preregistered proof artifacts to science."""

        plan_hash = binding.get("validation_plan_hash")
        if type(plan_hash) is not str:
            raise TransitionError("scientific validation plan hash is absent")
        try:
            plan = parse_canonical(self.evidence.read_verified(plan_hash))
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
            raise TransitionError(
                "scientific validation plan is unavailable"
            ) from exc
        if (
            not isinstance(plan, Mapping)
            or plan.get("schema") != "scientific_validation_plan.v2"
        ):
            return None
        requirements = plan.get("proof_requirements")
        if not isinstance(requirements, list) or not requirements:
            raise TransitionError(
                "scientific v2 proof requirement routing is unavailable"
            )
        proof_names: set[str] = set()
        for requirement in requirements:
            output_name = (
                None
                if not isinstance(requirement, Mapping)
                else requirement.get("output_name")
            )
            if type(output_name) is not str or not output_name:
                raise TransitionError(
                    "scientific v2 proof output routing is malformed"
                )
            proof_names.add(output_name)
        plan_names = {
            output_name
            for output_name, output_hash in output_manifest.items()
            if output_hash == plan_hash
            and output_classes.get(output_name) == "durable_evidence"
        }
        measurement_names = {
            output_name
            for output_name, output_hash in output_manifest.items()
            if output_hash in measurement_hashes
            and output_classes.get(output_name) == "durable_evidence"
        }
        routed = {
            result_name,
            *plan_names,
            *measurement_names,
            *proof_names,
        }
        if (
            len(plan_names) != 1
            or not measurement_hashes
            or len(measurement_names) != len(measurement_hashes)
            or {
                output_manifest[output_name]
                for output_name in measurement_names
            }
            != measurement_hashes
            or len(routed)
            != 1 + len(plan_names) + len(measurement_names) + len(proof_names)
            or any(
                output_classes.get(output_name) != "durable_evidence"
                or output_name not in output_manifest
                for output_name in routed
            )
        ):
            raise TransitionError(
                "scientific v2 validator artifact routing is ambiguous"
            )
        return frozenset(routed)

    def _validated_scientific_multiplicity_registrations(
        self,
        *,
        binding: Mapping[str, Any],
        registrations: object,
        adjudication: object,
        batch_record: IndexRecord | None,
        expected_batch_id: str | None,
        executable_id: str,
        mission_id: str,
    ) -> tuple[
        list[dict[str, Any]] | None,
        dict[str, Any] | None,
    ]:
        try:
            return validate_scientific_multiplicity_registrations(
                binding=binding,
                registrations=registrations,
                adjudication=adjudication,
                batch_record=batch_record,
                expected_batch_id=expected_batch_id,
                executable_id=executable_id,
                mission_id=mission_id,
                artifact_reader=self.evidence.read_verified,
            )
        except ScientificMultiplicityIntegrityError as exc:
            raise RecoveryRequired(str(exc)) from exc
        except ScientificMultiplicityAuthorityError as exc:
            raise TransitionError(str(exc)) from exc

    def _derive_runtime_job_evidence(
        self,
        *,
        job_id: str,
        job_hash: str,
        binding: Mapping[str, Any],
        provenance: Mapping[str, Any],
        source_lifecycle_coverage: object,
        output_manifest: Mapping[str, Any],
        output_classes: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Parse a content-addressed runtime result packet and derive claims."""

        result_name = binding["result_manifest_output"]
        result_hash = output_manifest.get(result_name)
        if not isinstance(result_hash, str):
            raise TransitionError("runtime result manifest output is absent")
        try:
            value = parse_canonical(self.evidence.read_verified(result_hash))
        except ValueError as exc:
            raise TransitionError("runtime result manifest is not canonical") from exc
        required = {
            "action",
            "candidate_id",
            "evidence_depth",
            "executable_id",
            "job_hash",
            "job_id",
            "mission_id",
            "observations",
            "runtime_permit_id",
            "schema",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise TransitionError("runtime result manifest schema is invalid")
        expected_values = {
            "action": binding["action"],
            "candidate_id": provenance["candidate_id"],
            "evidence_depth": binding["evidence_depth"],
            "executable_id": provenance["executable_id"],
            "job_hash": job_hash,
            "job_id": job_id,
            "mission_id": provenance["mission_id"],
            "runtime_permit_id": provenance["runtime_permit_id"],
            "schema": "runtime_job_evidence.v1",
        }
        if any(value.get(name) != expected for name, expected in expected_values.items()):
            raise TransitionError("runtime result manifest is bound to another execution")
        observations = value["observations"]
        if not isinstance(observations, list) or not observations:
            raise TransitionError("runtime result manifest has no observations")
        durable_hashes = {
            output_hash
            for output_name, output_hash in output_manifest.items()
            if output_classes.get(output_name) == "durable_evidence"
            and output_name != result_name
        }
        if not durable_hashes:
            raise TransitionError("runtime result has no measurement artifact")
        from axiom_rift.runtime.source_lifecycle_coverage import (
            SourceLifecycleCoverageError,
            require_source_lifecycle_coverage_ids,
        )

        coverage_rows = source_lifecycle_coverage
        if not isinstance(coverage_rows, list) or any(
            not isinstance(row, Mapping) for row in coverage_rows
        ):
            raise TransitionError(
                "runtime Job lacks Writer-derived source lifecycle coverage"
            )
        try:
            planned_coverage_ids = require_source_lifecycle_coverage_ids(
                binding["planned_source_lifecycle_coverage_ids"],
                allowed_rows=coverage_rows,
                planned_materialization_cases=binding[
                    "planned_materialization_cases"
                ],
            )
        except SourceLifecycleCoverageError as exc:
            raise TransitionError(str(exc)) from exc
        coverage_by_id = {
            row["coverage_id"]: row for row in coverage_rows
        }
        claims: set[str] = set()
        measurement_hashes: set[str] = set()
        observation_keys: set[tuple[str, str | None]] = set()
        observed_coverage_ids: set[str] = set()
        for observation in observations:
            if not isinstance(observation, dict) or set(observation) not in ({
                "claim_id",
                "measurement_artifact_hash",
                "status",
            }, {
                "claim_id",
                "measurement_artifact_hash",
                "source_lifecycle_coverage_id",
                "status",
            }):
                raise TransitionError("runtime observation schema is invalid")
            claim_id = observation["claim_id"]
            measurement_hash = observation["measurement_artifact_hash"]
            coverage_id = observation.get("source_lifecycle_coverage_id")
            observation_key = (claim_id, coverage_id)
            if (
                type(claim_id) is not str
                or observation_key in observation_keys
                or measurement_hash not in durable_hashes
            ):
                raise TransitionError("runtime observation is not artifact-bound")
            if coverage_id is not None:
                coverage_row = coverage_by_id.get(coverage_id)
                if (
                    coverage_id not in planned_coverage_ids
                    or coverage_row is None
                    or coverage_row.get("materialization_case") != claim_id
                ):
                    raise TransitionError(
                        "runtime source lifecycle observation exceeds its exact plan"
                    )
                observed_coverage_ids.add(coverage_id)
            elif coverage_rows and claim_id in {
                "source_interruption",
                "stale_or_missing_input",
            }:
                raise TransitionError(
                    "source-dependent lifecycle observation lacks its exact coverage row"
                )
            self.evidence.verify(measurement_hash)
            observation_keys.add(observation_key)
            claims.add(claim_id)
            measurement_hashes.add(measurement_hash)
        if observed_coverage_ids != set(planned_coverage_ids):
            raise TransitionError(
                "runtime source lifecycle observations do not cover the exact plan"
            )
        planned = (
            set(binding["planned_parity_surfaces"])
            if binding["evidence_depth"] == "execution_proof"
            else set(binding["planned_materialization_cases"])
        )
        if not claims.issubset(planned):
            raise TransitionError("runtime result exceeds preregistered claims")
        validated, validation_trace = self._run_registered_validator(
            domain="runtime",
            job_id=job_id,
            job_hash=job_hash,
            mission_id=provenance["mission_id"],
            evidence_subject={"kind": "Executable", "id": provenance["executable_id"]},
            binding=binding,
            result_manifest=value,
            output_manifest=output_manifest,
            output_classes=output_classes,
            result_name=result_name,
        )
        if validated.verdict != "passed" or set(validated.claims) != claims:
            raise TransitionError("runtime claims were not derived as passed by the validator")
        if set(validated.measurement_artifact_hashes) != measurement_hashes:
            raise TransitionError("runtime validator measurements differ from the Job packet")
        validated_coverage = validated.facts.get(
            "source_lifecycle_coverage_ids"
        )
        if planned_coverage_ids and (
            not isinstance(validated_coverage, (list, tuple))
            or tuple(validated_coverage) != planned_coverage_ids
        ):
            raise TransitionError(
                "runtime validator did not derive the exact source lifecycle coverage"
            )
        if not planned_coverage_ids and validated_coverage not in (None, (), []):
            raise TransitionError(
                "runtime validator invented source lifecycle coverage"
            )
        expected_roles = {
            role: output_manifest[output_name]
            for role, output_name in binding["artifact_roles"].items()
        }
        observed_roles = dict(validated.artifact_roles)
        if observed_roles != expected_roles:
            raise TransitionError("runtime validator artifact roles differ from declaration")
        if not self.engineering_fixture and (
            not validated.scientific_eligible or not validated.release_eligible
        ):
            raise TransitionError("runtime validator did not authorize Release-eligible evidence")
        return {
            **dict(provenance),
            "artifact_roles": dict(validated.artifact_roles),
            "materialization_cases": (
                sorted(claims)
                if binding["evidence_depth"] == "materialization"
                else []
            ),
            "measurement_artifact_hashes": sorted(measurement_hashes),
            "parity_surfaces": (
                sorted(claims)
                if binding["evidence_depth"] == "execution_proof"
                else []
            ),
            "result_manifest_hash": result_hash,
            "source_lifecycle_coverage_ids": list(
                planned_coverage_ids
            ),
            "scientific_eligible": validated.scientific_eligible,
            "release_eligible": validated.release_eligible,
            "validation_trace": validation_trace,
            "validator_id": binding["validator_id"],
            "validation_plan_hash": binding["validation_plan_hash"],
        }

    def _derive_source_job_evidence(
        self,
        *,
        job_id: str,
        job_hash: str,
        mission_id: str,
        evidence_subject: Mapping[str, str],
        binding: Mapping[str, Any],
        output_manifest: Mapping[str, Any],
        output_classes: Mapping[str, Any],
    ) -> dict[str, Any]:
        result_name = binding["result_manifest_output"]
        result_hash = output_manifest.get(result_name)
        if not isinstance(result_hash, str):
            raise TransitionError("source result manifest output is absent")
        try:
            value = parse_canonical(self.evidence.read_verified(result_hash))
        except ValueError as exc:
            raise TransitionError("source result manifest is not canonical") from exc
        required = {
            "facts",
            "job_hash",
            "job_id",
            "measurement_artifact_hashes",
            "mission_id",
            "observed_at_utc",
            "schema",
            "source_contract_id",
            "transition_evidence",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise TransitionError("source result manifest schema is invalid")
        if (
            value["schema"] != "source_eligibility_evidence.v1"
            or value["job_id"] != job_id
            or value["job_hash"] != job_hash
            or value["mission_id"] != mission_id
            or value["source_contract_id"] != binding["source_contract_id"]
            or value["transition_evidence"] != binding["transition_evidence"]
        ):
            raise TransitionError("source result manifest is bound to another Job")
        measurement_hashes = value["measurement_artifact_hashes"]
        if (
            not isinstance(measurement_hashes, list)
            or not measurement_hashes
            or len(set(measurement_hashes)) != len(measurement_hashes)
        ):
            raise TransitionError("source result measurements are invalid")
        durable_hashes = {
            output_hash
            for output_name, output_hash in output_manifest.items()
            if output_classes.get(output_name) == "durable_evidence"
            and output_name != result_name
        }
        if set(measurement_hashes) != durable_hashes:
            raise TransitionError("source measurements differ from durable Job outputs")
        for measurement_hash in measurement_hashes:
            self.evidence.verify(measurement_hash)
        if not isinstance(value["facts"], dict):
            raise TransitionError("source result facts are invalid")
        _require_ascii("source observed_at_utc", value["observed_at_utc"])
        validated, validation_trace = self._run_registered_validator(
            domain="source",
            job_id=job_id,
            job_hash=job_hash,
            mission_id=mission_id,
            evidence_subject=evidence_subject,
            binding=binding,
            result_manifest=value,
            output_manifest=output_manifest,
            output_classes=output_classes,
            result_name=result_name,
        )
        verified_facts = dict(validated.facts)
        observed_at_utc = verified_facts.pop("observed_at_utc", None)
        if (
            validated.verdict != "passed"
            or set(validated.measurement_artifact_hashes) != set(measurement_hashes)
            or verified_facts != value["facts"]
            or observed_at_utc != value["observed_at_utc"]
        ):
            raise TransitionError("source facts were not derived by the registered validator")
        return {
            "artifact_hashes": sorted(measurement_hashes),
            "facts": verified_facts,
            "observed_at_utc": observed_at_utc,
            "result_manifest_hash": result_hash,
            "source_contract_id": binding["source_contract_id"],
            "transition_evidence": binding["transition_evidence"],
            "validation_trace": validation_trace,
            "validator_id": binding["validator_id"],
            "validation_plan_hash": binding["validation_plan_hash"],
        }

    def _derive_scientific_job_evidence(
        self,
        *,
        job_id: str,
        job_hash: str,
        mission_id: str,
        executable_id: str,
        binding: Mapping[str, Any],
        output_manifest: Mapping[str, Any],
        output_classes: Mapping[str, Any],
        batch_record: IndexRecord | None = None,
        expected_batch_id: str | None = None,
    ) -> dict[str, Any]:
        result_name = binding["result_manifest_output"]
        result_hash = output_manifest.get(result_name)
        if not isinstance(result_hash, str):
            raise TransitionError("scientific result manifest output is absent")
        try:
            value = parse_canonical(self.evidence.read_verified(result_hash))
        except ValueError as exc:
            raise TransitionError("scientific result manifest is not canonical") from exc
        required = {
            "evidence_depth",
            "executable_id",
            "job_hash",
            "job_id",
            "mission_id",
            "observations",
            "schema",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise TransitionError("scientific result manifest schema is invalid")
        if (
            value["schema"] != "scientific_job_evidence.v1"
            or value["job_id"] != job_id
            or value["job_hash"] != job_hash
            or value["mission_id"] != mission_id
            or value["executable_id"] != executable_id
            or value["evidence_depth"] != binding["evidence_depth"]
        ):
            raise TransitionError("scientific result belongs to another Job")
        durable_hashes = {
            output_hash
            for output_name, output_hash in output_manifest.items()
            if output_classes.get(output_name) == "durable_evidence"
            and output_name != result_name
        }
        observations = value["observations"]
        if not isinstance(observations, list) or not observations:
            raise TransitionError("scientific result has no observations")
        claims: set[str] = set()
        measurement_hashes: set[str] = set()
        for observation in observations:
            if not isinstance(observation, dict) or set(observation) != {
                "claim_id",
                "measurement_artifact_hash",
            }:
                raise TransitionError("scientific observation schema is invalid")
            claim_id = observation["claim_id"]
            measurement_hash = observation["measurement_artifact_hash"]
            if (
                type(claim_id) is not str
                or claim_id in claims
                or measurement_hash not in durable_hashes
            ):
                raise TransitionError("scientific observation is not artifact-bound")
            claims.add(claim_id)
            measurement_hashes.add(measurement_hash)
        if claims != set(binding["planned_claims"]):
            raise TransitionError("scientific observations differ from preregistration")
        validator_artifact_outputs = (
            self._scientific_validator_artifact_output_names(
                binding=binding,
                result_name=result_name,
                measurement_hashes=measurement_hashes,
                output_manifest=output_manifest,
                output_classes=output_classes,
            )
        )
        validated, validation_trace = self._run_registered_validator(
            domain="scientific",
            job_id=job_id,
            job_hash=job_hash,
            mission_id=mission_id,
            evidence_subject={"kind": "Executable", "id": executable_id},
            binding=binding,
            result_manifest=value,
            output_manifest=output_manifest,
            output_classes=output_classes,
            result_name=result_name,
            artifact_output_names=validator_artifact_outputs,
        )
        validator_facts = dict(validated.facts)
        executed_modes = validator_facts.pop("executed_evidence_modes", None)
        adjudication = validator_facts.pop("scientific_adjudication", None)
        multiplicity_registrations = validator_facts.pop(
            "multiplicity_registrations", None
        )
        if (
            validated.verdict not in {"passed", "failed", "not_evaluable"}
            or set(validated.claims) != claims
            or set(validated.measurement_artifact_hashes) != measurement_hashes
            or executed_modes != list(binding["evidence_modes"])
            or validator_facts
            or not validated.scientific_eligible
        ):
            raise TransitionError(
                "scientific evidence was not derived as eligible by the validator"
            )
        if adjudication is not None:
            required_adjudication = {
                "candidate_eligible",
                "claims",
                "criteria",
                "evaluable",
                "evidence_depth",
                "invalid_metrics",
                "legacy_verdict",
                "multiplicity",
                "schema",
                "state",
            }
            projected_verdict = {
                "confirmed": "passed",
                "contradicted": "failed",
                "frontier": "passed",
                "not_evaluable": "not_evaluable",
                "partial_positive": "not_evaluable",
                "unresolved": "not_evaluable",
            }
            if (
                not isinstance(adjudication, dict)
                or set(adjudication) != required_adjudication
                or adjudication.get("schema") != "scientific_adjudication.v1"
                or adjudication.get("evidence_depth") != binding["evidence_depth"]
                or projected_verdict.get(adjudication.get("state"))
                != validated.verdict
                or adjudication.get("candidate_eligible")
                is not validated.candidate_eligible
                or not isinstance(adjudication.get("claims"), list)
                or {
                    item.get("claim_id")
                    for item in adjudication["claims"]
                    if isinstance(item, dict)
                }
                != claims
            ):
                raise TransitionError(
                    "scientific rich adjudication differs from the validator verdict"
                )
        (
            multiplicity_registrations,
            multiplicity_batch_binding,
        ) = (
            self._validated_scientific_multiplicity_registrations(
                binding=binding,
                registrations=multiplicity_registrations,
                adjudication=adjudication,
                batch_record=batch_record,
                expected_batch_id=expected_batch_id,
                executable_id=executable_id,
                mission_id=mission_id,
            )
        )
        scientific = {
            "candidate_eligible": validated.candidate_eligible,
            "claims": sorted(claims),
            "evidence_depth": binding["evidence_depth"],
            "executed_evidence_modes": list(binding["evidence_modes"]),
            "executable_id": executable_id,
            "measurement_artifact_hashes": sorted(measurement_hashes),
            "result_manifest_hash": result_hash,
            "scientific_eligible": True,
            "verdict": validated.verdict,
            "validation_trace": validation_trace,
            "validator_id": binding["validator_id"],
            "validation_plan_hash": binding["validation_plan_hash"],
        }
        if adjudication is not None:
            scientific["adjudication"] = adjudication
        if multiplicity_registrations is not None:
            scientific["multiplicity_registrations"] = (
                multiplicity_registrations
            )
        if multiplicity_batch_binding is not None:
            scientific["multiplicity_batch_binding"] = (
                multiplicity_batch_binding
            )
        return scientific

    def _derive_external_dependency_evidence(
        self,
        *,
        job_id: str,
        job_hash: str,
        mission_id: str,
        binding: Mapping[str, Any],
        outcome: str,
        output_manifest: Mapping[str, Any],
        output_classes: Mapping[str, Any],
    ) -> dict[str, Any]:
        result_name = binding["result_manifest_output"]
        result_hash = output_manifest.get(result_name)
        if not isinstance(result_hash, str):
            raise TransitionError("external result manifest output is absent")
        try:
            value = parse_canonical(self.evidence.read_verified(result_hash))
        except ValueError as exc:
            raise TransitionError("external result manifest is not canonical") from exc
        required = {
            "contract_valid_next_action_found",
            "dependency_id",
            "indispensable_to_mission_terminal",
            "job_hash",
            "job_id",
            "measurement_artifact_hashes",
            "mission_id",
            "observed_external_state",
            "recovery_kind",
            "required_external_change",
            "safe_substitute_found",
            "schema",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise TransitionError("external result manifest schema is invalid")
        if (
            value["schema"] != "external_dependency_evidence.v1"
            or value["job_id"] != job_id
            or value["job_hash"] != job_hash
            or value["mission_id"] != mission_id
            or value["dependency_id"] != binding["dependency_id"]
            or value["recovery_kind"] != binding["recovery_kind"]
            or value["required_external_change"]
            != binding["required_external_change"]
            or type(value["safe_substitute_found"]) is not bool
            or type(value["indispensable_to_mission_terminal"]) is not bool
            or type(value["contract_valid_next_action_found"]) is not bool
        ):
            raise TransitionError("external result is bound to another recovery Job")
        measurement_hashes = value["measurement_artifact_hashes"]
        durable_hashes = {
            output_hash
            for output_name, output_hash in output_manifest.items()
            if output_classes.get(output_name) == "durable_evidence"
            and output_name != result_name
        }
        if (
            not isinstance(measurement_hashes, list)
            or not measurement_hashes
            or set(measurement_hashes) != durable_hashes
            or len(set(measurement_hashes)) != len(measurement_hashes)
        ):
            raise TransitionError("external measurements differ from Job outputs")
        _require_ascii("observed_external_state", value["observed_external_state"])
        validated, validation_trace = self._run_registered_validator(
            domain="external",
            job_id=job_id,
            job_hash=job_hash,
            mission_id=mission_id,
            evidence_subject={"kind": "Mission", "id": mission_id},
            binding=binding,
            result_manifest=value,
            output_manifest=output_manifest,
            output_classes=output_classes,
            result_name=result_name,
        )
        expected_verdict = {
            "success": "passed",
            "failed": "failed",
            "not_evaluable": "not_evaluable",
        }[outcome]
        expected_facts = {
            "blocked_mission_capability": binding["blocked_mission_capability"],
            "contract_valid_next_action_found": value[
                "contract_valid_next_action_found"
            ],
            "dependency_id": value["dependency_id"],
            "indispensable_to_mission_terminal": value[
                "indispensable_to_mission_terminal"
            ],
            "observed_external_state": value["observed_external_state"],
            "recovery_kind": value["recovery_kind"],
            "required_external_change": value["required_external_change"],
            "safe_substitute_found": value["safe_substitute_found"],
        }
        if (
            validated.verdict != expected_verdict
            or validated.claims
            or validated.artifact_roles
            or validated.scientific_eligible
            or validated.candidate_eligible
            or validated.release_eligible
            or set(validated.measurement_artifact_hashes) != durable_hashes
            or dict(validated.facts) != expected_facts
        ):
            raise TransitionError(
                "external state was not derived by the registered validator"
            )
        return {
            **expected_facts,
            "measurement_artifact_hashes": sorted(durable_hashes),
            "result_manifest_hash": result_hash,
            "validation_trace": validation_trace,
            "validator_id": binding["validator_id"],
            "validation_plan_hash": binding["validation_plan_hash"],
            "verdict": validated.verdict,
        }

    def _derive_component_parity_job_evidence(
        self,
        *,
        job_id: str,
        job_hash: str,
        mission_id: str,
        evidence_subject: Mapping[str, str],
        binding: Mapping[str, Any],
        output_manifest: Mapping[str, Any],
        output_classes: Mapping[str, Any],
    ) -> dict[str, Any]:
        result_name = binding["result_manifest_output"]
        result_hash = output_manifest.get(result_name)
        if not isinstance(result_hash, str):
            raise TransitionError("component parity result manifest is absent")
        try:
            value = parse_canonical(self.evidence.read_verified(result_hash))
        except ValueError as exc:
            raise TransitionError(
                "component parity result manifest is not canonical"
            ) from exc
        required = {
            "architecture_chassis_identity",
            "artifact_hashes",
            "canonical_component_id",
            "dimensions",
            "equivalent_component_id",
            "job_hash",
            "job_id",
            "mission_id",
            "portfolio_axis_identity",
            "portfolio_decision_id",
            "portfolio_snapshot_id",
            "schema",
            "verdict",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise TransitionError("component parity result schema is invalid")
        expected = {
            "architecture_chassis_identity": binding[
                "architecture_chassis_identity"
            ],
            "canonical_component_id": binding["canonical_component_id"],
            "dimensions": binding["dimensions"],
            "equivalent_component_id": binding["equivalent_component_id"],
            "job_hash": job_hash,
            "job_id": job_id,
            "mission_id": mission_id,
            "portfolio_axis_identity": binding["portfolio_axis_identity"],
            "portfolio_decision_id": binding["portfolio_decision_id"],
            "portfolio_snapshot_id": binding["portfolio_snapshot_id"],
            "schema": "component_parity_result.v2",
        }
        if any(value.get(name) != expected_value for name, expected_value in expected.items()):
            raise TransitionError(
                "component parity result differs from its Decision-bound Job"
            )
        if value["verdict"] not in {"equivalent", "not_equivalent"}:
            raise TransitionError("component parity verdict is not typed")
        measurement_hashes = {
            output_hash
            for output_name, output_hash in output_manifest.items()
            if output_classes.get(output_name) == "durable_evidence"
            and output_name != result_name
        }
        if (
            not measurement_hashes
            or value["artifact_hashes"] != sorted(measurement_hashes)
        ):
            raise TransitionError(
                "component parity result does not bind every measurement artifact"
            )
        validated, validation_trace = self._run_registered_validator(
            domain="scientific",
            job_id=job_id,
            job_hash=job_hash,
            mission_id=mission_id,
            evidence_subject=evidence_subject,
            binding=binding,
            result_manifest=value,
            output_manifest=output_manifest,
            output_classes=output_classes,
            result_name=result_name,
        )
        equivalent = value["verdict"] == "equivalent"
        expected_facts = {
            "canonical_component_id": binding["canonical_component_id"],
            "dimensions": binding["dimensions"],
            "equivalent": equivalent,
            "equivalent_component_id": binding["equivalent_component_id"],
        }
        expected_verdict = "passed" if equivalent else "failed"
        if (
            validated.verdict != expected_verdict
            or validated.claims
            or validated.scientific_eligible
            or validated.candidate_eligible
            or validated.release_eligible
            or set(validated.measurement_artifact_hashes) != measurement_hashes
            or dict(validated.facts) != expected_facts
        ):
            raise TransitionError(
                "component equivalence was not derived by the registered validator"
            )
        return {
            "canonical_component_id": binding["canonical_component_id"],
            "canonical_component_manifest": binding[
                "canonical_component_manifest"
            ],
            "dimensions": list(binding["dimensions"]),
            "equivalent": equivalent,
            "equivalent_component_id": binding["equivalent_component_id"],
            "equivalent_component_manifest": binding[
                "equivalent_component_manifest"
            ],
            "measurement_artifact_hashes": sorted(measurement_hashes),
            "result_manifest_hash": result_hash,
            "validation_plan_hash": binding["validation_plan_hash"],
            "validation_trace": validation_trace,
            "validator_id": binding["validator_id"],
            "verdict": validated.verdict,
        }

    @staticmethod
    def _job_completion_validation_request_hash(
        *,
        outcome: str,
        output_manifest: Mapping[str, Any],
        failure_manifest: Mapping[str, Any] | None,
    ) -> str:
        return canonical_digest(
            domain="job-completion-validation-request",
            payload={
                "failure": (
                    None
                    if failure_manifest is None
                    else dict(failure_manifest)
                ),
                "outcome": outcome,
                "outputs": dict(output_manifest),
            },
        )

    @staticmethod
    def _job_completion_validation_kinds(
        *,
        declared_spec: Mapping[str, Any],
        outcome: str,
        failure_manifest: Mapping[str, Any] | None,
    ) -> tuple[str, ...]:
        kinds: list[str] = []
        if outcome == "success":
            if declared_spec.get("runtime_binding") is not None:
                kinds.append("runtime")
            if declared_spec.get("source_binding") is not None:
                kinds.append("source")
            if declared_spec.get("scientific_binding") is not None:
                kinds.append("scientific")
            if declared_spec.get("component_parity_binding") is not None:
                kinds.append("component_parity")
        external_binding = declared_spec.get("external_dependency_binding")
        if isinstance(external_binding, Mapping) and (
            outcome == "success"
            or (
                failure_manifest is not None
                and failure_manifest.get("failure_kind")
                == "external_dependency"
            )
        ):
            kinds.append("external")
        return tuple(kinds)

    def _materialize_job_completion_validation_capability(
        self,
        *,
        outcome: str,
        output_manifest: Mapping[str, Any],
        failure_manifest: Mapping[str, Any] | None,
    ) -> _JobCompletionValidationCapability | None:
        """Freeze one Job head, release its lock, and validate exactly once."""

        request_hash = self._job_completion_validation_request_hash(
            outcome=outcome,
            output_manifest=output_manifest,
            failure_manifest=failure_manifest,
        )
        dispatches: dict[str, dict[str, Any]] = {}
        with self.open_stable_index() as (control, index):
            science = control.get("scientific")
            job = (
                None
                if not isinstance(science, Mapping)
                else science.get("active_job")
            )
            if not isinstance(job, Mapping) or job.get("status") != "running":
                # Let _commit preserve its normal idempotent-operation path.
                return None
            job_id = job.get("id")
            job_hash = job.get("hash")
            if type(job_id) is not str or type(job_hash) is not str:
                raise TransitionError("running Job identity is invalid")
            declaration = index.get("job-declared", job_id)
            if declaration is None or declaration.fingerprint != job_hash:
                raise TransitionError("current Job declaration is unavailable")
            declared_spec = declaration.payload.get("spec")
            if not isinstance(declared_spec, Mapping):
                raise TransitionError("current Job spec is unavailable")
            validation_kinds = self._job_completion_validation_kinds(
                declared_spec=declared_spec,
                outcome=outcome,
                failure_manifest=failure_manifest,
            )
            if not validation_kinds:
                return None
            if job.get("required_repair_resume_record_id") is not None:
                raise TransitionError(
                    "a repaired Job must re-enter its exact engine before completion"
                )
            expected_outputs = declared_spec.get("expected_outputs")
            output_classes = declared_spec.get("output_classes")
            if not isinstance(expected_outputs, list) or not isinstance(
                output_classes, Mapping
            ):
                raise TransitionError("current Job output declaration is invalid")
            _require_job_output_namespace(
                expected_outputs,
                output_classes=output_classes,
            )
            _require_job_output_namespace(
                tuple(output_manifest),
                output_classes=output_classes,
                name="Job completion outputs",
            )
            if outcome == "success" and set(output_manifest) != set(
                expected_outputs
            ):
                raise TransitionError(
                    "successful Job output manifest differs from declaration"
                )
            if outcome != "success" and not set(output_manifest).issubset(
                expected_outputs
            ):
                raise TransitionError("failed Job returned an undeclared output")
            if set(output_classes) != set(expected_outputs):
                raise TransitionError(
                    "Job output classes differ from expected outputs"
                )
            for output_name, output_hash in output_manifest.items():
                _require_ascii("output name", output_name)
                _require_digest("output hash", output_hash)
                if output_classes[output_name] == "durable_evidence":
                    self.evidence.verify(output_hash)
                else:
                    target = (self.root / output_name).resolve()
                    local_root = (self.root / "local").resolve()
                    if local_root not in target.parents:
                        raise TransitionError("Job local output escaped local/")
                    if outcome == "success" and not target.is_file():
                        raise TransitionError(
                            "successful Job local output is absent"
                        )
                    if (
                        target.is_file()
                        and sha256(target.read_bytes()).hexdigest()
                        != output_hash
                    ):
                        raise TransitionError("Job local output hash mismatch")
            start_record_id = job.get("start_record_id")
            start_record = (
                None
                if type(start_record_id) is not str
                else index.get("job-started", start_record_id)
            )
            if start_record is None:
                raise TransitionError(
                    "current Job start provenance is unavailable"
                )
            job_permit_id = start_record.payload.get("job_permit_id")
            if type(job_permit_id) is not str:
                raise TransitionError("current Job start permit is unavailable")
            current_execution = RunningJobExecution(
                job_id=job_id,
                job_hash=job_hash,
                start_record_id=str(start_record_id),
                job_permit_id=job_permit_id,
            )

            def completion_runtime_source(
                snapshot: LocalIndexView,
                source_id: str,
                *,
                freshness_required: bool = True,
            ) -> IndexRecord:
                try:
                    return self._require_runtime_source(
                        snapshot,
                        source_id,
                        freshness_required=freshness_required,
                    )
                except TransitionError as exc:
                    raise JobCompletionEntryAuthorityError(str(exc)) from exc

            runtime_binding = declared_spec.get("runtime_binding")
            try:
                require_repair_resume_entry(
                    index=index,
                    job=job,
                    job_id=job_id,
                    declared_spec=declared_spec,
                    current_execution=current_execution,
                    effective_implementation_resolver=(
                        self._effective_running_job_implementation
                    ),
                )
                provenance = require_completion_engine_entry(
                    control=control,
                    index=index,
                    job=job,
                    job_id=job_id,
                    declaration=declaration,
                    start_record=start_record,
                    start_record_id=str(start_record_id),
                    job_permit_id=job_permit_id,
                    current_execution=current_execution,
                    runtime_binding=runtime_binding,
                    outcome=outcome,
                    failure_manifest=failure_manifest,
                    engineering_disposition=None,
                    direction=control.get("next_action"),
                    engineering_fixture=self.engineering_fixture,
                    runtime_source_resolver=completion_runtime_source,
                )
            except JobCompletionEntryIntegrityError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except JobCompletionEntryAuthorityError as exc:
                raise TransitionError(str(exc)) from exc
            mission_id = declaration.payload.get("mission_id")
            evidence_subject = declared_spec.get("evidence_subject")
            if type(mission_id) is not str or not isinstance(
                evidence_subject, Mapping
            ):
                raise TransitionError("Job validation authority is unavailable")
            shared = {
                "job_hash": job_hash,
                "job_id": job_id,
                "output_classes": _copy(output_classes),
                "output_manifest": _copy(output_manifest),
            }
            if "runtime" in validation_kinds:
                candidate_context = declaration.payload.get(
                    "candidate_execution_context"
                )
                dispatches["runtime"] = {
                    **shared,
                    "binding": _copy(runtime_binding),
                    "provenance": _copy(provenance),
                    "source_lifecycle_coverage": (
                        candidate_context.get("source_lifecycle_coverage")
                        if isinstance(candidate_context, Mapping)
                        else None
                    ),
                }
            source_binding = declared_spec.get("source_binding")
            if "source" in validation_kinds:
                dispatches["source"] = {
                    **shared,
                    "binding": _copy(source_binding),
                    "evidence_subject": _copy(evidence_subject),
                    "mission_id": mission_id,
                }
            scientific_binding = declared_spec.get("scientific_binding")
            if "scientific" in validation_kinds:
                declared_batch_id = declaration.payload.get("batch_id")
                active_batch = science.get("active_batch")
                batch_record = (
                    None
                    if type(declared_batch_id) is not str
                    else index.get("batch-open", declared_batch_id)
                )
                if type(declared_batch_id) is str and (
                    not isinstance(active_batch, Mapping)
                    or active_batch.get("id") != declared_batch_id
                    or batch_record is None
                ):
                    raise TransitionError(
                        "scientific Job lost its exact active Batch before completion"
                    )
                executable_id = evidence_subject.get("id")
                if type(executable_id) is not str:
                    raise TransitionError(
                        "scientific Job lost its Executable authority"
                    )
                dispatches["scientific"] = {
                    **shared,
                    "batch_record": batch_record,
                    "binding": _copy(scientific_binding),
                    "executable_id": executable_id,
                    "expected_batch_id": (
                        declared_batch_id
                        if type(declared_batch_id) is str
                        else None
                    ),
                    "mission_id": mission_id,
                }
            component_binding = declared_spec.get(
                "component_parity_binding"
            )
            if "component_parity" in validation_kinds:
                dispatches["component_parity"] = {
                    **shared,
                    "binding": _copy(component_binding),
                    "evidence_subject": _copy(evidence_subject),
                    "mission_id": mission_id,
                }
            external_binding = declared_spec.get(
                "external_dependency_binding"
            )
            if "external" in validation_kinds:
                dispatches["external"] = {
                    **shared,
                    "binding": _copy(external_binding),
                    "mission_id": mission_id,
                    "outcome": outcome,
                }
            control_hash = str(control["control_hash"])

        manifests: dict[str, Mapping[str, Any]] = {}
        if "runtime" in dispatches:
            manifests["runtime"] = self._derive_runtime_job_evidence(
                **dispatches["runtime"]
            )
        if "source" in dispatches:
            manifests["source"] = self._derive_source_job_evidence(
                **dispatches["source"]
            )
        if "scientific" in dispatches:
            manifests["scientific"] = self._derive_scientific_job_evidence(
                **dispatches["scientific"]
            )
        if "component_parity" in dispatches:
            manifests["component_parity"] = (
                self._derive_component_parity_job_evidence(
                    **dispatches["component_parity"]
                )
            )
        if "external" in dispatches:
            manifests["external"] = (
                self._derive_external_dependency_evidence(
                    **dispatches["external"]
                )
            )
        sealed_manifests = {
            name: _copy(manifest) for name, manifest in manifests.items()
        }
        manifests_hash = canonical_digest(
            domain="job-completion-validation-manifests",
            payload=sealed_manifests,
        )
        return _JobCompletionValidationCapability(
            token=_JOB_COMPLETION_VALIDATION_CAPABILITY_TOKEN,
            control_hash=control_hash,
            job_id=job_id,
            job_hash=job_hash,
            request_hash=request_hash,
            manifests=sealed_manifests,
            manifests_hash=manifests_hash,
        )

    def _require_job_completion_validation_capability(
        self,
        *,
        capability: _JobCompletionValidationCapability | None,
        current: Mapping[str, Any],
        job: Mapping[str, Any],
        declared_spec: Mapping[str, Any],
        outcome: str,
        output_manifest: Mapping[str, Any],
        failure_manifest: Mapping[str, Any] | None,
    ) -> dict[str, dict[str, Any]]:
        validation_kinds = self._job_completion_validation_kinds(
            declared_spec=declared_spec,
            outcome=outcome,
            failure_manifest=failure_manifest,
        )
        if not validation_kinds:
            if capability is not None:
                raise TransitionError(
                    "Job completion carries unrelated validation authority"
                )
            return {}
        request_hash = self._job_completion_validation_request_hash(
            outcome=outcome,
            output_manifest=output_manifest,
            failure_manifest=failure_manifest,
        )
        if (
            capability is None
            or capability.token
            is not _JOB_COMPLETION_VALIDATION_CAPABILITY_TOKEN
            or capability.control_hash != current.get("control_hash")
            or capability.job_id != job.get("id")
            or capability.job_hash != job.get("hash")
            or capability.request_hash != request_hash
            or set(capability.manifests) != set(validation_kinds)
            or canonical_digest(
                domain="job-completion-validation-manifests",
                payload=dict(capability.manifests),
            )
            != capability.manifests_hash
        ):
            raise TransitionError(
                "Job completion validation capability is absent or stale"
            )
        return {
            name: _copy(manifest)
            for name, manifest in capability.manifests.items()
        }

    def complete_job(
        self,
        *,
        outcome: str,
        output_manifest: Mapping[str, Any],
        failure: Mapping[str, Any] | None = None,
        operation_id: str,
        evidence_blobs: Sequence[bytes] = (),
        crash_after: str | None = None,
    ) -> TransitionResult:
        try:
            failure_manifest = normalize_job_failure_manifest(
                outcome=outcome,
                failure=failure,
                evidence_verifier=self.evidence.verify,
                engineering_cause_builder=self._engineering_failure_cause,
            )
        except JobContractError as exc:
            raise TransitionError(str(exc)) from exc

        completion_validation_capability: (
            _JobCompletionValidationCapability | None
        ) = None
        if crash_after != "after_evidence":
            # Registered validators consume content-addressed outputs.  Make
            # caller-supplied blobs visible before the lock-free dispatch;
            # EvidenceStore finalization is deterministic and idempotent, so
            # _commit can retain its existing crash and evidence semantics.
            for blob in evidence_blobs:
                self.evidence.finalize(blob)
            completion_validation_capability = (
                self._materialize_job_completion_validation_capability(
                    outcome=outcome,
                    output_manifest=output_manifest,
                    failure_manifest=failure_manifest,
                )
            )

        def prepare(current: dict[str, Any] | None, _index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            job = science["active_job"]
            if not isinstance(job, dict) or job["status"] != "running":
                raise TransitionError("no running Job can complete")
            job_id = job["id"]
            declaration = _index.get("job-declared", job_id)
            if declaration is None or declaration.fingerprint != job["hash"]:
                raise TransitionError("current Job declaration is unavailable")
            declared_spec = declaration.payload.get("spec")
            if not isinstance(declared_spec, dict):
                raise TransitionError("current Job spec is unavailable")
            engineering_disposition: dict[str, Any] | None = None
            engineering_disposition_record_id: str | None = None
            engineering_disposition_trace_sha256: str | None = None
            required_engineering_disposition = job.get(
                "required_engineering_disposition_hash"
            )
            required_engineering_cause = job.get(
                "required_engineering_failure_cause_hash"
            )
            required_engineering_repair = job.get(
                "required_engineering_repair_id"
            )
            required_engineering_disposition_record = job.get(
                "required_engineering_disposition_record_id"
            )
            direction = body.get("next_action")
            if job.get("required_repair_resume_record_id") is not None:
                raise TransitionError(
                    "a repaired Job must re-enter its exact engine before completion"
                )
            if (
                failure_manifest is not None
                and failure_manifest["failure_kind"] == "engineering"
            ):
                disposition_hash = failure_manifest["repair_disposition_hash"]
                if (
                    "required_engineering_repair_id" not in job
                    or not isinstance(required_engineering_disposition, str)
                    or not isinstance(required_engineering_cause, str)
                    or not isinstance(
                        required_engineering_disposition_record, str
                    )
                    or failure_manifest["engineering_cause_hash"]
                    != required_engineering_cause
                    or not isinstance(direction, Mapping)
                    or set(direction)
                    != {
                        "disposition_hash",
                        "disposition_record_id",
                        "job_id",
                        "kind",
                    }
                    or direction.get("kind")
                    != "complete_engineering_failure"
                    or direction.get("job_id") != job_id
                    or direction.get("disposition_hash")
                    != disposition_hash
                    or direction.get("disposition_record_id")
                    != required_engineering_disposition_record
                    or required_engineering_disposition
                    != disposition_hash
                ):
                    raise TransitionError(
                        "engineering failure lacks its exact durable disposition"
                    )
                (
                    engineering_disposition,
                    engineering_disposition_trace_sha256,
                ) = (
                    self._recorded_engineering_failure_disposition(
                    _index,
                    job_id=job_id,
                    job_hash=job["hash"],
                    repair_id=required_engineering_repair,
                    cause_hash=required_engineering_cause,
                    disposition_hash=disposition_hash,
                    disposition_record_id=(
                        required_engineering_disposition_record
                    ),
                    )
                )
                engineering_disposition_record_id = (
                    required_engineering_disposition_record
                )
            elif (
                required_engineering_disposition is not None
                or required_engineering_cause is not None
                or required_engineering_disposition_record is not None
                or "required_engineering_repair_id" in job
                or (
                    isinstance(direction, Mapping)
                    and direction.get("kind") == "complete_engineering_failure"
                )
            ):
                raise TransitionError(
                    "unrecovered Repair must complete as its typed engineering failure"
                )
            expected_outputs = declared_spec.get("expected_outputs")
            output_classes = declared_spec.get("output_classes")
            if not isinstance(expected_outputs, list) or not isinstance(output_classes, dict):
                raise TransitionError("current Job output declaration is invalid")
            _require_job_output_namespace(
                expected_outputs,
                output_classes=output_classes,
            )
            _require_job_output_namespace(
                tuple(output_manifest),
                output_classes=output_classes,
                name="Job completion outputs",
            )
            runtime_binding = declared_spec.get("runtime_binding")
            runtime_manifest: dict[str, Any] | None = None
            scientific_binding = declared_spec.get("scientific_binding")
            scientific_manifest: dict[str, Any] | None = None
            source_binding = declared_spec.get("source_binding")
            source_manifest: dict[str, Any] | None = None
            external_binding = declared_spec.get("external_dependency_binding")
            external_manifest: dict[str, Any] | None = None
            holdout_binding = declared_spec.get("holdout_binding")
            component_parity_binding = declared_spec.get(
                "component_parity_binding"
            )
            component_parity_manifest: dict[str, Any] | None = None
            prevalidated_manifests = (
                self._require_job_completion_validation_capability(
                    capability=completion_validation_capability,
                    current=current,
                    job=job,
                    declared_spec=declared_spec,
                    outcome=outcome,
                    output_manifest=output_manifest,
                    failure_manifest=failure_manifest,
                )
            )
            if (
                failure_manifest is not None
                and failure_manifest["failure_kind"]
                == "runtime_source_ineligibility"
                and runtime_binding is None
            ):
                raise TransitionError(
                    "runtime source ineligibility requires a runtime-bound Job"
                )
            active_holdout = science.get("active_holdout_evaluation")
            pre_reveal_holdout_engineering_gap = False
            if holdout_binding is not None:
                holdout_id = (
                    holdout_binding.get("holdout_id")
                    if isinstance(holdout_binding, Mapping)
                    else None
                )
                reveal_head = (
                    None
                    if not isinstance(holdout_id, str)
                    else _index.event_head(f"holdout-reveal:{holdout_id}")
                )
                reveal = (
                    None
                    if reveal_head is None
                    else _index.get(
                        reveal_head.record_kind,
                        reveal_head.record_id,
                    )
                )
                exact_revealed_holdout = (
                    isinstance(active_holdout, dict)
                    and active_holdout.get("status")
                    == "revealed_pending_evaluation"
                    and active_holdout.get("job_id") == job_id
                    and active_holdout.get("holdout_id") == holdout_id
                    and active_holdout.get("executable_id")
                    == declared_spec.get("evidence_subject", {}).get("id")
                    and reveal_head is not None
                    and reveal_head.sequence == 1
                    and reveal is not None
                    and reveal.kind == "holdout-reveal"
                    and reveal.status == "revealed_once"
                    and reveal.payload.get("job_id") == job_id
                )
                pre_reveal_holdout_engineering_gap = (
                    engineering_disposition is not None
                    and active_holdout is None
                    and reveal_head is None
                )
                if not (
                    exact_revealed_holdout
                    or pre_reveal_holdout_engineering_gap
                ):
                    raise TransitionError(
                        "holdout-bound Job cannot complete before its exact reveal"
                    )
            start_record_id = job.get("start_record_id")
            start_record = (
                None
                if not isinstance(start_record_id, str)
                else _index.get("job-started", start_record_id)
            )
            if start_record is None:
                raise TransitionError("current Job start provenance is unavailable")
            job_permit_id = start_record.payload.get("job_permit_id")
            if not isinstance(job_permit_id, str):
                raise TransitionError("current Job start permit is unavailable")
            current_execution = RunningJobExecution(
                job_id=job_id,
                job_hash=job["hash"],
                start_record_id=start_record_id,
                job_permit_id=job_permit_id,
            )
            repair_resume_record_id = job.get(
                "last_repair_resume_record_id"
            )

            def completion_runtime_source(
                index: LocalIndex,
                source_id: str,
                *,
                freshness_required: bool = True,
            ) -> IndexRecord:
                try:
                    return self._require_runtime_source(
                        index,
                        source_id,
                        freshness_required=freshness_required,
                    )
                except TransitionError as exc:
                    raise JobCompletionEntryAuthorityError(str(exc)) from exc

            try:
                require_repair_resume_entry(
                    index=_index,
                    job=job,
                    job_id=job_id,
                    declared_spec=declared_spec,
                    current_execution=current_execution,
                    effective_implementation_resolver=(
                        self._effective_running_job_implementation
                    ),
                )
                provenance = require_completion_engine_entry(
                    control=body,
                    index=_index,
                    job=job,
                    job_id=job_id,
                    declaration=declaration,
                    start_record=start_record,
                    start_record_id=start_record_id,
                    job_permit_id=job_permit_id,
                    current_execution=current_execution,
                    runtime_binding=runtime_binding,
                    outcome=outcome,
                    failure_manifest=failure_manifest,
                    engineering_disposition=engineering_disposition,
                    direction=direction,
                    engineering_fixture=self.engineering_fixture,
                    runtime_source_resolver=completion_runtime_source,
                )
            except JobCompletionEntryIntegrityError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except JobCompletionEntryAuthorityError as exc:
                raise TransitionError(str(exc)) from exc
            if outcome == "success" and set(output_manifest) != set(expected_outputs):
                raise TransitionError("successful Job output manifest differs from declaration")
            if outcome != "success" and not set(output_manifest).issubset(expected_outputs):
                raise TransitionError("failed Job returned an undeclared output")
            if set(output_classes) != set(expected_outputs):
                raise TransitionError("Job output classes differ from expected outputs")
            for output_name, output_hash in output_manifest.items():
                _require_ascii("output name", output_name)
                _require_digest("output hash", output_hash)
                if output_classes[output_name] == "durable_evidence":
                    self.evidence.verify(output_hash)
                else:
                    target = (self.root / output_name).resolve()
                    local_root = (self.root / "local").resolve()
                    if local_root not in target.parents:
                        raise TransitionError("Job local output escaped local/")
                    if outcome == "success" and not target.is_file():
                        raise TransitionError("successful Job local output is absent")
                    if target.is_file() and sha256(target.read_bytes()).hexdigest() != output_hash:
                        raise TransitionError("Job local output hash mismatch")
            if runtime_binding is not None and outcome == "success":
                runtime_manifest = _copy(prevalidated_manifests["runtime"])
            if source_binding is not None and outcome == "success":
                source_manifest = _copy(prevalidated_manifests["source"])
            if scientific_binding is not None and outcome == "success":
                if set(output_manifest) != set(expected_outputs):
                    raise TransitionError(
                        "scientific evidence disposition requires every declared output"
                    )
                declared_batch_id = declaration.payload.get("batch_id")
                active_batch = science.get("active_batch")
                scientific_batch_record = (
                    None
                    if not isinstance(declared_batch_id, str)
                    else _index.get("batch-open", declared_batch_id)
                )
                if (
                    isinstance(declared_batch_id, str)
                    and (
                        not isinstance(active_batch, Mapping)
                        or active_batch.get("id") != declared_batch_id
                        or scientific_batch_record is None
                    )
                ):
                    raise TransitionError(
                        "scientific Job lost its exact active Batch before completion"
                    )
                scientific_manifest = _copy(
                    prevalidated_manifests["scientific"]
                )
            if component_parity_binding is not None and outcome == "success":
                if set(output_manifest) != set(expected_outputs):
                    raise TransitionError(
                        "component parity disposition requires every declared output"
                    )
                component_parity_manifest = _copy(
                    prevalidated_manifests["component_parity"]
                )
            if isinstance(external_binding, dict) and (
                outcome == "success"
                or (
                    failure_manifest is not None
                    and failure_manifest["failure_kind"] == "external_dependency"
                )
            ):
                if set(output_manifest) != set(expected_outputs):
                    raise TransitionError(
                        "external dependency disposition requires every declared output"
                    )
                external_manifest = _copy(
                    prevalidated_manifests["external"]
                )
            if (
                failure_manifest is not None
                and failure_manifest["resume_action"] != declared_spec["resume_action"]
            ):
                raise TransitionError("failure resume action differs from the Job declaration")
            if failure_manifest is not None and failure_manifest["failure_kind"] == "external_dependency":
                if (
                    not isinstance(external_binding, dict)
                    or failure_manifest.get("external_dependency_id")
                    != external_binding["dependency_id"]
                    or failure_manifest["resume_action"]
                    != external_binding["exact_resume_action"]
                ):
                    raise TransitionError(
                        "external failure differs from its preregistered dependency"
                    )
            if (
                isinstance(external_binding, Mapping)
                and isinstance(engineering_disposition, Mapping)
                and engineering_disposition.get("successor_scope")
                is not None
            ):
                raise TransitionError(
                    "external engineering failure cannot authorize scientific successor work"
                )
            completion_identity_payload = {
                "candidate_execution_context": declaration.payload.get(
                    "candidate_execution_context"
                ),
                "job_id": job_id,
                "outcome": outcome,
                "outputs": dict(output_manifest),
                "failure_signature": (
                    None
                    if failure_manifest is None
                    else failure_manifest["failure_signature"]
                ),
                "external": external_manifest,
                "runtime": runtime_manifest,
                "repair_resume_record_id": repair_resume_record_id,
                "scientific": scientific_manifest,
                "source": source_manifest,
            }
            if engineering_disposition is not None:
                completion_identity_payload[
                    "engineering_disposition_record_id"
                ] = engineering_disposition_record_id
                completion_identity_payload[
                    "engineering_disposition_trace_sha256"
                ] = engineering_disposition_trace_sha256
            if component_parity_manifest is not None:
                completion_identity_payload["component_parity"] = (
                    component_parity_manifest
                )
            record_id = canonical_digest(
                domain="job-completion",
                payload=completion_identity_payload,
            )
            completion_payload = {
                "candidate_execution_context": declaration.payload.get(
                    "candidate_execution_context"
                ),
                "job_id": job_id,
                "outputs": dict(output_manifest),
                "output_classes": dict(output_classes),
                "failure": failure_manifest,
                "engineering_disposition": engineering_disposition,
                "external": external_manifest,
                "start_record_id": start_record_id,
                "runtime": runtime_manifest,
                "repair_resume_record_id": repair_resume_record_id,
                "scientific": scientific_manifest,
                "source": source_manifest,
            }
            if component_parity_manifest is not None:
                completion_payload["component_parity"] = component_parity_manifest
            if engineering_disposition is not None:
                completion_payload["engineering_disposition_record_id"] = (
                    engineering_disposition_record_id
                )
                completion_payload[
                    "engineering_disposition_trace_sha256"
                ] = engineering_disposition_trace_sha256
            record = _record(
                kind="job-completed",
                record_id=record_id,
                subject=f"Job:{job_id}",
                status=outcome,
                fingerprint=job["hash"],
                payload=completion_payload,
                event_stream=f"job-attempt:{declaration.payload['work_fingerprint']}",
                event_sequence=(
                    _index.event_head(
                        f"job-attempt:{declaration.payload['work_fingerprint']}"
                    ).sequence
                    + 1
                ),
            )
            try:
                retry_family_completion = (
                    build_retry_family_completion_record(
                        index=_index,
                        declaration=declaration,
                        outcome=outcome,
                        completion_record_id=record_id,
                    )
                )
            except JobRetryAdmissionIntegrityError as exc:
                raise RecoveryRequired(str(exc)) from exc
            science["active_job"] = None
            self._drop_authorization(body, SubjectKind.JOB, job_id)
            try:
                projection = project_job_completion(
                    index=_index,
                    declaration=declaration,
                    completion=record,
                    active_holdout=active_holdout,
                    pre_reveal_holdout_engineering_gap=(
                        pre_reveal_holdout_engineering_gap
                    ),
                    engineering_fixture=self.engineering_fixture,
                    record_builder=_record,
                )
            except JobCompletionProjectionIntegrityError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except JobCompletionProjectionError as exc:
                raise TransitionError(str(exc)) from exc
            body["next_action"] = dict(projection.next_action)
            science["active_holdout_evaluation"] = (
                None
                if projection.active_holdout_evaluation is None
                else dict(projection.active_holdout_evaluation)
            )
            records = [
                record,
                *(
                    [retry_family_completion]
                    if retry_family_completion is not None
                    else []
                ),
                *projection.supplemental_records,
            ]
            return body, records, {
                "job_id": job_id,
                "outcome": outcome,
                "scientific_verdict": (
                    None
                    if scientific_manifest is None
                    else scientific_manifest["verdict"]
                ),
                "completion_record_id": record_id,
                "failure_signature": (
                    None
                    if failure_manifest is None
                    else failure_manifest.get("failure_signature")
                ),
                "output_classes": dict(output_classes),
            }

        result = self._commit(
            event_kind="job_completed",
            operation_id=operation_id,
            subject="Job:active",
            payload={
                "outcome": outcome,
                "output_manifest": dict(output_manifest),
                "failure": failure_manifest,
            },
            prepare=prepare,
            evidence_blobs=evidence_blobs,
            crash_after=crash_after,
        )
        transient_root = (self.root / "local" / "jobs").resolve()
        for output_name, output_class in result.result["output_classes"].items():
            if output_class != "transient":
                continue
            target = (self.root / output_name).resolve()
            if transient_root not in target.parents:
                raise TransitionError("transient cleanup escaped local/jobs")
            if target.is_file():
                target.unlink()
            elif target.exists():
                raise TransitionError("transient output path is not a file")
        return result

    def judge_job_evidence(
        self,
        *,
        completion_record_id: str,
        disposition: str,
        negative_memory_id: str | None = None,
        operation_id: str,
    ) -> TransitionResult:
        """Consume a completed Job judgement before more Batch work."""

        from axiom_rift.operations.architecture_review_direction import (
            ARCHITECTURE_CONTINUATION_ACTION_FIELDS,
            ArchitectureReviewDirectionError,
            constraint_from_action,
            require_review_binding,
        )

        _require_digest("completion_record_id", completion_record_id)
        if disposition not in {
            "accept_component_parity",
            "continue_batch",
            "reject_component_parity",
            "stop_batch",
        }:
            raise TransitionError("Job evidence disposition is not typed")
        if negative_memory_id is not None:
            if not negative_memory_id.startswith("negative-memory:"):
                raise TransitionError("negative_memory_id is invalid")
            _require_digest(
                "negative_memory_id",
                negative_memory_id.removeprefix("negative-memory:"),
            )

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            if science["active_job"] is not None or science["active_repair"] is not None:
                raise TransitionError("Job judgement requires a stable completion")
            next_action = body.get("next_action")
            completion = index.get("job-completed", completion_record_id)
            if (
                completion is None
                or next_action
                != {
                    "completion_record_id": completion_record_id,
                    "job_id": completion.payload.get("job_id"),
                    "kind": "judge_job_evidence",
                }
            ):
                raise TransitionError("Job judgement is not the exact next action")
            job_id = completion.payload["job_id"]
            declaration = index.get("job-declared", job_id)
            if (
                declaration is None
                or declaration.payload.get("mission_id")
                != science["active_mission"]
            ):
                raise TransitionError("Job judgement lacks Mission provenance")
            scientific = completion.payload.get("scientific")
            component_parity = completion.payload.get("component_parity")
            needs_negative_memory = (
                isinstance(scientific, dict)
                and scientific.get("verdict") == "failed"
                and scientific.get("scientific_eligible") is True
            )
            if needs_negative_memory:
                memory = (
                    None
                    if negative_memory_id is None
                    else index.get("negative-memory", negative_memory_id)
                )
                if (
                    memory is None
                    or completion_record_id
                    not in memory.payload.get("evidence_references", [])
                    or memory.subject
                    != f"Executable:{scientific.get('executable_id')}"
                ):
                    raise TransitionError(
                        "scientific falsification requires its exact negative memory"
                    )
            elif negative_memory_id is not None:
                raise TransitionError("Job judgement carries unrelated negative memory")
            parity_binding = declaration.payload.get("spec", {}).get(
                "component_parity_binding"
            )
            parity_disposition = disposition in {
                "accept_component_parity",
                "reject_component_parity",
            }
            parity_member_records: list[IndexRecord] = []
            parity_trigger_records: list[IndexRecord] = []
            if parity_disposition:
                if not isinstance(parity_binding, dict):
                    raise TransitionError(
                        "component parity disposition requires its typed Job binding"
                    )
                if disposition == "accept_component_parity" and (
                    completion.status != "success"
                    or not isinstance(component_parity, dict)
                    or component_parity.get("equivalent") is not True
                    or component_parity.get("verdict") != "passed"
                ):
                    raise TransitionError(
                        "Writer cannot accept component parity without validator equivalence"
                    )
                decision = self._active_portfolio_decision(
                    index,
                    parity_binding["portfolio_decision_id"],
                )
                if decision is None:
                    raise TransitionError(
                        "component parity disposition lost its Portfolio Decision"
                    )
                options = {
                    option["option_id"]: option
                    for option in decision.payload.get("options", [])
                    if isinstance(option, dict)
                }
                chosen = options.get(decision.payload.get("chosen_option_id"))
                if not isinstance(chosen, dict):
                    raise TransitionError(
                        "component parity Portfolio Decision is malformed"
                    )
                decision_architecture = decision.payload.get(
                    "architecture_chassis"
                )
                if not isinstance(decision_architecture, dict):
                    raise TransitionError(
                        "component parity Decision lacks its architecture chassis"
                    )
                decision_baseline = decision.payload.get(
                    "baseline_executable"
                )
                raw_post_holdout_id = decision.payload.get(
                    "post_holdout_development_id"
                )
                if raw_post_holdout_id is not None and (
                    not isinstance(decision_baseline, Mapping)
                    or not isinstance(
                        decision_baseline.get("data_contract"),
                        str,
                    )
                    or not isinstance(
                        decision_baseline.get("split_contract"),
                        str,
                    )
                ):
                    raise RecoveryRequired(
                        "component parity post-holdout baseline is malformed"
                    )
                post_holdout_development_id, _ = (
                    self._require_post_holdout_decision_binding(
                        index,
                        science=science,
                        decision=decision,
                        data_contract=(
                            decision_baseline.get("data_contract")
                            if isinstance(raw_post_holdout_id, str)
                            and isinstance(decision_baseline, Mapping)
                            else None
                        ),
                        split_contract=(
                            decision_baseline.get("split_contract")
                            if isinstance(raw_post_holdout_id, str)
                            and isinstance(decision_baseline, Mapping)
                            else None
                        ),
                    )
                )
                extra_equivalences: tuple[Mapping[str, Any], ...] = ()
                if disposition == "accept_component_parity":
                    assert isinstance(component_parity, dict)
                    extra_equivalences = (
                        {
                            "canonical_component_id": component_parity.get(
                                "canonical_component_id"
                            ),
                            "canonical_component_manifest": component_parity.get(
                                "canonical_component_manifest"
                            ),
                            "completion_record_id": completion_record_id,
                            "dimensions": component_parity.get("dimensions"),
                            "equivalent_component_id": component_parity.get(
                                "equivalent_component_id"
                            ),
                            "equivalent_component_manifest": component_parity.get(
                                "equivalent_component_manifest"
                            ),
                            "parity_manifest_hash": component_parity.get(
                                "result_manifest_hash"
                            ),
                            "schema": "component_parity_evidence.v1",
                        },
                    )
                    parity_member_records = self._component_parity_member_records(
                        equivalence=extra_equivalences[0],
                        mission_id=science["active_mission"],
                        portfolio_decision_id=decision.record_id,
                    )
                resolved_family = self._resolved_architecture_family(
                    index=index,
                    architecture_payload=decision_architecture,
                    extra_equivalences=extra_equivalences,
                )
                execute_action = {
                    "action": chosen["action"],
                    "architecture_chassis_identity": parity_binding[
                        "architecture_chassis_identity"
                    ],
                    "baseline_executable_id": decision.payload[
                        "baseline_executable_id"
                    ],
                    "decision_id": decision.record_id,
                    "kind": "execute_portfolio_decision",
                    "portfolio_snapshot_id": parity_binding[
                        "portfolio_snapshot_id"
                    ],
                    "resolved_architecture_family": resolved_family,
                    "target_axis_identity": parity_binding[
                        "portfolio_axis_identity"
                    ],
                    "target_id": chosen["target_id"],
                }
                if isinstance(post_holdout_development_id, str):
                    execute_action["post_holdout_development_id"] = (
                        post_holdout_development_id
                    )
                try:
                    parity_diagnosis_authority = (
                        DiagnosisAuthorityContext.from_mapping(
                            decision.payload
                        )
                    )
                    parity_diagnosis_authority.require_effective(
                        index,
                        mission_id=science["active_mission"],
                    )
                except DiagnosisAuthorityContextError as exc:
                    raise RecoveryRequired(str(exc)) from exc
                execute_action.update(
                    parity_diagnosis_authority.to_action_fields()
                )
                reroute_action: dict[str, Any] | None = None
                if disposition == "accept_component_parity":
                    review_id = decision.payload.get("architecture_review_id")
                    review = (
                        None
                        if not isinstance(review_id, str)
                        else index.get("architecture-review", review_id)
                    )
                    if isinstance(review_id, str) and review is None:
                        raise RecoveryRequired(
                            "component parity lost its architecture review"
                        )
                    if review is not None and review.payload.get(
                        "conclusion"
                    ) == "bounded_same_architecture":
                        stored_constraints = decision.payload.get(
                            "scheduler_constraints"
                        )
                        if not isinstance(stored_constraints, dict):
                            raise RecoveryRequired(
                                "bounded parity Decision lost its scheduler constraints"
                            )
                        candidate_action = {
                            "kind": "portfolio_decision",
                            "portfolio_snapshot_id": parity_binding[
                                "portfolio_snapshot_id"
                            ],
                            **{
                                name: stored_constraints[name]
                                for name in (
                                    *ARCHITECTURE_CONTINUATION_ACTION_FIELDS,
                                    "pending_replay_obligation_ids",
                                    "required_replay_priority",
                                )
                                if name in stored_constraints
                            },
                        }
                        try:
                            continuation = constraint_from_action(candidate_action)
                        except ArchitectureReviewDirectionError as exc:
                            raise RecoveryRequired(str(exc)) from exc
                        trigger = (
                            None
                            if continuation is None
                            else index.get(
                                "architecture-review-trigger",
                                continuation.trigger_record_id,
                            )
                        )
                        if continuation is None or trigger is None:
                            raise RecoveryRequired(
                                "bounded parity Decision lost its review trigger"
                            )
                        try:
                            require_review_binding(
                                continuation,
                                review_record_id=review.record_id,
                                review_payload=review.payload,
                                trigger_payload=trigger.payload,
                            )
                        except ArchitectureReviewDirectionError as exc:
                            raise RecoveryRequired(str(exc)) from exc
                        reviewed_family = self._review_resolved_architecture_family(
                            index=index,
                            review=review,
                            extra_equivalences=extra_equivalences,
                        )
                        if (
                            resolved_family
                            != continuation.required_architecture_family
                            or reviewed_family
                            != continuation.required_architecture_family
                        ):
                            reroute_action = candidate_action
                    elif review is not None and review.payload.get(
                        "conclusion"
                    ) == "rotate_architecture":
                        reviewed_family = self._review_resolved_architecture_family(
                            index=index,
                            review=review,
                            extra_equivalences=extra_equivalences,
                        )
                        if resolved_family == reviewed_family:
                            reroute_action = {
                                "architecture_review_id": review.record_id,
                                "excluded_architecture_family": reviewed_family,
                                "kind": "portfolio_decision",
                                "portfolio_snapshot_id": parity_binding[
                                    "portfolio_snapshot_id"
                                ],
                            }
                    diagnosis_id = decision.payload.get("study_diagnosis_id")
                    diagnosis = None
                    if isinstance(diagnosis_id, str):
                        from axiom_rift.operations.effective_study_diagnosis import (
                            EffectiveStudyDiagnosisError,
                            effective_study_diagnosis,
                        )

                        try:
                            diagnosis = effective_study_diagnosis(
                                index,
                                diagnosis_id,
                            )
                        except EffectiveStudyDiagnosisError as exc:
                            raise RecoveryRequired(str(exc)) from exc
                    if reroute_action is None and diagnosis is not None:
                        snapshot = index.get(
                            "portfolio-snapshot",
                            parity_binding["portfolio_snapshot_id"],
                        )
                        if snapshot is None:
                            raise RecoveryRequired(
                                "component parity lost its Portfolio snapshot"
                            )
                        axes = {
                            axis["axis_id"]: axis
                            for axis in snapshot.payload.get("axes", [])
                            if isinstance(axis, dict)
                            and isinstance(axis.get("axis_id"), str)
                        }
                        target_axis = axes.get(chosen["target_id"])
                        source_axis = axes.get(
                            diagnosis.payload.get("portfolio_axis_id")
                        )
                        if target_axis is None or source_axis is None:
                            raise RecoveryRequired(
                                "component parity diagnosis axes are unavailable"
                            )
                        allowed_actions = set(
                            diagnosis.payload.get("allowed_actions", [])
                        )
                        allowed_layers = set(
                            diagnosis.payload.get("allowed_research_layers", [])
                        )
                        chosen_action = chosen["action"]
                        branch_match = (
                            chosen_action not in {"preserve", "prune"}
                            and chosen_action in allowed_actions
                            and (
                                target_axis["primary_research_layer"]
                                in allowed_layers
                                or chosen_action == "new_mechanism"
                            )
                        )
                        source_study_id = diagnosis.payload.get("study_id")
                        source_study = (
                            None
                            if not isinstance(source_study_id, str)
                            else index.get("study-open", source_study_id)
                        )
                        if source_study is None:
                            raise RecoveryRequired(
                                "component parity diagnosis Study is unavailable"
                            )
                        controlled = source_study.payload.get(
                            "controlled_chassis"
                        )
                        source_architecture = (
                            None
                            if not isinstance(controlled, dict)
                            else controlled.get("architecture")
                        )
                        source_family = (
                            self._resolved_architecture_family(
                                index=index,
                                architecture_payload=source_architecture,
                                extra_equivalences=extra_equivalences,
                            )
                            if isinstance(source_architecture, dict)
                            else source_study.payload.get(
                                "system_architecture_family"
                            )
                        )
                        forest_diversion = (
                            chosen["target_id"]
                            != diagnosis.payload.get("portfolio_axis_id")
                            and chosen_action
                            in {
                                "complementary_sleeve",
                                "contrast",
                                "recombine",
                                "rotate",
                                "synthesize",
                            }
                            and (
                                target_axis["primary_research_layer"]
                                != source_axis["primary_research_layer"]
                                or resolved_family != source_family
                            )
                        )
                        if not (branch_match or forest_diversion):
                            reroute_action = {
                                "kind": "portfolio_decision",
                                "portfolio_snapshot_id": parity_binding[
                                    "portfolio_snapshot_id"
                                ],
                                "study_diagnosis_id": diagnosis.record_id,
                            }
                    trigger = self._pending_architecture_review_trigger(
                        index=index,
                        mission_id=science["active_mission"],
                        portfolio_snapshot_id=parity_binding[
                            "portfolio_snapshot_id"
                        ],
                        architecture_family=resolved_family,
                        extra_equivalences=extra_equivalences,
                    )
                    if trigger is not None:
                        parity_trigger_records = [trigger]
                        reroute_action = {
                            "kind": "review_architecture",
                            "trigger_record_id": trigger.record_id,
                        }
                if (
                    reroute_action is not None
                    and reroute_action.get("kind") == "portfolio_decision"
                ):
                    reroute_action.update(
                        parity_diagnosis_authority.to_action_fields()
                    )
                if (
                    isinstance(post_holdout_development_id, str)
                    and reroute_action is not None
                    and reroute_action.get("kind")
                    in {"portfolio_decision", "review_architecture"}
                ):
                    reroute_action["post_holdout_development_id"] = (
                        post_holdout_development_id
                    )
                body["next_action"] = (
                    execute_action if reroute_action is None else reroute_action
                )
            batch = science.get("active_batch")
            declared_batch_id = declaration.payload.get("batch_id")
            if not parity_disposition:
                if (
                    not isinstance(batch, dict)
                    or declared_batch_id != batch.get("id")
                ):
                    raise TransitionError("Job judgement is outside the active Batch")
                if disposition == "stop_batch" and not self.engineering_fixture:
                    study_id = science.get("active_study")
                    if not isinstance(study_id, str):
                        raise TransitionError(
                            "Real Batch stop requires its active Study"
                        )
                    self._study_kpi_from_completion(
                        index=index,
                        study_id=study_id,
                        completion_record_id=completion_record_id,
                        require_stop_decision=False,
                    )
                body["next_action"] = (
                    {"kind": "declare_job", "batch_id": batch["id"]}
                    if disposition == "continue_batch"
                    else {"kind": "dispose_batch", "batch_id": batch["id"]}
                )
            record_id = canonical_digest(
                domain="job-evidence-decision",
                payload={
                    "completion_record_id": completion_record_id,
                    "disposition": disposition,
                    "negative_memory_id": negative_memory_id,
                },
            )
            record = _record(
                kind="job-evidence-decision",
                record_id=record_id,
                subject=f"Job:{job_id}",
                status=disposition,
                fingerprint=completion.fingerprint,
                payload={
                    "completion_record_id": completion_record_id,
                    "negative_memory_id": negative_memory_id,
                },
            )
            return body, [
                record,
                *parity_member_records,
                *parity_trigger_records,
            ], {
                "disposition": disposition,
                "job_id": job_id,
            }

        return self._commit(
            event_kind="job_evidence_judged",
            operation_id=operation_id,
            subject="Job:completed",
            payload={
                "completion_record_id": completion_record_id,
                "disposition": disposition,
                "negative_memory_id": negative_memory_id,
            },
            prepare=prepare,
        )

    def judge_external_dependency_evidence(
        self,
        *,
        completion_record_id: str,
        operation_id: str,
    ) -> TransitionResult:
        """Consume one Mission-scoped external recovery result exactly once."""

        _require_digest("completion_record_id", completion_record_id)

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            if science.get("active_job") is not None or science.get(
                "active_repair"
            ) is not None:
                raise TransitionError(
                    "external Job judgement requires a stable completion"
                )
            completion = index.get("job-completed", completion_record_id)
            next_action = body.get("next_action")
            if (
                completion is None
                or next_action
                != {
                    "completion_record_id": completion_record_id,
                    "job_id": completion.payload.get("job_id"),
                    "kind": "judge_external_dependency_evidence",
                }
            ):
                raise TransitionError(
                    "external Job judgement is not the exact next action"
                )
            job_id = completion.payload.get("job_id")
            declaration = (
                None
                if not isinstance(job_id, str)
                else index.get("job-declared", job_id)
            )
            binding = (
                None
                if declaration is None
                else declaration.payload.get("spec", {}).get(
                    "external_dependency_binding"
                )
            )
            if (
                declaration is None
                or declaration.payload.get("mission_id")
                != science.get("active_mission")
                or not isinstance(binding, dict)
            ):
                raise TransitionError(
                    "external Job judgement lacks exact Mission provenance"
                )
            try:
                plan = external_plan_from_binding(binding)
                path = plan.path(binding["recovery_path_id"])
            except ExternalDependencyContractError as exc:
                raise TransitionError(str(exc)) from exc
            plan_record = index.get("external-recovery-plan", plan.identity)
            if (
                plan_record is None
                or plan_record.status != "active"
                or plan_record.subject != f"Mission:{science['active_mission']}"
                or plan_record.payload != plan.to_identity_payload()
            ):
                raise RecoveryRequired(
                    "external Job judgement lost its frozen recovery plan"
                )
            attempt_id = canonical_digest(
                domain="external-dependency-attempt",
                payload={
                    "completion_record_id": completion_record_id,
                    "dependency_id": plan.condition.dependency_id,
                    "recovery_path_id": path.recovery_path_id,
                },
            )
            attempt = index.get("external-dependency-attempt", attempt_id)
            external = completion.payload.get("external")
            engineering = completion.payload.get("engineering_disposition")
            failure = completion.payload.get("failure")
            if (
                external is None
                and completion.status == "failed"
                and attempt is not None
                and attempt.status == "local_failure"
                and isinstance(engineering, Mapping)
                and engineering.get("schema")
                == "engineering_failure_disposition.v1"
                and isinstance(failure, Mapping)
                and failure.get("failure_kind") == "engineering"
            ):
                body["next_action"] = (
                    plan.condition.resume_action.to_next_action()
                )
                gap_payload = {
                    "completion_record_id": completion_record_id,
                    "disposition": "restore_local_engineering_failure",
                    "recovery_path_id": path.recovery_path_id,
                    "recovery_plan_id": plan.identity,
                    "scientific_failure_delta": 0,
                    "scientific_trial_delta": 0,
                }
                gap_id = canonical_digest(
                    domain="external-dependency-operational-gap",
                    payload=gap_payload,
                )
                gap_stream = (
                    f"external-operational-gap:{plan.identity}:"
                    f"{path.recovery_path_id}"
                )
                gap_head = index.event_head(gap_stream)
                gap = _record(
                    kind="external-dependency-operational-gap",
                    record_id=gap_id,
                    subject=f"Job:{job_id}",
                    status="engineering_gap",
                    fingerprint=completion.fingerprint,
                    payload=gap_payload,
                    event_stream=gap_stream,
                    event_sequence=(
                        1 if gap_head is None else gap_head.sequence + 1
                    ),
                )
                return body, [gap], {
                    "completion_record_id": completion_record_id,
                    "disposition": "restore_local_engineering_failure",
                    "recovery_plan_id": plan.identity,
                    "verdict": "engineering_gap",
                }
            if (
                attempt is None
                or attempt.payload.get("completion_record_id")
                != completion_record_id
                or not isinstance(external, dict)
            ):
                raise TransitionError(
                    "external Job judgement lacks its validator-derived attempt"
                )
            verdict = external.get("verdict")
            expected = {
                "failed": ("failed", "external_unavailable"),
                "not_evaluable": ("not_evaluable", "external_unresolved"),
                "passed": ("success", "available"),
            }
            if verdict not in expected or (
                completion.status,
                attempt.status,
            ) != expected[verdict]:
                raise TransitionError(
                    "external Job outcome differs from its validator verdict"
                )
            stream = f"external-recovery:{plan.identity}"
            decision_head = index.event_head(stream)
            decision_count = 0 if decision_head is None else decision_head.sequence
            if decision_count >= len(plan.paths) or plan.paths[decision_count] != path:
                raise TransitionError(
                    "external recovery result is outside the next frozen path"
                )
            prior_completion_ids: list[str] = []
            for sequence in range(1, decision_count + 1):
                prior = index.event_record(stream, sequence)
                if (
                    prior is None
                    or prior.kind != "external-dependency-judgement"
                    or prior.status != "failed"
                ):
                    raise RecoveryRequired(
                        "external recovery decision history is malformed"
                    )
                prior_completion = prior.payload.get("completion_record_id")
                if not isinstance(prior_completion, str):
                    raise RecoveryRequired(
                        "external recovery decision lost its completion"
                    )
                prior_completion_ids.append(prior_completion)
            all_completion_ids = [*prior_completion_ids, completion_record_id]
            blocker_credit = (
                verdict == "failed"
                and external.get("indispensable_to_mission_terminal") is True
                and external.get("contract_valid_next_action_found") is False
                and external.get("safe_substitute_found") is False
            )
            if verdict == "passed":
                body["next_action"] = plan.condition.resume_action.to_next_action()
                disposition = "resume_mission_action"
            elif verdict == "not_evaluable":
                body["next_action"] = plan.condition.resume_action.to_next_action()
                disposition = "restore_without_blocker_credit"
            elif not blocker_credit:
                body["next_action"] = plan.condition.resume_action.to_next_action()
                disposition = "restore_non_blocking_external_failure"
            elif decision_count + 1 < len(plan.paths):
                next_path = plan.paths[decision_count + 1]
                body["next_action"] = {
                    "kind": "declare_external_dependency_job",
                    "prior_completion_record_ids": all_completion_ids,
                    "recovery_path_id": next_path.recovery_path_id,
                    "recovery_plan_id": plan.identity,
                }
                disposition = "continue_external_recovery"
            else:
                body["next_action"] = {
                    "completion_record_ids": all_completion_ids,
                    "dependency_id": plan.condition.dependency_id,
                    "kind": "record_external_blocker",
                    "recovery_plan_id": plan.identity,
                }
                disposition = "record_external_blocker"
            decision_payload = {
                "blocker_credit": blocker_credit,
                "completion_record_id": completion_record_id,
                "disposition": disposition,
                "recovery_path_id": path.recovery_path_id,
                "recovery_plan_id": plan.identity,
                "verdict": verdict,
            }
            decision_id = canonical_digest(
                domain="external-dependency-judgement",
                payload=decision_payload,
            )
            record = _record(
                kind="external-dependency-judgement",
                record_id=decision_id,
                subject=f"Job:{job_id}",
                status=verdict,
                fingerprint=completion.fingerprint,
                payload=decision_payload,
                event_stream=stream,
                event_sequence=decision_count + 1,
            )
            return body, [record], {
                "completion_record_id": completion_record_id,
                "disposition": disposition,
                "recovery_plan_id": plan.identity,
                "verdict": verdict,
            }

        return self._commit(
            event_kind="external_dependency_evidence_judged",
            operation_id=operation_id,
            subject="Job:completed",
            payload={"completion_record_id": completion_record_id},
            prepare=prepare,
        )

