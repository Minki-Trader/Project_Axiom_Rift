"""Batch and Study lifecycle transitions behind the public StateWriter facade."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.batch_budget import (
    FIXED_HOLD_REPLAY_BUDGET_POLICY_ID,
    FIXED_HOLD_REPLAY_BUDGET_REPAIR_REASON,
    batch_budget_reservation_repair_manifest,
    registered_batch_budget_for_output_classes,
)
from axiom_rift.operations.permits import (
    Permit,
    PermitError,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.scientific_multiplicity_authority import (
    ScientificMultiplicityIntegrityError,
    concurrent_family_executable_ids,
)
from axiom_rift.operations.writer_support import (
    RecoveryRequired,
    TransitionError,
    TransitionResult,
    _digest,
    _record,
    _require_ascii,
    _require_digest,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView
from axiom_rift.storage.study_kpi import (
    LEDGER_RELATIVE_PATH,
    StudyKpiProjectionRow,
    materialize_study_kpi,
)
from axiom_rift.storage.state import WriterLock


_STUDY_OUTCOMES = frozenset(
    {"supported", "not_supported", "not_evaluable", "evidence_gap", "pruned", "preserved"}
)
_STUDY_KPI_METRICS = (
    "net_profit_micropoints",
    "median_fold_profit_factor_milli",
    "trade_count",
    "monthly_realized_exit_drawdown_share_of_gross_profit_ppm",
)
_STUDY_KPI_ACTIVATION_OPERATION_ID = "study-close-kpi-main-delivery-authority-v1"
_STUDY_KPI_BACKFILL_OPERATION_ID = "study-kpi-historical-backfill-v1"
_TYPED_STARTED_BATCH_EXIT_ACTIVATION_OPERATION_ID = (
    "project-goal-audit-v2-typed-started-batch-exit-v1"
)
_BATCH_OUTCOMES = frozenset(
    {"completed", "budget_exhausted", "stopped_early", "not_evaluable", "engineering_failure"}
)
_ENGINEERING_FIXTURE_OUTCOME = "engineering_fixture_complete"
_BATCH_EVIDENCE_DECISION_STATUSES = ("continue_batch", "stop_batch")


@dataclass(frozen=True, slots=True)
class _BatchJobDecisionInventory:
    """One bounded Batch-local declaration and evidence-decision slice."""

    batch_id: str
    declarations: tuple[IndexRecord, ...]
    decisions: tuple[IndexRecord, ...]


def _batch_job_decision_inventory(
    index: LocalIndex | LocalIndexView,
    *,
    batch_id: str,
) -> _BatchJobDecisionInventory:
    """Resolve one Batch without decoding project-wide Job history."""

    _require_ascii("Batch identity", batch_id)
    declarations = tuple(
        sorted(
            index.records_by_payload_text(
                "job-declared",
                "batch_id",
                batch_id,
            ),
            key=lambda record: record.record_id,
        )
    )
    decisions: list[IndexRecord] = []
    for declaration in declarations:
        job_decisions = tuple(
            record
            for status in _BATCH_EVIDENCE_DECISION_STATUSES
            for record in index.records_by_subject_status(
                f"Job:{declaration.record_id}",
                status,
            )
            if record.kind == "job-evidence-decision"
        )
        decisions.extend(job_decisions)
    return _BatchJobDecisionInventory(
        batch_id=batch_id,
        declarations=declarations,
        decisions=tuple(sorted(decisions, key=lambda record: record.record_id)),
    )


def _concurrent_family_executable_ids(
    batch_record: IndexRecord,
) -> tuple[str, ...] | None:
    try:
        return concurrent_family_executable_ids(batch_record)
    except ScientificMultiplicityIntegrityError as exc:
        raise RecoveryRequired(str(exc)) from exc


class BatchLifecycleWriterMixin:
    """Own Batch admission, budget, disposal, and continuation transitions."""

    def open_batch(
        self,
        *,
        batch_spec: Any,
        permit: Permit,
        source_permits: tuple[Permit, ...] = (),
        operation_id: str,
    ) -> TransitionResult:
        from axiom_rift.research.portfolio import BatchSpec

        self._require_study_close_delivery_guard()
        if not isinstance(batch_spec, BatchSpec):
            raise TransitionError("batch_spec must be a frozen BatchSpec")
        batch_id = batch_spec.identity
        batch_hash = batch_spec.identity.removeprefix("batch:")
        _require_digest("batch_hash", batch_hash)

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            study_id = science["active_study"]
            if study_id is None or science["active_batch"] is not None:
                raise TransitionError("Batch open requires one active Study and no Batch")
            if batch_spec.study_id != study_id:
                raise TransitionError("BatchSpec is bound to another Study")
            study_record = index.get("study-open", study_id)
            if (
                study_record is None
                or study_record.status != "open"
                or study_record.fingerprint != batch_spec.study_hash
            ):
                raise TransitionError("BatchSpec is not bound to the active Study identity")
            replay_admission = self._study_replay_implementation_admission(
                index,
                study_id=study_id,
                authority_manifest_digest=current.get("authority", {}).get(
                    "manifest_digest"
                ),
            )
            if (
                replay_admission is not None
                and replay_admission.payload.get("batch_id") != batch_id
            ):
                raise TransitionError(
                    "Batch differs from the replay implementation admission"
                )
            batch_head = index.event_head(f"study-batches:{study_id}")
            prior_batch_count = 0 if batch_head is None else batch_head.sequence
            commitment_batches = study_record.payload.get("commitment_batches")
            if not self.engineering_fixture and (
                type(commitment_batches) is not int
                or commitment_batches <= 0
            ):
                raise TransitionError(
                    "scientific Study requires a positive finite Batch bound"
                )
            if not self.engineering_fixture:
                assert type(commitment_batches) is int
                if prior_batch_count >= commitment_batches:
                    raise TransitionError(
                        "scientific Study Batch commitment is exhausted"
                    )
                if prior_batch_count == 0:
                    if body.get("next_action") != {
                        "kind": "freeze_batch",
                        "study_id": study_id,
                    }:
                        raise TransitionError(
                            "first Batch is not the exact frozen Study action"
                        )
                else:
                    continuation_head = index.event_head(
                        f"study-continuation:{study_id}"
                    )
                    continuation = (
                        None
                        if continuation_head is None
                        else index.get(
                            continuation_head.record_kind,
                            continuation_head.record_id,
                        )
                    )
                    expected_action = {
                        "batch_id": batch_id,
                        "continuation_decision_id": (
                            None
                            if continuation is None
                            else continuation.record_id
                        ),
                        "kind": "freeze_batch",
                        "study_id": study_id,
                    }
                    if (
                        continuation_head is None
                        or continuation_head.sequence != prior_batch_count
                        or continuation is None
                        or continuation.kind
                        != "study-continuation-decision"
                        or continuation.status != "continue"
                        or continuation.payload.get("study_id") != study_id
                        or continuation.payload.get("prior_batch_id")
                        != batch_head.record_id
                        or continuation.payload.get("next_batch_id")
                        != batch_id
                        or body.get("next_action") != expected_action
                    ):
                        raise TransitionError(
                            "later Batch lacks its exact continuation decision"
                        )
            self._validate_permit_locked(
                control=current,
                index=index,
                permit=permit,
                expected_kind=PermitKind.BATCH,
                action="open_batch",
                subject_kind=SubjectKind.STUDY,
                subject_id=study_id,
                expected_input_hash=batch_hash,
            )
            used_source_permits: set[str] = set()
            for source_id in batch_spec.source_contract_ids:
                matches = [
                    candidate
                    for candidate in source_permits
                    if f"source:{source_id}" in candidate.scope
                ]
                if len(matches) != 1:
                    raise PermitError(
                        "each external source requires one exact SourcePermit"
                    )
                source_permit = matches[0]
                self._validate_permit_locked(
                    control=current,
                    index=index,
                    permit=source_permit,
                    expected_kind=PermitKind.SOURCE,
                    action="performance_batch",
                    subject_kind=SubjectKind.STUDY,
                    subject_id=study_id,
                    expected_input_hash=batch_hash,
                    required_scope=(f"source:{source_id}",),
                )
                self._require_source_authority_for_actions(
                    index,
                    source_id,
                    actions=("performance_batch",),
                    error_type=PermitError,
                )
                used_source_permits.add(source_permit.permit_id)
            if used_source_permits != {item.permit_id for item in source_permits}:
                raise PermitError("Batch received an unrelated SourcePermit")
            science["active_batch"] = {"id": batch_id, "hash": batch_hash, "status": "open"}
            body["next_action"] = {"kind": "declare_job", "batch_id": batch_id}
            consumption = self._permit_consumption_record(permit, operation_id)
            source_consumptions = [
                self._permit_consumption_record(item, operation_id)
                for item in source_permits
            ]
            record = _record(
                kind="batch-open",
                record_id=batch_id,
                subject=f"Study:{study_id}",
                status="open",
                fingerprint=batch_hash,
                payload={
                    "batch_hash": batch_hash,
                    "display_id": batch_spec.batch_id,
                    "display_name": batch_spec.display_name,
                    "spec": batch_spec.to_identity_payload(),
                    "source_permit_ids": sorted(used_source_permits),
                },
                event_stream=f"study-batches:{study_id}",
                event_sequence=prior_batch_count + 1,
            )
            return body, [consumption, *source_consumptions, record], {"batch_id": batch_id}

        return self._commit(
            event_kind="batch_opened",
            operation_id=operation_id,
            subject=f"Batch:{batch_id}",
            payload={
                "batch_id": batch_id,
                "batch_hash": batch_hash,
                "source_permit_ids": sorted(item.permit_id for item in source_permits),
            },
            prepare=prepare,
        )

    def _batch_budget_reservation_repair_plan_locked(
        self,
        current: Mapping[str, Any],
        index: LocalIndex | LocalIndexView,
        *,
        corrected_job_budgets: Mapping[str, Mapping[str, int]],
        policy_id: str,
        reason: str,
    ) -> dict[str, object]:
        body = self._body(dict(current))
        science = body["scientific"]
        batch = science.get("active_batch")
        if (
            not isinstance(batch, dict)
            or science.get("active_job") is not None
            or science.get("active_repair") is not None
            or body.get("next_action")
            != {"kind": "declare_job", "batch_id": batch.get("id")}
        ):
            raise TransitionError(
                "Batch budget repair requires a stable between-Job boundary"
            )
        batch_id = batch.get("id")
        if type(batch_id) is not str:
            raise TransitionError("Batch budget repair lacks its active Batch")
        batch_record = index.get("batch-open", batch_id)
        budget_head = index.event_head(f"batch-budget:{batch_id}")
        if (
            batch_record is None
            or budget_head is None
            or budget_head.record_kind != "batch-budget-reservation"
        ):
            raise TransitionError(
                "Batch budget repair requires unrepaired reservations"
            )
        budget_record = index.get(
            budget_head.record_kind,
            budget_head.record_id,
        )
        if budget_record is None:
            raise TransitionError("Batch budget reservation head is absent")
        job_inventory = _batch_job_decision_inventory(
            index,
            batch_id=batch_id,
        )
        declarations = job_inventory.declarations
        if not declarations:
            raise TransitionError("Batch budget repair has no completed Jobs")
        decisions = {
            record.subject.removeprefix("Job:")
            for record in job_inventory.decisions
            if record.status in {"continue_batch", "stop_batch"}
        }
        job_ids = {record.record_id for record in declarations}
        if not job_ids.issubset(decisions):
            raise TransitionError(
                "Batch budget repair cannot rebase unfinished Job reservations"
            )
        declared_job_budgets: dict[str, dict[str, int]] = {}
        implementation_identities: dict[str, str] = {}
        declaration_specs: dict[str, Mapping[str, Any]] = {}
        for declaration in declarations:
            spec = declaration.payload.get("spec")
            budget = None if not isinstance(spec, Mapping) else spec.get("budget")
            implementation = (
                None
                if not isinstance(spec, Mapping)
                else spec.get("implementation_identity")
            )
            if not isinstance(budget, Mapping) or type(implementation) is not str:
                raise TransitionError(
                    "Batch budget repair Job declaration is malformed"
                )
            declared_job_budgets[declaration.record_id] = {
                "compute_seconds": budget.get("compute_seconds"),
                "wall_seconds": budget.get("wall_seconds"),
            }
            implementation_identities[declaration.record_id] = implementation
            assert isinstance(spec, Mapping)
            declaration_specs[declaration.record_id] = spec
        frozen_spec = batch_record.payload.get("spec")
        if not isinstance(frozen_spec, Mapping):
            raise TransitionError("Batch budget repair lacks the frozen ceiling")
        if not self.engineering_fixture:
            acceptance = frozen_spec.get("acceptance_profile")
            concurrent = (
                None
                if not isinstance(acceptance, Mapping)
                else acceptance.get("concurrent_family")
            )
            family_ids = (
                None
                if not isinstance(concurrent, Mapping)
                else concurrent.get("executable_ids")
            )
            subjects = {
                spec.get("evidence_subject", {}).get("id")
                for spec in declaration_specs.values()
                if isinstance(spec.get("evidence_subject"), Mapping)
            }
            callable_identities = {
                spec.get("callable_identity")
                for spec in declaration_specs.values()
            }
            if (
                policy_id != FIXED_HOLD_REPLAY_BUDGET_POLICY_ID
                or reason != FIXED_HOLD_REPLAY_BUDGET_REPAIR_REASON
                or not isinstance(acceptance, Mapping)
                or acceptance.get("candidate_authority") != "none"
                or not isinstance(acceptance.get("exact_original_criteria"), list)
                or not acceptance.get("exact_original_criteria")
                or type(acceptance.get("replay_obligation_id")) is not str
                or not isinstance(concurrent, Mapping)
                or concurrent.get("evaluation_mode") != "vectorized"
                or concurrent.get("family_size") != frozen_spec.get("max_trials")
                or not isinstance(family_ids, list)
                or len(family_ids) != frozen_spec.get("max_trials")
                or not subjects
                or not subjects.issubset(set(family_ids))
                or len(callable_identities) != 1
                or len(set(implementation_identities.values())) != 1
                or frozen_spec.get("stop_rule")
                != "stop only after the exact registered family"
            ):
                raise TransitionError(
                    "Batch budget repair is outside the registered replay policy"
                )
            cache_producer_count = 0
            registered_budgets: dict[str, dict[str, int]] = {}
            try:
                for job_id, spec in declaration_specs.items():
                    output_classes = spec.get("output_classes")
                    if not isinstance(output_classes, Mapping):
                        raise ValueError(
                            "Batch budget repair output classes are invalid"
                        )
                    cache_producer_count += tuple(output_classes.values()).count(
                        "reproducible_cache"
                    )
                    registered_budgets[job_id] = (
                        registered_batch_budget_for_output_classes(
                            policy_id=policy_id,
                            output_classes=output_classes,
                        )
                    )
            except ValueError as exc:
                raise TransitionError(str(exc)) from exc
            normalized_corrected = {
                job_id: dict(budget)
                for job_id, budget in corrected_job_budgets.items()
            }
            if (
                cache_producer_count != 1
                or normalized_corrected != registered_budgets
            ):
                raise TransitionError(
                    "Batch budget repair differs from the registered policy"
                )
        try:
            manifest = batch_budget_reservation_repair_manifest(
                batch_id=batch_id,
                frozen_budget_ceiling={
                    "compute_seconds": frozen_spec.get("max_compute_seconds"),
                    "wall_seconds": frozen_spec.get("max_wall_seconds"),
                },
                declared_job_budgets=declared_job_budgets,
                corrected_job_budgets=corrected_job_budgets,
                job_implementation_identities=implementation_identities,
                policy_id=policy_id,
                reason=reason,
            )
        except ValueError as exc:
            raise TransitionError(str(exc)) from exc
        prior = manifest["prior_reserved_totals"]
        if (
            not isinstance(prior, Mapping)
            or budget_record.payload.get("compute_seconds")
            != prior.get("compute_seconds")
            or budget_record.payload.get("wall_seconds")
            != prior.get("wall_seconds")
        ):
            raise TransitionError(
                "Batch budget repair differs from the reservation head"
            )
        return manifest

    def plan_batch_budget_reservation_repair(
        self,
        *,
        corrected_job_budgets: Mapping[str, Mapping[str, int]],
        policy_id: str,
        reason: str,
    ) -> dict[str, object]:
        """Build a read-only, reduction-only Batch reservation repair."""

        _require_ascii("Batch budget repair policy", policy_id)
        _require_ascii("Batch budget repair reason", reason)
        with WriterLock(self.lock_path):
            with self._open_authoritative_index() as index:
                current = self._require_stable_locked(index)
                if not isinstance(current, Mapping):
                    raise TransitionError("Batch budget repair requires control")
                return self._batch_budget_reservation_repair_plan_locked(
                    current,
                    index,
                    corrected_job_budgets=corrected_job_budgets,
                    policy_id=policy_id,
                    reason=reason,
                )

    def repair_batch_budget_reservations(
        self,
        *,
        corrected_job_budgets: Mapping[str, Mapping[str, int]],
        policy_id: str,
        reason: str,
        proof_hash: str,
        operation_id: str,
    ) -> TransitionResult:
        """Release proven over-reservations without changing frozen science."""

        _require_ascii("Batch budget repair policy", policy_id)
        _require_ascii("Batch budget repair reason", reason)
        _require_digest("Batch budget repair proof", proof_hash)
        try:
            proof = parse_canonical(self.evidence.read_verified(proof_hash))
        except ValueError as exc:
            raise TransitionError("Batch budget repair proof is invalid") from exc
        if not isinstance(proof, Mapping):
            raise TransitionError("Batch budget repair proof is not an object")

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("Batch budget repair requires control")
            expected = self._batch_budget_reservation_repair_plan_locked(
                current,
                index,
                corrected_job_budgets=corrected_job_budgets,
                policy_id=policy_id,
                reason=reason,
            )
            if dict(proof) != expected:
                raise TransitionError(
                    "Batch budget repair proof differs from durable state"
                )
            batch_id = str(expected["batch_id"])
            budget_head = index.event_head(f"batch-budget:{batch_id}")
            if budget_head is None:
                raise TransitionError("Batch budget repair head disappeared")
            totals = expected["corrected_reserved_totals"]
            assert isinstance(totals, Mapping)
            record = _record(
                kind="batch-budget-repair",
                record_id=canonical_digest(
                    domain="batch-budget-repair",
                    payload={
                        "batch_id": batch_id,
                        "policy_id": policy_id,
                        "proof_hash": proof_hash,
                    },
                ),
                subject=f"Batch:{batch_id}",
                status="repaired",
                fingerprint=proof_hash,
                payload={
                    "compute_seconds": totals["compute_seconds"],
                    "proof_hash": proof_hash,
                    "repair": expected,
                    "wall_seconds": totals["wall_seconds"],
                },
                event_stream=f"batch-budget:{batch_id}",
                event_sequence=budget_head.sequence + 1,
            )
            return self._body(current), [record], {
                "batch_id": batch_id,
                "completed_job_count": expected["completed_job_count"],
                "corrected_reserved_totals": dict(totals),
                "proof_hash": proof_hash,
                "scientific_trial_delta": 0,
            }

        return self._commit(
            event_kind="batch_budget_repaired",
            operation_id=operation_id,
            subject="Batch:active",
            payload={
                "corrected_job_budgets": {
                    job_id: dict(budget)
                    for job_id, budget in sorted(corrected_job_budgets.items())
                },
                "policy_id": policy_id,
                "proof_hash": proof_hash,
                "reason": reason,
            },
            prepare=prepare,
        )

    @staticmethod
    def _batch_continuation_bindings(
        index: LocalIndex,
        batch_id: str,
    ) -> dict[str, Any]:
        """Re-derive the closed Batch member, completion, and evidence set."""

        batch = index.get("batch-open", batch_id)
        spec = None if batch is None else batch.payload.get("spec")
        if batch is None or not isinstance(spec, Mapping):
            raise TransitionError("Study continuation lost its frozen Batch")
        trial_head = index.event_head(f"batch-trials:{batch_id}")
        trial_records: list[IndexRecord] = []
        if trial_head is not None:
            for sequence in range(1, trial_head.sequence + 1):
                trial = index.event_record(
                    f"batch-trials:{batch_id}", sequence
                )
                if (
                    trial is None
                    or trial.kind != "trial"
                    or trial.subject != f"Batch:{batch_id}"
                    or trial.event_sequence != sequence
                ):
                    raise TransitionError(
                        "Study continuation Batch member projection is invalid"
                    )
                trial_records.append(trial)
        registered_members = tuple(
            sorted(record.record_id for record in trial_records)
        )
        if len(set(registered_members)) != len(registered_members):
            raise TransitionError(
                "Study continuation Batch member set is not unique"
            )
        acceptance = spec.get("acceptance_profile")
        concurrent = (
            None
            if not isinstance(acceptance, Mapping)
            else acceptance.get("concurrent_family")
        )
        frozen_members = (
            None
            if not isinstance(concurrent, Mapping)
            else concurrent.get("executable_ids")
        )
        if frozen_members is not None and (
            not isinstance(frozen_members, list)
            or any(type(member) is not str for member in frozen_members)
            or len(set(frozen_members)) != len(frozen_members)
            or set(frozen_members) != set(registered_members)
        ):
            raise TransitionError(
                "Study continuation differs from the frozen concurrent family"
            )

        from axiom_rift.operations.scientific_history import (
            ScientificHistoryProjectionError,
            project_batch_job_evidence,
        )

        try:
            job_evidence = project_batch_job_evidence(
                index,
                batch_id=batch_id,
            )
        except ScientificHistoryProjectionError as exc:
            raise TransitionError(str(exc)) from exc
        declarations = job_evidence.declarations
        member_job_ids = tuple(record.record_id for record in declarations)
        declaration_members: set[str] = set()
        completion_ids: list[str] = []
        durable_evidence_hashes: set[str] = set()
        decision_statuses: list[str] = []
        for declaration, completion, evidence_decision in zip(
            declarations,
            job_evidence.completions,
            job_evidence.decisions,
            strict=True,
        ):
            declaration_spec = declaration.payload.get("spec")
            evidence_subject = (
                None
                if not isinstance(declaration_spec, Mapping)
                else declaration_spec.get("evidence_subject")
            )
            if (
                not isinstance(evidence_subject, Mapping)
                or evidence_subject.get("kind") != "Executable"
                or type(evidence_subject.get("id")) is not str
            ):
                raise TransitionError(
                    "Study continuation Job is not bound to a Batch member"
                )
            declaration_members.add(evidence_subject["id"])
            decision_statuses.append(evidence_decision.status)
            completion_id = completion.record_id
            if (
                completion.subject != f"Job:{declaration.record_id}"
                or completion.payload.get("job_id") != declaration.record_id
                or completion.fingerprint != declaration.fingerprint
            ):
                raise TransitionError(
                    "Study continuation Job completion binding is invalid"
                )
            completion_ids.append(completion_id)
            outputs = completion.payload.get("outputs")
            output_classes = completion.payload.get("output_classes")
            if not isinstance(outputs, Mapping) or not isinstance(
                output_classes, Mapping
            ):
                raise TransitionError(
                    "Study continuation completion outputs are malformed"
                )
            for output_name, output_hash in outputs.items():
                if output_classes.get(output_name) != "durable_evidence":
                    continue
                _require_digest(
                    "Study continuation durable evidence", output_hash
                )
                durable_evidence_hashes.add(output_hash)
        if (
            len(declarations) != len(registered_members)
            or len(declaration_members) != len(declarations)
            or declaration_members != set(registered_members)
        ):
            raise TransitionError(
                "Study continuation requires exactly one completed Job per Batch member"
            )
        return {
            "completion_record_ids": tuple(sorted(completion_ids)),
            "evidence_hashes": tuple(sorted(durable_evidence_hashes)),
            "member_executable_ids": registered_members,
            "member_job_ids": member_job_ids,
            "stop_rule_state": (
                "unresolved"
                if not decision_statuses
                else (
                    "reached"
                    if "stop_batch" in decision_statuses
                    else "not_reached"
                )
            ),
        }

    def dispose_batch(
        self, *, outcome: str, operation_id: str
    ) -> TransitionResult:
        _require_ascii("outcome", outcome)
        allowed = set(_BATCH_OUTCOMES)
        if self.engineering_fixture:
            allowed.add(_ENGINEERING_FIXTURE_OUTCOME)
        if outcome not in allowed:
            raise TransitionError("Batch outcome is not typed")

        def prepare(current: dict[str, Any] | None, _index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            batch = science["active_batch"]
            if not isinstance(batch, dict):
                raise TransitionError("no active Batch")
            if not self.engineering_fixture:
                next_action = body.get("next_action")
                exact_dispose = {
                    "kind": "dispose_batch",
                    "batch_id": batch["id"],
                }
                exact_unstarted = {
                    "kind": "declare_job",
                    "batch_id": batch["id"],
                }
                if next_action == exact_unstarted:
                    self._batch_unavailable_reason(
                        _index,
                        batch["id"],
                        outcome,
                    )
                elif (
                    isinstance(next_action, Mapping)
                    and next_action.get("kind") == "dispose_batch"
                    and next_action.get("batch_id") == batch["id"]
                    and set(next_action).issubset(
                        {"basis_record_id", "batch_id", "kind"}
                    )
                ):
                    disposition_basis = self._require_stop_batch_outcome(
                        _index,
                        batch["id"],
                        outcome,
                    )
                    basis_record_id = next_action.get("basis_record_id")
                    if (
                        basis_record_id is not None
                        and basis_record_id != disposition_basis
                    ):
                        raise TransitionError(
                            "Batch disposition differs from its exact preflight basis"
                        )
                else:
                    raise TransitionError(
                        "Batch disposition is not the exact next action"
                    )
            if science["active_job"] is not None or science["active_repair"] is not None:
                raise TransitionError("cannot dispose Batch with active Job or Repair")
            science["active_batch"] = None
            basis_record_id = (
                body.get("next_action", {}).get("basis_record_id")
                if isinstance(body.get("next_action"), Mapping)
                else None
            )
            close_payload = {"outcome": outcome}
            if isinstance(basis_record_id, str):
                close_payload["basis_record_id"] = basis_record_id
            fingerprint = _digest(
                {
                    "batch_id": batch["id"],
                    **close_payload,
                },
                domain="batch-close",
            )
            record = _record(
                kind="batch-close",
                record_id=fingerprint,
                subject=f"Batch:{batch['id']}",
                status=outcome,
                fingerprint=fingerprint,
                payload=close_payload,
            )
            study_id = science["active_study"]
            study = (
                None
                if not isinstance(study_id, str)
                else _index.get("study-open", study_id)
            )
            batch_head = (
                None
                if not isinstance(study_id, str)
                else _index.event_head(f"study-batches:{study_id}")
            )
            if not self.engineering_fixture:
                commitment = (
                    None
                    if study is None
                    else study.payload.get("commitment_batches")
                )
                if (
                    study is None
                    or batch_head is None
                    or batch_head.record_id != batch["id"]
                    or type(commitment) is not int
                    or commitment <= 0
                    or batch_head.sequence > commitment
                ):
                    raise TransitionError(
                        "Batch disposition lost its finite Study commitment"
                    )
                body["next_action"] = (
                    {
                        "batch_close_record_id": fingerprint,
                        "kind": "review_study_continuation",
                        "prior_batch_id": batch["id"],
                        "study_id": study_id,
                    }
                    if batch_head.sequence < commitment
                    else {"kind": "judge_study", "study_id": study_id}
                )
            else:
                body["next_action"] = {
                    "kind": "judge_study",
                    "study_id": study_id,
                }
            return body, [record], {"batch_id": batch["id"], "outcome": outcome}

        return self._commit(
            event_kind="batch_disposed",
            operation_id=operation_id,
            subject="Batch:active",
            payload={"outcome": outcome},
            prepare=prepare,
        )

    def review_study_continuation(
        self,
        *,
        decision: Any,
        operation_id: str,
    ) -> TransitionResult:
        """Close an intermediate boundary or pre-bind one exact next Batch."""

        from axiom_rift.research.study_continuation import (
            StudyContinuationDecision,
            StudyContinuationOutcome,
        )

        self._require_study_close_delivery_guard()
        if not isinstance(decision, StudyContinuationDecision):
            raise TransitionError(
                "decision must be a StudyContinuationDecision"
            )

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            study_id = science.get("active_study")
            if (
                study_id != decision.study_id
                or science.get("active_batch") is not None
                or science.get("active_job") is not None
                or science.get("active_repair") is not None
            ):
                raise TransitionError(
                    "Study continuation requires its stable active Study"
                )
            expected_pending = {
                "batch_close_record_id": decision.prior_batch_close_record_id,
                "kind": "review_study_continuation",
                "prior_batch_id": decision.prior_batch_id,
                "study_id": study_id,
            }
            if body.get("next_action") != expected_pending:
                raise TransitionError(
                    "Study continuation is not the exact pending review"
                )
            study = index.get("study-open", study_id)
            batch = index.get("batch-open", decision.prior_batch_id)
            close = index.get(
                "batch-close", decision.prior_batch_close_record_id
            )
            batch_head = index.event_head(f"study-batches:{study_id}")
            commitment = (
                None
                if study is None
                else study.payload.get("commitment_batches")
            )
            if (
                study is None
                or study.fingerprint != decision.study_hash
                or study.payload.get("question_hash") != decision.question_hash
                or study.payload.get("controlled_chassis_identity")
                != decision.controlled_chassis_identity
                or study.payload.get("portfolio_snapshot_id")
                != decision.portfolio_snapshot_id
                or study.payload.get("portfolio_axis_id")
                != decision.portfolio_axis_id
                or study.payload.get("portfolio_axis_identity")
                != decision.portfolio_axis_identity
                or study.payload.get("portfolio_decision_id")
                != decision.portfolio_decision_id
                or batch is None
                or batch.fingerprint
                != decision.prior_batch_id.removeprefix("batch:")
                or batch.payload.get("spec", {}).get("study_hash")
                != decision.study_hash
                or batch.payload.get("spec", {}).get("stop_rule")
                != decision.stop_rule
                or close is None
                or close.subject != f"Batch:{decision.prior_batch_id}"
                or batch_head is None
                or batch_head.record_id != decision.prior_batch_id
                or type(commitment) is not int
                or commitment <= 1
                or batch_head.sequence >= commitment
            ):
                raise TransitionError(
                    "Study continuation lost its immutable Study or Batch binding"
                )
            portfolio_head = index.event_head(
                f"portfolio:{science['active_mission']}"
            )
            snapshot = index.get(
                "portfolio-snapshot", decision.portfolio_snapshot_id
            )
            if (
                portfolio_head is None
                or portfolio_head.record_id != decision.portfolio_snapshot_id
                or snapshot is None
                or snapshot.subject != f"Mission:{science['active_mission']}"
            ):
                raise TransitionError(
                    "Study continuation Portfolio snapshot is stale"
                )
            axes = tuple(
                axis
                for axis in snapshot.payload.get("axes", ())
                if isinstance(axis, Mapping)
            )
            active_axis = next(
                (
                    axis
                    for axis in axes
                    if axis.get("axis_id") == decision.portfolio_axis_id
                ),
                None,
            )
            axis_resolutions = self._effective_axis_resolutions(
                index,
                axes,
            )
            other_axis_ids = tuple(
                sorted(
                    axis["axis_id"]
                    for axis, resolution in zip(
                        axes,
                        axis_resolutions,
                        strict=True,
                    )
                    if axis.get("axis_id") != decision.portfolio_axis_id
                    and type(axis.get("axis_id")) is str
                    and resolution.decision_option_eligible
                )
            )
            if (
                active_axis is None
                or active_axis.get("axis_identity")
                != decision.portfolio_axis_identity
                or other_axis_ids != decision.other_axis_ids
            ):
                raise TransitionError(
                    "Study continuation differs from the current Portfolio forest"
                )
            bindings = self._batch_continuation_bindings(
                index, decision.prior_batch_id
            )
            if any(
                getattr(decision, name) != bindings[name]
                for name in (
                    "completion_record_ids",
                    "evidence_hashes",
                    "member_executable_ids",
                    "member_job_ids",
                )
            ):
                raise TransitionError(
                    "Study continuation differs from exact Batch evidence"
                )
            if decision.stop_rule_state.value != bindings["stop_rule_state"]:
                raise TransitionError(
                    "Study continuation stop-rule state differs from exact Job judgements"
                )
            for evidence_hash in decision.evidence_hashes:
                try:
                    self.evidence.verify(evidence_hash)
                except (FileNotFoundError, RuntimeError, ValueError) as exc:
                    raise TransitionError(
                        "Study continuation durable evidence is unavailable"
                    ) from exc
            review_basis = {
                (basis.kind, basis.record_id)
                for assessment in decision.quant_team_review.assessments
                for basis in assessment.basis_records
            }
            required_basis = {
                ("portfolio-snapshot", decision.portfolio_snapshot_id),
                (
                    "batch-close",
                    decision.prior_batch_close_record_id,
                ),
                *(
                    ("job-completed", completion_id)
                    for completion_id in decision.completion_record_ids
                ),
            }
            if (
                any(
                    index.get(kind, record_id) is None
                    for kind, record_id in review_basis
                )
                or not required_basis.issubset(review_basis)
            ):
                raise TransitionError(
                    "Study continuation review omits exact durable bases"
                )
            continuation_head = index.event_head(
                f"study-continuation:{study_id}"
            )
            if (
                (continuation_head is None and batch_head.sequence != 1)
                or (
                    continuation_head is not None
                    and continuation_head.sequence != batch_head.sequence - 1
                )
            ):
                raise TransitionError(
                    "Study continuation decision sequence is invalid"
                )
            if decision.outcome is StudyContinuationOutcome.CONTINUE:
                assert decision.next_batch_id is not None
                body["next_action"] = {
                    "batch_id": decision.next_batch_id,
                    "continuation_decision_id": decision.identity,
                    "kind": "freeze_batch",
                    "study_id": study_id,
                }
            else:
                body["next_action"] = {
                    "kind": "judge_study",
                    "study_id": study_id,
                }
            record = _record(
                kind="study-continuation-decision",
                record_id=decision.identity,
                subject=f"Study:{study_id}",
                status=decision.outcome.value,
                fingerprint=decision.identity.removeprefix(
                    "study-continuation-decision:"
                ),
                payload=decision.to_identity_payload(),
                event_stream=f"study-continuation:{study_id}",
                event_sequence=batch_head.sequence,
            )
            return body, [record], {
                "continuation_decision_id": decision.identity,
                "next_batch_id": decision.next_batch_id,
                "outcome": decision.outcome.value,
            }

        return self._commit(
            event_kind="study_continuation_reviewed",
            operation_id=operation_id,
            subject=f"Study:{decision.study_id}",
            payload={
                "decision_id": decision.identity,
                "outcome": decision.outcome.value,
            },
            prepare=prepare,
        )

class StudyKpiProjectionWriterMixin:
    """Own Study KPI derivation, backfill, and projection maintenance."""

    @staticmethod
    def _contains_study_kpi_metric(
        value: Mapping[str, Any],
        name: str,
    ) -> bool:
        return any(
            key == name
            or (
                isinstance(item, Mapping)
                and StudyLifecycleWriterMixin._contains_study_kpi_metric(item, name)
            )
            for key, item in value.items()
        )

    @staticmethod
    def _collect_study_kpi_metric(
        measurements: Sequence[Mapping[str, Any]],
        name: str,
    ) -> int | None:
        observed: list[int | None] = []

        def visit(value: Mapping[str, Any]) -> None:
            for key, item in value.items():
                if key == name:
                    if item is not None and (
                        isinstance(item, bool) or not isinstance(item, int)
                    ):
                        raise TransitionError(
                            f"Study KPI metric {name} is not an integer or null"
                        )
                    observed.append(item)
                elif isinstance(item, Mapping):
                    visit(item)

        for measurement in measurements:
            metrics = measurement.get("metrics")
            if isinstance(metrics, Mapping):
                visit(metrics)
        values = set(observed)
        if not values:
            return None
        if len(values) != 1:
            raise TransitionError(f"Study KPI metric {name} is ambiguous")
        return values.pop()

    def _study_kpi_from_completion(
        self,
        *,
        index: LocalIndex,
        study_id: str,
        completion_record_id: str,
        require_stop_decision: bool = True,
    ) -> dict[str, Any]:
        _require_digest("Study KPI completion record", completion_record_id)
        completion = index.get("job-completed", completion_record_id)
        if completion is None:
            raise TransitionError("Study KPI completion record is unavailable")
        job_id = completion.payload.get("job_id")
        if type(job_id) is not str:
            raise TransitionError("Study KPI completion has no Job identity")
        declaration = index.get("job-declared", job_id)
        if (
            declaration is None
            or declaration.payload.get("study_id") != study_id
        ):
            raise TransitionError("Study KPI completion belongs to another Study")
        batch_head = index.event_head(f"study-batches:{study_id}")
        if (
            batch_head is None
            or declaration.payload.get("batch_id") != batch_head.record_id
        ):
            raise TransitionError(
                "Study KPI completion does not belong to the final Study Batch"
            )
        decisions = tuple(
            record
            for record in index.records_by_fingerprint(completion.fingerprint)
            if record.kind == "job-evidence-decision"
            and record.payload.get("completion_record_id") == completion_record_id
        )
        if require_stop_decision and (
            len(decisions) != 1
            or decisions[0].subject != f"Job:{job_id}"
            or decisions[0].status != "stop_batch"
        ):
            raise TransitionError(
                "Study KPI completion is not the disposition-driving stop_batch evidence"
            )
        scientific = completion.payload.get("scientific")
        if (
            not isinstance(scientific, Mapping)
            or scientific.get("scientific_eligible") is not True
        ):
            engineering = completion.payload.get("engineering_disposition")
            failure = completion.payload.get("failure")
            if isinstance(engineering, Mapping):
                if (
                    completion.status != "failed"
                    or not isinstance(failure, Mapping)
                    or failure.get("failure_kind") != "engineering"
                    or engineering.get("schema")
                    != "engineering_failure_disposition.v1"
                    or engineering.get("job_id") != job_id
                ):
                    raise TransitionError(
                        "Study KPI engineering completion is malformed"
                    )
                spec = declaration.payload.get("spec")
                subject = (
                    None
                    if not isinstance(spec, Mapping)
                    else spec.get("evidence_subject")
                )
                executable_id = (
                    subject.get("id")
                    if isinstance(subject, Mapping)
                    and subject.get("kind") == "Executable"
                    and type(subject.get("id")) is str
                    else None
                )
                return {
                    "completion_record_id": completion_record_id,
                    "executable_id": executable_id,
                    "metrics": {
                        name: None for name in _STUDY_KPI_METRICS
                    },
                    "source": "typed_engineering_failure_completion",
                    "unavailable_reason": "engineering_failure",
                }
            nonperformance = tuple(
                (domain, evidence)
                for domain, evidence in (
                    ("source", completion.payload.get("source")),
                    ("external", completion.payload.get("external")),
                )
                if isinstance(evidence, Mapping)
            )
            if len(nonperformance) != 1:
                raise TransitionError(
                    "Study KPI completion is not validator-derived evidence"
                )
            domain, evidence = nonperformance[0]
            if (
                type(evidence.get("validator_id")) is not str
                or not isinstance(evidence.get("validation_trace"), Mapping)
                or type(evidence.get("result_manifest_hash")) is not str
            ):
                raise TransitionError(
                    "Study KPI non-performance completion lacks validator provenance"
                )
            _require_digest(
                "Study KPI non-performance result",
                evidence["result_manifest_hash"],
            )
            spec = declaration.payload.get("spec")
            subject = None if not isinstance(spec, Mapping) else spec.get(
                "evidence_subject"
            )
            executable_id = (
                subject.get("id")
                if isinstance(subject, Mapping)
                and subject.get("kind") == "Executable"
                and type(subject.get("id")) is str
                else None
            )
            return {
                "completion_record_id": completion_record_id,
                "executable_id": executable_id,
                "metrics": {name: None for name in _STUDY_KPI_METRICS},
                "source": f"validator_derived_{domain}_completion",
                "unavailable_reason": "non_performance_study",
            }
        executable_id = scientific.get("executable_id")
        if type(executable_id) is not str:
            raise TransitionError("Study KPI completion has no Executable identity")
        measurement_hashes = scientific.get("measurement_artifact_hashes")
        if (
            not isinstance(measurement_hashes, list)
            or not measurement_hashes
            or len(set(measurement_hashes)) != len(measurement_hashes)
        ):
            raise TransitionError("Study KPI completion has invalid measurements")
        measurements: list[Mapping[str, Any]] = []
        for measurement_hash in measurement_hashes:
            _require_digest("Study KPI measurement artifact", measurement_hash)
            try:
                measurement = parse_canonical(
                    self.evidence.read_verified(measurement_hash)
                )
            except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                raise TransitionError(
                    "Study KPI measurement artifact is unavailable or invalid"
                ) from exc
            if not isinstance(measurement, Mapping):
                raise TransitionError(
                    "Study KPI measurement belongs to another Job or Executable"
                )
            metric_payload = measurement.get("metrics")
            has_kpi = isinstance(metric_payload, Mapping) and any(
                self._contains_study_kpi_metric(metric_payload, name)
                for name in _STUDY_KPI_METRICS
            )
            binding_mismatch = any(
                field in measurement and measurement.get(field) != expected
                for field, expected in (
                    ("executable_id", executable_id),
                    ("job_id", job_id),
                    ("job_hash", declaration.fingerprint),
                )
            )
            binding_absent_for_kpi = has_kpi and any(
                measurement.get(field) != expected
                for field, expected in (
                    ("executable_id", executable_id),
                    ("job_id", job_id),
                    ("job_hash", declaration.fingerprint),
                )
            )
            if binding_mismatch or binding_absent_for_kpi:
                raise TransitionError(
                    "Study KPI measurement belongs to another Job or Executable"
                )
            measurements.append(measurement)
        metrics = {
            name: self._collect_study_kpi_metric(measurements, name)
            for name in _STUDY_KPI_METRICS
        }
        return {
            "completion_record_id": completion_record_id,
            "executable_id": executable_id,
            "metrics": metrics,
            "source": "scientific_job_completion",
            "unavailable_reason": None,
        }

    @staticmethod
    def _study_kpi_display_id(
        index: LocalIndex,
        executable_id: str | None,
        reserved_display_owners: Mapping[str, str] | None = None,
    ) -> str | None:
        if executable_id is None:
            return None
        _require_ascii("Study KPI Executable identity", executable_id)
        reserved = dict(reserved_display_owners or {})
        if any(
            type(display) is not str
            or not display
            or not display.isascii()
            or type(identity) is not str
            or not identity
            or not identity.isascii()
            for display, identity in reserved.items()
        ):
            raise TransitionError("Reserved Study KPI display binding is invalid")

        def stored_display_owners(display_id: str) -> set[str]:
            owners: set[str] = set()
            for record in index.records_by_payload_text(
                "study-kpi",
                "study_kpi_executable_display_id",
                display_id,
            ):
                prior_identity = record.payload.get("executable_id")
                prior_display = record.payload.get("executable_display_id")
                if (
                    type(prior_identity) is not str
                    or prior_display != display_id
                ):
                    raise TransitionError(
                        "Existing Study KPI display binding is invalid"
                    )
                owners.add(prior_identity)
            if len(owners) > 1:
                raise TransitionError(
                    "Existing Study KPI display id is not unique"
                )
            return owners

        existing_for_identity: set[str] = set()
        for record in index.records_by_payload_text(
            "study-kpi",
            "study_kpi_executable_id",
            executable_id,
        ):
            prior_identity = record.payload.get("executable_id")
            prior_display = record.payload.get("executable_display_id")
            if prior_identity != executable_id or type(prior_display) is not str:
                raise TransitionError(
                    "Existing Study KPI display binding is invalid"
                )
            existing_for_identity.add(prior_display)
        existing_for_identity.update(
            display
            for display, identity in reserved.items()
            if identity == executable_id
        )
        if len(existing_for_identity) > 1:
            raise TransitionError("Executable has inconsistent Study KPI display ids")
        if existing_for_identity:
            display = next(iter(existing_for_identity))
            stored_owners = stored_display_owners(display)
            reserved_owner = reserved.get(display)
            if (
                (stored_owners and stored_owners != {executable_id})
                or (
                    reserved_owner is not None
                    and reserved_owner != executable_id
                )
            ):
                raise TransitionError(
                    "Existing Study KPI display id is not unique"
                )
            return display
        digest = executable_id.removeprefix("executable:")
        for length in range(12, 65, 4):
            display = f"EXE-{digest[:length]}"
            owners = stored_display_owners(display)
            reserved_owner = reserved.get(display)
            if not owners and reserved_owner is None:
                return display
            if len(owners | ({reserved_owner} if reserved_owner else set())) > 1:
                raise TransitionError(
                    "Existing Study KPI display id is not unique"
                )
        raise TransitionError("Executable has no unique Study KPI display id")

    @staticmethod
    def _batch_stop_completion_ids(
        index: LocalIndex,
        batch_id: str,
        inventory: _BatchJobDecisionInventory | None = None,
    ) -> tuple[str, ...]:
        resolved_inventory = (
            inventory
            if inventory is not None
            else _batch_job_decision_inventory(index, batch_id=batch_id)
        )
        if resolved_inventory.batch_id != batch_id:
            raise TransitionError("Batch evidence inventory belongs to another Batch")
        completion_ids: set[str] = set()
        for decision in resolved_inventory.decisions:
            if decision.status != "stop_batch":
                continue
            completion_id = decision.payload.get("completion_record_id")
            if type(completion_id) is not str:
                raise TransitionError(
                    "Batch stop decision lacks its completion identity"
                )
            completion_ids.add(completion_id)
        return tuple(sorted(completion_ids))

    @staticmethod
    def _batch_rejected_replay_preflights(
        index: LocalIndex,
        batch_id: str,
    ) -> tuple[IndexRecord, ...]:
        """Return exact Writer-derived pre-Job implementation rejections."""

        candidates = tuple(
            record
            for record in index.records_by_subject_status(
                f"Batch:{batch_id}",
                "rejected",
            )
            if record.kind == "job-implementation-preflight"
        )
        if len(candidates) > 1:
            raise TransitionError(
                "Batch has ambiguous replay implementation preflight rejection"
            )
        if not candidates:
            return ()
        record = candidates[0]
        payload = record.payload
        batch = index.get("batch-open", batch_id)
        study_id = payload.get("study_id")
        study = (
            None
            if not isinstance(study_id, str)
            else index.get("study-open", study_id)
        )
        family_ids = (
            None
            if batch is None
            else _concurrent_family_executable_ids(batch)
        )
        stream_head = (
            None
            if not isinstance(record.event_stream, str)
            else index.event_head(record.event_stream)
        )
        from axiom_rift.operations.replay_job_implementation_preflight import (
            REPLACEMENT_REQUIRED,
            ReplayJobImplementationPreflightError,
            replay_job_scientific_surface_hash,
        )

        try:
            surface = payload.get("scientific_surface")
            surface_hash = (
                replay_job_scientific_surface_hash(surface)
                if isinstance(surface, Mapping)
                else None
            )
        except ReplayJobImplementationPreflightError as exc:
            raise TransitionError(
                "Batch replay implementation rejection surface is malformed"
            ) from exc
        fingerprint = _digest(
            payload,
            domain="replay-job-implementation-preflight",
        )
        failure_fingerprint = payload.get("failure_fingerprint")
        validation_plans = payload.get("validation_plan_hashes")
        executable_ids = payload.get("executable_ids")
        if (
            payload.get("schema")
            != "replay_job_implementation_preflight.v1"
            or payload.get("batch_id") != batch_id
            or payload.get("outcome") != "rejected"
            or payload.get("remediation_kind") != REPLACEMENT_REQUIRED
            or payload.get("replacement_for_preflight_id") is not None
            or payload.get("source_closure_authority") is not None
            or payload.get("reason_code")
            not in {
                "historical_replay_lineage_invalid",
                "implementation_manifest_invalid",
                "source_closure_invalid",
            }
            or type(payload.get("failure_detail")) is not str
            or not payload["failure_detail"]
            or not payload["failure_detail"].isascii()
            or type(failure_fingerprint) is not str
            or len(failure_fingerprint) != 64
            or any(
                character not in "0123456789abcdef"
                for character in failure_fingerprint
            )
            or payload.get("artifact_hashes") != []
            or payload.get("component_implementation_hashes") != []
            or study is None
            or study.payload.get("mission_id") != payload.get("mission_id")
            or study.payload.get("replay_obligation_ids")
            != payload.get("replay_obligation_ids")
            or not isinstance(family_ids, tuple)
            or not isinstance(executable_ids, list)
            or sorted(executable_ids) != sorted(family_ids)
            or not isinstance(validation_plans, list)
            or len(validation_plans) != len(executable_ids)
            or validation_plans != sorted(set(validation_plans))
            or surface_hash != payload.get("scientific_surface_hash")
            or record.fingerprint != fingerprint
            or record.record_id
            != f"job-implementation-preflight:{fingerprint}"
            or record.event_stream
            != f"replay-job-implementation-preflight-batch:{batch_id}"
            or record.event_sequence != 1
            or stream_head is None
            or stream_head.record_id != record.record_id
        ):
            raise TransitionError(
                "Batch replay implementation rejection is malformed"
            )
        return (record,)

    @classmethod
    def _require_stop_batch_outcome(
        cls,
        index: LocalIndex,
        batch_id: str,
        outcome: str,
        inventory: _BatchJobDecisionInventory | None = None,
    ) -> str:
        """Bind a final stop decision to the matching operational Batch outcome."""

        resolved_inventory = (
            inventory
            if inventory is not None
            else _batch_job_decision_inventory(index, batch_id=batch_id)
        )
        rejected_preflights = cls._batch_rejected_replay_preflights(
            index,
            batch_id,
        )
        completion_ids = cls._batch_stop_completion_ids(
            index,
            batch_id,
            resolved_inventory,
        )
        if rejected_preflights:
            if completion_ids or resolved_inventory.decisions:
                raise TransitionError(
                    "pre-Job implementation rejection conflicts with Batch Job evidence"
                )
            if outcome != "not_evaluable":
                raise TransitionError(
                    "pre-Job implementation rejection requires not_evaluable Batch outcome"
                )
            return rejected_preflights[0].record_id
        if len(completion_ids) != 1:
            raise TransitionError(
                "Batch disposition requires exactly one final stop_batch completion"
            )
        completion_id = completion_ids[0]
        completion = index.get("job-completed", completion_id)
        if completion is None:
            raise TransitionError("Batch stop completion is unavailable")
        engineering = completion.payload.get("engineering_disposition")
        failure = completion.payload.get("failure")
        typed_engineering = (
            completion.status == "failed"
            and isinstance(engineering, Mapping)
            and engineering.get("schema")
            == "engineering_failure_disposition.v1"
            and isinstance(failure, Mapping)
            and failure.get("failure_kind") == "engineering"
        )
        if typed_engineering and outcome != "engineering_failure":
            raise TransitionError(
                "Typed unrecovered engineering completion requires the "
                "engineering_failure Batch outcome"
            )
        if not typed_engineering and outcome == "engineering_failure":
            raise TransitionError(
                "Engineering-failure Batch outcome requires its typed unrecovered "
                "completion"
            )
        return completion_id

    @staticmethod
    def _batch_unavailable_reason(
        index: LocalIndex,
        batch_id: str,
        outcome: str,
        inventory: _BatchJobDecisionInventory | None = None,
        *,
        allow_legacy_started_failure: bool = False,
    ) -> str:
        if type(allow_legacy_started_failure) is not bool:
            raise TransitionError(
                "legacy started-Batch failure compatibility flag must be bool"
            )
        if inventory is not None and inventory.batch_id != batch_id:
            raise TransitionError("Batch evidence inventory belongs to another Batch")
        rejected_preflights = StudyLifecycleWriterMixin._batch_rejected_replay_preflights(
            index,
            batch_id,
        )
        budget_head = index.event_head(f"batch-budget:{batch_id}")
        trial_head = index.event_head(f"batch-trials:{batch_id}")
        started = budget_head is not None or trial_head is not None
        if rejected_preflights:
            resolved_inventory = (
                inventory
                if inventory is not None
                else _batch_job_decision_inventory(index, batch_id=batch_id)
            )
            if (
                outcome != "not_evaluable"
                or resolved_inventory.decisions
                or StudyLifecycleWriterMixin._batch_stop_completion_ids(
                    index,
                    batch_id,
                    resolved_inventory,
                )
            ):
                raise TransitionError(
                    "Batch implementation rejection has conflicting disposition evidence"
                )
            return (
                f"{'started' if started else 'unstarted'}_batch_"
                "implementation_authority_invalid_"
                "without_final_validator_completion"
            )
        if not started:
            if outcome not in {"not_evaluable", "stopped_early"}:
                raise TransitionError(
                    "Unstarted Batch requires a typed unavailable disposition"
                )
        elif outcome == "budget_exhausted":
            batch_record = index.get("batch-open", batch_id)
            budget_record = index.get(
                budget_head.record_kind,
                budget_head.record_id,
            ) if budget_head is not None else None
            spec = None if batch_record is None else batch_record.payload.get("spec")
            budget = None if budget_record is None else budget_record.payload
            trial_count = 0 if trial_head is None else trial_head.sequence
            if (
                not isinstance(spec, Mapping)
                or (
                    (
                        not isinstance(budget, Mapping)
                        or (
                            budget.get("compute_seconds")
                            != spec.get("max_compute_seconds")
                            and budget.get("wall_seconds")
                            != spec.get("max_wall_seconds")
                        )
                    )
                    and trial_count != spec.get("max_trials")
                )
            ):
                raise TransitionError("Batch budget is not exhausted")
        elif outcome in {
            "engineering_failure",
            "not_evaluable",
            "stopped_early",
        }:
            if not allow_legacy_started_failure:
                raise TransitionError(
                    "Started Batch without final validator evidence requires a "
                    "disposition-driving stop_batch completion; continue_batch "
                    "keeps Repair or bounded work open"
                )
            if outcome == "stopped_early":
                return (
                    "started_batch_stopped_early_"
                    "without_final_validator_completion"
                )
            resolved_inventory = (
                inventory
                if inventory is not None
                else _batch_job_decision_inventory(index, batch_id=batch_id)
            )
            decisions = [
                decision
                for decision in resolved_inventory.decisions
                if decision.status == "continue_batch"
            ]
            latest = (
                None
                if not decisions
                else max(
                    decisions,
                    key=lambda item: (
                        -1
                        if item.authority_sequence is None
                        else item.authority_sequence
                    ),
                )
            )
            completion_id = (
                None
                if latest is None
                else latest.payload.get("completion_record_id")
            )
            completion = (
                None
                if not isinstance(completion_id, str)
                else index.get("job-completed", completion_id)
            )
            failure = None if completion is None else completion.payload.get("failure")
            expected_status = "failed" if outcome == "engineering_failure" else "not_evaluable"
            expected_failure = "engineering" if outcome == "engineering_failure" else "not_evaluable"
            if (
                completion is None
                or completion.status != expected_status
                or not isinstance(failure, Mapping)
                or failure.get("failure_kind") != expected_failure
                or isinstance(completion.payload.get("scientific"), Mapping)
                or isinstance(completion.payload.get("source"), Mapping)
                or isinstance(completion.payload.get("external"), Mapping)
            ):
                raise TransitionError(
                    f"Batch {outcome} lacks its final non-scientific failure basis"
                )
        else:
            raise TransitionError(
                "Started Batch without a final stop completion requires a typed "
                "unavailable disposition"
            )
        return (
            f"{'started' if started else 'unstarted'}_batch_{outcome}_"
            "without_final_validator_completion"
        )

    @staticmethod
    def _legacy_started_batch_failure_allowed(
        *,
        index: LocalIndex,
        kpi_record: IndexRecord,
    ) -> bool:
        """Limit read compatibility to KPI sources predating typed Batch exit."""

        activation = index.get(
            "operation",
            _TYPED_STARTED_BATCH_EXIT_ACTIVATION_OPERATION_ID,
        )
        if activation is None:
            # Before the additive activation exists, old immutable KPI rows
            # must remain readable so the migration itself can recover safely.
            return True
        activation_sequence = activation.authority_sequence
        if (
            activation.kind != "operation"
            or activation.status != "success"
            or activation.payload.get("event_kind") != "authority_migrated"
            or type(activation_sequence) is not int
        ):
            raise TransitionError(
                "typed started-Batch exit activation boundary is invalid"
            )
        payload = kpi_record.payload
        provenance = payload.get("provenance")
        if provenance == "historical_backfill":
            source_sequence = payload.get("historical_study_close_revision")
        else:
            source_sequence = kpi_record.authority_sequence
            if type(source_sequence) is not int:
                event_id = kpi_record.authority_event_id
                event = (
                    None
                    if type(event_id) is not str
                    else index.get("journal-event", event_id)
                )
                source_sequence = (
                    None if event is None else event.authority_sequence
                )
        if type(source_sequence) is not int:
            raise TransitionError(
                "legacy started-Batch KPI lacks its authority sequence"
            )
        return source_sequence < activation_sequence

    @staticmethod
    def _require_scientific_study_outcome(
        *,
        completion: IndexRecord,
        outcome: str,
    ) -> None:
        scientific = completion.payload.get("scientific")
        if (
            not isinstance(scientific, Mapping)
            or scientific.get("scientific_eligible") is not True
        ):
            raise TransitionError(
                "Study outcome basis is not an eligible scientific completion"
            )
        verdict = scientific.get("verdict")
        adjudication = scientific.get("adjudication")
        if adjudication is None:
            evidence_class = {
                "passed": "positive",
                "failed": "negative",
                "not_evaluable": "unavailable",
            }.get(verdict)
        else:
            state = (
                adjudication.get("state")
                if isinstance(adjudication, Mapping)
                else None
            )
            expected_verdict = {
                "confirmed": "passed",
                "contradicted": "failed",
                "frontier": "passed",
                "not_evaluable": "not_evaluable",
                "partial_positive": "not_evaluable",
                "unresolved": "not_evaluable",
            }.get(state)
            evidence_class = {
                "confirmed": "positive",
                "frontier": "positive",
                "partial_positive": "positive",
                "contradicted": "negative",
                "not_evaluable": "unavailable",
                "unresolved": "unavailable",
            }.get(state)
            if expected_verdict != verdict:
                evidence_class = None
        allowed_outcomes = {
            "positive": {"preserved", "supported"},
            "negative": {"not_supported", "pruned"},
            "unavailable": {"evidence_gap", "not_evaluable"},
        }
        if evidence_class is None:
            raise TransitionError(
                "Study outcome basis has malformed scientific adjudication"
            )
        if outcome not in allowed_outcomes[evidence_class]:
            raise TransitionError(
                "Study outcome conflicts with its disposition-driving scientific "
                "adjudication"
            )

    def _study_kpi_payload(
        self,
        *,
        index: LocalIndex,
        study_id: str,
        outcome: str,
        completion_record_id: str | None,
        closed_at_utc: str,
    ) -> dict[str, Any] | None:
        if self.engineering_fixture:
            return None
        if completion_record_id is None:
            batch_head = index.event_head(f"study-batches:{study_id}")
            if batch_head is None:
                raise TransitionError(
                    "Real Study close requires a disposed Batch"
                )
            batch_id = batch_head.record_id
            job_inventory = _batch_job_decision_inventory(
                index,
                batch_id=batch_id,
            )
            if self._batch_stop_completion_ids(
                index,
                batch_id,
                job_inventory,
            ):
                raise TransitionError(
                    "Study with a final stop decision requires its validator completion"
                )
            close_records = tuple(
                record
                for status in _BATCH_OUTCOMES
                for record in index.records_by_subject_status(
                    f"Batch:{batch_id}", status
                )
                if record.kind == "batch-close"
            )
            close_status = None if len(close_records) != 1 else close_records[0].status
            if (
                close_status is None
                or outcome not in {"evidence_gap", "not_evaluable"}
            ):
                raise TransitionError(
                    "Study KPI unavailable state is not writer-derived"
                )
            unavailable_reason = self._batch_unavailable_reason(
                index,
                batch_id,
                close_status,
                job_inventory,
            )
            source = {
                "completion_record_id": None,
                "executable_id": None,
                "executable_display_id": None,
                "metrics": {name: None for name in _STUDY_KPI_METRICS},
                "source": "writer_derived_unavailable",
                "unavailable_reason": unavailable_reason,
            }
        else:
            source = self._study_kpi_from_completion(
                index=index,
                study_id=study_id,
                completion_record_id=completion_record_id,
            )
            if source["source"] == "scientific_job_completion":
                completion = index.get("job-completed", completion_record_id)
                if completion is None:
                    raise TransitionError(
                        "Study outcome scientific completion is unavailable"
                    )
                self._require_scientific_study_outcome(
                    completion=completion,
                    outcome=outcome,
                )
            elif (
                source["source"] == "typed_engineering_failure_completion"
                and outcome not in {"evidence_gap", "not_evaluable"}
            ):
                raise TransitionError(
                    "Engineering Study outcome cannot become a scientific outcome"
                )
            if (
                source["source"]
                in {
                    "validator_derived_source_completion",
                    "validator_derived_external_completion",
                }
                and outcome
                not in {"preserved", "pruned", "evidence_gap", "not_evaluable"}
            ):
                raise TransitionError(
                    "Non-performance Study KPI completion is incompatible with the outcome"
                )
            source["executable_display_id"] = self._study_kpi_display_id(
                index,
                source["executable_id"],
            )
        head = index.event_head("study-kpi")
        sequence = 1 if head is None else head.sequence + 1
        payload = {
            **source,
            "historical_study_close_event_id": None,
            "historical_study_close_record_id": None,
            "historical_study_close_revision": None,
            "outcome": outcome,
            "provenance": "prospective_close",
            "sequence": sequence,
            "study_id": study_id,
        }
        try:
            StudyKpiProjectionRow(
                sequence=sequence,
                closed_at_utc=closed_at_utc,
                study_id=study_id,
                executable_id=payload["executable_id"],
                executable_display_id=payload["executable_display_id"],
                net_profit_micropoints=payload["metrics"][
                    "net_profit_micropoints"
                ],
                median_fold_profit_factor_milli=payload["metrics"][
                    "median_fold_profit_factor_milli"
                ],
                trade_count=payload["metrics"]["trade_count"],
                monthly_realized_exit_drawdown_share_of_gross_profit_ppm=payload[
                    "metrics"
                ]["monthly_realized_exit_drawdown_share_of_gross_profit_ppm"],
                outcome=outcome,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TransitionError("Study KPI row is not renderable") from exc
        return payload

    @staticmethod
    def _study_batch_close_record(
        index: LocalIndex,
        batch_id: str,
    ) -> IndexRecord:
        close_records = tuple(
            record
            for status in _BATCH_OUTCOMES
            for record in index.records_by_subject_status(
                f"Batch:{batch_id}",
                status,
            )
            if record.kind == "batch-close"
        )
        if len(close_records) != 1:
            raise TransitionError("Historical Study Batch close is ambiguous")
        return close_records[0]

    def _historical_engineering_unavailable_source(
        self,
        *,
        index: LocalIndex,
        study_id: str,
        batch_id: str,
        completion_record_id: str,
    ) -> dict[str, Any]:
        completion = index.get("job-completed", completion_record_id)
        job_id = None if completion is None else completion.payload.get("job_id")
        declaration = (
            None
            if not isinstance(job_id, str)
            else index.get("job-declared", job_id)
        )
        decisions = (
            ()
            if completion is None
            else tuple(
                record
                for record in index.records_by_fingerprint(completion.fingerprint)
                if record.kind == "job-evidence-decision"
                and record.payload.get("completion_record_id")
                == completion_record_id
            )
        )
        failure = None if completion is None else completion.payload.get("failure")
        spec = None if declaration is None else declaration.payload.get("spec")
        evidence_subject = (
            None if not isinstance(spec, Mapping) else spec.get("evidence_subject")
        )
        executable_id = (
            evidence_subject.get("id")
            if isinstance(evidence_subject, Mapping)
            and evidence_subject.get("kind") == "Executable"
            and type(evidence_subject.get("id")) is str
            else None
        )
        batch_close = self._study_batch_close_record(index, batch_id)
        if (
            completion is None
            or completion.status != "failed"
            or not isinstance(job_id, str)
            or declaration is None
            or declaration.payload.get("study_id") != study_id
            or declaration.payload.get("batch_id") != batch_id
            or len(decisions) != 1
            or decisions[0].subject != f"Job:{job_id}"
            or decisions[0].status != "stop_batch"
            or not isinstance(failure, Mapping)
            or failure.get("failure_kind") != "engineering"
            or executable_id is None
            or isinstance(completion.payload.get("scientific"), Mapping)
            or isinstance(completion.payload.get("source"), Mapping)
            or isinstance(completion.payload.get("external"), Mapping)
            or batch_close.status != "engineering_failure"
        ):
            raise TransitionError(
                "Historical Study KPI lacks an exact engineering-failure basis"
            )
        return {
            "completion_record_id": completion_record_id,
            "executable_id": executable_id,
            "executable_display_id": None,
            "metrics": {name: None for name in _STUDY_KPI_METRICS},
            "source": "historical_writer_verified_unavailable",
            "unavailable_reason": (
                "historical_final_non_scientific_engineering_failure"
            ),
        }

    def _historical_study_kpi_payload(
        self,
        *,
        index: LocalIndex,
        close_record: IndexRecord,
        sequence: int,
        reserved_display_owners: Mapping[str, str],
    ) -> dict[str, Any]:
        study_id = close_record.subject.removeprefix("Study:")
        close_event = index.get(
            "journal-event",
            close_record.authority_event_id or "",
        )
        study_open = index.get("study-open", study_id)
        batch_head = index.event_head(f"study-batches:{study_id}")
        if (
            close_record.kind != "study-close"
            or close_record.subject != f"Study:{study_id}"
            or close_record.status not in _STUDY_OUTCOMES
            or close_record.authority_sequence is None
            or close_event is None
            or close_event.status != "study_closed"
            or close_event.authority_sequence != close_record.authority_sequence
            or close_event.authority_event_id != close_record.authority_event_id
            or study_open is None
            or batch_head is None
        ):
            raise TransitionError("Historical Study close provenance is invalid")
        batch_id = batch_head.record_id
        job_inventory = _batch_job_decision_inventory(
            index,
            batch_id=batch_id,
        )
        completion_ids = self._batch_stop_completion_ids(
            index,
            batch_id,
            job_inventory,
        )
        if len(completion_ids) > 1:
            raise TransitionError("Historical Study has multiple final completions")
        if completion_ids:
            completion_record_id = completion_ids[0]
            try:
                source = self._study_kpi_from_completion(
                    index=index,
                    study_id=study_id,
                    completion_record_id=completion_record_id,
                )
            except TransitionError:
                source = self._historical_engineering_unavailable_source(
                    index=index,
                    study_id=study_id,
                    batch_id=batch_id,
                    completion_record_id=completion_record_id,
                )
        else:
            batch_close = self._study_batch_close_record(index, batch_id)
            unavailable_reason = self._batch_unavailable_reason(
                index,
                batch_id,
                batch_close.status,
                job_inventory,
                allow_legacy_started_failure=True,
            )
            source = {
                "completion_record_id": None,
                "executable_id": None,
                "executable_display_id": None,
                "metrics": {name: None for name in _STUDY_KPI_METRICS},
                "source": "writer_derived_unavailable",
                "unavailable_reason": unavailable_reason,
            }
        if (
            source["source"]
            in {
                "validator_derived_source_completion",
                "validator_derived_external_completion",
            }
            and close_record.status
            not in {"preserved", "pruned", "evidence_gap", "not_evaluable"}
        ):
            raise TransitionError(
                "Historical non-performance completion is incompatible with its outcome"
            )
        if (
            source["source"]
            in {
                "writer_derived_unavailable",
                "historical_writer_verified_unavailable",
            }
            and close_record.status
            not in {"evidence_gap", "not_evaluable", "pruned"}
        ):
            raise TransitionError(
                "Historical unavailable KPI is incompatible with its outcome"
            )
        source["executable_display_id"] = self._study_kpi_display_id(
            index,
            source["executable_id"],
            reserved_display_owners,
        )
        payload = {
            **source,
            "historical_study_close_event_id": close_record.authority_event_id,
            "historical_study_close_record_id": close_record.record_id,
            "historical_study_close_revision": close_record.authority_sequence,
            "outcome": close_record.status,
            "provenance": "historical_backfill",
            "sequence": sequence,
            "study_id": study_id,
        }
        try:
            StudyKpiProjectionRow(
                sequence=sequence,
                closed_at_utc=close_event.payload["occurred_at_utc"],
                study_id=study_id,
                executable_id=payload["executable_id"],
                executable_display_id=payload["executable_display_id"],
                net_profit_micropoints=payload["metrics"][
                    "net_profit_micropoints"
                ],
                median_fold_profit_factor_milli=payload["metrics"][
                    "median_fold_profit_factor_milli"
                ],
                trade_count=payload["metrics"]["trade_count"],
                monthly_realized_exit_drawdown_share_of_gross_profit_ppm=payload[
                    "metrics"
                ]["monthly_realized_exit_drawdown_share_of_gross_profit_ppm"],
                outcome=close_record.status,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TransitionError(
                "Historical Study KPI row is not renderable"
            ) from exc
        return payload

    def backfill_historical_study_kpis(
        self,
        *,
        operation_id: str = _STUDY_KPI_BACKFILL_OPERATION_ID,
    ) -> TransitionResult:
        """Project pre-activation Study closes into one evidence-bound ledger."""

        if self.engineering_fixture:
            raise TransitionError("engineering fixtures cannot backfill real Study KPIs")
        _require_ascii("operation_id", operation_id)

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            if (
                science["active_mission"] is not None
                or any(
                    science[name] is not None
                    for name in (
                        "active_initiative",
                        "active_study",
                        "active_batch",
                        "active_job",
                        "active_repair",
                        "active_lineage",
                        "active_executable",
                        "active_release",
                        "active_holdout_evaluation",
                    )
                )
                or body.get("next_action", {}).get("kind") != "await_root_goal"
            ):
                raise TransitionError(
                    "Historical Study KPI backfill requires the Mission-admission boundary"
                )
            activation = index.get(
                "operation",
                _STUDY_KPI_ACTIVATION_OPERATION_ID,
            )
            activation_event = (
                None
                if activation is None or activation.authority_event_id is None
                else index.get("journal-event", activation.authority_event_id)
            )
            if (
                activation is None
                or activation.authority_sequence is None
                or activation_event is None
                or activation_event.status != "authority_migrated"
                or activation.payload.get("event_kind") != "authority_migrated"
            ):
                raise TransitionError("Study KPI activation authority is unavailable")
            if index.count_by_kind("study-kpi"):
                raise TransitionError("Historical Study KPI backfill is already populated")
            all_closes = tuple(index.records_by_kind("study-close"))
            historical_closes = tuple(
                sorted(
                    (
                        record
                        for record in all_closes
                        if record.authority_sequence is not None
                        and record.authority_sequence
                        < activation.authority_sequence
                    ),
                    key=lambda record: record.authority_sequence or 0,
                )
            )
            historical_open_ids = {
                record.record_id
                for record in index.records_by_kind("study-open")
                if record.authority_sequence is not None
                and record.authority_sequence < activation.authority_sequence
            }
            historical_close_ids = {
                record.subject.removeprefix("Study:")
                for record in historical_closes
            }
            if (
                not historical_closes
                or len(historical_close_ids) != len(historical_closes)
                or historical_open_ids != historical_close_ids
                or index.event_head("study-kpi") is not None
            ):
                raise TransitionError("Historical Study close set is incomplete")
            if any(
                record.authority_sequence is not None
                and record.authority_sequence >= activation.authority_sequence
                for record in all_closes
            ):
                raise TransitionError(
                    "A prospective Study close is missing its mandatory KPI record"
                )
            reserved_display_owners: dict[str, str] = {}
            row_records: list[IndexRecord] = []
            row_fingerprints: list[str] = []
            for sequence, close_record in enumerate(historical_closes, start=1):
                payload = self._historical_study_kpi_payload(
                    index=index,
                    close_record=close_record,
                    sequence=sequence,
                    reserved_display_owners=reserved_display_owners,
                )
                display_id = payload["executable_display_id"]
                executable_id = payload["executable_id"]
                if display_id is not None and executable_id is not None:
                    reserved_display_owners[display_id] = executable_id
                fingerprint = _digest(payload, domain="study-kpi")
                row_fingerprints.append(fingerprint)
                row_records.append(
                    _record(
                        kind="study-kpi",
                        record_id=payload["study_id"],
                        subject=f"Study:{payload['study_id']}",
                        status=payload["outcome"],
                        fingerprint=fingerprint,
                        payload=payload,
                        event_stream="study-kpi",
                        event_sequence=sequence,
                    )
                )
            manifest_payload = {
                "activation_event_id": activation.authority_event_id,
                "activation_operation_id": _STUDY_KPI_ACTIVATION_OPERATION_ID,
                "activation_revision": activation.authority_sequence,
                "cutoff_revision": activation.authority_sequence - 1,
                "holdout_delta": 0,
                "row_fingerprints": row_fingerprints,
                "row_count": len(row_records),
                "schema": "study_kpi_historical_backfill.v1",
                "scientific_claim": "none",
                "sequence_end": len(row_records),
                "sequence_start": 1,
                "source_study_close_record_ids": [
                    record.record_id for record in historical_closes
                ],
                "trial_delta": 0,
            }
            backfill_record_id = _digest(
                manifest_payload,
                domain="study-kpi-backfill",
            )
            backfill_record = _record(
                kind="study-kpi-backfill",
                record_id=backfill_record_id,
                subject="StudyKpi:historical",
                status="complete",
                fingerprint=backfill_record_id,
                payload=manifest_payload,
            )
            return body, [backfill_record, *row_records], {
                "backfill_record_id": backfill_record_id,
                "row_count": len(row_records),
                "sequence_end": len(row_records),
                "sequence_start": 1,
            }

        transition = self._commit(
            event_kind="study_kpi_backfilled",
            operation_id=operation_id,
            subject="StudyKpi:historical",
            payload={
                "activation_operation_id": _STUDY_KPI_ACTIVATION_OPERATION_ID,
            },
            prepare=prepare,
        )
        self.rebuild_study_kpi_projection()
        return transition

    def rebuild_study_kpi_projection(self) -> bool:
        """Explicitly materialize the lag-tolerant Markdown navigation view.

        This intentionally performs a complete authority scan.  Routine Study
        close never calls it; the immutable ``study-kpi`` Journal record is the
        close-time authority and Git delivery validates only the bounded suffix.
        """

        rows: list[StudyKpiProjectionRow] = []
        with WriterLock(self.lock_path):
            with self._open_authoritative_index() as index:
                self._require_stable_locked(index)
                historical_backfills_by_event: dict[str, list[IndexRecord]] = {}
                for backfill in index.records_by_subject_status(
                    "StudyKpi:historical",
                    "complete",
                ):
                    if (
                        backfill.kind == "study-kpi-backfill"
                        and isinstance(backfill.authority_event_id, str)
                    ):
                        historical_backfills_by_event.setdefault(
                            backfill.authority_event_id,
                            [],
                        ).append(backfill)
                for record in index.records_by_kind("study-kpi"):
                    payload = record.payload
                    expected_fields = {
                        "completion_record_id",
                        "executable_id",
                        "executable_display_id",
                        "historical_study_close_event_id",
                        "historical_study_close_record_id",
                        "historical_study_close_revision",
                        "metrics",
                        "outcome",
                        "provenance",
                        "sequence",
                        "source",
                        "study_id",
                        "unavailable_reason",
                    }
                    metrics = payload.get("metrics")
                    sequence = payload.get("sequence")
                    study_id = payload.get("study_id")
                    outcome = payload.get("outcome")
                    provenance = payload.get("provenance")
                    if (
                        set(payload) != expected_fields
                        or not isinstance(metrics, Mapping)
                        or set(metrics) != set(_STUDY_KPI_METRICS)
                        or type(sequence) is not int
                        or record.record_id != study_id
                        or record.subject != f"Study:{study_id}"
                        or record.status != outcome
                        or record.event_stream != "study-kpi"
                        or record.event_sequence != sequence
                        or record.authority_event_id is None
                    ):
                        raise TransitionError("Study KPI record projection is invalid")
                    source = payload.get("source")
                    completion_record_id = payload.get("completion_record_id")
                    executable_id = payload.get("executable_id")
                    executable_display_id = payload.get("executable_display_id")
                    unavailable_reason = payload.get("unavailable_reason")
                    historical_close_event_id = payload.get(
                        "historical_study_close_event_id"
                    )
                    historical_close_record_id = payload.get(
                        "historical_study_close_record_id"
                    )
                    historical_close_revision = payload.get(
                        "historical_study_close_revision"
                    )
                    if source == "scientific_job_completion":
                        if (
                            type(completion_record_id) is not str
                            or type(executable_id) is not str
                            or type(executable_display_id) is not str
                            or unavailable_reason is not None
                        ):
                            raise TransitionError("Study KPI evidence source is invalid")
                    elif source in {
                        "validator_derived_source_completion",
                        "validator_derived_external_completion",
                    }:
                        if (
                            type(completion_record_id) is not str
                            or (
                                executable_id is not None
                                and type(executable_id) is not str
                            )
                            or (
                                executable_id is None
                                and executable_display_id is not None
                            )
                            or (
                                executable_id is not None
                                and type(executable_display_id) is not str
                            )
                            or unavailable_reason != "non_performance_study"
                            or any(value is not None for value in metrics.values())
                        ):
                            raise TransitionError(
                                "Study KPI non-performance source is invalid"
                            )
                    elif source == "typed_engineering_failure_completion":
                        derived_source = (
                            None
                            if type(completion_record_id) is not str
                            else self._study_kpi_from_completion(
                                index=index,
                                study_id=study_id,
                                completion_record_id=completion_record_id,
                            )
                        )
                        derived_display_id = (
                            None
                            if derived_source is None
                            else self._study_kpi_display_id(
                                index,
                                derived_source["executable_id"],
                            )
                        )
                        if (
                            derived_source is None
                            or derived_source["source"] != source
                            or derived_source["completion_record_id"]
                            != completion_record_id
                            or derived_source["executable_id"] != executable_id
                            or derived_display_id != executable_display_id
                            or derived_source["metrics"] != dict(metrics)
                            or derived_source["unavailable_reason"]
                            != unavailable_reason
                            or outcome not in {"evidence_gap", "not_evaluable"}
                        ):
                            raise TransitionError(
                                "Study KPI engineering failure source is invalid"
                            )
                    elif source == "writer_derived_unavailable":
                        allowed_reasons = {
                            "unstarted_batch_not_evaluable_without_final_validator_completion": "not_evaluable",
                            "unstarted_batch_stopped_early_without_final_validator_completion": "stopped_early",
                            "unstarted_batch_implementation_authority_invalid_without_final_validator_completion": "not_evaluable",
                            "started_batch_budget_exhausted_without_final_validator_completion": "budget_exhausted",
                            "started_batch_stopped_early_without_final_validator_completion": "stopped_early",
                            "started_batch_not_evaluable_without_final_validator_completion": "not_evaluable",
                            "started_batch_engineering_failure_without_final_validator_completion": "engineering_failure",
                            "started_batch_implementation_authority_invalid_without_final_validator_completion": "not_evaluable",
                        }
                        batch_head = index.event_head(
                            f"study-batches:{study_id}"
                        )
                        reason_status = allowed_reasons.get(unavailable_reason)
                        job_inventory = (
                            None
                            if batch_head is None or reason_status is None
                            else _batch_job_decision_inventory(
                                index,
                                batch_id=batch_head.record_id,
                            )
                        )
                        close_records = (
                            ()
                            if batch_head is None or reason_status is None
                            else tuple(
                                item
                                for item in index.records_by_subject_status(
                                    f"Batch:{batch_head.record_id}",
                                    reason_status,
                                )
                                if item.kind == "batch-close"
                            )
                        )
                        derived_reason = (
                            None
                            if batch_head is None or reason_status is None
                            else self._batch_unavailable_reason(
                                index,
                                batch_head.record_id,
                                reason_status,
                                job_inventory,
                                allow_legacy_started_failure=(
                                    self._legacy_started_batch_failure_allowed(
                                        index=index,
                                        kpi_record=record,
                                    )
                                ),
                            )
                        )
                        if (
                            completion_record_id is not None
                            or executable_id is not None
                            or executable_display_id is not None
                            or any(value is not None for value in metrics.values())
                            or reason_status is None
                            or outcome
                            not in {"evidence_gap", "not_evaluable", "pruned"}
                            or batch_head is None
                            or derived_reason != unavailable_reason
                            or self._batch_stop_completion_ids(
                                index,
                                batch_head.record_id,
                                job_inventory,
                            )
                            or len(close_records) != 1
                        ):
                            raise TransitionError(
                                "Study KPI Writer-derived unavailable source is invalid"
                            )
                    elif source == "historical_writer_verified_unavailable":
                        batch_head = index.event_head(
                            f"study-batches:{study_id}"
                        )
                        derived_source = (
                            None
                            if batch_head is None
                            or type(completion_record_id) is not str
                            else self._historical_engineering_unavailable_source(
                                index=index,
                                study_id=study_id,
                                batch_id=batch_head.record_id,
                                completion_record_id=completion_record_id,
                            )
                        )
                        if (
                            provenance != "historical_backfill"
                            or type(executable_id) is not str
                            or type(executable_display_id) is not str
                            or any(value is not None for value in metrics.values())
                            or unavailable_reason
                            != "historical_final_non_scientific_engineering_failure"
                            or derived_source is None
                            or derived_source["executable_id"] != executable_id
                            or derived_source["unavailable_reason"]
                            != unavailable_reason
                        ):
                            raise TransitionError(
                                "Historical Study KPI unavailable source is invalid"
                            )
                    else:
                        raise TransitionError("Study KPI source is not typed")
                    authority_event = index.get(
                        "journal-event",
                        record.authority_event_id,
                    )
                    if provenance == "prospective_close":
                        if (
                            historical_close_event_id is not None
                            or historical_close_record_id is not None
                            or historical_close_revision is not None
                            or authority_event is None
                            or authority_event.status != "study_closed"
                        ):
                            raise TransitionError(
                                "Prospective Study KPI close provenance is invalid"
                            )
                        event = authority_event
                    elif provenance == "historical_backfill":
                        event = (
                            None
                            if type(historical_close_event_id) is not str
                            else index.get(
                                "journal-event",
                                historical_close_event_id,
                            )
                        )
                        source_close = (
                            None
                            if type(historical_close_record_id) is not str
                            else index.get(
                                "study-close",
                                historical_close_record_id,
                            )
                        )
                        backfill_records = tuple(
                            historical_backfills_by_event.get(
                                record.authority_event_id,
                                (),
                            )
                        )
                        if (
                            authority_event is None
                            or authority_event.status != "study_kpi_backfilled"
                            or type(historical_close_revision) is not int
                            or event is None
                            or event.status != "study_closed"
                            or event.authority_sequence
                            != historical_close_revision
                            or source_close is None
                            or source_close.authority_event_id
                            != historical_close_event_id
                            or source_close.authority_sequence
                            != historical_close_revision
                            or source_close.subject != f"Study:{study_id}"
                            or source_close.status != outcome
                            or len(backfill_records) != 1
                            or record.fingerprint
                            not in backfill_records[0].payload.get(
                                "row_fingerprints",
                                [],
                            )
                        ):
                            raise TransitionError(
                                "Historical Study KPI close provenance is invalid"
                            )
                    else:
                        raise TransitionError("Study KPI provenance is not typed")
                    if event is None:
                        raise TransitionError(
                            "Study KPI record is not bound to a Study close event"
                        )
                    try:
                        rows.append(
                            StudyKpiProjectionRow(
                                sequence=sequence,
                                closed_at_utc=event.payload["occurred_at_utc"],
                                study_id=study_id,
                                executable_id=executable_id,
                                executable_display_id=executable_display_id,
                                net_profit_micropoints=metrics[
                                    "net_profit_micropoints"
                                ],
                                median_fold_profit_factor_milli=metrics[
                                    "median_fold_profit_factor_milli"
                                ],
                                trade_count=metrics["trade_count"],
                                monthly_realized_exit_drawdown_share_of_gross_profit_ppm=metrics[
                                    "monthly_realized_exit_drawdown_share_of_gross_profit_ppm"
                                ],
                                outcome=outcome,
                            )
                        )
                    except (KeyError, TypeError, ValueError) as exc:
                        raise TransitionError(
                            "Study KPI record cannot be rendered"
                        ) from exc
                try:
                    return materialize_study_kpi(
                        self.root / LEDGER_RELATIVE_PATH,
                        rows,
                    )
                except (OSError, ValueError) as exc:
                    raise TransitionError(
                        "Study KPI projection materialization failed"
                    ) from exc

class StudyCloseWriterMixin:
    """Own Study terminal mutation and its bounded diagnosis evidence adapters."""

    def close_study(
        self,
        *,
        outcome: str,
        operation_id: str,
        kpi_completion_record_id: str | None = None,
    ) -> TransitionResult:
        _require_ascii("outcome", outcome)
        allowed = set(_STUDY_OUTCOMES)
        if self.engineering_fixture:
            allowed.add(_ENGINEERING_FIXTURE_OUTCOME)
        if outcome not in allowed:
            raise TransitionError("Study outcome is not typed")
        def prepare(current: dict[str, Any] | None, _index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            study_id = science["active_study"]
            if study_id is None or science["active_batch"] is not None:
                raise TransitionError("Study close requires no undisposed Batch")
            if science["active_job"] is not None or science["active_repair"] is not None:
                raise TransitionError("Study close requires no active Job or Repair")
            study_record = _index.get("study-open", study_id)
            if study_record is None:
                raise TransitionError("Study declaration is unavailable")
            batch_head = _index.event_head(f"study-batches:{study_id}")
            if (
                batch_head is None
                or body.get("next_action")
                != {"kind": "judge_study", "study_id": study_id}
            ):
                raise TransitionError("Study close is not the exact next action")
            from axiom_rift.operations.replay_projection import (
                ReplayProjectionError,
                ReplayTransitionError,
                require_study_terminal_authority,
            )

            try:
                require_study_terminal_authority(
                    _index,
                    mission_id=study_record.payload.get("mission_id"),
                    study=study_record,
                )
            except ReplayProjectionError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except ReplayTransitionError as exc:
                raise TransitionError(str(exc)) from exc
            kpi_payload = self._study_kpi_payload(
                index=_index,
                study_id=study_id,
                outcome=outcome,
                completion_record_id=kpi_completion_record_id,
                closed_at_utc="1970-01-01T00:00:00Z",
            )
            science["active_study"] = None
            self._drop_authorization(body, SubjectKind.STUDY, study_id)
            fingerprint_payload = {"study_id": study_id, "outcome": outcome}
            if kpi_payload is not None:
                fingerprint_payload["study_kpi"] = kpi_payload
            fingerprint = _digest(fingerprint_payload, domain="study-close")
            body["next_action"] = (
                {
                    "kind": "portfolio_decision",
                    "portfolio_snapshot_id": study_record.payload.get(
                        "portfolio_snapshot_id"
                    ),
                }
                if self.engineering_fixture
                else {
                    "kind": "diagnose_study",
                    "study_id": study_id,
                    "study_close_record_id": fingerprint,
                    "portfolio_snapshot_id": study_record.payload.get(
                        "portfolio_snapshot_id"
                    ),
                }
            )
            record = _record(
                kind="study-close",
                record_id=fingerprint,
                subject=f"Study:{study_id}",
                status=outcome,
                fingerprint=fingerprint,
                payload={
                    "outcome": outcome,
                    "portfolio_axis_id": study_record.payload.get(
                        "portfolio_axis_id"
                    ),
                    "portfolio_axis_identity": study_record.payload.get(
                        "portfolio_axis_identity"
                    ),
                    "portfolio_snapshot_id": study_record.payload.get(
                        "portfolio_snapshot_id"
                    ),
                    "primary_research_layer": study_record.payload.get(
                        "primary_research_layer"
                    ),
                    "system_architecture_family": study_record.payload.get(
                        "system_architecture_family"
                    ),
                    "study_kpi_record_id": (
                        None if kpi_payload is None else study_id
                    ),
                },
            )
            records = [record]
            from axiom_rift.operations.semantic_question_registry import (
                SemanticQuestionRegistryError,
                SemanticQuestionRegistryIntegrityError,
                require_semantic_question_registry_activation,
                semantic_question_lineage_resolution_records,
            )

            try:
                if (
                    require_semantic_question_registry_activation(_index)
                    is not None
                ):
                    records.extend(
                        semantic_question_lineage_resolution_records(
                            _index, record
                        )
                    )
            except SemanticQuestionRegistryIntegrityError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except SemanticQuestionRegistryError as exc:
                raise TransitionError(str(exc)) from exc
            if kpi_payload is not None:
                kpi_fingerprint = _digest(kpi_payload, domain="study-kpi")
                records.append(
                    _record(
                        kind="study-kpi",
                        record_id=study_id,
                        subject=f"Study:{study_id}",
                        status=outcome,
                        fingerprint=kpi_fingerprint,
                        payload=kpi_payload,
                        event_stream="study-kpi",
                        event_sequence=kpi_payload["sequence"],
                    )
                )
            return body, records, {
                "study_id": study_id,
                "outcome": outcome,
                "study_kpi_record_id": None if kpi_payload is None else study_id,
                "study_kpi_sequence": (
                    None if kpi_payload is None else kpi_payload["sequence"]
                ),
            }

        transition = self._commit(
            event_kind="study_closed",
            operation_id=operation_id,
            subject="Study:active",
            payload={
                "kpi_completion_record_id": kpi_completion_record_id,
                "outcome": outcome,
            },
            prepare=prepare,
        )
        return transition

    @staticmethod
    def _study_diagnosis_evidence_basis(
        index: LocalIndex,
        *,
        study_id: str,
        close_record: IndexRecord,
    ) -> list[dict[str, str]]:
        from axiom_rift.operations.scientific_history import (
            ScientificHistoryProjectionError,
            project_study_job_evidence,
        )

        references: set[tuple[str, str]] = {
            ("study-close", close_record.record_id)
        }
        kpi_record_id = close_record.payload.get("study_kpi_record_id")
        if isinstance(kpi_record_id, str):
            kpi = index.get("study-kpi", kpi_record_id)
            if kpi is None:
                raise TransitionError("Study diagnosis KPI basis is unavailable")
            references.add(("study-kpi", kpi.record_id))
            completion_id = kpi.payload.get("completion_record_id")
            if isinstance(completion_id, str):
                if index.get("job-completed", completion_id) is None:
                    raise TransitionError(
                        "Study diagnosis completion basis is unavailable"
                    )
                references.add(("job-completed", completion_id))
        batch_head = index.event_head(f"study-batches:{study_id}")
        if batch_head is None:
            raise TransitionError("Study diagnosis requires a final Batch")
        references.add((batch_head.record_kind, batch_head.record_id))
        batch_closes = tuple(
            record
            for status in _BATCH_OUTCOMES
            for record in index.records_by_subject_status(
                f"Batch:{batch_head.record_id}", status
            )
            if record.kind == "batch-close"
        )
        if len(batch_closes) != 1:
            raise TransitionError("Study diagnosis final Batch close is ambiguous")
        references.add(("batch-close", batch_closes[0].record_id))
        rejected_preflights = StudyLifecycleWriterMixin._batch_rejected_replay_preflights(
            index,
            batch_head.record_id,
        )
        if rejected_preflights:
            if (
                batch_closes[0].status != "not_evaluable"
                or batch_closes[0].payload.get("basis_record_id")
                != rejected_preflights[0].record_id
            ):
                raise TransitionError(
                    "Study diagnosis implementation rejection has another Batch outcome"
                )
            references.add(
                (
                    "job-implementation-preflight",
                    rejected_preflights[0].record_id,
                )
            )
        try:
            job_evidence = project_study_job_evidence(
                index,
                study_id=study_id,
            )
        except ScientificHistoryProjectionError as exc:
            raise TransitionError(str(exc)) from exc
        references.update(
            ("job-completed", completion.record_id)
            for completion in job_evidence.completions
        )
        references.update(
            ("negative-memory", memory.record_id)
            for memory in job_evidence.negative_memories
        )
        return [
            {"kind": kind, "record_id": record_id}
            for kind, record_id in sorted(references)
        ]

    @staticmethod
    def _study_primary_scientific_completions(
        index: LocalIndex,
        *,
        study_id: str,
    ) -> tuple[IndexRecord, ...]:
        """Compatibility boundary for the read-only Study projection."""

        from axiom_rift.operations.study_diagnosis_projection import (
            StudyDiagnosisProjectionError,
            study_primary_scientific_completions,
        )

        try:
            return study_primary_scientific_completions(
                index,
                study_id=study_id,
            )
        except StudyDiagnosisProjectionError as exc:
            raise TransitionError(str(exc)) from exc

    @staticmethod
    def _study_claim_scoped_diagnosis(
        index: LocalIndex,
        *,
        study_id: str,
    ) -> Any | None:
        """Compatibility boundary for the read-only Study projection."""

        from axiom_rift.operations.study_diagnosis_projection import (
            StudyDiagnosisProjectionError,
            study_claim_scoped_diagnosis,
        )

        try:
            return study_claim_scoped_diagnosis(
                index,
                study_id=study_id,
            )
        except StudyDiagnosisProjectionError as exc:
            raise TransitionError(str(exc)) from exc


class StudyLifecycleWriterMixin(
    BatchLifecycleWriterMixin,
    StudyKpiProjectionWriterMixin,
    StudyCloseWriterMixin,
):
    """Compose focused lifecycle owners behind the public StateWriter facade."""
