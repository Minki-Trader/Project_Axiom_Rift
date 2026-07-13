"""The sole state writer for Axiom lifecycle and capability transitions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
import ast
import os
import re
import tempfile
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
    JOURNAL_MANIFEST_RELATIVE_PATH,
    JOURNAL_STORAGE_MIGRATION_SCHEMA,
    JournalHead,
    JournalIntegrityError,
    LEGACY_JOURNAL_RELATIVE_PATH,
    _issue_journal_write_capability,
)
from axiom_rift.storage.study_kpi import (
    LEDGER_RELATIVE_PATH,
    StudyKpiProjectionRow,
    materialize_study_kpi,
    validate_study_id,
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
_STUDY_KPI_METRICS = (
    "net_profit_micropoints",
    "median_fold_profit_factor_milli",
    "trade_count",
    "monthly_realized_exit_drawdown_share_of_gross_profit_ppm",
)
_STUDY_KPI_ACTIVATION_OPERATION_ID = (
    "study-close-kpi-main-delivery-authority-v1"
)
_STUDY_KPI_BACKFILL_OPERATION_ID = "study-kpi-historical-backfill-v1"
_BATCH_OUTCOMES = frozenset(
    {"completed", "budget_exhausted", "stopped_early", "not_evaluable", "engineering_failure"}
)
_ENGINEERING_FIXTURE_OUTCOME = "engineering_fixture_complete"
_STUDY_BOUND_IMPLEMENTATION_PATTERN = re.compile(r"\b(?:MIS|STU)-[0-9]{4}\b")


@dataclass(frozen=True, slots=True)
class TransitionResult:
    event_id: str
    revision: int
    reused: bool
    result: Mapping[str, Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class RunningJobExecution:
    """Immutable identity of one writer-authorized running Job execution."""

    job_id: str
    job_hash: str
    start_record_id: str
    job_permit_id: str

    def __post_init__(self) -> None:
        job_id = _require_ascii("running Job id", self.job_id)
        if not job_id.startswith("job:") or len(job_id) != 68:
            raise TransitionError("running Job id is invalid")
        _require_digest("running Job hash", self.job_hash)
        _require_digest("running Job start record", self.start_record_id)
        _require_digest("running Job permit", self.job_permit_id)

    def payload(self) -> dict[str, str]:
        return {
            "job_hash": self.job_hash,
            "job_id": self.job_id,
            "job_permit_id": self.job_permit_id,
            "start_record_id": self.start_record_id,
        }

    @property
    def identity(self) -> str:
        return canonical_digest(
            domain="running-job-execution",
            payload=self.payload(),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RunningJobExecution":
        if not isinstance(value, Mapping) or set(value) != {
            "job_hash",
            "job_id",
            "job_permit_id",
            "start_record_id",
        }:
            raise TransitionError("running Job execution context is invalid")
        return cls(
            job_hash=value["job_hash"],
            job_id=value["job_id"],
            job_permit_id=value["job_permit_id"],
            start_record_id=value["start_record_id"],
        )


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


def _static_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value
        if isinstance(node.value, bytes):
            try:
                return node.value.decode("ascii")
            except UnicodeDecodeError:
                return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left)
        right = _static_string(node.right)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                return None
            parts.append(value.value)
        return "".join(parts)
    return None


def _hardcoded_control_ids(source: bytes) -> tuple[str, ...]:
    """Find static Mission/Study IDs in Python or conservatively in other code."""

    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError:
        return tuple(
            sorted(
                set(
                    _STUDY_BOUND_IMPLEMENTATION_PATTERN.findall(
                        source.decode("ascii", errors="ignore")
                    )
                )
            )
        )
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return tuple(
            sorted(set(_STUDY_BOUND_IMPLEMENTATION_PATTERN.findall(text)))
        )
    docstrings: set[int] = set()
    for owner in ast.walk(tree):
        body = getattr(owner, "body", None)
        if (
            isinstance(body, list)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            docstrings.add(id(body[0].value))
    found: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in docstrings:
            continue
        value = _static_string(node)
        if value is not None:
            found.update(_STUDY_BOUND_IMPLEMENTATION_PATTERN.findall(value))
    return tuple(sorted(found))


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


def _require_successor_basis(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "continuation_reason",
        "predecessor_mission_close_record_id",
    }:
        raise TransitionError("successor basis schema is invalid")
    result = _copy(value)
    _require_ascii("continuation reason", result["continuation_reason"])
    _require_digest(
        "predecessor Mission close record",
        result["predecessor_mission_close_record_id"],
    )
    return result


def _require_authority_document_bytes(
    *, relative: str, current: bytes, replacement: bytes
) -> None:
    """Validate one bound authority document before it can enter the Journal."""

    try:
        current_text = current.decode("ascii")
        replacement_text = replacement.decode("ascii")
    except UnicodeDecodeError as exc:
        raise TransitionError("authority documents must remain ASCII") from exc
    if (
        not replacement_text.endswith("\n")
        or any(
            ord(character) < 32 and character not in {"\t", "\n", "\r"}
            for character in replacement_text
        )
    ):
        raise TransitionError("authority document text is malformed")
    if relative == "OPERATING_DIRECTION.md":
        required_markers = (
            "# Axiom Operating Direction\n",
            "status: active\n",
            "active_project_authority: true\n",
            "encoding: ascii_only\n",
            "- [MUST] ",
        )
        if any(marker not in replacement_text for marker in required_markers):
            raise TransitionError("operating direction structure is invalid")
        return
    if not relative.endswith(".yaml"):
        raise TransitionError("bound authority document type is unsupported")
    try:
        current_value = yaml.safe_load(current_text)
        replacement_value = yaml.safe_load(replacement_text)
    except yaml.YAMLError as exc:
        raise TransitionError("authority YAML is invalid") from exc
    if not isinstance(current_value, dict) or not isinstance(replacement_value, dict):
        raise TransitionError("authority YAML must contain one top-level mapping")
    if (
        type(current_value.get("schema")) is not str
        or type(current_value.get("status")) is not str
        or replacement_value.get("schema") != current_value["schema"]
        or replacement_value.get("status") != current_value["status"]
    ):
        raise TransitionError("authority YAML schema or status changed unexpectedly")


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
        self.journal = DurableJournal(self.root / LEGACY_JOURNAL_RELATIVE_PATH)
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
        freshness_required: bool = True,
        error_type: type[Exception] = TransitionError,
    ) -> IndexRecord:
        """Return typed source authority, optionally requiring live freshness."""

        from axiom_rift.research.source_authority import (
            AUTHORITY_TRANSITION_EVIDENCE,
            SourceAuthorityAuditManifest,
            SourceAuthorityInvalidation,
            SourceAuthorityLatch,
        )
        from axiom_rift.research.sources import (
            SourceContract,
            SourceEligibilityState,
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
            authority_stream = f"source-authority:{source_id}"
            authority_head = index.event_head(authority_stream)
            if authority_head is not None:
                correction = index.get(
                    authority_head.record_kind, authority_head.record_id
                )
                if (
                    correction is None
                    or correction.kind != "source-authority-invalidation"
                    or correction.status != "confirmed_and_suspended"
                    or correction.subject != f"Source:{source_id}"
                    or correction.event_stream != authority_stream
                    or correction.event_sequence != authority_head.sequence
                    or set(correction.payload)
                    != {
                        "audit_manifest",
                        "eligible_source_state_record_id",
                        "invalidated_state",
                        "invalidation",
                        "latch",
                        "preserved_receipt_id",
                        "prior_active_source_state_record_id",
                        "replacement_state_record_id",
                        "scientific_trial_delta",
                    }
                ):
                    raise ValueError("source authority correction is malformed")
                invalidation = SourceAuthorityInvalidation.from_identity_payload(
                    correction.payload["invalidation"]
                )
                manifest = SourceAuthorityAuditManifest.from_mapping(
                    correction.payload["audit_manifest"]
                )
                latch = SourceAuthorityLatch.from_mapping(correction.payload["latch"])
                expected_latch = SourceAuthorityLatch.bind(
                    invalidation=invalidation,
                    manifest=manifest,
                )
                replacement_id = correction.payload["replacement_state_record_id"]
                replacement = (
                    None
                    if not isinstance(replacement_id, str)
                    else index.get("source-state", replacement_id)
                )
                source_head = index.event_head(stream)
                invalidated = index.get(
                    "source-state", invalidation.source_state_record_id
                )
                prior_active_id = correction.payload[
                    "prior_active_source_state_record_id"
                ]
                prior_active = (
                    None
                    if not isinstance(prior_active_id, str)
                    else index.get("source-state", prior_active_id)
                )
                invalidated_receipt_payload = (
                    None
                    if invalidated is None
                    else invalidated.payload.get("receipt")
                )
                invalidated_receipt = (
                    None
                    if not isinstance(invalidated_receipt_payload, dict)
                    else require_edge(
                        invalidated,
                        sequence=invalidated.event_sequence or 0,
                        state=correction.payload["invalidated_state"],
                        evidence=SourceTransitionEvidence(
                            invalidated_receipt_payload["evidence"]
                        ),
                    )
                )
                invalidated_state = correction.payload["invalidated_state"]
                allowed_invalidated_states = {
                    SourceEligibilityState.CONTEXT_ONLY.value,
                    SourceEligibilityState.HISTORICAL_AUDITED.value,
                    SourceEligibilityState.RUNTIME_ELIGIBLE.value,
                }
                context_only_invalidation = (
                    invalidated_state == SourceEligibilityState.CONTEXT_ONLY.value
                )
                expected_invalidated_id = (
                    None
                    if invalidated is None
                    or invalidated.event_sequence is None
                    else canonical_digest(
                        domain="source-state",
                        payload={
                            "source_id": source_id,
                            "state": invalidated_state,
                            "ordinal": invalidated.event_sequence,
                            "evidence_receipt_id": invalidated.payload.get(
                                "evidence_receipt_id"
                            ),
                        },
                    )
                )
                invalidated_receipt_is_legal = (
                    invalidated_receipt is None
                    and invalidated_receipt_payload is None
                    and correction.payload["preserved_receipt_id"] is None
                    if context_only_invalidation
                    else invalidated_receipt is not None
                    and correction.payload["preserved_receipt_id"]
                    == invalidated_receipt.identity
                    and (
                        (
                            invalidated_state
                            == SourceEligibilityState.HISTORICAL_AUDITED.value
                            and invalidated_receipt.evidence
                            is SourceTransitionEvidence.HISTORICAL_AUDIT
                        )
                        or (
                            invalidated_state
                            == SourceEligibilityState.RUNTIME_ELIGIBLE.value
                            and invalidated_receipt.evidence
                            in {
                                SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF,
                                SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION,
                            }
                        )
                    )
                )
                expected_replacement_id = (
                    None
                    if replacement is None
                    else canonical_digest(
                        domain="source-state",
                        payload={
                            "source_id": source_id,
                            "state": "suspended",
                            "ordinal": replacement.event_sequence,
                            "evidence_receipt_id": replacement.payload.get(
                                "evidence_receipt_id"
                            ),
                        },
                    )
                )
                ordinary_suspended = (
                    prior_active is not None
                    and invalidated is not None
                    and prior_active.record_id != invalidated.record_id
                )
                ordinary_suspension_is_legal = True
                if ordinary_suspended:
                    try:
                        ordinary_receipt = require_edge(
                            prior_active,
                            sequence=prior_active.event_sequence or 0,
                            state=SourceEligibilityState.SUSPENDED.value,
                            evidence=SourceTransitionEvidence.DRIFT,
                        )
                    except (KeyError, TypeError, ValueError):
                        ordinary_suspension_is_legal = False
                    else:
                        ordinary_suspension_is_legal = (
                            ordinary_receipt is not None
                            and invalidated.event_sequence is not None
                            and prior_active.event_sequence
                            == invalidated.event_sequence + 1
                            and prior_active.subject == f"Source:{source_id}"
                            and prior_active.fingerprint == source_id
                            and prior_active.payload.get("source_authority_latch")
                            is None
                            and all(
                                prior_active.payload.get(field)
                                == invalidated.payload.get(field)
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
                        )
                if (
                    authority_head.sequence != 1
                    or invalidation.identity != correction.record_id
                    or correction.fingerprint
                    != invalidation.identity.removeprefix(
                        "source-authority-invalidation:"
                    )
                    or invalidation.source_contract_id != source_id
                    or invalidated_state not in allowed_invalidated_states
                    or correction.payload["eligible_source_state_record_id"]
                    != invalidation.source_state_record_id
                    or latch != expected_latch
                    or correction.payload["preserved_receipt_id"]
                    != (
                        None
                        if replacement is None
                        else replacement.payload.get("evidence_receipt_id")
                    )
                    or correction.payload["scientific_trial_delta"] != 0
                    or source_head is None
                    or replacement is None
                    or replacement.record_id != replacement_id
                    or replacement.record_id != expected_replacement_id
                    or replacement.event_stream != stream
                    or replacement.event_sequence != source_head.sequence
                    or replacement.record_id != source_head.record_id
                    or replacement.status != "suspended"
                    or replacement.subject != f"Source:{source_id}"
                    or replacement.fingerprint != source_id
                    or replacement.payload.get("ordinal")
                    != replacement.event_sequence
                    or replacement.payload.get("transition_evidence")
                    != AUTHORITY_TRANSITION_EVIDENCE
                    or replacement.payload.get("source_authority_latch")
                    != latch.to_identity_payload()
                    or replacement.payload.get(
                        "eligible_source_state_record_id"
                    )
                    != invalidation.source_state_record_id
                    or replacement.payload.get(
                        "prior_active_source_state_record_id"
                    )
                    != prior_active_id
                    or invalidated is None
                    or invalidated.status != invalidated_state
                    or invalidated.record_id != expected_invalidated_id
                    or not invalidated_receipt_is_legal
                    or invalidated.event_stream != stream
                    or prior_active is None
                    or prior_active.event_stream != stream
                    or prior_active.event_sequence != replacement.event_sequence - 1
                    or not ordinary_suspension_is_legal
                    or invalidated.record_id
                    != latch.invalidated_source_state_record_id
                    or invalidated.payload.get("evidence_receipt_id")
                    != correction.payload["preserved_receipt_id"]
                    or replacement.payload.get("receipt")
                    != invalidated.payload.get("receipt")
                    or replacement.payload.get("suspension_reason")
                    != (
                        f"{invalidation.reason_code.value}: "
                        f"{invalidation.observed_defect}"
                    )
                    or any(
                        replacement.payload.get(field)
                        != invalidated.payload.get(field)
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
                    raise ValueError("source authority correction provenance is invalid")
                durable_manifest = SourceAuthorityAuditManifest.from_bytes(
                    self.evidence.read_verified(latch.audit_manifest_hash)
                )
                if durable_manifest != manifest:
                    raise ValueError("source authority audit manifest projection drifted")
                durable_report = self.evidence.read_verified(
                    manifest.report_artifact_hash
                )
                manifest.require_report(durable_report)
                raise error_type(
                    f"source {source_id!r} is permanently audit-invalidated; "
                    "a new SourceContract identity is required"
                )
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
            availability = contract.availability()
            ttl_seconds = availability.get(
                "eligibility_receipt_ttl_seconds",
                availability["causal_ttl_seconds"],
            )
            if freshness_required and (
                isinstance(ttl_seconds, bool)
                or not isinstance(ttl_seconds, int)
                or ttl_seconds <= 0
            ):
                raise ValueError("runtime source eligibility TTL is invalid")
            age_seconds = (now - observed_at).total_seconds()
            if freshness_required and (
                age_seconds < 0 or age_seconds > ttl_seconds
            ):
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

    def _require_source_authority_for_actions(
        self,
        index: LocalIndex,
        source_id: str,
        *,
        actions: Sequence[str],
        error_type: type[Exception] = TransitionError,
    ) -> IndexRecord:
        """Apply one source-freshness policy consistently at all action gates."""

        normalized = tuple(actions)
        allowed = {"performance_batch", "runtime_source_use"}
        if (
            not normalized
            or len(set(normalized)) != len(normalized)
            or any(type(action) is not str or action not in allowed for action in normalized)
        ):
            raise error_type("source authority action policy is invalid")
        return self._require_runtime_source(
            index,
            source_id,
            freshness_required="runtime_source_use" in normalized,
            error_type=error_type,
        )

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

    def verify_running_job_execution(
        self,
        execution: RunningJobExecution,
        *,
        expected_callable_identity: str,
        expected_evidence_subject: Mapping[str, str] | None = None,
        required_input_hashes: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Reconstruct a non-runtime engine capability from Journal authority."""

        if not isinstance(execution, RunningJobExecution):
            raise PermitError("engine entry requires a running Job execution context")
        _require_ascii("expected callable identity", expected_callable_identity)
        expected_subject: dict[str, str] | None = None
        if expected_evidence_subject is not None:
            if (
                not isinstance(expected_evidence_subject, Mapping)
                or set(expected_evidence_subject) != {"kind", "id"}
            ):
                raise TransitionError("expected evidence subject is invalid")
            expected_subject = {
                "kind": _require_ascii(
                    "expected evidence subject kind",
                    expected_evidence_subject["kind"],
                ),
                "id": _require_ascii(
                    "expected evidence subject id",
                    expected_evidence_subject["id"],
                ),
            }
        required = tuple(required_input_hashes)
        for item in required:
            _require_digest("required Job input", item)
        if len(set(required)) != len(required):
            raise TransitionError("required Job inputs contain duplicates")

        with WriterLock(self.lock_path):
            with self._open_authoritative_index() as index:
                current = self._require_stable_locked(index)
                assert current is not None
                job = current["scientific"]["active_job"]
                if (
                    not isinstance(job, dict)
                    or job.get("status") != "running"
                    or job.get("id") != execution.job_id
                    or job.get("hash") != execution.job_hash
                    or job.get("start_record_id") != execution.start_record_id
                ):
                    raise PermitError("running Job execution context is stale")
                declaration = index.get("job-declared", execution.job_id)
                start = index.get("job-started", execution.start_record_id)
                if (
                    declaration is None
                    or declaration.fingerprint != execution.job_hash
                    or start is None
                    or start.status != "running"
                    or start.subject != f"Job:{execution.job_id}"
                    or start.fingerprint != execution.job_hash
                    or start.payload.get("job_permit_id")
                    != execution.job_permit_id
                ):
                    raise PermitError("running Job provenance is unavailable")
                spec = declaration.payload.get("spec")
                if (
                    not isinstance(spec, dict)
                    or spec.get("runtime_binding") is not None
                    or spec.get("callable_identity") != expected_callable_identity
                    or (
                        expected_subject is not None
                        and spec.get("evidence_subject") != expected_subject
                    )
                    or not set(required).issubset(spec.get("input_hashes", []))
                ):
                    raise PermitError("running Job capability differs from engine entry")
                stream = f"permit:{execution.job_permit_id}"
                issued = index.event_record(stream, 1)
                consumed = index.event_record(stream, 2)
                if issued is None or consumed is None:
                    raise PermitError("running Job permit provenance is incomplete")
                engine_entry_id = job.get("engine_entry_record_id")
                engine_entry = (
                    None
                    if not isinstance(engine_entry_id, str)
                    else index.get("job-engine-entry", engine_entry_id)
                )
                try:
                    issued_permit = Permit.from_mapping(issued.payload)
                except (KeyError, TypeError, ValueError) as exc:
                    raise PermitError("running Job issued permit is invalid") from exc
                if (
                    issued.kind != "permit-issued"
                    or issued.status != "issued"
                    or issued.fingerprint != execution.job_permit_id
                    or issued_permit.permit_id != execution.job_permit_id
                    or issued_permit.kind is not PermitKind.JOB
                    or issued_permit.subject.kind is not SubjectKind.JOB
                    or issued_permit.subject.subject_id != execution.job_id
                    or issued_permit.input_hash != execution.job_hash
                    or issued_permit.actions != ("start_job",)
                    or not issued_permit.one_shot
                    or consumed.kind != "permit-consumed"
                    or consumed.status != "consumed"
                    or consumed.fingerprint != execution.job_permit_id
                    or consumed.payload
                    != {
                        "one_shot": True,
                        "permit_id": execution.job_permit_id,
                    }
                    or consumed.authority_event_id != start.authority_event_id
                    or consumed.authority_sequence != start.authority_sequence
                    or engine_entry is None
                    or engine_entry.status != "validated"
                    or engine_entry.subject != f"Job:{execution.job_id}"
                    or engine_entry.fingerprint != execution.job_hash
                    or engine_entry.payload
                    != {
                        "execution": execution.payload(),
                        "permit_consumption_record_id": consumed.record_id,
                    }
                    or engine_entry.authority_event_id != start.authority_event_id
                    or engine_entry.authority_sequence != start.authority_sequence
                ):
                    raise PermitError("running Job permit and start provenance diverge")
                return {
                    "batch_id": declaration.payload.get("batch_id"),
                    "execution": execution.payload(),
                    "initiative_id": declaration.payload.get("initiative_id"),
                    "mission_id": declaration.payload.get("mission_id"),
                    "spec": _copy(spec),
                    "study_id": declaration.payload.get("study_id"),
                }

    def verify_reproducible_cache_producer(
        self,
        producer: RunningJobExecution,
        *,
        cache_output_name: str,
        cache_hash: str,
        expected_callable_identity: str,
        expected_evidence_subject: Mapping[str, str],
        expected_output_classes: Mapping[str, str],
        expected_study_id: str,
        manifest_output_name: str,
        manifest_hash: str,
    ) -> None:
        """Require cache bytes to come from a completed validated Job."""

        if not isinstance(producer, RunningJobExecution):
            raise TransitionError("cache producer execution is invalid")
        for name, value in (
            ("cache output name", cache_output_name),
            ("manifest output name", manifest_output_name),
        ):
            _require_ascii(name, value)
        _require_digest("cache hash", cache_hash)
        _require_digest("cache manifest hash", manifest_hash)
        _require_ascii("expected cache callable", expected_callable_identity)
        _require_ascii("expected cache Study", expected_study_id)
        if (
            not isinstance(expected_evidence_subject, Mapping)
            or set(expected_evidence_subject) != {"kind", "id"}
        ):
            raise TransitionError("expected cache evidence subject is invalid")
        expected_subject = dict(expected_evidence_subject)
        if any(
            type(value) is not str or not value or not value.isascii()
            for value in expected_subject.values()
        ):
            raise TransitionError("expected cache evidence subject is invalid")
        expected_classes = dict(expected_output_classes)
        if not expected_classes or any(
            type(name) is not str
            or not name
            or not name.isascii()
            or storage_class
            not in {"durable_evidence", "reproducible_cache", "transient"}
            for name, storage_class in expected_classes.items()
        ):
            raise TransitionError("expected cache output classes are invalid")
        with WriterLock(self.lock_path):
            with self._open_authoritative_index() as index:
                current = self._require_stable_locked(index)
                assert current is not None
                declaration = index.get("job-declared", producer.job_id)
                declared_spec = (
                    None if declaration is None else declaration.payload.get("spec")
                )
                if (
                    declaration is None
                    or declaration.fingerprint != producer.job_hash
                    or declaration.payload.get("mission_id")
                    != current["scientific"]["active_mission"]
                    or declaration.payload.get("study_id") != expected_study_id
                    or not isinstance(declared_spec, dict)
                    or declared_spec.get("callable_identity")
                    != expected_callable_identity
                    or declared_spec.get("evidence_subject") != expected_subject
                    or set(declared_spec.get("expected_outputs", []))
                    != set(expected_classes)
                    or declared_spec.get("output_classes") != expected_classes
                ):
                    raise TransitionError("cache producer declaration is unavailable")
                work_fingerprint = declaration.payload.get("work_fingerprint")
                head = (
                    None
                    if not isinstance(work_fingerprint, str)
                    else index.event_head(f"job-attempt:{work_fingerprint}")
                )
                completion = (
                    None
                    if head is None
                    else index.get(head.record_kind, head.record_id)
                )
                scientific = (
                    None if completion is None else completion.payload.get("scientific")
                )
                failure = (
                    None if completion is None else completion.payload.get("failure")
                )
                scientific_verdict = (
                    None
                    if not isinstance(scientific, dict)
                    else scientific.get("verdict")
                )
                if (
                    completion is None
                    or completion.kind != "job-completed"
                    or completion.payload.get("job_id") != producer.job_id
                    or completion.payload.get("start_record_id")
                    != producer.start_record_id
                    or set(completion.payload.get("outputs", {}))
                    != set(expected_classes)
                    or completion.payload.get("output_classes")
                    != expected_classes
                    or completion.payload.get("outputs", {}).get(cache_output_name)
                    != cache_hash
                    or completion.payload.get("outputs", {}).get(
                        manifest_output_name
                    )
                    != manifest_hash
                    or completion.payload.get("output_classes", {}).get(
                        cache_output_name
                    )
                    != "reproducible_cache"
                    or completion.payload.get("output_classes", {}).get(
                        manifest_output_name
                    )
                    != "durable_evidence"
                    or not isinstance(scientific, dict)
                    or scientific_verdict not in {"passed", "failed", "not_evaluable"}
                    or scientific.get("scientific_eligible") is not True
                    or completion.status not in {
                        "success",
                        "failed",
                        "not_evaluable",
                    }
                    or (
                        completion.status == "success"
                        and failure is not None
                    )
                    or (
                        completion.status == "failed"
                        and (
                            not isinstance(failure, dict)
                            or failure.get("failure_kind")
                            != "scientific_falsification"
                        )
                    )
                    or (
                        completion.status == "not_evaluable"
                        and (
                            not isinstance(failure, dict)
                            or failure.get("failure_kind") != "not_evaluable"
                        )
                    )
                ):
                    raise TransitionError(
                        "cache producer completion is not validator-derived"
                    )

    def _commit(
        self,
        *,
        event_kind: str,
        operation_id: str,
        subject: str,
        payload: Mapping[str, Any],
        prepare: Prepare,
        evidence_blobs: Sequence[bytes] = (),
        authority_replacements: Sequence[Mapping[str, Any]] = (),
        journal_storage_migration: bool = False,
        crash_after: str | None = None,
        allow_empty: bool = False,
        read_only_when_unchanged: bool = False,
    ) -> TransitionResult:
        _require_ascii("event_kind", event_kind)
        _require_ascii("operation_id", operation_id)
        _require_ascii("subject", subject)
        if bool(authority_replacements) != (event_kind == "authority_migrated"):
            raise TransitionError(
                "authority replacements and the typed migration event are inseparable"
            )
        if journal_storage_migration != (event_kind == "journal_storage_migrated"):
            raise TransitionError(
                "Journal storage materialization and its typed event are inseparable"
            )
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
                    if (
                        existing.authority_sequence is None
                        or existing.authority_event_id is None
                    ):
                        raise IndexIntegrityError(
                            "idempotent operation lacks Journal authority"
                        )
                    return TransitionResult(
                        event_id=existing.authority_event_id,
                        revision=existing.authority_sequence,
                        reused=True,
                        result=existing.payload.get("result", {}),
                    )
                if current is not None:
                    science = current["scientific"]
                    pending_direction = current["next_action"].get("kind")
                    required_direction_event = {
                        "record_research_intake": "research_intake_recorded",
                        "diagnose_study": "study_diagnosis_recorded",
                        "review_architecture": "architecture_review_recorded",
                    }.get(pending_direction)
                    if (
                        required_direction_event is not None
                        and event_kind != required_direction_event
                        and not event_kind.endswith("_fixture_seeded")
                    ):
                        direction_label = {
                            "record_research_intake": "research intake",
                            "diagnose_study": "Study diagnosis",
                            "review_architecture": "architecture review",
                        }[pending_direction]
                        raise TransitionError(
                            f"transition cannot bypass pending {direction_label}"
                        )
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
                if not isinstance(next_body, dict):
                    raise TransitionError("transition control body must be a mapping")
                if current is not None:
                    current_authority = current["authority"]
                    next_authority = next_body.get("authority")
                    if event_kind == "authority_migrated":
                        expected_authority = _copy(current_authority)
                        if isinstance(next_authority, dict):
                            expected_authority["manifest_digest"] = next_authority.get(
                                "manifest_digest"
                            )
                        if (
                            not isinstance(next_authority, dict)
                            or next_authority != expected_authority
                            or next_authority.get("manifest_digest")
                            == current_authority.get("manifest_digest")
                        ):
                            raise TransitionError(
                                "authority migration may change only the manifest digest"
                            )
                    elif next_authority != current_authority:
                        raise TransitionError(
                            "only a typed authority migration may change authority"
                        )
                preview = _copy(next_body)
                if current is None:
                    preview["revision"] = 1
                    preview["heads"] = {
                        "journal": {"sequence": 1, "event_id": "0" * 64},
                        "index": {
                            "required_sequence": 1,
                            "required_record_count": 1,
                            "required_projection_digest": "0" * 64,
                        },
                    }
                else:
                    preview["revision"] = current["revision"]
                    preview["heads"] = _copy(current["heads"])
                try:
                    seal_control(preview)
                except ControlStateError as exc:
                    raise TransitionError(
                        "transition produced an invalid control body"
                    ) from exc
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
                event_occurred_at_utc = self.clock()
                _parse_utc("event occurred_at_utc", event_occurred_at_utc)
                event = self.journal._append_authorized(
                    capability=self._journal_write_capability,
                    expected_head=current_head,
                    event_kind=event_kind,
                    operation_id=operation_id,
                    subject=subject,
                    occurred_at_utc=event_occurred_at_utc,
                    payload=committed_payload,
                    control=next_body,
                    index_records=[self._index_mapping(item) for item in all_records],
                    index_record_count=index.record_count() + 1 + len(all_records),
                    index_projection_digest=projected_digest,
                )
                if crash_after == "after_journal":
                    raise InjectedCrash("after_journal")
                if journal_storage_migration:
                    def after_journal_storage_stage(label: str) -> None:
                        if crash_after == label:
                            raise InjectedCrash(label)

                    self.journal.materialize_legacy_migration(
                        event,
                        after_stage=after_journal_storage_stage,
                    )
                    if crash_after == "after_journal_storage":
                        raise InjectedCrash("after_journal_storage")
                if authority_replacements:
                    self._apply_authority_replacements(
                        authority=next_body["authority"],
                        replacements=authority_replacements,
                        expected_manifest_digest=next_body["authority"][
                            "manifest_digest"
                        ],
                    )
                if crash_after == "after_authority_files":
                    raise InjectedCrash("after_authority_files")
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
            journal_storage_repaired = self.journal.recover_storage()
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
                return {
                    "journal_sequence": 0,
                    "journal_storage_repaired": journal_storage_repaired,
                    "control_repaired": False,
                    "index_rebuilt": False,
                }
            last = events[-1]
            desired = self._assemble(last)
            try:
                sealed_desired = seal_control(desired)
            except ControlStateError as exc:
                raise JournalIntegrityError(
                    "latest Journal control body is invalid"
                ) from exc
            applied_sequence = (
                0 if control is None else control["heads"]["journal"]["sequence"]
            )
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
                self._apply_pending_authority_migrations(
                    events=events,
                    applied_sequence=applied_sequence,
                    final_authority=desired["authority"],
                )
                if (
                    self._authority_manifest_digest(desired["authority"])
                    != desired["authority"]["manifest_digest"]
                ):
                    raise RecoveryRequired(
                        "journal authority manifest is not materialized"
                    )
                control_repaired = control is None or control != sealed_desired
                if control_repaired:
                    self.control.replace(desired)
                records: list[IndexRecord] = []
                for event in events:
                    records.extend(self._event_records(event))
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
            report = {
                "journal_sequence": last["sequence"],
                "journal_storage_repaired": journal_storage_repaired,
                "control_repaired": control_repaired,
                "index_rebuilt": needs_rebuild,
            }
        report["study_kpi_projection_changed"] = (
            self.rebuild_study_kpi_projection()
        )
        return report

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

    @staticmethod
    def _authority_relative_paths(authority: Mapping[str, Any]) -> tuple[str, ...]:
        relative_paths = tuple(
            [authority["operating_direction"]]
            + list(authority["contracts"])
            + list(authority["foundation_inputs"])
        )
        if len(set(relative_paths)) != len(relative_paths):
            raise RecoveryRequired("authority manifest paths are not unique")
        return relative_paths

    @staticmethod
    def _authority_digest_from_hashes(hashes: Mapping[str, str]) -> str:
        return _digest(dict(sorted(hashes.items())), domain="authority-manifest")

    def _authority_path_hashes(
        self, authority: Mapping[str, Any]
    ) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for relative in self._authority_relative_paths(authority):
            _require_ascii("authority path", relative)
            path = (self.foundation_root / relative).resolve()
            root = self.foundation_root.resolve()
            if root != path and root not in path.parents:
                raise RecoveryRequired("authority path escapes Foundation root")
            if not path.is_file():
                raise RecoveryRequired(f"authority input is absent: {relative}")
            hashes[relative] = sha256(path.read_bytes()).hexdigest()
        return hashes

    def _authority_manifest_digest(self, authority: Mapping[str, Any]) -> str:
        return self._authority_digest_from_hashes(
            self._authority_path_hashes(authority)
        )

    def _replace_authority_file(self, relative: str, content: bytes) -> None:
        target = (self.foundation_root / relative).resolve()
        root = self.foundation_root.resolve()
        if root != target and root not in target.parents:
            raise RecoveryRequired("authority migration target escapes Foundation root")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".authority.tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _apply_authority_replacements(
        self,
        *,
        authority: Mapping[str, Any],
        replacements: Sequence[Mapping[str, Any]],
        expected_manifest_digest: str,
    ) -> None:
        rows = self._validated_authority_replacement_rows(
            authority=authority,
            replacements=replacements,
        )
        targets = {
            row["path"]: {
                "allowed_current_hashes": {row["old_sha256"]},
                "artifact_sha256": row["artifact_sha256"],
                "new_sha256": row["new_sha256"],
            }
            for row in rows
        }
        self._materialize_authority_targets(
            authority=authority,
            targets=targets,
            expected_manifest_digest=expected_manifest_digest,
        )

    def _validated_authority_replacement_rows(
        self,
        *,
        authority: Mapping[str, Any],
        replacements: Sequence[Mapping[str, Any]],
    ) -> tuple[dict[str, str], ...]:
        bound_paths = set(self._authority_relative_paths(authority))
        observed_paths: set[str] = set()
        rows: list[dict[str, str]] = []
        if not replacements:
            raise JournalIntegrityError("authority migration has no replacements")
        for replacement in replacements:
            if set(replacement) != {
                "artifact_sha256",
                "new_sha256",
                "old_sha256",
                "path",
            }:
                raise JournalIntegrityError(
                    "authority replacement schema is invalid"
                )
            relative = _require_ascii("authority replacement path", replacement["path"])
            if relative not in bound_paths or relative in observed_paths:
                raise JournalIntegrityError(
                    "authority replacement path is unbound or duplicated"
                )
            observed_paths.add(relative)
            old_hash = _require_digest(
                "authority old hash", replacement["old_sha256"]
            )
            new_hash = _require_digest(
                "authority new hash", replacement["new_sha256"]
            )
            artifact_hash = _require_digest(
                "authority artifact hash", replacement["artifact_sha256"]
            )
            if artifact_hash != new_hash or old_hash == new_hash:
                raise JournalIntegrityError(
                    "authority replacement identities are invalid"
                )
            rows.append(
                {
                    "artifact_sha256": artifact_hash,
                    "new_sha256": new_hash,
                    "old_sha256": old_hash,
                    "path": relative,
                }
            )
        return tuple(rows)

    def _materialize_authority_targets(
        self,
        *,
        authority: Mapping[str, Any],
        targets: Mapping[str, Mapping[str, Any]],
        expected_manifest_digest: str,
    ) -> None:
        current_hashes = self._authority_path_hashes(authority)
        to_write: list[tuple[str, bytes, str]] = []
        for relative in sorted(targets):
            target = targets[relative]
            if relative not in current_hashes or set(target) != {
                "allowed_current_hashes",
                "artifact_sha256",
                "new_sha256",
            }:
                raise JournalIntegrityError("authority target schema is invalid")
            allowed_current_hashes = target["allowed_current_hashes"]
            artifact_hash = _require_digest(
                "authority target artifact hash", target["artifact_sha256"]
            )
            new_hash = _require_digest(
                "authority target new hash", target["new_sha256"]
            )
            if (
                not isinstance(allowed_current_hashes, set)
                or not allowed_current_hashes
                or any(
                    type(value) is not str
                    or len(value) != 64
                    or any(character not in "0123456789abcdef" for character in value)
                    for value in allowed_current_hashes
                )
                or artifact_hash != new_hash
            ):
                raise JournalIntegrityError("authority target identities are invalid")
            current_hash = current_hashes[relative]
            if current_hash != new_hash:
                if current_hash not in allowed_current_hashes:
                    raise RecoveryRequired(
                        f"authority replacement source drifted: {relative}"
                    )
                content = self.evidence.read_verified(artifact_hash)
                to_write.append((relative, content, new_hash))
            current_hashes[relative] = new_hash
        if (
            self._authority_digest_from_hashes(current_hashes)
            != expected_manifest_digest
        ):
            raise RecoveryRequired(
                "authority replacement set does not produce the bound manifest"
            )
        for relative, content, new_hash in to_write:
            self._replace_authority_file(relative, content)
            target_path = (self.foundation_root / relative).resolve()
            if sha256(target_path.read_bytes()).hexdigest() != new_hash:
                raise RecoveryRequired(
                    f"authority replacement verification failed: {relative}"
                )
        if self._authority_manifest_digest(authority) != expected_manifest_digest:
            raise RecoveryRequired("authority migration manifest does not materialize")

    def _apply_pending_authority_migrations(
        self,
        *,
        events: Sequence[Mapping[str, Any]],
        applied_sequence: int,
        final_authority: Mapping[str, Any],
    ) -> None:
        targets: dict[str, dict[str, Any]] = {}
        for event in events[applied_sequence:]:
            if event.get("event_kind") != "authority_migrated":
                continue
            payload = event.get("payload")
            control = event.get("control")
            if not isinstance(payload, dict) or not isinstance(control, dict):
                raise JournalIntegrityError("authority migration event is malformed")
            replacements = payload.get("replacements")
            authority = control.get("authority")
            if not isinstance(replacements, list) or not isinstance(authority, dict):
                raise JournalIntegrityError("authority migration payload is malformed")
            sequence = event.get("sequence")
            if type(sequence) is not int or sequence <= 1 or sequence > len(events):
                raise JournalIntegrityError("authority migration sequence is invalid")
            previous_control = events[sequence - 2].get("control")
            previous_authority = (
                None
                if not isinstance(previous_control, dict)
                else previous_control.get("authority")
            )
            if not isinstance(previous_authority, dict):
                raise JournalIntegrityError(
                    "authority migration predecessor is malformed"
                )
            expected_authority = _copy(previous_authority)
            expected_authority["manifest_digest"] = authority.get("manifest_digest")
            if (
                authority != expected_authority
                or payload.get("schema") != "authority_manifest_migration.v1"
                or payload.get("old_manifest_digest")
                != previous_authority.get("manifest_digest")
                or payload.get("new_manifest_digest")
                != authority.get("manifest_digest")
            ):
                raise JournalIntegrityError("authority migration chain is invalid")
            rows = self._validated_authority_replacement_rows(
                authority=authority,
                replacements=replacements,
            )
            for row in rows:
                relative = row["path"]
                existing = targets.get(relative)
                if existing is None:
                    targets[relative] = {
                        "allowed_current_hashes": {
                            row["old_sha256"],
                            row["new_sha256"],
                        },
                        "artifact_sha256": row["artifact_sha256"],
                        "new_sha256": row["new_sha256"],
                    }
                    continue
                if existing["new_sha256"] != row["old_sha256"]:
                    raise JournalIntegrityError(
                        "authority replacement hash chain is discontinuous"
                    )
                existing["allowed_current_hashes"].add(row["new_sha256"])
                existing["artifact_sha256"] = row["artifact_sha256"]
                existing["new_sha256"] = row["new_sha256"]
        if targets:
            self._materialize_authority_targets(
                authority=final_authority,
                targets=targets,
                expected_manifest_digest=final_authority["manifest_digest"],
            )

    @staticmethod
    def _authority_migration_boundary(
        current: Mapping[str, Any], *, allow_active_stable_boundary: bool
    ) -> str | None:
        science = current["scientific"]
        inactive_names = (
            "active_study",
            "active_batch",
            "active_job",
            "active_repair",
            "active_executable",
            "active_lineage",
            "active_release",
            "active_holdout_evaluation",
        )
        disposed_root = (
            current["next_action"].get("kind") == "await_root_goal"
            and science.get("active_mission") is None
            and science.get("active_initiative") is None
            and all(science.get(name) is None for name in inactive_names)
            and current.get("authorizations") == {}
            and science.get("claim") == "none"
        )
        if disposed_root:
            return "disposed_root"
        active_authorizations = current.get("authorizations")
        mission_id = science.get("active_mission")
        initiative_id = science.get("active_initiative")
        active_stable = (
            allow_active_stable_boundary
            and current["next_action"].get("kind") == "portfolio_decision"
            and type(mission_id) is str
            and type(initiative_id) is str
            and all(science.get(name) is None for name in inactive_names)
            and isinstance(active_authorizations, dict)
            and set(active_authorizations)
            == {f"Mission:{mission_id}", f"Initiative:{initiative_id}"}
            and science.get("claim") == "none"
        )
        return "active_stable" if active_stable else None

    def migrate_journal_storage(
        self,
        *,
        reason: str,
        operation_id: str,
        allow_active_stable_boundary: bool = False,
        crash_after: str | None = None,
    ) -> TransitionResult:
        """Seal exact legacy Journal bytes and activate segmented storage."""

        _require_ascii("Journal storage migration reason", reason)
        _require_ascii("operation_id", operation_id)
        if type(allow_active_stable_boundary) is not bool:
            raise TransitionError("active stable Journal migration flag must be bool")
        self._require_study_close_delivery_guard()

        if self.journal.manifest_path.is_file() and not self.journal.path.exists():
            with WriterLock(self.lock_path):
                with self._open_authoritative_index() as index:
                    self._require_stable_locked(index)
                    existing = index.get("operation", operation_id)
                    if (
                        existing is None
                        or existing.status != "success"
                        or existing.payload.get("event_kind")
                        != "journal_storage_migrated"
                        or existing.authority_sequence is None
                        or existing.authority_event_id is None
                    ):
                        raise TransitionError(
                            "segmented Journal lacks the requested migration operation"
                        )
                    return TransitionResult(
                        event_id=existing.authority_event_id,
                        revision=existing.authority_sequence,
                        reused=True,
                        result=existing.payload.get("result", {}),
                    )
        if not self.journal.path.is_file():
            raise TransitionError("legacy Journal is unavailable for migration")
        if self.journal.manifest_path.exists():
            raise TransitionError("legacy and segmented Journal layouts overlap")
        if self.journal.segment_directory.is_dir() and any(
            path.is_file() and not path.name.startswith(".")
            for path in self.journal.segment_directory.iterdir()
        ):
            raise TransitionError("Journal segment residue precedes migration")

        legacy_content = self.journal.path.read_bytes()
        legacy_events = self.journal.read_all()
        if not legacy_events:
            raise TransitionError("Journal storage migration requires authority")
        pre_migration = {
            "byte_length": len(legacy_content),
            "sha256": sha256(legacy_content).hexdigest(),
            "first_sequence": legacy_events[0]["sequence"],
            "last_sequence": legacy_events[-1]["sequence"],
            "first_event_id": legacy_events[0]["event_id"],
            "last_event_id": legacy_events[-1]["event_id"],
        }
        boundary_name = (
            "active_stable"
            if allow_active_stable_boundary
            else "disposed_root"
        )
        migration_payload = {
            "schema": JOURNAL_STORAGE_MIGRATION_SCHEMA,
            "boundary": boundary_name,
            "reason": reason,
            "legacy_path": LEGACY_JOURNAL_RELATIVE_PATH,
            "manifest_path": JOURNAL_MANIFEST_RELATIVE_PATH,
            "sealed_segment_id": "000001",
            "sealed_segment_path": "records/journal/journal-000001.jsonl",
            "seal_path": "records/journal/journal-000001.seal.json",
            "active_segment_id": "000002",
            "active_segment_path": "records/journal/journal-000002.jsonl",
            "pre_migration": pre_migration,
            "trial_delta": 0,
            "holdout_delta": 0,
            "candidate_delta": 0,
            "claim_delta": 0,
            "recovery_action": "StateWriter.recover",
        }
        migration_id = canonical_digest(
            domain="journal-storage-migration", payload=migration_payload
        )

        def prepare(current: dict[str, Any] | None, _index: LocalIndex):
            if current is None:
                raise TransitionError("Journal storage migration requires control")
            boundary = self._authority_migration_boundary(
                current,
                allow_active_stable_boundary=allow_active_stable_boundary,
            )
            if boundary != boundary_name:
                raise TransitionError(
                    "Journal storage migration requires a disposed root or "
                    "authorized active Portfolio boundary"
                )
            if self.journal.manifest_path.exists():
                raise RecoveryRequired("Journal storage changed before migration")
            observed = self.journal.path.read_bytes()
            observed_events = self.journal.read_all()
            if (
                len(observed) != pre_migration["byte_length"]
                or sha256(observed).hexdigest() != pre_migration["sha256"]
                or not observed_events
                or observed_events[0]["event_id"]
                != pre_migration["first_event_id"]
                or observed_events[-1]["sequence"]
                != pre_migration["last_sequence"]
                or observed_events[-1]["event_id"]
                != pre_migration["last_event_id"]
                or current["heads"]["journal"]["event_id"]
                != pre_migration["last_event_id"]
            ):
                raise RecoveryRequired("legacy Journal changed before migration")
            body = self._body(current)
            record = _record(
                kind="journal-storage-migration",
                record_id=migration_id,
                subject="Journal:authority",
                status="activated",
                fingerprint=migration_id,
                payload=migration_payload,
            )
            return body, [record], {
                "migration_id": migration_id,
                "manifest_path": JOURNAL_MANIFEST_RELATIVE_PATH,
                "active_segment_path": migration_payload[
                    "active_segment_path"
                ],
            }

        return self._commit(
            event_kind="journal_storage_migrated",
            operation_id=operation_id,
            subject="Journal:authority",
            payload=migration_payload,
            prepare=prepare,
            journal_storage_migration=True,
            crash_after=crash_after,
        )

    def migrate_authority(
        self,
        *,
        replacements: Mapping[str, bytes],
        reason: str,
        operation_id: str,
        allow_active_stable_boundary: bool = False,
        crash_after: str | None = None,
    ) -> TransitionResult:
        """Activate exact staged authority bytes without rewriting prior state."""

        _require_ascii("authority migration reason", reason)
        _require_ascii("operation_id", operation_id)
        if type(allow_active_stable_boundary) is not bool:
            raise TransitionError("active stable authority boundary flag must be bool")
        if not isinstance(replacements, Mapping) or not replacements:
            raise TransitionError("authority migration requires replacement bytes")
        if any(type(relative) is not str for relative in replacements):
            raise TransitionError("authority replacement paths must be strings")
        requested_paths = tuple(sorted(replacements))
        for content in replacements.values():
            if type(content) is not bytes:
                raise TransitionError("authority replacement content must be bytes")
        authority: dict[str, Any] | None = None
        old_hashes: dict[str, str] | None = None
        current_contents: dict[str, bytes] | None = None
        with WriterLock(self.lock_path):
            with self._open_authoritative_index() as index:
                stable = self._require_stable_locked(index)
                if stable is None:
                    raise TransitionError(
                        "authority migration requires initialized control"
                    )
                existing = index.get("operation", operation_id)
                if existing is None:
                    authority = _copy(stable["authority"])
                    bound_paths = set(self._authority_relative_paths(authority))
                    if any(path not in bound_paths for path in requested_paths):
                        raise TransitionError(
                            "authority migration names an unbound path"
                        )
                    old_hashes = self._authority_path_hashes(authority)
                    if (
                        self._authority_digest_from_hashes(old_hashes)
                        != authority.get("manifest_digest")
                    ):
                        raise RecoveryRequired(
                            "authority drift precedes the migration"
                        )
                    current_contents = {
                        relative: (self.foundation_root / relative).read_bytes()
                        for relative in requested_paths
                    }
        if existing is not None:
            if (
                existing.status != "success"
                or existing.payload.get("event_kind") != "authority_migrated"
                or existing.authority_sequence is None
                or existing.authority_event_id is None
                or existing.authority_offset is None
            ):
                raise TransitionError("existing authority migration operation is invalid")
            event = self.journal.read_event_at(
                offset=existing.authority_offset,
                expected_sequence=existing.authority_sequence,
                expected_event_id=existing.authority_event_id,
            )
            event_payload = event.get("payload")
            if (
                event.get("operation_id") != operation_id
                or event.get("event_kind") != "authority_migrated"
                or not isinstance(event_payload, dict)
            ):
                raise TransitionError("existing authority migration payload is absent")
            rows = event_payload.get("replacements")
            observed = (
                {}
                if not isinstance(rows, list)
                else {row.get("path"): row.get("new_sha256") for row in rows}
            )
            requested = {
                relative: sha256(replacements[relative]).hexdigest()
                for relative in requested_paths
            }
            requested_boundary = (
                "active_stable"
                if allow_active_stable_boundary
                else "disposed_root"
            )
            if (
                event_payload.get("reason") != reason
                or event_payload.get("boundary") != requested_boundary
                or observed != requested
            ):
                raise TransitionError("idempotency key reused with different input")
            base_payload = {
                key: value for key, value in event_payload.items() if key != "evidence"
            }

            def unreachable(_current, _index):
                raise TransitionError("existing migration unexpectedly prepared again")

            return self._commit(
                event_kind="authority_migrated",
                operation_id=operation_id,
                subject="Authority:active",
                payload=base_payload,
                prepare=unreachable,
                evidence_blobs=tuple(
                    replacements[relative] for relative in requested_paths
                ),
                authority_replacements=tuple(rows),
                crash_after=crash_after,
            )
        assert authority is not None
        assert old_hashes is not None
        assert current_contents is not None
        old_manifest_digest = self._authority_digest_from_hashes(old_hashes)
        replacement_rows: list[dict[str, str]] = []
        replacement_blobs: list[bytes] = []
        new_hashes = dict(old_hashes)
        for relative in requested_paths:
            content = replacements[relative]
            _require_authority_document_bytes(
                relative=relative,
                current=current_contents[relative],
                replacement=content,
            )
            artifact = self.evidence.finalize(content)
            if artifact.sha256 == old_hashes[relative]:
                raise TransitionError("authority replacement does not change content")
            replacement_blobs.append(content)
            new_hashes[relative] = artifact.sha256
            replacement_rows.append(
                {
                    "artifact_sha256": artifact.sha256,
                    "new_sha256": artifact.sha256,
                    "old_sha256": old_hashes[relative],
                    "path": relative,
                }
            )
        new_manifest_digest = self._authority_digest_from_hashes(new_hashes)
        migration_payload = {
            "boundary": (
                "active_stable"
                if allow_active_stable_boundary
                else "disposed_root"
            ),
            "holdout_delta": 0,
            "new_manifest_digest": new_manifest_digest,
            "old_manifest_digest": old_manifest_digest,
            "reason": reason,
            "replacements": replacement_rows,
            "schema": "authority_manifest_migration.v1",
            "scientific_claim": "none",
            "trial_delta": 0,
        }
        migration_id = canonical_digest(
            domain="authority-manifest-migration", payload=migration_payload
        )

        def prepare(current: dict[str, Any] | None, _index: LocalIndex):
            if current is None:
                raise TransitionError("authority migration requires control")
            if (
                current["authority"].get("manifest_digest")
                != old_manifest_digest
                or self._authority_path_hashes(current["authority"]) != old_hashes
            ):
                raise RecoveryRequired("authority changed before migration commit")
            boundary = self._authority_migration_boundary(
                current,
                allow_active_stable_boundary=allow_active_stable_boundary,
            )
            if boundary is None:
                raise TransitionError(
                    "authority migration requires a disposed root or authorized "
                    "active Portfolio boundary"
                )
            if boundary != migration_payload["boundary"]:
                raise TransitionError("authority migration boundary differs")
            body = self._body(current)
            body["authority"]["manifest_digest"] = new_manifest_digest
            record = _record(
                kind="authority-migration",
                record_id=migration_id,
                subject="Authority:active",
                status="activated",
                fingerprint=migration_id,
                payload=migration_payload,
            )
            return body, [record], {
                "migration_id": migration_id,
                "new_manifest_digest": new_manifest_digest,
            }

        return self._commit(
            event_kind="authority_migrated",
            operation_id=operation_id,
            subject="Authority:active",
            payload=migration_payload,
            prepare=prepare,
            evidence_blobs=tuple(replacement_blobs),
            authority_replacements=tuple(replacement_rows),
            crash_after=crash_after,
        )

    def activate_project_goal_continuation(
        self,
        *,
        predecessor_mission_id: str,
        predecessor_mission_close_record_id: str,
        operation_id: str,
    ) -> TransitionResult:
        """Adopt one legacy negative terminal as the successor boundary."""

        _require_ascii("predecessor Mission id", predecessor_mission_id)
        _require_digest(
            "predecessor Mission close record",
            predecessor_mission_close_record_id,
        )

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("Project Goal activation requires control")
            science = current["scientific"]
            if (
                current["next_action"] != {"kind": "await_root_goal"}
                or any(
                    science.get(name) is not None
                    for name in (
                        "active_mission",
                        "active_initiative",
                        "active_study",
                        "active_batch",
                        "active_job",
                        "active_repair",
                        "active_executable",
                        "active_lineage",
                        "active_release",
                        "active_holdout_evaluation",
                    )
                )
                or current["authorizations"] != {}
            ):
                raise TransitionError(
                    "Project Goal activation requires the bare root boundary"
                )
            if index.event_head("project-goal:OPERATING_DIRECTION.md") is not None:
                raise TransitionError("Project Goal continuation is already activated")
            close_record = index.get(
                "mission-close", predecessor_mission_close_record_id
            )
            mission_open = index.get("mission-open", predecessor_mission_id)
            mission_closes = index.records_by_kind("mission-close")
            latest_close = (
                None
                if not mission_closes
                else max(
                    mission_closes,
                    key=lambda record: (
                        -1
                        if record.authority_sequence is None
                        else record.authority_sequence,
                        -1
                        if record.authority_offset is None
                        else record.authority_offset,
                    ),
                )
            )
            basis_id = (
                None
                if close_record is None
                else close_record.payload.get("basis_record_id")
            )
            basis = (
                None
                if not isinstance(basis_id, str)
                else index.get("exhaustion-audit", basis_id)
            )
            if (
                close_record is None
                or close_record.subject != f"Mission:{predecessor_mission_id}"
                or close_record.status != "closed_no_candidate"
                or mission_open is None
                or mission_open.subject != f"Mission:{predecessor_mission_id}"
                or mission_open.status != "open"
                or basis is None
                or basis.status != "accepted"
                or basis.subject != f"Mission:{predecessor_mission_id}"
                or latest_close is None
                or latest_close.record_id != predecessor_mission_close_record_id
            ):
                raise TransitionError(
                    "legacy predecessor is not an accepted negative terminal"
                )
            body = self._body(current)
            body["next_action"] = {
                "kind": "await_root_goal",
                "predecessor_basis_record_id": basis_id,
                "predecessor_mission_close_record_id": (
                    predecessor_mission_close_record_id
                ),
                "predecessor_mission_id": predecessor_mission_id,
                "predecessor_outcome": "closed_no_candidate",
            }
            adoption_payload = {
                "adopted_mission_close_record_id": (
                    predecessor_mission_close_record_id
                ),
                "basis_record_id": basis_id,
                "mission_id": predecessor_mission_id,
                "no_retroactive_authorization": True,
                "project_goal_authority": current["authority"][
                    "operating_direction"
                ],
                "schema": "project_goal_continuation_adoption.v1",
            }
            adoption_id = canonical_digest(
                domain="project-goal-continuation-adoption",
                payload=adoption_payload,
            )
            record = _record(
                kind="project-goal-adoption",
                record_id=adoption_id,
                subject="ProjectGoal:OPERATING_DIRECTION.md",
                status="active",
                fingerprint=adoption_id,
                payload=adoption_payload,
                event_stream="project-goal:OPERATING_DIRECTION.md",
                event_sequence=1,
            )
            return body, [record], {
                "adoption_id": adoption_id,
                "next_mission_ordinal": 2,
            }

        return self._commit(
            event_kind="project_goal_continuation_activated",
            operation_id=operation_id,
            subject="ProjectGoal:OPERATING_DIRECTION.md",
            payload={
                "predecessor_mission_close_record_id": (
                    predecessor_mission_close_record_id
                ),
                "predecessor_mission_id": predecessor_mission_id,
            },
            prepare=prepare,
        )

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
        successor_basis: Mapping[str, Any] | None = None,
        operation_id: str,
    ) -> TransitionResult:
        _require_ascii("mission_id", mission_id)
        goal_manifest = _require_manifest(
            "goal",
            goal,
            required={"objective", "scope", "terminal_contract"},
        )
        goal_hash = _digest(goal_manifest, domain="mission-goal")
        supplied_successor = (
            None
            if successor_basis is None
            else _require_successor_basis(successor_basis)
        )

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("Foundation is not initialized")
            body = self._body(current)
            science = body["scientific"]
            if science["active_mission"] is not None:
                raise TransitionError("a root Mission is already active")
            if index.get("mission-open", mission_id) is not None:
                raise TransitionError("Mission identity is already durable")
            boundary = body["next_action"]
            if boundary["kind"] != "await_root_goal":
                raise TransitionError("control is not at the root-goal boundary")
            if science.get("active_release") is not None:
                raise TransitionError("ready boundary contains an active Release")
            if science.get("active_holdout_evaluation") is not None:
                raise TransitionError("ready boundary contains an active holdout")
            predecessor_keys = {
                "kind",
                "predecessor_basis_record_id",
                "predecessor_mission_close_record_id",
                "predecessor_mission_id",
                "predecessor_outcome",
            }
            predecessor: dict[str, Any] | None = None
            if set(boundary) == {"kind"}:
                if supplied_successor is not None:
                    raise TransitionError(
                        "the first Mission cannot declare a successor basis"
                    )
                if index.records_by_kind("mission-close"):
                    raise TransitionError(
                        "a bare boundary with Mission history requires typed adoption"
                    )
                mission_ordinal = 1
                science["holdout_reveals"] = 0
                science["required_future_holdout_id"] = None
            elif set(boundary) == predecessor_keys:
                if boundary["predecessor_outcome"] != "closed_no_candidate":
                    raise TransitionError(
                        "only a negative Mission terminal admits a successor"
                    )
                if (
                    supplied_successor is None
                    or supplied_successor["predecessor_mission_close_record_id"]
                    != boundary["predecessor_mission_close_record_id"]
                ):
                    raise TransitionError(
                        "successor basis does not bind the exact predecessor"
                    )
                close_record = index.get(
                    "mission-close",
                    boundary["predecessor_mission_close_record_id"],
                )
                if (
                    close_record is None
                    or close_record.subject
                    != f"Mission:{boundary['predecessor_mission_id']}"
                    or close_record.status != boundary["predecessor_outcome"]
                    or close_record.payload.get("basis_record_id")
                    != boundary["predecessor_basis_record_id"]
                ):
                    raise TransitionError(
                        "successor predecessor is absent or stale"
                    )
                predecessor_open = index.get(
                    "mission-open", boundary["predecessor_mission_id"]
                )
                if predecessor_open is None:
                    raise TransitionError("predecessor Mission open record is absent")
                prior_ordinal = predecessor_open.payload.get("mission_ordinal", 1)
                if type(prior_ordinal) is not int or prior_ordinal < 1:
                    raise TransitionError("predecessor Mission ordinal is invalid")
                mission_ordinal = prior_ordinal + 1
                predecessor = {
                    "continuation_reason": supplied_successor[
                        "continuation_reason"
                    ],
                    "predecessor_basis_record_id": boundary[
                        "predecessor_basis_record_id"
                    ],
                    "predecessor_mission_close_record_id": boundary[
                        "predecessor_mission_close_record_id"
                    ],
                    "predecessor_mission_id": boundary[
                        "predecessor_mission_id"
                    ],
                    "predecessor_outcome": boundary["predecessor_outcome"],
                }
            else:
                raise TransitionError("root-goal predecessor boundary is malformed")
            science["active_mission"] = mission_id
            body["next_action"] = (
                {"kind": "open_initiative", "mission_id": mission_id}
                if self.engineering_fixture
                else {"kind": "record_research_intake", "mission_id": mission_id}
            )
            authorization = self._authorization(
                kind=SubjectKind.MISSION,
                subject_id=mission_id,
                semantic_hash=goal_hash,
            )
            self._bind_authorization(body, authorization)
            project_stream = "project-goal:OPERATING_DIRECTION.md"
            project_head = index.event_head(project_stream)
            project_sequence = 1 if project_head is None else project_head.sequence + 1
            record = _record(
                kind="mission-open",
                record_id=mission_id,
                subject=f"Mission:{mission_id}",
                status="open",
                fingerprint=goal_hash,
                payload={
                    "goal_hash": goal_hash,
                    "goal": goal_manifest,
                    "mission_ordinal": mission_ordinal,
                    "project_goal_authority": body["authority"][
                        "operating_direction"
                    ],
                    "successor_basis": predecessor,
                },
                event_stream=project_stream,
                event_sequence=project_sequence,
            )
            return body, [record], {
                "mission_id": mission_id,
                "mission_ordinal": mission_ordinal,
                "project_goal_complete": False,
            }

        return self._commit(
            event_kind="mission_opened",
            operation_id=operation_id,
            subject=f"Mission:{mission_id}",
            payload={
                "mission_id": mission_id,
                "goal_hash": goal_hash,
                "goal": goal_manifest,
                "successor_basis": supplied_successor,
            },
            prepare=prepare,
        )

    @staticmethod
    def _derive_research_history_summary(index: LocalIndex) -> dict[str, Any]:
        studies = index.records_by_kind("study-open")
        closes = index.records_by_kind("study-close")
        layer_counts: dict[str, int] = {}
        architecture_counts: dict[str, int] = {}
        component_domain_trial_counts: dict[str, int] = {}
        classified_studies = 0
        for study in studies:
            layer = study.payload.get("primary_research_layer")
            architecture = study.payload.get("system_architecture_family")
            if isinstance(layer, str) and isinstance(architecture, str):
                classified_studies += 1
                layer_counts[layer] = layer_counts.get(layer, 0) + 1
                architecture_counts[architecture] = (
                    architecture_counts.get(architecture, 0) + 1
                )
        for trial in index.records_by_kind("trial"):
            executable = trial.payload.get("executable")
            manifests = (
                None
                if not isinstance(executable, dict)
                else executable.get("component_manifests")
            )
            if not isinstance(manifests, list):
                continue
            seen_domains: set[str] = set()
            for manifest in manifests:
                protocol = (
                    None
                    if not isinstance(manifest, dict)
                    else manifest.get("protocol")
                )
                if isinstance(protocol, str) and protocol:
                    seen_domains.add(protocol.split(".", 1)[0])
            for domain in seen_domains:
                component_domain_trial_counts[domain] = (
                    component_domain_trial_counts.get(domain, 0) + 1
                )
        outcome_counts: dict[str, int] = {}
        for close in closes:
            outcome_counts[close.status] = outcome_counts.get(close.status, 0) + 1
        evidence_state_counts: dict[str, int] = {}
        for diagnosis in index.records_by_kind("study-diagnosis"):
            evidence_state_counts[diagnosis.status] = (
                evidence_state_counts.get(diagnosis.status, 0) + 1
            )
        mission_outcomes: dict[str, int] = {}
        for close in index.records_by_kind("mission-close"):
            mission_outcomes[close.status] = mission_outcomes.get(close.status, 0) + 1
        return {
            "candidate_record_count": len(index.records_by_kind("candidate")),
            "architecture_review_count": len(
                index.records_by_kind("architecture-review")
            ),
            "classified_study_count": classified_studies,
            "component_domain_trial_counts": dict(
                sorted(component_domain_trial_counts.items())
            ),
            "legacy_unclassified_study_count": len(studies) - classified_studies,
            "evidence_state_counts": dict(sorted(evidence_state_counts.items())),
            "mission_outcome_counts": dict(sorted(mission_outcomes.items())),
            "negative_memory_count": len(index.records_by_kind("negative-memory")),
            "research_layer_study_counts": dict(sorted(layer_counts.items())),
            "study_count": len(studies),
            "study_kpi_count": len(index.records_by_kind("study-kpi")),
            "study_outcome_counts": dict(sorted(outcome_counts.items())),
            "system_architecture_study_counts": dict(
                sorted(architecture_counts.items())
            ),
            "trial_count": len(index.records_by_kind("trial")),
        }

    def record_research_intake(
        self,
        *,
        intake: Any,
        operation_id: str,
    ) -> TransitionResult:
        from axiom_rift.research.governance import MissionResearchIntake

        self._require_study_close_delivery_guard()
        if self.engineering_fixture:
            raise TransitionError("engineering fixtures do not create research intake")
        if not isinstance(intake, MissionResearchIntake):
            raise TransitionError("intake must be a MissionResearchIntake")

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            science = current["scientific"]
            if (
                science["active_mission"] != intake.mission_id
                or science["active_initiative"] is not None
                or any(
                    science[name] is not None
                    for name in (
                        "active_batch",
                        "active_executable",
                        "active_job",
                        "active_repair",
                        "active_study",
                    )
                )
            ):
                raise TransitionError(
                    "research intake requires one Mission and no subordinate work"
                )
            if current["next_action"] != {
                "kind": "record_research_intake",
                "mission_id": intake.mission_id,
            }:
                raise TransitionError("research intake is not the exact next action")
            journal_head = current.get("heads", {}).get("journal", {})
            if (
                intake.history_head_sequence != current.get("revision")
                or intake.history_head_sequence != journal_head.get("sequence")
                or intake.history_head_event_id != journal_head.get("event_id")
            ):
                raise TransitionError("research intake history head is stale")
            if index.event_head(f"research-intake:{intake.mission_id}") is not None:
                raise TransitionError("Mission research intake already exists")
            history_summary = self._derive_research_history_summary(index)
            mission = index.get("mission-open", intake.mission_id)
            if mission is None:
                raise TransitionError("research intake Mission is unavailable")
            mission_ordinal = mission.payload.get("mission_ordinal")
            if (
                type(mission_ordinal) is not int
                or mission_ordinal < 1
                or (mission_ordinal > 1 and history_summary["study_count"] < 1)
            ):
                raise TransitionError("successor intake lacks predecessor research history")
            payload = {
                **intake.to_identity_payload(),
                "history_summary": history_summary,
                "holdout_reveals": science["holdout_reveals"],
                "mission_ordinal": mission_ordinal,
            }
            body = self._body(current)
            body["next_action"] = {
                "kind": "open_initiative",
                "mission_id": intake.mission_id,
                "research_intake_id": intake.identity,
            }
            record = _record(
                kind="research-intake",
                record_id=intake.identity,
                subject=f"Mission:{intake.mission_id}",
                status="accepted",
                fingerprint=intake.identity.removeprefix("research-intake:"),
                payload=payload,
                event_stream=f"research-intake:{intake.mission_id}",
                event_sequence=1,
            )
            return body, [record], {
                "research_intake_id": intake.identity,
                "history_summary": history_summary,
            }

        return self._commit(
            event_kind="research_intake_recorded",
            operation_id=operation_id,
            subject=f"Mission:{intake.mission_id}",
            payload={"research_intake_id": intake.identity},
            prepare=prepare,
        )

    def activate_research_protocol(
        self,
        *,
        activation: Any,
        operation_id: str,
    ) -> TransitionResult:
        """Activate or rebind the prospective protocol to current authority."""

        from axiom_rift.research.protocol import (
            ResearchProtocol,
            ResearchProtocolActivation,
        )
        from axiom_rift.research.validation_v2 import (
            SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        )

        if not isinstance(activation, ResearchProtocolActivation):
            raise TransitionError("research protocol activation must be typed")
        if (
            activation.protocol
            is not ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2
            or activation.validator_id
            != SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
        ):
            raise TransitionError(
                "research protocol activation does not name the supported v2 validator"
            )
        self.evidence.verify(activation.audit_artifact_hash)
        try:
            self.validation_registry.require_registered(
                validator_id=activation.validator_id,
                domain="scientific",
            )
        except EvidenceValidationError as exc:
            raise TransitionError(
                "research protocol validator is unavailable or drifted"
            ) from exc
        self._require_study_close_delivery_guard()

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("research protocol activation requires control")
            science = current["scientific"]
            if (
                current.get("authority", {}).get("manifest_digest")
                != activation.authority_manifest_digest
            ):
                raise TransitionError(
                    "research protocol activation is bound to another authority"
                )
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
                    "research protocol activation requires the stable Portfolio boundary"
                )
            stream = "research-protocol:scientific"
            prior_head = index.event_head(stream)
            prior = (
                None
                if prior_head is None
                else index.get(prior_head.record_kind, prior_head.record_id)
            )
            if prior_head is not None and (
                prior is None
                or prior.kind != "research-protocol-activation"
                or prior.status != "active"
                or prior.event_sequence != prior_head.sequence
                or prior.payload.get("protocol")
                != ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2.value
                or prior.payload.get("validator_id") != activation.validator_id
            ):
                raise RecoveryRequired(
                    "prospective scientific protocol projection is invalid"
                )
            if (
                prior is not None
                and prior.payload.get("authority_manifest_digest")
                == activation.authority_manifest_digest
            ):
                raise TransitionError(
                    "prospective scientific protocol is already bound to this authority"
                )
            ordinal = 1 if prior_head is None else prior_head.sequence + 1
            record = _record(
                kind="research-protocol-activation",
                record_id=activation.identity,
                subject="ProjectGoal:OPERATING_DIRECTION.md",
                status="active",
                fingerprint=activation.identity.removeprefix(
                    "research-protocol:"
                ),
                payload={
                    **activation.to_identity_payload(),
                    "ordinal": ordinal,
                    "scientific_trial_delta": 0,
                    "supersedes_activation_record_id": (
                        None if prior is None else prior.record_id
                    ),
                },
                event_stream=stream,
                event_sequence=ordinal,
            )
            return self._body(current), [record], {
                "activation_record_id": activation.identity,
                "ordinal": ordinal,
                "protocol": activation.protocol.value,
                "trial_delta": 0,
                "validator_id": activation.validator_id,
            }

        return self._commit(
            event_kind="research_protocol_activated",
            operation_id=operation_id,
            subject="ProjectGoal:OPERATING_DIRECTION.md",
            payload=activation.to_identity_payload(),
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
            portfolio_head = index.event_head(
                f"portfolio:{science['active_mission']}"
            )
            research_intake_id: str | None = None
            if not self.engineering_fixture:
                next_action = current["next_action"]
                if portfolio_head is None:
                    research_intake_id = next_action.get("research_intake_id")
                    intake = (
                        None
                        if not isinstance(research_intake_id, str)
                        else index.get("research-intake", research_intake_id)
                    )
                    if (
                        next_action.get("kind") != "open_initiative"
                        or next_action.get("mission_id") != science["active_mission"]
                        or intake is None
                        or intake.subject != f"Mission:{science['active_mission']}"
                        or intake.status != "accepted"
                    ):
                        raise TransitionError(
                            "first Initiative requires the exact accepted research intake"
                        )
                elif next_action.get("kind") not in {
                    "choose_next_initiative_or_terminal",
                    "open_initiative",
                } or next_action.get("mission_id") != science["active_mission"]:
                    raise TransitionError(
                        "successor Initiative is not the exact Mission boundary"
                    )
            science["active_initiative"] = initiative_id
            if portfolio_head is None:
                body["next_action"] = {
                    "kind": "build_portfolio",
                    "initiative_id": initiative_id,
                }
                if research_intake_id is not None:
                    body["next_action"]["research_intake_id"] = research_intake_id
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
                    "research_intake_id": research_intake_id,
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
            if (
                not self.engineering_fixture
                and body["next_action"].get("kind")
                in {"diagnose_study", "review_architecture"}
            ):
                raise TransitionError(
                    "Initiative close cannot bypass research diagnosis or review"
                )
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
    def _portfolio_decision_withdrawal(
        index: LocalIndex,
        decision_id: str,
    ) -> IndexRecord | None:
        stream = f"portfolio-decision-status:{decision_id}"
        head = index.event_head(stream)
        if head is None:
            return None
        record = index.get(head.record_kind, head.record_id)
        if (
            record is None
            or record.kind != "portfolio-decision-withdrawal"
            or record.status != "withdrawn_pre_execution"
            or record.event_stream != stream
            or record.event_sequence != 1
            or head.sequence != 1
            or record.payload.get("decision_id") != decision_id
        ):
            raise RecoveryRequired(
                "Portfolio Decision withdrawal status projection is invalid"
            )
        return record

    @staticmethod
    def _active_portfolio_decision(
        index: LocalIndex,
        decision_id: str,
    ) -> IndexRecord | None:
        decision = index.get("portfolio-decision", decision_id)
        withdrawal = StateWriter._portfolio_decision_withdrawal(index, decision_id)
        if withdrawal is None:
            return decision
        if (
            decision is None
            or withdrawal.subject != decision.subject
            or withdrawal.fingerprint != decision.fingerprint
        ):
            raise RecoveryRequired(
                "withdrawn Portfolio Decision lost its accepted provenance"
            )
        return None

    @staticmethod
    def _axis_architecture_anchor(
        index: LocalIndex,
        axis: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        typed_identity = axis.get("architecture_chassis_identity")
        typed_payload = axis.get("architecture_chassis")
        if isinstance(typed_identity, str):
            if not isinstance(typed_payload, dict):
                raise RecoveryRequired("typed Portfolio axis chassis is malformed")
            return {
                "architecture_chassis": dict(typed_payload),
                "architecture_chassis_identity": typed_identity,
                "baseline_executable": None,
                "baseline_executable_id": None,
            }
        axis_identity = axis.get("axis_identity")
        anchors: dict[tuple[str, str], dict[str, Any]] = {}
        for record in index.records_by_kind("portfolio-decision"):
            if StateWriter._active_portfolio_decision(index, record.record_id) is None:
                continue
            payload = record.payload
            architecture_identity = payload.get("architecture_chassis_identity")
            baseline_id = payload.get("baseline_executable_id")
            if (
                payload.get("target_axis_identity") != axis_identity
                or not isinstance(architecture_identity, str)
                or not isinstance(baseline_id, str)
            ):
                continue
            anchor = {
                "architecture_chassis": payload.get("architecture_chassis"),
                "architecture_chassis_identity": architecture_identity,
                "baseline_executable": payload.get("baseline_executable"),
                "baseline_executable_id": baseline_id,
            }
            anchors[(architecture_identity, baseline_id)] = anchor
        if len(anchors) > 1:
            raise RecoveryRequired(
                "legacy Portfolio axis has conflicting prospective chassis anchors"
            )
        return None if not anchors else next(iter(anchors.values()))

    def _require_registered_chassis_baseline(
        self,
        *,
        index: LocalIndex,
        controlled_chassis: Any,
        decision: IndexRecord,
    ) -> None:
        baseline = controlled_chassis.baseline_executable
        baseline_payload = baseline.to_identity_payload()
        provenance = decision.payload.get("baseline_provenance")
        if (
            decision.payload.get("baseline_executable_id") != baseline.identity
            or decision.payload.get("baseline_executable") != baseline_payload
            or not isinstance(provenance, dict)
        ):
            raise TransitionError(
                "controlled chassis baseline differs from its accepted Decision"
            )
        target_axis_identity = decision.payload.get("target_axis_identity")
        prior = self._prior_scientific_baseline(
            index,
            baseline,
            portfolio_axis_identity=(
                target_axis_identity
                if isinstance(target_axis_identity, str)
                else None
            ),
        )
        if provenance.get("kind") == "trial":
            if prior is None or provenance.get("record_id") != prior.record_id:
                raise TransitionError(
                    "controlled chassis baseline lost its prior scientific trial"
                )
        elif provenance.get("kind") == "controlled_chassis_anchor_reuse":
            anchor_id = provenance.get("record_id")
            anchor = (
                None
                if not isinstance(anchor_id, str)
                else self._active_portfolio_decision(index, anchor_id)
            )
            if (
                prior is not None
                or anchor is None
                or anchor.payload.get("baseline_executable_id") != baseline.identity
                or anchor.payload.get("baseline_executable") != baseline_payload
                or not isinstance(anchor.payload.get("baseline_provenance"), dict)
                or anchor.payload["baseline_provenance"].get("kind")
                not in {
                    "first_controlled_chassis_bootstrap",
                    "first_axis_controlled_chassis_bootstrap",
                }
            ):
                raise TransitionError(
                    "controlled chassis bootstrap anchor reuse is invalid"
                )
        else:
            relevant_trials = [
                record
                for record in index.records_by_kind("trial")
                if isinstance(record.payload.get("executable"), dict)
                and record.payload["executable"].get("data_contract")
                == baseline.data_contract
            ]
            controlled_history = [
                record
                for record in index.records_by_kind("study-open")
                if isinstance(record.payload.get("controlled_chassis"), dict)
                and isinstance(
                    record.payload["controlled_chassis"].get(
                        "baseline_executable"
                    ),
                    dict,
                )
                and record.payload["controlled_chassis"][
                    "baseline_executable"
                ].get("data_contract")
                == baseline.data_contract
            ]
            axis_controlled_history = [
                record
                for record in controlled_history
                if record.payload.get("portfolio_axis_identity")
                == target_axis_identity
            ]
            expected_bootstrap = (
                {
                    "data_contract": baseline.data_contract,
                    "kind": "first_axis_controlled_chassis_bootstrap",
                    "portfolio_axis_identity": target_axis_identity,
                }
                if relevant_trials
                and controlled_history
                and not axis_controlled_history
                else {
                    "data_contract": baseline.data_contract,
                    "kind": (
                        "first_controlled_chassis_bootstrap"
                        if relevant_trials
                        else "first_data_contract_bootstrap"
                    ),
                }
            )
            if (
                provenance != expected_bootstrap
                or prior is not None
                or (
                    relevant_trials
                    and axis_controlled_history
                    and provenance.get("kind")
                    != "controlled_chassis_anchor_reuse"
                )
            ):
                raise TransitionError(
                    "controlled chassis baseline bootstrap is no longer valid"
                )
        for component, component_id in zip(
            baseline.components, baseline.component_identities, strict=True
        ):
            expected = self._component_manifest_record(
                component_id=component_id,
                manifest=component.to_identity_payload(),
            )
            existing = index.get("component-manifest", component_id)
            if existing is None:
                raise TransitionError(
                    "controlled chassis baseline component is not registered"
                )
            self._require_component_manifest_projection(index, expected)

    @staticmethod
    def _prior_scientific_baseline(
        index: LocalIndex,
        baseline: Any,
        portfolio_axis_identity: str | None = None,
    ) -> IndexRecord | None:
        baseline_payload = baseline.to_identity_payload()
        relevant = [
            record
            for record in index.records_by_kind("trial")
            if isinstance(record.payload.get("executable"), dict)
            and record.payload["executable"].get("data_contract")
            == baseline.data_contract
        ]
        exact = index.get("trial", baseline.identity)
        if not relevant:
            return None
        if exact is None:
            accepted_bootstrap_anchors = [
                record
                for record in index.records_by_kind("portfolio-decision")
                if StateWriter._active_portfolio_decision(index, record.record_id)
                is not None
                and record.payload.get("baseline_executable_id") == baseline.identity
                and record.payload.get("baseline_executable") == baseline_payload
                and isinstance(record.payload.get("baseline_provenance"), dict)
                and record.payload["baseline_provenance"].get("kind")
                in {
                    "first_controlled_chassis_bootstrap",
                    "first_axis_controlled_chassis_bootstrap",
                }
                and (
                    portfolio_axis_identity is None
                    or record.payload.get("target_axis_identity")
                    == portfolio_axis_identity
                )
            ]
            controlled_history = [
                record
                for record in index.records_by_kind("study-open")
                if isinstance(record.payload.get("controlled_chassis"), dict)
                and isinstance(
                    record.payload["controlled_chassis"].get(
                        "baseline_executable"
                    ),
                    dict,
                )
                and record.payload["controlled_chassis"][
                    "baseline_executable"
                ].get("data_contract")
                == baseline.data_contract
                and (
                    portfolio_axis_identity is None
                    or record.payload.get("portfolio_axis_identity")
                    == portfolio_axis_identity
                )
            ]
            if not controlled_history or accepted_bootstrap_anchors:
                return None
        study_id = None if exact is None else exact.payload.get("study_id")
        study = (
            None
            if not isinstance(study_id, str)
            else index.get("study-open", study_id)
        )
        if (
            exact is None
            or exact.status != "evaluated"
            or exact.fingerprint != baseline.identity.removeprefix("executable:")
            or exact.payload.get("scientific_eligible") is not True
            or exact.payload.get("engineering_fixture") is not False
            or exact.payload.get("executable") != baseline_payload
            or study is None
            or exact.payload.get("mission_id") != study.payload.get("mission_id")
        ):
            raise TransitionError(
                "Portfolio Decision baseline must reuse a prior scientific Executable"
            )
        return exact

    def _require_component_parity_payload(
        self,
        *,
        index: LocalIndex,
        equivalence: Mapping[str, Any],
        mission_id: str,
        portfolio_decision_id: str | None,
    ) -> None:
        completion_id = equivalence.get("completion_record_id")
        parity_manifest_hash = equivalence.get("parity_manifest_hash")
        try:
            _require_digest("component parity completion", completion_id)
            _require_digest("component parity manifest", parity_manifest_hash)
        except (TypeError, ValueError) as exc:
            raise TransitionError("component parity authority is malformed") from exc
        completion = index.get("job-completed", completion_id)
        if completion is None or completion.status != "success":
            raise TransitionError(
                "component parity requires a successful registered-validator Job completion"
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
            else declaration.payload.get("spec", {}).get("component_parity_binding")
        )
        parity = completion.payload.get("component_parity")
        expected = {
            "canonical_component_id": equivalence.get("canonical_component_id"),
            "canonical_component_manifest": equivalence.get(
                "canonical_component_manifest"
            ),
            "dimensions": equivalence.get("dimensions"),
            "equivalent_component_id": equivalence.get("equivalent_component_id"),
            "equivalent_component_manifest": equivalence.get(
                "equivalent_component_manifest"
            ),
        }
        if (
            declaration is None
            or declaration.fingerprint != completion.fingerprint
            or declaration.payload.get("mission_id") != mission_id
            or not isinstance(binding, dict)
            or (
                portfolio_decision_id is not None
                and binding.get("portfolio_decision_id") != portfolio_decision_id
            )
            or any(binding.get(name) != value for name, value in expected.items())
            or not isinstance(parity, dict)
            or parity.get("equivalent") is not True
            or parity.get("result_manifest_hash") != parity_manifest_hash
            or any(parity.get(name) != value for name, value in expected.items())
        ):
            raise TransitionError(
                "component parity completion differs from its typed endpoints"
            )
        trace = parity.get("validation_trace")
        measurement_hashes = parity.get("measurement_artifact_hashes")
        if (
            not isinstance(trace, dict)
            or trace.get("validator_id") != binding.get("validator_id")
            or type(trace.get("declared_artifact_count")) is not int
            or trace.get("declared_artifact_count", 0) <= 0
            or trace.get("declared_artifact_count")
            != trace.get("opened_artifact_count")
            or not isinstance(measurement_hashes, list)
            or not measurement_hashes
        ):
            raise TransitionError(
                "component parity lacks a complete registered-validator trace"
            )
        decisions = index.records_by_subject_status(
            subject=f"Job:{job_id}", status="accept_component_parity"
        )
        if not any(
            record.payload.get("completion_record_id") == completion_id
            for record in decisions
        ):
            raise TransitionError("component parity Job has not been accepted by Writer")
        for artifact_hash in [parity_manifest_hash, *measurement_hashes]:
            try:
                self.evidence.verify(artifact_hash)
            except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                raise TransitionError(
                    "component parity evidence bytes are unavailable"
                ) from exc

    def _require_component_parity_evidence(
        self,
        *,
        index: LocalIndex,
        controlled_chassis: Any,
        mission_id: str,
        portfolio_decision_id: str,
    ) -> None:
        """Verify every equivalence through Writer-accepted validator completions."""

        from axiom_rift.research.chassis import ControlledStudyChassis

        if not isinstance(controlled_chassis, ControlledStudyChassis):
            raise TransitionError("controlled component chassis is not typed")
        for equivalence in controlled_chassis.equivalences:
            self._require_component_parity_payload(
                index=index,
                equivalence=equivalence.to_identity_payload(),
                mission_id=mission_id,
                portfolio_decision_id=portfolio_decision_id,
            )

    @staticmethod
    def _component_parity_member_records(
        *,
        equivalence: Mapping[str, Any],
        mission_id: str,
        portfolio_decision_id: str,
    ) -> list[IndexRecord]:
        from axiom_rift.research.chassis import (
            ChassisIdentityError,
            architecture_component_semantic_surface_identity,
            component_semantic_surface_identity,
        )

        canonical_id = equivalence.get("canonical_component_id")
        equivalent_id = equivalence.get("equivalent_component_id")
        if not isinstance(canonical_id, str) or not isinstance(equivalent_id, str):
            raise TransitionError("component parity endpoints are malformed")
        edge_id = canonical_digest(
            domain="component-parity-edge",
            payload={
                "component_ids": sorted((canonical_id, equivalent_id)),
                "schema": "component_parity_edge.v1",
            },
        )
        records: list[IndexRecord] = []
        for endpoint, peer, prefix in (
            (canonical_id, equivalent_id, "canonical"),
            (equivalent_id, canonical_id, "equivalent"),
        ):
            manifest = equivalence.get(f"{prefix}_component_manifest")
            if not isinstance(manifest, Mapping):
                raise TransitionError("component parity endpoint manifest is malformed")
            try:
                surface = architecture_component_semantic_surface_identity(manifest)
            except ChassisIdentityError as exc:
                if "outside the prediction-to-position" not in str(exc):
                    raise TransitionError(str(exc)) from exc
                surface = component_semantic_surface_identity(manifest)
            record_id = canonical_digest(
                domain="component-parity-member",
                payload={
                    "completion_record_id": equivalence.get(
                        "completion_record_id"
                    ),
                    "edge_id": edge_id,
                    "endpoint_id": endpoint,
                    "schema": "component_parity_member.v1",
                },
            )
            records.append(
                _record(
                    kind="component-parity-member",
                    record_id=record_id,
                    subject=f"Component:{endpoint}",
                    status="equivalent",
                    fingerprint=surface,
                    payload={
                        "edge_id": edge_id,
                        "endpoint_id": endpoint,
                        "equivalence": dict(equivalence),
                        "mission_id": mission_id,
                        "peer_component_id": peer,
                        "portfolio_decision_id": portfolio_decision_id,
                        "schema": "component_parity_member_projection.v1",
                    },
                )
            )
        return records

    def _verified_component_parity_edges(
        self,
        index: LocalIndex,
        *,
        surface_seeds: tuple[str, ...] = (),
        component_seeds: tuple[str, ...] = (),
    ) -> tuple[dict[str, Any], ...]:
        """Re-verify every durable Writer-accepted parity edge from exact bytes."""

        edges: dict[tuple[str, str], dict[str, Any]] = {}
        if surface_seeds or component_seeds:
            members_by_id: dict[str, IndexRecord] = {}
            pending_surfaces = list(dict.fromkeys(surface_seeds))
            pending_components = list(dict.fromkeys(component_seeds))
            seen_surfaces: set[str] = set()
            seen_components: set[str] = set()
            while pending_surfaces or pending_components:
                if pending_surfaces:
                    surface = pending_surfaces.pop()
                    if surface in seen_surfaces:
                        continue
                    seen_surfaces.add(surface)
                    candidates = index.records_by_fingerprint(surface)
                else:
                    component_id = pending_components.pop()
                    if component_id in seen_components:
                        continue
                    seen_components.add(component_id)
                    candidates = index.records_by_subject_status(
                        subject=f"Component:{component_id}",
                        status="equivalent",
                    )
                for candidate in candidates:
                    if candidate.kind != "component-parity-member":
                        continue
                    members_by_id[candidate.record_id] = candidate
                    equivalence = candidate.payload.get("equivalence")
                    if not isinstance(equivalence, dict):
                        raise RecoveryRequired(
                            "accepted component parity member is malformed"
                        )
                    for name in (
                        "canonical_component_id",
                        "equivalent_component_id",
                    ):
                        value = equivalence.get(name)
                        if isinstance(value, str) and value not in seen_components:
                            pending_components.append(value)
            members = tuple(members_by_id.values())
        else:
            members = index.records_by_kind("component-parity-member")
        for member in members:
            equivalence = member.payload.get("equivalence")
            mission_id = member.payload.get("mission_id")
            portfolio_decision_id = member.payload.get("portfolio_decision_id")
            if (
                member.status != "equivalent"
                or member.payload.get("schema")
                != "component_parity_member_projection.v1"
                or not isinstance(equivalence, dict)
                or not isinstance(mission_id, str)
                or not isinstance(portfolio_decision_id, str)
            ):
                raise RecoveryRequired("accepted component parity member is malformed")
            self._require_component_parity_payload(
                index=index,
                equivalence=equivalence,
                mission_id=mission_id,
                portfolio_decision_id=portfolio_decision_id,
            )
            endpoints = (
                equivalence["canonical_component_id"],
                equivalence["equivalent_component_id"],
            )
            if any(not isinstance(value, str) for value in endpoints):
                raise RecoveryRequired("accepted component parity endpoints are malformed")
            key = tuple(sorted(endpoints))
            prior = edges.get(key)
            if prior is not None and (
                prior["canonical_component_manifest"]
                != equivalence["canonical_component_manifest"]
                or prior["equivalent_component_manifest"]
                != equivalence["equivalent_component_manifest"]
            ):
                prior_by_id = {
                    prior["canonical_component_id"]: prior[
                        "canonical_component_manifest"
                    ],
                    prior["equivalent_component_id"]: prior[
                        "equivalent_component_manifest"
                    ],
                }
                current_by_id = {
                    equivalence["canonical_component_id"]: equivalence[
                        "canonical_component_manifest"
                    ],
                    equivalence["equivalent_component_id"]: equivalence[
                        "equivalent_component_manifest"
                    ],
                }
                if prior_by_id != current_by_id:
                    raise RecoveryRequired(
                        "accepted component parity endpoints conflict"
                    )
            edges[key] = equivalence
        return tuple(edges[key] for key in sorted(edges))

    @staticmethod
    def _architecture_parity_surface_replacements(
        equivalences: tuple[Mapping[str, Any], ...],
    ) -> dict[str, str]:
        from axiom_rift.research.chassis import (
            ChassisIdentityError,
            architecture_component_semantic_surface_identity,
        )

        parents: dict[str, str] = {}
        manifests: dict[str, Mapping[str, Any]] = {}

        def find(component_id: str) -> str:
            parent = parents.setdefault(component_id, component_id)
            if parent != component_id:
                parents[component_id] = find(parent)
            return parents[component_id]

        def union(left_id: str, right_id: str) -> None:
            left_root = find(left_id)
            right_root = find(right_id)
            if left_root == right_root:
                return
            low, high = sorted((left_root, right_root))
            parents[high] = low

        for equivalence in equivalences:
            endpoint_values = []
            for prefix in ("canonical", "equivalent"):
                component_id = equivalence.get(f"{prefix}_component_id")
                manifest = equivalence.get(f"{prefix}_component_manifest")
                if not isinstance(component_id, str) or not isinstance(manifest, Mapping):
                    raise RecoveryRequired("accepted parity endpoint is malformed")
                expected_id = "component:" + canonical_digest(
                    domain="component", payload=dict(manifest)
                )
                if component_id != expected_id:
                    raise RecoveryRequired(
                        "accepted parity endpoint differs from its manifest"
                    )
                prior = manifests.get(component_id)
                if prior is not None and dict(prior) != dict(manifest):
                    raise RecoveryRequired("accepted parity manifest collision")
                manifests[component_id] = manifest
                endpoint_values.append(component_id)
            union(endpoint_values[0], endpoint_values[1])

        surface_owners: dict[str, str] = {}
        for component_id, manifest in manifests.items():
            try:
                surface = architecture_component_semantic_surface_identity(
                    manifest
                )
            except ChassisIdentityError as exc:
                if "outside the prediction-to-position" in str(exc):
                    continue
                raise RecoveryRequired(str(exc)) from exc
            owner = surface_owners.get(surface)
            if owner is None:
                surface_owners[surface] = component_id
            else:
                union(owner, component_id)

        classes: dict[str, list[str]] = {}
        for component_id in parents:
            classes.setdefault(find(component_id), []).append(component_id)
        replacements: dict[str, str] = {}
        for members in classes.values():
            normalized_members = sorted(members)
            class_surface = "architecture-equivalence-class:" + canonical_digest(
                domain="architecture-equivalence-class",
                payload={
                    "component_ids": normalized_members,
                    "schema": "architecture_equivalence_class.v1",
                },
            )
            for component_id in normalized_members:
                try:
                    surface = architecture_component_semantic_surface_identity(
                        manifests[component_id]
                    )
                except ChassisIdentityError as exc:
                    if "outside the prediction-to-position" in str(exc):
                        continue
                    raise RecoveryRequired(str(exc)) from exc
                prior = replacements.get(surface)
                if prior is not None and prior != class_surface:
                    raise RecoveryRequired(
                        "accepted parity architecture classes conflict"
                    )
                replacements[surface] = class_surface
        return replacements

    def _resolved_architecture_family(
        self,
        *,
        index: LocalIndex,
        architecture_payload: Mapping[str, Any],
        extra_equivalences: tuple[Mapping[str, Any], ...] = (),
    ) -> str:
        from axiom_rift.research.chassis import (
            ChassisIdentityError,
            architecture_family_identity,
        )

        roles = architecture_payload.get("roles")
        if not isinstance(roles, Mapping):
            raise TransitionError("architecture chassis roles are malformed")
        surface_seeds = tuple(
            sorted(
                {
                    surface
                    for role in roles.values()
                    if isinstance(role, Mapping)
                    for surface in role.get("component_semantic_surfaces", [])
                    if isinstance(surface, str)
                }
            )
        )
        cache = getattr(index, "_axiom_verified_parity_cache", None)
        if cache is None:
            cache = {}
            setattr(index, "_axiom_verified_parity_cache", cache)
        verified = cache.get(surface_seeds)
        if verified is None:
            verified = self._verified_component_parity_edges(
                index,
                surface_seeds=surface_seeds,
            )
            cache[surface_seeds] = verified
        equivalences = (
            *verified,
            *extra_equivalences,
        )
        replacements = self._architecture_parity_surface_replacements(
            tuple(equivalences)
        )
        try:
            return architecture_family_identity(
                architecture_payload,
                surface_replacements=replacements,
            )
        except ChassisIdentityError as exc:
            raise TransitionError(str(exc)) from exc

    def _study_resolved_architecture_family(
        self,
        *,
        index: LocalIndex,
        study: IndexRecord,
        extra_equivalences: tuple[Mapping[str, Any], ...] = (),
    ) -> str:
        controlled = study.payload.get("controlled_chassis")
        architecture = (
            None if not isinstance(controlled, dict) else controlled.get("architecture")
        )
        if isinstance(architecture, dict):
            return self._resolved_architecture_family(
                index=index,
                architecture_payload=architecture,
                extra_equivalences=extra_equivalences,
            )
        legacy = study.payload.get("system_architecture_family")
        if not isinstance(legacy, str):
            raise TransitionError("Study lacks a system architecture family")
        return legacy

    def _review_resolved_architecture_family(
        self,
        *,
        index: LocalIndex,
        review: IndexRecord,
        extra_equivalences: tuple[Mapping[str, Any], ...] = (),
    ) -> str:
        families: set[str] = set()
        for diagnosis_id in review.payload.get("covered_diagnosis_ids", []):
            if not isinstance(diagnosis_id, str):
                raise RecoveryRequired("architecture review diagnosis binding is malformed")
            diagnosis = index.get("study-diagnosis", diagnosis_id)
            study_id = None if diagnosis is None else diagnosis.payload.get("study_id")
            study = (
                None
                if not isinstance(study_id, str)
                else index.get("study-open", study_id)
            )
            if study is None:
                raise RecoveryRequired(
                    "architecture review lost a covered Study diagnosis"
                )
            controlled = study.payload.get("controlled_chassis")
            architecture = (
                None
                if not isinstance(controlled, dict)
                else controlled.get("architecture")
            )
            if isinstance(architecture, dict):
                families.add(
                    self._resolved_architecture_family(
                        index=index,
                        architecture_payload=architecture,
                        extra_equivalences=extra_equivalences,
                    )
                )
            else:
                legacy = study.payload.get("system_architecture_family")
                if not isinstance(legacy, str):
                    raise RecoveryRequired(
                        "architecture review Study family is unavailable"
                    )
                families.add(legacy)
        if len(families) > 1:
            raise RecoveryRequired(
                "architecture review covered Studies no longer share one family"
            )
        if families:
            return next(iter(families))
        stored = review.payload.get("system_architecture_family")
        if not isinstance(stored, str):
            raise RecoveryRequired("architecture review family is unavailable")
        return stored

    def _pending_architecture_review_trigger(
        self,
        *,
        index: LocalIndex,
        mission_id: str,
        portfolio_snapshot_id: str,
        architecture_family: str,
        extra_equivalences: tuple[Mapping[str, Any], ...] = (),
    ) -> IndexRecord | None:
        snapshot = index.get("portfolio-snapshot", portfolio_snapshot_id)
        standard = (
            None if snapshot is None else snapshot.payload.get("exhaustion_standard")
        )
        if not isinstance(standard, dict):
            return None
        minimum_studies = standard.get("architecture_review_minimum_studies")
        minimum_axes = standard.get("architecture_review_minimum_axes")
        if type(minimum_studies) is not int or type(minimum_axes) is not int:
            raise RecoveryRequired("architecture review threshold is malformed")
        reviewed_ids: set[str] = set()
        for review in index.records_by_kind("architecture-review"):
            if review.payload.get("mission_id") == mission_id:
                reviewed_ids.update(
                    value
                    for value in review.payload.get("covered_diagnosis_ids", [])
                    if isinstance(value, str)
                )
        diagnoses: list[IndexRecord] = []
        for diagnosis in index.records_by_kind("study-diagnosis"):
            if (
                diagnosis.payload.get("mission_id") != mission_id
                or diagnosis.record_id in reviewed_ids
                or diagnosis.payload.get("evidence_state")
                in {"engineering_gap", "supported_requires_confirmation"}
            ):
                continue
            study_id = diagnosis.payload.get("study_id")
            study = (
                None
                if not isinstance(study_id, str)
                else index.get("study-open", study_id)
            )
            if study is None:
                raise RecoveryRequired(
                    "architecture review diagnosis lost its Study"
                )
            if (
                self._study_resolved_architecture_family(
                    index=index,
                    study=study,
                    extra_equivalences=extra_equivalences,
                )
                == architecture_family
            ):
                diagnoses.append(diagnosis)
        axis_ids = {
            diagnosis.payload.get("portfolio_axis_id") for diagnosis in diagnoses
        }
        if (
            len(diagnoses) < minimum_studies
            or len(axis_ids) < minimum_axes
            or None in axis_ids
        ):
            return None
        trigger_payload = {
            "diagnosis_ids": sorted(
                diagnosis.record_id for diagnosis in diagnoses
            ),
            "mission_id": mission_id,
            "portfolio_axis_ids": sorted(axis_ids),
            "portfolio_snapshot_id": portfolio_snapshot_id,
            "primary_research_layers": sorted(
                {
                    diagnosis.payload["primary_research_layer"]
                    for diagnosis in diagnoses
                }
            ),
            "schema": "architecture_review_trigger.v1",
            "system_architecture_family": architecture_family,
            "threshold": {
                "minimum_distinct_axes": minimum_axes,
                "minimum_studies": minimum_studies,
            },
        }
        trigger_id = canonical_digest(
            domain="architecture-review-trigger",
            payload=trigger_payload,
        )
        return _record(
            kind="architecture-review-trigger",
            record_id=trigger_id,
            subject=f"Mission:{mission_id}",
            status="required",
            fingerprint=trigger_id,
            payload=trigger_payload,
        )

    @staticmethod
    def study_input_hash(
        *,
        question: Mapping[str, Any],
        material_identity: str,
        semantic_proposal: Mapping[str, Any],
        controlled_chassis: Any | None = None,
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
        from axiom_rift.research.chassis import ControlledStudyChassis

        if controlled_chassis is not None and not isinstance(
            controlled_chassis, ControlledStudyChassis
        ):
            raise TransitionError("controlled_chassis must be a ControlledStudyChassis")
        return _digest(
            {
                "controlled_chassis": (
                    None
                    if controlled_chassis is None
                    else controlled_chassis.to_identity_payload()
                ),
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
        controlled_chassis: Any | None = None,
        permit: Permit,
        operation_id: str,
        portfolio_axis_id: str | None = None,
        portfolio_axis_identity: str | None = None,
        portfolio_decision_id: str | None = None,
    ) -> TransitionResult:
        self._require_study_close_delivery_guard()
        try:
            validate_study_id(study_id)
        except ValueError as exc:
            raise TransitionError("study_id is invalid") from exc
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
        from axiom_rift.research.chassis import ControlledStudyChassis

        if controlled_chassis is not None and not isinstance(
            controlled_chassis, ControlledStudyChassis
        ):
            raise TransitionError("controlled_chassis must be a ControlledStudyChassis")
        if not self.engineering_fixture and controlled_chassis is None:
            raise TransitionError(
                "scientific Study requires a typed controlled component chassis"
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
            controlled_chassis=controlled_chassis,
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
            primary_research_layer: str | None = None
            system_architecture_family: str | None = None
            changed_domains: list[str] | None = None
            controlled_domains: list[str] | None = None
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
                decision = self._active_portfolio_decision(
                    _index, portfolio_decision_id
                )
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
                primary_research_layer = axis["primary_research_layer"]
                system_architecture_family = axis["system_architecture_family"]
                changed_domains = list(axis["changed_domains"])
                controlled_domains = list(axis["controlled_domains"])
                portfolio_action = chosen["action"]
                commitment_batches = decision.payload["commitment_batches"]
                assert controlled_chassis is not None
                if [domain.value for domain in controlled_chassis.changed_domains] != sorted(
                    changed_domains
                ):
                    raise TransitionError(
                        "Study changed component domains differ from its Portfolio axis"
                    )
                if [domain.value for domain in controlled_chassis.controlled_domains] != sorted(
                    controlled_domains
                ):
                    raise TransitionError(
                        "Study controlled component domains differ from its Portfolio axis"
                    )
                typed_axis_chassis = axis.get("architecture_chassis_identity")
                typed_axis_payload = axis.get("architecture_chassis")
                accepted_architecture = next_action.get(
                    "architecture_chassis_identity"
                )
                accepted_resolved_family = next_action.get(
                    "resolved_architecture_family"
                )
                accepted_baseline = next_action.get("baseline_executable_id")
                resolved_controlled_family = self._resolved_architecture_family(
                    index=_index,
                    architecture_payload=controlled_chassis.architecture.to_identity_payload(),
                )
                resolved_axis_family = (
                    None
                    if not isinstance(typed_axis_chassis, str)
                    else self._resolved_architecture_family(
                        index=_index,
                        architecture_payload=typed_axis_payload,
                    )
                    if isinstance(typed_axis_payload, dict)
                    else None
                )
                if (
                    not isinstance(accepted_architecture, str)
                    or not isinstance(accepted_resolved_family, str)
                    or not isinstance(accepted_baseline, str)
                    or accepted_architecture
                    != decision.payload.get("architecture_chassis_identity")
                    or decision.payload.get("architecture_chassis")
                    != controlled_chassis.architecture.to_identity_payload()
                    or accepted_baseline
                    != decision.payload.get("baseline_executable_id")
                    or accepted_architecture
                    != controlled_chassis.architecture.identity
                    or accepted_baseline
                    != controlled_chassis.baseline_executable.identity
                    or accepted_resolved_family != resolved_controlled_family
                    or (
                        isinstance(typed_axis_chassis, str)
                        and resolved_axis_family != resolved_controlled_family
                    )
                ):
                    raise TransitionError(
                        "Study chassis differs from its accepted Portfolio Decision anchor"
                    )
                self._require_registered_chassis_baseline(
                    index=_index,
                    controlled_chassis=controlled_chassis,
                    decision=decision,
                )
                self._require_component_parity_evidence(
                    index=_index,
                    controlled_chassis=controlled_chassis,
                    mission_id=science["active_mission"],
                    portfolio_decision_id=portfolio_decision_id,
                )
                required_study_scope = {
                    "study",
                    f"decision:{portfolio_decision_id}",
                    f"axis:{portfolio_axis_identity}",
                    f"baseline:{accepted_baseline}",
                    f"chassis:{accepted_architecture}",
                    f"snapshot:{portfolio_snapshot_id}",
                }
                if not required_study_scope.issubset(permit.scope):
                    raise TransitionError(
                        "StudyPermit does not bind the accepted Portfolio Decision"
                    )
                system_architecture_family = resolved_controlled_family
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
                    "primary_research_layer": primary_research_layer,
                    "system_architecture_family": system_architecture_family,
                    "portfolio_architecture_family": axis[
                        "system_architecture_family"
                    ] if not self.engineering_fixture else None,
                    "controlled_chassis": (
                        None
                        if controlled_chassis is None
                        else controlled_chassis.to_identity_payload()
                    ),
                    "controlled_chassis_identity": (
                        None
                        if controlled_chassis is None
                        else controlled_chassis.controlled_chassis_identity
                    ),
                    "changed_domains": changed_domains,
                    "controlled_domains": controlled_domains,
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
                "controlled_chassis_identity": (
                    None
                    if controlled_chassis is None
                    else controlled_chassis.controlled_chassis_identity
                ),
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

    def study_chassis_combination_identity(
        self,
        *,
        left_study_id: str,
        right_study_id: str,
        shared_domains: tuple[Any, ...],
    ) -> str:
        """Prove cross-Study chassis compatibility from stored Writer authority."""

        validate_study_id(left_study_id)
        validate_study_id(right_study_id)
        from axiom_rift.research.chassis import (
            ChassisIdentityError,
            combine_control_payloads,
        )
        from axiom_rift.research.governance import ResearchLayer

        if type(shared_domains) is not tuple or not shared_domains or any(
            not isinstance(domain, ResearchLayer) for domain in shared_domains
        ):
            raise TransitionError("shared chassis domains are not typed")
        with WriterLock(self.lock_path):
            with self._open_authoritative_index() as index:
                self._require_stable_locked(index)
                studies = [
                    index.get("study-open", study_id)
                    for study_id in (left_study_id, right_study_id)
                ]
                if any(study is None for study in studies):
                    raise TransitionError(
                        "cross-Study chassis proof requires registered Studies"
                    )
                payloads: list[Mapping[str, Any]] = []
                for study in studies:
                    assert study is not None
                    payload = study.payload.get("controlled_chassis")
                    mission_id = study.payload.get("mission_id")
                    decision_id = study.payload.get("portfolio_decision_id")
                    if (
                        not isinstance(payload, dict)
                        or not isinstance(mission_id, str)
                        or not isinstance(decision_id, str)
                    ):
                        raise TransitionError(
                            "Study lacks a Writer-bound controlled chassis"
                        )
                    equivalences = payload.get("equivalences")
                    if not isinstance(equivalences, list):
                        raise TransitionError(
                            "Study component equivalences are malformed"
                        )
                    for equivalence in equivalences:
                        if not isinstance(equivalence, dict):
                            raise TransitionError(
                                "Study component equivalence is malformed"
                            )
                        self._require_component_parity_payload(
                            index=index,
                            equivalence=equivalence,
                            mission_id=mission_id,
                            portfolio_decision_id=decision_id,
                        )
                    payloads.append(payload)
                surface_seeds: set[str] = set()
                component_seeds: set[str] = set()
                for payload in payloads:
                    architecture = payload.get("architecture")
                    roles = (
                        None
                        if not isinstance(architecture, dict)
                        else architecture.get("roles")
                    )
                    if not isinstance(roles, dict):
                        raise TransitionError(
                            "Study architecture roles are malformed"
                        )
                    for role in roles.values():
                        surfaces = (
                            None
                            if not isinstance(role, dict)
                            else role.get("component_semantic_surfaces")
                        )
                        if not isinstance(surfaces, list):
                            raise TransitionError(
                                "Study architecture surfaces are malformed"
                            )
                        surface_seeds.update(
                            value for value in surfaces if isinstance(value, str)
                        )
                    components = payload.get("controlled_component_identities")
                    if not isinstance(components, dict):
                        raise TransitionError(
                            "Study controlled component identities are malformed"
                        )
                    for domain in shared_domains:
                        values = components.get(domain.value)
                        if not isinstance(values, list):
                            raise TransitionError(
                                "Study shared controlled domain is malformed"
                            )
                        component_seeds.update(
                            value for value in values if isinstance(value, str)
                        )
                try:
                    return combine_control_payloads(
                        payloads[0],
                        payloads[1],
                        shared_domains=shared_domains,
                        verified_equivalences=self._verified_component_parity_edges(
                            index,
                            surface_seeds=tuple(sorted(surface_seeds)),
                            component_seeds=tuple(sorted(component_seeds)),
                        ),
                    )
                except ChassisIdentityError as exc:
                    raise TransitionError(str(exc)) from exc

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
                elif next_action != exact_dispose:
                    raise TransitionError(
                        "Batch disposition is not the exact next action"
                    )
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

    @staticmethod
    def _contains_study_kpi_metric(
        value: Mapping[str, Any],
        name: str,
    ) -> bool:
        return any(
            key == name
            or (
                isinstance(item, Mapping)
                and StateWriter._contains_study_kpi_metric(item, name)
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
        used: dict[str, str] = {}
        existing_for_identity: set[str] = set()
        for record in index.records_by_kind("study-kpi"):
            prior_identity = record.payload.get("executable_id")
            prior_display = record.payload.get("executable_display_id")
            if prior_identity is None and prior_display is None:
                continue
            if type(prior_identity) is not str or type(prior_display) is not str:
                raise TransitionError("Existing Study KPI display binding is invalid")
            owner = used.get(prior_display)
            if owner is not None and owner != prior_identity:
                raise TransitionError("Existing Study KPI display id is not unique")
            used[prior_display] = prior_identity
            if prior_identity == executable_id:
                existing_for_identity.add(prior_display)
        for prior_display, prior_identity in dict(
            reserved_display_owners or {}
        ).items():
            if type(prior_display) is not str or type(prior_identity) is not str:
                raise TransitionError("Reserved Study KPI display binding is invalid")
            owner = used.get(prior_display)
            if owner is not None and owner != prior_identity:
                raise TransitionError("Reserved Study KPI display id is not unique")
            used[prior_display] = prior_identity
            if prior_identity == executable_id:
                existing_for_identity.add(prior_display)
        if len(existing_for_identity) > 1:
            raise TransitionError("Executable has inconsistent Study KPI display ids")
        if existing_for_identity:
            return next(iter(existing_for_identity))
        digest = executable_id.removeprefix("executable:")
        for length in range(12, 65, 4):
            display = f"EXE-{digest[:length]}"
            if display not in used:
                return display
        raise TransitionError("Executable has no unique Study KPI display id")

    @staticmethod
    def _batch_stop_completion_ids(
        index: LocalIndex,
        batch_id: str,
    ) -> tuple[str, ...]:
        completion_ids: set[str] = set()
        for decision in index.records_by_kind("job-evidence-decision"):
            if decision.status != "stop_batch":
                continue
            job_id = decision.subject.removeprefix("Job:")
            declaration = index.get("job-declared", job_id)
            completion_id = decision.payload.get("completion_record_id")
            if (
                declaration is not None
                and declaration.payload.get("batch_id") == batch_id
            ):
                if type(completion_id) is not str:
                    raise TransitionError(
                        "Batch stop decision lacks its completion identity"
                    )
                completion_ids.add(completion_id)
        return tuple(sorted(completion_ids))

    @staticmethod
    def _batch_unavailable_reason(
        index: LocalIndex,
        batch_id: str,
        outcome: str,
    ) -> str:
        budget_head = index.event_head(f"batch-budget:{batch_id}")
        trial_head = index.event_head(f"batch-trials:{batch_id}")
        started = budget_head is not None or trial_head is not None
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
        elif outcome in {"engineering_failure", "not_evaluable"}:
            decisions: list[IndexRecord] = []
            for decision in index.records_by_kind("job-evidence-decision"):
                if decision.status != "continue_batch":
                    continue
                job_id = decision.subject.removeprefix("Job:")
                declaration = index.get("job-declared", job_id)
                if (
                    declaration is not None
                    and declaration.payload.get("batch_id") == batch_id
                ):
                    decisions.append(decision)
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
        elif outcome != "stopped_early":
            raise TransitionError(
                "Started Batch without a final stop completion requires a typed "
                "unavailable disposition"
            )
        return (
            f"{'started' if started else 'unstarted'}_batch_{outcome}_"
            "without_final_validator_completion"
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
            if self._batch_stop_completion_ids(index, batch_id):
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
                or outcome not in {"evidence_gap", "not_evaluable", "pruned"}
            ):
                raise TransitionError(
                    "Study KPI unavailable state is not writer-derived"
                )
            unavailable_reason = self._batch_unavailable_reason(
                index,
                batch_id,
                close_status,
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
        completion_ids = self._batch_stop_completion_ids(index, batch_id)
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
            existing_kpis = index.records_by_kind("study-kpi")
            if existing_kpis:
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
        """Materialize the tracked Markdown view from Journal-bound records."""

        rows: list[StudyKpiProjectionRow] = []
        with WriterLock(self.lock_path):
            with self._open_authoritative_index() as index:
                self._require_stable_locked(index)
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
                        or isinstance(sequence, bool)
                        or not isinstance(sequence, int)
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
                    elif source == "writer_derived_unavailable":
                        allowed_reasons = {
                            "unstarted_batch_not_evaluable_without_final_validator_completion": "not_evaluable",
                            "unstarted_batch_stopped_early_without_final_validator_completion": "stopped_early",
                            "started_batch_budget_exhausted_without_final_validator_completion": "budget_exhausted",
                            "started_batch_stopped_early_without_final_validator_completion": "stopped_early",
                            "started_batch_not_evaluable_without_final_validator_completion": "not_evaluable",
                            "started_batch_engineering_failure_without_final_validator_completion": "engineering_failure",
                        }
                        batch_head = index.event_head(
                            f"study-batches:{study_id}"
                        )
                        reason_status = allowed_reasons.get(unavailable_reason)
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
                            item
                            for item in index.records_by_kind(
                                "study-kpi-backfill"
                            )
                            if item.authority_event_id
                            == record.authority_event_id
                        )
                        if (
                            authority_event is None
                            or authority_event.status != "study_kpi_backfilled"
                            or isinstance(historical_close_revision, bool)
                            or not isinstance(historical_close_revision, int)
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
        if not self.engineering_fixture:
            self.rebuild_study_kpi_projection()
        return transition

    @staticmethod
    def _study_diagnosis_evidence_basis(
        index: LocalIndex,
        *,
        study_id: str,
        close_record: IndexRecord,
    ) -> list[dict[str, str]]:
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
        for memory in index.records_by_kind("negative-memory"):
            if memory.payload.get("study_id") == study_id:
                references.add(("negative-memory", memory.record_id))
        return [
            {"kind": kind, "record_id": record_id}
            for kind, record_id in sorted(references)
        ]

    def record_study_diagnosis(
        self,
        *,
        diagnosis: Any,
        operation_id: str,
    ) -> TransitionResult:
        from axiom_rift.research.governance import (
            EvidenceState,
            ResearchLayer,
            StudyDiagnosis,
            diagnosis_branch,
        )

        self._require_study_close_delivery_guard()
        if self.engineering_fixture:
            raise TransitionError("engineering fixtures do not create Study diagnosis")
        if not isinstance(diagnosis, StudyDiagnosis):
            raise TransitionError("diagnosis must be a StudyDiagnosis")

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None or current["scientific"]["active_mission"] is None:
                raise TransitionError("Study diagnosis requires an active Mission")
            science = current["scientific"]
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
                raise TransitionError("Study diagnosis cannot bypass active work")
            next_action = current["next_action"]
            if next_action != {
                "kind": "diagnose_study",
                "study_id": diagnosis.study_id,
                "study_close_record_id": diagnosis.study_close_record_id,
                "portfolio_snapshot_id": next_action.get("portfolio_snapshot_id"),
            }:
                raise TransitionError("Study diagnosis is not the exact next action")
            close_record = index.get(
                "study-close", diagnosis.study_close_record_id
            )
            study = index.get("study-open", diagnosis.study_id)
            if (
                close_record is None
                or close_record.subject != f"Study:{diagnosis.study_id}"
                or study is None
                or study.payload.get("mission_id") != science["active_mission"]
                or close_record.payload.get("portfolio_axis_identity")
                != study.payload.get("portfolio_axis_identity")
            ):
                raise TransitionError("Study diagnosis subject is unavailable or stale")
            outcome = close_record.status
            supported_states = {EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION}
            unavailable_states = {
                EvidenceState.ENGINEERING_GAP,
                EvidenceState.NOT_IDENTIFIABLE,
            }
            negative_states = set(EvidenceState) - supported_states - {
                EvidenceState.ENGINEERING_GAP,
                EvidenceState.NOT_IDENTIFIABLE,
            }
            allowed_states = (
                supported_states
                if outcome in {"supported", "preserved"}
                else unavailable_states
                if outcome in {"evidence_gap", "not_evaluable"}
                else negative_states
                if outcome == "not_supported"
                else negative_states | {EvidenceState.NOT_IDENTIFIABLE}
                if outcome == "pruned"
                else set()
            )
            if diagnosis.evidence_state not in allowed_states:
                raise TransitionError(
                    "Study diagnosis evidence state conflicts with its typed outcome"
                )
            kpi = index.get("study-kpi", diagnosis.study_id)
            unavailable_reason = (
                None if kpi is None else kpi.payload.get("unavailable_reason")
            )
            engineering_basis = (
                isinstance(unavailable_reason, str)
                and "engineering_failure" in unavailable_reason
            )
            if (
                diagnosis.evidence_state == EvidenceState.ENGINEERING_GAP
            ) != engineering_basis:
                raise TransitionError(
                    "engineering diagnosis must match the writer-derived Batch basis"
                )
            try:
                primary_layer = ResearchLayer(
                    study.payload["primary_research_layer"]
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise TransitionError(
                    "Study diagnosis lacks a typed primary research layer"
                ) from exc
            architecture = self._study_resolved_architecture_family(
                index=index,
                study=study,
            )
            allowed_actions, allowed_layers = diagnosis_branch(
                diagnosis.evidence_state,
                primary_layer=primary_layer,
            )
            evidence_basis = self._study_diagnosis_evidence_basis(
                index,
                study_id=diagnosis.study_id,
                close_record=close_record,
            )
            payload = {
                **diagnosis.to_identity_payload(),
                "allowed_actions": list(allowed_actions),
                "allowed_research_layers": list(allowed_layers),
                "evidence_basis": evidence_basis,
                "mission_id": science["active_mission"],
                "portfolio_axis_id": study.payload.get("portfolio_axis_id"),
                "portfolio_axis_identity": study.payload.get(
                    "portfolio_axis_identity"
                ),
                "portfolio_snapshot_id": study.payload.get(
                    "portfolio_snapshot_id"
                ),
                "primary_research_layer": primary_layer.value,
                "study_outcome": outcome,
                "system_architecture_family": architecture,
            }
            prior_diagnoses: list[IndexRecord] = []
            for record in index.records_by_kind("study-diagnosis"):
                if (
                    record.payload.get("mission_id") != science["active_mission"]
                    or record.payload.get("evidence_state")
                    in {
                        EvidenceState.ENGINEERING_GAP.value,
                        EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION.value,
                    }
                ):
                    continue
                prior_study_id = record.payload.get("study_id")
                prior_study = (
                    None
                    if not isinstance(prior_study_id, str)
                    else index.get("study-open", prior_study_id)
                )
                if (
                    prior_study is not None
                    and self._study_resolved_architecture_family(
                        index=index,
                        study=prior_study,
                    )
                    == architecture
                ):
                    prior_diagnoses.append(record)
            reviewed_ids: set[str] = set()
            for review in index.records_by_kind("architecture-review"):
                if review.payload.get("mission_id") == science["active_mission"]:
                    reviewed_ids.update(
                        value
                        for value in review.payload.get(
                            "covered_diagnosis_ids", []
                        )
                        if isinstance(value, str)
                    )
            unreviewed = [
                record for record in prior_diagnoses if record.record_id not in reviewed_ids
            ]
            current_is_reviewable = diagnosis.evidence_state not in {
                EvidenceState.ENGINEERING_GAP,
                EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION,
            }
            review_records = [*unreviewed]
            diagnosis_sequence_head = index.event_head(
                f"study-diagnosis:{science['active_mission']}"
            )
            diagnosis_sequence = (
                1
                if diagnosis_sequence_head is None
                else diagnosis_sequence_head.sequence + 1
            )
            diagnosis_record = _record(
                kind="study-diagnosis",
                record_id=diagnosis.identity,
                subject=f"Study:{diagnosis.study_id}",
                status=diagnosis.evidence_state.value,
                fingerprint=diagnosis.identity.removeprefix("diagnosis:"),
                payload=payload,
                event_stream=f"study-diagnosis:{science['active_mission']}",
                event_sequence=diagnosis_sequence,
            )
            if current_is_reviewable:
                review_records.append(diagnosis_record)
            snapshot_id = study.payload.get("portfolio_snapshot_id")
            snapshot = (
                None
                if not isinstance(snapshot_id, str)
                else index.get("portfolio-snapshot", snapshot_id)
            )
            standard = (
                None if snapshot is None else snapshot.payload.get("exhaustion_standard")
            )
            trigger_record: IndexRecord | None = None
            if isinstance(standard, dict) and current_is_reviewable:
                minimum_studies = standard.get(
                    "architecture_review_minimum_studies"
                )
                minimum_axes = standard.get("architecture_review_minimum_axes")
                axis_ids = {
                    record.payload.get("portfolio_axis_id")
                    for record in review_records
                }
                if (
                    type(minimum_studies) is int
                    and type(minimum_axes) is int
                    and len(review_records) >= minimum_studies
                    and len(axis_ids) >= minimum_axes
                    and None not in axis_ids
                ):
                    trigger_payload = {
                        "diagnosis_ids": sorted(
                            record.record_id for record in review_records
                        ),
                        "mission_id": science["active_mission"],
                        "portfolio_axis_ids": sorted(axis_ids),
                        "portfolio_snapshot_id": snapshot_id,
                        "primary_research_layers": sorted(
                            {
                                record.payload["primary_research_layer"]
                                for record in review_records
                            }
                        ),
                        "schema": "architecture_review_trigger.v1",
                        "system_architecture_family": architecture,
                        "threshold": {
                            "minimum_distinct_axes": minimum_axes,
                            "minimum_studies": minimum_studies,
                        },
                    }
                    trigger_id = canonical_digest(
                        domain="architecture-review-trigger",
                        payload=trigger_payload,
                    )
                    trigger_record = _record(
                        kind="architecture-review-trigger",
                        record_id=trigger_id,
                        subject=f"Mission:{science['active_mission']}",
                        status="required",
                        fingerprint=trigger_id,
                        payload=trigger_payload,
                    )
            body = self._body(current)
            if trigger_record is None:
                body["next_action"] = {
                    "kind": "portfolio_decision",
                    "portfolio_snapshot_id": snapshot_id,
                    "study_diagnosis_id": diagnosis.identity,
                }
                records = [diagnosis_record]
            else:
                body["next_action"] = {
                    "kind": "review_architecture",
                    "trigger_record_id": trigger_record.record_id,
                }
                records = [diagnosis_record, trigger_record]
            return body, records, {
                "architecture_review_trigger_id": (
                    None if trigger_record is None else trigger_record.record_id
                ),
                "study_diagnosis_id": diagnosis.identity,
            }

        return self._commit(
            event_kind="study_diagnosis_recorded",
            operation_id=operation_id,
            subject=f"Study:{diagnosis.study_id}",
            payload={"study_diagnosis_id": diagnosis.identity},
            prepare=prepare,
        )

    def record_architecture_review(
        self,
        *,
        review: Any,
        operation_id: str,
    ) -> TransitionResult:
        from axiom_rift.research.governance import (
            ArchitectureReview,
            ArchitectureReviewConclusion,
        )

        self._require_study_close_delivery_guard()
        if self.engineering_fixture:
            raise TransitionError("engineering fixtures do not create architecture review")
        if not isinstance(review, ArchitectureReview):
            raise TransitionError("review must be an ArchitectureReview")

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None or current["scientific"]["active_mission"] is None:
                raise TransitionError("architecture review requires an active Mission")
            science = current["scientific"]
            if science["active_mission"] != review.mission_id:
                raise TransitionError("architecture review belongs to another Mission")
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
                raise TransitionError("architecture review cannot bypass active work")
            next_action = current["next_action"]
            trigger_id = next_action.get("trigger_record_id")
            trigger = (
                None
                if not isinstance(trigger_id, str)
                else index.get("architecture-review-trigger", trigger_id)
            )
            if (
                next_action.get("kind") != "review_architecture"
                or trigger_id != review.trigger_record_id
                or trigger is None
                or trigger.status != "required"
                or trigger.payload.get("mission_id") != review.mission_id
                or trigger.payload.get("system_architecture_family")
                != review.system_architecture_family
            ):
                raise TransitionError("architecture review trigger is absent or stale")
            payload = {
                **review.to_identity_payload(),
                "covered_diagnosis_ids": trigger.payload["diagnosis_ids"],
                "portfolio_axis_ids": trigger.payload["portfolio_axis_ids"],
                "portfolio_snapshot_id": trigger.payload["portfolio_snapshot_id"],
                "primary_research_layers": trigger.payload[
                    "primary_research_layers"
                ],
            }
            body = self._body(current)
            body["next_action"] = {
                "kind": "portfolio_decision",
                "architecture_review_id": review.identity,
                "constraint_source_id": review.identity,
                "portfolio_snapshot_id": trigger.payload["portfolio_snapshot_id"],
            }
            if (
                review.conclusion
                == ArchitectureReviewConclusion.ROTATE_ARCHITECTURE
            ):
                body["next_action"]["excluded_architecture_family"] = (
                    review.system_architecture_family
                )
            else:
                body["next_action"]["excluded_research_layers"] = trigger.payload[
                    "primary_research_layers"
                ]
            record = _record(
                kind="architecture-review",
                record_id=review.identity,
                subject=f"Mission:{review.mission_id}",
                status=review.conclusion.value,
                fingerprint=review.identity.removeprefix("architecture-review:"),
                payload=payload,
            )
            return body, [record], {"architecture_review_id": review.identity}

        return self._commit(
            event_kind="architecture_review_recorded",
            operation_id=operation_id,
            subject=f"Mission:{review.mission_id}",
            payload={"architecture_review_id": review.identity},
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
        for binding_name in (
            "component_parity_binding",
            "runtime_binding",
            "scientific_binding",
        ):
            binding = value.get(binding_name)
            if isinstance(binding, dict):
                for name in (
                    "evidence_modes",
                    "planned_claims",
                    "planned_parity_surfaces",
                    "planned_materialization_cases",
                    "dimensions",
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
            "component_parity_binding",
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
        component_parity_binding = spec.get("component_parity_binding")
        external_binding = spec.get("external_dependency_binding")
        if sum(
            binding is not None
            for binding in (
                component_parity_binding,
                runtime_binding,
                scientific_binding,
                source_binding,
                external_binding,
            )
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
            required_scientific_fields = {
                "evidence_depth",
                "evidence_modes",
                "planned_claims",
                "result_manifest_output",
                "validation_plan_hash",
                "validator_id",
            }
            allowed_scientific_fields = required_scientific_fields | {
                "evaluation_schema"
            }
            if (
                not isinstance(scientific_binding, dict)
                or not required_scientific_fields.issubset(scientific_binding)
                or not set(scientific_binding).issubset(allowed_scientific_fields)
            ):
                raise TransitionError("scientific_binding has an invalid schema")
            validate_validator_binding(scientific_binding)
            if "evaluation_schema" in scientific_binding:
                _require_ascii(
                    "scientific evaluation schema",
                    scientific_binding["evaluation_schema"],
                )
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
        if component_parity_binding is not None:
            required_parity_fields = {
                "architecture_chassis_identity",
                "canonical_component_id",
                "canonical_component_manifest",
                "dimensions",
                "equivalent_component_id",
                "equivalent_component_manifest",
                "portfolio_axis_identity",
                "portfolio_decision_id",
                "portfolio_snapshot_id",
                "result_manifest_output",
                "validation_plan_hash",
                "validator_id",
            }
            if (
                not isinstance(component_parity_binding, dict)
                or set(component_parity_binding) != required_parity_fields
            ):
                raise TransitionError("component parity binding schema is invalid")
            validate_validator_binding(component_parity_binding)
            from axiom_rift.research.chassis import (
                ComponentParityDimension,
                component_semantic_surface_identity,
            )

            expected_dimensions = sorted(
                value.value for value in ComponentParityDimension
            )
            if component_parity_binding["dimensions"] != expected_dimensions:
                raise TransitionError(
                    "component parity must preregister every typed dimension"
                )
            manifests: list[dict[str, Any]] = []
            component_ids: list[str] = []
            for prefix in ("canonical", "equivalent"):
                component_id = component_parity_binding[f"{prefix}_component_id"]
                manifest = component_parity_binding[
                    f"{prefix}_component_manifest"
                ]
                if not isinstance(manifest, dict):
                    raise TransitionError("component parity manifest is malformed")
                expected_id = "component:" + canonical_digest(
                    domain="component", payload=manifest
                )
                if component_id != expected_id:
                    raise TransitionError(
                        "component parity endpoint differs from its exact manifest"
                    )
                component_ids.append(component_id)
                manifests.append(manifest)
            if component_ids[0] == component_ids[1]:
                raise TransitionError("component parity endpoints must be distinct")
            protocols = [manifest.get("protocol") for manifest in manifests]
            if any(not isinstance(value, str) for value in protocols) or (
                protocols[0].split(".", 1)[0]
                != protocols[1].split(".", 1)[0]
            ):
                raise TransitionError("component parity cannot cross protocol domains")
            if (
                protocols[0] != protocols[1]
                and component_semantic_surface_identity(manifests[0])
                == component_semantic_surface_identity(manifests[1])
            ):
                raise TransitionError(
                    "protocol-only component identity bumps cannot receive parity"
                )
            for component_id in component_ids:
                component_digest = component_id.removeprefix("component:")
                _require_digest("component parity input", component_digest)
                if component_digest not in input_hashes:
                    raise TransitionError(
                        "component parity endpoints must be content-bound Job inputs"
                    )
            for name in (
                "architecture_chassis_identity",
                "portfolio_axis_identity",
                "portfolio_decision_id",
                "portfolio_snapshot_id",
            ):
                _require_ascii(name, component_parity_binding[name])
            result_output = component_parity_binding["result_manifest_output"]
            if output_classes.get(result_output) != "durable_evidence":
                raise TransitionError(
                    "component parity result manifest must be durable"
                )
            if sum(
                value == "durable_evidence" for value in output_classes.values()
            ) < 2:
                raise TransitionError(
                    "component parity requires result and measurement artifacts"
                )
            if evidence_subject["kind"] != "Mission":
                raise TransitionError("component parity Job must bind the Mission")
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
                source_artifact = self.evidence.verify(source_hash)
                source_bytes = (
                    self.evidence._root / source_artifact.relative_path
                ).read_bytes()
                if _hardcoded_control_ids(source_bytes):
                    raise TransitionError(
                        "Job implementation hardcodes a Mission or Study identity; "
                        "use a reusable mechanism with declarative runtime binding"
                    )
            except TransitionError:
                raise
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

    def _preflight_scientific_binding(self, spec: Mapping[str, Any]) -> None:
        binding = spec.get("scientific_binding")
        if not isinstance(binding, Mapping):
            return
        try:
            self.validation_registry.preflight_binding(
                validator_id=binding["validator_id"],
                domain="scientific",
                binding=binding,
            )
        except EvidenceValidationError as exc:
            raise TransitionError(
                f"scientific validation preflight failed: {exc}"
            ) from exc

    def _authority_requires_scientific_adjudication_v2(
        self,
        current: Mapping[str, Any],
    ) -> bool:
        authority = current.get("authority")
        if not isinstance(authority, Mapping):
            raise RecoveryRequired("scientific protocol authority is unavailable")
        contracts = authority.get("contracts")
        if not isinstance(contracts, list):
            raise RecoveryRequired("scientific protocol contract manifest is invalid")
        root = self.foundation_root.resolve()
        for relative in contracts:
            _require_ascii("authority contract path", relative)
            path = (root / relative).resolve()
            if root != path and root not in path.parents:
                raise RecoveryRequired("scientific protocol contract escapes Foundation")
            if not path.is_file():
                raise RecoveryRequired("scientific protocol contract is unavailable")
            if any(
                line.strip() == b"scientific_adjudication_v2:"
                for line in path.read_bytes().splitlines()
            ):
                return True
        return False

    def declare_job(
        self, *, spec: Mapping[str, Any], operation_id: str
    ) -> TransitionResult:
        self._require_study_close_delivery_guard()
        spec = self._normalize_job_spec(spec)
        self._validate_job_spec(spec)
        self._preflight_scientific_binding(spec)
        work_basis = {
            "callable_identity": spec["callable_identity"],
            "component_parity_binding": spec.get("component_parity_binding"),
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
            scientific_binding = spec.get("scientific_binding")
            protocol_head = _index.event_head("research-protocol:scientific")
            if (
                isinstance(scientific_binding, dict)
                and protocol_head is None
                and self._authority_requires_scientific_adjudication_v2(current)
            ):
                raise TransitionError(
                    "authority requires an active v2 scientific protocol"
                )
            if isinstance(scientific_binding, dict) and protocol_head is not None:
                protocol = _index.get(
                    protocol_head.record_kind, protocol_head.record_id
                )
                if (
                    protocol is None
                    or protocol.kind != "research-protocol-activation"
                    or protocol.status != "active"
                    or protocol.event_sequence != protocol_head.sequence
                    or protocol.payload.get("protocol")
                    != "scientific_adjudication_v2"
                    or protocol.payload.get("authority_manifest_digest")
                    != current.get("authority", {}).get("manifest_digest")
                ):
                    raise RecoveryRequired(
                        "active scientific protocol projection is invalid"
                    )
                if (
                    scientific_binding.get("validator_id")
                    != protocol.payload.get("validator_id")
                ):
                    raise TransitionError(
                        "prospective scientific Job must use the active v2 protocol"
                    )
            if not self.engineering_fixture:
                next_action = current.get("next_action")
                active_batch = science.get("active_batch")
                parity_binding = spec.get("component_parity_binding")
                parity_at_accepted_decision = (
                    isinstance(next_action, dict)
                    and next_action.get("kind") == "execute_portfolio_decision"
                    and isinstance(parity_binding, dict)
                    and parity_binding.get("portfolio_decision_id")
                    == next_action.get("decision_id")
                    and parity_binding.get("portfolio_snapshot_id")
                    == next_action.get("portfolio_snapshot_id")
                    and parity_binding.get("portfolio_axis_identity")
                    == next_action.get("target_axis_identity")
                    and parity_binding.get("architecture_chassis_identity")
                    == next_action.get("architecture_chassis_identity")
                )
                if isinstance(parity_binding, dict) and not parity_at_accepted_decision:
                    raise TransitionError(
                        "component parity Job must bind the exact accepted Portfolio Decision"
                    )
                batch_allowed = isinstance(active_batch, dict) and next_action == {
                    "kind": "declare_job",
                    "batch_id": active_batch["id"],
                }
                active_executable = science.get("active_executable")
                candidate_allowed = (
                    isinstance(active_executable, str)
                    and isinstance(next_action, dict)
                    and next_action.get("kind") == "plan_candidate_bound_evidence"
                    and spec["evidence_subject"]
                    == {"kind": "Executable", "id": active_executable}
                    and any(
                        isinstance(spec.get(name), dict)
                        for name in ("runtime_binding", "scientific_binding")
                    )
                )
                source_allowed = (
                    isinstance(science.get("active_study"), str)
                    and isinstance(spec.get("source_binding"), dict)
                )
                external_allowed = isinstance(
                    spec.get("external_dependency_binding"), dict
                )
                if not any(
                    (
                        batch_allowed,
                        candidate_allowed,
                        external_allowed,
                        parity_at_accepted_decision,
                        source_allowed,
                    )
                ):
                    raise TransitionError(
                        "Job declaration cannot preempt research direction and is outside every exact authorized work boundary"
                    )
                if parity_at_accepted_decision:
                    if active_batch is not None or science.get("active_study") is not None:
                        raise TransitionError(
                            "pre-Study component parity requires no active Study or Batch"
                        )
                    decision = self._active_portfolio_decision(
                        _index, parity_binding["portfolio_decision_id"]
                    )
                    baseline = None if decision is None else decision.payload.get(
                        "baseline_executable"
                    )
                    canonical_id = parity_binding["canonical_component_id"]
                    if (
                        decision is None
                        or not isinstance(baseline, dict)
                        or canonical_id
                        not in baseline.get("component_identities", [])
                        or spec["evidence_subject"]
                        != {"kind": "Mission", "id": science["active_mission"]}
                    ):
                        raise TransitionError(
                            "component parity canonical endpoint is outside the accepted baseline"
                        )
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
            if kind is PermitKind.STUDY and not self.engineering_fixture:
                next_action = current.get("next_action", {})
                decision_id = next_action.get("decision_id")
                snapshot_id = next_action.get("portfolio_snapshot_id")
                axis_identity = next_action.get("target_axis_identity")
                architecture_identity = next_action.get(
                    "architecture_chassis_identity"
                )
                baseline_id = next_action.get("baseline_executable_id")
                decision = (
                    None
                    if not isinstance(decision_id, str)
                    else self._active_portfolio_decision(_index, decision_id)
                )
                snapshot = (
                    None
                    if not isinstance(snapshot_id, str)
                    else _index.get("portfolio-snapshot", snapshot_id)
                )
                required_scope = {
                    "study",
                    f"decision:{decision_id}",
                    f"axis:{axis_identity}",
                    f"baseline:{baseline_id}",
                    f"chassis:{architecture_identity}",
                    f"snapshot:{snapshot_id}",
                }
                if (
                    next_action.get("kind") != "execute_portfolio_decision"
                    or not isinstance(architecture_identity, str)
                    or not isinstance(baseline_id, str)
                    or decision is None
                    or snapshot is None
                    or decision.payload.get("portfolio_snapshot_id") != snapshot_id
                    or not required_scope.issubset(scope)
                ):
                    raise PermitError(
                        "StudyPermit requires an accepted current Portfolio Decision"
                    )
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
                    self._require_source_authority_for_actions(
                        _index,
                        source_id,
                        actions=actions,
                        error_type=PermitError,
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

        self._require_study_close_delivery_guard()
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
            if body["next_action"].get("kind") in {
                "record_research_intake",
                "diagnose_study",
                "review_architecture",
            }:
                raise TransitionError(
                    "candidate freeze cannot bypass research direction"
                )
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

    @staticmethod
    def _component_manifest_record(
        *,
        component_id: str,
        manifest: Mapping[str, Any],
    ) -> IndexRecord:
        from axiom_rift.research.chassis import (
            component_semantic_surface_identity,
        )

        expected_id = "component:" + canonical_digest(
            domain="component", payload=dict(manifest)
        )
        if component_id != expected_id:
            raise TransitionError("component identity differs from its exact manifest")
        protocol = manifest.get("protocol")
        if not isinstance(protocol, str) or not protocol or not protocol.isascii():
            raise TransitionError("component protocol is invalid")
        domain = protocol.split(".", 1)[0]
        surface_identity = component_semantic_surface_identity(manifest)
        return _record(
            kind="component-manifest",
            record_id=component_id,
            subject=f"Component:{component_id}",
            status="registered",
            fingerprint=surface_identity,
            payload={
                "component_id": component_id,
                "manifest": dict(manifest),
                "protocol_domain": domain,
                "schema": "component_manifest_projection.v1",
                "semantic_surface_identity": surface_identity,
            },
        )

    @staticmethod
    def _require_component_manifest_projection(
        index: LocalIndex,
        record: IndexRecord,
    ) -> IndexRecord | None:
        existing = index.get(record.kind, record.record_id)
        if existing is None:
            return record
        if (
            existing.subject != record.subject
            or existing.status != record.status
            or existing.fingerprint != record.fingerprint
            or dict(existing.payload) != dict(record.payload)
        ):
            raise RecordCollisionError("component manifest projection collision")
        return None

    @staticmethod
    def _component_protocol_neutral_surface(
        manifest: Mapping[str, Any],
    ) -> str:
        if not all(
            name in manifest
            for name in ("implementation", "semantic_dependencies", "spec")
        ):
            raise TransitionError("component manifest semantic surface is incomplete")
        return "component-protocol-neutral:" + canonical_digest(
            domain="component-protocol-neutral-surface",
            payload={
                "implementation": manifest["implementation"],
                "schema": "component_protocol_neutral_surface.v1",
                "semantic_dependencies": manifest["semantic_dependencies"],
                "spec": manifest["spec"],
            },
        )

    def _project_executable_components(
        self,
        index: LocalIndex,
        executable: Any,
    ) -> list[IndexRecord]:
        """Project exact components and reject only genuinely new surface aliases."""

        from axiom_rift.core.identity import ExecutableSpec

        if not isinstance(executable, ExecutableSpec):
            raise TransitionError("component projection requires an ExecutableSpec")
        records: list[IndexRecord] = []
        seen_surfaces: set[str] = set()
        seen_protocol_neutral_surfaces: set[str] = set()
        for component, component_id in zip(
            executable.components,
            executable.component_identities,
            strict=True,
        ):
            candidate = self._component_manifest_record(
                component_id=component_id,
                manifest=component.to_identity_payload(),
            )
            if candidate.fingerprint in seen_surfaces:
                raise TransitionError(
                    "one Executable cannot contain duplicate protocol-neutral component surfaces"
                )
            seen_surfaces.add(candidate.fingerprint)
            protocol_neutral_surface = self._component_protocol_neutral_surface(
                component.to_identity_payload()
            )
            if protocol_neutral_surface in seen_protocol_neutral_surfaces:
                raise TransitionError(
                    "one Executable cannot relabel the same component semantics across protocol domains"
                )
            seen_protocol_neutral_surfaces.add(protocol_neutral_surface)
            exact = index.get("component-manifest", component_id)
            if exact is not None:
                self._require_component_manifest_projection(index, candidate)
                continue
            variants = tuple(
                record
                for record in index.records_by_fingerprint(candidate.fingerprint)
                if record.kind == "component-manifest"
            )
            if variants:
                raise TransitionError(
                    "new component protocol/name drift duplicates an existing semantic surface"
                )
            cross_domain_variants = tuple(
                record
                for record in index.records_by_kind("component-manifest")
                if isinstance(record.payload.get("manifest"), dict)
                and self._component_protocol_neutral_surface(
                    record.payload["manifest"]
                )
                == protocol_neutral_surface
            )
            if cross_domain_variants:
                raise TransitionError(
                    "new component protocol/domain drift duplicates existing semantics"
                )
            records.append(candidate)
        return records

    def backfill_component_manifests(
        self,
        *,
        operation_id: str,
    ) -> TransitionResult:
        """Project exact legacy trial components without changing scientific credit."""

        self._require_study_close_delivery_guard()

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            science = current["scientific"]
            if any(
                science[name] is not None
                for name in (
                    "active_batch",
                    "active_executable",
                    "active_holdout_evaluation",
                    "active_job",
                    "active_release",
                    "active_repair",
                    "active_study",
                )
            ):
                raise TransitionError(
                    "component manifest backfill requires a stable scientific boundary"
                )
            projected: dict[str, IndexRecord] = {}
            for trial in index.records_by_kind("trial"):
                executable = trial.payload.get("executable")
                if not isinstance(executable, dict):
                    raise TransitionError("legacy trial executable manifest is absent")
                component_ids = executable.get("component_identities")
                manifests = executable.get("component_manifests")
                if (
                    not isinstance(component_ids, list)
                    or not isinstance(manifests, list)
                    or len(component_ids) != len(manifests)
                ):
                    raise TransitionError("legacy trial component manifests are malformed")
                for component_id, manifest in zip(component_ids, manifests, strict=True):
                    if not isinstance(component_id, str) or not isinstance(manifest, dict):
                        raise TransitionError(
                            "legacy trial component identity binding is malformed"
                        )
                    record = self._component_manifest_record(
                        component_id=component_id,
                        manifest=manifest,
                    )
                    prior = projected.get(component_id)
                    if prior is not None and dict(prior.payload) != dict(record.payload):
                        raise RecordCollisionError(
                            "legacy component identity has conflicting manifests"
                        )
                    projected[component_id] = record
            records: list[IndexRecord] = []
            for component_id in sorted(projected):
                record = self._require_component_manifest_projection(
                    index, projected[component_id]
                )
                if record is not None:
                    records.append(record)
            return self._body(current), records, {
                "claim": science["claim"],
                "component_manifest_count": len(projected),
                "holdout_delta": 0,
                "projected_record_count": len(records),
                "trial_delta": 0,
            }

        return self._commit(
            event_kind="component_manifests_backfilled",
            operation_id=operation_id,
            subject="ProjectGoal:OPERATING_DIRECTION.md",
            payload={
                "claim_delta": "none",
                "holdout_delta": 0,
                "trial_delta": 0,
            },
            prepare=prepare,
        )

    @staticmethod
    def _executable_surface_record(
        *,
        surface_identity: str,
        executable_ids: tuple[str, ...],
    ) -> IndexRecord:
        if (
            not surface_identity.startswith("executable-surface:")
            or len(surface_identity) != 83
        ):
            raise TransitionError("Executable semantic surface identity is invalid")
        normalized_ids = tuple(sorted(set(executable_ids)))
        if len(normalized_ids) != len(executable_ids) or not normalized_ids:
            raise TransitionError("Executable semantic surface members are invalid")
        for executable_id in normalized_ids:
            if (
                not executable_id.startswith("executable:")
                or len(executable_id) != 75
            ):
                raise TransitionError("Executable semantic surface member is invalid")
        return _record(
            kind="executable-surface",
            record_id=surface_identity,
            subject=f"ExecutableSurface:{surface_identity}",
            status="registered",
            fingerprint=surface_identity,
            payload={
                "exact_executable_ids": list(normalized_ids),
                "schema": "executable_semantic_surface_projection.v1",
                "surface_identity": surface_identity,
            },
        )

    @staticmethod
    def _require_executable_surface_projection(
        index: LocalIndex,
        record: IndexRecord,
    ) -> IndexRecord | None:
        existing = index.get(record.kind, record.record_id)
        if existing is None:
            return record
        if (
            existing.subject != record.subject
            or existing.status != record.status
            or existing.fingerprint != record.fingerprint
            or dict(existing.payload) != dict(record.payload)
        ):
            raise RecordCollisionError("Executable semantic surface projection collision")
        return None

    def backfill_executable_semantic_surfaces(
        self,
        *,
        operation_id: str,
    ) -> TransitionResult:
        """Index legacy trials by protocol-neutral Executable surface, without credit."""

        self._require_study_close_delivery_guard()

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            science = current["scientific"]
            if any(
                science[name] is not None
                for name in (
                    "active_batch",
                    "active_executable",
                    "active_holdout_evaluation",
                    "active_job",
                    "active_release",
                    "active_repair",
                    "active_study",
                )
            ):
                raise TransitionError(
                    "Executable semantic surface backfill requires a stable scientific boundary"
                )
            from axiom_rift.research.chassis import (
                ChassisIdentityError,
                executable_semantic_surface_identity,
            )

            grouped: dict[str, set[str]] = {}
            for trial in index.records_by_kind("trial"):
                executable_payload = trial.payload.get("executable")
                if not isinstance(executable_payload, dict):
                    raise TransitionError("legacy trial executable manifest is absent")
                try:
                    surface_identity = executable_semantic_surface_identity(
                        executable_payload
                    )
                except ChassisIdentityError as exc:
                    raise TransitionError(str(exc)) from exc
                grouped.setdefault(surface_identity, set()).add(trial.record_id)
            records: list[IndexRecord] = []
            for surface_identity in sorted(grouped):
                projected = self._executable_surface_record(
                    surface_identity=surface_identity,
                    executable_ids=tuple(sorted(grouped[surface_identity])),
                )
                record = self._require_executable_surface_projection(index, projected)
                if record is not None:
                    records.append(record)
            return self._body(current), records, {
                "claim": science["claim"],
                "exact_executable_count": sum(len(values) for values in grouped.values()),
                "holdout_delta": 0,
                "projected_record_count": len(records),
                "surface_count": len(grouped),
                "trial_delta": 0,
            }

        return self._commit(
            event_kind="executable_semantic_surfaces_backfilled",
            operation_id=operation_id,
            subject="ProjectGoal:OPERATING_DIRECTION.md",
            payload={
                "claim_delta": "none",
                "holdout_delta": 0,
                "trial_delta": 0,
            },
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
                self._require_source_authority_for_actions(
                    index,
                    source_id,
                    actions=("performance_batch",),
                )
            record_kind = "engineering-evaluation-fixture" if self.engineering_fixture else "trial"
            study_id = current["scientific"]["active_study"]
            study_record = index.get("study-open", study_id)
            if study_record is None:
                raise TransitionError("active Study declaration is unavailable")
            material_identity = study_record.payload["material_identity"]
            component_records: list[IndexRecord] = []
            executable_surface_record: IndexRecord | None = None
            if not self.engineering_fixture:
                from axiom_rift.research.chassis import (
                    ChassisIdentityError,
                    executable_semantic_surface_identity,
                    validate_controlled_executable,
                )

                controlled_chassis = study_record.payload.get("controlled_chassis")
                if not isinstance(controlled_chassis, dict):
                    raise TransitionError(
                        "scientific Study lacks a controlled component chassis"
                    )
                try:
                    is_exact_baseline_control = (
                        controlled_chassis.get("baseline_executable_id")
                        == executable_id
                        and controlled_chassis.get("baseline_executable")
                        == executable.to_identity_payload()
                    )
                    if not is_exact_baseline_control:
                        validate_controlled_executable(
                            controlled_chassis, executable
                        )
                    surface_identity = executable_semantic_surface_identity(executable)
                except ChassisIdentityError as exc:
                    raise TransitionError(str(exc)) from exc
                surface_projection = index.get(
                    "executable-surface", surface_identity
                )
                if surface_projection is not None:
                    exact_ids = surface_projection.payload.get(
                        "exact_executable_ids"
                    )
                    if (
                        surface_projection.status != "registered"
                        or surface_projection.fingerprint != surface_identity
                        or surface_projection.payload.get("schema")
                        != "executable_semantic_surface_projection.v1"
                        or not isinstance(exact_ids, list)
                        or any(not isinstance(value, str) for value in exact_ids)
                    ):
                        raise RecoveryRequired(
                            "Executable semantic surface projection is malformed"
                        )
                    if executable_id not in exact_ids:
                        raise TransitionError(
                            "protocol-neutral Executable duplicate already has scientific history; "
                            "reuse its exact historical identity"
                        )
            existing = index.get(record_kind, executable_id)
            if existing is not None:
                if existing.fingerprint != executable_hash:
                    raise RecordCollisionError("Executable identity collision")
                if (
                    not self.engineering_fixture
                    and index.get("executable-surface", surface_identity) is None
                ):
                    raise RecoveryRequired(
                        "counted Executable lacks its semantic surface projection"
                    )
                return self._body(current), [], {"trial_delta": 0, "cache_hit": True}
            if not self.engineering_fixture:
                component_records.extend(
                    self._project_executable_components(index, executable)
                )
                executable_surface_record = self._executable_surface_record(
                    surface_identity=surface_identity,
                    executable_ids=(executable_id,),
                )
                projection = self._require_executable_surface_projection(
                    index, executable_surface_record
                )
                if projection is None:
                    raise RecoveryRequired(
                        "new Executable collides with an existing semantic surface"
                    )
                executable_surface_record = projection
            status = "engineering_only" if self.engineering_fixture else "evaluated"
            trial_head = index.event_head(f"batch-trials:{batch['id']}")
            evaluated_count = 0 if trial_head is None else trial_head.sequence
            max_trials = batch_record.payload["spec"]["max_trials"]
            if evaluated_count >= max_trials:
                raise TransitionError("frozen Batch trial budget is exhausted")
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
            records = [
                *component_records,
                *(
                    []
                    if executable_surface_record is None
                    else [executable_surface_record]
                ),
                record,
            ]
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

        self._require_study_close_delivery_guard()
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
            required_target_axis_ids: list[str] = []
            constraint_source_id: str | None = None
            if head is None:
                standard = snapshot.exhaustion_standard_value()
                if not self.engineering_fixture and not isinstance(standard, dict):
                    raise TransitionError(
                        "scientific Portfolio requires a preregistered exhaustion standard"
                    )
                if isinstance(standard, dict):
                    if not self.engineering_fixture and any(
                        axis.architecture_chassis is None for axis in snapshot.axes
                    ):
                        raise TransitionError(
                            "scientific Portfolio axes require canonical architecture chassis"
                        )
                    families = {axis.mechanism_family for axis in snapshot.axes}
                    research_layers = {
                        axis.primary_research_layer.value for axis in snapshot.axes
                    }
                    architecture_families = {
                        axis.architecture_chassis.identity
                        for axis in snapshot.axes
                        if axis.architecture_chassis is not None
                    }
                    if (
                        len(snapshot.axes) < standard["minimum_axes"]
                        or len(families) < standard["minimum_mechanism_families"]
                        or len(research_layers)
                        < standard["minimum_primary_research_layers"]
                        or len(architecture_families)
                        < standard["minimum_system_architecture_families"]
                    ):
                        raise TransitionError(
                            "initial Portfolio is smaller than its exhaustion standard"
                        )
                intake = (
                    None
                    if not isinstance(snapshot.research_intake_id, str)
                    else index.get("research-intake", snapshot.research_intake_id)
                )
                if (
                    current["next_action"].get("kind") != "build_portfolio"
                    or current["next_action"].get("initiative_id")
                    != science["active_initiative"]
                    or (
                        not self.engineering_fixture
                        and (
                            current["next_action"].get("research_intake_id")
                            != snapshot.research_intake_id
                            or intake is None
                            or intake.subject != f"Mission:{snapshot.mission_id}"
                            or intake.status != "accepted"
                        )
                    )
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
                    else self._active_portfolio_decision(index, decision_id)
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
                if (
                    new_payload.get("research_intake_id")
                    != prior.payload.get("research_intake_id")
                ):
                    raise TransitionError(
                        "Portfolio research intake is immutable within a Mission"
                    )
                if not set(old_axes).issubset(new_axes):
                    raise TransitionError("Portfolio axes cannot be silently removed")
                added_axis_ids = set(new_axes) - set(old_axes)
                if not self.engineering_fixture and any(
                    new_axes[axis_id].get("architecture_chassis_identity") is None
                    for axis_id in added_axis_ids
                ):
                    raise TransitionError(
                        "new scientific Portfolio axes require canonical architecture chassis"
                    )
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
                    required_layers = set(
                        next_action.get("required_followup_layers", [])
                    )
                    excluded_layers = set(
                        next_action.get("excluded_research_layers", [])
                    )
                    excluded_architecture = next_action.get(
                        "excluded_architecture_family"
                    )
                    constrained = bool(
                        required_layers
                        or excluded_layers
                        or isinstance(excluded_architecture, str)
                    )
                    if constrained:
                        required_target_axis_ids = sorted(
                            axis_id
                            for axis_id in added
                            if (
                                not required_layers
                                or new_axes[axis_id]["primary_research_layer"]
                                in required_layers
                            )
                            and new_axes[axis_id]["primary_research_layer"]
                            not in excluded_layers
                            and (
                                not isinstance(excluded_architecture, str)
                                or (
                                    isinstance(
                                        new_axes[axis_id].get(
                                            "architecture_chassis_identity"
                                        ),
                                        str,
                                    )
                                    and new_axes[axis_id][
                                        "architecture_chassis_identity"
                                    ]
                                    != excluded_architecture
                                )
                            )
                        )
                        if not required_target_axis_ids:
                            raise TransitionError(
                                "new mechanism does not satisfy its diagnosis or architecture constraint"
                            )
                        source = next_action.get("constraint_source_id")
                        if not isinstance(source, str):
                            raise TransitionError(
                                "constrained Portfolio mutation lacks its source"
                            )
                        constraint_source_id = source
                else:
                    raise TransitionError(
                        "Portfolio Decision does not authorize snapshot mutation"
                    )
            body = self._body(current)
            body["next_action"] = {
                "kind": "portfolio_decision",
                "portfolio_snapshot_id": snapshot.identity,
            }
            if required_target_axis_ids:
                body["next_action"].update(
                    {
                        "constraint_source_id": constraint_source_id,
                        "required_target_axis_ids": required_target_axis_ids,
                    }
                )
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

        self._require_study_close_delivery_guard()

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
            required_target_axis_ids = next_action.get("required_target_axis_ids")
            if required_target_axis_ids is not None and (
                not isinstance(required_target_axis_ids, list)
                or not required_target_axis_ids
                or required_target_axis_ids != sorted(set(required_target_axis_ids))
                or any(type(item) is not str for item in required_target_axis_ids)
                or any(item not in eligible_targets for item in required_target_axis_ids)
                or decision.chosen.target_id not in required_target_axis_ids
            ):
                raise TransitionError(
                    "Portfolio Decision bypasses its admitted constrained axis"
                )
            constraint_source_id = next_action.get("constraint_source_id")
            if constraint_source_id is not None and (
                type(constraint_source_id) is not str
                or not constraint_source_id
                or not constraint_source_id.isascii()
            ):
                raise TransitionError("Portfolio Decision constraint source is invalid")
            if required_target_axis_ids is not None and constraint_source_id is None:
                raise TransitionError(
                    "Portfolio Decision constrained axes lack their exact source"
                )
            scheduler_constraints = None
            if required_target_axis_ids is not None or constraint_source_id is not None:
                scheduler_constraints = {
                    "constraint_source_id": constraint_source_id,
                    "required_target_axis_ids": required_target_axis_ids,
                }
            if (
                decision.recent_positive_lineage_id is not None
                and decision.recent_positive_lineage_id not in eligible_targets
                and _index.get("lineage", decision.recent_positive_lineage_id) is None
            ):
                raise TransitionError("recent-positive reference is not durable")
            target_axis = axes_by_id[decision.chosen.target_id]
            work_actions = {
                PortfolioAction.COMPLEMENTARY_SLEEVE,
                PortfolioAction.CONTRAST,
                PortfolioAction.DEEPEN,
                PortfolioAction.RECOMBINE,
                PortfolioAction.ROTATE,
                PortfolioAction.SYNTHESIZE,
            }
            baseline = decision.baseline_executable
            architecture = decision.architecture_chassis
            component_records: list[IndexRecord] = []
            baseline_provenance: dict[str, Any] | None = None
            resolved_architecture_family: str | None = None
            if not self.engineering_fixture and decision.chosen.action in work_actions:
                if baseline is None or architecture is None:
                    raise TransitionError(
                        "scientific Portfolio Decision must bind a baseline Executable chassis"
                    )
                typed_axis_identity = target_axis.get(
                    "architecture_chassis_identity"
                )
                typed_axis_payload = target_axis.get("architecture_chassis")
                prior_anchor = self._axis_architecture_anchor(_index, target_axis)
                resolved_architecture_family = self._resolved_architecture_family(
                    index=_index,
                    architecture_payload=architecture.to_identity_payload(),
                )
                if isinstance(typed_axis_identity, str):
                    if not isinstance(typed_axis_payload, dict):
                        raise RecoveryRequired(
                            "typed Portfolio axis chassis payload is malformed"
                        )
                    typed_axis_family = self._resolved_architecture_family(
                        index=_index,
                        architecture_payload=typed_axis_payload,
                    )
                    if typed_axis_family != resolved_architecture_family:
                        raise TransitionError(
                            "Portfolio Decision baseline differs from its typed axis chassis"
                        )
                if not isinstance(typed_axis_identity, str) and prior_anchor is not None and (
                    (
                        self._resolved_architecture_family(
                            index=_index,
                            architecture_payload=prior_anchor[
                                "architecture_chassis"
                            ],
                        )
                        if isinstance(
                            prior_anchor.get("architecture_chassis"), dict
                        )
                        else prior_anchor["architecture_chassis_identity"]
                    )
                    != resolved_architecture_family
                ):
                    raise TransitionError(
                        "legacy Portfolio axis cannot change its prospective chassis anchor"
                    )
                prior_baseline = self._prior_scientific_baseline(
                    _index,
                    baseline,
                    portfolio_axis_identity=target_axis["axis_identity"],
                )
                bootstrap_anchors = [
                    record
                    for record in _index.records_by_kind("portfolio-decision")
                    if self._active_portfolio_decision(_index, record.record_id)
                    is not None
                    and record.payload.get("baseline_executable_id") == baseline.identity
                    and record.payload.get("baseline_executable")
                    == baseline.to_identity_payload()
                    and isinstance(record.payload.get("baseline_provenance"), dict)
                    and record.payload["baseline_provenance"].get("kind")
                    in {
                        "first_controlled_chassis_bootstrap",
                        "first_axis_controlled_chassis_bootstrap",
                    }
                    and record.payload.get("target_axis_identity")
                    == target_axis["axis_identity"]
                ]
                if len(bootstrap_anchors) > 1:
                    raise RecoveryRequired(
                        "controlled chassis has conflicting bootstrap anchors"
                    )
                has_data_contract_trials = any(
                    isinstance(record.payload.get("executable"), dict)
                    and record.payload["executable"].get("data_contract")
                    == baseline.data_contract
                    for record in _index.records_by_kind("trial")
                )
                axis_has_controlled_history = any(
                    isinstance(record.payload.get("controlled_chassis"), dict)
                    and record.payload.get("portfolio_axis_identity")
                    == target_axis["axis_identity"]
                    for record in _index.records_by_kind("study-open")
                )
                has_any_controlled_history = any(
                    isinstance(record.payload.get("controlled_chassis"), dict)
                    for record in _index.records_by_kind("study-open")
                )
                baseline_provenance = (
                    {
                        "kind": "trial",
                        "record_id": prior_baseline.record_id,
                    }
                    if prior_baseline is not None
                    else {
                        "kind": "controlled_chassis_anchor_reuse",
                        "record_id": bootstrap_anchors[0].record_id,
                    }
                    if bootstrap_anchors
                    else {
                        "data_contract": baseline.data_contract,
                        **(
                            {
                                "kind": "first_axis_controlled_chassis_bootstrap",
                                "portfolio_axis_identity": target_axis[
                                    "axis_identity"
                                ],
                            }
                            if has_data_contract_trials
                            and has_any_controlled_history
                            and not axis_has_controlled_history
                            else {
                                "kind": (
                                    "first_controlled_chassis_bootstrap"
                                    if has_data_contract_trials
                                    else "first_data_contract_bootstrap"
                                )
                            }
                        ),
                    }
                )
                component_records = self._project_executable_components(
                    _index, baseline
                )
            elif (
                not self.engineering_fixture
                and (baseline is not None or architecture is not None)
            ):
                raise TransitionError(
                    "structural Portfolio Decision cannot pre-register a Study baseline"
                )
            target_architecture_identity = resolved_architecture_family
            if target_architecture_identity is None:
                target_anchor = self._axis_architecture_anchor(_index, target_axis)
                if target_anchor is not None:
                    target_payload = target_anchor.get("architecture_chassis")
                    target_architecture_identity = (
                        self._resolved_architecture_family(
                            index=_index,
                            architecture_payload=target_payload,
                        )
                        if isinstance(target_payload, dict)
                        else target_anchor["architecture_chassis_identity"]
                    )
            diagnosis_id = next_action.get("study_diagnosis_id")
            diagnosis = (
                None
                if not isinstance(diagnosis_id, str)
                else _index.get("study-diagnosis", diagnosis_id)
            )
            if isinstance(diagnosis_id, str):
                if (
                    diagnosis is None
                    or diagnosis.payload.get("mission_id")
                    != science["active_mission"]
                    or diagnosis.payload.get("portfolio_snapshot_id")
                    != snapshot.record_id
                ):
                    raise TransitionError(
                        "Portfolio Decision Study diagnosis is absent or stale"
                    )
                allowed_actions = set(diagnosis.payload.get("allowed_actions", []))
                allowed_layers = set(
                    diagnosis.payload.get("allowed_research_layers", [])
                )
                source_axis_id = diagnosis.payload.get("portfolio_axis_id")
                source_axis = axes_by_id.get(source_axis_id)
                chosen_action = decision.chosen.action.value
                same_axis_disposition = (
                    decision.chosen.target_id == source_axis_id
                    and chosen_action in {"preserve", "prune"}
                    and chosen_action in allowed_actions
                )
                branch_match = (
                    chosen_action not in {"preserve", "prune"}
                    and chosen_action in allowed_actions
                    and (
                        target_axis["primary_research_layer"] in allowed_layers
                        or chosen_action == "new_mechanism"
                    )
                )
                forest_diversion = (
                    source_axis is not None
                    and decision.chosen.target_id != source_axis_id
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
                        or (
                            isinstance(target_architecture_identity, str)
                            and target_architecture_identity
                            != diagnosis.payload.get("system_architecture_family")
                        )
                    )
                )
                if not (same_axis_disposition or branch_match or forest_diversion):
                    raise TransitionError(
                        "Portfolio Decision does not follow or structurally exit its diagnosis"
                    )
            architecture_review_id = next_action.get("architecture_review_id")
            architecture_review = (
                None
                if not isinstance(architecture_review_id, str)
                else _index.get("architecture-review", architecture_review_id)
            )
            if isinstance(architecture_review_id, str) and (
                architecture_review is None
                or architecture_review.payload.get("mission_id")
                != science["active_mission"]
            ):
                raise TransitionError(
                    "Portfolio Decision architecture review is absent or stale"
                )
            excluded_architecture = next_action.get(
                "excluded_architecture_family"
            )
            excluded_layers = set(
                next_action.get("excluded_research_layers", [])
            )
            if architecture_review is not None:
                conclusion = architecture_review.payload.get("conclusion")
                if conclusion == "rotate_architecture":
                    reviewed_family = self._review_resolved_architecture_family(
                        index=_index,
                        review=architecture_review,
                    )
                    if (
                        excluded_architecture != reviewed_family
                        or excluded_layers
                    ):
                        raise TransitionError(
                            "Portfolio Decision architecture constraint is malformed"
                        )
                elif conclusion == "change_research_layer":
                    if (
                        excluded_layers
                        != set(
                            architecture_review.payload.get(
                                "primary_research_layers", []
                            )
                        )
                        or excluded_architecture is not None
                    ):
                        raise TransitionError(
                            "Portfolio Decision layer constraint is malformed"
                        )
                else:
                    raise TransitionError(
                        "Portfolio Decision architecture conclusion is invalid"
                    )
            if decision.chosen.action != PortfolioAction.NEW_MECHANISM:
                if (
                    isinstance(excluded_architecture, str)
                    and not isinstance(target_architecture_identity, str)
                ):
                    raise TransitionError(
                        "Portfolio Decision cannot prove architecture rotation from a legacy name"
                    )
                if (
                    isinstance(excluded_architecture, str)
                    and target_architecture_identity == excluded_architecture
                ):
                    raise TransitionError(
                        "Portfolio Decision did not rotate the reviewed architecture"
                    )
                if target_axis["primary_research_layer"] in excluded_layers:
                    raise TransitionError(
                        "Portfolio Decision did not change the reviewed research layer"
                    )
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
            body["next_action"] = {
                "kind": next_kind,
                "decision_id": decision.identity,
                "action": decision.chosen.action.value,
                "target_id": decision.chosen.target_id,
                "target_axis_identity": target_axis["axis_identity"],
                "portfolio_snapshot_id": snapshot.record_id,
            }
            if next_kind == "execute_portfolio_decision" and not self.engineering_fixture:
                assert baseline is not None and architecture is not None
                body["next_action"].update(
                    {
                        "architecture_chassis_identity": architecture.identity,
                        "resolved_architecture_family": resolved_architecture_family,
                        "baseline_executable_id": baseline.identity,
                    }
                )
            if next_kind == "record_portfolio_snapshot" and (
                decision.chosen.action == PortfolioAction.NEW_MECHANISM
            ):
                constraint_source_id = next_action.get("constraint_source_id")
                if isinstance(diagnosis_id, str):
                    body["next_action"]["required_followup_layers"] = list(
                        diagnosis.payload["allowed_research_layers"]
                    )
                    constraint_source_id = diagnosis_id
                if isinstance(excluded_architecture, str):
                    body["next_action"]["excluded_architecture_family"] = (
                        excluded_architecture
                    )
                if excluded_layers:
                    body["next_action"]["excluded_research_layers"] = sorted(
                        excluded_layers
                    )
                if (
                    "required_followup_layers" in body["next_action"]
                    or "excluded_architecture_family" in body["next_action"]
                    or "excluded_research_layers" in body["next_action"]
                ):
                    if not isinstance(constraint_source_id, str):
                        raise TransitionError(
                            "constrained new mechanism lacks its exact source"
                        )
                    body["next_action"]["constraint_source_id"] = (
                        constraint_source_id
                    )
            record = _record(
                kind="portfolio-decision",
                record_id=decision.identity,
                subject=f"Mission:{science['active_mission']}",
                status=decision.chosen.action.value,
                fingerprint=decision_hash,
                payload={
                    **decision.to_identity_payload(),
                    "architecture_review_id": architecture_review_id,
                    "baseline_provenance": baseline_provenance,
                    "portfolio_snapshot_id": snapshot.record_id,
                    "scheduler_constraints": scheduler_constraints,
                    "study_diagnosis_id": diagnosis_id,
                    "target_axis_identity": target_axis["axis_identity"],
                    "resolved_architecture_family": resolved_architecture_family,
                },
            )
            return body, [*component_records, record], {
                "decision_id": decision.identity
            }

        return self._commit(
            event_kind="portfolio_decision_recorded",
            operation_id=operation_id,
            subject="Portfolio:active",
            payload={"decision_id": decision.identity},
            prepare=prepare,
        )

    def withdraw_pending_portfolio_decision(
        self,
        *,
        manifest_artifact_hash: str,
        operation_id: str,
    ) -> TransitionResult:
        """Withdraw an accepted but unstarted Decision whose basis was invalidated."""

        from axiom_rift.research.decision_withdrawal import (
            PortfolioDecisionWithdrawalManifest,
            PortfolioDecisionWithdrawalReason,
        )

        _require_digest(
            "Portfolio Decision withdrawal manifest",
            manifest_artifact_hash,
        )
        try:
            manifest_bytes = self.evidence.read_verified(manifest_artifact_hash)
            manifest = PortfolioDecisionWithdrawalManifest.from_bytes(manifest_bytes)
            report_bytes = self.evidence.read_verified(manifest.report_artifact_hash)
            manifest.require_report(report_bytes)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise TransitionError(
                "Portfolio Decision withdrawal lacks its exact canonical manifest"
            ) from exc
        if (
            manifest.reason_code
            is not PortfolioDecisionWithdrawalReason.SOURCE_AUTHORITY_INVALIDATED
        ):
            raise TransitionError("Portfolio Decision withdrawal reason is unsupported")

        self._require_study_close_delivery_guard()

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("Portfolio Decision withdrawal requires control")
            science = current["scientific"]
            mission_id = science.get("active_mission")
            initiative_id = science.get("active_initiative")
            if type(mission_id) is not str or type(initiative_id) is not str:
                raise TransitionError(
                    "Portfolio Decision withdrawal requires active Mission work"
                )
            if any(
                science.get(name) is not None
                for name in (
                    "active_batch",
                    "active_executable",
                    "active_job",
                    "active_lineage",
                    "active_release",
                    "active_repair",
                    "active_study",
                    "active_holdout_evaluation",
                )
            ):
                raise TransitionError(
                    "Portfolio Decision withdrawal cannot bypass started work"
                )
            next_action = current.get("next_action")
            decision = index.get("portfolio-decision", manifest.decision_id)
            if (
                self._portfolio_decision_withdrawal(
                    index,
                    manifest.decision_id,
                )
                is not None
            ):
                raise TransitionError("Portfolio Decision is already withdrawn")
            if (
                not isinstance(next_action, dict)
                or next_action.get("kind") != "execute_portfolio_decision"
                or next_action.get("decision_id") != manifest.decision_id
                or decision is None
                or decision.subject != f"Mission:{mission_id}"
                or decision.payload.get("portfolio_snapshot_id")
                != next_action.get("portfolio_snapshot_id")
            ):
                raise TransitionError(
                    "Portfolio Decision withdrawal is not the exact unstarted action"
                )
            snapshot = index.get(
                "portfolio-snapshot",
                manifest.portfolio_snapshot_id,
            )
            axes = (
                ()
                if snapshot is None
                else tuple(snapshot.payload.get("axes", ()))
            )
            target_axes = tuple(
                axis
                for axis in axes
                if isinstance(axis, dict)
                and axis.get("axis_id") == manifest.target_axis_id
            )
            eligible_axis_ids = {
                axis.get("axis_id")
                for axis in axes
                if isinstance(axis, dict)
                and axis.get("status") != "pruned"
                and isinstance(axis.get("axis_id"), str)
            }
            chosen_options = tuple(
                option
                for option in decision.payload.get("options", ())
                if isinstance(option, dict)
                and option.get("option_id")
                == decision.payload.get("chosen_option_id")
            )
            baseline = decision.payload.get("baseline_executable")
            component_manifests = (
                ()
                if not isinstance(baseline, dict)
                else baseline.get("component_manifests", ())
            )
            bound_sources = set(
                baseline.get("source_contracts", ())
                if isinstance(baseline, dict)
                else ()
            )
            if isinstance(component_manifests, list):
                for component in component_manifests:
                    specification = (
                        None
                        if not isinstance(component, dict)
                        else component.get("spec")
                    )
                    source_id = (
                        None
                        if not isinstance(specification, dict)
                        else specification.get("source_contract_id")
                    )
                    if isinstance(source_id, str):
                        bound_sources.add(source_id)
            source_head = index.event_head(
                f"source:{manifest.source_contract_id}"
            )
            source_state = (
                None
                if source_head is None
                else index.get(source_head.record_kind, source_head.record_id)
            )
            if (
                snapshot is None
                or snapshot.record_id != decision.payload.get("portfolio_snapshot_id")
                or len(target_axes) != 1
                or len(chosen_options) != 1
                or chosen_options[0].get("target_id") != manifest.target_axis_id
                or target_axes[0].get("axis_identity")
                != manifest.target_axis_identity
                or decision.payload.get("target_axis_identity")
                != manifest.target_axis_identity
                or next_action.get("target_id") != manifest.target_axis_id
                or next_action.get("target_axis_identity")
                != manifest.target_axis_identity
                or decision.payload.get("baseline_executable_id")
                != manifest.baseline_executable_id
                or (
                    next_action.get("baseline_executable_id") is not None
                    and next_action.get("baseline_executable_id")
                    != manifest.baseline_executable_id
                )
                or manifest.source_contract_id not in bound_sources
                or source_head is None
                or source_state is None
                or source_head.record_id != manifest.source_state_record_id
                or source_state.subject
                != f"Source:{manifest.source_contract_id}"
                or source_state.fingerprint != manifest.source_contract_id
            ):
                raise TransitionError(
                    "Portfolio Decision withdrawal manifest does not bind its exact basis"
                )
            try:
                durable_manifest_bytes = self.evidence.read_verified(
                    manifest_artifact_hash
                )
                durable_report_bytes = self.evidence.read_verified(
                    manifest.report_artifact_hash
                )
                durable_manifest = PortfolioDecisionWithdrawalManifest.from_bytes(
                    durable_manifest_bytes
                )
                durable_manifest.require_report(durable_report_bytes)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                raise RecoveryRequired(
                    "Portfolio Decision withdrawal evidence changed before commit"
                ) from exc
            if (
                durable_manifest_bytes != manifest_bytes
                or durable_report_bytes != report_bytes
                or durable_manifest != manifest
            ):
                raise RecoveryRequired(
                    "Portfolio Decision withdrawal evidence changed before commit"
                )
            body = self._body(current)
            replacement_action: dict[str, Any] = {
                "kind": "portfolio_decision",
                "portfolio_snapshot_id": decision.payload["portfolio_snapshot_id"],
            }
            constraints = decision.payload.get("scheduler_constraints")
            if constraints is not None:
                if (
                    not isinstance(constraints, dict)
                    or set(constraints)
                    != {"constraint_source_id", "required_target_axis_ids"}
                ):
                    raise RecoveryRequired(
                        "withdrawn Decision scheduler constraints are malformed"
                    )
                required = constraints.get("required_target_axis_ids")
                source = constraints.get("constraint_source_id")
                if required is not None:
                    if (
                        not isinstance(required, list)
                        or not required
                        or required != sorted(set(required))
                        or any(type(item) is not str for item in required)
                        or any(item not in eligible_axis_ids for item in required)
                        or manifest.target_axis_id not in required
                    ):
                        raise RecoveryRequired(
                            "withdrawn Decision target constraints are malformed"
                        )
                    replacement_action["required_target_axis_ids"] = list(required)
                if source is not None:
                    if (
                        type(source) is not str
                        or not source
                        or not source.isascii()
                    ):
                        raise RecoveryRequired(
                            "withdrawn Decision constraint source is malformed"
                        )
                    replacement_action["constraint_source_id"] = source
                if required is not None and source is None:
                    raise RecoveryRequired(
                        "withdrawn Decision constrained axes lack their source"
                    )
            diagnosis_id = decision.payload.get("study_diagnosis_id")
            if isinstance(diagnosis_id, str):
                replacement_action["study_diagnosis_id"] = diagnosis_id
            review_id = decision.payload.get("architecture_review_id")
            if isinstance(review_id, str):
                review = index.get("architecture-review", review_id)
                if review is None or review.payload.get("mission_id") != mission_id:
                    raise RecoveryRequired(
                        "withdrawn Decision architecture review is unavailable"
                    )
                replacement_action["architecture_review_id"] = review_id
                conclusion = review.payload.get("conclusion")
                if conclusion == "rotate_architecture":
                    replacement_action["excluded_architecture_family"] = (
                        self._review_resolved_architecture_family(
                            index=index,
                            review=review,
                        )
                    )
                elif conclusion == "change_research_layer":
                    replacement_action["excluded_research_layers"] = sorted(
                        review.payload.get("primary_research_layers", [])
                    )
                else:
                    raise RecoveryRequired(
                        "withdrawn Decision architecture review is malformed"
                    )
            body["next_action"] = replacement_action
            record_id = canonical_digest(
                domain="portfolio-decision-withdrawal",
                payload={
                    "manifest": manifest.to_identity_payload(),
                    "manifest_artifact_hash": manifest_artifact_hash,
                },
            )
            record = _record(
                kind="portfolio-decision-withdrawal",
                record_id=record_id,
                subject=f"Mission:{mission_id}",
                status="withdrawn_pre_execution",
                fingerprint=decision.fingerprint,
                payload={
                    "decision_id": manifest.decision_id,
                    "manifest": manifest.to_identity_payload(),
                    "manifest_artifact_hash": manifest_artifact_hash,
                    "replacement_next_action": replacement_action,
                },
                event_stream=(
                    f"portfolio-decision-status:{manifest.decision_id}"
                ),
                event_sequence=1,
            )
            return body, [record], {
                "decision_id": manifest.decision_id,
                "withdrawal_record_id": record_id,
            }

        return self._commit(
            event_kind="portfolio_decision_withdrawn",
            operation_id=operation_id,
            subject="Portfolio:active",
            payload={
                "manifest": manifest.to_identity_payload(),
                "manifest_artifact_hash": manifest_artifact_hash,
            },
            prepare=prepare,
        )

    def _require_historical_validity_override(
        self,
        index: LocalIndex,
        *,
        override: Any,
        executable_id: str,
        declaration: IndexRecord,
    ) -> None:
        """Verify that an additive validity override is an exact dependency fact."""

        from axiom_rift.research.historical_adjudication import (
            HistoricalValidityOverride,
            HistoricalValidityReason,
        )
        from axiom_rift.research.source_authority import (
            AUTHORITY_TRANSITION_EVIDENCE,
            SourceAuthorityAuditManifest,
            SourceAuthorityInvalidation,
            SourceAuthorityLatch,
        )

        if (
            not isinstance(override, HistoricalValidityOverride)
            or override.reason
            is not HistoricalValidityReason.SOURCE_AUTHORITY_INVALIDATED
        ):
            raise TransitionError("historical validity override is unsupported")

        source_id = override.subject_id
        correction = index.get(
            "source-authority-invalidation", override.evidence_record_id
        )
        if correction is None:
            raise TransitionError(
                "historical validity override evidence is unavailable"
            )
        try:
            invalidation = SourceAuthorityInvalidation.from_identity_payload(
                correction.payload["invalidation"]
            )
            manifest = SourceAuthorityAuditManifest.from_mapping(
                correction.payload["audit_manifest"]
            )
            latch = SourceAuthorityLatch.from_mapping(correction.payload["latch"])
            expected_latch = SourceAuthorityLatch.bind(
                invalidation=invalidation,
                manifest=manifest,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TransitionError(
                "historical validity override evidence is malformed"
            ) from exc

        correction_head = index.event_head(f"source-authority:{source_id}")
        if (
            invalidation.identity != override.evidence_record_id
            or invalidation.source_contract_id != source_id
            or correction.subject != f"Source:{source_id}"
            or correction.status != "confirmed_and_suspended"
            or correction.fingerprint
            != override.evidence_record_id.removeprefix(
                "source-authority-invalidation:"
            )
            or correction.event_stream != f"source-authority:{source_id}"
            or correction.event_sequence != 1
            or correction_head is None
            or correction_head.record_kind != correction.kind
            or correction_head.record_id != correction.record_id
            or correction_head.sequence != correction.event_sequence
            or latch != expected_latch
            or latch.source_contract_id != source_id
            or latch.invalidation_id != override.evidence_record_id
            or latch.audit_manifest_hash != invalidation.audit_artifact_hash
        ):
            raise TransitionError(
                "historical validity override does not bind the canonical correction"
            )

        try:
            durable_manifest = SourceAuthorityAuditManifest.from_bytes(
                self.evidence.read_verified(latch.audit_manifest_hash)
            )
            durable_report = self.evidence.read_verified(
                latch.report_artifact_hash
            )
            durable_manifest.require_report(durable_report)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise TransitionError(
                "historical validity override audit evidence is unavailable"
            ) from exc
        if durable_manifest != manifest:
            raise TransitionError(
                "historical validity override audit manifest has drifted"
            )

        original_state = index.get(
            "source-state", invalidation.source_state_record_id
        )
        replacement_id = correction.payload.get("replacement_state_record_id")
        replacement_state = (
            None
            if not isinstance(replacement_id, str)
            else index.get("source-state", replacement_id)
        )
        prior_active_id = correction.payload.get(
            "prior_active_source_state_record_id"
        )
        prior_active_state = (
            None
            if not isinstance(prior_active_id, str)
            else index.get("source-state", prior_active_id)
        )
        source_head = index.event_head(f"source:{source_id}")
        preserved_receipt_id = correction.payload.get("preserved_receipt_id")
        ordinary_suspended = (
            original_state is not None
            and prior_active_state is not None
            and original_state.record_id != prior_active_state.record_id
        )
        if (
            original_state is None
            or original_state.subject != f"Source:{source_id}"
            or original_state.status != "runtime_eligible"
            or original_state.fingerprint != source_id
            or original_state.event_stream != f"source:{source_id}"
            or replacement_state is None
            or replacement_state.subject != f"Source:{source_id}"
            or replacement_state.status != "suspended"
            or replacement_state.fingerprint != source_id
            or replacement_state.event_stream != f"source:{source_id}"
            or original_state.event_sequence is None
            or prior_active_state is None
            or prior_active_state.event_sequence is None
            or replacement_state.event_sequence
            != prior_active_state.event_sequence + 1
            or source_head is None
            or source_head.record_kind != "source-state"
            or source_head.record_id != replacement_state.record_id
            or source_head.sequence != replacement_state.event_sequence
            or replacement_state.payload.get("transition_evidence")
            != AUTHORITY_TRANSITION_EVIDENCE
            or replacement_state.payload.get("source_authority_latch")
            != latch.to_identity_payload()
            or correction.payload.get("eligible_source_state_record_id")
            != original_state.record_id
            or replacement_state.payload.get("eligible_source_state_record_id")
            != original_state.record_id
            or replacement_state.payload.get(
                "prior_active_source_state_record_id"
            )
            != prior_active_state.record_id
            or replacement_state.payload.get("evidence_receipt_id")
            != preserved_receipt_id
            or original_state.payload.get("evidence_receipt_id")
            != preserved_receipt_id
            or replacement_state.payload.get("receipt")
            != original_state.payload.get("receipt")
            or (
                ordinary_suspended
                and (
                    prior_active_state.status != "suspended"
                    or prior_active_state.event_sequence
                    != original_state.event_sequence + 1
                    or prior_active_state.payload.get("transition_evidence")
                    != "drift"
                    or prior_active_state.payload.get("source_authority_latch")
                    is not None
                    or any(
                        prior_active_state.payload.get(field)
                        != original_state.payload.get(field)
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
                )
            )
        ):
            raise TransitionError(
                "historical validity override source suspension is not durable"
            )

        spec = declaration.payload.get("spec")
        trial = index.get("trial", executable_id)
        executable = None if trial is None else trial.payload.get("executable")
        sources = (
            None if not isinstance(executable, dict) else executable.get("source_contracts")
        )
        if (
            not isinstance(spec, dict)
            or spec.get("evidence_subject")
            != {"kind": "Executable", "id": executable_id}
            or trial is None
            or trial.record_id != executable_id
            or trial.status != "evaluated"
            or not isinstance(executable, dict)
            or canonical_digest(domain="executable", payload=executable)
            != executable_id.removeprefix("executable:")
            or not isinstance(sources, list)
            or source_id not in sources
        ):
            raise TransitionError(
                "historical validity override is not bound to the completed trial"
            )

    def _writer_derived_historical_validity_overrides(
        self,
        index: LocalIndex,
        *,
        executable_id: str,
        declaration: IndexRecord,
        prior: IndexRecord | None,
    ) -> tuple[Any, ...]:
        """Derive the monotone validity facts for one legacy completion.

        A request may describe these facts, but it cannot create, omit, or
        withdraw them.  The durable source-authority streams and any prior
        additive overlay are the only inputs to this projection.
        """

        from axiom_rift.research.historical_adjudication import (
            HistoricalValidityOverride,
            HistoricalValidityReason,
        )

        trial = index.get("trial", executable_id)
        executable = None if trial is None else trial.payload.get("executable")
        sources = (
            None
            if not isinstance(executable, dict)
            else executable.get("source_contracts")
        )
        if (
            trial is None
            or trial.record_id != executable_id
            or trial.status != "evaluated"
            or not isinstance(executable, dict)
            or canonical_digest(domain="executable", payload=executable)
            != executable_id.removeprefix("executable:")
            or not isinstance(sources, list)
            or any(type(source_id) is not str for source_id in sources)
            or len(sources) != len(set(sources))
        ):
            raise TransitionError(
                "historical validity projection lacks the exact completed trial"
            )

        overrides_by_subject: dict[str, Any] = {}
        if prior is not None:
            raw_prior = prior.payload.get("validity_overrides")
            if not isinstance(raw_prior, list):
                raise RecoveryRequired(
                    "prior historical validity projection is malformed"
                )
            try:
                prior_overrides = tuple(
                    HistoricalValidityOverride(
                        reason=HistoricalValidityReason(item["reason"]),
                        subject_id=item["subject_id"],
                        evidence_record_id=item["evidence_record_id"],
                    )
                    for item in raw_prior
                    if isinstance(item, dict)
                    and set(item)
                    == {"evidence_record_id", "reason", "subject_id"}
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise RecoveryRequired(
                    "prior historical validity projection is malformed"
                ) from exc
            if len(prior_overrides) != len(raw_prior):
                raise RecoveryRequired(
                    "prior historical validity projection is malformed"
                )
            for override in prior_overrides:
                self._require_historical_validity_override(
                    index,
                    override=override,
                    executable_id=executable_id,
                    declaration=declaration,
                )
                previous = overrides_by_subject.setdefault(
                    override.subject_id, override
                )
                if previous != override:
                    raise RecoveryRequired(
                        "prior historical validity projection conflicts"
                    )

        for source_id in sorted(sources):
            correction_head = index.event_head(f"source-authority:{source_id}")
            if correction_head is None:
                continue
            if correction_head.record_kind != "source-authority-invalidation":
                raise RecoveryRequired(
                    "source authority correction head is malformed"
                )
            try:
                override = HistoricalValidityOverride(
                    reason=(
                        HistoricalValidityReason.SOURCE_AUTHORITY_INVALIDATED
                    ),
                    subject_id=source_id,
                    evidence_record_id=correction_head.record_id,
                )
            except (TypeError, ValueError) as exc:
                raise RecoveryRequired(
                    "source authority correction identity is malformed"
                ) from exc
            self._require_historical_validity_override(
                index,
                override=override,
                executable_id=executable_id,
                declaration=declaration,
            )
            previous = overrides_by_subject.setdefault(source_id, override)
            if previous != override:
                raise RecoveryRequired(
                    "historical validity correction cannot be replaced"
                )

        return tuple(
            sorted(
                overrides_by_subject.values(),
                key=lambda item: (
                    item.reason.value,
                    item.subject_id,
                    item.evidence_record_id,
                ),
            )
        )

    def record_historical_scientific_adjudications(
        self,
        *,
        requests: Sequence[Any],
        audit_artifact_hash: str,
        operation_id: str,
    ) -> TransitionResult:
        """Add claim-scoped interpretations without rewriting legacy evidence."""

        from axiom_rift.research.historical_adjudication import (
            HistoricalAdjudicationRequest,
            HistoricalScientificAdjudication,
            derive_historical_adjudication,
            profile_manifest,
        )
        from axiom_rift.research.adjudication import AdjudicationProfile

        _require_digest("historical audit artifact", audit_artifact_hash)
        self.evidence.verify(audit_artifact_hash)
        normalized = tuple(requests)
        if (
            not normalized
            or any(
                not isinstance(item, HistoricalAdjudicationRequest)
                for item in normalized
            )
            or len({item.completion_record_id for item in normalized})
            != len(normalized)
        ):
            raise TransitionError(
                "historical adjudication requires unique typed completion requests"
            )
        normalized = tuple(
            sorted(normalized, key=lambda item: item.completion_record_id)
        )
        request_manifest = [
            {
                "completion_record_id": item.completion_record_id,
                "disposition": item.disposition.value,
                "profile": profile_manifest(item.profile),
                "reason_codes": list(item.reason_codes),
                "replay_priority": item.replay_priority.value,
                "validity_overrides": [
                    override.manifest() for override in item.validity_overrides
                ],
            }
            for item in normalized
        ]
        self._require_study_close_delivery_guard()

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("historical adjudication requires control")
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
                    "historical adjudication requires the active stable Portfolio boundary"
                )

            memory_by_subject: dict[tuple[str, str], list[str]] = {}
            for memory in index.records_by_kind("negative-memory"):
                study_id = memory.payload.get("study_id")
                executable_id = memory.subject.removeprefix("Executable:")
                if isinstance(study_id, str) and isinstance(executable_id, str):
                    memory_by_subject.setdefault(
                        (study_id, executable_id), []
                    ).append(memory.record_id)

            records: list[IndexRecord] = []
            derived: list[HistoricalScientificAdjudication] = []
            for request in normalized:
                completion = index.get(
                    "job-completed", request.completion_record_id
                )
                scientific = (
                    None
                    if completion is None
                    else completion.payload.get("scientific")
                )
                declaration = (
                    None
                    if completion is None
                    else index.get(
                        "job-declared", completion.payload.get("job_id", "")
                    )
                )
                if (
                    completion is None
                    or completion.status not in {
                        "failed",
                        "not_evaluable",
                        "success",
                    }
                    or not isinstance(scientific, dict)
                    or declaration is None
                ):
                    raise TransitionError(
                        "historical adjudication completion is unavailable"
                    )
                if "adjudication" in scientific:
                    raise TransitionError(
                        "historical adjudication is restricted to legacy completions "
                        "without rich v2 adjudication"
                    )
                study_id = declaration.payload.get("study_id")
                executable_id = scientific.get("executable_id")
                plan_hash = scientific.get("validation_plan_hash")
                measurement_hashes = scientific.get(
                    "measurement_artifact_hashes"
                )
                verdict = scientific.get("verdict")
                if (
                    not isinstance(study_id, str)
                    or not isinstance(executable_id, str)
                    or not isinstance(plan_hash, str)
                    or not isinstance(measurement_hashes, list)
                    or len(measurement_hashes) != 1
                    or not isinstance(measurement_hashes[0], str)
                    or verdict not in {"passed", "failed", "not_evaluable"}
                ):
                    raise TransitionError(
                        "historical adjudication scientific provenance is malformed"
                    )
                measurement_hash = measurement_hashes[0]
                _require_digest("historical validation plan", plan_hash)
                _require_digest("historical measurement", measurement_hash)
                outputs = completion.payload.get("outputs")
                spec = declaration.payload.get("spec")
                if (
                    not isinstance(outputs, dict)
                    or plan_hash not in outputs.values()
                    or measurement_hash not in outputs.values()
                    or not isinstance(spec, dict)
                    or plan_hash not in spec.get("input_hashes", [])
                ):
                    raise TransitionError(
                        "historical adjudication artifacts are not completion-bound"
                    )
                try:
                    plan = parse_canonical(self.evidence.read_verified(plan_hash))
                    measurement = parse_canonical(
                        self.evidence.read_verified(measurement_hash)
                    )
                except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                    raise TransitionError(
                        "historical adjudication evidence is unavailable"
                    ) from exc
                if not isinstance(plan, dict) or not isinstance(measurement, dict):
                    raise TransitionError(
                        "historical adjudication evidence is not a mapping"
                    )
                if (
                    plan.get("schema") != "scientific_validation_plan.v1"
                    or measurement.get("schema") != "scientific_measurement.v1"
                ):
                    raise TransitionError(
                        "historical adjudication requires exact legacy v1 artifacts"
                    )
                if (
                    plan.get("executable_id") != executable_id
                    or measurement.get("executable_id") != executable_id
                    or plan.get("mission_id")
                    != declaration.payload.get("mission_id")
                    or measurement.get("mission_id")
                    != declaration.payload.get("mission_id")
                ):
                    raise TransitionError(
                        "historical adjudication subject binding is invalid"
                    )
                fixed_profile = AdjudicationProfile()
                if request.profile != fixed_profile:
                    raise TransitionError(
                        "historical adjudication profile differs from the "
                        "Writer-derived fixed legacy audit profile"
                    )
                stream = f"historical-adjudication:{completion.record_id}"
                head = index.event_head(stream)
                prior = (
                    None
                    if head is None
                    else index.get(head.record_kind, head.record_id)
                )
                if head is not None and (
                    prior is None
                    or prior.kind != "historical-scientific-adjudication"
                    or prior.event_stream != stream
                    or prior.event_sequence != head.sequence
                ):
                    raise RecoveryRequired(
                        "historical adjudication stream head is malformed"
                    )
                derived_overrides = (
                    self._writer_derived_historical_validity_overrides(
                        index,
                        executable_id=executable_id,
                        declaration=declaration,
                        prior=prior,
                    )
                )
                if request.validity_overrides != derived_overrides:
                    raise TransitionError(
                        "historical validity overrides differ from "
                        "Writer-derived durable source-authority latches"
                    )
                study = index.get("study-open", study_id)
                close_records = tuple(
                    record
                    for outcome in _STUDY_OUTCOMES
                    for record in index.records_by_subject_status(
                        f"Study:{study_id}", outcome
                    )
                    if record.kind == "study-close"
                )
                if study is None or len(close_records) != 1:
                    raise TransitionError(
                        "historical adjudication Study close is unavailable"
                    )
                close = close_records[0]
                try:
                    item = derive_historical_adjudication(
                        audit_artifact_hash=audit_artifact_hash,
                        study_id=study_id,
                        study_close_record_id=close.record_id,
                        completion_record_id=completion.record_id,
                        executable_id=executable_id,
                        validation_plan_hash=plan_hash,
                        measurement_artifact_hash=measurement_hash,
                        original_job_status=completion.status,
                        original_scientific_verdict=verdict,
                        plan=plan,
                        measurement=measurement,
                        request=request,
                        negative_memory_ids=tuple(
                            memory_by_subject.get(
                                (study_id, executable_id), ()
                            )
                        ),
                    )
                except ValueError as exc:
                    raise TransitionError(
                        "historical adjudication derivation failed"
                    ) from exc
                if item.adjudication.legacy_verdict != verdict:
                    raise TransitionError(
                        "historical adjudication does not reproduce the legacy verdict"
                    )
                sequence = 1 if head is None else head.sequence + 1
                prior_record_id = None if head is None else head.record_id
                payload = {
                    **item.to_identity_payload(),
                    "supersedes_record_id": prior_record_id,
                    "trial_delta": 0,
                    "holdout_delta": 0,
                    "candidate_delta": 0,
                    "claim_authority": "additive_qualification_only",
                    "profile_authority": "writer_derived_fixed_legacy_v1",
                    "validity_override_authority": (
                        "writer_derived_durable_source_latches"
                    ),
                }
                records.append(
                    _record(
                        kind="historical-scientific-adjudication",
                        record_id=item.identity,
                        subject=f"Study:{study_id}",
                        status=item.disposition.value,
                        fingerprint=item.identity.removeprefix(
                            "historical-adjudication:"
                        ),
                        payload=payload,
                        event_stream=stream,
                        event_sequence=sequence,
                    )
                )
                derived.append(item)
            return self._body(current), records, {
                "adjudication_record_ids": [item.identity for item in derived],
                "audit_artifact_hash": audit_artifact_hash,
                "candidate_delta": 0,
                "holdout_delta": 0,
                "trial_delta": 0,
            }

        return self._commit(
            event_kind="historical_scientific_adjudications_recorded",
            operation_id=operation_id,
            subject="ProjectGoal:OPERATING_DIRECTION.md",
            payload={
                "audit_artifact_hash": audit_artifact_hash,
                "requests": request_manifest,
            },
            prepare=prepare,
        )

    def _require_study_close_delivery_guard(self) -> None:
        if self.engineering_fixture or not (self.root / ".git").exists():
            return
        from axiom_rift.operations.study_close_git import (
            StudyCloseDeliveryError,
            require_all_study_close_deliveries,
            require_study_close_guard_ready,
        )

        try:
            require_study_close_guard_ready(self.root)
            require_all_study_close_deliveries(self.root)
        except (OSError, RuntimeError, StudyCloseDeliveryError) as exc:
            raise TransitionError(
                "Scientific transition is blocked by the Study-close Git guard"
            ) from exc

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
            evidence_study_ids: set[str] = set()
            for reference in memory.evidence_references:
                evidence = index.get("job-completed", reference)
                failure = None if evidence is None else evidence.payload.get("failure")
                scientific = None if evidence is None else evidence.payload.get("scientific")
                legacy_scientific_failure = (
                    evidence is not None
                    and evidence.status == "failed"
                    and isinstance(failure, dict)
                    and failure.get("failure_kind") == "scientific_falsification"
                )
                operationally_successful_falsification = (
                    evidence is not None
                    and evidence.status == "success"
                    and failure is None
                )
                if (
                    evidence is None
                    or not (
                        legacy_scientific_failure
                        or operationally_successful_falsification
                    )
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
                evidence_study_id = (
                    None
                    if declaration is None
                    else declaration.payload.get("study_id")
                )
                evidence_study = (
                    None
                    if not isinstance(evidence_study_id, str)
                    else index.get("study-open", evidence_study_id)
                )
                same_study_context = (
                    declaration is not None
                    and evidence_study is not None
                    and evidence_study.payload.get("mission_id") == mission_id
                    and evidence_study.payload.get("material_identity")
                    == trial.payload.get("material_identity")
                    and evidence_study.payload.get("portfolio_axis_identity")
                    == trial.payload.get("portfolio_axis_identity")
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
                if same_study_context:
                    assert isinstance(evidence_study_id, str)
                    evidence_study_ids.add(evidence_study_id)
            if len(evidence_study_ids) > 1:
                raise TransitionError(
                    "negative memory evidence spans multiple Study contexts"
                )
            memory_study_id = (
                next(iter(evidence_study_ids))
                if evidence_study_ids
                else trial_study_id
            )
            memory_study = index.get("study-open", memory_study_id)
            if memory_study is None:
                raise TransitionError("negative memory Study context is unavailable")
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
                    "portfolio_axis_id": memory_study.payload.get(
                        "portfolio_axis_id"
                    ),
                    "portfolio_axis_identity": memory_study.payload.get(
                        "portfolio_axis_identity"
                    ),
                    "portfolio_snapshot_id": memory_study.payload.get(
                        "portfolio_snapshot_id"
                    ),
                    "study_id": memory_study_id,
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
        validator_facts = dict(validated.facts)
        executed_modes = validator_facts.pop("executed_evidence_modes", None)
        adjudication = validator_facts.pop("scientific_adjudication", None)
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
        artifact = self.evidence.verify(result_hash)
        try:
            value = parse_canonical(
                (self.evidence._root / artifact.relative_path).read_bytes()
            )
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
            if failure_manifest["failure_kind"] == "scientific_falsification":
                raise TransitionError(
                    "a validator-derived scientific verdict is not a Job execution failure"
                )
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
            component_parity_binding = declared_spec.get(
                "component_parity_binding"
            )
            component_parity_manifest: dict[str, Any] | None = None
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
                engine_entry_id = job.get("engine_entry_record_id")
                engine_entry = (
                    None
                    if not isinstance(engine_entry_id, str)
                    else _index.get("job-engine-entry", engine_entry_id)
                )
                job_permit_id = start_record.payload.get("job_permit_id")
                permit_stream = (
                    ""
                    if not isinstance(job_permit_id, str)
                    else f"permit:{job_permit_id}"
                )
                consumed = (
                    None
                    if not permit_stream
                    else _index.event_record(permit_stream, 2)
                )
                expected_execution = RunningJobExecution(
                    job_id=job_id,
                    job_hash=job["hash"],
                    start_record_id=start_record_id,
                    job_permit_id=job_permit_id,
                )
                if (
                    engine_entry is None
                    or engine_entry.status != "validated"
                    or engine_entry.subject != f"Job:{job_id}"
                    or engine_entry.fingerprint != job["hash"]
                    or consumed is None
                    or engine_entry.payload
                    != {
                        "execution": expected_execution.payload(),
                        "permit_consumption_record_id": consumed.record_id,
                    }
                    or engine_entry.authority_event_id
                    != start_record.authority_event_id
                    or engine_entry.authority_sequence
                    != start_record.authority_sequence
                ):
                    raise TransitionError(
                        "Job completion lacks its exact engine-entry attestation"
                    )
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
            if scientific_binding is not None and outcome == "success":
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
                )
            if component_parity_binding is not None and outcome == "success":
                if set(output_manifest) != set(expected_outputs):
                    raise TransitionError(
                        "component parity disposition requires every declared output"
                    )
                component_parity_manifest = (
                    self._derive_component_parity_job_evidence(
                        job_id=job_id,
                        job_hash=job["hash"],
                        mission_id=declaration.payload["mission_id"],
                        evidence_subject=declared_spec["evidence_subject"],
                        binding=component_parity_binding,
                        output_manifest=output_manifest,
                        output_classes=output_classes,
                    )
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
            completion_identity_payload = {
                "job_id": job_id,
                "outcome": outcome,
                "outputs": dict(output_manifest),
                "external": external_manifest,
                "runtime": runtime_manifest,
                "scientific": scientific_manifest,
                "source": source_manifest,
            }
            if component_parity_manifest is not None:
                completion_identity_payload["component_parity"] = (
                    component_parity_manifest
                )
            record_id = canonical_digest(
                domain="job-completion",
                payload=completion_identity_payload,
            )
            completion_payload = {
                "job_id": job_id,
                "outputs": dict(output_manifest),
                "output_classes": dict(output_classes),
                "failure": failure_manifest,
                "external": external_manifest,
                "start_record_id": start_record_id,
                "runtime": runtime_manifest,
                "scientific": scientific_manifest,
                "source": source_manifest,
            }
            if component_parity_manifest is not None:
                completion_payload["component_parity"] = component_parity_manifest
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
                or not isinstance(next_action, dict)
                or next_action.get("kind") != "judge_job_evidence"
                or next_action.get("job_id") != completion.payload.get("job_id")
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
                reroute_action: dict[str, Any] | None = None
                if disposition == "accept_component_parity":
                    review_id = decision.payload.get("architecture_review_id")
                    review = (
                        None
                        if not isinstance(review_id, str)
                        else index.get("architecture-review", review_id)
                    )
                    if review is not None and review.payload.get(
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
                    diagnosis = (
                        None
                        if not isinstance(diagnosis_id, str)
                        else index.get("study-diagnosis", diagnosis_id)
                    )
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

    @staticmethod
    def _resolved_candidate_disposition_for_completion(
        index: LocalIndex,
        *,
        completion: IndexRecord,
        mission_id: str,
    ) -> str | None:
        """Return the exact terminal candidate-stream head for one positive.

        Candidate eligibility is authority to enter the candidate lifecycle,
        not a permanent ban on an honest axis disposition.  It is resolved only
        when the Writer-created candidate binds this exact completion and the
        latest executable stream head is its later typed disposition.
        """

        scientific = completion.payload.get("scientific")
        executable_id = (
            None
            if not isinstance(scientific, dict)
            else scientific.get("executable_id")
        )
        if (
            completion.status != "success"
            or not isinstance(scientific, dict)
            or scientific.get("scientific_eligible") is not True
            or scientific.get("candidate_eligible") is not True
            or not isinstance(executable_id, str)
        ):
            return None
        head = index.event_head(f"candidate:{executable_id}")
        disposition = (
            None
            if head is None
            else index.get(head.record_kind, head.record_id)
        )
        candidate_id = (
            None
            if disposition is None
            else disposition.payload.get("candidate_id")
        )
        candidate = (
            None
            if not isinstance(candidate_id, str)
            else index.get("candidate", candidate_id)
        )
        evidence_refs = (
            None if candidate is None else candidate.payload.get("evidence_refs")
        )
        reason = (
            None if disposition is None else disposition.payload.get("reason")
        )
        expected_candidate_id = (
            None
            if not isinstance(evidence_refs, list)
            or any(not isinstance(item, str) for item in evidence_refs)
            else "candidate:"
            + canonical_digest(
                domain="mission-candidate",
                payload={
                    "evidence_refs": sorted(evidence_refs),
                    "executable_id": executable_id,
                    "mission_id": mission_id,
                },
            )
        )
        expected_disposition_id = (
            None
            if disposition is None
            or not isinstance(reason, str)
            or disposition.status
            not in {
                "invalidated",
                "rejected",
                "returned_to_library",
                "superseded",
            }
            else canonical_digest(
                domain="candidate-disposition",
                payload={
                    "candidate_id": candidate_id,
                    "disposition": disposition.status,
                    "reason": reason,
                },
            )
        )
        candidate_stream = f"candidate:{executable_id}"
        if (
            head is None
            or disposition is None
            or disposition.kind != "candidate-disposition"
            or disposition.event_stream != candidate_stream
            or disposition.event_sequence != head.sequence
            or disposition.record_id != expected_disposition_id
            or disposition.subject != f"Executable:{executable_id}"
            or disposition.payload.get("candidate_id") != candidate_id
            or disposition.payload.get("executable_id") != executable_id
            or disposition.payload.get("mission_id") != mission_id
            or candidate is None
            or candidate.record_id != expected_candidate_id
            or candidate.status != "frozen"
            or candidate.event_stream != candidate_stream
            or candidate.event_sequence is None
            or candidate.event_sequence + 1 != disposition.event_sequence
            or candidate.subject != f"Executable:{executable_id}"
            or candidate.fingerprint != executable_id.removeprefix("executable:")
            or disposition.fingerprint != candidate.fingerprint
            or candidate.payload.get("mission_id") != mission_id
            or not isinstance(evidence_refs, list)
            or len(set(evidence_refs)) != len(evidence_refs)
            or evidence_refs != sorted(evidence_refs)
            or completion.record_id not in evidence_refs
            or completion.authority_sequence is None
            or candidate.authority_sequence is None
            or disposition.authority_sequence is None
            or candidate.authority_sequence <= completion.authority_sequence
            or disposition.authority_sequence <= candidate.authority_sequence
        ):
            return None
        return disposition.record_id

    @classmethod
    def _candidate_authority_for_axis_bindings(
        cls,
        index: LocalIndex,
        *,
        references: Sequence[Any],
        bindings: Sequence[Any],
        mission_id: str,
    ) -> tuple[list[dict[str, str]], tuple[str, ...]]:
        resolved: list[dict[str, str]] = []
        unresolved: list[str] = []
        for reference, binding in zip(references, bindings, strict=True):
            if not binding.candidate_eligible:
                continue
            completion = (
                None
                if getattr(reference.kind, "value", None) != "job-completed"
                else index.get("job-completed", reference.record_id)
            )
            disposition_id = (
                None
                if completion is None
                else cls._resolved_candidate_disposition_for_completion(
                    index,
                    completion=completion,
                    mission_id=mission_id,
                )
            )
            if disposition_id is None:
                unresolved.append(reference.record_id)
            else:
                resolved.append(
                    {
                        "candidate_disposition_record_id": disposition_id,
                        "completion_record_id": reference.record_id,
                    }
                )
        return (
            sorted(
                resolved,
                key=lambda item: (
                    item["completion_record_id"],
                    item["candidate_disposition_record_id"],
                ),
            ),
            tuple(sorted(unresolved)),
        )

    def record_axis_dispositions(
        self,
        *,
        dispositions: Sequence[Any],
        operation_id: str,
    ) -> TransitionResult:
        """Record additive evidence-bound axis states without rewriting snapshots."""

        from axiom_rift.operations.axis_disposition import (
            AxisDispositionEvidenceError,
            aggregate_axis_evidence_state,
            derive_axis_evidence_binding,
            required_axis_scientific_references,
        )
        from axiom_rift.research.axis_disposition import (
            AxisDisposition,
            AxisDispositionAction,
            AxisEvidenceKind,
            AxisEvidenceState,
        )

        self._require_study_close_delivery_guard()
        normalized = tuple(dispositions)
        if (
            not normalized
            or any(not isinstance(item, AxisDisposition) for item in normalized)
            or len({item.axis_id for item in normalized}) != len(normalized)
            or len({item.axis_identity for item in normalized}) != len(normalized)
        ):
            raise TransitionError(
                "axis dispositions require unique typed Mission axes"
            )
        normalized = tuple(sorted(normalized, key=lambda item: item.axis_id))

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("axis disposition requires control")
            science = current["scientific"]
            mission_id = science.get("active_mission")
            if not isinstance(mission_id, str) or any(
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
                    "axis disposition requires a stable active Mission boundary"
                )
            next_action = current.get("next_action", {})
            active_initiative = science.get("active_initiative")
            stable_initiative_boundary = (
                isinstance(active_initiative, str)
                and next_action.get("kind") == "portfolio_decision"
            )
            stable_mission_boundary = (
                active_initiative is None
                and next_action
                == {
                    "kind": "choose_next_initiative_or_terminal",
                    "mission_id": mission_id,
                }
            )
            if not (stable_initiative_boundary or stable_mission_boundary):
                raise TransitionError(
                    "axis disposition cannot bypass pending research direction"
                )
            portfolio_head = index.event_head(f"portfolio:{mission_id}")
            snapshot = (
                None
                if portfolio_head is None
                else index.get(portfolio_head.record_kind, portfolio_head.record_id)
            )
            if snapshot is None or snapshot.kind != "portfolio-snapshot":
                raise TransitionError("axis disposition requires a current Portfolio")
            if (
                stable_initiative_boundary
                and next_action.get("portfolio_snapshot_id") != snapshot.record_id
            ):
                raise TransitionError(
                    "axis disposition Portfolio boundary is not current"
                )
            axes = {axis["axis_id"]: axis for axis in snapshot.payload["axes"]}
            records: list[IndexRecord] = []
            accepted_ids: list[str] = []
            for disposition in normalized:
                axis = axes.get(disposition.axis_id)
                if (
                    disposition.mission_id != mission_id
                    or disposition.portfolio_snapshot_id != snapshot.record_id
                    or axis is None
                    or axis.get("axis_identity") != disposition.axis_identity
                ):
                    raise TransitionError(
                        "axis disposition is stale or belongs to another Portfolio"
                    )
                try:
                    required_references = required_axis_scientific_references(
                        index,
                        mission_id=mission_id,
                        axis_id=disposition.axis_id,
                        axis_identity=disposition.axis_identity,
                    )
                    supplied_scientific_references = {
                        (reference.kind, reference.record_id)
                        for reference in disposition.evidence_references
                        if reference.kind is not AxisEvidenceKind.NEGATIVE_MEMORY
                    }
                    exact_required_references = {
                        (reference.kind, reference.record_id)
                        for reference in required_references
                    }
                    if supplied_scientific_references != exact_required_references:
                        raise AxisDispositionEvidenceError(
                            "axis disposition omits or supersedes scientific history"
                        )
                    bindings = tuple(
                        derive_axis_evidence_binding(
                            index,
                            reference=reference,
                            mission_id=mission_id,
                            axis_id=disposition.axis_id,
                            axis_identity=disposition.axis_identity,
                        )
                        for reference in disposition.evidence_references
                    )
                    effective_state = aggregate_axis_evidence_state(bindings)
                except AxisDispositionEvidenceError as exc:
                    raise TransitionError(str(exc)) from exc
                (
                    resolved_candidate_authority,
                    unresolved_candidate_completions,
                ) = self._candidate_authority_for_axis_bindings(
                    index,
                    references=disposition.evidence_references,
                    bindings=bindings,
                    mission_id=mission_id,
                )
                if unresolved_candidate_completions:
                    raise TransitionError(
                        "candidate-eligible evidence remains unresolved by its "
                        "candidate/disposition stream: "
                        + ", ".join(sorted(unresolved_candidate_completions))
                    )
                if effective_state is not disposition.evidence_state:
                    raise TransitionError(
                        "axis disposition differs from its Writer-derived evidence state"
                    )
                negative_memory_ids = sorted(
                    {
                        memory_id
                        for binding in bindings
                        for memory_id in binding.negative_memory_ids
                    }
                )
                scientifically_exhausted = bool(
                    effective_state is AxisEvidenceState.LOW_INFORMATION
                    and disposition.action
                    is AxisDispositionAction.RETIRE_WITH_REASON
                    and negative_memory_ids
                )
                if (
                    effective_state is AxisEvidenceState.LOW_INFORMATION
                    and disposition.action
                    is AxisDispositionAction.RETIRE_WITH_REASON
                    and not scientifically_exhausted
                ):
                    raise TransitionError(
                        "low-information retirement requires durable negative memory"
                    )
                stream = (
                    f"axis-disposition:{mission_id}:{disposition.axis_identity}"
                )
                head = index.event_head(stream)
                if head is not None and head.record_id == disposition.identity:
                    raise TransitionError("axis disposition is already current")
                sequence = 1 if head is None else head.sequence + 1
                payload = {
                    **disposition.to_identity_payload(),
                    "candidate_eligible": False,
                    "candidate_delta": 0,
                    "claim_delta": "none",
                    "derived_evidence_states": sorted(
                        {item.state.value for item in bindings}
                    ),
                    "holdout_delta": 0,
                    "negative_memory_ids": negative_memory_ids,
                    "resolved_candidate_authority": resolved_candidate_authority,
                    "scientifically_exhausted": scientifically_exhausted,
                    "supersedes_record_id": None if head is None else head.record_id,
                    "trial_delta": 0,
                }
                records.append(
                    _record(
                        kind="axis-disposition",
                        record_id=disposition.identity,
                        subject=f"Axis:{disposition.axis_identity}",
                        status=disposition.action.value,
                        fingerprint=disposition.identity.removeprefix(
                            "axis-disposition:"
                        ),
                        payload=payload,
                        event_stream=stream,
                        event_sequence=sequence,
                    )
                )
                accepted_ids.append(disposition.identity)
            return self._body(current), records, {
                "axis_disposition_record_ids": accepted_ids,
                "candidate_delta": 0,
                "claim_delta": "none",
                "holdout_delta": 0,
                "trial_delta": 0,
            }

        return self._commit(
            event_kind="axis_dispositions_recorded",
            operation_id=operation_id,
            subject="Mission:active",
            payload={
                "dispositions": [
                    item.to_identity_payload() for item in normalized
                ]
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
        from axiom_rift.operations.axis_disposition import (
            AxisDispositionEvidenceError,
            aggregate_axis_evidence_state,
            derive_axis_evidence_binding,
            required_axis_scientific_references,
        )
        from axiom_rift.research.axis_disposition import (
            AxisDispositionAction,
            AxisEvidenceKind,
            AxisEvidenceReference,
            AxisEvidenceState,
        )

        self._require_study_close_delivery_guard()
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
            if current["next_action"] != {
                "kind": "choose_next_initiative_or_terminal",
                "mission_id": science["active_mission"],
            }:
                raise TransitionError(
                    "exhaustion audit requires the exact Mission terminal boundary"
                )
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
            research_layers = {
                axis.get("primary_research_layer") for axis in axes.values()
            }
            resolved_architectures = [
                self._axis_architecture_anchor(index, axis)
                for axis in axes.values()
            ]
            architecture_families = {
                (
                    self._resolved_architecture_family(
                        index=index,
                        architecture_payload=anchor["architecture_chassis"],
                    )
                    if isinstance(anchor.get("architecture_chassis"), dict)
                    else anchor["architecture_chassis_identity"]
                )
                for anchor in resolved_architectures
                if anchor is not None
            }
            standard = snapshot.payload.get("exhaustion_standard")
            if not isinstance(standard, dict):
                raise TransitionError(
                    "exhaustion Portfolio lacks its preregistered standard"
                )
            if (
                set(normalized) != set(axes)
                or len(axes) < standard["minimum_axes"]
                or len(families) < standard["minimum_mechanism_families"]
                or len(research_layers)
                < standard["minimum_primary_research_layers"]
                or len(architecture_families)
                < standard["minimum_system_architecture_families"]
                or any(anchor is None for anchor in resolved_architectures)
                or None in research_layers
            ):
                raise TransitionError(
                    "exhaustion does not cover its preregistered axes and families"
                )
            family_executables: dict[str, set[str]] = {
                family: set() for family in families
            }
            axis_studies: dict[str, set[str]] = {axis_id: set() for axis_id in axes}
            axis_modes: dict[str, set[str]] = {axis_id: set() for axis_id in axes}
            global_executables: set[str] = set()
            scientifically_exhausted_axes: set[str] = set()
            carried_forward_axes: set[str] = set()
            retired_families: set[str] = set()
            disposition_summaries: dict[str, dict[str, Any]] = {}
            for axis_id, references in normalized.items():
                axis_identity = axes[axis_id]["axis_identity"]
                stream = (
                    f"axis-disposition:{science['active_mission']}:{axis_identity}"
                )
                head = index.event_head(stream)
                disposition = (
                    None
                    if head is None
                    else index.get(head.record_kind, head.record_id)
                )
                if (
                    disposition is None
                    or disposition.kind != "axis-disposition"
                    or disposition.payload.get("mission_id")
                    != science["active_mission"]
                    or disposition.payload.get("portfolio_snapshot_id")
                    != snapshot.record_id
                    or disposition.payload.get("axis_id") != axis_id
                    or disposition.payload.get("axis_identity") != axis_identity
                    or disposition.payload.get("candidate_eligible") is not False
                    or disposition.authority_sequence is None
                    or snapshot.authority_sequence is None
                    or disposition.authority_sequence
                    <= snapshot.authority_sequence
                ):
                    raise TransitionError(
                        "every axis requires its latest evidence-bound disposition"
                    )
                evidence_manifest = disposition.payload.get(
                    "evidence_references"
                )
                if not isinstance(evidence_manifest, list) or not evidence_manifest:
                    raise TransitionError(
                        "axis disposition evidence manifest is malformed"
                    )
                try:
                    typed_references = tuple(
                        AxisEvidenceReference(
                            kind=AxisEvidenceKind(reference["kind"]),
                            record_id=reference["record_id"],
                        )
                        for reference in evidence_manifest
                        if isinstance(reference, dict)
                        and set(reference) == {"kind", "record_id"}
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise TransitionError(
                        "axis disposition evidence manifest is malformed"
                    ) from exc
                if len(typed_references) != len(evidence_manifest):
                    raise TransitionError(
                        "axis disposition evidence manifest is malformed"
                    )
                expected_references = {
                    ("axis-disposition", disposition.record_id),
                    *{
                        (reference.kind.value, reference.record_id)
                        for reference in typed_references
                    },
                }
                supplied_references = {
                    (reference["kind"], reference["record_id"])
                    for reference in references
                }
                if (
                    len(supplied_references) != len(references)
                    or supplied_references != expected_references
                ):
                    raise TransitionError(
                        "exhaustion frontier differs from its exact axis disposition"
                    )
                try:
                    required_references = required_axis_scientific_references(
                        index,
                        mission_id=science["active_mission"],
                        axis_id=axis_id,
                        axis_identity=axis_identity,
                    )
                    supplied_scientific_references = {
                        (reference.kind, reference.record_id)
                        for reference in typed_references
                        if reference.kind is not AxisEvidenceKind.NEGATIVE_MEMORY
                    }
                    exact_required_references = {
                        (reference.kind, reference.record_id)
                        for reference in required_references
                    }
                    if supplied_scientific_references != exact_required_references:
                        raise AxisDispositionEvidenceError(
                            "axis disposition no longer covers scientific history"
                        )
                    bindings = tuple(
                        derive_axis_evidence_binding(
                            index,
                            reference=reference,
                            mission_id=science["active_mission"],
                            axis_id=axis_id,
                            axis_identity=axis_identity,
                        )
                        for reference in typed_references
                    )
                    effective_state = aggregate_axis_evidence_state(bindings)
                    action = AxisDispositionAction(disposition.status)
                except (AxisDispositionEvidenceError, ValueError) as exc:
                    raise TransitionError(str(exc)) from exc
                (
                    resolved_candidate_authority,
                    unresolved_candidate_completions,
                ) = self._candidate_authority_for_axis_bindings(
                    index,
                    references=typed_references,
                    bindings=bindings,
                    mission_id=science["active_mission"],
                )
                if (
                    unresolved_candidate_completions
                    or disposition.payload.get("resolved_candidate_authority")
                    != resolved_candidate_authority
                    or disposition.payload.get("evidence_state")
                    != effective_state.value
                    or disposition.payload.get("action") != action.value
                ):
                    raise TransitionError(
                        "axis disposition no longer matches its scientific evidence"
                    )
                evidence_records = [
                    index.get(reference.kind.value, reference.record_id)
                    for reference in typed_references
                ]
                if any(
                    record is None
                    or record.authority_sequence is None
                    or record.authority_sequence
                    >= disposition.authority_sequence
                    for record in evidence_records
                ):
                    raise TransitionError(
                        "axis disposition does not postdate its exact evidence"
                    )
                for binding in bindings:
                    axis_studies[axis_id].update(binding.study_ids)
                    axis_modes[axis_id].update(binding.evidence_modes)
                negative_bindings = tuple(
                    binding for binding in bindings if binding.negative_memory_ids
                )
                scientifically_exhausted = bool(
                    effective_state is AxisEvidenceState.LOW_INFORMATION
                    and action is AxisDispositionAction.RETIRE_WITH_REASON
                    and negative_bindings
                )
                if (
                    disposition.payload.get("scientifically_exhausted")
                    is not scientifically_exhausted
                ):
                    raise TransitionError(
                        "axis scientific-exhaustion projection has drifted"
                    )
                if scientifically_exhausted:
                    family = axes[axis_id]["mechanism_family"]
                    retired_families.add(family)
                    scientifically_exhausted_axes.add(axis_id)
                    for binding in negative_bindings:
                        for executable_id in binding.executable_ids:
                            if executable_id in global_executables:
                                raise TransitionError(
                                    "negative Executable is reused across axis dispositions"
                                )
                            global_executables.add(executable_id)
                            family_executables[family].add(executable_id)
                else:
                    carried_forward_axes.add(axis_id)
                disposition_summaries[axis_id] = {
                    "action": action.value,
                    "axis_disposition_record_id": disposition.record_id,
                    "continuation_or_reopen_condition": disposition.payload.get(
                        "continuation_or_reopen_condition"
                    ),
                    "evidence_state": effective_state.value,
                    "scientifically_exhausted": scientifically_exhausted,
                }
            if not scientifically_exhausted_axes:
                raise TransitionError(
                    "exhaustion requires at least one genuinely scientifically "
                    "exhausted axis"
                )
            required_modes = set(standard["required_evidence_modes"])
            for axis_id in scientifically_exhausted_axes:
                if (
                    len(axis_studies[axis_id])
                    < standard["minimum_distinct_studies_per_axis"]
                    or not required_modes.issubset(axis_modes[axis_id])
                ):
                    raise TransitionError(
                        "scientifically exhausted axis lacks preregistered depth"
                    )
            if any(
                len(family_executables[family])
                < standard["minimum_negative_executables_per_family"]
                for family in retired_families
            ):
                raise TransitionError(
                    "retired negative family is below its preregistered depth"
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
                if self._resolved_candidate_disposition_for_completion(
                    index,
                    completion=completion,
                    mission_id=science["active_mission"],
                ) is None:
                    unresolved_positive_axes.add(axis_id)
            if unresolved_positive_axes:
                raise TransitionError(
                    "candidate-eligible positive evidence remains unresolved on: "
                    + ", ".join(sorted(unresolved_positive_axes))
                )
            audit_payload = {
                "axis_dispositions": disposition_summaries,
                "carried_forward_axis_ids": sorted(carried_forward_axes),
                "diversity_basis": diversity_basis,
                "frontiers": normalized,
                "mechanism_families": sorted(families),
                "primary_research_layers": sorted(research_layers),
                "system_architecture_families": sorted(architecture_families),
                "opportunity_cost_audit": opportunity_cost_audit,
                "portfolio_snapshot_id": snapshot.record_id,
                "preregistered_exhaustion_standard": standard,
                "scientifically_exhausted_axis_ids": sorted(
                    scientifically_exhausted_axes
                ),
                "unique_negative_executable_count": len(global_executables),
                "unresolved_candidate_eligible_axes": sorted(
                    unresolved_positive_axes
                ),
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
        self._require_study_close_delivery_guard()
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
            mission_open = index.get("mission-open", mission_id)
            if mission_open is None:
                raise TransitionError("Mission open record is absent")
            mission_ordinal = mission_open.payload.get("mission_ordinal", 1)
            if type(mission_ordinal) is not int or mission_ordinal < 1:
                raise TransitionError("Mission ordinal is invalid")
            project_goal_authority = mission_open.payload.get(
                "project_goal_authority",
                body["authority"]["operating_direction"],
            )
            project_goal_complete = outcome == "completed_pre_live_handoff"
            science["active_holdout_evaluation"] = None
            if project_goal_complete:
                science["required_future_holdout_id"] = None
            science["active_mission"] = None
            self._drop_authorization(body, SubjectKind.MISSION, mission_id)
            record_id = canonical_digest(
                domain="mission-close",
                payload={"mission_id": mission_id, "outcome": outcome, "basis": basis_record_id},
            )
            if outcome == "closed_no_candidate":
                body["next_action"] = {
                    "kind": "await_root_goal",
                    "predecessor_basis_record_id": basis_record_id,
                    "predecessor_mission_close_record_id": record_id,
                    "predecessor_mission_id": mission_id,
                    "predecessor_outcome": outcome,
                }
            elif outcome == "blocked_external":
                body["next_action"] = {
                    "basis_record_id": basis_record_id,
                    "kind": "await_external_change",
                    "predecessor_mission_close_record_id": record_id,
                    "predecessor_mission_id": mission_id,
                    "required_external_change": basis.payload.get(
                        "required_external_change",
                        basis.payload.get("cause", {}).get(
                            "required_external_change"
                        ),
                    ),
                }
            else:
                body["next_action"] = {
                    "kind": "project_goal_complete",
                    "mission_close_record_id": record_id,
                    "outcome": outcome,
                }
            project_stream = "project-goal:OPERATING_DIRECTION.md"
            project_head = index.event_head(project_stream)
            project_sequence = 1 if project_head is None else project_head.sequence + 1
            record = _record(
                kind="mission-close",
                record_id=record_id,
                subject=f"Mission:{mission_id}",
                status=outcome,
                fingerprint=record_id,
                payload={
                    "basis_record_id": basis_record_id,
                    "mission_ordinal": mission_ordinal,
                    "project_goal_authority": project_goal_authority,
                    "project_goal_complete": project_goal_complete,
                },
                event_stream=project_stream,
                event_sequence=project_sequence,
            )
            return body, [record], {
                "mission_id": mission_id,
                "outcome": outcome,
                "project_goal_complete": project_goal_complete,
            }

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
