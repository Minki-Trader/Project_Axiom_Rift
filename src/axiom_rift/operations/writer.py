"""The sole state writer for Axiom lifecycle and capability transitions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
import yaml

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.permits import (
    Permit,
    PermitAuthority,
    PermitError,
    PermitKind,
    PermitStatus,
    SubjectKind,
    SubjectRef,
)
from axiom_rift.operations.validation import (
    EngineeringFixtureValidator,
    EvidenceValidationError,
    EvidenceValidationRequest,
    EvidenceValidatorRegistry,
    ValidationArtifact,
)
from axiom_rift.storage.evidence import EvidenceStore
from axiom_rift.storage.index import (
    IndexIntegrityError,
    IndexRecord,
    LocalIndex,
    RecordCollisionError,
)
from axiom_rift.storage.journal import (
    DurableJournal,
    JournalHead,
    JournalIntegrityError,
    _issue_journal_write_capability,
)
from axiom_rift.storage.state import ControlStateError, ControlStore, WriterLock, seal_control


class TransitionError(RuntimeError):
    """A requested transition violates the active lifecycle."""


class RecoveryRequired(TransitionError):
    """A projection trails or conflicts with the durable journal."""


class InjectedCrash(RuntimeError):
    """Commissioning-only crash injection after a transaction boundary."""


class IdenticalFailedRetryError(TransitionError):
    """A failed work fingerprint was retried without new information."""


_PERMIT_RULES: dict[PermitKind, tuple[frozenset[SubjectKind], frozenset[str]]] = {
    PermitKind.SOURCE: (
        frozenset({SubjectKind.STUDY, SubjectKind.EXECUTABLE}),
        frozenset({"performance_batch", "runtime_source_use"}),
    ),
    PermitKind.STUDY: (
        frozenset({SubjectKind.INITIATIVE}),
        frozenset({"open_study"}),
    ),
    PermitKind.BATCH: (
        frozenset({SubjectKind.STUDY}),
        frozenset({"open_batch"}),
    ),
    PermitKind.JOB: (
        frozenset({SubjectKind.JOB}),
        frozenset({"start_job"}),
    ),
    PermitKind.REPAIR: (
        frozenset({SubjectKind.JOB}),
        frozenset({"open_repair"}),
    ),
    PermitKind.RUNTIME: (
        frozenset({SubjectKind.EXECUTABLE}),
        frozenset({"start_runtime", "run_execution_proof", "materialize"}),
    ),
    PermitKind.HOLDOUT: (
        frozenset({SubjectKind.EXECUTABLE}),
        frozenset({"reveal_holdout"}),
    ),
    PermitKind.RELEASE: (
        frozenset({SubjectKind.RELEASE}),
        frozenset({"freeze_release"}),
    ),
}

_INITIATIVE_OUTCOMES = frozenset(
    {"completed", "continued_handoff", "no_action", "superseded", "blocked_external"}
)
_STUDY_OUTCOMES = frozenset(
    {"supported", "not_supported", "not_evaluable", "evidence_gap", "pruned", "preserved"}
)
_BATCH_OUTCOMES = frozenset(
    {"completed", "budget_exhausted", "stopped_early", "not_evaluable", "engineering_failure"}
)
_ENGINEERING_FIXTURE_OUTCOME = "engineering_fixture_complete"


@dataclass(frozen=True, slots=True)
class TransitionResult:
    event_id: str
    revision: int
    reused: bool
    result: Mapping[str, Any]


Prepare = Callable[
    [dict[str, Any] | None, LocalIndex],
    tuple[dict[str, Any], list[IndexRecord], Mapping[str, Any]],
]


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _copy(value: Mapping[str, Any]) -> dict[str, Any]:
    copied = parse_canonical(canonical_bytes(dict(value)))
    assert isinstance(copied, dict)
    return dict(copied)


def _digest(value: Mapping[str, Any], *, domain: str) -> str:
    return canonical_digest(domain=domain, payload=dict(value))


def _require_ascii(name: str, value: str) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise TransitionError(f"{name} must be non-empty ASCII")
    return value


def _require_digest(name: str, value: str) -> str:
    _require_ascii(name, value)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise TransitionError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _parse_utc(name: str, value: str) -> datetime:
    _require_ascii(name, value)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TransitionError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise TransitionError(f"{name} must be UTC")
    return parsed


def _require_manifest(
    name: str,
    value: Mapping[str, Any],
    *,
    required: set[str],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TransitionError(f"{name} must be a mapping")
    missing = required - set(value)
    if missing:
        raise TransitionError(f"{name} is missing fields: {sorted(missing)!r}")
    return _copy(value)


def _require_study_evidence_modes(question: Mapping[str, Any]) -> tuple[str, ...]:
    allowed = {
        "ablation",
        "causal_contrast",
        "cost_and_execution",
        "extreme_or_boundary",
        "neighborhood",
        "regime_stability",
        "sensitivity_or_stress",
        "temporal_stability",
    }
    modes = question.get("evidence_modes")
    if (
        not isinstance(modes, list)
        or not modes
        or any(type(mode) is not str for mode in modes)
        or len(set(modes)) != len(modes)
        or not set(modes).issubset(allowed)
    ):
        raise TransitionError("Study evidence_modes are invalid")
    return tuple(sorted(modes))


def _record(
    *,
    kind: str,
    record_id: str,
    subject: str,
    status: str,
    fingerprint: str,
    payload: Mapping[str, Any],
    event_stream: str | None = None,
    event_sequence: int | None = None,
) -> IndexRecord:
    return IndexRecord(
        kind=kind,
        record_id=record_id,
        subject=subject,
        status=status,
        fingerprint=fingerprint,
        payload=dict(payload),
        event_stream=event_stream,
        event_sequence=event_sequence,
    )


def ready_control_body() -> dict[str, Any]:
    """Return the exact clean Foundation ready projection without heads."""

    return {
        "schema": "axiom_control",
        "authority": {
            "graph_count": 1,
            "operating_direction": "OPERATING_DIRECTION.md",
            "contracts": [
                "contracts/operations.yaml",
                "contracts/science.yaml",
                "contracts/evidence.yaml",
                "contracts/runtime.yaml",
            ],
            "foundation_inputs": [
                "foundation/market.yaml",
                "foundation/environment.yaml",
                "foundation/data.yaml",
                "foundation/data_exposure.yaml",
                "foundation/prior_scientific_memory.yaml",
                "foundation/origin.yaml",
            ],
        },
        "initiative": {
            "id": "INI-0001",
            "status": "closed",
            "outcome": "completed_ready_boundary",
        },
        "engineering": {
            "harness_status": "ready",
            "active_authority_graph_count": 1,
            "mutable_control_state_count": 1,
        },
        "scientific": {
            "active_mission": None,
            "active_initiative": None,
            "active_study": None,
            "active_batch": None,
            "active_job": None,
            "active_repair": None,
            "active_executable": None,
            "active_lineage": None,
            "active_release": None,
            "active_holdout_evaluation": None,
            "required_future_holdout_id": None,
            "holdout_reveals": 0,
            "claim": "none",
        },
        "authorizations": {},
        "next_action": {"kind": "await_root_goal"},
    }


class StateWriter:
    """Commit one hash-chained event and advance its two projections."""

    def __init__(
        self,
        root: str | Path,
        *,
        permit_authority: PermitAuthority | None = None,
        clock: Callable[[], str] = _now_utc,
        engineering_fixture: bool = False,
        foundation_root: str | Path | None = None,
        validation_registry: EvidenceValidatorRegistry | None = None,
    ) -> None:
        self.root = Path(root)
        self.foundation_root = Path(foundation_root) if foundation_root else self.root
        if engineering_fixture and any(
            (candidate / ".git").exists()
            for candidate in (self.root.resolve(), *self.root.resolve().parents)
        ):
            raise TransitionError(
                "engineering_fixture state must be isolated outside a Git worktree"
            )
        self.control = ControlStore(self.root / "state" / "control.json")
        self.journal = DurableJournal(self.root / "records" / "journal.jsonl")
        self._journal_write_capability = _issue_journal_write_capability()
        self.index_path = self.root / "local" / "index.sqlite"
        self.lock_path = self.root / "local" / "state.writer.lock"
        self.evidence = EvidenceStore(self.root / "local" / "evidence")
        self.permit_authority = permit_authority
        self.clock = clock
        self.engineering_fixture = engineering_fixture
        self.validation_registry = (
            validation_registry
            if validation_registry is not None
            else EvidenceValidatorRegistry(
                (EngineeringFixtureValidator(),) if engineering_fixture else ()
            )
        )

    @staticmethod
    def _body(control: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in _copy(control).items()
            if key not in {"revision", "heads", "control_hash"}
        }

    @staticmethod
    def _assemble(event: Mapping[str, Any]) -> dict[str, Any]:
        sequence = event["sequence"]
        control = _copy(event["control"])
        control["revision"] = sequence
        control["heads"] = {
            "journal": {
                "sequence": sequence,
                "event_id": event["event_id"],
            },
            "index": {
                "required_sequence": sequence,
                "required_record_count": event["index_record_count"],
                "required_projection_digest": event[
                    "index_projection_digest"
                ],
            },
        }
        return control

    @staticmethod
    def _event_records(event: Mapping[str, Any]) -> tuple[IndexRecord, ...]:
        authority = {
            "authority_sequence": event["sequence"],
            "authority_event_id": event["event_id"],
            "authority_offset": event["journal_offset"],
        }
        event_record = IndexRecord(
            kind="journal-event",
            record_id=event["event_id"],
            subject=event["subject"],
            status=event["event_kind"],
            fingerprint=event["event_id"],
            payload={
                "operation_id": event["operation_id"],
                "occurred_at_utc": event["occurred_at_utc"],
            },
            event_stream="control",
            event_sequence=event["sequence"],
            **authority,
        )
        return (event_record,) + tuple(
            IndexRecord.from_mapping({**item, **authority})
            for item in event["index_records"]
        )

    @staticmethod
    def _index_mapping(record: IndexRecord) -> dict[str, Any]:
        return {
            "kind": record.kind,
            "record_id": record.record_id,
            "subject": record.subject,
            "status": record.status,
            "fingerprint": record.fingerprint,
            "payload": dict(record.payload),
            "event_stream": record.event_stream,
            "event_sequence": record.event_sequence,
        }

    def _validate_index_record_authority(self, record: IndexRecord) -> None:
        if (
            record.authority_sequence is None
            or record.authority_event_id is None
            or record.authority_offset is None
        ):
            raise IndexIntegrityError("operating projection record lacks Journal authority")
        event = self.journal.read_event_at(
            offset=record.authority_offset,
            expected_sequence=record.authority_sequence,
            expected_event_id=record.authority_event_id,
        )
        projected = self._index_mapping(record)
        if record.kind == "journal-event":
            expected = self._index_mapping(self._event_records(event)[0])
            if projected != expected:
                raise IndexIntegrityError("journal-event projection differs from authority")
            return
        matches = [item for item in event["index_records"] if item == projected]
        if len(matches) != 1:
            raise IndexIntegrityError("projection record is not a unique Journal member")

    def _open_authoritative_index(self) -> LocalIndex:
        return LocalIndex(
            self.index_path,
            authority_validator=self._validate_index_record_authority,
        )

    def _require_runtime_source(
        self,
        index: LocalIndex,
        source_id: str,
        *,
        error_type: type[Exception] = TransitionError,
    ) -> IndexRecord:
        """Return a current, typed and artifact-backed runtime source state."""

        from axiom_rift.research.sources import (
            SourceContract,
            SourceEligibilityReceipt,
            SourceTransitionEvidence,
            SourceType,
        )

        _require_ascii("source_id", source_id)
        stream = f"source:{source_id}"

        def require_edge(
            record: IndexRecord | None,
            *,
            sequence: int,
            state: str,
            evidence: SourceTransitionEvidence | None,
        ) -> SourceEligibilityReceipt | None:
            if (
                record is None
                or record.kind != "source-state"
                or record.subject != f"Source:{source_id}"
                or record.fingerprint != source_id
                or record.status != state
                or record.event_stream != stream
                or record.event_sequence != sequence
                or record.payload.get("ordinal") != sequence
            ):
                raise ValueError("source transition edge is structurally invalid")
            payload = record.payload
            expected_record_id = canonical_digest(
                domain="source-state",
                payload={
                    "source_id": source_id,
                    "state": state,
                    "ordinal": sequence,
                    "evidence_receipt_id": payload.get("evidence_receipt_id"),
                },
            )
            if record.record_id != expected_record_id:
                raise ValueError("source-state identity is not canonical")
            suspension_reason = payload.get("suspension_reason")
            if (state == "suspended") != (
                isinstance(suspension_reason, str) and bool(suspension_reason)
            ):
                raise ValueError("source suspension reason does not match state")
            if evidence is None:
                if (
                    payload.get("receipt") is not None
                    or payload.get("evidence_receipt_id") is not None
                    or payload.get("transition_evidence") is not None
                ):
                    raise ValueError("source registration edge contains transition evidence")
                return None
            receipt_payload = payload.get("receipt")
            if not isinstance(receipt_payload, dict):
                raise ValueError("source transition receipt is absent")
            receipt = SourceEligibilityReceipt(
                source_contract_id=receipt_payload["source_contract_id"],
                evidence=SourceTransitionEvidence(receipt_payload["evidence"]),
                producer_completion_id=receipt_payload["producer_completion_id"],
                observed_at_utc=receipt_payload["observed_at_utc"],
                artifact_hashes=tuple(receipt_payload["artifact_hashes"]),
                facts=receipt_payload["facts"],
            )
            if (
                receipt.source_contract_id != source_id
                or receipt.identity != payload.get("evidence_receipt_id")
                or receipt.evidence is not evidence
                or payload.get("transition_evidence") != evidence.value
                or receipt_payload != receipt.to_identity_payload()
            ):
                raise ValueError("source transition receipt provenance is invalid")
            for artifact_hash in receipt.artifact_hashes:
                self.evidence.verify(artifact_hash)
            return receipt

        try:
            head = index.event_head(stream)
            record = None if head is None else index.get(head.record_kind, head.record_id)
            if head is None or record is None or record.status != "runtime_eligible":
                raise ValueError("current source projection is not runtime eligible")
            receipt_payload = record.payload.get("receipt")
            if not isinstance(receipt_payload, dict):
                raise ValueError("runtime source receipt is absent")
            current_evidence = SourceTransitionEvidence(receipt_payload["evidence"])
            if current_evidence not in {
                SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF,
                SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION,
            }:
                raise ValueError("current source receipt is not runtime evidence")
            receipt = require_edge(
                record,
                sequence=head.sequence,
                state="runtime_eligible",
                evidence=current_evidence,
            )
            assert receipt is not None
            payload = record.payload
            contract_payload = payload.get("contract")
            if not isinstance(contract_payload, dict):
                raise ValueError("source contract projection is absent")
            contract = SourceContract(
                display_name="journal-projection",
                canonical_instrument=contract_payload["canonical_instrument"],
                runtime_identifier=contract_payload["runtime_identifier"],
                source_type=SourceType(contract_payload["source_type"]),
                instrument_semantics=contract_payload["instrument_semantics"],
                mapping_semantics=contract_payload["mapping_semantics"],
                schema_semantics=contract_payload["schema_semantics"],
                field_semantics=contract_payload["field_semantics"],
                clock_semantics=contract_payload["clock_semantics"],
                availability_semantics=contract_payload["availability_semantics"],
            )
            if (
                contract.identity != source_id
                or contract_payload != contract.to_identity_payload()
                or payload.get("contract_hash") != source_id.removeprefix("source:")
                or payload.get("mapping_identity") != contract.mapping_identity
                or payload.get("schema_identity") != contract.schema_identity
                or payload.get("field_identity") != contract.field_identity
                or payload.get("clock_identity") != contract.clock_identity
                or payload.get("availability_identity") != contract.availability_identity
            ):
                raise ValueError("source contract identity projection is invalid")
            observed_at = datetime.fromisoformat(
                receipt.observed_at_utc.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            now = datetime.fromisoformat(
                self.clock().replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            ttl_seconds = contract.availability()["causal_ttl_seconds"]
            age_seconds = (now - observed_at).total_seconds()
            if age_seconds < 0 or age_seconds > ttl_seconds:
                raise ValueError("runtime source eligibility receipt is stale")
            if (
                receipt.evidence is SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF
                and head.sequence != 3
            ) or (
                receipt.evidence
                is SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION
                and (head.sequence < 5 or head.sequence % 2 == 0)
            ):
                raise ValueError("runtime source receipt appears at an invalid transition")
            require_edge(
                index.event_record(stream, 1),
                sequence=1,
                state="context_only",
                evidence=None,
            )
            require_edge(
                index.event_record(stream, 2),
                sequence=2,
                state="historical_audited",
                evidence=SourceTransitionEvidence.HISTORICAL_AUDIT,
            )
            if receipt.evidence is SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION:
                initial_runtime = index.event_record(stream, 3)
                initial_receipt = require_edge(
                    initial_runtime,
                    sequence=3,
                    state="runtime_eligible",
                    evidence=SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF,
                )
                assert initial_receipt is not None
                require_edge(
                    index.event_record(stream, head.sequence - 1),
                    sequence=head.sequence - 1,
                    state="suspended",
                    evidence=SourceTransitionEvidence.DRIFT,
                )
            return record
        except Exception as exc:
            if isinstance(exc, error_type):
                raise
            raise error_type(
                f"source {source_id!r} lacks current runtime provenance"
            ) from exc

    def _require_stable_locked(
        self, index: LocalIndex, *, allow_empty: bool = False
    ) -> dict[str, Any] | None:
        control = self.control.read()
        journal_head, journal_event = self.journal.tail()
        index_head = index.event_head("control")
        if control is None:
            if allow_empty and journal_head.sequence == 0 and index_head is None:
                return None
            raise RecoveryRequired("control is absent or trails durable state")
        if (
            control["authority"].get("manifest_digest")
            != self._authority_manifest_digest(control["authority"])
        ):
            raise RecoveryRequired("authority or Foundation input content drifted")
        state_head = control["heads"]["journal"]
        if control["revision"] != state_head["sequence"]:
            raise ControlStateError("control revision and journal head diverge")
        if (
            journal_head.sequence != state_head["sequence"]
            or journal_head.event_id != state_head["event_id"]
        ):
            raise RecoveryRequired("control and journal require recovery")
        assert journal_event is not None
        if control != seal_control(self._assemble(journal_event)):
            raise RecoveryRequired("control content differs from journal authority")
        if (
            index_head is None
            or index_head.sequence != journal_head.sequence
            or index_head.fingerprint != journal_head.event_id
        ):
            raise RecoveryRequired("local index requires recovery")
        if index.record_count() != control["heads"]["index"]["required_record_count"]:
            raise RecoveryRequired("local index contains an unauthoritative record count")
        projection_digest, projection_valid = index.projection_guard()
        if (
            not projection_valid
            or projection_digest
            != control["heads"]["index"]["required_projection_digest"]
        ):
            raise RecoveryRequired("local index projection digest requires recovery")
        return control

    def read_control(self) -> dict[str, Any] | None:
        return self.control.read()

    def _commit(
        self,
        *,
        event_kind: str,
        operation_id: str,
        subject: str,
        payload: Mapping[str, Any],
        prepare: Prepare,
        evidence_blobs: Sequence[bytes] = (),
        crash_after: str | None = None,
        allow_empty: bool = False,
        read_only_when_unchanged: bool = False,
    ) -> TransitionResult:
        _require_ascii("event_kind", event_kind)
        _require_ascii("operation_id", operation_id)
        _require_ascii("subject", subject)
        evidence = [self.evidence.finalize(blob).manifest() for blob in evidence_blobs]
        committed_payload = {**dict(payload), "evidence": evidence}
        operation_fingerprint = _digest(
            {"event_kind": event_kind, "payload": committed_payload},
            domain="operation",
        )
        if crash_after == "after_evidence":
            raise InjectedCrash("after_evidence")
        with WriterLock(self.lock_path):
            with self._open_authoritative_index() as index:
                current = self._require_stable_locked(index, allow_empty=allow_empty)
                existing = index.get("operation", operation_id)
                if existing is not None:
                    if existing.fingerprint != operation_fingerprint:
                        raise TransitionError("idempotency key reused with different input")
                    head = self.journal.tail()[0]
                    return TransitionResult(
                        event_id=head.event_id or "",
                        revision=head.sequence,
                        reused=True,
                        result=existing.payload.get("result", {}),
                    )
                if current is not None:
                    science = current["scientific"]
                    active_job = science.get("active_job")
                    active_repair = science.get("active_repair")
                    if isinstance(active_job, dict):
                        allowed_by_status = {
                            "declared": {
                                "permit_issued",
                                "permit_revoked",
                                "job_started",
                            },
                            "running": {
                                "permit_issued",
                                "permit_revoked",
                                "runtime_engine_entered",
                                "holdout_revealed",
                                "job_completed",
                                "repair_opened",
                            },
                            "interrupted_repair": {"repair_closed"},
                        }
                        if event_kind not in allowed_by_status.get(
                            active_job.get("status"), set()
                        ):
                            raise TransitionError(
                                "active Job must resume or complete before another transition"
                            )
                    if active_repair is not None and event_kind != "repair_closed":
                        raise TransitionError(
                            "active Repair must close before another transition"
                        )
                    pending_terminal = current["next_action"]
                    frozen_release_withdrawal = (
                        pending_terminal.get("kind") == "close_mission"
                        and pending_terminal.get("outcome")
                        == "completed_pre_live_handoff"
                        and event_kind == "release_disposed"
                        and isinstance(science.get("active_release"), dict)
                        and science["active_release"].get("id")
                        == pending_terminal.get("basis_record_id")
                        and science["active_release"].get("status") == "frozen"
                    )
                    if (
                        pending_terminal.get("kind") == "close_mission"
                        and event_kind
                        not in {"mission_closed", "terminal_basis_withdrawn"}
                        and not frozen_release_withdrawal
                    ):
                        raise TransitionError(
                            "pending Mission terminal must close or be withdrawn exactly"
                        )
                    if science.get("active_holdout_evaluation") is not None and event_kind not in {
                        "holdout_evaluated",
                        "negative_memory_recorded",
                        "job_completed",
                        "permit_issued",
                        "permit_revoked",
                        "repair_opened",
                        "repair_closed",
                    }:
                        raise TransitionError(
                            "revealed holdout must receive a typed disposition before other work"
                        )
                    if (
                        current["next_action"].get("kind")
                        == "await_new_future_holdout_data"
                        and event_kind not in {"holdout_sealed", "external_blocker_recorded"}
                    ):
                        raise TransitionError(
                            "failed holdout requires genuinely later sealed data"
                        )
                    if (
                        current["next_action"].get("kind")
                        == "register_future_development_material"
                        and event_kind
                        not in {
                            "future_development_registered",
                            "external_blocker_recorded",
                        }
                    ):
                        raise TransitionError(
                            "successor holdout requires its typed future-development registration"
                        )
                next_body, records, result = prepare(current, index)
                if read_only_when_unchanged and not records:
                    if current is None or next_body != self._body(current):
                        raise TransitionError(
                            "read-only observation attempted to change control state"
                        )
                    head = self.journal.tail()[0]
                    return TransitionResult(
                        event_id=head.event_id or "",
                        revision=head.sequence,
                        reused=True,
                        result=dict(result),
                    )
                operation_record = _record(
                    kind="operation",
                    record_id=operation_id,
                    subject=subject,
                    status="success",
                    fingerprint=operation_fingerprint,
                    payload={
                        "event_kind": event_kind,
                        "result": dict(result),
                    },
                )
                all_records = [operation_record, *records]
                for record in all_records:
                    if index.get(record.kind, record.record_id) is not None:
                        raise RecordCollisionError(
                            "a new journal event cannot re-project an existing record key"
                        )
                current_head = (
                    JournalHead(0, None)
                    if current is None
                    else JournalHead(
                        current["heads"]["journal"]["sequence"],
                        current["heads"]["journal"]["event_id"],
                    )
                )
                projected_digest = index.projected_digest(all_records)
                event = self.journal._append_authorized(
                    capability=self._journal_write_capability,
                    expected_head=current_head,
                    event_kind=event_kind,
                    operation_id=operation_id,
                    subject=subject,
                    occurred_at_utc=self.clock(),
                    payload=committed_payload,
                    control=next_body,
                    index_records=[self._index_mapping(item) for item in all_records],
                    index_record_count=index.record_count() + 1 + len(all_records),
                    index_projection_digest=projected_digest,
                )
                if crash_after == "after_journal":
                    raise InjectedCrash("after_journal")
                replacement = self._assemble(event)
                self.control.compare_and_swap(
                    expected_revision=-1 if current is None else current["revision"],
                    expected_event_id=(
                        None
                        if current is None
                        else current["heads"]["journal"]["event_id"]
                    ),
                    replacement=replacement,
                )
                if crash_after == "after_cursor":
                    raise InjectedCrash("after_cursor")
                index.put_many(self._event_records(event))
                if crash_after == "after_index":
                    raise InjectedCrash("after_index")
                return TransitionResult(
                    event_id=event["event_id"],
                    revision=event["sequence"],
                    reused=False,
                    result=dict(result),
                )

    def recover(self) -> dict[str, Any]:
        """Explicitly reconcile control and index projections from authority."""

        with WriterLock(self.lock_path):
            events = self.journal.read_all()
            control = self.control.read()
            if control is not None:
                sequence = control["heads"]["journal"]["sequence"]
                event_id = control["heads"]["journal"]["event_id"]
                if sequence > len(events):
                    raise JournalIntegrityError("control claims a future journal head")
                if sequence and events[sequence - 1]["event_id"] != event_id:
                    raise JournalIntegrityError("control claims a foreign journal head")
            if not events:
                if control is not None:
                    raise JournalIntegrityError("control exists without journal authority")
                return {"journal_sequence": 0, "control_repaired": False, "index_rebuilt": False}
            last = events[-1]
            desired = self._assemble(last)
            control_repaired = control is None or control != seal_control(desired)
            if control_repaired:
                self.control.replace(desired)
            records: list[IndexRecord] = []
            for event in events:
                records.extend(self._event_records(event))
            with LocalIndex(self.index_path) as index:
                projection_corrupt = False
                try:
                    head = index.event_head("control")
                    index.check_integrity()
                except IndexIntegrityError:
                    head = None
                    projection_corrupt = True
                if head is not None:
                    if head.sequence > len(events):
                        raise JournalIntegrityError("index claims a future journal head")
                    if events[head.sequence - 1]["event_id"] != head.fingerprint:
                        raise JournalIntegrityError("index claims a foreign journal head")
                needs_rebuild = (
                    projection_corrupt
                    or head is None
                    or head.sequence != last["sequence"]
                    or head.fingerprint != last["event_id"]
                    or index.record_count() != last["index_record_count"]
                )
                if not projection_corrupt and not index.exactly_matches(records):
                    needs_rebuild = True
                if needs_rebuild:
                    index.rebuild(records)
                index.check_integrity()
                if not index.exactly_matches(records):
                    raise JournalIntegrityError(
                        "local index record set differs from Journal authority"
                    )
                if index.record_count() != last["index_record_count"]:
                    raise JournalIntegrityError(
                        "rebuilt index count differs from journal authority"
                    )
                projection_digest, projection_valid = index.projection_guard()
                if (
                    not projection_valid
                    or projection_digest != last["index_projection_digest"]
                ):
                    raise JournalIntegrityError(
                        "rebuilt index digest differs from journal authority"
                    )
            return {
                "journal_sequence": last["sequence"],
                "control_repaired": control_repaired,
                "index_rebuilt": needs_rebuild,
            }

    def initialize_ready(
        self,
        *,
        operation_id: str = "foundation-ready-boundary",
        crash_after: str | None = None,
    ) -> TransitionResult:
        body = ready_control_body()
        body["authority"]["manifest_digest"] = self._authority_manifest_digest(
            body["authority"]
        )
        if self.engineering_fixture:
            body["engineering"]["commissioning_fixture"] = True
        closeout_fingerprint = _digest(body["initiative"], domain="initiative-close")

        def prepare(
            current: dict[str, Any] | None, _index: LocalIndex
        ) -> tuple[dict[str, Any], list[IndexRecord], Mapping[str, Any]]:
            if current is not None:
                raise TransitionError("control is already initialized")
            record = _record(
                kind="initiative-close",
                record_id="INI-0001:completed_ready_boundary",
                subject="Initiative:INI-0001",
                status="completed_ready_boundary",
                fingerprint=closeout_fingerprint,
                payload={
                    "scientific_claim": "none",
                    "trial_delta": 0,
                    "holdout_delta": 0,
                    "next_action": "await_root_goal",
                },
            )
            return body, [record], {"outcome": "completed_ready_boundary"}

        return self._commit(
            event_kind="foundation_ready",
            operation_id=operation_id,
            subject="Initiative:INI-0001",
            payload={"scientific_claim": "none"},
            prepare=prepare,
            crash_after=crash_after,
            allow_empty=True,
        )

    def _authority_manifest_digest(self, authority: Mapping[str, Any]) -> str:
        relative_paths = (
            [authority["operating_direction"]]
            + list(authority["contracts"])
            + list(authority["foundation_inputs"])
        )
        hashes: dict[str, str] = {}
        for relative in relative_paths:
            _require_ascii("authority path", relative)
            path = (self.foundation_root / relative).resolve()
            root = self.foundation_root.resolve()
            if root != path and root not in path.parents:
                raise RecoveryRequired("authority path escapes Foundation root")
            if not path.is_file():
                raise RecoveryRequired(f"authority input is absent: {relative}")
            hashes[relative] = sha256(path.read_bytes()).hexdigest()
        return _digest(hashes, domain="authority-manifest")

    @staticmethod
    def _authorization(
        *, kind: SubjectKind, subject_id: str, semantic_hash: str, epoch: int = 1
    ) -> SubjectRef:
        authorization_hash = _digest(
            {
                "kind": kind.value,
                "subject_id": subject_id,
                "semantic_hash": semantic_hash,
                "epoch": epoch,
            },
            domain="subject-authorization",
        )
        return SubjectRef(
            kind=kind,
            subject_id=subject_id,
            authorization_epoch=epoch,
            authorization_hash=authorization_hash,
        )

    @staticmethod
    def _bind_authorization(body: dict[str, Any], subject: SubjectRef) -> None:
        body["authorizations"][subject.key] = subject.payload()

    @staticmethod
    def _drop_authorization(
        body: dict[str, Any], kind: SubjectKind, subject_id: str
    ) -> None:
        body["authorizations"].pop(f"{kind.value}:{subject_id}", None)

    @staticmethod
    def _current_subject(
        control: Mapping[str, Any], kind: SubjectKind, subject_id: str
    ) -> SubjectRef:
        value = control["authorizations"].get(f"{kind.value}:{subject_id}")
        if not isinstance(value, dict):
            raise PermitError("permit subject is not active")
        return SubjectRef(
            kind=kind,
            subject_id=subject_id,
            authorization_epoch=value["authorization_epoch"],
            authorization_hash=value["authorization_hash"],
        )

    @staticmethod
    def _permit_status(index: LocalIndex, permit_id: str) -> PermitStatus:
        head = index.event_head(f"permit:{permit_id}")
        if head is None:
            raise PermitError("permit was not issued by this journal")
        latest = index.get(head.record_kind, head.record_id)
        if latest is None or latest.fingerprint != permit_id:
            raise PermitError("permit status projection is invalid")
        if latest.kind == "permit-revoked":
            return PermitStatus.REVOKED
        if latest.kind == "permit-consumed":
            return PermitStatus.CONSUMED
        if latest.kind != "permit-issued":
            raise PermitError("permit status projection has an unknown record kind")
        return PermitStatus.ISSUED

    def open_mission(
        self,
        *,
        mission_id: str,
        goal: Mapping[str, Any],
        operation_id: str,
    ) -> TransitionResult:
        _require_ascii("mission_id", mission_id)
        goal_manifest = _require_manifest(
            "goal",
            goal,
            required={"objective", "scope", "terminal_contract"},
        )
        goal_hash = _digest(goal_manifest, domain="mission-goal")

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("Foundation is not initialized")
            body = self._body(current)
            science = body["scientific"]
            if science["active_mission"] is not None:
                raise TransitionError("a root Mission is already active")
            if body["next_action"]["kind"] != "await_root_goal":
                raise TransitionError("control is not at the root-goal boundary")
            if science.get("active_release") is not None:
                raise TransitionError("ready boundary contains an active Release")
            if science.get("active_holdout_evaluation") is not None:
                raise TransitionError("ready boundary contains an active holdout")
            science["active_mission"] = mission_id
            science["holdout_reveals"] = 0
            science["required_future_holdout_id"] = None
            body["next_action"] = {"kind": "open_initiative", "mission_id": mission_id}
            authorization = self._authorization(
                kind=SubjectKind.MISSION,
                subject_id=mission_id,
                semantic_hash=goal_hash,
            )
            self._bind_authorization(body, authorization)
            record = _record(
                kind="mission-open",
                record_id=mission_id,
                subject=f"Mission:{mission_id}",
                status="open",
                fingerprint=goal_hash,
                payload={"goal_hash": goal_hash, "goal": goal_manifest},
            )
            return body, [record], {"mission_id": mission_id}

        return self._commit(
            event_kind="mission_opened",
            operation_id=operation_id,
            subject=f"Mission:{mission_id}",
            payload={
                "mission_id": mission_id,
                "goal_hash": goal_hash,
                "goal": goal_manifest,
            },
            prepare=prepare,
        )

    def open_initiative(
        self,
        *,
        initiative_id: str,
        objective: Mapping[str, Any],
        operation_id: str,
    ) -> TransitionResult:
        _require_ascii("initiative_id", initiative_id)
        objective_manifest = _require_manifest(
            "objective",
            objective,
            required={"objective", "bounds", "done_conditions"},
        )
        objective_hash = _digest(objective_manifest, domain="initiative-objective")

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            if science["active_mission"] is None or science["active_initiative"] is not None:
                raise TransitionError("Initiative open requires one active Mission and no Initiative")
            science["active_initiative"] = initiative_id
            portfolio_head = index.event_head(
                f"portfolio:{science['active_mission']}"
            )
            if portfolio_head is None:
                body["next_action"] = {
                    "kind": "build_portfolio",
                    "initiative_id": initiative_id,
                }
            else:
                snapshot = index.get(
                    portfolio_head.record_kind, portfolio_head.record_id
                )
                if snapshot is None or snapshot.kind != "portfolio-snapshot":
                    raise TransitionError("Mission Portfolio head is unavailable")
                body["next_action"] = {
                    "kind": "portfolio_decision",
                    "portfolio_snapshot_id": snapshot.record_id,
                }
            authorization = self._authorization(
                kind=SubjectKind.INITIATIVE,
                subject_id=initiative_id,
                semantic_hash=objective_hash,
            )
            self._bind_authorization(body, authorization)
            record = _record(
                kind="initiative-open",
                record_id=initiative_id,
                subject=f"Initiative:{initiative_id}",
                status="open",
                fingerprint=objective_hash,
                payload={
                    "objective_hash": objective_hash,
                    "objective": objective_manifest,
                },
            )
            return body, [record], {"initiative_id": initiative_id}

        return self._commit(
            event_kind="initiative_opened",
            operation_id=operation_id,
            subject=f"Initiative:{initiative_id}",
            payload={
                "initiative_id": initiative_id,
                "objective_hash": objective_hash,
                "objective": objective_manifest,
            },
            prepare=prepare,
        )

    def close_initiative(
        self,
        *,
        outcome: str,
        operation_id: str,
    ) -> TransitionResult:
        _require_ascii("outcome", outcome)
        allowed = set(_INITIATIVE_OUTCOMES)
        if self.engineering_fixture:
            allowed.add(_ENGINEERING_FIXTURE_OUTCOME)
        if outcome not in allowed:
            raise TransitionError("Initiative outcome is not typed")

        def prepare(current: dict[str, Any] | None, _index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            initiative_id = science["active_initiative"]
            if initiative_id is None:
                raise TransitionError("no active Initiative")
            if any(
                science[key] is not None
                for key in ("active_study", "active_batch", "active_job", "active_repair")
            ):
                raise TransitionError("Initiative close has undisposed active work")
            science["active_initiative"] = None
            self._drop_authorization(body, SubjectKind.INITIATIVE, initiative_id)
            body["next_action"] = {
                "kind": "choose_next_initiative_or_terminal",
                "mission_id": science["active_mission"],
            }
            fingerprint = _digest(
                {"initiative_id": initiative_id, "outcome": outcome},
                domain="initiative-close",
            )
            record = _record(
                kind="initiative-close",
                record_id=fingerprint,
                subject=f"Initiative:{initiative_id}",
                status=outcome,
                fingerprint=fingerprint,
                payload={"outcome": outcome},
            )
            return body, [record], {"initiative_id": initiative_id, "outcome": outcome}

        return self._commit(
            event_kind="initiative_closed",
            operation_id=operation_id,
            subject="Initiative:active",
            payload={"outcome": outcome},
            prepare=prepare,
        )

    @staticmethod
    def study_input_hash(
        *,
        question: Mapping[str, Any],
        material_identity: str,
        semantic_proposal: Mapping[str, Any],
        portfolio_axis_id: str | None = None,
        portfolio_axis_identity: str | None = None,
        portfolio_decision_id: str | None = None,
    ) -> str:
        question_manifest = _require_manifest(
            "question",
            question,
            required={
                "causal_question",
                "changed_variables",
                "controlled_variables",
                "done_conditions",
                "evidence_modes",
            },
        )
        question_manifest["evidence_modes"] = list(
            _require_study_evidence_modes(question_manifest)
        )
        question_hash = _digest(question_manifest, domain="study-question")
        _require_ascii("material_identity", material_identity)
        return _digest(
            {
                "question_hash": question_hash,
                "material_identity": material_identity,
                "portfolio_axis_id": portfolio_axis_id,
                "portfolio_axis_identity": portfolio_axis_identity,
                "portfolio_decision_id": portfolio_decision_id,
                "semantic_proposal": dict(semantic_proposal),
            },
            domain="study-input",
        )

    def open_study(
        self,
        *,
        study_id: str,
        question: Mapping[str, Any],
        material_identity: str,
        material_display_name: str,
        semantic_proposal: Mapping[str, Any],
        permit: Permit,
        operation_id: str,
        portfolio_axis_id: str | None = None,
        portfolio_axis_identity: str | None = None,
        portfolio_decision_id: str | None = None,
    ) -> TransitionResult:
        _require_ascii("study_id", study_id)
        question_manifest = _require_manifest(
            "question",
            question,
            required={
                "causal_question",
                "changed_variables",
                "controlled_variables",
                "done_conditions",
                "evidence_modes",
            },
        )
        question_manifest["evidence_modes"] = list(
            _require_study_evidence_modes(question_manifest)
        )
        question_hash = _digest(question_manifest, domain="study-question")
        _require_ascii("material_identity", material_identity)
        _require_ascii("material_display_name", material_display_name)
        from axiom_rift.research.trials import (
            MaterialReference,
            StudyTrialContext,
            TrialAccountant,
        )

        trial_accountant = TrialAccountant.from_foundation(self.foundation_root)
        material_reference = MaterialReference(
            identity=material_identity,
            display_name=material_display_name,
        )
        study_hash = self.study_input_hash(
            question=question_manifest,
            material_identity=material_identity,
            semantic_proposal=semantic_proposal,
            portfolio_axis_id=portfolio_axis_id,
            portfolio_axis_identity=portfolio_axis_identity,
            portfolio_decision_id=portfolio_decision_id,
        )

        def prepare(current: dict[str, Any] | None, _index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            if science["active_initiative"] is None or science["active_study"] is not None:
                raise TransitionError("Study open requires an Initiative and no active Study")
            initiative_id = science["active_initiative"]
            portfolio_snapshot_id: str | None = None
            mechanism_family: str | None = None
            portfolio_action: str | None = None
            commitment_batches: int | None = None
            if not self.engineering_fixture:
                if (
                    portfolio_axis_id is None
                    or portfolio_axis_identity is None
                    or portfolio_decision_id is None
                ):
                    raise TransitionError(
                        "scientific Study requires exact Portfolio axis and Decision identities"
                    )
                _require_ascii("portfolio_axis_id", portfolio_axis_id)
                next_action = current["next_action"]
                portfolio_snapshot_id = next_action.get("portfolio_snapshot_id")
                if (
                    next_action.get("kind") != "execute_portfolio_decision"
                    or next_action.get("target_id") != portfolio_axis_id
                    or next_action.get("target_axis_identity")
                    != portfolio_axis_identity
                    or next_action.get("decision_id") != portfolio_decision_id
                    or not isinstance(portfolio_snapshot_id, str)
                ):
                    raise TransitionError(
                        "Study must execute the current Portfolio Decision target"
                    )
                snapshot = _index.get("portfolio-snapshot", portfolio_snapshot_id)
                if snapshot is None:
                    raise TransitionError("Study Portfolio snapshot is unavailable")
                decision = _index.get("portfolio-decision", portfolio_decision_id)
                if (
                    decision is None
                    or decision.payload.get("portfolio_snapshot_id")
                    != portfolio_snapshot_id
                ):
                    raise TransitionError("Study Portfolio Decision is unavailable or stale")
                options = {
                    option["option_id"]: option
                    for option in decision.payload.get("options", [])
                }
                chosen = options.get(decision.payload.get("chosen_option_id"))
                work_actions = {
                    "complementary_sleeve",
                    "contrast",
                    "deepen",
                    "recombine",
                    "rotate",
                    "synthesize",
                }
                if (
                    not isinstance(chosen, dict)
                    or chosen.get("action") not in work_actions
                    or chosen.get("target_id") != portfolio_axis_id
                ):
                    raise TransitionError(
                        "Portfolio Decision does not authorize a scientific Study"
                    )
                axis = next(
                    (
                        value
                        for value in snapshot.payload["axes"]
                        if value["axis_id"] == portfolio_axis_id
                    ),
                    None,
                )
                if (
                    axis is None
                    or axis["status"] == "pruned"
                    or axis.get("axis_identity") != portfolio_axis_identity
                ):
                    raise TransitionError("Study Portfolio axis is absent or pruned")
                mechanism_family = axis["mechanism_family"]
                portfolio_action = chosen["action"]
                commitment_batches = decision.payload["commitment_batches"]
            if material_identity == trial_accountant.observed_material_identity:
                trial_context = trial_accountant.open_study(
                    material=material_reference,
                    semantic_proposal=dict(semantic_proposal),
                )
            else:
                development_material = _index.get(
                    "development-material", material_identity
                )
                if (
                    development_material is None
                    or development_material.status != "accepted"
                    or development_material.subject
                    != f"Mission:{science['active_mission']}"
                    or development_material.payload.get("mission_id")
                    != science["active_mission"]
                    or development_material.payload.get("material_identity")
                    != material_identity
                    or (
                        science["holdout_reveals"] > 0
                        and development_material.payload.get("holdout_id")
                        != science.get("required_future_holdout_id")
                    )
                ):
                    raise TransitionError(
                        "Study material is not registered for the active Mission"
                    )
                trial_context = StudyTrialContext(
                    material_identity=material_identity,
                    prior_global_multiplicity=0,
                    semantic_warnings=trial_accountant.lookup_semantic_warnings(
                        dict(semantic_proposal)
                    ),
                    warning_scheduler_weight="none",
                )
            trial_head = _index.event_head(
                f"material-trial:{trial_context.material_identity}"
            )
            prior_global_multiplicity = (
                trial_context.prior_global_multiplicity
                + (0 if trial_head is None else trial_head.sequence)
            )
            prior_material_trial_count = 0 if trial_head is None else trial_head.sequence
            self._validate_permit_locked(
                control=current,
                index=_index,
                permit=permit,
                expected_kind=PermitKind.STUDY,
                action="open_study",
                subject_kind=SubjectKind.INITIATIVE,
                subject_id=initiative_id,
                expected_input_hash=study_hash,
            )
            science["active_study"] = study_id
            body["next_action"] = {"kind": "freeze_batch", "study_id": study_id}
            authorization = self._authorization(
                kind=SubjectKind.STUDY,
                subject_id=study_id,
                semantic_hash=study_hash,
            )
            self._bind_authorization(body, authorization)
            consumption = self._permit_consumption_record(permit, operation_id)
            record = _record(
                kind="study-open",
                record_id=study_id,
                subject=f"Study:{study_id}",
                status="open",
                fingerprint=study_hash,
                payload={
                    "question_hash": question_hash,
                    "question": question_manifest,
                    "material_identity": trial_context.material_identity,
                    "mechanism_family": mechanism_family,
                    "mission_id": science["active_mission"],
                    "portfolio_action": portfolio_action,
                    "portfolio_axis_id": portfolio_axis_id,
                    "portfolio_axis_identity": portfolio_axis_identity,
                    "portfolio_decision_id": portfolio_decision_id,
                    "portfolio_snapshot_id": portfolio_snapshot_id,
                    "commitment_batches": commitment_batches,
                    "prior_global_multiplicity": prior_global_multiplicity,
                    "prior_material_trial_count": prior_material_trial_count,
                    "semantic_warning_ids": [
                        warning.warning_id for warning in trial_context.semantic_warnings
                    ],
                    "warning_scheduler_weight": trial_context.warning_scheduler_weight,
                },
            )
            return body, [consumption, record], {
                "study_id": study_id,
                "study_hash": study_hash,
                "prior_global_multiplicity": prior_global_multiplicity,
                "semantic_warning_count": len(trial_context.semantic_warnings),
            }

        return self._commit(
            event_kind="study_opened",
            operation_id=operation_id,
            subject=f"Study:{study_id}",
            payload={
                "study_id": study_id,
                "question_hash": question_hash,
                "question": question_manifest,
                "material_identity": material_identity,
                "portfolio_axis_identity": portfolio_axis_identity,
                "portfolio_decision_id": portfolio_decision_id,
                "study_hash": study_hash,
                "permit_id": permit.permit_id,
            },
            prepare=prepare,
        )

    def record_source_eligibility(
        self,
        *,
        eligibility: Any,
        receipt: Any | None,
        operation_id: str,
    ) -> TransitionResult:
        """Commit one typed source-contract eligibility edge to the journal."""

        from axiom_rift.research.sources import (
            SourceEligibility,
            SourceEligibilityReceipt,
            SourceEligibilityState,
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
            if current["scientific"]["active_mission"] is None:
                raise TransitionError("source eligibility requires an active Mission")
            if receipt is not None and not self.engineering_fixture:
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
                    or declaration is None
                    or declaration.payload.get("mission_id")
                    != current["scientific"]["active_mission"]
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
            previous = (
                None if latest is None else SourceEligibilityState(latest.status)
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
            record = _record(
                kind="source-state",
                record_id=state_key,
                subject=f"Source:{source_id}",
                status=eligibility.state.value,
                fingerprint=source_id,
                payload={
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
                },
                event_stream=f"source:{source_id}",
                event_sequence=ordinal,
            )
            return self._body(current), [record], {
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

    def open_batch(
        self,
        *,
        batch_spec: Any,
        permit: Permit,
        source_permits: tuple[Permit, ...] = (),
        operation_id: str,
    ) -> TransitionResult:
        from axiom_rift.research.portfolio import BatchSpec

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
            batch_head = index.event_head(f"study-batches:{study_id}")
            prior_batch_count = 0 if batch_head is None else batch_head.sequence
            commitment_batches = study_record.payload.get("commitment_batches")
            if not self.engineering_fixture and type(commitment_batches) is not int:
                raise TransitionError("scientific Study lacks its Batch commitment")
            if (
                type(commitment_batches) is int
                and prior_batch_count >= commitment_batches
            ):
                raise TransitionError(
                    "Portfolio Decision Batch commitment is exhausted"
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
                self._require_runtime_source(
                    index, source_id, error_type=PermitError
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
            if science["active_job"] is not None or science["active_repair"] is not None:
                raise TransitionError("cannot dispose Batch with active Job or Repair")
            science["active_batch"] = None
            body["next_action"] = {"kind": "judge_study", "study_id": science["active_study"]}
            fingerprint = _digest(
                {"batch_id": batch["id"], "outcome": outcome}, domain="batch-close"
            )
            record = _record(
                kind="batch-close",
                record_id=fingerprint,
                subject=f"Batch:{batch['id']}",
                status=outcome,
                fingerprint=fingerprint,
                payload={"outcome": outcome},
            )
            return body, [record], {"batch_id": batch["id"], "outcome": outcome}

        return self._commit(
            event_kind="batch_disposed",
            operation_id=operation_id,
            subject="Batch:active",
            payload={"outcome": outcome},
            prepare=prepare,
        )

    def close_study(self, *, outcome: str, operation_id: str) -> TransitionResult:
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
            science["active_study"] = None
            self._drop_authorization(body, SubjectKind.STUDY, study_id)
            body["next_action"] = {
                "kind": "portfolio_decision",
                "portfolio_snapshot_id": study_record.payload.get(
                    "portfolio_snapshot_id"
                ),
            }
            fingerprint = _digest(
                {"study_id": study_id, "outcome": outcome}, domain="study-close"
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
                },
            )
            return body, [record], {"study_id": study_id, "outcome": outcome}

        return self._commit(
            event_kind="study_closed",
            operation_id=operation_id,
            subject="Study:active",
            payload={"outcome": outcome},
            prepare=prepare,
        )

    @staticmethod
    def _normalize_job_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
        value = _copy(spec)
        for name in ("input_hashes", "expected_outputs"):
            if isinstance(value.get(name), list):
                value[name] = sorted(value[name])
        claims = value.get("worker_claims")
        if isinstance(claims, list):
            for claim in claims:
                if isinstance(claim, dict):
                    for name in ("inputs", "outputs", "resources"):
                        if isinstance(claim.get(name), list):
                            claim[name] = sorted(claim[name])
            value["worker_claims"] = sorted(
                claims,
                key=lambda claim: (
                    claim.get("worker_id", "") if isinstance(claim, dict) else ""
                ),
            )
        for binding_name in ("runtime_binding", "scientific_binding"):
            binding = value.get(binding_name)
            if isinstance(binding, dict):
                for name in (
                    "evidence_modes",
                    "planned_claims",
                    "planned_parity_surfaces",
                    "planned_materialization_cases",
                ):
                    if isinstance(binding.get(name), list):
                        binding[name] = sorted(binding[name])
        return value

    @staticmethod
    def _validate_job_spec(spec: Mapping[str, Any]) -> None:
        required = {
            "callable_identity",
            "implementation_identity",
            "input_hashes",
            "budget",
            "expected_outputs",
            "output_classes",
            "log_path",
            "timeout_or_stop_rule",
            "resume_action",
            "worker_claims",
            "evidence_subject",
        }
        missing = required - set(spec)
        if missing:
            raise TransitionError(f"Job spec missing fields: {sorted(missing)!r}")
        unexpected = set(spec) - required - {
            "changed_cause_proof_hash",
            "external_dependency_binding",
            "holdout_binding",
            "runtime_binding",
            "scientific_binding",
            "source_binding",
        }
        if unexpected:
            raise TransitionError(f"Job spec has unknown fields: {sorted(unexpected)!r}")
        changed_proof = spec.get("changed_cause_proof_hash")
        if changed_proof is not None:
            _require_digest("changed_cause_proof_hash", changed_proof)
        _require_digest("implementation_identity", spec["implementation_identity"])
        for name in ("callable_identity", "log_path", "timeout_or_stop_rule", "resume_action"):
            _require_ascii(name, spec[name])
        input_hashes = spec["input_hashes"]
        if not isinstance(input_hashes, list) or not input_hashes:
            raise TransitionError("input_hashes must be a non-empty list")
        for input_hash in input_hashes:
            _require_digest("input hash", input_hash)
        expected_outputs = spec["expected_outputs"]
        output_classes = spec["output_classes"]
        if (
            not isinstance(expected_outputs, list)
            or not expected_outputs
            or any(not isinstance(item, str) for item in expected_outputs)
            or len(set(expected_outputs)) != len(expected_outputs)
        ):
            raise TransitionError("expected_outputs must be a unique non-empty string list")
        if not isinstance(output_classes, dict) or set(output_classes) != set(expected_outputs):
            raise TransitionError("output_classes must classify every expected output exactly")
        allowed_classes = {"durable_evidence", "reproducible_cache", "transient"}
        if any(value not in allowed_classes for value in output_classes.values()):
            raise TransitionError("Job output has an invalid storage class")
        for output_name, output_class in output_classes.items():
            path = Path(output_name)
            if path.is_absolute() or ".." in path.parts:
                raise TransitionError("Job output path escapes the repository")
            if output_class == "transient" and path.parts[:2] != ("local", "jobs"):
                raise TransitionError("transient outputs must stay under local/jobs")
            if output_class == "reproducible_cache" and path.parts[:2] != (
                "local",
                "cache",
            ):
                raise TransitionError("reproducible cache must stay under local/cache")
        budget = spec["budget"]
        if (
            not isinstance(budget, dict)
            or not budget
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
                for value in budget.values()
            )
        ):
            raise TransitionError("Job budget must contain positive integer bounds")
        if not {"compute_seconds", "wall_seconds"}.issubset(budget):
            raise TransitionError("Job budget must bind compute_seconds and wall_seconds")
        evidence_subject = spec["evidence_subject"]
        if (
            not isinstance(evidence_subject, dict)
            or set(evidence_subject) != {"kind", "id"}
            or evidence_subject["kind"]
            not in {"Mission", "Initiative", "Study", "Executable", "Release"}
        ):
            raise TransitionError("Job evidence_subject is invalid")
        _require_ascii("evidence subject id", evidence_subject["id"])
        claims = spec["worker_claims"]
        if not isinstance(claims, list):
            raise TransitionError("worker_claims must be a list")
        inputs: set[str] = set()
        outputs: set[str] = set()
        resources: set[str] = set()
        worker_ids: set[str] = set()
        for claim in claims:
            if not isinstance(claim, dict):
                raise TransitionError("worker claim must be an object")
            worker_id = _require_ascii("worker_id", claim.get("worker_id"))
            if worker_id in worker_ids:
                raise TransitionError("worker_id values must be unique")
            worker_ids.add(worker_id)
            for key, seen in (("inputs", inputs), ("outputs", outputs), ("resources", resources)):
                values = claim.get(key, [])
                if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
                    raise TransitionError(f"worker {key} must be a string list")
                if len(set(values)) != len(values):
                    raise TransitionError(f"worker {key} has duplicate claims")
                overlap = seen.intersection(values)
                if overlap:
                    raise TransitionError(f"worker {key} overlap: {sorted(overlap)!r}")
                seen.update(values)
        runtime_binding = spec.get("runtime_binding")
        scientific_binding = spec.get("scientific_binding")
        source_binding = spec.get("source_binding")
        if sum(
            binding is not None
            for binding in (runtime_binding, scientific_binding, source_binding)
        ) > 1:
            raise TransitionError("Job cannot mix evidence-domain bindings")
        holdout_binding = spec.get("holdout_binding")
        if holdout_binding is not None:
            if (
                not isinstance(holdout_binding, dict)
                or set(holdout_binding) != {"holdout_id"}
                or scientific_binding is None
                or scientific_binding.get("evidence_depth") != "confirmation"
                or evidence_subject["kind"] != "Executable"
            ):
                raise TransitionError(
                    "holdout Job requires confirmation scientific binding"
                )
            holdout_id = holdout_binding["holdout_id"]
            if (
                type(holdout_id) is not str
                or not holdout_id.startswith("holdout:")
                or len(holdout_id) != 72
            ):
                raise TransitionError("holdout_binding identity is invalid")
            if holdout_id.removeprefix("holdout:") not in input_hashes:
                raise TransitionError("holdout identity must be a bound Job input")
        external_binding = spec.get("external_dependency_binding")
        if external_binding is not None:
            if not isinstance(external_binding, dict) or set(external_binding) != {
                "blocked_mission_capability",
                "dependency_id",
                "dependency_kind",
                "exact_resume_action",
                "recovery_kind",
                "recovery_path_id",
                "result_manifest_output",
                "required_external_change",
                "validation_plan_hash",
                "validator_id",
            }:
                raise TransitionError("external dependency binding schema is invalid")
            if external_binding["dependency_kind"] not in {
                "broker_service",
                "market_data_service",
                "vendor_runtime",
                "operating_system_service",
                "hardware_service",
            }:
                raise TransitionError("external dependency kind is not typed")
            if external_binding["recovery_kind"] not in {
                "external_probe",
                "local_recovery",
                "safe_substitute_search",
                "escalation_probe",
            }:
                raise TransitionError("external recovery kind is not typed")
            for name, field_value in external_binding.items():
                _require_ascii(name, field_value)
            if evidence_subject["kind"] != "Mission":
                raise TransitionError("external dependency Job must bind the Mission")

        def validate_validator_binding(binding: Mapping[str, Any]) -> None:
            validator_id = binding.get("validator_id")
            validator_digest = (
                validator_id.removeprefix("validator:")
                if isinstance(validator_id, str)
                else ""
            )
            _require_digest("validator identity", validator_digest)
            plan_hash = binding.get("validation_plan_hash")
            _require_digest("validation_plan_hash", plan_hash)
            if plan_hash not in input_hashes:
                raise TransitionError(
                    "validation plan must be a content-bound Job input"
                )

        if external_binding is not None:
            validate_validator_binding(external_binding)
            result_output = external_binding["result_manifest_output"]
            if output_classes.get(result_output) != "durable_evidence":
                raise TransitionError(
                    "external dependency result manifest must be durable"
                )
            if sum(value == "durable_evidence" for value in output_classes.values()) < 2:
                raise TransitionError(
                    "external dependency Job requires result and measurement artifacts"
                )

        if source_binding is not None:
            if not isinstance(source_binding, dict) or set(source_binding) != {
                "result_manifest_output",
                "source_contract_id",
                "transition_evidence",
                "validation_plan_hash",
                "validator_id",
            }:
                raise TransitionError("source_binding has an invalid schema")
            validate_validator_binding(source_binding)
            source_id = source_binding["source_contract_id"]
            if (
                type(source_id) is not str
                or not source_id.startswith("source:")
                or len(source_id) != 71
            ):
                raise TransitionError("source Job requires a SourceContract identity")
            if source_binding["transition_evidence"] not in {
                "historical_audit",
                "runtime_availability_proof",
                "drift",
                "same_semantics_recertification",
            }:
                raise TransitionError("source Job transition evidence is not typed")
            result_output = source_binding["result_manifest_output"]
            if output_classes.get(result_output) != "durable_evidence":
                raise TransitionError("source result manifest must be durable output")
            if sum(value == "durable_evidence" for value in output_classes.values()) < 2:
                raise TransitionError("source Job requires result and measurement artifacts")
        if scientific_binding is not None:
            if not isinstance(scientific_binding, dict) or set(scientific_binding) != {
                "evidence_depth",
                "evidence_modes",
                "planned_claims",
                "result_manifest_output",
                "validation_plan_hash",
                "validator_id",
            }:
                raise TransitionError("scientific_binding has an invalid schema")
            validate_validator_binding(scientific_binding)
            if scientific_binding["evidence_depth"] not in {
                "discovery",
                "confirmation",
            }:
                raise TransitionError("scientific Job evidence depth is invalid")
            executed_modes = _require_study_evidence_modes(scientific_binding)
            if list(executed_modes) != scientific_binding["evidence_modes"]:
                raise TransitionError("scientific Job evidence modes are not canonical")
            planned_claims = scientific_binding["planned_claims"]
            if (
                not isinstance(planned_claims, list)
                or not planned_claims
                or len(set(planned_claims)) != len(planned_claims)
            ):
                raise TransitionError("scientific Job claims must be preregistered")
            for claim in planned_claims:
                _require_ascii("scientific claim", claim)
            result_output = scientific_binding["result_manifest_output"]
            if output_classes.get(result_output) != "durable_evidence":
                raise TransitionError("scientific result manifest must be durable")
            if sum(value == "durable_evidence" for value in output_classes.values()) < 2:
                raise TransitionError(
                    "scientific Job requires result and measurement artifacts"
                )
            if evidence_subject["kind"] != "Executable":
                raise TransitionError("scientific Job must bind an Executable")
        if runtime_binding is not None:
            from axiom_rift.runtime.guards import (
                EvidenceDepth,
                REQUIRED_CASES,
                REQUIRED_PARITY,
                REQUIRED_RELEASE_ARTIFACT_ROLES,
            )

            if not isinstance(runtime_binding, dict) or set(runtime_binding) != {
                "action",
                "evidence_depth",
                "planned_materialization_cases",
                "planned_parity_surfaces",
                "result_manifest_output",
                "artifact_roles",
                "numeric_tolerances",
                "validation_plan_hash",
                "validator_id",
            }:
                raise TransitionError("runtime_binding has an invalid schema")
            validate_validator_binding(runtime_binding)
            action = runtime_binding["action"]
            depth = runtime_binding["evidence_depth"]
            expected_action = {
                EvidenceDepth.EXECUTION_PROOF.value: "run_execution_proof",
                EvidenceDepth.MATERIALIZATION.value: "materialize",
            }.get(depth)
            if action != expected_action:
                raise TransitionError("runtime Job action and evidence depth conflict")
            parity = runtime_binding["planned_parity_surfaces"]
            cases = runtime_binding["planned_materialization_cases"]
            if (
                not isinstance(parity, list)
                or any(type(item) is not str for item in parity)
                or len(set(parity)) != len(parity)
                or not set(parity).issubset(REQUIRED_PARITY)
                or not isinstance(cases, list)
                or any(type(item) is not str for item in cases)
                or len(set(cases)) != len(cases)
                or not set(cases).issubset(REQUIRED_CASES)
            ):
                raise TransitionError("runtime Job planned claims are invalid")
            if depth == EvidenceDepth.EXECUTION_PROOF.value and (not parity or cases):
                raise TransitionError("execution proof must preregister parity only")
            if depth == EvidenceDepth.MATERIALIZATION.value and (not cases or parity):
                raise TransitionError("materialization must preregister cases only")
            if evidence_subject["kind"] != "Executable":
                raise TransitionError("runtime Job must bind an Executable")
            if not any(value == "durable_evidence" for value in output_classes.values()):
                raise TransitionError("runtime Job requires durable evidence output")
            result_output = runtime_binding["result_manifest_output"]
            if (
                type(result_output) is not str
                or output_classes.get(result_output) != "durable_evidence"
            ):
                raise TransitionError(
                    "runtime Job result manifest must be a declared durable output"
                )
            if sum(
                value == "durable_evidence" for value in output_classes.values()
            ) < 2:
                raise TransitionError(
                    "runtime Job requires a result manifest and measurement artifact"
                )
            tolerances = runtime_binding["numeric_tolerances"]
            if not isinstance(tolerances, dict):
                raise TransitionError("runtime numeric tolerances must be preregistered")
            canonical_bytes(tolerances)
            artifact_roles = runtime_binding["artifact_roles"]
            if (
                not isinstance(artifact_roles, dict)
                or not artifact_roles
                or not set(artifact_roles).issubset(REQUIRED_RELEASE_ARTIFACT_ROLES)
                or len(set(artifact_roles.values())) != len(artifact_roles)
            ):
                raise TransitionError("runtime artifact roles are invalid")
            for role, output_name in artifact_roles.items():
                _require_ascii("runtime artifact role", role)
                _require_ascii("runtime artifact output", output_name)
                if (
                    output_name == result_output
                    or output_classes.get(output_name) != "durable_evidence"
                ):
                    raise TransitionError(
                        "runtime artifact roles require distinct durable outputs"
                    )

    def _require_job_implementation_evidence(
        self, spec: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Resolve one Job implementation identity to its exact stored bytes."""

        identity = spec["implementation_identity"]
        try:
            implementation_artifact = self.evidence.verify(identity)
            implementation_manifest = parse_canonical(
                (
                    self.evidence._root / implementation_artifact.relative_path
                ).read_bytes()
            )
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
            raise TransitionError(
                "Job implementation identity is not available canonical evidence"
            ) from exc
        if (
            not isinstance(implementation_manifest, dict)
            or set(implementation_manifest)
            != {"artifact_hashes", "callable_identity", "protocol", "schema"}
            or implementation_manifest.get("schema")
            != "job_implementation_evidence.v1"
            or implementation_manifest.get("callable_identity")
            != spec["callable_identity"]
            or type(implementation_manifest.get("protocol")) is not str
            or not implementation_manifest["protocol"]
            or not implementation_manifest["protocol"].isascii()
            or not isinstance(implementation_manifest.get("artifact_hashes"), list)
            or not implementation_manifest["artifact_hashes"]
            or any(
                type(source_hash) is not str
                for source_hash in implementation_manifest["artifact_hashes"]
            )
            or len(set(implementation_manifest["artifact_hashes"]))
            != len(implementation_manifest["artifact_hashes"])
            or implementation_manifest["artifact_hashes"]
            != sorted(implementation_manifest["artifact_hashes"])
        ):
            raise TransitionError("Job implementation evidence manifest is invalid")
        for source_hash in implementation_manifest["artifact_hashes"]:
            try:
                _require_digest("implementation artifact", source_hash)
                self.evidence.verify(source_hash)
            except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                raise TransitionError(
                    "Job implementation artifact bytes are unavailable"
                ) from exc
        return implementation_manifest

    def _require_reusable_success_outputs(
        self, *, completion: IndexRecord, spec: Mapping[str, Any]
    ) -> None:
        """Fail closed when a cached success no longer has its exact outputs."""

        outputs = completion.payload.get("outputs")
        output_classes = spec["output_classes"]
        if not isinstance(outputs, dict):
            raise RecoveryRequired("successful Job cache has no output manifest")
        for output_name in spec["expected_outputs"]:
            output_hash = outputs.get(output_name)
            try:
                _require_digest("cached output hash", output_hash)
                output_class = output_classes[output_name]
                if output_class == "durable_evidence":
                    self.evidence.verify(output_hash)
                    continue
                if output_class == "transient":
                    raise RecoveryRequired(
                        "successful Job cache cannot reuse transient output"
                    )
                target = (self.root / output_name).resolve()
                cache_root = (self.root / "local" / "cache").resolve()
                if cache_root not in target.parents or not target.is_file():
                    raise RecoveryRequired(
                        "successful Job cache output is unavailable"
                    )
                if sha256(target.read_bytes()).hexdigest() != output_hash:
                    raise RecoveryRequired(
                        "successful Job cache output hash mismatch"
                    )
            except RecoveryRequired:
                raise
            except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                raise RecoveryRequired(
                    "successful Job cache output is unavailable or corrupt"
                ) from exc

    def declare_job(
        self, *, spec: Mapping[str, Any], operation_id: str
    ) -> TransitionResult:
        spec = self._normalize_job_spec(spec)
        self._validate_job_spec(spec)
        work_basis = {
            "callable_identity": spec["callable_identity"],
            "evidence_subject": spec["evidence_subject"],
            "external_dependency_binding": spec.get(
                "external_dependency_binding"
            ),
            "input_hashes": spec["input_hashes"],
            "holdout_binding": spec.get("holdout_binding"),
            "runtime_binding": spec.get("runtime_binding"),
            "scientific_binding": spec.get("scientific_binding"),
            "source_binding": spec.get("source_binding"),
        }

        def prepare(current: dict[str, Any] | None, _index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            if science["active_mission"] is None:
                raise TransitionError("Job requires an active Mission")
            if science["active_job"] is not None:
                raise TransitionError("another parent Job is active")
            mission_id = science["active_mission"]
            implementation_manifest = self._require_job_implementation_evidence(spec)
            job_hash = _digest(
                {"mission_id": mission_id, "spec": dict(spec)}, domain="job"
            )
            job_id = f"job:{job_hash}"
            work_fingerprint = _digest(
                {"mission_id": mission_id, "work": work_basis},
                domain="job-work",
            )
            success_fingerprint = _digest(
                {
                    "expected_outputs": spec["expected_outputs"],
                    "implementation_identity": spec["implementation_identity"],
                    "mission_id": mission_id,
                    "output_classes": spec["output_classes"],
                    "work_fingerprint": work_fingerprint,
                },
                domain="job-success-cache",
            )
            cached_success = _index.get("job-success-cache", success_fingerprint)
            if cached_success is not None:
                completion_id = cached_success.payload.get("completion_record_id")
                completion = (
                    None
                    if not isinstance(completion_id, str)
                    else _index.get("job-completed", completion_id)
                )
                if (
                    completion is None
                    or completion.status != "success"
                    or set(completion.payload.get("outputs", {}))
                    != set(spec["expected_outputs"])
                    or completion.payload.get("output_classes")
                    != spec["output_classes"]
                    or cached_success.payload.get("mission_id") != mission_id
                ):
                    raise RecoveryRequired("successful Job cache is inconsistent")
                self._require_reusable_success_outputs(
                    completion=completion, spec=spec
                )
                return body, [], {
                    "disposition": "reuse_success",
                    "completion_record_id": completion.record_id,
                    "job_id": completion.payload["job_id"],
                }
            attempt_head = _index.event_head(f"job-attempt:{work_fingerprint}")
            previous_attempt = (
                None
                if attempt_head is None
                else _index.get(attempt_head.record_kind, attempt_head.record_id)
            )
            if (
                previous_attempt is not None
                and previous_attempt.kind == "job-completed"
                and previous_attempt.status != "success"
            ):
                changed_proof = spec.get("changed_cause_proof_hash")
                if changed_proof is None:
                    raise IdenticalFailedRetryError(
                        "failed Job work cannot be retried without changed-cause proof"
                    )
                changed_artifact = self.evidence.verify(changed_proof)
                prior_failure = previous_attempt.payload.get("failure")
                previous_job_id = previous_attempt.payload.get("job_id")
                previous_declaration = (
                    None
                    if not isinstance(previous_job_id, str)
                    else _index.get("job-declared", previous_job_id)
                )
                if (
                    isinstance(prior_failure, dict)
                    and changed_proof
                    in prior_failure.get("minimum_reproduction_evidence", [])
                ):
                    raise IdenticalFailedRetryError(
                        "changed-cause proof reuses failed reproduction evidence"
                    )
                if (
                    previous_declaration is not None
                    and previous_declaration.payload["spec"].get(
                        "changed_cause_proof_hash"
                    )
                    == changed_proof
                ):
                    raise IdenticalFailedRetryError(
                        "changed-cause proof was already consumed by the prior retry"
                    )
                if previous_declaration is None:
                    raise IdenticalFailedRetryError(
                        "prior failed Job declaration is unavailable"
                    )
                try:
                    previous_implementation_manifest = (
                        self._require_job_implementation_evidence(
                            previous_declaration.payload["spec"]
                        )
                    )
                except TransitionError as exc:
                    raise IdenticalFailedRetryError(
                        "prior implementation evidence is unavailable"
                    ) from exc
                if (
                    previous_implementation_manifest["artifact_hashes"]
                    == implementation_manifest["artifact_hashes"]
                ):
                    raise IdenticalFailedRetryError(
                        "changed-cause proof does not change implementation artifacts"
                    )
                try:
                    changed_manifest = parse_canonical(
                        (
                            self.evidence._root / changed_artifact.relative_path
                        ).read_bytes()
                    )
                except ValueError as exc:
                    raise IdenticalFailedRetryError(
                        "changed-cause proof is not a canonical manifest"
                    ) from exc
                if (
                    not isinstance(changed_manifest, dict)
                    or set(changed_manifest)
                    != {
                        "changed_dimension",
                        "explanation",
                        "new_evidence_hashes",
                        "new_implementation_identity",
                        "prior_failure_signature",
                        "previous_implementation_identity",
                        "schema",
                    }
                    or changed_manifest.get("schema") != "job_changed_cause.v1"
                    or changed_manifest.get("prior_failure_signature")
                    != (
                        prior_failure.get("failure_signature")
                        if isinstance(prior_failure, dict)
                        else None
                    )
                    or changed_manifest.get("changed_dimension") != "implementation"
                    or previous_declaration is None
                    or changed_manifest.get("previous_implementation_identity")
                    != previous_declaration.payload["spec"].get(
                        "implementation_identity"
                    )
                    or changed_manifest.get("new_implementation_identity")
                    != spec["implementation_identity"]
                    or changed_manifest.get("new_implementation_identity")
                    == changed_manifest.get("previous_implementation_identity")
                    or type(changed_manifest.get("explanation")) is not str
                    or not changed_manifest["explanation"]
                    or not changed_manifest["explanation"].isascii()
                    or not isinstance(changed_manifest.get("new_evidence_hashes"), list)
                    or not changed_manifest["new_evidence_hashes"]
                    or len(set(changed_manifest["new_evidence_hashes"]))
                    != len(changed_manifest["new_evidence_hashes"])
                ):
                    raise IdenticalFailedRetryError(
                        "changed-cause proof does not bind the prior failure and change"
                    )
                prior_reproduction = (
                    set(prior_failure.get("minimum_reproduction_evidence", []))
                    if isinstance(prior_failure, dict)
                    else set()
                )
                for evidence_hash in changed_manifest["new_evidence_hashes"]:
                    _require_digest("changed-cause evidence", evidence_hash)
                    self.evidence.verify(evidence_hash)
                    if evidence_hash in prior_reproduction:
                        raise IdenticalFailedRetryError(
                            "changed-cause evidence reuses prior reproduction"
                        )
                if (
                    changed_manifest["new_implementation_identity"]
                    not in changed_manifest["new_evidence_hashes"]
                ):
                    raise IdenticalFailedRetryError(
                        "changed-cause proof lacks the new implementation bytes"
                    )
                for source_hash in implementation_manifest["artifact_hashes"]:
                    if source_hash not in changed_manifest["new_evidence_hashes"]:
                        raise IdenticalFailedRetryError(
                            "changed-cause proof omits implementation artifact bytes"
                        )
            evidence_subject = spec["evidence_subject"]
            active_by_kind = {
                "Mission": science["active_mission"],
                "Initiative": science["active_initiative"],
                "Study": science["active_study"],
                "Executable": science["active_executable"],
            }
            if evidence_subject["kind"] == "Executable":
                subject_exists = (
                    _index.get("trial", evidence_subject["id"]) is not None
                    or _index.get("engineering-evaluation-fixture", evidence_subject["id"])
                    is not None
                    or active_by_kind["Executable"] == evidence_subject["id"]
                )
            elif evidence_subject["kind"] == "Release":
                subject_exists = (
                    _index.get("release-declared", evidence_subject["id"]) is not None
                )
            else:
                subject_exists = active_by_kind[evidence_subject["kind"]] == evidence_subject["id"]
            if not subject_exists:
                raise TransitionError("Job evidence subject is not active or registered")
            scientific_binding = spec.get("scientific_binding")
            if isinstance(scientific_binding, dict) and not self.engineering_fixture:
                lineage_study_id = science["active_study"]
                if not isinstance(lineage_study_id, str):
                    trial = _index.get("trial", evidence_subject["id"])
                    lineage_study_id = (
                        None if trial is None else trial.payload.get("study_id")
                    )
                lineage_study = (
                    None
                    if not isinstance(lineage_study_id, str)
                    else _index.get("study-open", lineage_study_id)
                )
                declared_modes = set(scientific_binding["evidence_modes"])
                if (
                    lineage_study is None
                    or lineage_study.payload.get("mission_id") != mission_id
                    or not declared_modes.issubset(
                        _require_study_evidence_modes(
                            lineage_study.payload.get("question", {})
                        )
                    )
                ):
                    raise TransitionError(
                        "scientific Job evidence modes exceed its Study preregistration"
                    )
            reservation_records: list[IndexRecord] = []
            batch = science["active_batch"]
            if isinstance(batch, dict):
                batch_record = _index.get("batch-open", batch["id"])
                if batch_record is None:
                    raise TransitionError("active Batch declaration is unavailable")
                budget_head = _index.event_head(f"batch-budget:{batch['id']}")
                previous_budget = (
                    {"compute_seconds": 0, "wall_seconds": 0}
                    if budget_head is None
                    else _index.get(budget_head.record_kind, budget_head.record_id).payload
                )
                next_compute = previous_budget["compute_seconds"] + spec["budget"]["compute_seconds"]
                next_wall = previous_budget["wall_seconds"] + spec["budget"]["wall_seconds"]
                frozen_spec = batch_record.payload["spec"]
                if (
                    next_compute > frozen_spec["max_compute_seconds"]
                    or next_wall > frozen_spec["max_wall_seconds"]
                ):
                    raise TransitionError("Job exceeds the frozen Batch compute or wall budget")
                reservation_id = canonical_digest(
                    domain="batch-budget-reservation",
                    payload={"batch_id": batch["id"], "job_id": job_id},
                )
                reservation_records.append(
                    _record(
                        kind="batch-budget-reservation",
                        record_id=reservation_id,
                        subject=f"Batch:{batch['id']}",
                        status="reserved",
                        fingerprint=job_hash,
                        payload={
                            "compute_seconds": next_compute,
                            "wall_seconds": next_wall,
                            "job_id": job_id,
                        },
                        event_stream=f"batch-budget:{batch['id']}",
                        event_sequence=1 if budget_head is None else budget_head.sequence + 1,
                    )
                )
            science["active_job"] = {
                "id": job_id,
                "hash": job_hash,
                "status": "declared",
                "resume_action": spec["resume_action"],
            }
            body["next_action"] = {"kind": "issue_job_permit", "job_id": job_id}
            authorization = self._authorization(
                kind=SubjectKind.JOB, subject_id=job_id, semantic_hash=job_hash
            )
            self._bind_authorization(body, authorization)
            record = _record(
                kind="job-declared",
                record_id=job_id,
                subject=f"Job:{job_id}",
                status="declared",
                fingerprint=job_hash,
                payload={
                    "spec": dict(spec),
                    "mission_id": science["active_mission"],
                    "initiative_id": science["active_initiative"],
                    "study_id": science["active_study"],
                    "batch_id": None if not isinstance(batch, dict) else batch["id"],
                    "success_fingerprint": success_fingerprint,
                    "work_fingerprint": work_fingerprint,
                },
                event_stream=f"job-attempt:{work_fingerprint}",
                event_sequence=(
                    1 if attempt_head is None else attempt_head.sequence + 1
                ),
            )
            return body, [*reservation_records, record], {
                "job_id": job_id,
                "job_hash": job_hash,
            }

        return self._commit(
            event_kind="job_declared",
            operation_id=operation_id,
            subject=(
                f"{spec['evidence_subject']['kind']}:{spec['evidence_subject']['id']}"
            ),
            payload={"job_spec_hash": _digest(dict(spec), domain="job-spec")},
            prepare=prepare,
            read_only_when_unchanged=True,
        )

    def issue_permit(
        self,
        *,
        kind: PermitKind,
        subject_kind: SubjectKind,
        subject_id: str,
        input_hash: str,
        actions: tuple[str, ...],
        scope: tuple[str, ...],
        expires_at_utc: str,
        one_shot: bool,
        operation_id: str,
    ) -> Permit:
        if self.permit_authority is None:
            raise PermitError("permit authority is unavailable")
        _require_digest("input_hash", input_hash)
        if not isinstance(kind, PermitKind) or not isinstance(subject_kind, SubjectKind):
            raise PermitError("permit kind and subject kind must be typed")
        allowed_subjects, allowed_actions = _PERMIT_RULES[kind]
        if subject_kind not in allowed_subjects:
            raise PermitError(f"{kind.value} permit cannot bind {subject_kind.value}")
        if not actions or not set(actions).issubset(allowed_actions):
            raise PermitError(f"{kind.value} permit contains a forbidden action")
        if kind in {
            PermitKind.SOURCE,
            PermitKind.STUDY,
            PermitKind.BATCH,
            PermitKind.JOB,
            PermitKind.REPAIR,
            PermitKind.HOLDOUT,
            PermitKind.RELEASE,
        } and not one_shot:
            raise PermitError(f"{kind.value} permits must be one-shot")
        if kind is PermitKind.RUNTIME and one_shot:
            raise PermitError("RuntimePermit uses reusable running-Job lease semantics")

        def prepare(current: dict[str, Any] | None, _index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            subject = self._current_subject(current, subject_kind, subject_id)
            if kind in {PermitKind.RUNTIME, PermitKind.HOLDOUT}:
                if subject_kind is not SubjectKind.EXECUTABLE:
                    raise PermitError("runtime and holdout permits must bind an Executable")
                candidate_head = _index.event_head(f"candidate:{subject_id}")
                candidate = (
                    None
                    if candidate_head is None
                    else _index.get(candidate_head.record_kind, candidate_head.record_id)
                )
                expected = (
                    ("engineering-executable-fixture", "bound_fixture")
                    if self.engineering_fixture
                    else ("candidate", "frozen")
                )
                candidate_bound = (
                    candidate is not None
                    and (candidate.kind, candidate.status) == expected
                )
                if not candidate_bound:
                    raise PermitError("runtime or holdout permit requires a frozen candidate")
                if kind is PermitKind.HOLDOUT:
                    holdout_id = f"holdout:{input_hash}"
                    seal = _index.get("holdout-seal", holdout_id)
                    required_holdout_scope = {
                        holdout_id,
                        f"candidate:{candidate.record_id}",
                        f"executable:{subject_id}",
                    }
                    if (
                        seal is None
                        or seal.status != "sealed_unrevealed"
                        or not required_holdout_scope.issubset(scope)
                        or current["scientific"].get("active_holdout_evaluation")
                        is not None
                        or (
                            current["scientific"].get("required_future_holdout_id")
                            is not None
                            and current["scientific"]["required_future_holdout_id"]
                            != holdout_id
                        )
                        or _index.event_head(f"holdout-reveal:{holdout_id}") is not None
                    ):
                        raise PermitError(
                            "HoldoutPermit requires one current unrevealed semantic seal"
                        )
            if kind is PermitKind.SOURCE:
                source_scopes = [item[7:] for item in scope if item.startswith("source:")]
                if not source_scopes:
                    raise PermitError("SourcePermit must name at least one source scope")
                for source_id in source_scopes:
                    self._require_runtime_source(
                        _index, source_id, error_type=PermitError
                    )
            if kind is PermitKind.RUNTIME:
                from axiom_rift.runtime.guards import EvidenceDepth

                depth_scopes = [item for item in scope if item.startswith("depth:")]
                allowed_depth_scopes = {
                    f"depth:{EvidenceDepth.EXECUTION_PROOF.value}",
                    f"depth:{EvidenceDepth.MATERIALIZATION.value}",
                }
                if len(depth_scopes) != 1 or depth_scopes[0] not in allowed_depth_scopes:
                    raise PermitError(
                        "RuntimePermit requires one execution_proof or materialization depth"
                    )
                required_depth_by_action = {
                    "run_execution_proof": f"depth:{EvidenceDepth.EXECUTION_PROOF.value}",
                    "materialize": f"depth:{EvidenceDepth.MATERIALIZATION.value}",
                }
                if any(
                    action in required_depth_by_action
                    and required_depth_by_action[action] != depth_scopes[0]
                    for action in actions
                ):
                    raise PermitError("RuntimePermit action and evidence depth conflict")
            if kind is PermitKind.RELEASE:
                declaration = _index.get("release-declared", subject_id)
                if (
                    declaration is None
                    or declaration.status != "declared"
                    or declaration.fingerprint != input_hash
                ):
                    raise PermitError("ReleasePermit requires the exact Release declaration")
            permit = self.permit_authority.issue(
                kind=kind,
                subject=subject,
                input_hash=input_hash,
                actions=actions,
                scope=scope,
                issued_at_utc=self.clock(),
                expires_at_utc=expires_at_utc,
                one_shot=one_shot,
                audit_revision=current["revision"],
            )
            record = _record(
                kind="permit-issued",
                record_id=permit.permit_id,
                subject=f"Permit:{permit.permit_id}",
                status="issued",
                fingerprint=permit.permit_id,
                payload=permit.payload(),
                event_stream=f"permit:{permit.permit_id}",
                event_sequence=1,
            )
            return self._body(current), [record], {"permit": permit.payload()}

        result = self._commit(
            event_kind="permit_issued",
            operation_id=operation_id,
            subject=f"{subject_kind.value}:{subject_id}",
            payload={
                "kind": kind.value,
                "subject_kind": subject_kind.value,
                "subject_id": subject_id,
                "input_hash": input_hash,
                "actions": list(actions),
                "scope": list(scope),
                "expires_at_utc": expires_at_utc,
                "one_shot": one_shot,
            },
            prepare=prepare,
        )
        return Permit.from_mapping(result.result["permit"])

    def revoke_permit(
        self,
        *,
        permit_id: str,
        reason: str,
        operation_id: str,
    ) -> TransitionResult:
        _require_digest("permit_id", permit_id)
        _require_ascii("reason", reason)

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            if self._permit_status(index, permit_id) is not PermitStatus.ISSUED:
                raise PermitError("only an issued permit can be revoked")
            issued = index.get("permit-issued", permit_id)
            if issued is None:
                raise PermitError("permit issue record is absent")
            record_id = canonical_digest(
                domain="permit-revocation",
                payload={"permit_id": permit_id, "reason": reason},
            )
            record = _record(
                kind="permit-revoked",
                record_id=record_id,
                subject=f"Permit:{permit_id}",
                status="revoked",
                fingerprint=permit_id,
                payload={"reason": reason, "issued_kind": issued.payload["kind"]},
                event_stream=f"permit:{permit_id}",
                event_sequence=2,
            )
            return self._body(current), [record], {"permit_id": permit_id}

        return self._commit(
            event_kind="permit_revoked",
            operation_id=operation_id,
            subject=f"Permit:{permit_id}",
            payload={"permit_id": permit_id, "reason": reason},
            prepare=prepare,
        )

    def freeze_candidate(
        self,
        *,
        executable: Any,
        evidence_refs: tuple[str, ...],
        operation_id: str,
    ) -> TransitionResult:
        from axiom_rift.core.identity import ExecutableSpec

        if not isinstance(executable, ExecutableSpec):
            raise TransitionError("candidate requires a frozen ExecutableSpec")
        executable_id = executable.identity
        executable_hash = executable_id.removeprefix("executable:")
        _require_digest("executable_hash", executable_hash)
        if len(set(evidence_refs)) != len(evidence_refs):
            raise TransitionError("candidate evidence references must be unique")
        for reference in evidence_refs:
            _require_ascii("candidate evidence reference", reference)
        evidence_refs = tuple(sorted(evidence_refs))
        candidate_basis_hash = canonical_digest(
            domain="candidate",
            payload={
                "executable_id": executable_id,
                "evidence_refs": list(evidence_refs),
            },
        )

        def prepare(current: dict[str, Any] | None, _index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            if science["active_mission"] is None:
                raise TransitionError("candidate freeze requires an active Mission")
            candidate_id = "candidate:" + canonical_digest(
                domain="mission-candidate",
                payload={
                    "evidence_refs": list(evidence_refs),
                    "executable_id": executable_id,
                    "mission_id": science["active_mission"],
                },
            )
            if science["active_executable"] is not None:
                raise TransitionError("another Executable is active")
            if any(
                science[name] is not None
                for name in ("active_study", "active_batch", "active_job", "active_repair")
            ):
                raise TransitionError("candidate freeze requires disposed scientific work")
            if (
                science["holdout_reveals"] > 0
                and science.get("required_future_holdout_id") is None
            ):
                raise TransitionError(
                    "post-holdout candidate work requires genuinely later sealed data"
                )
            post_holdout_receipt = None
            if science["holdout_reveals"] > 0:
                trial = _index.get("trial", executable_id)
                material_identity = (
                    None if trial is None else trial.payload.get("material_identity")
                )
                development_material = (
                    None
                    if not isinstance(material_identity, str)
                    else _index.get("development-material", material_identity)
                )
                receipt_id = (
                    None
                    if development_material is None
                    else development_material.payload.get(
                        "post_holdout_development_id"
                    )
                )
                post_holdout_receipt = (
                    None
                    if not isinstance(receipt_id, str)
                    else _index.get("post-holdout-development", receipt_id)
                )
                receipt_payload = (
                    {}
                    if post_holdout_receipt is None
                    else post_holdout_receipt.payload
                )
                if (
                    trial is None
                    or trial.payload.get("mission_id") != science["active_mission"]
                    or trial.payload.get("executable")
                    != executable.to_identity_payload()
                    or post_holdout_receipt is None
                    or post_holdout_receipt.status != "accepted"
                    or post_holdout_receipt.subject
                    != f"Material:{material_identity}"
                    or receipt_payload.get("holdout_id")
                    != science["required_future_holdout_id"]
                    or receipt_payload.get("mission_id")
                    != science["active_mission"]
                    or executable.data_contract != f"data:{material_identity}"
                    or executable.split_contract
                    != f"split:{receipt_payload.get('split_identity')}"
                    or development_material is None
                    or development_material.status != "accepted"
                    or development_material.subject
                    != f"Mission:{science['active_mission']}"
                    or development_material.payload.get(
                        "post_holdout_development_id"
                    )
                    != receipt_id
                    or development_material.payload.get("material_receipt_hash")
                    != receipt_payload.get("material_receipt_hash")
                    or post_holdout_receipt.authority_sequence is None
                    or trial.authority_sequence is None
                    or trial.authority_sequence
                    <= post_holdout_receipt.authority_sequence
                ):
                    raise TransitionError(
                        "post-holdout candidate work requires its durable future-development receipt"
                    )
            source_bindings: list[dict[str, Any]] = []
            for source_id in executable.source_contracts:
                source_state = self._require_runtime_source(_index, source_id)
                source_bindings.append(
                    {
                        "source_contract_id": source_id,
                        "eligibility_receipt_id": source_state.payload[
                            "evidence_receipt_id"
                        ],
                        "mapping_identity": source_state.payload["mapping_identity"],
                    }
                )
            if not self.engineering_fixture:
                if not evidence_refs:
                    raise TransitionError("candidate freeze requires bound evidence")
                scientific_depths: set[str] = set()
                confirmation_eligible = False
                for reference in evidence_refs:
                    evidence = _index.get("job-completed", reference)
                    if evidence is None or evidence.status != "success":
                        raise TransitionError(
                            "candidate evidence must name a successful Job completion"
                        )
                    if (
                        post_holdout_receipt is not None
                        and (
                            evidence.authority_sequence is None
                            or evidence.authority_sequence
                            <= post_holdout_receipt.authority_sequence
                        )
                    ):
                        raise TransitionError(
                            "post-holdout candidate evidence must postdate future-development authority"
                        )
                    declaration = _index.get(
                        "job-declared", evidence.payload.get("job_id", "")
                    )
                    if declaration is None:
                        raise TransitionError("candidate evidence Job declaration is absent")
                    scientific = evidence.payload.get("scientific")
                    if (
                        not isinstance(scientific, dict)
                        or scientific.get("scientific_eligible") is not True
                        or scientific.get("executable_id") != executable_id
                        or scientific.get("evidence_depth")
                        not in {"discovery", "confirmation"}
                    ):
                        raise TransitionError(
                            "candidate evidence is not validator-derived scientific evidence"
                        )
                    scientific_depths.add(scientific["evidence_depth"])
                    if scientific["evidence_depth"] == "confirmation":
                        confirmation_eligible = (
                            confirmation_eligible
                            or scientific.get("candidate_eligible") is True
                        )
                    declared_subject = declaration.payload["spec"]["evidence_subject"]
                    if declared_subject != {
                        "kind": "Executable",
                        "id": executable_id,
                    } or declaration.payload["mission_id"] != science["active_mission"]:
                        raise TransitionError(
                            "candidate evidence is not bound to this Executable and Mission"
                        )
                if scientific_depths != {"discovery", "confirmation"}:
                    raise TransitionError(
                        "candidate freeze requires discovery and confirmation evidence"
                    )
                if not confirmation_eligible:
                    raise TransitionError(
                        "confirmation validator did not authorize candidate promotion"
                    )
            science["active_executable"] = executable_id
            body["next_action"] = {
                "kind": "plan_candidate_bound_evidence",
                "executable_id": executable_id,
            }
            candidate_head = _index.event_head(f"candidate:{executable_id}")
            candidate_sequence = (
                1 if candidate_head is None else candidate_head.sequence + 1
            )
            activation_hash = _digest(
                {
                    "candidate_id": candidate_id,
                    "candidate_sequence": candidate_sequence,
                    "executable_hash": executable_hash,
                    "mission_id": science["active_mission"],
                },
                domain="candidate-authorization",
            )
            authorization = self._authorization(
                kind=SubjectKind.EXECUTABLE,
                subject_id=executable_id,
                semantic_hash=activation_hash,
                epoch=candidate_sequence,
            )
            self._bind_authorization(body, authorization)
            status = "bound_fixture" if self.engineering_fixture else "frozen"
            record = _record(
                kind=(
                    "engineering-executable-fixture"
                    if self.engineering_fixture
                    else "candidate"
                ),
                record_id=candidate_id,
                subject=f"Executable:{executable_id}",
                status=status,
                fingerprint=executable_hash,
                payload={
                    "evidence_refs": list(evidence_refs),
                    "executable": executable.to_identity_payload(),
                    "mission_id": science["active_mission"],
                    "source_bindings": source_bindings,
                    "scientific_eligible": not self.engineering_fixture,
                    "scheduler_eligible": False,
                },
                event_stream=f"candidate:{executable_id}",
                event_sequence=candidate_sequence,
            )
            return body, [record], {
                "candidate_id": candidate_id,
                "executable_id": executable_id,
                "fixture": self.engineering_fixture,
            }

        return self._commit(
            event_kind="candidate_frozen",
            operation_id=operation_id,
            subject=f"Executable:{executable_id}",
            payload={
                "candidate_basis_hash": candidate_basis_hash,
                "executable_id": executable_id,
                "executable_hash": executable_hash,
                "evidence_refs": list(evidence_refs),
                "engineering_fixture": self.engineering_fixture,
            },
            prepare=prepare,
        )

    def dispose_candidate(
        self,
        *,
        disposition: str,
        reason: str,
        operation_id: str,
    ) -> TransitionResult:
        _require_ascii("disposition", disposition)
        _require_ascii("reason", reason)
        if disposition not in {
            "rejected",
            "returned_to_library",
            "superseded",
            "invalidated",
        }:
            raise TransitionError("candidate disposition is not typed")

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            executable_id = science["active_executable"]
            if executable_id is None:
                raise TransitionError("no active candidate Executable")
            if science["active_job"] is not None or science["active_repair"] is not None:
                raise TransitionError("candidate disposition cannot bypass active work")
            candidate_head = index.event_head(f"candidate:{executable_id}")
            candidate = (
                None
                if candidate_head is None
                else index.get(candidate_head.record_kind, candidate_head.record_id)
            )
            if candidate is None:
                raise TransitionError("candidate binding is unavailable")
            if science.get("active_release") is not None:
                raise TransitionError("an active Release must be disposed before its candidate")
            passed_holdout = index.get("candidate-holdout", candidate.record_id)
            if passed_holdout is not None and (
                passed_holdout.status != "passed"
                or passed_holdout.payload.get("mission_id")
                != science["active_mission"]
                or passed_holdout.payload.get("executable_id") != executable_id
            ):
                raise TransitionError("candidate holdout projection is inconsistent")
            science["active_executable"] = None
            self._drop_authorization(body, SubjectKind.EXECUTABLE, executable_id)
            if passed_holdout is not None:
                science["required_future_holdout_id"] = None
                body["next_action"] = {
                    "kind": "await_new_future_holdout_data",
                    "predecessor_holdout_id": passed_holdout.payload["holdout_id"],
                }
            elif science["active_initiative"] is None:
                body["next_action"] = {
                    "kind": "open_initiative",
                    "mission_id": science["active_mission"],
                }
            else:
                portfolio_head = index.event_head(
                    f"portfolio:{science['active_mission']}"
                )
                snapshot = (
                    None
                    if portfolio_head is None
                    else index.get(portfolio_head.record_kind, portfolio_head.record_id)
                )
                if snapshot is None or snapshot.kind != "portfolio-snapshot":
                    raise TransitionError(
                        "candidate disposition in an Initiative requires a current Portfolio snapshot"
                    )
                body["next_action"] = {
                    "kind": "portfolio_decision",
                    "portfolio_snapshot_id": snapshot.record_id,
                }
            record_id = canonical_digest(
                domain="candidate-disposition",
                payload={
                    "candidate_id": candidate.record_id,
                    "disposition": disposition,
                    "reason": reason,
                },
            )
            record = _record(
                kind="candidate-disposition",
                record_id=record_id,
                subject=f"Executable:{executable_id}",
                status=disposition,
                fingerprint=candidate.fingerprint,
                payload={
                    "candidate_id": candidate.record_id,
                    "executable_id": executable_id,
                    "mission_id": science["active_mission"],
                    "reason": reason,
                },
                event_stream=f"candidate:{executable_id}",
                event_sequence=candidate_head.sequence + 1,
            )
            return body, [record], {"executable_id": executable_id}

        return self._commit(
            event_kind="candidate_disposed",
            operation_id=operation_id,
            subject="Executable:active",
            payload={"disposition": disposition, "reason": reason},
            prepare=prepare,
        )

    def _derive_release_basis_locked(
        self,
        *,
        index: LocalIndex,
        control: Mapping[str, Any],
        executable_id: str,
        candidate_id: str,
        completion_record_ids: tuple[str, ...],
        allow_engineering_fixture: bool = False,
    ) -> dict[str, Any]:
        """Derive Release claims only from current runtime Job completions."""

        from axiom_rift.runtime.guards import (
            EvidenceDepth,
            REQUIRED_CASES,
            REQUIRED_PARITY,
            REQUIRED_RELEASE_ARTIFACT_ROLES,
        )

        science = control["scientific"]
        mission_id = science["active_mission"]
        if mission_id is None or science["active_executable"] != executable_id:
            raise TransitionError("Release basis is not in the active Mission")
        if science["active_job"] is not None or science["active_repair"] is not None:
            raise TransitionError("Release transition cannot bypass active work")
        candidate_head = index.event_head(f"candidate:{executable_id}")
        candidate = (
            None
            if candidate_head is None
            else index.get(candidate_head.record_kind, candidate_head.record_id)
        )
        expected_candidate = (
            ("engineering-executable-fixture", "bound_fixture")
            if allow_engineering_fixture and self.engineering_fixture
            else ("candidate", "frozen")
        )
        if (
            candidate is None
            or (candidate.kind, candidate.status) != expected_candidate
            or candidate.record_id != candidate_id
        ):
            raise TransitionError("Release basis lacks the current frozen candidate")
        current_subject = self._current_subject(
            control, SubjectKind.EXECUTABLE, executable_id
        )
        current_source_receipts = sorted(
            self._require_runtime_source(
                index, binding["source_contract_id"]
            ).payload["evidence_receipt_id"]
            for binding in candidate.payload["source_bindings"]
        )
        parity: set[str] = set()
        cases: set[str] = set()
        artifact_hashes: set[str] = set()
        artifact_roles: dict[str, str] = {}
        artifact_role_hashes: set[str] = set()
        job_ids: list[str] = []
        runtime_permit_ids: list[str] = []
        depth_records: list[dict[str, str]] = []
        for completion_id in completion_record_ids:
            completion = index.get("job-completed", completion_id)
            if completion is None or completion.status != "success":
                raise TransitionError("Release references an unsuccessful or absent Job")
            runtime = completion.payload.get("runtime")
            if not isinstance(runtime, dict):
                raise TransitionError("Release references a non-runtime Job")
            job_id = completion.payload.get("job_id")
            declaration = (
                None if not isinstance(job_id, str) else index.get("job-declared", job_id)
            )
            start_id = completion.payload.get("start_record_id")
            started = (
                None
                if not isinstance(start_id, str)
                else index.get("job-started", start_id)
            )
            if declaration is None or started is None:
                raise TransitionError("Release Job provenance chain is incomplete")
            spec = declaration.payload.get("spec")
            binding = None if not isinstance(spec, dict) else spec.get("runtime_binding")
            if (
                not isinstance(binding, dict)
                or declaration.payload.get("mission_id") != mission_id
                or spec.get("evidence_subject")
                != {"kind": "Executable", "id": executable_id}
            ):
                raise TransitionError("Release Job belongs to another scientific subject")
            started_runtime = started.payload.get("runtime")
            if not isinstance(started_runtime, dict):
                raise TransitionError("Release Job did not start through RuntimePermit")
            for name in (
                "action",
                "candidate_id",
                "evidence_depth",
                "executable_id",
                "mission_id",
                "runtime_permit_id",
                "source_receipt_ids",
            ):
                if runtime.get(name) != started_runtime.get(name):
                    raise TransitionError(
                        "Release Job runtime provenance changed at completion"
                    )
            entry_id = runtime.get("runtime_entry_record_id")
            engine_entry = (
                None
                if not isinstance(entry_id, str)
                else index.get("runtime-engine-entry", entry_id)
            )
            if (
                engine_entry is None
                or engine_entry.payload.get("job_id") != job_id
                or engine_entry.payload.get("candidate_id") != candidate_id
                or engine_entry.payload.get("runtime_permit_id")
                != runtime.get("runtime_permit_id")
            ):
                raise TransitionError("Release Job lacks durable engine-entry provenance")
            if (
                runtime["mission_id"] != mission_id
                or runtime["candidate_id"] != candidate_id
                or runtime["executable_id"] != executable_id
                or sorted(runtime["source_receipt_ids"]) != current_source_receipts
                or runtime["action"] != binding["action"]
                or runtime["evidence_depth"] != binding["evidence_depth"]
            ):
                raise TransitionError("Release Job is stale or bound to another activation")
            permit_id = runtime["runtime_permit_id"]
            issued = index.get("permit-issued", permit_id)
            if (
                issued is None
                or issued.payload.get("kind") != PermitKind.RUNTIME.value
                or issued.payload.get("input_hash") != declaration.fingerprint
                or issued.payload.get("subject") != current_subject.payload()
                or runtime["action"] not in issued.payload.get("actions", [])
            ):
                raise TransitionError("Release Job RuntimePermit provenance is invalid")
            required_scope = {
                f"candidate:{candidate_id}",
                f"depth:{runtime['evidence_depth']}",
                f"executable:{executable_id}",
                f"job:{job_id}",
            }
            if not required_scope.issubset(issued.payload.get("scope", [])):
                raise TransitionError("Release Job RuntimePermit scope is incomplete")
            if not allow_engineering_fixture and runtime.get("release_eligible") is not True:
                raise TransitionError("Release Job validator did not authorize Release evidence")
            output_classes = completion.payload.get("output_classes")
            outputs = completion.payload.get("outputs")
            if not isinstance(output_classes, dict) or not isinstance(outputs, dict):
                raise TransitionError("Release Job output manifest is invalid")
            durable = {
                output_hash
                for output_name, output_hash in outputs.items()
                if output_classes.get(output_name) == "durable_evidence"
            }
            if not durable:
                raise TransitionError("Release Job has no durable evidence artifact")
            for artifact_hash in durable:
                self.evidence.verify(artifact_hash)
            runtime_roles = runtime.get("artifact_roles")
            if not isinstance(runtime_roles, dict) or not runtime_roles:
                raise TransitionError("Release Job lacks validated artifact roles")
            for role, artifact_hash in runtime_roles.items():
                if role in artifact_roles and artifact_roles[role] != artifact_hash:
                    raise TransitionError("Release artifact role has conflicting evidence")
                if role not in artifact_roles and artifact_hash in artifact_role_hashes:
                    raise TransitionError("one artifact cannot satisfy multiple Release roles")
                if artifact_hash not in durable:
                    raise TransitionError("Release role is not a durable Job output")
                artifact_roles[role] = artifact_hash
                artifact_role_hashes.add(artifact_hash)
            depth = runtime["evidence_depth"]
            observed_parity = set(runtime.get("parity_surfaces", []))
            observed_cases = set(runtime.get("materialization_cases", []))
            if depth == EvidenceDepth.EXECUTION_PROOF.value:
                if observed_cases or not observed_parity:
                    raise TransitionError("execution proof Release evidence is malformed")
                parity.update(observed_parity)
            elif depth == EvidenceDepth.MATERIALIZATION.value:
                if observed_parity or not observed_cases:
                    raise TransitionError("materialization Release evidence is malformed")
                cases.update(observed_cases)
            else:
                raise TransitionError("Release Job has an ineligible evidence depth")
            artifact_hashes.update(durable)
            job_ids.append(job_id)
            runtime_permit_ids.append(permit_id)
            depth_records.append({"completion_id": completion_id, "depth": depth})
        missing_parity = REQUIRED_PARITY - parity
        missing_cases = REQUIRED_CASES - cases
        missing_roles = REQUIRED_RELEASE_ARTIFACT_ROLES - set(artifact_roles)
        if missing_parity or missing_cases or missing_roles:
            raise TransitionError(
                f"Release evidence coverage is incomplete: "
                f"parity={sorted(missing_parity)!r}, cases={sorted(missing_cases)!r}, "
                f"roles={sorted(missing_roles)!r}"
            )
        handoff_hash = artifact_roles["local_handoff_manifest"]
        handoff_artifact = self.evidence.verify(handoff_hash)
        try:
            handoff = parse_canonical(
                (self.evidence._root / handoff_artifact.relative_path).read_bytes()
            )
        except ValueError as exc:
            raise TransitionError("local handoff manifest is not canonical") from exc
        expected_handoff = {
            "artifact_roles": {
                role: artifact_hash
                for role, artifact_hash in sorted(artifact_roles.items())
                if role != "local_handoff_manifest"
            },
            "authority_manifest_digest": control["authority"]["manifest_digest"],
            "candidate_id": candidate_id,
            "executable_id": executable_id,
            "mission_id": mission_id,
            "schema": "axiom_local_handoff.v1",
            "source_receipt_ids": current_source_receipts,
        }
        if handoff != expected_handoff:
            raise TransitionError("local handoff manifest differs from the Release basis")
        return {
            "artifact_hashes": sorted(artifact_hashes),
            "artifact_roles": dict(sorted(artifact_roles.items())),
            "completion_record_ids": list(completion_record_ids),
            "depth_records": depth_records,
            "job_ids": job_ids,
            "materialization_cases": sorted(cases),
            "parity_surfaces": sorted(parity),
            "runtime_permit_ids": runtime_permit_ids,
            "source_receipt_ids": current_source_receipts,
        }

    def validate_release_basis_fixture(
        self,
        *,
        executable_id: str,
        candidate_id: str,
        completion_record_ids: tuple[str, ...],
    ) -> Mapping[str, Any]:
        """Exercise the production Release derivation without creating Release authority."""

        if not self.engineering_fixture:
            raise TransitionError("fixture Release validation requires engineering mode")
        with WriterLock(self.lock_path):
            with self._open_authoritative_index() as index:
                control = self._require_stable_locked(index)
                assert control is not None
                return self._derive_release_basis_locked(
                    index=index,
                    control=control,
                    executable_id=executable_id,
                    candidate_id=candidate_id,
                    completion_record_ids=completion_record_ids,
                    allow_engineering_fixture=True,
                )

    def declare_release(
        self,
        *,
        release_id: str,
        executable_id: str,
        candidate_id: str,
        evidence: Any,
        operation_id: str,
    ) -> TransitionResult:
        from axiom_rift.runtime.guards import ReleaseEvidence

        if self.engineering_fixture:
            raise TransitionError("engineering fixtures cannot declare a Release")
        _require_ascii("release_id", release_id)
        _require_ascii("executable_id", executable_id)
        _require_ascii("candidate_id", candidate_id)
        if not isinstance(evidence, ReleaseEvidence):
            raise TransitionError("Release declaration requires ReleaseEvidence")

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            if science.get("active_release") is not None:
                raise TransitionError("another Release is already active")
            derived = self._derive_release_basis_locked(
                index=index,
                control=current,
                executable_id=executable_id,
                candidate_id=candidate_id,
                completion_record_ids=evidence.completion_record_ids,
            )
            release_payload = {
                "release_id": release_id,
                "candidate_id": candidate_id,
                "executable_id": executable_id,
                "mission_id": science["active_mission"],
                **derived,
            }
            release_hash = _digest(release_payload, domain="release")
            authorization = self._authorization(
                kind=SubjectKind.RELEASE,
                subject_id=release_id,
                semantic_hash=release_hash,
            )
            self._bind_authorization(body, authorization)
            science["active_release"] = {
                "id": release_id,
                "status": "declared",
                "candidate_id": candidate_id,
                "executable_id": executable_id,
            }
            body["next_action"] = {
                "kind": "issue_release_permit",
                "release_id": release_id,
            }
            record = _record(
                kind="release-declared",
                record_id=release_id,
                subject=f"Executable:{executable_id}",
                status="declared",
                fingerprint=release_hash,
                payload=release_payload,
                event_stream=f"release:{release_id}",
                event_sequence=1,
            )
            return body, [record], {
                "release_id": release_id,
                "release_hash": release_hash,
            }

        return self._commit(
            event_kind="release_declared",
            operation_id=operation_id,
            subject=f"Release:{release_id}",
            payload={
                "release_id": release_id,
                "candidate_id": candidate_id,
                "executable_id": executable_id,
                "completion_record_ids": list(evidence.completion_record_ids),
            },
            prepare=prepare,
        )

    def freeze_release(
        self,
        *,
        release_id: str,
        permit: Permit,
        operation_id: str,
    ) -> TransitionResult:
        if self.engineering_fixture:
            raise TransitionError("engineering fixtures cannot freeze a Release")
        _require_ascii("release_id", release_id)

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            active_release = science.get("active_release")
            if (
                not isinstance(active_release, dict)
                or active_release.get("id") != release_id
                or active_release.get("status") != "declared"
            ):
                raise TransitionError("Release is not the single active declaration")
            declared = index.get("release-declared", release_id)
            if declared is None or declared.status != "declared":
                raise TransitionError("Release declaration is absent")
            self._validate_permit_locked(
                control=current,
                index=index,
                permit=permit,
                expected_kind=PermitKind.RELEASE,
                action="freeze_release",
                subject_kind=SubjectKind.RELEASE,
                subject_id=release_id,
                expected_input_hash=declared.fingerprint,
                required_scope=(f"release:{release_id}",),
            )
            executable_id = declared.payload["executable_id"]
            derived = self._derive_release_basis_locked(
                index=index,
                control=current,
                executable_id=executable_id,
                candidate_id=declared.payload["candidate_id"],
                completion_record_ids=tuple(
                    declared.payload["completion_record_ids"]
                ),
            )
            for name, value in derived.items():
                if declared.payload.get(name) != value:
                    raise TransitionError("Release declaration differs from current evidence")
            if _digest(dict(declared.payload), domain="release") != declared.fingerprint:
                raise TransitionError("Release declaration identity is invalid")
            record = _record(
                kind="release",
                record_id=release_id,
                subject=f"Executable:{executable_id}",
                status="frozen",
                fingerprint=declared.fingerprint,
                payload=dict(declared.payload),
                event_stream=f"release:{release_id}",
                event_sequence=2,
            )
            consumption = self._permit_consumption_record(permit, operation_id)
            self._drop_authorization(body, SubjectKind.RELEASE, release_id)
            active_release["status"] = "frozen"
            body["next_action"] = {
                "kind": "close_mission",
                "outcome": "completed_pre_live_handoff",
                "basis_record_id": release_id,
            }
            return body, [consumption, record], {"release_id": release_id}

        return self._commit(
            event_kind="release_frozen",
            operation_id=operation_id,
            subject=f"Release:{release_id}",
            payload={"release_id": release_id, "permit_id": permit.permit_id},
            prepare=prepare,
        )

    def abandon_release(
        self,
        *,
        release_id: str,
        disposition: str,
        reason: str,
        operation_id: str,
    ) -> TransitionResult:
        """Dispose the one active Release without changing its Executable identity."""

        if disposition not in {"abandoned", "invalidated"}:
            raise TransitionError("Release disposition is not typed")
        _require_ascii("release_id", release_id)
        _require_ascii("reason", reason)

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            active = science.get("active_release")
            if not isinstance(active, dict) or active.get("id") != release_id:
                raise TransitionError("Release is not active")
            head = index.event_head(f"release:{release_id}")
            latest = None if head is None else index.get(head.record_kind, head.record_id)
            if latest is None or latest.status not in {"declared", "frozen"}:
                raise TransitionError("active Release projection is invalid")
            if latest.status == "frozen" and disposition != "invalidated":
                raise TransitionError("a frozen Release may only be invalidated")
            record_id = canonical_digest(
                domain="release-disposition",
                payload={
                    "release_id": release_id,
                    "prior_status": latest.status,
                    "disposition": disposition,
                    "reason": reason,
                },
            )
            record = _record(
                kind="release-disposition",
                record_id=record_id,
                subject=f"Release:{release_id}",
                status=disposition,
                fingerprint=latest.fingerprint,
                payload={"prior_status": latest.status, "reason": reason},
                event_stream=f"release:{release_id}",
                event_sequence=head.sequence + 1,
            )
            self._drop_authorization(body, SubjectKind.RELEASE, release_id)
            science["active_release"] = None
            body["next_action"] = {
                "kind": "plan_candidate_bound_evidence",
                "executable_id": science["active_executable"],
            }
            return body, [record], {"release_id": release_id, "disposition": disposition}

        return self._commit(
            event_kind="release_disposed",
            operation_id=operation_id,
            subject=f"Release:{release_id}",
            payload={"disposition": disposition, "reason": reason},
            prepare=prepare,
        )

    def register_trial(
        self,
        *,
        executable: Any,
        operation_id: str,
    ) -> TransitionResult:
        from axiom_rift.core.identity import ExecutableSpec

        if not isinstance(executable, ExecutableSpec):
            raise TransitionError("trial registration requires an ExecutableSpec")
        executable_id = executable.identity
        executable_hash = executable_id.removeprefix("executable:")
        _require_digest("executable_hash", executable_hash)

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            batch = current["scientific"]["active_batch"]
            if not isinstance(batch, dict):
                raise TransitionError("trial registration requires an active Batch")
            batch_record = index.get("batch-open", batch["id"])
            if batch_record is None:
                raise TransitionError("active Batch declaration is unavailable")
            declared_sources = set(
                batch_record.payload["spec"].get("source_contract_ids", [])
            )
            executable_sources = set(executable.source_contracts)
            if not executable_sources.issubset(declared_sources):
                raise TransitionError(
                    "Executable uses an external source absent from the frozen Batch"
                )
            for source_id in executable_sources:
                self._require_runtime_source(index, source_id)
            record_kind = "engineering-evaluation-fixture" if self.engineering_fixture else "trial"
            existing = index.get(record_kind, executable_id)
            if existing is not None:
                if existing.fingerprint != executable_hash:
                    raise RecordCollisionError("Executable identity collision")
                return self._body(current), [], {"trial_delta": 0, "cache_hit": True}
            status = "engineering_only" if self.engineering_fixture else "evaluated"
            trial_head = index.event_head(f"batch-trials:{batch['id']}")
            evaluated_count = 0 if trial_head is None else trial_head.sequence
            max_trials = batch_record.payload["spec"]["max_trials"]
            if evaluated_count >= max_trials:
                raise TransitionError("frozen Batch trial budget is exhausted")
            study_id = current["scientific"]["active_study"]
            study_record = index.get("study-open", study_id)
            if study_record is None:
                raise TransitionError("active Study declaration is unavailable")
            material_identity = study_record.payload["material_identity"]
            if (
                not self.engineering_fixture
                and executable.data_contract != f"data:{material_identity}"
            ):
                raise TransitionError(
                    "Executable data contract differs from the active Study material"
                )
            record = _record(
                kind=record_kind,
                record_id=executable_id,
                subject=f"Batch:{batch['id']}",
                status=status,
                fingerprint=executable_hash,
                payload={
                    "engineering_fixture": self.engineering_fixture,
                    "executable": executable.to_identity_payload(),
                    "scientific_eligible": not self.engineering_fixture,
                    "scheduler_eligible": False,
                    "trial_delta": 0 if self.engineering_fixture else 1,
                    "material_identity": material_identity,
                    "mission_id": study_record.payload.get("mission_id"),
                    "portfolio_axis_id": study_record.payload.get("portfolio_axis_id"),
                    "portfolio_axis_identity": study_record.payload.get(
                        "portfolio_axis_identity"
                    ),
                    "portfolio_decision_id": study_record.payload.get(
                        "portfolio_decision_id"
                    ),
                    "portfolio_snapshot_id": study_record.payload.get(
                        "portfolio_snapshot_id"
                    ),
                    "study_id": study_id,
                },
                event_stream=f"batch-trials:{batch['id']}",
                event_sequence=evaluated_count + 1,
            )
            records = [record]
            global_multiplicity: int | None = None
            if not self.engineering_fixture:
                material_head = index.event_head(
                    f"material-trial:{material_identity}"
                )
                material_sequence = 1 if material_head is None else material_head.sequence + 1
                global_multiplicity = (
                    study_record.payload["prior_global_multiplicity"]
                    + material_sequence
                    - study_record.payload["prior_material_trial_count"]
                )
                accounting_id = canonical_digest(
                    domain="material-trial",
                    payload={
                        "material_identity": material_identity,
                        "executable_id": executable_id,
                    },
                )
                records.append(
                    _record(
                        kind="trial-accounting",
                        record_id=accounting_id,
                        subject=f"Material:{material_identity}",
                        status="counted",
                        fingerprint=executable_hash,
                        payload={
                            "executable_id": executable_id,
                            "global_multiplicity": global_multiplicity,
                            "study_id": study_id,
                        },
                        event_stream=f"material-trial:{material_identity}",
                        event_sequence=material_sequence,
                    )
                )
            return self._body(current), records, {
                "trial_delta": 0 if self.engineering_fixture else 1,
                "cache_hit": False,
                "global_multiplicity": global_multiplicity,
            }

        return self._commit(
            event_kind="trial_registered",
            operation_id=operation_id,
            subject=f"Executable:{executable_id}",
            payload={
                "executable_id": executable_id,
                "executable_hash": executable_hash,
            },
            prepare=prepare,
        )

    def record_lineage(
        self,
        *,
        parent_executable_id: str,
        child_executable_id: str,
        relation: str,
        operation_id: str,
    ) -> TransitionResult:
        if parent_executable_id == child_executable_id:
            raise TransitionError("Lineage requires distinct Executables")
        allowed_relations = {
            "mechanism_branch",
            "contrast",
            "recombination",
            "synthesis",
            "semantic_refinement",
        }
        if relation not in allowed_relations:
            raise TransitionError("Lineage relation is not typed")
        for identity in (parent_executable_id, child_executable_id):
            if not identity.startswith("executable:") or len(identity) != 75:
                raise TransitionError("Lineage members must be Executable identities")
        lineage_id = canonical_digest(
            domain="lineage",
            payload={
                "parent": parent_executable_id,
                "child": child_executable_id,
                "relation": relation,
            },
        )

        def prepare(current: dict[str, Any] | None, _index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            if current["scientific"]["active_mission"] is None:
                raise TransitionError("Lineage requires an active Mission")
            for identity in (parent_executable_id, child_executable_id):
                candidate_head = _index.event_head(f"candidate:{identity}")
                if (
                    _index.get("trial", identity) is None
                    and _index.get("engineering-evaluation-fixture", identity) is None
                    and candidate_head is None
                ):
                    raise TransitionError("Lineage member is not a registered Executable")
            record = _record(
                kind="lineage",
                record_id=lineage_id,
                subject=f"Executable:{child_executable_id}",
                status="related",
                fingerprint=lineage_id,
                payload={
                    "parent_executable_id": parent_executable_id,
                    "child_executable_id": child_executable_id,
                    "relation": relation,
                    "evidence_merged": False,
                },
            )
            return self._body(current), [record], {"lineage_id": lineage_id}

        return self._commit(
            event_kind="lineage_recorded",
            operation_id=operation_id,
            subject=f"Executable:{child_executable_id}",
            payload={"lineage_id": lineage_id},
            prepare=prepare,
        )

    def record_portfolio_snapshot(
        self,
        *,
        snapshot: Any,
        operation_id: str,
    ) -> TransitionResult:
        from axiom_rift.research.portfolio import PortfolioSnapshot

        if not isinstance(snapshot, PortfolioSnapshot):
            raise TransitionError("snapshot must be a PortfolioSnapshot")

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            science = current["scientific"]
            if science["active_mission"] != snapshot.mission_id:
                raise TransitionError("Portfolio snapshot belongs to another Mission")
            if science["active_initiative"] is None:
                raise TransitionError("Portfolio snapshot requires an active Initiative")
            if any(
                science[name] is not None
                for name in (
                    "active_batch",
                    "active_executable",
                    "active_job",
                    "active_repair",
                    "active_study",
                )
            ):
                raise TransitionError("Portfolio snapshot cannot bypass active work")
            head = index.event_head(f"portfolio:{snapshot.mission_id}")
            sequence = 1 if head is None else head.sequence + 1
            if head is None:
                standard = snapshot.exhaustion_standard_value()
                if not self.engineering_fixture and not isinstance(standard, dict):
                    raise TransitionError(
                        "scientific Portfolio requires a preregistered exhaustion standard"
                    )
                if isinstance(standard, dict):
                    families = {axis.mechanism_family for axis in snapshot.axes}
                    if (
                        len(snapshot.axes) < standard["minimum_axes"]
                        or len(families) < standard["minimum_mechanism_families"]
                    ):
                        raise TransitionError(
                            "initial Portfolio is smaller than its exhaustion standard"
                        )
                if (
                    current["next_action"].get("kind") != "build_portfolio"
                    or current["next_action"].get("initiative_id")
                    != science["active_initiative"]
                ):
                    raise TransitionError(
                        "initial Portfolio snapshot is not the exact Initiative action"
                    )
            else:
                prior = index.get(head.record_kind, head.record_id)
                if prior is None or prior.kind != "portfolio-snapshot":
                    raise TransitionError("current Portfolio snapshot is unavailable")
                next_action = current["next_action"]
                decision_id = next_action.get("decision_id")
                decision = (
                    None
                    if not isinstance(decision_id, str)
                    else index.get("portfolio-decision", decision_id)
                )
                if (
                    next_action.get("kind") != "record_portfolio_snapshot"
                    or decision is None
                    or decision.payload.get("portfolio_snapshot_id") != prior.record_id
                ):
                    raise TransitionError(
                        "Portfolio snapshot mutation requires the current structural Decision"
                    )
                old_axes = {axis["axis_id"]: axis for axis in prior.payload["axes"]}
                new_payload = snapshot.to_identity_payload()
                new_axes = {axis["axis_id"]: axis for axis in new_payload["axes"]}
                if (
                    new_payload.get("exhaustion_standard")
                    != prior.payload.get("exhaustion_standard")
                ):
                    raise TransitionError(
                        "Portfolio exhaustion standard is immutable within a Mission"
                    )
                if not set(old_axes).issubset(new_axes):
                    raise TransitionError("Portfolio axes cannot be silently removed")
                for axis_id, old_axis in old_axes.items():
                    if new_axes[axis_id]["axis_identity"] != old_axis["axis_identity"]:
                        raise TransitionError(
                            "Portfolio axis meaning is immutable within a Mission"
                        )
                    if old_axis["status"] == "pruned" and new_axes[axis_id]["status"] != "pruned":
                        raise TransitionError("a pruned Portfolio axis cannot reopen")
                action = next_action.get("action")
                target_id = next_action.get("target_id")
                if action in {"preserve", "prune"}:
                    if set(new_axes) != set(old_axes) or target_id not in old_axes:
                        raise TransitionError(
                            "axis disposition snapshot may change one declared target only"
                        )
                    expected_status = "preserved" if action == "preserve" else "pruned"
                    for axis_id, old_axis in old_axes.items():
                        wanted = expected_status if axis_id == target_id else old_axis["status"]
                        if new_axes[axis_id]["status"] != wanted:
                            raise TransitionError(
                                "Portfolio snapshot differs from its structural Decision"
                            )
                elif action == "new_mechanism":
                    added = set(new_axes) - set(old_axes)
                    old_families = {
                        axis["mechanism_family"] for axis in old_axes.values()
                    }
                    if (
                        not added
                        or any(
                            new_axes[axis_id]["status"] != old_axis["status"]
                            for axis_id, old_axis in old_axes.items()
                        )
                        or not any(
                            new_axes[axis_id]["mechanism_family"] not in old_families
                            for axis_id in added
                        )
                    ):
                        raise TransitionError(
                            "new_mechanism must add a genuinely distinct untouched axis"
                        )
                else:
                    raise TransitionError(
                        "Portfolio Decision does not authorize snapshot mutation"
                    )
            body = self._body(current)
            body["next_action"] = {
                "kind": "portfolio_decision",
                "portfolio_snapshot_id": snapshot.identity,
            }
            record = _record(
                kind="portfolio-snapshot",
                record_id=snapshot.identity,
                subject=f"Mission:{snapshot.mission_id}",
                status=(
                    "closed"
                    if all(axis.status == "pruned" for axis in snapshot.axes)
                    else "current"
                ),
                fingerprint=snapshot.identity.removeprefix("portfolio:"),
                payload=snapshot.to_identity_payload(),
                event_stream=f"portfolio:{snapshot.mission_id}",
                event_sequence=sequence,
            )
            return body, [record], {"portfolio_snapshot_id": snapshot.identity}

        return self._commit(
            event_kind="portfolio_snapshot_recorded",
            operation_id=operation_id,
            subject=f"Mission:{snapshot.mission_id}",
            payload={"portfolio_snapshot_id": snapshot.identity},
            prepare=prepare,
        )

    def record_portfolio_decision(
        self,
        *,
        decision: Any,
        operation_id: str,
    ) -> TransitionResult:
        from axiom_rift.research.portfolio import PortfolioAction, PortfolioDecision

        if not isinstance(decision, PortfolioDecision):
            raise TransitionError("decision must be a PortfolioDecision")
        decision_hash = decision.identity.removeprefix("decision:")
        _require_digest("decision hash", decision_hash)

        def prepare(current: dict[str, Any] | None, _index: LocalIndex):
            if current is None or current["scientific"]["active_mission"] is None:
                raise TransitionError("Portfolio Decision requires an active Mission")
            science = current["scientific"]
            if science["active_initiative"] is None:
                raise TransitionError("Portfolio Decision requires an active Initiative")
            if any(
                science[name] is not None
                for name in (
                    "active_batch",
                    "active_executable",
                    "active_job",
                    "active_repair",
                    "active_study",
                )
            ):
                raise TransitionError("Portfolio Decision cannot bypass active work")
            portfolio_head = _index.event_head(
                f"portfolio:{science['active_mission']}"
            )
            snapshot = (
                None
                if portfolio_head is None
                else _index.get(portfolio_head.record_kind, portfolio_head.record_id)
            )
            if snapshot is None or snapshot.kind != "portfolio-snapshot":
                raise TransitionError("Portfolio Decision requires a current snapshot")
            next_action = current["next_action"]
            if (
                next_action.get("kind") != "portfolio_decision"
                or (
                    next_action.get("portfolio_snapshot_id") is not None
                    and next_action.get("portfolio_snapshot_id") != snapshot.record_id
                )
            ):
                raise TransitionError("Portfolio Decision is not the exact next action")
            axes_by_id = {
                axis["axis_id"]: axis for axis in snapshot.payload["axes"]
            }
            eligible_targets = {
                axis["axis_id"]
                for axis in snapshot.payload["axes"]
                if axis["status"] != "pruned"
            }
            if any(option.target_id not in eligible_targets for option in decision.options):
                raise TransitionError("Portfolio Decision names an undeclared target axis")
            if (
                decision.recent_positive_lineage_id is not None
                and decision.recent_positive_lineage_id not in eligible_targets
                and _index.get("lineage", decision.recent_positive_lineage_id) is None
            ):
                raise TransitionError("recent-positive reference is not durable")
            body = self._body(current)
            next_kind = (
                "record_portfolio_snapshot"
                if decision.chosen.action
                in {
                    PortfolioAction.NEW_MECHANISM,
                    PortfolioAction.PRESERVE,
                    PortfolioAction.PRUNE,
                }
                else "execute_portfolio_decision"
            )
            target_axis = axes_by_id[decision.chosen.target_id]
            body["next_action"] = {
                "kind": next_kind,
                "decision_id": decision.identity,
                "action": decision.chosen.action.value,
                "target_id": decision.chosen.target_id,
                "target_axis_identity": target_axis["axis_identity"],
                "portfolio_snapshot_id": snapshot.record_id,
            }
            record = _record(
                kind="portfolio-decision",
                record_id=decision.identity,
                subject=f"Mission:{science['active_mission']}",
                status=decision.chosen.action.value,
                fingerprint=decision_hash,
                payload={
                    **decision.to_identity_payload(),
                    "portfolio_snapshot_id": snapshot.record_id,
                    "target_axis_identity": target_axis["axis_identity"],
                },
            )
            return body, [record], {"decision_id": decision.identity}

        return self._commit(
            event_kind="portfolio_decision_recorded",
            operation_id=operation_id,
            subject="Portfolio:active",
            payload={"decision_id": decision.identity},
            prepare=prepare,
        )

    def record_negative_memory(
        self,
        *,
        memory: Any,
        operation_id: str,
    ) -> TransitionResult:
        from axiom_rift.research.trials import NegativeMemory

        if self.engineering_fixture:
            raise TransitionError("engineering fixtures cannot create negative memory")
        if not isinstance(memory, NegativeMemory):
            raise TransitionError("memory must be a NegativeMemory")

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None or current["scientific"]["active_mission"] is None:
                raise TransitionError("negative memory requires an active Mission")
            mission_id = current["scientific"]["active_mission"]
            trial = index.get("trial", memory.executable_identity)
            if trial is None:
                raise TransitionError("negative memory requires a counted Executable trial")
            trial_study_id = trial.payload.get("study_id")
            trial_study = (
                None
                if not isinstance(trial_study_id, str)
                else index.get("study-open", trial_study_id)
            )
            if (
                trial_study is None
                or trial.payload.get("portfolio_axis_identity")
                != trial_study.payload.get("portfolio_axis_identity")
                or trial.payload.get("portfolio_snapshot_id")
                != trial_study.payload.get("portfolio_snapshot_id")
            ):
                raise TransitionError("negative memory trial Portfolio lineage is incomplete")
            holdout_context_id: str | None = None
            executed_evidence_modes: set[str] = set()
            for reference in memory.evidence_references:
                evidence = index.get("job-completed", reference)
                failure = None if evidence is None else evidence.payload.get("failure")
                scientific = None if evidence is None else evidence.payload.get("scientific")
                if (
                    evidence is None
                    or evidence.status != "failed"
                    or not isinstance(failure, dict)
                    or failure.get("failure_kind") != "scientific_falsification"
                    or not isinstance(scientific, dict)
                    or scientific.get("verdict") != "failed"
                    or scientific.get("scientific_eligible") is not True
                    or scientific.get("executable_id") != memory.executable_identity
                ):
                    raise TransitionError("negative memory evidence reference is invalid")
                evidence_modes = scientific.get("executed_evidence_modes")
                normalized_modes = _require_study_evidence_modes(
                    {"evidence_modes": evidence_modes}
                )
                if list(normalized_modes) != evidence_modes:
                    raise TransitionError(
                        "negative memory evidence modes are not canonical"
                    )
                executed_evidence_modes.update(normalized_modes)
                declaration = index.get("job-declared", evidence.payload["job_id"])
                active_holdout = current["scientific"].get(
                    "active_holdout_evaluation"
                )
                holdout_binding = (
                    None
                    if declaration is None
                    else declaration.payload["spec"].get("holdout_binding")
                )
                candidate = (
                    None
                    if not isinstance(active_holdout, dict)
                    else index.get(
                        "candidate", active_holdout.get("candidate_id", "")
                    )
                )
                same_study_context = (
                    declaration is not None
                    and declaration.payload.get("study_id") == trial_study_id
                )
                holdout_context = (
                    declaration is not None
                    and isinstance(active_holdout, dict)
                    and declaration.payload.get("study_id") is None
                    and evidence.payload.get("job_id") == active_holdout.get("job_id")
                    and active_holdout.get("executable_id")
                    == memory.executable_identity
                    and holdout_binding
                    == {"holdout_id": active_holdout.get("holdout_id")}
                    and candidate is not None
                    and candidate.payload.get("mission_id") == mission_id
                    and candidate.subject
                    == f"Executable:{memory.executable_identity}"
                )
                if (
                    declaration is None
                    or declaration.payload["mission_id"] != mission_id
                    or not (same_study_context or holdout_context)
                    or declaration.payload["spec"]["evidence_subject"]
                    != {"kind": "Executable", "id": memory.executable_identity}
                ):
                    raise TransitionError("negative evidence is not Executable/Mission bound")
                if holdout_context:
                    holdout_context_id = active_holdout["holdout_id"]
            record = _record(
                kind="negative-memory",
                record_id=memory.identity,
                subject=f"Executable:{memory.executable_identity}",
                status="durable",
                fingerprint=memory.executable_identity,
                payload={
                    "scope": memory.scope,
                    "evidence_references": list(memory.evidence_references),
                    "executed_evidence_modes": sorted(executed_evidence_modes),
                    "reason": memory.reason,
                    "reopen_condition": memory.reopen_condition,
                    "mission_id": mission_id,
                    "portfolio_axis_id": trial.payload.get("portfolio_axis_id"),
                    "portfolio_axis_identity": trial.payload.get(
                        "portfolio_axis_identity"
                    ),
                    "portfolio_snapshot_id": trial.payload.get(
                        "portfolio_snapshot_id"
                    ),
                    "study_id": trial_study_id,
                    "holdout_id": holdout_context_id,
                },
            )
            return self._body(current), [record], {"negative_memory_id": memory.identity}

        return self._commit(
            event_kind="negative_memory_recorded",
            operation_id=operation_id,
            subject=f"Executable:{memory.executable_identity}",
            payload={"negative_memory_id": memory.identity},
            prepare=prepare,
        )

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
            current_source_receipts = [
                self._require_runtime_source(
                    index, source_id, error_type=PermitError
                ).payload["evidence_receipt_id"]
                for source_id in source_contracts
            ]
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
                "source_receipt_ids": sorted(current_source_receipts),
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
                "current_source_receipts": sorted(current_source_receipts),
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
            runtime_binding = declared_spec.get("runtime_binding")
            for domain, binding_name in (
                ("external", "external_dependency_binding"),
                ("scientific", "scientific_binding"),
                ("source", "source_binding"),
                ("runtime", "runtime_binding"),
            ):
                binding = declared_spec.get(binding_name)
                if isinstance(binding, dict):
                    try:
                        self.validation_registry.require_registered(
                            validator_id=binding["validator_id"], domain=domain
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
                source_receipts = [
                    self._require_runtime_source(
                        index, source_id, error_type=PermitError
                    ).payload["evidence_receipt_id"]
                    for source_id in source_contracts
                ]
                runtime_provenance = {
                    "action": runtime_binding["action"],
                    "candidate_id": candidate.record_id,
                    "evidence_depth": runtime_binding["evidence_depth"],
                    "executable_id": executable_id,
                    "mission_id": science["active_mission"],
                    "runtime_permit_id": runtime_permit.permit_id,
                    "source_receipt_ids": source_receipts,
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
            return body, [consumption, record], {"job_id": job["id"]}

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
    ) -> tuple[Any, dict[str, Any]]:
        artifacts: list[ValidationArtifact] = []
        for output_name, output_hash in sorted(output_manifest.items()):
            if output_classes.get(output_name) != "durable_evidence":
                continue
            artifact = self.evidence.verify(output_hash)
            artifacts.append(
                ValidationArtifact(
                    output_name=output_name,
                    sha256=artifact.sha256,
                    _source=self.evidence._root / artifact.relative_path,
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

    def _derive_runtime_job_evidence(
        self,
        *,
        job_id: str,
        job_hash: str,
        binding: Mapping[str, Any],
        provenance: Mapping[str, Any],
        output_manifest: Mapping[str, Any],
        output_classes: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Parse a content-addressed runtime result packet and derive claims."""

        result_name = binding["result_manifest_output"]
        result_hash = output_manifest.get(result_name)
        if not isinstance(result_hash, str):
            raise TransitionError("runtime result manifest output is absent")
        artifact = self.evidence.verify(result_hash)
        try:
            value = parse_canonical(
                (self.evidence._root / artifact.relative_path).read_bytes()
            )
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
        claims: set[str] = set()
        measurement_hashes: set[str] = set()
        for observation in observations:
            if not isinstance(observation, dict) or set(observation) != {
                "claim_id",
                "measurement_artifact_hash",
                "status",
            }:
                raise TransitionError("runtime observation schema is invalid")
            claim_id = observation["claim_id"]
            measurement_hash = observation["measurement_artifact_hash"]
            if (
                type(claim_id) is not str
                or claim_id in claims
                or measurement_hash not in durable_hashes
            ):
                raise TransitionError("runtime observation is not artifact-bound")
            self.evidence.verify(measurement_hash)
            claims.add(claim_id)
            measurement_hashes.add(measurement_hash)
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
        artifact = self.evidence.verify(result_hash)
        try:
            value = parse_canonical(
                (self.evidence._root / artifact.relative_path).read_bytes()
            )
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
        expected_outcome: str,
    ) -> dict[str, Any]:
        result_name = binding["result_manifest_output"]
        result_hash = output_manifest.get(result_name)
        if not isinstance(result_hash, str):
            raise TransitionError("scientific result manifest output is absent")
        artifact = self.evidence.verify(result_hash)
        try:
            value = parse_canonical(
                (self.evidence._root / artifact.relative_path).read_bytes()
            )
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
        )
        expected_verdict = {
            "success": "passed",
            "failed": "failed",
            "not_evaluable": "not_evaluable",
        }[expected_outcome]
        if (
            validated.verdict != expected_verdict
            or set(validated.claims) != claims
            or set(validated.measurement_artifact_hashes) != measurement_hashes
            or dict(validated.facts)
            != {"executed_evidence_modes": list(binding["evidence_modes"])}
            or not validated.scientific_eligible
        ):
            raise TransitionError(
                "scientific evidence was not derived as eligible by the validator"
            )
        return {
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
        artifact = self.evidence.verify(result_hash)
        try:
            value = parse_canonical(
                (self.evidence._root / artifact.relative_path).read_bytes()
            )
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
        if outcome not in {"success", "failed", "not_evaluable"}:
            raise TransitionError("invalid Job outcome")
        failure_manifest: dict[str, Any] | None = None
        if outcome == "success":
            if failure is not None:
                raise TransitionError("a successful Job cannot carry failure evidence")
        else:
            if failure is None:
                raise TransitionError("failed or not-evaluable Job requires failure evidence")
            failure_manifest = _require_manifest(
                "failure",
                failure,
                required={
                    "failure_kind",
                    "minimum_reproduction_evidence",
                    "root_cause",
                    "interrupted_action",
                    "resume_action",
                },
            )
            for name in ("root_cause", "interrupted_action", "resume_action"):
                _require_ascii(name, failure_manifest[name])
            if failure_manifest["failure_kind"] not in {
                "engineering",
                "runtime_source_ineligibility",
                "scientific_falsification",
                "not_evaluable",
                "external_dependency",
            }:
                raise TransitionError("Job failure_kind is not typed")
            references = failure_manifest["minimum_reproduction_evidence"]
            if not isinstance(references, list) or not references:
                raise TransitionError("failure requires minimum reproduction evidence")
            for reference in references:
                self.evidence.verify(reference)
            if failure_manifest["failure_kind"] == "external_dependency":
                if set(failure_manifest) - {
                    "failure_kind",
                    "minimum_reproduction_evidence",
                    "root_cause",
                    "interrupted_action",
                    "resume_action",
                    "external_dependency_id",
                    "observed_external_state",
                }:
                    raise TransitionError("external dependency failure has unknown fields")
                for name in ("external_dependency_id", "observed_external_state"):
                    _require_ascii(name, failure_manifest.get(name))
            failure_manifest["failure_signature"] = _digest(
                {
                    "minimum_reproduction_evidence": references,
                    "failure_kind": failure_manifest["failure_kind"],
                    "root_cause": failure_manifest["root_cause"],
                    "interrupted_action": failure_manifest["interrupted_action"],
                },
                domain="job-failure",
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
            expected_outputs = declared_spec.get("expected_outputs")
            output_classes = declared_spec.get("output_classes")
            if not isinstance(expected_outputs, list) or not isinstance(output_classes, dict):
                raise TransitionError("current Job output declaration is invalid")
            runtime_binding = declared_spec.get("runtime_binding")
            runtime_manifest: dict[str, Any] | None = None
            scientific_binding = declared_spec.get("scientific_binding")
            scientific_manifest: dict[str, Any] | None = None
            source_binding = declared_spec.get("source_binding")
            source_manifest: dict[str, Any] | None = None
            external_binding = declared_spec.get("external_dependency_binding")
            external_manifest: dict[str, Any] | None = None
            start_record_id = job.get("start_record_id")
            start_record = (
                None
                if not isinstance(start_record_id, str)
                else _index.get("job-started", start_record_id)
            )
            if start_record is None:
                raise TransitionError("current Job start provenance is unavailable")
            if runtime_binding is None:
                if start_record.payload.get("runtime") is not None:
                    raise TransitionError("generic Job cannot produce runtime evidence")
            else:
                provenance = start_record.payload.get("runtime")
                if not isinstance(provenance, dict):
                    raise TransitionError("runtime Job start lacks RuntimePermit provenance")
                runtime_entry_id = job.get("runtime_entry_record_id")
                runtime_entry = (
                    None
                    if not isinstance(runtime_entry_id, str)
                    else _index.get("runtime-engine-entry", runtime_entry_id)
                )
                if (
                    runtime_entry is None
                    or runtime_entry.status != "validated"
                    or runtime_entry.subject != f"Job:{job_id}"
                    or runtime_entry.fingerprint != job["hash"]
                    or runtime_entry.payload.get("job_start_record_id") != start_record_id
                    or runtime_entry.payload.get("runtime_permit_id")
                    != provenance.get("runtime_permit_id")
                    or runtime_entry.payload.get("candidate_id")
                    != provenance.get("candidate_id")
                    or runtime_entry.payload.get("source_receipt_ids")
                    != sorted(provenance.get("source_receipt_ids", []))
                ):
                    raise TransitionError(
                        "runtime Job completion lacks its exact engine-entry attestation"
                    )
                provenance = {**provenance, "runtime_entry_record_id": runtime_entry_id}
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
                runtime_manifest = self._derive_runtime_job_evidence(
                    job_id=job_id,
                    job_hash=job["hash"],
                    binding=runtime_binding,
                    provenance=provenance,
                    output_manifest=output_manifest,
                    output_classes=output_classes,
                )
            if source_binding is not None and outcome == "success":
                source_manifest = self._derive_source_job_evidence(
                    job_id=job_id,
                    job_hash=job["hash"],
                    mission_id=declaration.payload["mission_id"],
                    evidence_subject=declared_spec["evidence_subject"],
                    binding=source_binding,
                    output_manifest=output_manifest,
                    output_classes=output_classes,
                )
            if scientific_binding is not None and (
                outcome == "success"
                or (
                    failure_manifest is not None
                    and failure_manifest["failure_kind"] == "scientific_falsification"
                )
                or (
                    declared_spec.get("holdout_binding") is not None
                    and outcome == "not_evaluable"
                    and failure_manifest is not None
                    and failure_manifest["failure_kind"] == "not_evaluable"
                )
            ):
                if set(output_manifest) != set(expected_outputs):
                    raise TransitionError(
                        "scientific evidence disposition requires every declared output"
                    )
                scientific_manifest = self._derive_scientific_job_evidence(
                    job_id=job_id,
                    job_hash=job["hash"],
                    mission_id=declaration.payload["mission_id"],
                    executable_id=declared_spec["evidence_subject"]["id"],
                    binding=scientific_binding,
                    output_manifest=output_manifest,
                    output_classes=output_classes,
                    expected_outcome=outcome,
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
                external_manifest = self._derive_external_dependency_evidence(
                    job_id=job_id,
                    job_hash=job["hash"],
                    mission_id=declaration.payload["mission_id"],
                    binding=external_binding,
                    outcome=outcome,
                    output_manifest=output_manifest,
                    output_classes=output_classes,
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
            record_id = canonical_digest(
                domain="job-completion",
                payload={
                    "job_id": job_id,
                    "outcome": outcome,
                    "outputs": dict(output_manifest),
                    "external": external_manifest,
                    "runtime": runtime_manifest,
                    "scientific": scientific_manifest,
                    "source": source_manifest,
                },
            )
            record = _record(
                kind="job-completed",
                record_id=record_id,
                subject=f"Job:{job_id}",
                status=outcome,
                fingerprint=job["hash"],
                payload={
                    "job_id": job_id,
                    "outputs": dict(output_manifest),
                    "output_classes": dict(output_classes),
                    "failure": failure_manifest,
                    "external": external_manifest,
                    "start_record_id": start_record_id,
                    "runtime": runtime_manifest,
                    "scientific": scientific_manifest,
                    "source": source_manifest,
                },
                event_stream=f"job-attempt:{declaration.payload['work_fingerprint']}",
                event_sequence=(
                    _index.event_head(
                        f"job-attempt:{declaration.payload['work_fingerprint']}"
                    ).sequence
                    + 1
                ),
            )
            science["active_job"] = None
            self._drop_authorization(body, SubjectKind.JOB, job_id)
            body["next_action"] = {"kind": "judge_job_evidence", "job_id": job_id}
            records = [record]
            if outcome == "success":
                success_fingerprint = declaration.payload.get("success_fingerprint")
                _require_digest("Job success fingerprint", success_fingerprint)
                records.append(
                    _record(
                        kind="job-success-cache",
                        record_id=success_fingerprint,
                        subject=f"Mission:{declaration.payload['mission_id']}",
                        status="reusable",
                        fingerprint=job["hash"],
                        payload={
                            "completion_record_id": record_id,
                            "expected_outputs": list(expected_outputs),
                            "job_id": job_id,
                            "mission_id": declaration.payload["mission_id"],
                            "output_classes": dict(output_classes),
                        },
                    )
                )
            if isinstance(external_binding, dict):
                dependency_head = _index.event_head(
                    f"external-dependency:{external_binding['dependency_id']}"
                )
                attempt_sequence = (
                    1 if dependency_head is None else dependency_head.sequence + 1
                )
                attempt_id = canonical_digest(
                    domain="external-dependency-attempt",
                    payload={
                        "completion_record_id": record_id,
                        "dependency_id": external_binding["dependency_id"],
                        "recovery_path_id": external_binding["recovery_path_id"],
                    },
                )
                records.append(
                    _record(
                        kind="external-dependency-attempt",
                        record_id=attempt_id,
                        subject=f"Mission:{declaration.payload['mission_id']}",
                        status=(
                            "available"
                            if outcome == "success"
                            else (
                            "external_unavailable"
                                if external_manifest is not None
                                and external_manifest["verdict"]
                                in {"failed", "not_evaluable"}
                                else "local_failure"
                            )
                        ),
                        fingerprint=external_binding["dependency_id"],
                        payload={
                            "completion_record_id": record_id,
                            "external": external_manifest,
                            **external_binding,
                        },
                        event_stream=f"external-dependency:{external_binding['dependency_id']}",
                        event_sequence=attempt_sequence,
                    )
                )
            return body, records, {
                "job_id": job_id,
                "outcome": outcome,
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

    def open_repair(
        self,
        *,
        permit: Permit,
        failure: Mapping[str, Any],
        operation_id: str,
    ) -> TransitionResult:
        failure_manifest = _require_manifest(
            "repair failure",
            failure,
            required={
                "minimum_reproduction_evidence",
                "root_cause",
                "interrupted_action",
            },
        )
        for name in ("root_cause", "interrupted_action"):
            _require_ascii(name, failure_manifest[name])
        references = failure_manifest["minimum_reproduction_evidence"]
        if not isinstance(references, list) or not references:
            raise TransitionError("Repair requires minimum reproduction evidence")
        for reference in references:
            self.evidence.verify(reference)
        cause_hash = _digest(failure_manifest, domain="repair-cause")

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
            repair_id = f"repair:{canonical_digest(domain='repair', payload={'job_id': job['id'], 'cause_hash': cause_hash})}"
            job["status"] = "interrupted_repair"
            science["active_repair"] = {
                "id": repair_id,
                "job_id": job["id"],
                "cause_hash": cause_hash,
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

    def close_repair(
        self,
        *,
        changed_cause_proof_hash: str,
        operation_id: str,
    ) -> TransitionResult:
        _require_digest("changed_cause_proof_hash", changed_cause_proof_hash)
        self.evidence.verify(changed_cause_proof_hash)

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
            opened = _index.get("repair-open", repair["id"])
            if opened is None:
                raise TransitionError("Repair cause record is absent")
            if changed_cause_proof_hash in opened.payload["minimum_reproduction_evidence"]:
                raise TransitionError("changed-cause proof reuses the failure reproduction")
            science["active_repair"] = None
            job["status"] = "running"
            body["next_action"] = {"kind": "resume_job", "job_id": job["id"]}
            record = _record(
                kind="repair-close",
                record_id=canonical_digest(
                    domain="repair-close",
                    payload={"repair_id": repair["id"], "proof": changed_cause_proof_hash},
                ),
                subject=f"Repair:{repair['id']}",
                status="repaired",
                fingerprint=changed_cause_proof_hash,
                payload={
                    "resume_action": repair["resume_action"],
                    "changed_cause_proof_hash": changed_cause_proof_hash,
                    "scientific_trial_delta": 0,
                    "scientific_failure_delta": 0,
                },
            )
            return body, [record], {"job_id": job["id"], "resume_action": repair["resume_action"]}

        return self._commit(
            event_kind="repair_closed",
            operation_id=operation_id,
            subject="Repair:active",
            payload={"changed_cause_proof_hash": changed_cause_proof_hash},
            prepare=prepare,
        )

    def record_work_result(
        self,
        *,
        work: Mapping[str, Any],
        outcome: str,
        details: Mapping[str, Any],
        operation_id: str,
    ) -> TransitionResult:
        work_manifest = _require_manifest(
            "work",
            work,
            required={"callable_identity", "input_identity"},
        )
        work_fingerprint = _digest(work_manifest, domain="work-fingerprint")
        if outcome not in {"success", "failed"}:
            raise TransitionError("work outcome must be success or failed")
        if outcome == "failed" and (
            not isinstance(details, Mapping) or not isinstance(details.get("cause"), str)
        ):
            raise TransitionError("failed work requires a cause")

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            if current["scientific"]["active_mission"] is None:
                raise TransitionError("work result requires an active Mission")
            existing = index.get("work-result", work_fingerprint)
            if existing is not None:
                if existing.status == "success":
                    return self._body(current), [], {"disposition": "reuse_success"}
                raise IdenticalFailedRetryError("identical failed work requires changed cause or input")
            record = _record(
                kind="work-result",
                record_id=work_fingerprint,
                subject="Work:fingerprint",
                status=outcome,
                fingerprint=work_fingerprint,
                payload=dict(details),
            )
            return self._body(current), [record], {"disposition": outcome}

        return self._commit(
            event_kind="work_result_recorded",
            operation_id=operation_id,
            subject="Work:fingerprint",
            payload={
                "work": work_manifest,
                "work_fingerprint": work_fingerprint,
                "outcome": outcome,
                "details": dict(details),
            },
            prepare=prepare,
        )

    def record_holdout_seal(
        self,
        *,
        manifest: Any,
        operation_id: str,
    ) -> TransitionResult:
        """Register sealed future data by semantic row/split identity without reading it."""

        from axiom_rift.runtime.guards import SealedHoldoutManifest

        if not isinstance(manifest, SealedHoldoutManifest):
            raise TransitionError("holdout seal requires SealedHoldoutManifest")
        artifact = self.evidence.verify(manifest.artifact_sha256)
        if artifact.size_bytes != manifest.size_bytes:
            raise TransitionError("holdout seal size differs from its artifact")
        starts_at = _parse_utc("holdout starts_at_utc", manifest.starts_at_utc)
        ends_at = _parse_utc("holdout ends_at_utc", manifest.ends_at_utc)
        if starts_at > ends_at:
            raise TransitionError("holdout time boundary is reversed")
        holdout_hash = manifest.identity.removeprefix("holdout:")
        _require_digest("holdout identity", holdout_hash)
        row_binding_id = canonical_digest(
            domain="holdout-row-binding", payload={"row_identity": manifest.row_identity}
        )

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("Foundation is not initialized")
            if index.get("holdout-row-binding", row_binding_id) is not None:
                raise TransitionError(
                    "semantic holdout rows are already sealed under another operation"
                )
            chain_head = index.event_head("holdout-chain")
            chain_latest = (
                None
                if chain_head is None
                else index.get(chain_head.record_kind, chain_head.record_id)
            )
            if chain_head is None:
                if manifest.predecessor_holdout_id is not None:
                    raise TransitionError(
                        "first holdout cannot name a predecessor"
                    )
                try:
                    exposure = yaml.safe_load(
                        (self.foundation_root / "foundation" / "data_exposure.yaml").read_text(
                            encoding="ascii"
                        )
                    )
                    boundary_text = exposure["forward_holdout"]["starts_after"]
                    boundary = datetime.fromisoformat(boundary_text).replace(
                        tzinfo=timezone.utc
                    )
                except (OSError, UnicodeError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
                    raise TransitionError(
                        "Foundation forward-holdout boundary is unavailable"
                    ) from exc
                if starts_at <= boundary:
                    raise TransitionError(
                        "first holdout is not strictly after the Foundation boundary"
                    )
            else:
                if (
                    chain_latest is None
                    or manifest.predecessor_holdout_id != chain_latest.record_id
                ):
                    raise TransitionError(
                        "new holdout must extend the single latest global chain"
                    )
                predecessor = index.get(
                    "holdout-seal", manifest.predecessor_holdout_id
                )
                if predecessor is None:
                    raise TransitionError("holdout predecessor seal is absent")
                reveal_head = index.event_head(
                    f"holdout-reveal:{manifest.predecessor_holdout_id}"
                )
                reveal_latest = (
                    None
                    if reveal_head is None
                    else index.get(reveal_head.record_kind, reveal_head.record_id)
                )
                if (
                    reveal_head is None
                    or reveal_head.sequence != 2
                    or reveal_latest is None
                    or reveal_latest.kind != "holdout-disposition"
                ):
                    raise TransitionError(
                        "new future holdout requires a disposed predecessor"
                    )
                predecessor_end = _parse_utc(
                    "predecessor ends_at_utc", predecessor.payload["ends_at_utc"]
                )
                if starts_at <= predecessor_end:
                    raise TransitionError(
                        "replacement holdout is not genuinely later future data"
                    )
            payload = {
                "artifact_sha256": manifest.artifact_sha256,
                "data_receipt_id": manifest.data_receipt_id,
                "ends_at_utc": manifest.ends_at_utc,
                "predecessor_holdout_id": manifest.predecessor_holdout_id,
                "row_identity": manifest.row_identity,
                "size_bytes": manifest.size_bytes,
                "split_identity": manifest.split_identity,
                "starts_at_utc": manifest.starts_at_utc,
                "value_exposed": False,
            }
            seal = _record(
                kind="holdout-seal",
                record_id=manifest.identity,
                subject=f"Data:{manifest.data_receipt_id}",
                status="sealed_unrevealed",
                fingerprint=holdout_hash,
                payload=payload,
                event_stream="holdout-chain",
                event_sequence=1 if chain_head is None else chain_head.sequence + 1,
            )
            row_binding = _record(
                kind="holdout-row-binding",
                record_id=row_binding_id,
                subject=f"Holdout:{manifest.identity}",
                status="sealed",
                fingerprint=holdout_hash,
                payload={"holdout_id": manifest.identity},
            )
            body = self._body(current)
            if body["next_action"].get("kind") == "await_new_future_holdout_data":
                if (
                    manifest.predecessor_holdout_id
                    != body["next_action"].get("predecessor_holdout_id")
                ):
                    raise TransitionError(
                        "replacement holdout differs from the required predecessor"
                    )
                body["scientific"]["required_future_holdout_id"] = manifest.identity
                body["next_action"] = {
                    "kind": "register_future_development_material",
                    "holdout_id": manifest.identity,
                    "mission_id": body["scientific"]["active_mission"],
                    "predecessor_holdout_id": manifest.predecessor_holdout_id,
                }
            return body, [seal, row_binding], {"holdout_id": manifest.identity}

        return self._commit(
            event_kind="holdout_sealed",
            operation_id=operation_id,
            subject=f"Holdout:{manifest.identity}",
            payload={"holdout_id": manifest.identity},
            prepare=prepare,
        )

    def register_future_development_material(
        self,
        *,
        material_receipt_hash: str,
        operation_id: str,
    ) -> TransitionResult:
        """Admit new post-reveal development without reading successor values."""

        if self.engineering_fixture:
            raise TransitionError(
                "engineering fixtures cannot register scientific development material"
            )
        _require_digest("material_receipt_hash", material_receipt_hash)
        receipt_artifact = self.evidence.verify(material_receipt_hash)
        try:
            receipt = parse_canonical(
                (self.evidence._root / receipt_artifact.relative_path).read_bytes()
            )
        except ValueError as exc:
            raise TransitionError(
                "future development material receipt is not canonical"
            ) from exc
        required_receipt_fields = {
            "development_ends_at_utc",
            "development_starts_at_utc",
            "material_content_sha256",
            "material_identity",
            "mission_id",
            "predecessor_holdout_id",
            "schema",
            "split_identity",
            "successor_holdout_id",
            "successor_values_exposed",
        }
        if (
            not isinstance(receipt, dict)
            or set(receipt) != required_receipt_fields
            or receipt.get("schema") != "post_holdout_development_material.v1"
            or receipt.get("successor_values_exposed") is not False
        ):
            raise TransitionError(
                "future development material receipt schema is invalid"
            )
        for name in (
            "mission_id",
            "predecessor_holdout_id",
            "successor_holdout_id",
        ):
            _require_ascii(name, receipt[name])
        material_content_sha256 = _require_digest(
            "material_content_sha256", receipt["material_content_sha256"]
        )
        self.evidence.verify(material_content_sha256)
        material_identity = _require_digest(
            "material_identity", receipt["material_identity"]
        )
        split_identity = _require_digest("split_identity", receipt["split_identity"])
        development_start = _parse_utc(
            "development_starts_at_utc", receipt["development_starts_at_utc"]
        )
        development_end = _parse_utc(
            "development_ends_at_utc", receipt["development_ends_at_utc"]
        )
        if development_start > development_end:
            raise TransitionError("future development time boundary is reversed")
        expected_material_identity = canonical_digest(
            domain="post-holdout-development-material",
            payload={
                "development_ends_at_utc": receipt["development_ends_at_utc"],
                "development_starts_at_utc": receipt[
                    "development_starts_at_utc"
                ],
                "material_content_sha256": material_content_sha256,
                "predecessor_holdout_id": receipt["predecessor_holdout_id"],
                "successor_holdout_id": receipt["successor_holdout_id"],
            },
        )
        expected_split_identity = canonical_digest(
            domain="post-holdout-development-split",
            payload={
                "development_ends_at_utc": receipt["development_ends_at_utc"],
                "development_starts_at_utc": receipt[
                    "development_starts_at_utc"
                ],
                "material_identity": expected_material_identity,
                "predecessor_holdout_id": receipt["predecessor_holdout_id"],
                "successor_holdout_id": receipt["successor_holdout_id"],
            },
        )
        if (
            material_identity != expected_material_identity
            or split_identity != expected_split_identity
        ):
            raise TransitionError(
                "future development receipt material identity is invalid"
            )

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            mission_id = science["active_mission"]
            next_action = current["next_action"]
            successor_holdout_id = next_action.get("holdout_id")
            predecessor_holdout_id = next_action.get("predecessor_holdout_id")
            if (
                mission_id is None
                or next_action.get("kind")
                != "register_future_development_material"
                or next_action.get("mission_id") != mission_id
                or not isinstance(successor_holdout_id, str)
                or not isinstance(predecessor_holdout_id, str)
                or science.get("required_future_holdout_id")
                != successor_holdout_id
            ):
                raise TransitionError(
                    "future development registration is not the exact successor action"
                )
            if any(
                science[name] is not None
                for name in (
                    "active_study",
                    "active_batch",
                    "active_job",
                    "active_repair",
                    "active_executable",
                    "active_release",
                    "active_holdout_evaluation",
                )
            ):
                raise TransitionError(
                    "future development registration requires disposed active work"
                )
            if (
                receipt["mission_id"] != mission_id
                or receipt["successor_holdout_id"] != successor_holdout_id
                or receipt["predecessor_holdout_id"] != predecessor_holdout_id
            ):
                raise TransitionError(
                    "future development receipt belongs to another successor boundary"
                )
            successor = index.get("holdout-seal", successor_holdout_id)
            predecessor = index.get("holdout-seal", predecessor_holdout_id)
            predecessor_reveal = index.event_record(
                f"holdout-reveal:{predecessor_holdout_id}", 1
            )
            predecessor_disposition = index.event_record(
                f"holdout-reveal:{predecessor_holdout_id}", 2
            )
            if (
                successor is None
                or successor.status != "sealed_unrevealed"
                or successor.payload.get("predecessor_holdout_id")
                != predecessor_holdout_id
                or index.event_head(f"holdout-reveal:{successor_holdout_id}")
                is not None
                or predecessor is None
                or predecessor_reveal is None
                or predecessor_reveal.kind != "holdout-reveal"
                or predecessor_disposition is None
                or predecessor_disposition.kind != "holdout-disposition"
            ):
                raise TransitionError(
                    "future development registration lacks an untouched successor chain"
                )
            if not predecessor_reveal.subject.startswith("Executable:executable:"):
                raise TransitionError(
                    "predecessor holdout lacks its Executable binding"
                )
            predecessor_executable_id = predecessor_reveal.subject.removeprefix(
                "Executable:"
            )
            predecessor_end = _parse_utc(
                "predecessor ends_at_utc", predecessor.payload["ends_at_utc"]
            )
            successor_start = _parse_utc(
                "successor starts_at_utc", successor.payload["starts_at_utc"]
            )
            if (
                development_start <= predecessor_end
                or development_end >= successor_start
                or material_content_sha256
                in {
                    predecessor.payload["artifact_sha256"],
                    successor.payload["artifact_sha256"],
                }
            ):
                raise TransitionError(
                    "development material is not a distinct post-reveal pre-successor surface"
                )
            receipt_id = canonical_digest(
                domain="post-holdout-development",
                payload={
                    "holdout_id": successor_holdout_id,
                    "material_identity": material_identity,
                    "mission_id": mission_id,
                },
            )
            authority_payload = {
                "holdout_id": successor_holdout_id,
                "material_identity": material_identity,
                "material_content_sha256": material_content_sha256,
                "material_receipt_hash": material_receipt_hash,
                "mission_id": mission_id,
                "predecessor_executable_id": predecessor_executable_id,
                "predecessor_holdout_id": predecessor_holdout_id,
                "split_identity": split_identity,
            }
            authority = _record(
                kind="post-holdout-development",
                record_id=receipt_id,
                subject=f"Material:{material_identity}",
                status="accepted",
                fingerprint=material_receipt_hash,
                payload=authority_payload,
            )
            material = _record(
                kind="development-material",
                record_id=material_identity,
                subject=f"Mission:{mission_id}",
                status="accepted",
                fingerprint=material_receipt_hash,
                payload={
                    **authority_payload,
                    "development_ends_at_utc": receipt[
                        "development_ends_at_utc"
                    ],
                    "development_starts_at_utc": receipt[
                        "development_starts_at_utc"
                    ],
                    "post_holdout_development_id": receipt_id,
                },
            )
            if science["active_initiative"] is None:
                body["next_action"] = {
                    "kind": "open_initiative",
                    "mission_id": mission_id,
                }
            else:
                portfolio_head = index.event_head(f"portfolio:{mission_id}")
                snapshot = (
                    None
                    if portfolio_head is None
                    else index.get(
                        portfolio_head.record_kind, portfolio_head.record_id
                    )
                )
                if snapshot is None or snapshot.kind != "portfolio-snapshot":
                    raise TransitionError(
                        "active Initiative lacks its Portfolio reentry boundary"
                    )
                body["next_action"] = {
                    "kind": "portfolio_decision",
                    "portfolio_snapshot_id": snapshot.record_id,
                }
            return body, [authority, material], {
                "material_identity": material_identity,
                "post_holdout_development_id": receipt_id,
            }

        return self._commit(
            event_kind="future_development_registered",
            operation_id=operation_id,
            subject=f"Material:{material_identity}",
            payload={
                "material_receipt_hash": material_receipt_hash,
            },
            prepare=prepare,
        )

    def consume_holdout_permit(
        self,
        *,
        permit: Permit,
        executable_id: str,
        operation_id: str,
    ) -> TransitionResult:
        _require_ascii("executable_id", executable_id)

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            if science["active_executable"] != executable_id:
                raise TransitionError("holdout permit is not candidate-executable bound")
            job = science.get("active_job")
            if not isinstance(job, dict) or job.get("status") != "running":
                raise TransitionError(
                    "holdout reveal requires its preregistered running evaluation Job"
                )
            declaration = index.get("job-declared", job["id"])
            holdout_id = f"holdout:{permit.input_hash}"
            if (
                declaration is None
                or declaration.payload["spec"].get("holdout_binding")
                != {"holdout_id": holdout_id}
                or declaration.payload["spec"].get("evidence_subject")
                != {"kind": "Executable", "id": executable_id}
            ):
                raise TransitionError("running Job is not bound to this holdout")
            self._validate_permit_locked(
                control=current,
                index=index,
                permit=permit,
                expected_kind=PermitKind.HOLDOUT,
                action="reveal_holdout",
                subject_kind=SubjectKind.EXECUTABLE,
                subject_id=executable_id,
                required_scope=(
                    holdout_id,
                    f"executable:{executable_id}",
                ),
            )
            seal = index.get("holdout-seal", holdout_id)
            if seal is None or seal.status != "sealed_unrevealed":
                raise TransitionError("holdout semantic seal is unavailable")
            self.evidence.verify(seal.payload["artifact_sha256"])
            if index.event_head(f"holdout-reveal:{holdout_id}") is not None:
                raise TransitionError("holdout semantic identity was already revealed")
            candidate_head = index.event_head(f"candidate:{executable_id}")
            candidate = (
                None
                if candidate_head is None
                else index.get(candidate_head.record_kind, candidate_head.record_id)
            )
            if candidate is None:
                raise TransitionError("holdout candidate activation is unavailable")
            science["holdout_reveals"] += 1
            science["active_holdout_evaluation"] = {
                "holdout_id": holdout_id,
                "candidate_id": candidate.record_id,
                "executable_id": executable_id,
                "job_id": job["id"],
                "status": "revealed_pending_evaluation",
            }
            body["next_action"] = {"kind": "evaluate_frozen_holdout", "executable_id": executable_id}
            consumption = self._permit_consumption_record(permit, operation_id)
            reveal_id = canonical_digest(
                domain="holdout-reveal",
                payload={
                    "candidate_id": candidate.record_id,
                    "holdout_id": holdout_id,
                    "job_id": job["id"],
                    "permit_id": permit.permit_id,
                },
            )
            reveal = _record(
                kind="holdout-reveal",
                record_id=reveal_id,
                subject=f"Executable:{executable_id}",
                status="revealed_once",
                fingerprint=seal.fingerprint,
                payload={
                    "artifact_sha256": seal.payload["artifact_sha256"],
                    "candidate_id": candidate.record_id,
                    "holdout_id": holdout_id,
                    "job_id": job["id"],
                    "reveal_delta": 1,
                    "retuning_allowed": False,
                },
                event_stream=f"holdout-reveal:{holdout_id}",
                event_sequence=1,
            )
            return body, [consumption, reveal], {
                "artifact_sha256": seal.payload["artifact_sha256"],
                "holdout_id": holdout_id,
                "reveal_count": science["holdout_reveals"],
                "reveal_record_id": reveal_id,
            }

        return self._commit(
            event_kind="holdout_revealed",
            operation_id=operation_id,
            subject=f"Executable:{executable_id}",
            payload={"permit_id": permit.permit_id, "executable_id": executable_id},
            prepare=prepare,
        )

    def reveal_holdout_values(
        self,
        *,
        permit: Permit,
        executable_id: str,
        operation_id: str,
    ) -> bytes:
        """Commit the one-time reveal before returning verified sealed values."""

        consumed = self.consume_holdout_permit(
            permit=permit,
            executable_id=executable_id,
            operation_id=operation_id,
        )
        if consumed.reused:
            raise PermitError("holdout reveal operation cannot return values twice")
        artifact = self.evidence.verify(consumed.result["artifact_sha256"])
        return (self.evidence._root / artifact.relative_path).read_bytes()

    def record_holdout_evaluation(
        self,
        *,
        completion_record_id: str,
        negative_memory_id: str | None,
        operation_id: str,
    ) -> TransitionResult:
        """Dispose the revealed final surface from validator-derived Job evidence."""

        _require_ascii("completion_record_id", completion_record_id)
        if negative_memory_id is not None:
            _require_ascii("negative_memory_id", negative_memory_id)

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            active = science.get("active_holdout_evaluation")
            if not isinstance(active, dict):
                raise TransitionError("no revealed holdout awaits evaluation")
            completion = index.get("job-completed", completion_record_id)
            scientific = None if completion is None else completion.payload.get("scientific")
            if (
                completion is None
                or completion.payload.get("job_id") != active["job_id"]
                or not isinstance(scientific, dict)
                or scientific.get("executable_id") != active["executable_id"]
                or scientific.get("evidence_depth") != "confirmation"
                or scientific.get("scientific_eligible") is not True
            ):
                raise TransitionError(
                    "holdout disposition lacks its validator-derived evaluation"
                )
            declaration = index.get("job-declared", active["job_id"])
            if (
                declaration is None
                or declaration.payload["spec"].get("holdout_binding")
                != {"holdout_id": active["holdout_id"]}
            ):
                raise TransitionError("holdout evaluation Job binding is unavailable")
            verdict = scientific.get("verdict")
            if verdict not in {"passed", "failed", "not_evaluable"}:
                raise TransitionError("holdout validator verdict is invalid")
            candidate_head = index.event_head(
                f"candidate:{active['executable_id']}"
            )
            candidate = (
                None
                if candidate_head is None
                else index.get(candidate_head.record_kind, candidate_head.record_id)
            )
            if candidate is None or candidate.record_id != active["candidate_id"]:
                raise TransitionError("holdout candidate activation changed")
            if verdict == "passed":
                if scientific.get("candidate_eligible") is not True:
                    raise TransitionError(
                        "passed holdout did not authorize the frozen candidate"
                    )
                if negative_memory_id is not None:
                    raise TransitionError("passed holdout cannot carry negative memory")
                next_action = {
                    "kind": "plan_candidate_bound_evidence",
                    "executable_id": active["executable_id"],
                }
                science["required_future_holdout_id"] = None
            else:
                if verdict == "failed":
                    memory = (
                        None
                        if negative_memory_id is None
                        else index.get("negative-memory", negative_memory_id)
                    )
                    if (
                        memory is None
                        or memory.subject != f"Executable:{active['executable_id']}"
                        or completion_record_id
                        not in memory.payload.get("evidence_references", [])
                    ):
                        raise TransitionError(
                            "failed holdout requires its durable negative memory"
                        )
                elif negative_memory_id is not None:
                    raise TransitionError(
                        "not-evaluable holdout is not scientific negative memory"
                    )
                candidate_disposition_id = canonical_digest(
                    domain="candidate-disposition",
                    payload={
                        "candidate_id": active["candidate_id"],
                        "disposition": "invalidated",
                        "reason": "final_holdout_" + verdict,
                    },
                )
                candidate_disposition = _record(
                    kind="candidate-disposition",
                    record_id=candidate_disposition_id,
                    subject=f"Executable:{active['executable_id']}",
                    status="invalidated",
                    fingerprint=candidate.fingerprint,
                    payload={
                        "candidate_id": active["candidate_id"],
                        "executable_id": active["executable_id"],
                        "mission_id": science["active_mission"],
                        "reason": "final_holdout_" + verdict,
                    },
                    event_stream=f"candidate:{active['executable_id']}",
                    event_sequence=candidate_head.sequence + 1,
                )
                science["active_executable"] = None
                self._drop_authorization(
                    body, SubjectKind.EXECUTABLE, active["executable_id"]
                )
                next_action = {
                    "kind": "await_new_future_holdout_data",
                    "predecessor_holdout_id": active["holdout_id"],
                }
            disposition_id = canonical_digest(
                domain="holdout-disposition",
                payload={
                    "completion_record_id": completion_record_id,
                    "holdout_id": active["holdout_id"],
                    "verdict": verdict,
                },
            )
            disposition = _record(
                kind="holdout-disposition",
                record_id=disposition_id,
                subject=f"Holdout:{active['holdout_id']}",
                status=verdict,
                fingerprint=active["holdout_id"].removeprefix("holdout:"),
                payload={
                    "completion_record_id": completion_record_id,
                    "negative_memory_id": negative_memory_id,
                    "retuning_allowed": False,
                },
                event_stream=f"holdout-reveal:{active['holdout_id']}",
                event_sequence=2,
            )
            candidate_holdout = _record(
                kind="candidate-holdout",
                record_id=active["candidate_id"],
                subject=f"Candidate:{active['candidate_id']}",
                status=verdict,
                fingerprint=active["holdout_id"].removeprefix("holdout:"),
                payload={
                    "completion_record_id": completion_record_id,
                    "executable_id": active["executable_id"],
                    "holdout_id": active["holdout_id"],
                    "mission_id": science["active_mission"],
                },
            )
            records = [disposition, candidate_holdout]
            if verdict != "passed":
                records.append(candidate_disposition)
            science["active_holdout_evaluation"] = None
            body["next_action"] = next_action
            return body, records, {
                "holdout_id": active["holdout_id"],
                "verdict": verdict,
            }

        return self._commit(
            event_kind="holdout_evaluated",
            operation_id=operation_id,
            subject="Holdout:active",
            payload={
                "completion_record_id": completion_record_id,
                "negative_memory_id": negative_memory_id,
            },
            prepare=prepare,
        )

    def accept_exhaustion_audit(
        self,
        *,
        frontiers: Mapping[str, Sequence[Mapping[str, str]]],
        diversity_basis: str,
        opportunity_cost_audit: str,
        operation_id: str,
    ) -> TransitionResult:
        if self.engineering_fixture:
            raise TransitionError("engineering fixtures cannot accept frontier exhaustion")
        _require_ascii("diversity_basis", diversity_basis)
        _require_ascii("opportunity_cost_audit", opportunity_cost_audit)
        if not frontiers:
            raise TransitionError("exhaustion audit requires a non-empty diverse frontier")
        normalized: dict[str, list[dict[str, str]]] = {}
        for frontier, references in frontiers.items():
            _require_ascii("frontier", frontier)
            if not references:
                raise TransitionError("every frontier requires bound evidence")
            normalized[frontier] = []
            for reference in references:
                if set(reference) != {"kind", "record_id"}:
                    raise TransitionError("exhaustion evidence reference is malformed")
                normalized[frontier].append(
                    {
                        "kind": _require_ascii("evidence kind", reference["kind"]),
                        "record_id": _require_ascii(
                            "evidence record id", reference["record_id"]
                        ),
                    }
                )
            normalized[frontier].sort(
                key=lambda value: (value["kind"], value["record_id"])
            )
        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None or current["scientific"]["active_mission"] is None:
                raise TransitionError("exhaustion audit requires an active Mission")
            science = current["scientific"]
            if any(
                science[key] is not None
                for key in (
                    "active_initiative",
                    "active_study",
                    "active_batch",
                    "active_job",
                    "active_repair",
                    "active_executable",
                )
            ):
                raise TransitionError("exhaustion audit requires disposed active work")
            portfolio_head = index.event_head(
                f"portfolio:{science['active_mission']}"
            )
            latest = (
                None
                if portfolio_head is None
                else index.get(portfolio_head.record_kind, portfolio_head.record_id)
            )
            if latest is None:
                raise TransitionError("exhaustion requires a durable Portfolio")
            if latest.kind != "portfolio-snapshot":
                raise TransitionError("exhaustion requires a final Portfolio snapshot")
            snapshot_id = latest.record_id
            snapshot = (
                None
                if not isinstance(snapshot_id, str)
                else index.get("portfolio-snapshot", snapshot_id)
            )
            if snapshot is None or snapshot.subject != f"Mission:{science['active_mission']}":
                raise TransitionError("exhaustion Portfolio snapshot is unavailable")
            axes = {axis["axis_id"]: axis for axis in snapshot.payload["axes"]}
            families = {axis["mechanism_family"] for axis in axes.values()}
            standard = snapshot.payload.get("exhaustion_standard")
            if not isinstance(standard, dict):
                raise TransitionError(
                    "exhaustion Portfolio lacks its preregistered standard"
                )
            if (
                set(normalized) != set(axes)
                or len(axes) < standard["minimum_axes"]
                or len(families) < standard["minimum_mechanism_families"]
            ):
                raise TransitionError(
                    "exhaustion does not cover its preregistered axes and families"
                )
            if snapshot.status != "closed" or any(
                axis["status"] != "pruned" for axis in axes.values()
            ):
                raise TransitionError(
                    "exhaustion requires every current Portfolio axis to be durably pruned"
                )
            family_executables: dict[str, set[str]] = {
                family: set() for family in families
            }
            axis_studies: dict[str, set[str]] = {axis_id: set() for axis_id in axes}
            axis_modes: dict[str, set[str]] = {axis_id: set() for axis_id in axes}
            global_executables: set[str] = set()
            for axis_id, references in normalized.items():
                prune_found = False
                negative_found = False
                for reference in references:
                    if reference["kind"] not in {
                        "portfolio-decision",
                        "negative-memory",
                    }:
                        raise TransitionError(
                            "exhaustion evidence kind is not scientifically admissible"
                        )
                    record = index.get(reference["kind"], reference["record_id"])
                    if record is None:
                        raise TransitionError("exhaustion evidence record is absent")
                    if record.kind == "portfolio-decision":
                        options = {
                            option["option_id"]: option
                            for option in record.payload.get("options", [])
                        }
                        chosen = options.get(record.payload.get("chosen_option_id"))
                        if (
                            record.subject != f"Mission:{science['active_mission']}"
                            or not isinstance(chosen, dict)
                            or chosen.get("action") != "prune"
                            or chosen.get("target_id") != axis_id
                            or record.payload.get("target_axis_identity")
                            != axes[axis_id]["axis_identity"]
                        ):
                            raise TransitionError(
                                "frontier prune Decision is not Mission/axis bound"
                            )
                        prune_found = True
                    else:
                        executable_id = record.subject.removeprefix("Executable:")
                        study_id = record.payload.get("study_id")
                        study = (
                            None
                            if not isinstance(study_id, str)
                            else index.get("study-open", study_id)
                        )
                        if (
                            record.payload.get("mission_id")
                            != science["active_mission"]
                            or record.payload.get("portfolio_axis_id") != axis_id
                            or record.payload.get("portfolio_axis_identity")
                            != axes[axis_id]["axis_identity"]
                            or study is None
                            or study.payload.get("portfolio_axis_identity")
                            != axes[axis_id]["axis_identity"]
                            or executable_id in global_executables
                        ):
                            raise TransitionError(
                                "frontier negative memory is stale, reused, or unbound"
                            )
                        global_executables.add(executable_id)
                        family_executables[axes[axis_id]["mechanism_family"]].add(
                            executable_id
                        )
                        axis_studies[axis_id].add(study_id)
                        axis_modes[axis_id].update(
                            record.payload.get("executed_evidence_modes", [])
                        )
                        negative_found = True
                if not prune_found or not negative_found:
                    raise TransitionError(
                        "every frontier requires a prune Decision and negative memory"
                    )
            if any(
                len(executables)
                < standard["minimum_negative_executables_per_family"]
                for executables in family_executables.values()
            ):
                raise TransitionError(
                    "negative evidence is below the preregistered family bound"
                )
            required_modes = set(standard["required_evidence_modes"])
            for axis_id in axes:
                if (
                    len(axis_studies[axis_id])
                    < standard["minimum_distinct_studies_per_axis"]
                    or not required_modes.issubset(axis_modes[axis_id])
                ):
                    raise TransitionError(
                        "frontier lacks preregistered Study or evidence-mode depth"
                    )
            unresolved_positive_axes: set[str] = set()
            for completion in index.records_by_kind("job-completed"):
                scientific = completion.payload.get("scientific")
                if (
                    completion.status != "success"
                    or not isinstance(scientific, dict)
                    or scientific.get("candidate_eligible") is not True
                ):
                    continue
                declaration = index.get(
                    "job-declared", completion.payload.get("job_id", "")
                )
                executable_id = scientific.get("executable_id")
                trial = (
                    None
                    if not isinstance(executable_id, str)
                    else index.get("trial", executable_id)
                )
                if (
                    declaration is None
                    or declaration.payload.get("mission_id")
                    != science["active_mission"]
                    or trial is None
                ):
                    continue
                axis_id = trial.payload.get("portfolio_axis_id")
                if (
                    axis_id not in axes
                    or trial.payload.get("portfolio_axis_identity")
                    != axes[axis_id]["axis_identity"]
                ):
                    raise TransitionError(
                        "positive scientific evidence has stale Portfolio lineage"
                    )
                candidate_head = index.event_head(f"candidate:{executable_id}")
                candidate_state = (
                    None
                    if candidate_head is None
                    else index.get(
                        candidate_head.record_kind, candidate_head.record_id
                    )
                )
                candidate = (
                    None
                    if candidate_state is None
                    or candidate_state.kind != "candidate-disposition"
                    else index.get(
                        "candidate", candidate_state.payload.get("candidate_id", "")
                    )
                )
                if (
                    candidate_state is None
                    or candidate_state.kind != "candidate-disposition"
                    or candidate is None
                    or candidate.payload.get("mission_id")
                    != science["active_mission"]
                    or candidate_state.payload.get("mission_id")
                    != science["active_mission"]
                    or completion.record_id
                    not in candidate.payload.get("evidence_refs", [])
                    or candidate.authority_sequence is None
                    or completion.authority_sequence is None
                    or candidate_state.authority_sequence is None
                    or candidate.authority_sequence <= completion.authority_sequence
                    or candidate_state.authority_sequence <= candidate.authority_sequence
                ):
                    unresolved_positive_axes.add(axis_id)
            if unresolved_positive_axes:
                raise TransitionError(
                    "candidate-eligible positive evidence remains unresolved on: "
                    + ", ".join(sorted(unresolved_positive_axes))
                )
            audit_payload = {
                "diversity_basis": diversity_basis,
                "frontiers": normalized,
                "mechanism_families": sorted(families),
                "opportunity_cost_audit": opportunity_cost_audit,
                "portfolio_snapshot_id": snapshot.record_id,
                "preregistered_exhaustion_standard": standard,
                "unique_negative_executable_count": len(global_executables),
                "unresolved_positive_iv_axes": sorted(unresolved_positive_axes),
            }
            audit_id = canonical_digest(
                domain="exhaustion-audit", payload=audit_payload
            )
            body = self._body(current)
            body["next_action"] = {
                "kind": "close_mission",
                "outcome": "closed_no_candidate",
                "basis_record_id": audit_id,
            }
            record = _record(
                kind="exhaustion-audit",
                record_id=audit_id,
                subject=f"Mission:{science['active_mission']}",
                status="accepted",
                fingerprint=audit_id,
                payload=audit_payload,
            )
            return body, [record], {"basis_record_id": audit_id}

        return self._commit(
            event_kind="exhaustion_audit_accepted",
            operation_id=operation_id,
            subject="Mission:active",
            payload={
                "diversity_basis": diversity_basis,
                "frontiers": normalized,
                "opportunity_cost_audit": opportunity_cost_audit,
            },
            prepare=prepare,
        )

    def record_external_blocker(
        self,
        *,
        dependency_id: str,
        completion_record_ids: tuple[str, ...],
        operation_id: str,
    ) -> TransitionResult:
        if self.engineering_fixture:
            raise TransitionError("engineering fixtures cannot create external blockers")
        _require_ascii("dependency_id", dependency_id)
        if (
            type(completion_record_ids) is not tuple
            or len(completion_record_ids) < 3
            or len(set(completion_record_ids)) != len(completion_record_ids)
        ):
            raise TransitionError(
                "external blocker requires at least three unique recovery completions"
            )
        for completion_id in completion_record_ids:
            _require_ascii("completion_record_id", completion_id)

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None or current["scientific"]["active_mission"] is None:
                raise TransitionError("external blocker requires an active Mission")
            science = current["scientific"]
            if any(
                science[key] is not None
                for key in (
                    "active_initiative",
                    "active_study",
                    "active_batch",
                    "active_job",
                    "active_repair",
                    "active_executable",
                )
            ):
                raise TransitionError("external blocker requires preserved, disposed work")
            mission_id = science["active_mission"]
            attempts: list[IndexRecord] = []
            recovery_kinds: set[str] = set()
            recovery_paths: set[str] = set()
            required_changes: set[str] = set()
            resume_actions: set[str] = set()
            dependency_kinds: set[str] = set()
            blocked_capabilities: set[str] = set()
            reproduction_evidence: set[str] = set()
            completed_jobs: list[str] = []
            for completion_id in completion_record_ids:
                completion = index.get("job-completed", completion_id)
                failure = None if completion is None else completion.payload.get("failure")
                external = None if completion is None else completion.payload.get("external")
                job_id = None if completion is None else completion.payload.get("job_id")
                declaration = (
                    None
                    if not isinstance(job_id, str)
                    else index.get("job-declared", job_id)
                )
                binding = (
                    None
                    if declaration is None
                    else declaration.payload["spec"].get(
                        "external_dependency_binding"
                    )
                )
                if (
                    completion is None
                    or completion.status not in {"failed", "not_evaluable"}
                    or not isinstance(failure, dict)
                    or failure.get("failure_kind") != "external_dependency"
                    or failure.get("external_dependency_id") != dependency_id
                    or not isinstance(external, dict)
                    or external.get("dependency_id") != dependency_id
                    or external.get("verdict") not in {"failed", "not_evaluable"}
                    or external.get("indispensable_to_mission_terminal") is not True
                    or external.get("contract_valid_next_action_found") is not False
                    or external.get("safe_substitute_found") is not False
                    or external.get("observed_external_state")
                    != failure.get("observed_external_state")
                    or declaration is None
                    or declaration.payload.get("mission_id") != mission_id
                    or not isinstance(binding, dict)
                    or binding.get("dependency_id") != dependency_id
                ):
                    raise TransitionError(
                        "blocker completion is not typed external dependency evidence"
                    )
                attempt_id = canonical_digest(
                    domain="external-dependency-attempt",
                    payload={
                        "completion_record_id": completion_id,
                        "dependency_id": dependency_id,
                        "recovery_path_id": binding["recovery_path_id"],
                    },
                )
                attempt = index.get("external-dependency-attempt", attempt_id)
                if (
                    attempt is None
                    or attempt.status != "external_unavailable"
                    or attempt.subject != f"Mission:{mission_id}"
                    or attempt.payload.get("external") != external
                ):
                    raise TransitionError(
                        "external dependency attempt projection is unavailable"
                    )
                attempts.append(attempt)
                recovery_kinds.add(binding["recovery_kind"])
                blocked_capabilities.add(binding["blocked_mission_capability"])
                if binding["recovery_path_id"] in recovery_paths:
                    raise TransitionError("external recovery path was repeated")
                recovery_paths.add(binding["recovery_path_id"])
                required_changes.add(binding["required_external_change"])
                resume_actions.add(binding["exact_resume_action"])
                dependency_kinds.add(binding["dependency_kind"])
                reproduction_evidence.update(
                    failure["minimum_reproduction_evidence"]
                )
                completed_jobs.append(job_id)
            required_recovery_kinds = {
                "external_probe",
                "local_recovery",
                "safe_substitute_search",
            }
            if not required_recovery_kinds.issubset(recovery_kinds):
                raise TransitionError(
                    "external blocker has not exhausted probe, local recovery, and substitute search"
                )
            if (
                len(required_changes) != 1
                or len(resume_actions) != 1
                or len(dependency_kinds) != 1
                or len(blocked_capabilities) != 1
            ):
                raise TransitionError("external recovery attempts disagree on the dependency")
            dependency_head = index.event_head(f"external-dependency:{dependency_id}")
            dependency_latest = (
                None
                if dependency_head is None
                else index.get(
                    dependency_head.record_kind, dependency_head.record_id
                )
            )
            sequences = sorted(attempt.event_sequence for attempt in attempts)
            if (
                dependency_head is None
                or dependency_latest is None
                or dependency_latest.status != "external_unavailable"
                or sequences
                != list(
                    range(
                        dependency_head.sequence - len(attempts) + 1,
                        dependency_head.sequence + 1,
                    )
                )
            ):
                raise TransitionError(
                    "external blocker evidence is stale or not the latest consecutive state"
                )
            blocker_payload = {
                "cause": {
                    "blocked_mission_capability": next(
                        iter(blocked_capabilities)
                    ),
                    "dependency_id": dependency_id,
                    "dependency_kind": next(iter(dependency_kinds)),
                },
                "completed_local_work": sorted(completed_jobs),
                "completion_record_ids": sorted(completion_record_ids),
                "exact_resume_action": next(iter(resume_actions)),
                "exhausted_recovery_kinds": sorted(recovery_kinds),
                "exhausted_recovery_paths": sorted(recovery_paths),
                "minimum_reproduction_evidence": sorted(reproduction_evidence),
                "preserved_state": {
                    "control_revision": current["revision"],
                    "journal_event_id": current["heads"]["journal"]["event_id"],
                    "mission_id": mission_id,
                },
                "required_external_change": next(iter(required_changes)),
                "safe_substitute_absent": True,
                "contract_valid_next_action_absent": True,
                "indispensable_to_mission_terminal": True,
            }
            blocker_id = canonical_digest(
                domain="external-blocker", payload=blocker_payload
            )
            body = self._body(current)
            body["next_action"] = {
                "kind": "close_mission",
                "outcome": "blocked_external",
                "basis_record_id": blocker_id,
            }
            record = _record(
                kind="external-blocker",
                record_id=blocker_id,
                subject=f"Mission:{science['active_mission']}",
                status="complete",
                fingerprint=blocker_id,
                payload=blocker_payload,
            )
            return body, [record], {"basis_record_id": blocker_id}

        return self._commit(
            event_kind="external_blocker_recorded",
            operation_id=operation_id,
            subject="Mission:active",
            payload={
                "completion_record_ids": list(completion_record_ids),
                "dependency_id": dependency_id,
            },
            prepare=prepare,
        )

    def close_mission(
        self,
        *,
        outcome: str,
        basis_record_id: str,
        operation_id: str,
    ) -> TransitionResult:
        if self.engineering_fixture:
            raise TransitionError("engineering fixtures cannot create a Mission terminal")
        allowed = {"completed_pre_live_handoff", "closed_no_candidate", "blocked_external"}
        if outcome not in allowed:
            raise TransitionError("invalid Mission terminal")

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            mission_id = science["active_mission"]
            if mission_id is None:
                raise TransitionError("no active Mission")
            if body["next_action"] != {
                "kind": "close_mission",
                "outcome": outcome,
                "basis_record_id": basis_record_id,
            }:
                raise TransitionError("Mission terminal differs from the pending exact basis")
            if any(
                science[key] is not None
                for key in (
                    "active_initiative",
                    "active_study",
                    "active_batch",
                    "active_job",
                    "active_repair",
                    "active_lineage",
                )
            ):
                raise TransitionError("Mission terminal has active subordinate work")
            if outcome == "completed_pre_live_handoff":
                basis = index.get("release", basis_record_id)
                active_release = science.get("active_release")
                if (
                    basis is None
                    or basis.status != "frozen"
                    or basis.payload.get("mission_id") != mission_id
                    or basis.payload.get("executable_id") != science["active_executable"]
                    or not isinstance(active_release, dict)
                    or active_release
                    != {
                        "id": basis_record_id,
                        "status": "frozen",
                        "candidate_id": basis.payload.get("candidate_id"),
                        "executable_id": basis.payload.get("executable_id"),
                    }
                ):
                    raise TransitionError("positive terminal requires a frozen Release")
                derived = self._derive_release_basis_locked(
                    index=index,
                    control=current,
                    executable_id=basis.payload["executable_id"],
                    candidate_id=basis.payload["candidate_id"],
                    completion_record_ids=tuple(basis.payload["completion_record_ids"]),
                )
                if any(basis.payload.get(name) != value for name, value in derived.items()):
                    raise TransitionError("frozen Release no longer matches current evidence")
                executable_id = science["active_executable"]
                science["active_executable"] = None
                science["active_release"] = None
                self._drop_authorization(body, SubjectKind.EXECUTABLE, executable_id)
            elif outcome == "closed_no_candidate":
                basis = index.get("exhaustion-audit", basis_record_id)
                if (
                    science["active_executable"] is not None
                    or science.get("active_release") is not None
                    or science.get("active_holdout_evaluation") is not None
                    or basis is None
                    or basis.status != "accepted"
                    or basis.subject != f"Mission:{mission_id}"
                ):
                    raise TransitionError("negative terminal requires an exhaustion audit")
            else:
                basis = index.get("external-blocker", basis_record_id)
                dependency_id = (
                    None
                    if basis is None
                    else basis.payload.get("cause", {}).get("dependency_id")
                )
                dependency_head = (
                    None
                    if not isinstance(dependency_id, str)
                    else index.event_head(f"external-dependency:{dependency_id}")
                )
                dependency_latest = (
                    None
                    if dependency_head is None
                    else index.get(
                        dependency_head.record_kind, dependency_head.record_id
                    )
                )
                if (
                    science["active_executable"] is not None
                    or science.get("active_release") is not None
                    or science.get("active_holdout_evaluation") is not None
                    or basis is None
                    or basis.status != "complete"
                    or basis.subject != f"Mission:{mission_id}"
                    or dependency_head is None
                    or dependency_latest is None
                    or dependency_latest.status != "external_unavailable"
                ):
                    raise TransitionError("blocked terminal requires a complete external blocker")
            expected_authorizations = {f"Mission:{mission_id}"}
            if set(body["authorizations"]) != expected_authorizations:
                raise TransitionError("Mission terminal has stale subject authorization")
            science["active_holdout_evaluation"] = None
            science["required_future_holdout_id"] = None
            science["active_mission"] = None
            self._drop_authorization(body, SubjectKind.MISSION, mission_id)
            body["next_action"] = {"kind": "await_root_goal"}
            record_id = canonical_digest(
                domain="mission-close",
                payload={"mission_id": mission_id, "outcome": outcome, "basis": basis_record_id},
            )
            record = _record(
                kind="mission-close",
                record_id=record_id,
                subject=f"Mission:{mission_id}",
                status=outcome,
                fingerprint=record_id,
                payload={"basis_record_id": basis_record_id},
            )
            return body, [record], {"mission_id": mission_id, "outcome": outcome}

        return self._commit(
            event_kind="mission_closed",
            operation_id=operation_id,
            subject="Mission:active",
            payload={"outcome": outcome, "basis_record_id": basis_record_id},
            prepare=prepare,
        )

    def withdraw_terminal_basis(
        self,
        *,
        reason: str,
        operation_id: str,
    ) -> TransitionResult:
        """Withdraw a pending negative or blocker terminal when new evidence exists."""

        _require_ascii("reason", reason)

        def prepare(current: dict[str, Any] | None, _index: LocalIndex):
            if current is None or current["scientific"]["active_mission"] is None:
                raise TransitionError("terminal withdrawal requires an active Mission")
            pending = current["next_action"]
            if pending.get("kind") != "close_mission" or pending.get("outcome") not in {
                "closed_no_candidate",
                "blocked_external",
            }:
                raise TransitionError("there is no withdrawable terminal basis")
            body = self._body(current)
            body["next_action"] = {
                "kind": "choose_next_initiative_or_terminal",
                "mission_id": body["scientific"]["active_mission"],
            }
            record_id = canonical_digest(
                domain="terminal-basis-withdrawal",
                payload={"pending": pending, "reason": reason},
            )
            record = _record(
                kind="terminal-basis-withdrawal",
                record_id=record_id,
                subject=f"Mission:{body['scientific']['active_mission']}",
                status="withdrawn",
                fingerprint=record_id,
                payload={"pending": pending, "reason": reason},
            )
            return body, [record], {"withdrawn_basis_record_id": pending["basis_record_id"]}

        return self._commit(
            event_kind="terminal_basis_withdrawn",
            operation_id=operation_id,
            subject="Mission:active",
            payload={"reason": reason},
            prepare=prepare,
        )
