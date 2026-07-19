"""Source eligibility, invalidation, and replacement transitions.

The StateWriter facade remains the sole atomic commit owner.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.writer_support import (
    RecoveryRequired,
    TransitionError,
    TransitionResult,
    _copy,
    _record,
    _require_digest,
)
from axiom_rift.storage.index import LocalIndex


class SourceAuthorityWriterMixin:
    """Own source authority transitions; the facade commits atomically."""

    def record_source_eligibility(
        self,
        *,
        eligibility: Any,
        receipt: Any | None,
        operation_id: str,
    ) -> TransitionResult:
        """Commit one typed source-contract eligibility edge to the journal."""

        from axiom_rift.research.source_authority import SourceAuthorityLatch
        from axiom_rift.research.sources import (
            RuntimeSourceDriftObservation,
            SourceContractError,
            SourceEligibility,
            SourceEligibilityReceipt,
            SourceEligibilityState,
            SourceTransitionEvidence,
            require_source_state_transition,
        )

        if not isinstance(eligibility, SourceEligibility):
            raise TransitionError("eligibility must be a SourceEligibility")
        source_id = eligibility.contract.source_contract_id
        contract_hash = source_id.removeprefix("source:")
        _require_digest("source contract hash", contract_hash)
        if eligibility.state is SourceEligibilityState.CONTEXT_ONLY:
            if receipt is not None or eligibility.evidence_receipt_id is not None:
                raise TransitionError("context_only registration has no evidence receipt")
            transition_evidence = None
        else:
            if not isinstance(receipt, SourceEligibilityReceipt):
                raise TransitionError("source transition requires a typed evidence receipt")
            if receipt.source_contract_id != source_id:
                raise TransitionError("source receipt is bound to another contract")
            if eligibility.evidence_receipt_id != receipt.identity:
                raise TransitionError("source eligibility does not bind the supplied receipt")
            transition_evidence = receipt.evidence
            for artifact_hash in receipt.artifact_hashes:
                self.evidence.verify(artifact_hash)

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            if body["scientific"]["active_mission"] is None:
                raise TransitionError("source eligibility requires an active Mission")
            pending = body.get("next_action")
            routed_source_job = (
                isinstance(pending, Mapping)
                and pending.get("kind") == "record_source_eligibility"
            )
            active_job = body["scientific"].get("active_job")
            runtime_drift_context: dict[str, Any] | None = None
            if (
                receipt is not None
                and receipt.evidence is SourceTransitionEvidence.DRIFT
                and eligibility.state is SourceEligibilityState.SUSPENDED
                and isinstance(active_job, Mapping)
                and active_job.get("status") == "running"
            ):
                runtime_drift_declaration = index.get(
                    "job-declared", active_job.get("id", "")
                )
                runtime_drift_start = index.get(
                    "job-started", active_job.get("start_record_id", "")
                )
                runtime_spec = (
                    None
                    if runtime_drift_declaration is None
                    else runtime_drift_declaration.payload.get("spec")
                )
                runtime_start = (
                    None
                    if runtime_drift_start is None
                    else runtime_drift_start.payload.get("runtime")
                )
                candidate_id = (
                    None
                    if not isinstance(runtime_start, Mapping)
                    else runtime_start.get("candidate_id")
                )
                executable_id = (
                    None
                    if not isinstance(runtime_start, Mapping)
                    else runtime_start.get("executable_id")
                )
                candidate_head = (
                    None
                    if not isinstance(executable_id, str)
                    else index.event_head(f"candidate:{executable_id}")
                )
                candidate = (
                    None
                    if candidate_head is None
                    else index.get(candidate_head.record_kind, candidate_head.record_id)
                )
                runtime_entry_id = active_job.get("runtime_entry_record_id")
                runtime_entry = (
                    None
                    if not isinstance(runtime_entry_id, str)
                    else index.get("runtime-engine-entry", runtime_entry_id)
                )
                allowed_producers = {
                    runtime_drift_start.record_id
                } if runtime_drift_start is not None else set()
                if runtime_entry is not None:
                    allowed_producers.add(runtime_entry.record_id)
                if (
                    runtime_drift_declaration is None
                    or runtime_drift_start is None
                    or not isinstance(runtime_spec, Mapping)
                    or not isinstance(runtime_spec.get("runtime_binding"), Mapping)
                    or not isinstance(runtime_start, Mapping)
                    or runtime_drift_declaration.payload.get("mission_id")
                    != body["scientific"].get("active_mission")
                    or runtime_spec.get("evidence_subject")
                    != {"kind": "Executable", "id": executable_id}
                    or executable_id != body["scientific"].get("active_executable")
                    or candidate is None
                    or candidate.record_id != candidate_id
                    or candidate_head is None
                    or candidate_head.record_id != candidate_id
                    or source_id
                    not in candidate.payload.get("executable", {}).get(
                        "source_contracts", []
                    )
                    or pending
                    != {"kind": "resume_job", "job_id": active_job.get("id")}
                    or receipt.producer_completion_id not in allowed_producers
                    or (
                        runtime_entry_id is not None
                        and (
                            runtime_entry is None
                            or runtime_entry.status != "validated"
                            or runtime_entry.subject
                            != f"Job:{active_job.get('id')}"
                            or runtime_entry.fingerprint != active_job.get("hash")
                            or runtime_entry.payload.get("job_start_record_id")
                            != runtime_drift_start.record_id
                            or runtime_entry.payload.get("candidate_id")
                            != candidate_id
                        )
                    )
                ):
                    raise TransitionError(
                        "runtime source drift is not bound to the exact active runtime Job"
                    )
                observations: list[tuple[str, RuntimeSourceDriftObservation]] = []
                for artifact_hash in receipt.artifact_hashes:
                    content = self.evidence.read_verified(artifact_hash)
                    try:
                        value = parse_canonical(content)
                    except (TypeError, ValueError):
                        continue
                    if (
                        isinstance(value, Mapping)
                        and value.get("schema")
                        == "runtime_source_drift_observation.v1"
                    ):
                        try:
                            observation = RuntimeSourceDriftObservation.from_bytes(
                                content
                            )
                        except (SourceContractError, TypeError, ValueError) as exc:
                            raise TransitionError(
                                "runtime source drift observation is malformed"
                            ) from exc
                        observations.append((artifact_hash, observation))
                if len(observations) != 1:
                    raise TransitionError(
                        "runtime source drift requires one exact typed observation"
                    )
                observation_hash, observation = observations[0]
                if (
                    observation.candidate_id != candidate_id
                    or observation.executable_id != executable_id
                    or observation.job_id != active_job.get("id")
                    or observation.job_hash != active_job.get("hash")
                    or observation.job_start_record_id
                    != runtime_drift_start.record_id
                    or observation.observed_at_utc != receipt.observed_at_utc
                    or observation.producer_record_id
                    != receipt.producer_completion_id
                    or observation.source_contract_id != source_id
                    or observation.fact_values() != receipt.fact_values()
                ):
                    raise TransitionError(
                        "runtime source drift observation differs from its active Job"
                    )
                runtime_drift_context = {
                    "artifact_hash": observation_hash,
                    "candidate_id": candidate_id,
                    "executable_id": executable_id,
                    "observation": observation,
                    "runtime_start": runtime_start,
                }
            elif isinstance(active_job, Mapping) and active_job.get("status") == "running":
                raise TransitionError(
                    "a running Job source transition must be its exact runtime drift"
                )
            if routed_source_job:
                resume_next_action = pending.get("resume_next_action")
                if (
                    receipt is None
                    or set(pending)
                    != {
                        "completion_record_id",
                        "job_id",
                        "kind",
                        "resume_next_action",
                        "source_contract_id",
                    }
                    or pending.get("source_contract_id") != source_id
                    or pending.get("completion_record_id")
                    != receipt.producer_completion_id
                    or not isinstance(resume_next_action, Mapping)
                    or not isinstance(resume_next_action.get("kind"), str)
                ):
                    raise TransitionError(
                        "source eligibility does not consume its exact routed Job"
                    )
            elif (
                receipt is not None
                and not self.engineering_fixture
                and runtime_drift_context is None
            ):
                raise TransitionError(
                    "source Job evidence must consume its exact completion route"
                )
            if (
                receipt is not None
                and not self.engineering_fixture
                and runtime_drift_context is None
            ):
                producer = index.get(
                    "job-completed", receipt.producer_completion_id
                )
                source_evidence = (
                    None if producer is None else producer.payload.get("source")
                )
                declaration = (
                    None
                    if producer is None
                    else index.get("job-declared", producer.payload.get("job_id", ""))
                )
                if (
                    producer is None
                    or producer.status != "success"
                    or (
                        routed_source_job
                        and producer.payload.get("job_id")
                        != pending.get("job_id")
                    )
                    or declaration is None
                    or declaration.payload.get("mission_id")
                    != body["scientific"]["active_mission"]
                    or not isinstance(source_evidence, dict)
                    or source_evidence.get("source_contract_id") != source_id
                    or source_evidence.get("transition_evidence")
                    != receipt.evidence.value
                    or source_evidence.get("observed_at_utc") != receipt.observed_at_utc
                    or source_evidence.get("facts") != receipt.fact_values()
                    or tuple(source_evidence.get("artifact_hashes", ()))
                    != receipt.artifact_hashes
                ):
                    raise TransitionError(
                        "source receipt is not derived from its successful source Job"
                    )
            source_head = index.event_head(f"source:{source_id}")
            latest = (
                None
                if source_head is None
                else index.get(source_head.record_kind, source_head.record_id)
            )
            if latest is not None and latest.kind != "source-state":
                raise TransitionError("source-state projection is invalid")
            latch_payload = (
                None if latest is None else latest.payload.get("source_authority_latch")
            )
            authority_head = index.event_head(f"source-authority:{source_id}")
            if authority_head is not None or latch_payload is not None:
                if latch_payload is None:
                    raise RecoveryRequired(
                        "source authority correction lacks its permanent latch"
                    )
                try:
                    latch = SourceAuthorityLatch.from_mapping(latch_payload)
                except (TypeError, ValueError) as exc:
                    raise RecoveryRequired(
                        "source authority latch projection is malformed"
                    ) from exc
                if (
                    latest is None
                    or latest.status != SourceEligibilityState.SUSPENDED.value
                    or latch.source_contract_id != source_id
                    or latch.to_identity_payload() != latch_payload
                    or authority_head is None
                    or authority_head.record_id != latch.invalidation_id
                ):
                    raise RecoveryRequired(
                        "source authority latch projection is inconsistent"
                    )
                raise TransitionError(
                    "audit-invalidated SourceContract cannot be recertified; "
                    "register a new SourceContract identity"
                )
            previous = (
                None if latest is None else SourceEligibilityState(latest.status)
            )
            if runtime_drift_context is not None:
                observation = runtime_drift_context["observation"]
                runtime_start = runtime_drift_context["runtime_start"]
                if (
                    latest is None
                    or previous is not SourceEligibilityState.RUNTIME_ELIGIBLE
                    or latest.record_id
                    != observation.prior_source_state_record_id
                    or latest.payload.get("evidence_receipt_id")
                    != observation.prior_source_receipt_id
                    or observation.prior_source_receipt_id
                    not in runtime_start.get("source_receipt_ids", [])
                ):
                    raise TransitionError(
                        "runtime source drift does not bind the exact source state used at Job start"
                    )
            require_source_state_transition(
                previous=previous,
                target=eligibility.state,
                evidence=transition_evidence,
            )
            if previous is not None and eligibility.evidence_receipt_id is None:
                raise TransitionError("a source transition requires an evidence receipt")
            ordinal = 1 if latest is None else latest.payload["ordinal"] + 1
            state_key = canonical_digest(
                domain="source-state",
                payload={
                    "source_id": source_id,
                    "state": eligibility.state.value,
                    "ordinal": ordinal,
                    "evidence_receipt_id": eligibility.evidence_receipt_id,
                },
            )
            source_payload = {
                "contract_hash": contract_hash,
                "contract": eligibility.contract.to_identity_payload(),
                "mapping_identity": eligibility.contract.mapping_identity,
                "schema_identity": eligibility.contract.schema_identity,
                "field_identity": eligibility.contract.field_identity,
                "clock_identity": eligibility.contract.clock_identity,
                "availability_identity": eligibility.contract.availability_identity,
                "ordinal": ordinal,
                "evidence_receipt_id": eligibility.evidence_receipt_id,
                "suspension_reason": eligibility.suspension_reason,
                "transition_evidence": (
                    None if transition_evidence is None else transition_evidence.value
                ),
                "receipt": None if receipt is None else receipt.to_identity_payload(),
                "scientific_trial_delta": 0,
                "alpha_failure": False,
            }
            if runtime_drift_context is not None:
                source_payload["runtime_source_drift_observation_id"] = (
                    runtime_drift_context["observation"].identity
                )
            record = _record(
                kind="source-state",
                record_id=state_key,
                subject=f"Source:{source_id}",
                status=eligibility.state.value,
                fingerprint=source_id,
                payload=source_payload,
                event_stream=f"source:{source_id}",
                event_sequence=ordinal,
            )
            records = [record]
            if routed_source_job:
                body["next_action"] = _copy(pending["resume_next_action"])
            elif runtime_drift_context is not None:
                observation = runtime_drift_context["observation"]
                observation_record = _record(
                    kind="runtime-source-drift-observation",
                    record_id=observation.identity,
                    subject=f"Job:{active_job['id']}",
                    status="fail_closed",
                    fingerprint=active_job["hash"],
                    payload={
                        **observation.to_identity_payload(),
                        "artifact_hash": runtime_drift_context["artifact_hash"],
                    },
                )
                records.append(observation_record)
                body["next_action"] = {
                    "job_id": active_job["id"],
                    "kind": "complete_runtime_source_ineligibility",
                    "observation_id": observation.identity,
                    "source_contract_id": source_id,
                    "source_state_record_id": state_key,
                }
            return body, records, {
                "runtime_source_drift_observation_id": (
                    None
                    if runtime_drift_context is None
                    else runtime_drift_context["observation"].identity
                ),
                "source_id": source_id,
                "state": eligibility.state.value,
                "ordinal": ordinal,
            }

        return self._commit(
            event_kind="source_eligibility_recorded",
            operation_id=operation_id,
            subject=f"Source:{source_id}",
            payload={
                "source_id": source_id,
                "state": eligibility.state.value,
                "transition_evidence": (
                    None if transition_evidence is None else transition_evidence.value
                ),
                "receipt_id": None if receipt is None else receipt.identity,
            },
            prepare=prepare,
        )

    def suspend_source_authority_from_audit(
        self,
        *,
        invalidation: Any,
        operation_id: str,
        crash_after: str | None = None,
    ) -> TransitionResult:
        """Fail closed one exact legacy source head without rewriting history."""

        from axiom_rift.research.source_authority import (
            AUTHORITY_TRANSITION_EVIDENCE,
            SourceAuthorityAuditManifest,
            SourceAuthorityInvalidation,
            SourceAuthorityLatch,
        )
        from axiom_rift.research.sources import (
            SourceContract,
            SourceEligibilityReceipt,
            SourceEligibilityState,
            SourceTransitionEvidence,
            SourceType,
        )

        if not isinstance(invalidation, SourceAuthorityInvalidation):
            raise TransitionError(
                "source authority suspension requires a typed invalidation"
            )
        try:
            manifest = SourceAuthorityAuditManifest.from_bytes(
                self.evidence.read_verified(invalidation.audit_artifact_hash)
            )
            invalidation.require_manifest(manifest)
            report_bytes = self.evidence.read_verified(
                manifest.report_artifact_hash
            )
            manifest.require_report(report_bytes)
            latch = SourceAuthorityLatch.bind(
                invalidation=invalidation,
                manifest=manifest,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise TransitionError(
                "source authority suspension lacks its exact canonical audit manifest"
            ) from exc
        self._require_study_close_delivery_guard()

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("source authority suspension requires control")
            science = current["scientific"]
            if (
                not isinstance(science.get("active_mission"), str)
                or not isinstance(science.get("active_initiative"), str)
                or current.get("next_action", {}).get("kind")
                != "portfolio_decision"
                or any(
                    science.get(name) is not None
                    for name in (
                        "active_batch",
                        "active_executable",
                        "active_holdout_evaluation",
                        "active_job",
                        "active_lineage",
                        "active_release",
                        "active_repair",
                        "active_study",
                    )
                )
            ):
                raise TransitionError(
                    "source authority suspension requires the stable Portfolio boundary"
                )
            try:
                durable_manifest = SourceAuthorityAuditManifest.from_bytes(
                    self.evidence.read_verified(invalidation.audit_artifact_hash)
                )
                durable_report_bytes = self.evidence.read_verified(
                    durable_manifest.report_artifact_hash
                )
                durable_manifest.require_report(durable_report_bytes)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                raise RecoveryRequired(
                    "source authority audit evidence changed before commit"
                ) from exc
            if durable_manifest != manifest or durable_report_bytes != report_bytes:
                raise RecoveryRequired(
                    "source authority audit manifest changed before commit"
                )

            source_id = invalidation.source_contract_id
            if index.event_head(f"source-authority:{source_id}") is not None:
                raise TransitionError(
                    "source is permanently audit-invalidated; "
                    "a new SourceContract identity is required"
                )
            stream = f"source:{source_id}"
            head = index.event_head(stream)
            latest = (
                None
                if head is None
                else index.get(head.record_kind, head.record_id)
            )
            eligible = index.get(
                "source-state",
                invalidation.source_state_record_id,
            )
            expected_latest_id = (
                None
                if latest is None or latest.event_sequence is None
                else canonical_digest(
                    domain="source-state",
                    payload={
                        "source_id": source_id,
                        "state": latest.status,
                        "ordinal": latest.event_sequence,
                        "evidence_receipt_id": latest.payload.get(
                            "evidence_receipt_id"
                        ),
                    },
                )
            )
            expected_eligible_id = (
                None
                if eligible is None or eligible.event_sequence is None
                else canonical_digest(
                    domain="source-state",
                    payload={
                        "source_id": source_id,
                        "state": eligible.status,
                        "ordinal": eligible.event_sequence,
                        "evidence_receipt_id": eligible.payload.get(
                            "evidence_receipt_id"
                        ),
                    },
                )
            )
            if (
                head is None
                or latest is None
                or latest.kind != "source-state"
                or latest.record_id != expected_latest_id
                or latest.subject != f"Source:{source_id}"
                or latest.fingerprint != source_id
                or latest.event_sequence != head.sequence
                or latest.payload.get("ordinal") != head.sequence
                or eligible is None
                or eligible.kind != "source-state"
                or eligible.record_id != invalidation.source_state_record_id
                or eligible.record_id != expected_eligible_id
                or eligible.status
                not in {
                    SourceEligibilityState.CONTEXT_ONLY.value,
                    SourceEligibilityState.HISTORICAL_AUDITED.value,
                    SourceEligibilityState.RUNTIME_ELIGIBLE.value,
                }
                or eligible.subject != f"Source:{source_id}"
                or eligible.fingerprint != source_id
                or eligible.event_stream != stream
                or eligible.payload.get("ordinal") != eligible.event_sequence
            ):
                raise TransitionError(
                    "source authority invalidation does not bind its eligible head"
                )
            ordinary_suspended = latest.record_id != eligible.record_id
            prior_stream_record = (
                None
                if eligible.event_sequence is None
                else index.event_record(stream, eligible.event_sequence)
            )
            if ordinary_suspended and (
                eligible.status != SourceEligibilityState.RUNTIME_ELIGIBLE.value
                or latest.status != SourceEligibilityState.SUSPENDED.value
                or eligible.event_sequence is None
                or latest.event_sequence != eligible.event_sequence + 1
                or prior_stream_record is None
                or prior_stream_record.record_id != eligible.record_id
                or latest.payload.get("transition_evidence")
                != SourceTransitionEvidence.DRIFT.value
                or latest.payload.get("source_authority_latch") is not None
            ):
                raise TransitionError(
                    "source authority invalidation is not the active eligible head "
                    "or its exact ordinary suspension"
                )
            contract_payload = eligible.payload.get("contract")
            if not isinstance(contract_payload, dict):
                raise RecoveryRequired("source authority contract projection is absent")
            try:
                contract = SourceContract(
                    display_name="audit-invalidated-journal-projection",
                    canonical_instrument=contract_payload["canonical_instrument"],
                    runtime_identifier=contract_payload["runtime_identifier"],
                    source_type=SourceType(contract_payload["source_type"]),
                    instrument_semantics=contract_payload["instrument_semantics"],
                    mapping_semantics=contract_payload["mapping_semantics"],
                    schema_semantics=contract_payload["schema_semantics"],
                    field_semantics=contract_payload["field_semantics"],
                    clock_semantics=contract_payload["clock_semantics"],
                    availability_semantics=contract_payload[
                        "availability_semantics"
                    ],
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise RecoveryRequired(
                    "source authority contract projection is malformed"
                ) from exc
            if (
                contract.identity != source_id
                or contract.to_identity_payload() != contract_payload
                or eligible.payload.get("contract_hash")
                != source_id.removeprefix("source:")
                or eligible.payload.get("mapping_identity")
                != contract.mapping_identity
                or eligible.payload.get("schema_identity")
                != contract.schema_identity
                or eligible.payload.get("field_identity") != contract.field_identity
                or eligible.payload.get("clock_identity") != contract.clock_identity
                or eligible.payload.get("availability_identity")
                != contract.availability_identity
            ):
                raise RecoveryRequired(
                    "source authority contract projection differs from its identity"
                )

            invalidated_state = eligible.status
            preserved_receipt_id = eligible.payload.get("evidence_receipt_id")
            preserved_receipt = eligible.payload.get("receipt")
            if (
                invalidated_state == SourceEligibilityState.CONTEXT_ONLY.value
                and (preserved_receipt_id is not None or preserved_receipt is not None)
            ) or (
                invalidated_state != SourceEligibilityState.CONTEXT_ONLY.value
                and (
                    not isinstance(preserved_receipt_id, str)
                    or not isinstance(preserved_receipt, dict)
                )
            ):
                raise RecoveryRequired(
                    "source authority invalidation cannot preserve the legal receipt"
                )
            receipt: SourceEligibilityReceipt | None = None
            if isinstance(preserved_receipt, dict):
                try:
                    receipt = SourceEligibilityReceipt(
                        source_contract_id=preserved_receipt["source_contract_id"],
                        evidence=SourceTransitionEvidence(
                            preserved_receipt["evidence"]
                        ),
                        producer_completion_id=preserved_receipt[
                            "producer_completion_id"
                        ],
                        observed_at_utc=preserved_receipt["observed_at_utc"],
                        artifact_hashes=tuple(preserved_receipt["artifact_hashes"]),
                        facts=preserved_receipt["facts"],
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise RecoveryRequired(
                        "source authority invalidation receipt is malformed"
                    ) from exc
            legal_receipt = (
                receipt is None
                and invalidated_state == SourceEligibilityState.CONTEXT_ONLY.value
            ) or (
                receipt is not None
                and receipt.identity == preserved_receipt_id
                and receipt.source_contract_id == source_id
                and receipt.to_identity_payload() == preserved_receipt
                and eligible.payload.get("transition_evidence")
                == receipt.evidence.value
                and (
                    (
                        invalidated_state
                        == SourceEligibilityState.HISTORICAL_AUDITED.value
                        and receipt.evidence
                        is SourceTransitionEvidence.HISTORICAL_AUDIT
                    )
                    or (
                        invalidated_state
                        == SourceEligibilityState.RUNTIME_ELIGIBLE.value
                        and receipt.evidence
                        in {
                            SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF,
                            SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION,
                        }
                    )
                )
            )
            if not legal_receipt:
                raise RecoveryRequired(
                    "source authority invalidation receipt differs from its state"
                )
            ordinary_suspension_receipt: SourceEligibilityReceipt | None = None
            if ordinary_suspended:
                latest_receipt_payload = latest.payload.get("receipt")
                try:
                    ordinary_suspension_receipt = SourceEligibilityReceipt(
                        source_contract_id=latest_receipt_payload[
                            "source_contract_id"
                        ],
                        evidence=SourceTransitionEvidence(
                            latest_receipt_payload["evidence"]
                        ),
                        producer_completion_id=latest_receipt_payload[
                            "producer_completion_id"
                        ],
                        observed_at_utc=latest_receipt_payload["observed_at_utc"],
                        artifact_hashes=tuple(
                            latest_receipt_payload["artifact_hashes"]
                        ),
                        facts=latest_receipt_payload["facts"],
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise RecoveryRequired(
                        "ordinary source suspension receipt is malformed"
                    ) from exc
                if (
                    ordinary_suspension_receipt.evidence
                    is not SourceTransitionEvidence.DRIFT
                    or ordinary_suspension_receipt.source_contract_id != source_id
                    or ordinary_suspension_receipt.identity
                    != latest.payload.get("evidence_receipt_id")
                    or ordinary_suspension_receipt.to_identity_payload()
                    != latest_receipt_payload
                    or not isinstance(latest.payload.get("suspension_reason"), str)
                    or any(
                        latest.payload.get(field) != eligible.payload.get(field)
                        for field in (
                            "availability_identity",
                            "clock_identity",
                            "contract",
                            "contract_hash",
                            "field_identity",
                            "mapping_identity",
                            "schema_identity",
                        )
                    )
                ):
                    raise RecoveryRequired(
                        "ordinary source suspension does not preserve eligible provenance"
                    )
            if receipt is not None:
                for artifact_hash in receipt.artifact_hashes:
                    self.evidence.verify(artifact_hash)
            if ordinary_suspension_receipt is not None:
                for artifact_hash in ordinary_suspension_receipt.artifact_hashes:
                    self.evidence.verify(artifact_hash)
            suspension_reason = (
                f"{invalidation.reason_code.value}: "
                f"{invalidation.observed_defect}"
            )
            ordinal = head.sequence + 1
            state_id = canonical_digest(
                domain="source-state",
                payload={
                    "source_id": source_id,
                    "state": SourceEligibilityState.SUSPENDED.value,
                    "ordinal": ordinal,
                    "evidence_receipt_id": preserved_receipt_id,
                },
            )
            correction_stream = f"source-authority:{source_id}"
            correction_head = index.event_head(correction_stream)
            if correction_head is not None:
                raise RecoveryRequired(
                    "source authority contract already has an audit correction"
                )
            correction = _record(
                kind="source-authority-invalidation",
                record_id=invalidation.identity,
                subject=f"Source:{source_id}",
                status="confirmed_and_suspended",
                fingerprint=invalidation.identity.removeprefix(
                    "source-authority-invalidation:"
                ),
                payload={
                    "audit_manifest": manifest.to_identity_payload(),
                    "eligible_source_state_record_id": eligible.record_id,
                    "invalidation": invalidation.to_identity_payload(),
                    "latch": latch.to_identity_payload(),
                    "invalidated_state": invalidated_state,
                    "preserved_receipt_id": preserved_receipt_id,
                    "prior_active_source_state_record_id": latest.record_id,
                    "replacement_state_record_id": state_id,
                    "scientific_trial_delta": 0,
                },
                event_stream=correction_stream,
                event_sequence=1,
            )
            state = _record(
                kind="source-state",
                record_id=state_id,
                subject=f"Source:{source_id}",
                status=SourceEligibilityState.SUSPENDED.value,
                fingerprint=source_id,
                payload={
                    "contract_hash": source_id.removeprefix("source:"),
                    "contract": contract.to_identity_payload(),
                    "mapping_identity": contract.mapping_identity,
                    "schema_identity": contract.schema_identity,
                    "field_identity": contract.field_identity,
                    "clock_identity": contract.clock_identity,
                    "availability_identity": contract.availability_identity,
                    "ordinal": ordinal,
                    "evidence_receipt_id": preserved_receipt_id,
                    "suspension_reason": suspension_reason,
                    "transition_evidence": AUTHORITY_TRANSITION_EVIDENCE,
                    "receipt": (
                        None
                        if preserved_receipt is None
                        else _copy(preserved_receipt)
                    ),
                    "eligible_source_state_record_id": eligible.record_id,
                    "prior_active_source_state_record_id": latest.record_id,
                    "source_authority_latch": latch.to_identity_payload(),
                    "scientific_trial_delta": 0,
                    "alpha_failure": False,
                },
                event_stream=stream,
                event_sequence=ordinal,
            )
            return self._body(current), [correction, state], {
                "invalidation_record_id": invalidation.identity,
                "invalidated_state": invalidated_state,
                "prior_active_source_state_record_id": latest.record_id,
                "source_id": source_id,
                "source_state_record_id": state_id,
                "state": SourceEligibilityState.SUSPENDED.value,
                "trial_delta": 0,
            }

        return self._commit(
            event_kind="source_authority_suspended_from_audit",
            operation_id=operation_id,
            subject=f"Source:{invalidation.source_contract_id}",
            payload=invalidation.to_identity_payload(),
            prepare=prepare,
            crash_after=crash_after,
        )

    def record_source_replacement_lineage(
        self,
        *,
        lineage: Any,
        operation_id: str,
    ) -> TransitionResult:
        """Retire one invalidated old axis into a distinct eligible source axis."""

        from axiom_rift.operations.effective_axis_projection import (
            EffectiveAxisProjectionError,
            validate_source_replacement_lineage,
        )
        from axiom_rift.research.effective_axis import EffectiveAxisStatus
        from axiom_rift.research.source_authority import SourceReplacementLineage

        self._require_study_close_delivery_guard()
        if not isinstance(lineage, SourceReplacementLineage):
            raise TransitionError(
                "source replacement lineage must be a typed additive record"
            )

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            science = current["scientific"]
            mission_id = science.get("active_mission")
            if mission_id != lineage.mission_id or any(
                science.get(name) is not None
                for name in (
                    "active_batch",
                    "active_executable",
                    "active_holdout_evaluation",
                    "active_job",
                    "active_lineage",
                    "active_release",
                    "active_repair",
                    "active_study",
                )
            ):
                raise TransitionError(
                    "source replacement requires a stable active Mission boundary"
                )
            active_initiative = science.get("active_initiative")
            next_action = current.get("next_action")
            stable_portfolio_boundary = (
                isinstance(active_initiative, str)
                and isinstance(next_action, dict)
                and next_action.get("kind") == "portfolio_decision"
            )
            if not (
                stable_portfolio_boundary
                or self._active_mission_stable_boundary(current)
            ):
                raise TransitionError(
                    "source replacement cannot bypass pending research direction"
                )
            portfolio_head = index.event_head(f"portfolio:{mission_id}")
            snapshot = (
                None
                if portfolio_head is None
                else index.get(portfolio_head.record_kind, portfolio_head.record_id)
            )
            raw_axes = None if snapshot is None else snapshot.payload.get("axes")
            if (
                snapshot is None
                or snapshot.record_id != lineage.portfolio_snapshot_id
                or snapshot.subject != f"Mission:{mission_id}"
                or not isinstance(raw_axes, list)
            ):
                raise TransitionError(
                    "source replacement is not bound to the current Portfolio"
                )
            axes = {
                axis.get("axis_id"): axis
                for axis in raw_axes
                if isinstance(axis, dict) and isinstance(axis.get("axis_id"), str)
            }
            original_axis = axes.get(lineage.original_axis_id)
            replacement_axis = axes.get(lineage.replacement_axis_id)
            if (
                len(axes) != len(raw_axes)
                or original_axis is None
                or replacement_axis is None
            ):
                raise TransitionError(
                    "source replacement Portfolio axes are unavailable"
                )
            try:
                binding = validate_source_replacement_lineage(
                    index,
                    lineage,
                    require_current_replacement_source=True,
                )
            except EffectiveAxisProjectionError as exc:
                raise TransitionError(str(exc)) from exc
            original_resolution, replacement_resolution = (
                self._effective_axis_resolutions(
                    index,
                    (original_axis, replacement_axis),
                )
            )
            exact_invalidation = any(
                item.source_contract_id
                == lineage.invalidated_source_contract_id
                and item.invalidation_record_id == lineage.invalidation_id
                for item in original_resolution.invalidations
            )
            if (
                original_resolution.effective_status
                is not EffectiveAxisStatus.BLOCKED_BY_INVALIDATED_SOURCE
                or not exact_invalidation
                or not replacement_resolution.selectable
                or binding.record_id != lineage.identity
            ):
                raise TransitionError(
                    "source replacement does not retire one exact blocked axis "
                    "into a selectable replacement axis"
                )
            stream = (
                f"source-replacement:{mission_id}:"
                f"{lineage.original_axis_identity}:"
                f"{lineage.invalidated_source_contract_id}"
            )
            if index.event_head(stream) is not None:
                raise TransitionError(
                    "source replacement lineage is already recorded"
                )
            payload = {
                "candidate_delta": 0,
                "claim_delta": "none",
                "holdout_delta": 0,
                "lineage": lineage.to_identity_payload(),
                "scientific_credit": 0,
                "terminal_scientific_credit": 0,
                "trial_delta": 0,
            }
            record = _record(
                kind="source-replacement-lineage",
                record_id=lineage.identity,
                subject=f"Axis:{lineage.original_axis_identity}",
                status="retired_original_axis",
                fingerprint=lineage.identity.removeprefix(
                    "source-replacement-lineage:"
                ),
                payload=payload,
                event_stream=stream,
                event_sequence=1,
            )
            return self._body(current), [record], {
                "candidate_delta": 0,
                "claim_delta": "none",
                "holdout_delta": 0,
                "original_axis_id": lineage.original_axis_id,
                "replacement_axis_id": lineage.replacement_axis_id,
                "source_replacement_lineage_id": lineage.identity,
                "trial_delta": 0,
            }

        return self._commit(
            event_kind="source_replacement_lineage_recorded",
            operation_id=operation_id,
            subject=f"Axis:{lineage.original_axis_identity}",
            payload={"lineage": lineage.to_identity_payload()},
            prepare=prepare,
        )
