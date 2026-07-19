"""The sole state writer for Axiom lifecycle and capability transitions."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any
import yaml

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.core.component_surface import (
    COMPONENT_SURFACE_PROTOCOL_NEUTRAL,
    ComponentManifestError,
    component_manifest_surfaces,
)
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.foundation_data_authority import (
    FOUNDATION_DATA_EXPOSURE_PATH,
    FOUNDATION_DATA_PATH,
    PROTECTED_FOUNDATION_DATA_PATHS,
    FoundationDataAuthorityError,
    FoundationDataDerivationProof,
    build_foundation_data_derivation_proof,
    foundation_data_derivation_binding,
    validate_foundation_data_identity_transition,
    verify_foundation_data_derivation_proof,
)
from axiom_rift.operations.foundation_authority_files import (
    FoundationAuthorityFileError,
    hash_foundation_file,
    replace_foundation_file,
)
from axiom_rift.operations.job_contract import (
    JobContractError,
    build_job_identity_plan,
    canonical_job_output_identity,
    canonical_worker_claim_identity,
    normalize_job_failure_manifest,
    normalize_job_spec,
    require_job_output_namespace,
    validate_job_spec,
)
from axiom_rift.operations.job_cache_authority import (
    JobCacheAuthorityError,
    require_cached_success_binding,
    require_reusable_success_outputs,
)
from axiom_rift.operations.job_implementation_authority import (
    JobImplementationAuthorityError,
    hardcoded_control_ids,
    implementation_source_closure_hashes,
    require_job_implementation_evidence,
    requires_current_source_authority,
)
from axiom_rift.operations.historical_replay_implementation_authority import (
    HistoricalReplayImplementationAuthorityError,
    authenticated_historical_implementation_sources,
)
from axiom_rift.operations.job_retry_admission import (
    JobRetryAdmissionIntegrityError,
    JobRetryAdmissionRejected,
    JobRetryAdmissionSpecificationError,
    build_retry_family_completion_record,
    build_retry_family_declaration_record,
    prepare_job_retry_admission,
)
from axiom_rift.operations.job_retry_family import (
    JobRetryFamilyError,
    JobRetryValidationAuthority,
    JobRetryValidationDispatchRequired,
    validate_engineering_retry_evidence,
)
from axiom_rift.operations.job_admission_authority import (
    JobAdmissionAuthorityError,
    require_job_admission,
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
from axiom_rift.operations.executable_axis_lineage import (
    ExecutableAxisLineageError,
    completion_executable_axis_lineage,
    holdout_completion_executable_lineage,
)
from axiom_rift.operations.observed_development_binding import (
    ObservedDevelopmentBindingError,
    scientific_observed_development_job_binding,
    verify_observed_development_prefix_artifact,
)
from axiom_rift.operations.external_observed_development_binding import (
    ExternalObservedDevelopmentJobBindingError,
    external_observed_development_job_binding,
    require_current_external_observed_development_job_binding,
    verify_external_observed_development_job_prefixes,
)
from axiom_rift.operations.permits import (
    Permit,
    PermitAuthority,
    PermitError,
    PermitKind,
    PermitStatus,
    SubjectKind,
    SubjectRef,
)
from axiom_rift.operations.running_job import (
    RunningJobAuthority,
    RunningJobAuthorityError,
    RunningJobAuthorityIntegrityError,
    RunningJobExecution,
)
from axiom_rift.operations.running_job_repair_projection import (
    effective_repair_head_implementation,
)
from axiom_rift.operations.repair_protocol import (
    EngineeringFailureDisposition,
    RepairAttemptProof,
    repair_attempt_intervention_fingerprint,
)
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
from axiom_rift.operations.repair_validation import (
    DISPOSITION_TRACE_SCHEMA,
    RepairValidationError,
    REGISTERED_REPAIR_AUTHORITY_SCHEMA,
    build_repair_candidate_validation_context,
    parse_repair_candidate_validation_receipt,
    build_repair_validation_plan,
    repair_validation_binding,
    repair_validation_capabilities,
    require_stored_accepted_repair_candidate_attempt,
    require_stored_repair_candidate_validation,
    require_stored_engineering_disposition_validation,
    require_stored_repair_attempt_validation,
    validate_repair_candidate,
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
from axiom_rift.operations.runtime_completion import (
    RuntimeSuccessAuthorityError,
    candidate_job_execution_context,
    current_runtime_source_snapshot,
)
from axiom_rift.operations.scientific_multiplicity_authority import (
    ScientificMultiplicityAuthorityError,
    ScientificMultiplicityIntegrityError,
    require_concurrent_family_registration,
    validate_scientific_multiplicity_registrations,
)
from axiom_rift.operations.external_dependency import (
    ExternalChangeEvidence,
    ExternalDependencyContractError,
    ExternalRecoveryPlan,
    ExternalResumeAction,
    external_plan_from_binding,
)
from axiom_rift.operations.study_close_delivery import (
    StudyCloseDeliveryObservation,
    StudyCloseGuardCapability,
)
from axiom_rift.operations.validation import (
    EngineeringFixtureValidator,
    EngineeringRepairFixtureValidator,
    EngineeringRetryFixtureValidator,
    EvidenceValidationError,
    EvidenceValidationRequest,
    EvidenceValidatorRegistry,
    ExternalChangeValidationRequest,
    ValidationArtifact,
)
from axiom_rift.storage.evidence import EvidenceStore
from axiom_rift.storage.index import (
    IndexIntegrityError,
    IndexRecord,
    LocalIndex,
    LocalIndexError,
    LocalIndexView,
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
from axiom_rift.storage.state import ControlStateError, ControlStore, WriterLock, seal_control
from axiom_rift.operations.writer_lifecycle import (
    StudyLifecycleWriterMixin,
    _BATCH_OUTCOMES,
    _ENGINEERING_FIXTURE_OUTCOME,
    _STUDY_KPI_ACTIVATION_OPERATION_ID,
    _STUDY_KPI_BACKFILL_OPERATION_ID,
    _STUDY_KPI_METRICS,
    _TYPED_STARTED_BATCH_EXIT_ACTIVATION_OPERATION_ID,
    _batch_job_decision_inventory,
    _concurrent_family_executable_ids,
)
from axiom_rift.operations.writer_job_admission import (
    JobAdmissionWriterMixin,
    _job_implementation_source_closure_hashes,
    _job_requires_current_source_authority,
    _require_concurrent_family_registration,
)
from axiom_rift.operations.writer_job_execution import JobExecutionWriterMixin
from axiom_rift.operations.writer_historical_replay import (
    HistoricalReplayWriterMixin,
)
from axiom_rift.operations.writer_holdout import HoldoutWriterMixin
from axiom_rift.operations.writer_portfolio_decision import (
    PortfolioDecisionWriterMixin,
)
from axiom_rift.operations.writer_portfolio_withdrawal import (
    PortfolioWithdrawalWriterMixin,
)
from axiom_rift.operations.writer_repair import (
    RepairSemanticEquivalenceUnavailable,
    RepairWriterMixin,
    _RepairDispositionCapability,
)
from axiom_rift.operations.writer_source_authority import (
    SourceAuthorityWriterMixin,
)
from axiom_rift.operations.writer_study_admission import (
    StudyAdmissionWriterMixin,
)
from axiom_rift.operations.writer_study_diagnosis import (
    StudyDiagnosisWriterMixin,
)
from axiom_rift.operations.writer_support import (
    IdenticalFailedRetryError,
    RecoveryRequired,
    TransitionError,
    TransitionResult,
    _copy,
    _digest,
    _effective_completion_scope,
    _parse_utc,
    _record,
    _require_ascii,
    _require_digest,
    _require_manifest,
    _require_study_evidence_modes,
)


class InjectedCrash(RuntimeError):
    """Commissioning-only crash injection after a transaction boundary."""


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
_AUTHORITATIVE_EVENT_CACHE_SIZE = 64
_ENGINEERING_FIXTURE_SEED_BOUNDARIES = {
    "axis_disposition_zero_credit_fixture_seeded": (
        "Mission:",
        frozenset({"completion_record_id"}),
    ),
    "correction_recovery_fixture_seeded": (
        "Mission:",
        frozenset({"obligation_id"}),
    ),
    "development_material_fixture_seeded": (
        "Mission:",
        frozenset({"material_id"}),
    ),
    "historical_adjudication_fixture_seeded": (
        "Study:",
        frozenset({"study_id"}),
    ),
    "legacy_negative_terminal_fixture_seeded": (
        "Mission:",
        frozenset({"basis_record_id", "mission_close_record_id"}),
    ),
    "legacy_surface_trial_fixture_seeded": (
        "=Executable:legacy",
        frozenset({"trial_delta"}),
    ),
    "legacy_trial_fixture_seeded": (
        "=Executable:legacy",
        frozenset({"trial_delta"}),
    ),
    "negative_terminal_fixture_seeded": (
        "Mission:",
        frozenset({"basis_record_id"}),
    ),
    "portfolio_scheduler_constraint_fixture_seeded": (
        "=Portfolio:active",
        frozenset({"target_id"}),
    ),
    "positive_terminal_fixture_seeded": (
        "Mission:",
        frozenset({"release_id"}),
    ),
    "project_holdout_state_fixture_seeded": (
        "=ProjectGoal:OPERATING_DIRECTION.md",
        frozenset({"record_id"}),
    ),
    "replay_repair_declaration_fixture_seeded": (
        "Mission:",
        frozenset({"job_id"}),
    ),
    "replay_repair_progress_fixture_seeded": (
        "Mission:",
        frozenset({"replay_executable_id"}),
    ),
    "replay_repair_success_fixture_seeded": (
        "Mission:",
        frozenset({"completion_record_id"}),
    ),
    "replay_resume_fixture_seeded": (
        "Mission:",
        frozenset({"obligation_id"}),
    ),
    "rich_scientific_completion_fixture_seeded": (
        "Study:",
        frozenset({"completion_record_id"}),
    ),
    "source_replacement_writer_lineage_fixture_seeded": (
        "Mission:",
        frozenset({"scientific_credit", "trial_delta"}),
    ),
}


_EXTERNAL_REENTRY_VALIDATION_CAPABILITY_TOKEN = object()


@dataclass(frozen=True, slots=True)
class _ExternalReentryValidationCapability:
    """One external-change dispatch bound to one blocked Mission head."""

    token: object
    control_hash: str
    request_hash: str
    validation_payload: Mapping[str, Any]
    validation_payload_hash: str


Prepare = Callable[
    [dict[str, Any] | None, LocalIndex],
    tuple[dict[str, Any], list[IndexRecord], Mapping[str, Any]],
]


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _engineering_fixture_seed_exemption(
    *,
    engineering_fixture: bool,
    event_kind: str,
    subject: str,
    payload: Mapping[str, Any],
) -> bool:
    """Recognize only inventoried zero-authority fixture seed boundaries."""

    if not engineering_fixture:
        return False
    boundary = _ENGINEERING_FIXTURE_SEED_BOUNDARIES.get(event_kind)
    if boundary is None:
        return False
    subject_boundary, payload_keys = boundary
    if subject_boundary.startswith("="):
        subject_valid = subject == subject_boundary.removeprefix("=")
    else:
        subject_valid = (
            type(subject) is str
            and subject.startswith(subject_boundary)
            and len(subject) > len(subject_boundary)
            and subject.isascii()
        )
    if (
        not subject_valid
        or set(payload) != {*payload_keys, "evidence"}
        or payload.get("evidence") != []
    ):
        return False
    for name, value in payload.items():
        if name == "evidence":
            continue
        if name in {"scientific_credit", "trial_delta"}:
            if type(value) is not int or value != 0:
                return False
        elif type(value) is not str or not value or not value.isascii():
            return False
    if event_kind == "historical_adjudication_fixture_seeded" and (
        subject != f"Study:{payload['study_id']}"
    ):
        return False
    return True


_hardcoded_control_ids = hardcoded_control_ids


def _canonical_job_output_identity(
    value: object,
    *,
    output_class: object | None = None,
    name: str = "Job output",
) -> str:
    try:
        return canonical_job_output_identity(
            value,
            output_class=output_class,
            name=name,
        )
    except JobContractError as exc:
        raise TransitionError(str(exc)) from exc


def _canonical_worker_claim_identity(
    value: object,
    *,
    name: str,
) -> str:
    try:
        return canonical_worker_claim_identity(value, name=name)
    except JobContractError as exc:
        raise TransitionError(str(exc)) from exc


def _require_authority_integer(
    name: str,
    value: object,
    *,
    minimum: int = 1,
    error_type: type[Exception] = TransitionError,
) -> int:
    """Reject bool and non-integer authority counters before comparison."""

    if type(value) is not int or value < minimum:
        raise error_type(f"{name} must be an integer >= {minimum}")
    return value


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


def _terminal_scientific_evidence_modes(
    modes: Sequence[str],
) -> tuple[str, ...]:
    """Exclude descriptive audit work from Mission-terminal science credit."""

    return tuple(sorted({mode for mode in modes if mode != "audit_integrity"}))


def _exact_source_replacement_wait_capability(
    *,
    mission_id: str,
    terminal_axes: Mapping[str, Mapping[str, Any]],
    terminal_resolutions: Mapping[str, Any],
    terminal_hard_blockers: Sequence[str],
) -> str | None:
    """Derive the only external-wait capability for source-only blockers.

    Every current hard blocker must be an unresolved audit-invalidated source.
    The residual source-free projection must contain no replay or scope blocker;
    this prevents invalidation precedence from hiding an internal obligation.
    Already replaced invalidations are excluded from the exact pending set.
    """

    from axiom_rift.research.effective_axis import (
        EffectiveAxisStatus,
        resolve_effective_axis,
    )
    from axiom_rift.research.source_authority import (
        source_replacement_capability_id,
        source_replacement_capability_set_id,
    )

    if not terminal_hard_blockers:
        return None
    capability_ids: list[str] = []
    for axis_id in sorted(terminal_hard_blockers):
        axis = terminal_axes.get(axis_id)
        resolution = terminal_resolutions.get(axis_id)
        if (
            not isinstance(axis, Mapping)
            or resolution is None
            or resolution.effective_status
            is not EffectiveAxisStatus.BLOCKED_BY_INVALIDATED_SOURCE
            or resolution.blocking_replay_obligation_ids
            or any(item.blocks_terminal for item in resolution.replay_bindings)
        ):
            return None
        residual = resolve_effective_axis(
            axis_id=resolution.axis_id,
            axis_identity=resolution.axis_identity,
            snapshot_status=resolution.snapshot_status,
            source_contract_ids=resolution.source_contract_ids,
            invalidations=(),
            source_replacements=(),
            replay_bindings=resolution.replay_bindings,
            evidence_scope_bindings=resolution.evidence_scope_bindings,
        )
        if not residual.terminal_eligible:
            return None
        replaced_sources = {
            item.invalidated_source_contract_id
            for item in resolution.source_replacements
        }
        unresolved = tuple(
            item
            for item in resolution.invalidations
            if item.source_contract_id not in replaced_sources
        )
        if not unresolved:
            return None
        axis_identity = axis.get("axis_identity")
        if axis_identity != resolution.axis_identity:
            return None
        capability_ids.extend(
            source_replacement_capability_id(
                mission_id=mission_id,
                original_axis_id=axis_id,
                original_axis_identity=axis_identity,
                invalidation_id=invalidation.invalidation_record_id,
                invalidated_source_contract_id=(
                    invalidation.source_contract_id
                ),
            )
            for invalidation in unresolved
        )
    if len(capability_ids) != len(set(capability_ids)):
        return None
    if len(capability_ids) == 1:
        return capability_ids[0]
    try:
        return source_replacement_capability_set_id(capability_ids)
    except ValueError:
        return None


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


class StateWriter(
    HistoricalReplayWriterMixin,
    HoldoutWriterMixin,
    JobAdmissionWriterMixin,
    JobExecutionWriterMixin,
    PortfolioDecisionWriterMixin,
    PortfolioWithdrawalWriterMixin,
    RepairWriterMixin,
    SourceAuthorityWriterMixin,
    StudyAdmissionWriterMixin,
    StudyDiagnosisWriterMixin,
    StudyLifecycleWriterMixin,
):
    """Commit one hash-chained event and advance its two projections."""

    def __init__(
        self,
        root: str | Path,
        *,
        permit_authority: PermitAuthority | None = None,
        clock: Callable[[], str] = _now_utc,
        engineering_fixture: bool = False,
        study_close_guard_capability: StudyCloseGuardCapability | None = None,
        study_close_delivery_observation: StudyCloseDeliveryObservation | None = None,
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
        if study_close_guard_capability is not None and (
            study_close_guard_capability
            is not StudyCloseGuardCapability.ISOLATED_ENGINEERING_FIXTURE
            or engineering_fixture
            or any(
                (candidate / ".git").exists()
                for candidate in (self.root.resolve(), *self.root.resolve().parents)
            )
        ):
            raise TransitionError(
                "Study-close guard capability must be an isolated non-Git fixture"
            )
        if study_close_delivery_observation is not None and (
            not isinstance(
                study_close_delivery_observation,
                StudyCloseDeliveryObservation,
            )
            or engineering_fixture
            or study_close_guard_capability is not None
        ):
            raise TransitionError(
                "Study-close delivery observation requires a real guarded writer"
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
        self.study_close_guard_capability = study_close_guard_capability
        self.study_close_delivery_observation = (
            study_close_delivery_observation
        )
        self._repair_disposition_capabilities: dict[
            str, _RepairDispositionCapability
        ] = {}
        self.validation_registry = (
            validation_registry
            if validation_registry is not None
            else EvidenceValidatorRegistry(
                (
                    EngineeringFixtureValidator(),
                    EngineeringRepairFixtureValidator(),
                    EngineeringRetryFixtureValidator(),
                )
                if engineering_fixture
                else ()
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
        sequence = _require_authority_integer(
            "Journal sequence",
            event.get("sequence"),
            error_type=JournalIntegrityError,
        )
        record_count = _require_authority_integer(
            "Journal index record count",
            event.get("index_record_count"),
            error_type=JournalIntegrityError,
        )
        control = _copy(event["control"])
        control["revision"] = sequence
        control["heads"] = {
            "journal": {
                "sequence": sequence,
                "event_id": event["event_id"],
            },
            "index": {
                "required_sequence": sequence,
                "required_record_count": record_count,
                "required_projection_digest": event[
                    "index_projection_digest"
                ],
            },
        }
        return control

    @staticmethod
    def _event_records(event: Mapping[str, Any]) -> tuple[IndexRecord, ...]:
        sequence = _require_authority_integer(
            "Journal sequence",
            event.get("sequence"),
            error_type=JournalIntegrityError,
        )
        offset = _require_authority_integer(
            "Journal offset",
            event.get("journal_offset"),
            minimum=0,
            error_type=JournalIntegrityError,
        )
        authority = {
            "authority_sequence": sequence,
            "authority_event_id": event["event_id"],
            "authority_offset": offset,
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
            event_sequence=sequence,
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

    @staticmethod
    def _index_record_authority_key(record: IndexRecord) -> tuple[int, int, str]:
        if (
            type(record.authority_sequence) is not int
            or record.authority_sequence < 1
            or type(record.authority_event_id) is not str
            or not record.authority_event_id
            or type(record.authority_offset) is not int
            or record.authority_offset < 0
        ):
            raise IndexIntegrityError("operating projection record lacks Journal authority")
        return (
            record.authority_offset,
            record.authority_sequence,
            record.authority_event_id,
        )

    def _validate_index_record_projection(
        self,
        record: IndexRecord,
        event: Mapping[str, Any],
    ) -> None:
        """Validate one row against its already authenticated Journal event."""

        projected = self._index_mapping(record)
        if record.kind == "journal-event":
            expected = self._index_mapping(self._event_records(event)[0])
            if projected != expected:
                raise IndexIntegrityError("journal-event projection differs from authority")
            return
        matches = [item for item in event["index_records"] if item == projected]
        if len(matches) != 1:
            raise IndexIntegrityError("projection record is not a unique Journal member")

    def _validate_index_record_authority(self, record: IndexRecord) -> None:
        offset, sequence, event_id = self._index_record_authority_key(record)
        event = self.journal.read_event_at(
            offset=offset,
            expected_sequence=sequence,
            expected_event_id=event_id,
        )
        self._validate_index_record_projection(record, event)

    def _authoritative_index_validator(
        self,
    ) -> Callable[[IndexRecord], None]:
        """Build one session-local Journal authority validator."""

        @lru_cache(maxsize=_AUTHORITATIVE_EVENT_CACHE_SIZE)
        def read_authoritative_event(
            offset: int,
            sequence: int,
            event_id: str,
        ) -> Mapping[str, Any]:
            return self.journal.read_event_at(
                offset=offset,
                expected_sequence=sequence,
                expected_event_id=event_id,
            )

        def validate(record: IndexRecord) -> None:
            authority_key = self._index_record_authority_key(record)
            event = read_authoritative_event(*authority_key)
            self._validate_index_record_projection(record, event)

        return validate

    def _open_authoritative_index(self) -> LocalIndexView:
        """Open one authenticated, existing, current-schema read snapshot."""

        try:
            return LocalIndex.open_read_only(
                self.index_path,
                authority_validator=self._authoritative_index_validator(),
            )
        except (IndexIntegrityError, LocalIndexError) as exc:
            raise RecoveryRequired(str(exc)) from exc

    def _open_mutable_authoritative_index(self) -> LocalIndex:
        """Open the authenticated projection for the atomic commit path only."""

        return LocalIndex(
            self.index_path,
            authority_validator=self._authoritative_index_validator(),
        )

    def _open_mutable_recovery_index(self) -> LocalIndex:
        """Open a projection that explicit Journal recovery may rebuild."""

        return LocalIndex(self.index_path)

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
            if type(sequence) is not int or sequence < 1:
                raise ValueError("source transition sequence is invalid")
            if (
                record is None
                or record.kind != "source-state"
                or record.subject != f"Source:{source_id}"
                or record.fingerprint != source_id
                or record.status != state
                or record.event_stream != stream
                or type(record.event_sequence) is not int
                or record.event_sequence != sequence
                or type(record.payload.get("ordinal")) is not int
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
                authority_sequence = _require_authority_integer(
                    "source authority head sequence",
                    authority_head.sequence,
                    error_type=ValueError,
                )
                correction = index.get(
                    authority_head.record_kind, authority_head.record_id
                )
                if (
                    correction is None
                    or correction.kind != "source-authority-invalidation"
                    or correction.status != "confirmed_and_suspended"
                    or correction.subject != f"Source:{source_id}"
                    or correction.event_stream != authority_stream
                    or type(correction.event_sequence) is not int
                    or correction.event_sequence != authority_sequence
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
                if source_head is not None:
                    _require_authority_integer(
                        "source head sequence",
                        source_head.sequence,
                        error_type=ValueError,
                    )
                for sequence_name, source_record in (
                    ("invalidated source event sequence", invalidated),
                    ("prior active source event sequence", prior_active),
                    ("replacement source event sequence", replacement),
                ):
                    if source_record is not None:
                        _require_authority_integer(
                            sequence_name,
                            source_record.event_sequence,
                            error_type=ValueError,
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
                    authority_sequence != 1
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
            head_sequence = _require_authority_integer(
                "runtime source head sequence",
                head.sequence,
                error_type=ValueError,
            )
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
                sequence=head_sequence,
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
                and head_sequence != 3
            ) or (
                receipt.evidence
                is SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION
                and (head_sequence < 5 or head_sequence % 2 == 0)
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
                    index.event_record(stream, head_sequence - 1),
                    sequence=head_sequence - 1,
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
        self,
        index: LocalIndex | LocalIndexView,
        *,
        allow_empty: bool = False,
    ) -> dict[str, Any] | None:
        control = self.control.read()
        journal_head, journal_event = self.journal.tail()
        index_head = index.event_head("control")
        if control is None:
            if (
                allow_empty
                and type(journal_head.sequence) is int
                and journal_head.sequence == 0
                and index_head is None
            ):
                return None
            raise RecoveryRequired("control is absent or trails durable state")
        if (
            control["authority"].get("manifest_digest")
            != self._authority_manifest_digest(control["authority"])
        ):
            raise RecoveryRequired("authority or Foundation input content drifted")
        state_head = control["heads"]["journal"]
        index_state_head = control["heads"]["index"]
        revision = _require_authority_integer(
            "control revision",
            control.get("revision"),
            error_type=ControlStateError,
        )
        state_sequence = _require_authority_integer(
            "control journal sequence",
            state_head.get("sequence"),
            error_type=ControlStateError,
        )
        required_index_sequence = _require_authority_integer(
            "control index sequence",
            index_state_head.get("required_sequence"),
            error_type=ControlStateError,
        )
        required_record_count = _require_authority_integer(
            "control index record count",
            index_state_head.get("required_record_count"),
            error_type=ControlStateError,
        )
        if required_index_sequence != state_sequence:
            raise ControlStateError("control index and journal sequences diverge")
        if revision != state_sequence:
            raise ControlStateError("control revision and journal head diverge")
        if (
            type(journal_head.sequence) is not int
            or journal_head.sequence != state_sequence
            or journal_head.event_id != state_head["event_id"]
        ):
            raise RecoveryRequired("control and journal require recovery")
        assert journal_event is not None
        if control != seal_control(self._assemble(journal_event)):
            raise RecoveryRequired("control content differs from journal authority")
        if (
            index_head is None
            or type(index_head.sequence) is not int
            or index_head.sequence != journal_head.sequence
            or index_head.fingerprint != journal_head.event_id
        ):
            raise RecoveryRequired("local index requires recovery")
        if index.record_count() != required_record_count:
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

    @contextmanager
    def open_stable_index(
        self,
    ) -> Iterator[tuple[dict[str, Any], LocalIndexView]]:
        """Yield one Journal-authenticated, query-only management snapshot.

        Reusable management workflows must not open the repository projection
        directly or pair an independently read control file with index rows.
        The read-only running-Job authority already owns the fail-closed stable
        boundary, including writer-lock coordination and full control, Journal,
        authority-manifest, projection-head, record-count, and digest checks.
        """

        authority = RunningJobAuthority(
            self.root,
            foundation_root=self.foundation_root,
        )
        try:
            with authority.open_stable_index() as snapshot:
                yield snapshot
        except RunningJobAuthorityError as exc:
            raise RecoveryRequired(str(exc)) from exc

    def require_stable_head(self) -> dict[str, Any]:
        """Return a read-only stable-head report without attempting recovery.

        Forest inspection commands use this bounded gate instead of calling
        ``recover()`` on every read.  Any control, Journal, index, projection,
        or authority-head mismatch fails closed through ``RecoveryRequired``;
        repair remains an explicit operator action.
        """

        with WriterLock(self.lock_path):
            with self._open_authoritative_index() as index:
                current = self._require_stable_locked(index)
                assert current is not None
                projection_digest, projection_valid = index.projection_guard()
                if not projection_valid:
                    raise RecoveryRequired("local index projection requires recovery")
                return {
                    "control": _copy(current),
                    "control_revision": current["revision"],
                    "index_record_count": index.record_count(),
                    "journal_event_id": current["heads"]["journal"]["event_id"],
                    "projection_digest": projection_digest,
                }

    def require_exact_trailing_event_recovery_boundary(
        self,
        *,
        expected_sequence: int,
        expected_event_id: str,
        expected_operation_id: str,
        expected_previous_event_id: str,
    ) -> dict[str, Any]:
        """Admit recovery only from the exact projection before one event.

        This intentionally performs a full Journal-derived projection audit.
        It is an exceptional recovery boundary, never a routine stable read.
        """

        with WriterLock(self.lock_path):
            return self._require_exact_trailing_event_recovery_locked(
                expected_sequence=expected_sequence,
                expected_event_id=expected_event_id,
                expected_operation_id=expected_operation_id,
                expected_previous_event_id=expected_previous_event_id,
            )

    def _require_exact_trailing_event_recovery_locked(
        self,
        *,
        expected_sequence: int,
        expected_event_id: str,
        expected_operation_id: str,
        expected_previous_event_id: str,
    ) -> dict[str, Any]:
        if (
            type(expected_sequence) is not int
            or expected_sequence < 2
            or type(expected_event_id) is not str
            or not expected_event_id
            or type(expected_operation_id) is not str
            or not expected_operation_id
            or type(expected_previous_event_id) is not str
            or not expected_previous_event_id
        ):
            raise RecoveryRequired(
                "exact trailing-event recovery identity is malformed"
            )
        events = self.journal.read_all()
        if len(events) < 2:
            raise RecoveryRequired(
                "exact trailing-event recovery lacks a predecessor"
            )
        trailing = events[-1]
        previous = events[-2]
        if (
            trailing.get("sequence") != expected_sequence
            or trailing.get("event_id") != expected_event_id
            or trailing.get("operation_id") != expected_operation_id
            or trailing.get("previous_event_id") != expected_previous_event_id
            or previous.get("sequence") != expected_sequence - 1
            or previous.get("event_id") != expected_previous_event_id
        ):
            raise RecoveryRequired(
                "Journal tail is not the exact admitted recovery event"
            )
        current = self.control.read()
        if current is None:
            raise RecoveryRequired(
                "exact trailing-event recovery requires predecessor control"
            )
        predecessor_control = seal_control(self._assemble(previous))
        trailing_control = seal_control(self._assemble(trailing))
        if current == predecessor_control:
            control_position = "predecessor"
        elif current == trailing_control:
            control_position = "trailing_event"
        else:
            raise RecoveryRequired(
                "control is outside the exact trailing-event recovery pair"
            )
        expected_records: list[IndexRecord] = []
        for event in events[:-1]:
            expected_records.extend(self._event_records(event))
        with self._open_authoritative_index() as index:
            head = index.event_head("control")
            projection_digest, projection_valid = index.projection_guard()
            if (
                head is None
                or head.sequence != previous["sequence"]
                or head.fingerprint != previous["event_id"]
                or index.record_count() != previous["index_record_count"]
                or not projection_valid
                or projection_digest != previous["index_projection_digest"]
                or not index.full_maintenance_exactly_matches(expected_records)
            ):
                raise RecoveryRequired(
                    "local index is not the exact predecessor projection"
                )
        return {
            "control_position": control_position,
            "expected_event_id": expected_event_id,
            "expected_previous_event_id": expected_previous_event_id,
            "expected_sequence": expected_sequence,
            "full_projection_record_count": len(expected_records),
            "schema": "exact_trailing_event_recovery_boundary.v1",
        }

    @staticmethod
    def _effective_running_job_implementation(
        index: LocalIndex,
        *,
        job_id: str,
        declared_implementation_identity: str,
    ) -> tuple[str, str | None]:
        """Project the latest typed in-place implementation Repair."""
        try:
            return effective_repair_head_implementation(
                index,
                job_id=job_id,
                declared_implementation_identity=(
                    declared_implementation_identity
                ),
            )
        except RunningJobAuthorityIntegrityError as exc:
            raise RecoveryRequired(str(exc)) from exc

    def resume_repaired_job_execution(
        self,
        execution: RunningJobExecution,
        *,
        expected_callable_identity: str,
        operation_id: str,
        expected_evidence_subject: Mapping[str, str] | None = None,
        required_input_hashes: Sequence[str] = (),
    ) -> TransitionResult:
        """Durably re-enter the exact Job engine after a successful Repair."""

        if not isinstance(execution, RunningJobExecution):
            raise PermitError("Repair resume requires a running Job execution context")
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

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            job = science.get("active_job")
            if (
                not isinstance(job, dict)
                or job.get("status") != "running"
                or science.get("active_repair") is not None
                or job.get("id") != execution.job_id
                or job.get("hash") != execution.job_hash
                or job.get("start_record_id") != execution.start_record_id
            ):
                raise PermitError("repaired Job execution context is stale")
            close_id = job.get("required_repair_resume_record_id")
            direction = body.get("next_action")
            if (
                not isinstance(close_id, str)
                or not isinstance(direction, Mapping)
                or direction
                != {
                    "job_id": execution.job_id,
                    "kind": "resume_job",
                    "repair_close_record_id": close_id,
                }
            ):
                raise TransitionError("no exact repaired Job execution is pending")
            declaration = index.get("job-declared", execution.job_id)
            start = index.get("job-started", execution.start_record_id)
            spec = None if declaration is None else declaration.payload.get("spec")
            if (
                declaration is None
                or declaration.fingerprint != execution.job_hash
                or start is None
                or start.status != "running"
                or start.subject != f"Job:{execution.job_id}"
                or start.fingerprint != execution.job_hash
                or start.payload.get("job_permit_id") != execution.job_permit_id
                or not isinstance(spec, dict)
                or spec.get("callable_identity") != expected_callable_identity
                or (
                    expected_subject is not None
                    and spec.get("evidence_subject") != expected_subject
                )
                or not set(required).issubset(spec.get("input_hashes", []))
            ):
                raise PermitError("repaired Job differs from engine re-entry")
            close = index.get("repair-close", close_id)
            repair_head = index.event_head(f"job-repair:{execution.job_id}")
            effective_implementation, effective_close_id = (
                self._effective_running_job_implementation(
                    index,
                    job_id=execution.job_id,
                    declared_implementation_identity=spec[
                        "implementation_identity"
                    ],
                )
            )
            try:
                repaired_manifest = self._require_job_implementation_evidence(
                    {
                        **dict(spec),
                        "implementation_identity": effective_implementation,
                    },
                    _index=index,
                )
                from axiom_rift.research.implementation_closure import (
                    ImplementationClosureError,
                    require_current_job_source_closure,
                    require_job_implementation_closure,
                )

                subject = spec.get("evidence_subject")
                component_hashes: tuple[str, ...] = ()
                if (
                    isinstance(subject, Mapping)
                    and subject.get("kind") == "Executable"
                ):
                    trial = index.get("trial", str(subject.get("id")))
                    executable = (
                        None if trial is None else trial.payload.get("executable")
                    )
                    if not isinstance(executable, Mapping):
                        raise ImplementationClosureError(
                            "repaired Job lost its exact Executable closure"
                        )
                    component_hashes = require_job_implementation_closure(
                        executable_manifest=executable,
                        job_artifact_hashes=repaired_manifest["artifact_hashes"],
                        artifact_reader=self.evidence.read_verified,
                    )
                subject_kind = (
                    None
                    if not isinstance(subject, Mapping)
                    else subject.get("kind")
                )
                if _job_requires_current_source_authority(
                    engineering_fixture=self.engineering_fixture,
                    evidence_subject_kind=subject_kind,
                ):
                    require_current_job_source_closure(
                        callable_identity=str(spec["callable_identity"]),
                        job_artifact_hashes=repaired_manifest[
                            "artifact_hashes"
                        ],
                        artifact_reader=self.evidence.read_verified,
                        source_root=self.foundation_root / "src",
                        verified_non_source_artifact_hashes=component_hashes,
                    )
            except (ImplementationClosureError, TransitionError) as exc:
                raise RecoveryRequired(
                    "repaired Job current implementation authority drifted"
                ) from exc
            attempt_id = (
                None if close is None else close.payload.get("attempt_record_id")
            )
            attempt = (
                None
                if not isinstance(attempt_id, str)
                else index.get("repair-attempt", attempt_id)
            )
            repair_id = None if close is None else close.payload.get("repair_id")
            if (
                close is None
                or close.kind != "repair-close"
                or close.status != "repaired"
                or close.subject != f"Job:{execution.job_id}"
                or close.record_id != close_id
                or repair_head is None
                or repair_head.record_id != close_id
                or effective_close_id != close_id
                or close.payload.get("job_id") != execution.job_id
                or close.payload.get("effective_implementation_identity")
                != effective_implementation
                or close.payload.get("resume_action") != spec.get("resume_action")
                or not isinstance(repair_id, str)
                or attempt is None
                or attempt.status != "repaired"
                or attempt.subject != f"Repair:{repair_id}"
                or attempt.payload.get("repair_id") != repair_id
                or attempt.payload.get("job_id") != execution.job_id
            ):
                raise RecoveryRequired("repaired Job re-entry provenance is invalid")
            resume_payload = {
                "callable_identity": expected_callable_identity,
                "effective_implementation_identity": effective_implementation,
                "engine_entry_record_id": job.get("engine_entry_record_id"),
                "execution": execution.payload(),
                "repair_attempt_record_id": attempt_id,
                "repair_close_record_id": close_id,
                "repair_id": repair_id,
                "runtime_entry_record_id": job.get("runtime_entry_record_id"),
            }
            record_id = canonical_digest(
                domain="job-repaired-execution-resume",
                payload=resume_payload,
            )
            stream = f"job-resume:{execution.job_id}"
            head = index.event_head(stream)
            record = _record(
                kind="job-resumed",
                record_id=record_id,
                subject=f"Job:{execution.job_id}",
                status="validated",
                fingerprint=execution.job_hash,
                payload=resume_payload,
                event_stream=stream,
                event_sequence=1 if head is None else head.sequence + 1,
            )
            job.pop("required_repair_resume_record_id")
            job["last_repair_resume_record_id"] = record_id
            body["next_action"] = {
                "kind": "resume_job",
                "job_id": execution.job_id,
            }
            return body, [record], {
                "job_id": execution.job_id,
                "repair_close_record_id": close_id,
                "resume_record_id": record_id,
            }

        return self._commit(
            event_kind="job_repaired_execution_resumed",
            operation_id=operation_id,
            subject=f"Job:{execution.job_id}",
            payload={
                "execution": execution.payload(),
                "expected_callable_identity": expected_callable_identity,
                "expected_evidence_subject": expected_subject,
                "required_input_hashes": list(required),
            },
            prepare=prepare,
        )

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

        control = self.read_control()
        active_job = (
            None
            if control is None
            else control.get("scientific", {}).get("active_job")
        )
        pending_repair_close = (
            None
            if not isinstance(active_job, dict)
            else active_job.get("required_repair_resume_record_id")
        )
        if isinstance(pending_repair_close, str):
            self.resume_repaired_job_execution(
                execution,
                expected_callable_identity=expected_callable_identity,
                expected_evidence_subject=expected_subject,
                required_input_hashes=required,
                operation_id=(
                    "resume-repaired-job-execution-" + pending_repair_close
                ),
            )
        authority = RunningJobAuthority(
            self.root,
            foundation_root=self.foundation_root,
        )
        try:
            return authority.verify_running_job_execution(
                execution,
                expected_callable_identity=expected_callable_identity,
                expected_evidence_subject=expected_subject,
                required_input_hashes=required,
            )
        except RunningJobAuthorityIntegrityError as exc:
            raise RecoveryRequired(str(exc)) from exc

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
        authority = RunningJobAuthority(
            self.root,
            foundation_root=self.foundation_root,
        )
        try:
            authority.verify_reproducible_cache_producer(
                producer,
                cache_output_name=cache_output_name,
                cache_hash=cache_hash,
                expected_callable_identity=expected_callable_identity,
                expected_evidence_subject=expected_evidence_subject,
                expected_output_classes=expected_output_classes,
                expected_study_id=expected_study_id,
                manifest_output_name=manifest_output_name,
                manifest_hash=manifest_hash,
            )
        except RunningJobAuthorityIntegrityError as exc:
            raise RecoveryRequired(str(exc)) from exc
        except (RunningJobAuthorityError, ValueError) as exc:
            raise TransitionError(str(exc)) from exc

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
        authority_derivation_check: Callable[[], None] | None = None,
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
        if authority_derivation_check is not None and event_kind != "authority_migrated":
            raise TransitionError(
                "authority derivation checks require the typed migration event"
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
            with self._open_mutable_authoritative_index() as index:
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
                    required_direction_events = {
                        "complete_engineering_failure": {"job_completed"},
                        "complete_runtime_source_ineligibility": {
                            "job_completed"
                        },
                        "diagnose_study": {"study_diagnosis_recorded"},
                        "dispose_revealed_holdout_engineering_gap": {
                            "holdout_engineering_gap_disposed"
                        },
                        "judge_external_dependency_evidence": {
                            "external_dependency_evidence_judged"
                        },
                        "judge_job_evidence": {
                            "job_evidence_judged",
                            "negative_memory_recorded",
                        },
                        "record_holdout_evaluation": {
                            "holdout_evaluated",
                            "negative_memory_recorded",
                        },
                        "record_axis_reopen_authority": {
                            "axis_reopen_authority_recorded"
                        },
                        "record_research_intake": {
                            "research_intake_recorded"
                        },
                        "record_source_eligibility": {
                            "source_eligibility_recorded"
                        },
                        "review_architecture": {
                            "architecture_review_recorded"
                        },
                        "resolve_candidate_engineering_gap": {
                            "candidate_disposed",
                            "job_declared",
                        },
                    }.get(pending_direction)
                    if (
                        required_direction_events is not None
                        and event_kind not in required_direction_events
                        and not _engineering_fixture_seed_exemption(
                            engineering_fixture=(
                                self.engineering_fixture
                                or self.study_close_guard_capability
                                is StudyCloseGuardCapability.ISOLATED_ENGINEERING_FIXTURE
                            ),
                            event_kind=event_kind,
                            subject=subject,
                            payload=committed_payload,
                        )
                    ):
                        direction_label = {
                            "complete_engineering_failure": (
                                "unrecovered engineering Job completion"
                            ),
                            "complete_runtime_source_ineligibility": (
                                "runtime source-ineligibility completion"
                            ),
                            "record_research_intake": "research intake",
                            "diagnose_study": "Study diagnosis",
                            "dispose_revealed_holdout_engineering_gap": (
                                "revealed holdout engineering-gap disposition"
                            ),
                            "judge_external_dependency_evidence": (
                                "external dependency judgement"
                            ),
                            "judge_job_evidence": "Job evidence judgement",
                            "record_holdout_evaluation": (
                                "revealed holdout disposition"
                            ),
                            "record_axis_reopen_authority": (
                                "audit-deferred axis reopen authority"
                            ),
                            "record_source_eligibility": (
                                "source eligibility transition"
                            ),
                            "review_architecture": "architecture review",
                            "resolve_candidate_engineering_gap": (
                                "candidate engineering-gap resolution"
                            ),
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
                                "engineering_failure_disposition_recorded",
                                "job_repaired_execution_resumed",
                                "permit_issued",
                                "permit_revoked",
                                "runtime_engine_entered",
                                "source_eligibility_recorded",
                                "holdout_revealed",
                                "job_completed",
                                "repair_opened",
                            },
                            "interrupted_repair": {
                                "repair_attempt_failed",
                                "repair_closed",
                                "repair_concluded_unrecovered",
                                "repair_validation_observed",
                            },
                        }
                        if event_kind not in allowed_by_status.get(
                            active_job.get("status"), set()
                        ):
                            raise TransitionError(
                                "active Job must resume or complete before another transition"
                            )
                    if active_repair is not None and event_kind not in {
                        "repair_attempt_failed",
                        "repair_closed",
                        "repair_concluded_unrecovered",
                        "repair_validation_observed",
                    }:
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
                        "engineering_failure_disposition_recorded",
                        "holdout_evaluated",
                        "holdout_engineering_gap_disposed",
                        "job_repaired_execution_resumed",
                        "negative_memory_recorded",
                        "job_completed",
                        "permit_issued",
                        "permit_revoked",
                        "repair_opened",
                        "repair_attempt_failed",
                        "repair_closed",
                        "repair_concluded_unrecovered",
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
                physical_authority = (
                    next_body.get("authority")
                    if current is None
                    else current.get("authority")
                )
                if not isinstance(physical_authority, Mapping):
                    raise TransitionError(
                        "transition authority manifest is unavailable"
                    )

                def require_preappend_authority() -> None:
                    expected_manifest = physical_authority.get(
                        "manifest_digest"
                    )
                    if (
                        type(expected_manifest) is not str
                        or expected_manifest
                        != self._authority_manifest_digest(
                            physical_authority
                        )
                    ):
                        raise RecoveryRequired(
                            "authority or Foundation input changed during transition preparation"
                        )
                    if authority_derivation_check is not None:
                        authority_derivation_check()

                if read_only_when_unchanged and not records:
                    if current is None or next_body != self._body(current):
                        raise TransitionError(
                            "read-only observation attempted to change control state"
                        )
                    require_preappend_authority()
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
                require_preappend_authority()
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
                if authority_derivation_check is not None:
                    authority_derivation_check()
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
            return self._recover_locked()

    def recover_exact_trailing_event(
        self,
        *,
        expected_sequence: int,
        expected_event_id: str,
        expected_operation_id: str,
        expected_previous_event_id: str,
    ) -> dict[str, Any]:
        """Atomically prove and recover one exact trailing Journal event."""

        with WriterLock(self.lock_path):
            boundary = self._require_exact_trailing_event_recovery_locked(
                expected_sequence=expected_sequence,
                expected_event_id=expected_event_id,
                expected_operation_id=expected_operation_id,
                expected_previous_event_id=expected_previous_event_id,
            )
            report = self._recover_locked(
                expected_tail=(
                    expected_sequence,
                    expected_event_id,
                    expected_operation_id,
                    expected_previous_event_id,
                )
            )
        return {"recovery_boundary": boundary, **report}

    def _recover_locked(
        self,
        *,
        expected_tail: tuple[int, str, str, str] | None = None,
    ) -> dict[str, Any]:
        journal_storage_repaired = self.journal.recover_storage()
        events = self.journal.read_all()
        if expected_tail is not None:
            sequence, event_id, operation_id, previous_event_id = expected_tail
            if (
                not events
                or events[-1].get("sequence") != sequence
                or events[-1].get("event_id") != event_id
                or events[-1].get("operation_id") != operation_id
                or events[-1].get("previous_event_id") != previous_event_id
            ):
                raise RecoveryRequired(
                    "Journal tail changed after exact recovery admission"
                )
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
                "study_kpi_projection_changed": False,
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
        with self._open_mutable_recovery_index() as index:
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
        # Recovery restores authority (Journal, control, and the reconstructible
        # SQLite projection).  The Markdown KPI ledger is lag-tolerant
        # navigation and is materialized only by explicit maintenance; making
        # every recovery render complete KPI history would reintroduce the
        # same history-linear bottleneck removed from routine Study close.
        report["study_kpi_projection_changed"] = False
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
            try:
                hashes[relative] = hash_foundation_file(
                    self.foundation_root,
                    relative,
                )
            except FoundationAuthorityFileError as exc:
                raise RecoveryRequired(str(exc)) from exc
        return hashes

    def _authority_manifest_digest(self, authority: Mapping[str, Any]) -> str:
        return self._authority_digest_from_hashes(
            self._authority_path_hashes(authority)
        )

    def _replace_authority_file(
        self,
        relative: str,
        content: bytes,
        *,
        expected_current_sha256: str,
    ) -> None:
        try:
            replace_foundation_file(
                self.foundation_root,
                relative,
                content,
                expected_current_sha256=expected_current_sha256,
            )
        except FoundationAuthorityFileError as exc:
            raise RecoveryRequired(str(exc)) from exc

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
        to_write: list[tuple[str, bytes, str, str]] = []
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
                to_write.append(
                    (relative, content, current_hash, new_hash)
                )
            current_hashes[relative] = new_hash
        if (
            self._authority_digest_from_hashes(current_hashes)
            != expected_manifest_digest
        ):
            raise RecoveryRequired(
                "authority replacement set does not produce the bound manifest"
            )
        for relative, content, current_hash, new_hash in to_write:
            self._replace_authority_file(
                relative,
                content,
                expected_current_sha256=current_hash,
            )
            try:
                materialized_hash = hash_foundation_file(
                    self.foundation_root,
                    relative,
                )
            except FoundationAuthorityFileError as exc:
                raise RecoveryRequired(str(exc)) from exc
            if materialized_hash != new_hash:
                raise RecoveryRequired(
                    f"authority replacement verification failed: {relative}"
                )
        if self._authority_manifest_digest(authority) != expected_manifest_digest:
            raise RecoveryRequired("authority migration manifest does not materialize")

    def _verify_foundation_data_derivation_event(
        self,
        *,
        event: Mapping[str, Any],
        binding: Mapping[str, Any],
    ) -> None:
        if set(binding) != {
            "data_document_sha256",
            "data_exposure_document_sha256",
            "material_identity",
            "proof_hash",
            "proof_id",
            "schema",
        } or binding.get("schema") != (
            "foundation_data_authority_derivation_binding.v1"
        ):
            raise JournalIntegrityError(
                "Foundation data derivation binding is malformed"
            )
        try:
            data_hash = _require_digest(
                "Foundation data document hash",
                binding.get("data_document_sha256"),
            )
            exposure_hash = _require_digest(
                "Foundation data exposure document hash",
                binding.get("data_exposure_document_sha256"),
            )
            proof_hash = _require_digest(
                "Foundation data derivation proof hash",
                binding.get("proof_hash"),
            )
            _require_digest(
                "Foundation material identity",
                binding.get("material_identity"),
            )
        except TransitionError as exc:
            raise JournalIntegrityError(
                "Foundation data derivation binding digests are malformed"
            ) from exc
        proof_id = binding.get("proof_id")
        if (
            type(proof_id) is not str
            or not proof_id.startswith("foundation-data-derivation:")
            or len(proof_id) != 91
        ):
            raise JournalIntegrityError(
                "Foundation data derivation proof identity is malformed"
            )
        evidence = event.get("payload", {}).get("evidence")
        if not isinstance(evidence, list):
            raise JournalIntegrityError(
                "Foundation data derivation evidence is absent"
            )
        evidenced_hashes = {
            item.get("sha256")
            for item in evidence
            if isinstance(item, Mapping)
        }
        if not {data_hash, exposure_hash, proof_hash}.issubset(evidenced_hashes):
            raise JournalIntegrityError(
                "Foundation data derivation evidence is incomplete"
            )
        try:
            data_document = self.evidence.read_verified(data_hash)
            data_exposure_document = self.evidence.read_verified(exposure_hash)
            proof_bytes = self.evidence.read_verified(proof_hash)
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
            raise RecoveryRequired(
                "Foundation data derivation evidence is unavailable or corrupt"
            ) from exc
        try:
            proof = FoundationDataDerivationProof.from_bytes(proof_bytes)
        except FoundationDataAuthorityError as exc:
            raise JournalIntegrityError(
                "Foundation data derivation proof is malformed"
            ) from exc
        if (
            proof.data_document_sha256 != data_hash
            or proof.data_exposure_document_sha256 != exposure_hash
            or foundation_data_derivation_binding(proof) != dict(binding)
        ):
            raise JournalIntegrityError(
                "Foundation data derivation event binding differs"
            )
        try:
            verify_foundation_data_derivation_proof(
                self.root,
                proof=proof,
                data_document=data_document,
                data_exposure_document=data_exposure_document,
            )
        except FoundationDataAuthorityError as exc:
            raise RecoveryRequired(str(exc)) from exc

    def _apply_pending_authority_migrations(
        self,
        *,
        events: Sequence[Mapping[str, Any]],
        applied_sequence: int,
        final_authority: Mapping[str, Any],
    ) -> None:
        targets: dict[str, dict[str, Any]] = {}
        latest_foundation_derivation: tuple[
            Mapping[str, Any], Mapping[str, Any]
        ] | None = None
        typed_foundation_boundary_seen = False
        for authoritative_event in events:
            if authoritative_event.get("event_kind") != "authority_migrated":
                continue
            authoritative_payload = authoritative_event.get("payload")
            if not isinstance(authoritative_payload, Mapping):
                raise JournalIntegrityError(
                    "authority migration payload is malformed"
                )
            authoritative_rows = authoritative_payload.get("replacements")
            if not isinstance(authoritative_rows, list) or any(
                not isinstance(row, Mapping) for row in authoritative_rows
            ):
                raise JournalIntegrityError(
                    "authority migration replacement rows are malformed"
                )
            row_paths = [row.get("path") for row in authoritative_rows]
            protected_paths = set(row_paths).intersection(
                PROTECTED_FOUNDATION_DATA_PATHS
            )
            binding = authoritative_payload.get("foundation_data_derivation")
            if binding is not None:
                if (
                    len(row_paths) != len(PROTECTED_FOUNDATION_DATA_PATHS)
                    or set(row_paths) != set(PROTECTED_FOUNDATION_DATA_PATHS)
                    or not isinstance(binding, Mapping)
                ):
                    raise JournalIntegrityError(
                        "typed Foundation data migration path set is invalid"
                    )
                latest_foundation_derivation = (
                    authoritative_event,
                    binding,
                )
                typed_foundation_boundary_seen = True
            elif "foundation_data_derivation" in authoritative_payload:
                raise JournalIntegrityError(
                    "Foundation data derivation binding is null"
                )
            elif protected_paths:
                # Historical migrations predate the prospective typed boundary.
                if typed_foundation_boundary_seen:
                    raise JournalIntegrityError(
                        "untyped Foundation data migration follows typed activation"
                    )
                latest_foundation_derivation = None
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
        if latest_foundation_derivation is not None:
            event, binding = latest_foundation_derivation
            self._verify_foundation_data_derivation_event(
                event=event,
                binding=binding,
            )
        if targets:
            self._materialize_authority_targets(
                authority=final_authority,
                targets=targets,
                expected_manifest_digest=final_authority["manifest_digest"],
            )

    @staticmethod
    def _active_mission_stable_boundary(current: Mapping[str, Any]) -> bool:
        """Recognize the exact no-Initiative Mission scheduling boundary."""

        science = current["scientific"]
        mission_id = science.get("active_mission")
        authorizations = current.get("authorizations")
        raw_action = current.get("next_action")
        try:
            resume_action = ExternalResumeAction.from_next_action(raw_action)
        except (ExternalDependencyContractError, TypeError):
            resume_action = None
        stable_action = (
            resume_action is not None
            and resume_action.kind == "choose_next_initiative_or_terminal"
            and resume_action.mission_id == mission_id
            and resume_action.to_next_action() == raw_action
        )
        return (
            type(mission_id) is str
            and stable_action
            and science.get("active_initiative") is None
            and all(
                science.get(name) is None
                for name in (
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
            and isinstance(authorizations, dict)
            and set(authorizations) == {f"Mission:{mission_id}"}
            and science.get("claim") == "none"
            and science.get("holdout_reveals") == 0
            and science.get("required_future_holdout_id") is None
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
            and (
                (
                    current["next_action"].get("kind") == "portfolio_decision"
                    and type(mission_id) is str
                    and type(initiative_id) is str
                    and all(science.get(name) is None for name in inactive_names)
                    and isinstance(active_authorizations, dict)
                    and set(active_authorizations)
                    == {f"Mission:{mission_id}", f"Initiative:{initiative_id}"}
                    and science.get("claim") == "none"
                )
                or StateWriter._active_mission_stable_boundary(current)
            )
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

        return self._migrate_authority(
            replacements=replacements,
            reason=reason,
            operation_id=operation_id,
            allow_active_stable_boundary=allow_active_stable_boundary,
            foundation_data_boundary=False,
            crash_after=crash_after,
        )

    def migrate_foundation_data_authority(
        self,
        *,
        replacements: Mapping[str, bytes],
        reason: str,
        operation_id: str,
        allow_active_stable_boundary: bool = False,
        crash_after: str | None = None,
    ) -> TransitionResult:
        """Migrate both Foundation data documents under an exact derivation proof."""

        return self._migrate_authority(
            replacements=replacements,
            reason=reason,
            operation_id=operation_id,
            allow_active_stable_boundary=allow_active_stable_boundary,
            foundation_data_boundary=True,
            crash_after=crash_after,
        )

    def _migrate_authority(
        self,
        *,
        replacements: Mapping[str, bytes],
        reason: str,
        operation_id: str,
        allow_active_stable_boundary: bool,
        foundation_data_boundary: bool,
        crash_after: str | None,
    ) -> TransitionResult:
        """Shared authority migration engine with a protected data capability."""

        self.require_study_close_delivery_guard()
        _require_ascii("authority migration reason", reason)
        _require_ascii("operation_id", operation_id)
        if type(allow_active_stable_boundary) is not bool:
            raise TransitionError("active stable authority boundary flag must be bool")
        if not isinstance(replacements, Mapping) or not replacements:
            raise TransitionError("authority migration requires replacement bytes")
        if any(type(relative) is not str for relative in replacements):
            raise TransitionError("authority replacement paths must be strings")
        requested_paths = tuple(sorted(replacements))
        protected_paths = set(requested_paths).intersection(
            PROTECTED_FOUNDATION_DATA_PATHS
        )
        if foundation_data_boundary:
            if set(requested_paths) != set(PROTECTED_FOUNDATION_DATA_PATHS):
                raise TransitionError(
                    "typed Foundation data migration requires exactly both data documents"
                )
        elif protected_paths:
            raise TransitionError(
                "Foundation data documents require the typed derivation boundary"
            )
        for content in replacements.values():
            if type(content) is not bytes:
                raise TransitionError("authority replacement content must be bytes")
        foundation_data_document = (
            replacements[FOUNDATION_DATA_PATH]
            if foundation_data_boundary
            else None
        )
        foundation_data_exposure_document = (
            replacements[FOUNDATION_DATA_EXPOSURE_PATH]
            if foundation_data_boundary
            else None
        )
        foundation_proof: FoundationDataDerivationProof | None = None
        foundation_binding: dict[str, str] | None = None
        if foundation_data_boundary:
            assert foundation_data_document is not None
            assert foundation_data_exposure_document is not None
            try:
                foundation_proof = build_foundation_data_derivation_proof(
                    self.root,
                    data_document=foundation_data_document,
                    data_exposure_document=foundation_data_exposure_document,
                )
            except FoundationDataAuthorityError as exc:
                raise TransitionError(str(exc)) from exc
            foundation_binding = foundation_data_derivation_binding(
                foundation_proof
            )

        def authority_evidence_blobs() -> tuple[bytes, ...]:
            values = [replacements[relative] for relative in requested_paths]
            if foundation_proof is not None:
                values.append(foundation_proof.to_bytes())
            unique: list[bytes] = []
            observed_hashes: set[str] = set()
            for value in values:
                digest = sha256(value).hexdigest()
                if digest not in observed_hashes:
                    observed_hashes.add(digest)
                    unique.append(value)
            return tuple(unique)

        def require_foundation_derivation() -> None:
            if foundation_proof is None:
                return
            assert foundation_data_document is not None
            assert foundation_data_exposure_document is not None
            try:
                verify_foundation_data_derivation_proof(
                    self.root,
                    proof=foundation_proof,
                    data_document=foundation_data_document,
                    data_exposure_document=foundation_data_exposure_document,
                )
            except FoundationDataAuthorityError as exc:
                raise RecoveryRequired(str(exc)) from exc
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
                    if foundation_proof is not None:
                        try:
                            validate_foundation_data_identity_transition(
                                predecessor_data_document=current_contents[
                                    FOUNDATION_DATA_PATH
                                ],
                                predecessor_data_exposure_document=current_contents[
                                    FOUNDATION_DATA_EXPOSURE_PATH
                                ],
                                successor_proof=foundation_proof,
                            )
                        except FoundationDataAuthorityError as exc:
                            raise TransitionError(str(exc)) from exc
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
                or event_payload.get("foundation_data_derivation")
                != foundation_binding
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
                evidence_blobs=authority_evidence_blobs(),
                authority_replacements=tuple(rows),
                authority_derivation_check=(
                    require_foundation_derivation
                    if foundation_proof is not None
                    else None
                ),
                crash_after=crash_after,
            )
        assert authority is not None
        assert old_hashes is not None
        assert current_contents is not None
        old_manifest_digest = self._authority_digest_from_hashes(old_hashes)
        replacement_rows: list[dict[str, str]] = []
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
        if foundation_binding is not None:
            migration_payload["foundation_data_derivation"] = foundation_binding
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
            evidence_blobs=authority_evidence_blobs(),
            authority_replacements=tuple(replacement_rows),
            authority_derivation_check=(
                require_foundation_derivation
                if foundation_proof is not None
                else None
            ),
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
                if index.count_by_kind("mission-close"):
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
        trials = index.records_by_kind("trial")
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
        for trial in trials:
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
        from axiom_rift.operations.effective_study_diagnosis import (
            EffectiveStudyDiagnosisError,
            effective_study_diagnosis,
        )

        for diagnosis_record in index.records_by_kind("study-diagnosis"):
            try:
                diagnosis = effective_study_diagnosis(
                    index,
                    diagnosis_record.record_id,
                )
            except EffectiveStudyDiagnosisError as exc:
                raise RecoveryRequired(str(exc)) from exc
            evidence_state_counts[diagnosis.status] = (
                evidence_state_counts.get(diagnosis.status, 0) + 1
            )
        mission_outcomes: dict[str, int] = {}
        for close in index.records_by_kind("mission-close"):
            mission_outcomes[close.status] = mission_outcomes.get(close.status, 0) + 1
        return {
            "candidate_record_count": index.count_by_kind("candidate"),
            "architecture_review_count": index.count_by_kind(
                "architecture-review"
            ),
            "classified_study_count": classified_studies,
            "component_domain_trial_counts": dict(
                sorted(component_domain_trial_counts.items())
            ),
            "legacy_unclassified_study_count": len(studies) - classified_studies,
            "evidence_state_counts": dict(sorted(evidence_state_counts.items())),
            "mission_outcome_counts": dict(sorted(mission_outcomes.items())),
            "negative_memory_count": index.count_by_kind("negative-memory"),
            "research_layer_study_counts": dict(sorted(layer_counts.items())),
            "study_count": len(studies),
            "study_kpi_count": index.count_by_kind("study-kpi"),
            "study_outcome_counts": dict(sorted(outcome_counts.items())),
            "system_architecture_study_counts": dict(
                sorted(architecture_counts.items())
            ),
            "trial_count": len(trials),
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
        allow_active_stable_boundary: bool = False,
        allow_active_unexecuted_study_boundary: bool = False,
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
        if type(allow_active_stable_boundary) is not bool:
            raise TransitionError(
                "active stable research protocol boundary flag must be bool"
            )
        if type(allow_active_unexecuted_study_boundary) is not bool:
            raise TransitionError(
                "active unexecuted Study protocol boundary flag must be bool"
            )
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
            portfolio_boundary = (
                isinstance(science.get("active_mission"), str)
                and isinstance(science.get("active_initiative"), str)
                and current.get("next_action", {}).get("kind")
                == "portfolio_decision"
                and all(
                    science.get(name) is None
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
            )
            mission_boundary = (
                allow_active_stable_boundary
                and self._active_mission_stable_boundary(current)
            )
            active_batch = science.get("active_batch")
            active_study = science.get("active_study")
            active_batch_record = (
                None
                if not isinstance(active_batch, dict)
                else index.get(
                    "batch-open",
                    str(active_batch.get("id", "")),
                )
            )
            active_study_record = (
                None
                if not isinstance(active_study, str)
                else index.get("study-open", active_study)
            )
            registration_only_surface = False
            if (
                allow_active_unexecuted_study_boundary
                and active_batch_record is not None
                and active_study_record is not None
                and active_batch_record.status == "open"
                and active_batch_record.subject == f"Study:{active_study}"
                and index.event_head(
                    f"batch-budget:{active_batch_record.record_id}"
                )
                is None
                and not index.records_by_payload_text(
                    "job-declared",
                    "batch_id",
                    active_batch_record.record_id,
                )
            ):
                trial_head = index.event_head(
                    f"batch-trials:{active_batch_record.record_id}"
                )
                if trial_head is None:
                    registration_only_surface = True
                elif active_study_record.payload.get("replay_obligation_ids"):
                    from axiom_rift.operations.replay_study_admission import (
                        ReplayStudyAdmissionError,
                        inspect_replay_study_registration,
                    )

                    try:
                        inspect_replay_study_registration(
                            index,
                            study_record=active_study_record,
                            batch_record=active_batch_record,
                        ).require_usable()
                    except ReplayStudyAdmissionError as exc:
                        raise RecoveryRequired(str(exc)) from exc
                    registration_only_surface = True
            active_unexecuted_study_boundary = (
                allow_active_unexecuted_study_boundary
                and isinstance(science.get("active_mission"), str)
                and isinstance(science.get("active_initiative"), str)
                and isinstance(active_study, str)
                and isinstance(active_batch, dict)
                and current.get("next_action")
                == {
                    "kind": "declare_job",
                    "batch_id": active_batch.get("id"),
                }
                and all(
                    science.get(name) is None
                    for name in (
                        "active_executable",
                        "active_holdout_evaluation",
                        "active_job",
                        "active_lineage",
                        "active_release",
                        "active_repair",
                    )
                )
                and registration_only_surface
            )
            if not (
                portfolio_boundary
                or mission_boundary
                or active_unexecuted_study_boundary
            ):
                raise TransitionError(
                    "research protocol activation requires the stable Portfolio "
                    "boundary, its explicit stable Mission boundary, or an "
                    "explicit unexecuted Study boundary"
                )
            if (
                not isinstance(science.get("active_mission"), str)
                or (
                    not active_unexecuted_study_boundary
                    and any(
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
                )
            ):
                raise TransitionError(
                    "research protocol activation has active scientific execution"
                )
            stream = "research-protocol:scientific"
            prior_head = index.event_head(stream)
            prior = (
                None
                if prior_head is None
                else index.get(prior_head.record_kind, prior_head.record_id)
            )
            prior_activation = None
            if prior is not None:
                try:
                    prior_activation = ResearchProtocolActivation(
                        protocol=ResearchProtocol(prior.payload.get("protocol")),
                        validator_id=prior.payload.get("validator_id"),
                        authority_manifest_digest=prior.payload.get(
                            "authority_manifest_digest"
                        ),
                        audit_artifact_hash=prior.payload.get(
                            "audit_artifact_hash"
                        ),
                    )
                except (TypeError, ValueError):
                    prior_activation = None
            if prior_head is not None and (
                prior is None
                or prior.kind != "research-protocol-activation"
                or prior.status != "active"
                or prior.event_sequence != prior_head.sequence
                or prior.subject != "ProjectGoal:OPERATING_DIRECTION.md"
                or prior_activation is None
                or prior.record_id != prior_activation.identity
                or prior.fingerprint
                != prior_activation.identity.removeprefix("research-protocol:")
                or prior.payload.get("schema")
                != "research_protocol_activation.v1"
                or prior.payload.get("ordinal") != prior_head.sequence
                or prior.payload.get("scientific_trial_delta") != 0
            ):
                raise RecoveryRequired(
                    "prospective scientific protocol projection is invalid"
                )
            if (
                prior is not None
                and prior.payload.get("authority_manifest_digest")
                == activation.authority_manifest_digest
                and prior.payload.get("validator_id") == activation.validator_id
            ):
                raise TransitionError(
                    "prospective scientific protocol is already bound to this "
                    "authority and validator"
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
            next_action = current["next_action"]
            post_holdout_development_id = next_action.get(
                "post_holdout_development_id"
            )
            if post_holdout_development_id is not None:
                required_holdout_id = science.get("required_future_holdout_id")
                if (
                    science.get("holdout_reveals", 0) < 1
                    or not isinstance(required_holdout_id, str)
                    or not isinstance(post_holdout_development_id, str)
                ):
                    raise TransitionError(
                        "Initiative post-holdout reentry authority is malformed"
                    )
                self._require_post_holdout_development_authority(
                    index,
                    mission_id=science["active_mission"],
                    record_id=post_holdout_development_id,
                    required_holdout_id=required_holdout_id,
                )
            replay_constraints = self._replay_scheduler_constraints(
                index,
                mission_id=science["active_mission"],
            )
            incoming_replay = {
                name: current["next_action"].get(name)
                for name in (
                    "pending_replay_obligation_ids",
                    "required_replay_priority",
                )
                if current["next_action"].get(name) is not None
            }
            if incoming_replay != (replay_constraints or {}):
                raise TransitionError(
                    "Initiative admission replay scheduler authority is stale"
                )
            research_intake_id: str | None = None
            if not self.engineering_fixture:
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
                if isinstance(post_holdout_development_id, str):
                    body["next_action"]["post_holdout_development_id"] = (
                        post_holdout_development_id
                    )
                if replay_constraints is not None:
                    body["next_action"].update(replay_constraints)
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
            replay_heads = self._historical_replay_obligation_heads(
                _index,
                mission_id=science["active_mission"],
            )
            if any(head.status == "in_progress" for _, head in replay_heads):
                raise TransitionError(
                    "Initiative close cannot strand an in-progress historical replay"
                )
            science["active_initiative"] = None
            self._drop_authorization(body, SubjectKind.INITIATIVE, initiative_id)
            body["next_action"] = {
                "kind": "choose_next_initiative_or_terminal",
                "mission_id": science["active_mission"],
            }
            replay_constraints = self._replay_scheduler_constraints(
                _index,
                mission_id=science["active_mission"],
            )
            if replay_constraints is not None:
                body["next_action"].update(replay_constraints)
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
                        "source_state_record_id": source_state.record_id,
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
                    effective_scope = (
                        None
                        if not isinstance(scientific, dict)
                        else _effective_completion_scope(_index, evidence)
                    )
                    if (
                        not isinstance(scientific, dict)
                        or effective_scope is None
                        or effective_scope.scientific_eligible is not True
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
                            or effective_scope.candidate_eligible is True
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
            pending_gap = body.get("next_action")
            engineering_gap = (
                pending_gap
                if isinstance(pending_gap, Mapping)
                and pending_gap.get("kind")
                == "resolve_candidate_engineering_gap"
                else None
            )
            if engineering_gap is not None:
                if (
                    engineering_gap.get("executable_id") != executable_id
                    or not isinstance(
                        engineering_gap.get("completion_record_id"), str
                    )
                    or index.get(
                        "job-completed",
                        engineering_gap["completion_record_id"],
                    )
                    is None
                ):
                    raise RecoveryRequired(
                        "candidate engineering-gap resolution lost its completion"
                    )
                if engineering_gap.get("successor_scope") is not None and (
                    disposition != "invalidated"
                    or reason
                    != "engineering_requires_scientific_change"
                ):
                    raise TransitionError(
                        "scientific-change engineering gap must invalidate the frozen candidate"
                    )
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
            disposition_identity = {
                "candidate_id": candidate.record_id,
                "disposition": disposition,
                "reason": reason,
            }
            disposition_payload = {
                "candidate_id": candidate.record_id,
                "executable_id": executable_id,
                "mission_id": science["active_mission"],
                "reason": reason,
            }
            if engineering_gap is not None:
                disposition_identity[
                    "engineering_gap_completion_record_id"
                ] = engineering_gap["completion_record_id"]
                disposition_payload["engineering_gap"] = dict(
                    engineering_gap
                )
            record_id = canonical_digest(
                domain="candidate-disposition",
                payload=disposition_identity,
            )
            record = _record(
                kind="candidate-disposition",
                record_id=record_id,
                subject=f"Executable:{executable_id}",
                status=disposition,
                fingerprint=candidate.fingerprint,
                payload=disposition_payload,
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
        from axiom_rift.operations.runtime_source_readiness import (
            RuntimeSourceReadinessError,
            current_readiness_payload,
            validate_completion_receipt_reuse,
        )
        from axiom_rift.runtime.source_lifecycle_coverage import (
            SourceLifecycleCoverageError,
            derive_source_lifecycle_coverage,
            require_source_lifecycle_coverage_ids,
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
        executable_manifest = candidate.payload.get("executable")
        if not isinstance(executable_manifest, Mapping):
            raise TransitionError(
                "Release candidate lacks its frozen Executable manifest"
            )
        try:
            required_source_lifecycle_rows = (
                derive_source_lifecycle_coverage(executable_manifest)
            )
        except SourceLifecycleCoverageError as exc:
            raise TransitionError(str(exc)) from exc
        required_source_lifecycle_ids = {
            row["coverage_id"] for row in required_source_lifecycle_rows
        }
        current_subject = self._current_subject(
            control, SubjectKind.EXECUTABLE, executable_id
        )
        candidate_source_bindings = candidate.payload.get("source_bindings")
        if not isinstance(candidate_source_bindings, list):
            raise TransitionError("Release candidate source bindings are malformed")
        source_bindings_by_id: dict[str, Mapping[str, Any]] = {}
        for source_binding in candidate_source_bindings:
            if (
                not isinstance(source_binding, Mapping)
                or set(source_binding)
                != {
                    "eligibility_receipt_id",
                    "mapping_identity",
                    "source_contract_id",
                    "source_state_record_id",
                }
                or type(source_binding.get("source_contract_id")) is not str
                or type(source_binding.get("mapping_identity")) is not str
                or type(source_binding.get("eligibility_receipt_id")) is not str
                or type(source_binding.get("source_state_record_id")) is not str
                or source_binding["source_contract_id"] in source_bindings_by_id
            ):
                raise TransitionError("Release candidate source bindings are malformed")
            source_bindings_by_id[source_binding["source_contract_id"]] = source_binding
        candidate_source_ids = candidate.payload.get("executable", {}).get(
            "source_contracts"
        )
        if (
            not isinstance(candidate_source_ids, list)
            or candidate_source_ids != sorted(source_bindings_by_id)
        ):
            raise TransitionError("Release candidate source inventory is malformed")
        current_source_states: dict[str, IndexRecord] = {}
        current_readiness_rows: list[dict[str, Any]] = []
        for source_id in candidate_source_ids:
            frozen_binding = source_bindings_by_id[source_id]
            frozen_state = index.get(
                "source-state", frozen_binding["source_state_record_id"]
            )
            frozen_sequence = (
                None if frozen_state is None else frozen_state.event_sequence
            )
            expected_frozen_state_id = (
                None
                if type(frozen_sequence) is not int
                else canonical_digest(
                    domain="source-state",
                    payload={
                        "source_id": source_id,
                        "state": "runtime_eligible",
                        "ordinal": frozen_sequence,
                        "evidence_receipt_id": frozen_binding[
                            "eligibility_receipt_id"
                        ],
                    },
                )
            )
            if (
                frozen_state is None
                or frozen_state.kind != "source-state"
                or frozen_state.status != "runtime_eligible"
                or frozen_state.subject != f"Source:{source_id}"
                or frozen_state.fingerprint != source_id
                or frozen_state.event_stream != f"source:{source_id}"
                or frozen_state.record_id != expected_frozen_state_id
                or frozen_state.payload.get("ordinal") != frozen_sequence
                or frozen_state.payload.get("evidence_receipt_id")
                != frozen_binding["eligibility_receipt_id"]
                or frozen_state.payload.get("mapping_identity")
                != frozen_binding["mapping_identity"]
                or type(frozen_state.authority_sequence) is not int
                or type(candidate.authority_sequence) is not int
                or frozen_state.authority_sequence
                >= candidate.authority_sequence
            ):
                raise TransitionError(
                    "Release candidate source binding lacks its exact frozen state"
                )
            state = self._require_runtime_source(index, source_id)
            if (
                state.payload.get("mapping_identity")
                != frozen_binding["mapping_identity"]
            ):
                raise TransitionError(
                    "Release current source mapping differs from its frozen candidate"
                )
            current_source_states[source_id] = state
            try:
                current_readiness_rows.append(
                    current_readiness_payload(
                        source_contract_id=source_id,
                        current_state=state,
                    )
                )
            except RuntimeSourceReadinessError as exc:
                raise TransitionError(str(exc)) from exc
        current_readiness_rows.sort(key=lambda item: item["source_contract_id"])
        current_source_receipts = [
            item["receipt_id"] for item in current_readiness_rows
        ]

        def authority_event_time(record: IndexRecord) -> str:
            offset, sequence, event_id = self._index_record_authority_key(record)
            event = self.journal.read_event_at(
                offset=offset,
                expected_sequence=sequence,
                expected_event_id=event_id,
            )
            occurred_at_utc = event.get("occurred_at_utc")
            if type(occurred_at_utc) is not str:
                raise RecoveryRequired(
                    "Release evidence authority timestamp is unavailable"
                )
            return occurred_at_utc

        parity: set[str] = set()
        cases: set[str] = set()
        artifact_hashes: set[str] = set()
        artifact_roles: dict[str, str] = {}
        artifact_role_completion_ids: dict[str, str] = {}
        artifact_role_hashes: set[str] = set()
        job_ids: list[str] = []
        runtime_permit_ids: list[str] = []
        depth_records: list[dict[str, str]] = []
        completion_readiness_rows: list[dict[str, Any]] = []
        completion_source_receipts: dict[str, list[str]] = {}
        source_lifecycle_coverage_ids: set[str] = set()
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
                "source_snapshot_rows",
                "source_state_record_ids",
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
            runtime_source_receipts = runtime.get("source_receipt_ids")
            runtime_source_state_ids = runtime.get("source_state_record_ids")
            runtime_source_snapshot_rows = runtime.get("source_snapshot_rows")
            source_snapshot_by_id: dict[str, Mapping[str, Any]] = {}
            if isinstance(runtime_source_snapshot_rows, list):
                for source_snapshot in runtime_source_snapshot_rows:
                    if (
                        not isinstance(source_snapshot, Mapping)
                        or set(source_snapshot)
                        != {
                            "mapping_identity",
                            "source_contract_id",
                            "source_receipt_id",
                            "source_state_record_id",
                        }
                        or type(source_snapshot.get("source_contract_id"))
                        is not str
                        or source_snapshot["source_contract_id"]
                        in source_snapshot_by_id
                    ):
                        raise TransitionError(
                            "Release Job source snapshot rows are malformed"
                        )
                    source_snapshot_by_id[
                        source_snapshot["source_contract_id"]
                    ] = source_snapshot
            if (
                engine_entry is None
                or engine_entry.payload.get("job_id") != job_id
                or engine_entry.payload.get("candidate_id") != candidate_id
                or engine_entry.payload.get("runtime_permit_id")
                != runtime.get("runtime_permit_id")
                or not isinstance(runtime_source_receipts, list)
                or any(type(item) is not str for item in runtime_source_receipts)
                or len(set(runtime_source_receipts)) != len(runtime_source_receipts)
                or not isinstance(runtime_source_state_ids, list)
                or any(type(item) is not str for item in runtime_source_state_ids)
                or runtime_source_state_ids
                != sorted(set(runtime_source_state_ids))
                or not isinstance(runtime_source_snapshot_rows, list)
                or list(source_snapshot_by_id) != candidate_source_ids
                or sorted(
                    row["source_receipt_id"]
                    for row in source_snapshot_by_id.values()
                )
                != runtime_source_receipts
                or sorted(
                    row["source_state_record_id"]
                    for row in source_snapshot_by_id.values()
                )
                != runtime_source_state_ids
                or engine_entry.payload.get("source_receipt_ids")
                != runtime_source_receipts
                or engine_entry.payload.get("source_state_record_ids")
                != runtime_source_state_ids
                or engine_entry.payload.get("source_snapshot_rows")
                != runtime_source_snapshot_rows
            ):
                raise TransitionError("Release Job lacks durable engine-entry provenance")
            if (
                runtime["mission_id"] != mission_id
                or runtime["candidate_id"] != candidate_id
                or runtime["executable_id"] != executable_id
                or runtime["action"] != binding["action"]
                or runtime["evidence_depth"] != binding["evidence_depth"]
            ):
                raise TransitionError("Release Job is stale or bound to another activation")
            completion_source_rows: list[dict[str, Any]] = []
            consumed_receipts: set[str] = set()
            for source_id in candidate_source_ids:
                source_binding = source_bindings_by_id[source_id]
                try:
                    source_row = validate_completion_receipt_reuse(
                        index=index,
                        source_contract_id=source_id,
                        candidate_mapping_identity=source_binding[
                            "mapping_identity"
                        ],
                        completion_receipt_ids=runtime_source_receipts,
                        completion_source_snapshot=(
                            source_snapshot_by_id[source_id]
                        ),
                        current_state=current_source_states[source_id],
                        engine_entry_authority_sequence=(
                            engine_entry.authority_sequence
                        ),
                        completion_authority_sequence=(
                            completion.authority_sequence
                        ),
                        engine_entry_occurred_at_utc=authority_event_time(
                            engine_entry
                        ),
                        completion_occurred_at_utc=authority_event_time(
                            completion
                        ),
                        verify_artifact=self.evidence.verify,
                    )
                except RuntimeSourceReadinessError as exc:
                    raise TransitionError(
                        f"Release invalidates completion {completion_id}: {exc}"
                    ) from exc
                receipt_id = source_row["completion_receipt_id"]
                if receipt_id in consumed_receipts:
                    raise TransitionError(
                        "Release completion reuses one receipt for multiple sources"
                    )
                consumed_receipts.add(receipt_id)
                completion_source_rows.append(source_row)
            if consumed_receipts != set(runtime_source_receipts):
                raise TransitionError(
                    "Release completion source receipts do not match its keyed source inventory"
                )
            completion_source_receipts[completion_id] = sorted(
                runtime_source_receipts
            )
            completion_readiness_rows.append(
                {
                    "completion_record_id": completion_id,
                    "sources": completion_source_rows,
                }
            )
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
                if role in artifact_roles:
                    if artifact_roles[role] != artifact_hash:
                        raise TransitionError(
                            "Release artifact role has conflicting evidence"
                        )
                    raise TransitionError(
                        "Release artifact role producer is ambiguous"
                    )
                if role not in artifact_roles and artifact_hash in artifact_role_hashes:
                    raise TransitionError("one artifact cannot satisfy multiple Release roles")
                if artifact_hash not in durable:
                    raise TransitionError("Release role is not a durable Job output")
                artifact_roles[role] = artifact_hash
                artifact_role_completion_ids[role] = completion_id
                artifact_role_hashes.add(artifact_hash)
            depth = runtime["evidence_depth"]
            observed_parity = set(runtime.get("parity_surfaces", []))
            observed_cases = set(runtime.get("materialization_cases", []))
            try:
                planned_source_lifecycle_ids = (
                    require_source_lifecycle_coverage_ids(
                        binding.get(
                            "planned_source_lifecycle_coverage_ids"
                        ),
                        allowed_rows=required_source_lifecycle_rows,
                        planned_materialization_cases=binding.get(
                            "planned_materialization_cases", ()
                        ),
                    )
                )
            except SourceLifecycleCoverageError as exc:
                raise TransitionError(
                    f"Release invalidates completion {completion_id}: {exc}"
                ) from exc
            if runtime.get("source_lifecycle_coverage_ids") != list(
                planned_source_lifecycle_ids
            ):
                raise TransitionError(
                    "Release Job source lifecycle coverage differs from its "
                    "preregistered and validated plan"
                )
            if depth == EvidenceDepth.EXECUTION_PROOF.value:
                if (
                    observed_cases
                    or not observed_parity
                    or planned_source_lifecycle_ids
                ):
                    raise TransitionError("execution proof Release evidence is malformed")
                parity.update(observed_parity)
            elif depth == EvidenceDepth.MATERIALIZATION.value:
                if observed_parity or not observed_cases:
                    raise TransitionError("materialization Release evidence is malformed")
                cases.update(observed_cases)
                source_lifecycle_coverage_ids.update(
                    planned_source_lifecycle_ids
                )
            else:
                raise TransitionError("Release Job has an ineligible evidence depth")
            artifact_hashes.update(durable)
            job_ids.append(job_id)
            runtime_permit_ids.append(permit_id)
            depth_records.append({"completion_id": completion_id, "depth": depth})
        missing_parity = REQUIRED_PARITY - parity
        missing_cases = REQUIRED_CASES - cases
        missing_roles = REQUIRED_RELEASE_ARTIFACT_ROLES - set(artifact_roles)
        missing_source_lifecycle = (
            required_source_lifecycle_ids
            - source_lifecycle_coverage_ids
        )
        if (
            missing_parity
            or missing_cases
            or missing_roles
            or missing_source_lifecycle
        ):
            raise TransitionError(
                f"Release evidence coverage is incomplete: "
                f"parity={sorted(missing_parity)!r}, cases={sorted(missing_cases)!r}, "
                f"roles={sorted(missing_roles)!r}, "
                f"source_lifecycle={sorted(missing_source_lifecycle)!r}"
            )
        handoff_hash = artifact_roles["local_handoff_manifest"]
        handoff_completion_id = artifact_role_completion_ids[
            "local_handoff_manifest"
        ]
        handoff_source_receipts = completion_source_receipts[
            handoff_completion_id
        ]
        try:
            handoff = parse_canonical(self.evidence.read_verified(handoff_hash))
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
            "source_receipt_ids": handoff_source_receipts,
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
            "source_readiness": {
                "completion_uses": completion_readiness_rows,
                "current": current_readiness_rows,
                "schema": "release_source_readiness.v1",
            },
            "source_lifecycle_coverage": {
                "required_rows": [
                    dict(row) for row in required_source_lifecycle_rows
                ],
                "satisfied_coverage_ids": sorted(
                    source_lifecycle_coverage_ids
                ),
                "schema": "release_source_lifecycle_coverage.v1",
            },
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
        try:
            return component_manifest_surfaces(manifest).protocol_neutral
        except ComponentManifestError as exc:
            raise TransitionError(str(exc)) from exc

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
            cross_domain_variants = index.component_manifests_by_surface(
                COMPONENT_SURFACE_PROTOCOL_NEUTRAL,
                protocol_neutral_surface,
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

    def backfill_semantic_question_registry(
        self,
        *,
        operation_id: str,
    ) -> TransitionResult:
        """Bind every historical Study to one exact question core, without credit."""

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
                    "Semantic question backfill requires a stable scientific boundary"
                )
            from axiom_rift.operations.semantic_question_registry import (
                SemanticQuestionRegistryError,
                SemanticQuestionRegistryIntegrityError,
                backfill_semantic_question_records,
                require_semantic_question_projection,
                semantic_question_registry_activation_record,
            )

            try:
                study_opens = index.records_by_kind("study-open")
                projections = backfill_semantic_question_records(study_opens)
                core_count = sum(
                    record.kind == "semantic-question-core"
                    for record in projections
                )
                binding_count = sum(
                    record.kind == "semantic-question-study"
                    for record in projections
                )
                if binding_count != len(study_opens):
                    raise SemanticQuestionRegistryIntegrityError(
                        "semantic question backfill lost a Study binding"
                    )
                activation = semantic_question_registry_activation_record(
                    operation_id=operation_id,
                    study_count=binding_count,
                    core_count=core_count,
                )
                records: list[IndexRecord] = []
                for projection in (*projections, activation):
                    pending = require_semantic_question_projection(
                        index, projection
                    )
                    if pending is not None:
                        records.append(pending)
            except SemanticQuestionRegistryIntegrityError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except SemanticQuestionRegistryError as exc:
                raise TransitionError(str(exc)) from exc
            return self._body(current), records, {
                "claim": science["claim"],
                "core_count": core_count,
                "holdout_delta": 0,
                "projected_record_count": len(records),
                "study_binding_count": binding_count,
                "trial_delta": 0,
            }

        return self._commit(
            event_kind="semantic_question_registry_backfilled",
            operation_id=operation_id,
            subject="ProjectGoal:OPERATING_DIRECTION.md",
            payload={
                "claim_delta": "none",
                "holdout_delta": 0,
                "trial_delta": 0,
            },
            prepare=prepare,
        )

    def record_semantic_question_corrections(
        self,
        *,
        equivalence_proposals: Sequence[Any],
        lineage_proposals: Sequence[Any],
        review_artifact_hash: str,
        operation_id: str,
    ) -> TransitionResult:
        """Add expert-reviewed historical lineage without rewriting verdicts."""

        self._require_study_close_delivery_guard()
        _require_digest(
            "semantic question review artifact",
            review_artifact_hash,
        )
        if not self.engineering_fixture:
            self.evidence.verify(review_artifact_hash)
        from axiom_rift.research.semantic_question import (
            SemanticQuestionEquivalenceProposal,
            SemanticQuestionLineageProposal,
        )

        if (
            not isinstance(equivalence_proposals, (list, tuple))
            or any(
                not isinstance(item, SemanticQuestionEquivalenceProposal)
                for item in equivalence_proposals
            )
            or not isinstance(lineage_proposals, (list, tuple))
            or not lineage_proposals
            or any(
                not isinstance(item, SemanticQuestionLineageProposal)
                for item in lineage_proposals
            )
        ):
            raise TransitionError(
                "semantic question corrections require typed proposal sequences"
            )
        if len({item.identity for item in equivalence_proposals}) != len(
            equivalence_proposals
        ) or len({item.identity for item in lineage_proposals}) != len(
            lineage_proposals
        ):
            raise TransitionError(
                "semantic question correction proposals must be unique"
            )
        if len({item.successor_study_id for item in lineage_proposals}) != len(
            lineage_proposals
        ):
            raise TransitionError(
                "one correction event may record only one incoming edge per Study"
            )
        equivalence_ids = tuple(
            sorted(item.identity for item in equivalence_proposals)
        )
        lineage_ids = tuple(sorted(item.identity for item in lineage_proposals))

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
                    "Semantic question correction requires a stable scientific boundary"
                )
            from axiom_rift.operations.semantic_question_registry import (
                SemanticQuestionRegistryError,
                SemanticQuestionRegistryIntegrityError,
                require_semantic_question_projection,
                require_semantic_question_registry_activation,
                semantic_question_equivalence_record,
                semantic_question_lineage_record,
            )

            try:
                if require_semantic_question_registry_activation(index) is None:
                    raise SemanticQuestionRegistryError(
                        "semantic question registry is not active"
                    )
                if not self.engineering_fixture:
                    protocol_head = index.event_head(
                        "research-protocol:scientific"
                    )
                    protocol = (
                        None
                        if protocol_head is None
                        else index.get(
                            protocol_head.record_kind,
                            protocol_head.record_id,
                        )
                    )
                    if (
                        protocol is None
                        or protocol.kind != "research-protocol-activation"
                        or protocol.status != "active"
                        or protocol.event_sequence != protocol_head.sequence
                        or protocol.payload.get("authority_manifest_digest")
                        != current["authority"]["manifest_digest"]
                    ):
                        raise RecoveryRequired(
                            "semantic question review lacks the active protocol"
                        )
                    if (
                        protocol.payload.get("audit_artifact_hash")
                        != review_artifact_hash
                    ):
                        raise SemanticQuestionRegistryError(
                            "semantic question review artifact differs from the active protocol"
                        )
                records: list[IndexRecord] = []
                accepted_equivalences: dict[str, IndexRecord] = {}
                for proposal in equivalence_proposals:
                    projected = semantic_question_equivalence_record(
                        index, proposal
                    )
                    pending = require_semantic_question_projection(
                        index, projected
                    )
                    accepted_equivalences[proposal.identity] = (
                        projected
                        if pending is not None
                        else index.get(projected.kind, projected.record_id)
                    )  # type: ignore[assignment]
                    if accepted_equivalences[proposal.identity] is None:
                        raise SemanticQuestionRegistryIntegrityError(
                            "accepted semantic question equivalence disappeared"
                        )
                    if pending is not None:
                        records.append(pending)
                for proposal in lineage_proposals:
                    accepted = None
                    equivalence_id = proposal.equivalence_proposal_id
                    if equivalence_id is not None:
                        accepted = accepted_equivalences.get(equivalence_id)
                        if accepted is None:
                            matches = tuple(
                                record
                                for record in index.records_by_fingerprint(
                                    equivalence_id
                                )
                                if record.kind
                                == "semantic-question-equivalence"
                            )
                            if len(matches) != 1:
                                raise SemanticQuestionRegistryError(
                                    "lineage equivalence is unavailable or ambiguous"
                                )
                            accepted = matches[0]
                    projected = semantic_question_lineage_record(
                        index,
                        proposal,
                        equivalence_record=accepted,
                    )
                    pending = require_semantic_question_projection(
                        index, projected
                    )
                    if pending is not None:
                        records.append(pending)
            except SemanticQuestionRegistryIntegrityError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except SemanticQuestionRegistryError as exc:
                raise TransitionError(str(exc)) from exc
            return self._body(current), records, {
                "claim": science["claim"],
                "equivalence_count": len(equivalence_proposals),
                "holdout_delta": 0,
                "lineage_count": len(lineage_proposals),
                "projected_record_count": len(records),
                "review_artifact_hash": review_artifact_hash,
                "trial_delta": 0,
            }

        return self._commit(
            event_kind="semantic_question_corrections_recorded",
            operation_id=operation_id,
            subject="ProjectGoal:OPERATING_DIRECTION.md",
            payload={
                "claim_delta": "none",
                "equivalence_proposal_ids": list(equivalence_ids),
                "holdout_delta": 0,
                "lineage_proposal_ids": list(lineage_ids),
                "review_artifact_hash": review_artifact_hash,
                "trial_delta": 0,
            },
            prepare=prepare,
        )

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
            replay_admission = self._study_replay_implementation_admission(
                index,
                study_id=study_id,
                authority_manifest_digest=current.get("authority", {}).get(
                    "manifest_digest"
                ),
            )
            study_replay_obligation_ids = study_record.payload.get(
                "replay_obligation_ids"
            )
            if study_replay_obligation_ids and replay_admission is None:
                raise RecoveryRequired(
                    "replay trial registration requires a current "
                    "implementation admission"
                )
            if replay_admission is not None:
                request_payload = replay_admission.payload.get("request")
                admitted_manifests = (
                    None
                    if not isinstance(request_payload, Mapping)
                    else request_payload.get("executable_manifests")
                )
                if (
                    not isinstance(admitted_manifests, list)
                    or executable.to_identity_payload()
                    not in admitted_manifests
                ):
                    raise TransitionError(
                        "Executable differs from the replay implementation admission"
                    )
                self._require_replay_registration_source_authority(
                    index,
                    admission=replay_admission,
                    executable=executable,
                )
            material_identity = study_record.payload["material_identity"]
            from axiom_rift.operations.replay_projection import (
                ReplayProjectionError,
                ReplayTransitionError,
                prepare_execution_progress,
            )

            try:
                progressed_replay_obligation_ids, replay_progress_records = (
                    prepare_execution_progress(
                        index,
                        study_record=study_record,
                        batch_record=batch_record,
                        executable_id=executable_id,
                        executable_payload=executable.to_identity_payload(),
                    )
                )
            except ReplayProjectionError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except ReplayTransitionError as exc:
                raise TransitionError(str(exc)) from exc
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
                return self._body(current), replay_progress_records, {
                    "trial_delta": 0,
                    "cache_hit": True,
                    "replay_obligation_ids": list(
                        progressed_replay_obligation_ids
                    ),
                }
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
                    **(
                        {
                            "replay_obligation_ids": list(
                                progressed_replay_obligation_ids
                            )
                        }
                        if progressed_replay_obligation_ids
                        else {}
                    ),
                },
                event_stream=f"batch-trials:{batch['id']}",
                event_sequence=evaluated_count + 1,
            )
            records = [
                *replay_progress_records,
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

    def require_study_close_delivery_guard(self) -> None:
        """Public fail-closed preflight for coherent scientific mutations."""

        self._require_study_close_delivery_guard()

    def _require_study_close_delivery_guard(self) -> None:
        if self.engineering_fixture:
            return
        from axiom_rift.operations.study_close_git import (
            StudyCloseDeliveryError,
            require_all_study_close_deliveries,
            require_study_close_delivery_observation,
            require_study_close_guard_ready,
        )

        try:
            capability = getattr(self, "study_close_guard_capability", None)
            observation = getattr(
                self,
                "study_close_delivery_observation",
                None,
            )
            if observation is not None:
                require_study_close_delivery_observation(
                    self.root,
                    observation,
                )
            elif capability is None:
                require_study_close_guard_ready(self.root)
                require_all_study_close_deliveries(self.root)
            else:
                require_study_close_guard_ready(
                    self.root, capability=capability
                )
                require_all_study_close_deliveries(
                    self.root, capability=capability
                )
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
                effective_scope = (
                    None
                    if evidence is None or not isinstance(scientific, dict)
                    else _effective_completion_scope(index, evidence)
                )
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
                    or effective_scope is None
                    or effective_scope.scientific_eligible is not True
                    or effective_scope.candidate_eligible is not False
                    or scientific.get("executable_id") != memory.executable_identity
                ):
                    raise TransitionError("negative memory evidence reference is invalid")
                evidence_modes = list(effective_scope.evidence_modes)
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
            required_axes_scientific_references,
        )
        from axiom_rift.operations.effective_study_diagnosis import (
            EffectiveStudyDiagnosisError,
            effective_study_diagnoses_by_study,
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
            axis_values = tuple(axes.values())
            axis_resolutions = {
                axis["axis_id"]: resolution
                for axis, resolution in zip(
                    axis_values,
                    self._effective_axis_resolutions(index, axis_values),
                    strict=True,
                )
            }
            for disposition in normalized:
                axis = axes.get(disposition.axis_id)
                resolution = axis_resolutions.get(disposition.axis_id)
                if (
                    disposition.mission_id != mission_id
                    or disposition.portfolio_snapshot_id != snapshot.record_id
                    or axis is None
                    or resolution is None
                    or axis.get("axis_identity") != disposition.axis_identity
                ):
                    raise TransitionError(
                        "axis disposition is stale or belongs to another Portfolio"
                    )
                if not resolution.terminal_eligible:
                    raise TransitionError(
                        "axis disposition cannot interpret replay- or scope-blocked authority"
                    )
            try:
                required_references_by_target = (
                    required_axes_scientific_references(
                        index,
                        targets=tuple(
                            (
                                mission_id,
                                disposition.axis_id,
                                disposition.axis_identity,
                            )
                            for disposition in normalized
                        ),
                    )
                )
            except AxisDispositionEvidenceError as exc:
                raise TransitionError(str(exc)) from exc
            try:
                diagnosis_projection = effective_study_diagnoses_by_study(
                    index,
                    mission_id=mission_id,
                )
            except EffectiveStudyDiagnosisError as exc:
                raise RecoveryRequired(str(exc)) from exc
            records: list[IndexRecord] = []
            accepted_ids: list[str] = []
            for disposition in normalized:
                try:
                    required_references = required_references_by_target[
                        (
                            mission_id,
                            disposition.axis_id,
                            disposition.axis_identity,
                        )
                    ]
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
                            diagnosis_projection=diagnosis_projection,
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
            required_axes_scientific_references,
        )
        from axiom_rift.operations.effective_study_diagnosis import (
            EffectiveStudyDiagnosisError,
            effective_study_diagnoses_by_study,
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
            axis_values = tuple(axes.values())
            axis_resolutions = {
                axis["axis_id"]: resolution
                for axis, resolution in zip(
                    axis_values,
                    self._effective_axis_resolutions(index, axis_values),
                    strict=True,
                )
            }
            blocked_axis_ids = sorted(
                axis_id
                for axis_id, resolution in axis_resolutions.items()
                if not resolution.terminal_eligible
            )
            mission_axis_blockers = self._mission_effective_axis_blockers(
                index,
                mission_id=science["active_mission"],
            )
            if blocked_axis_ids or mission_axis_blockers:
                raise TransitionError(
                    "exhaustion cannot bypass unresolved replay or source authority"
                )
            eligible_axes = {
                axis_id: axis
                for axis_id, axis in axes.items()
                if axis_resolutions[axis_id].terminal_eligible
            }
            families = {
                axis["mechanism_family"] for axis in eligible_axes.values()
            }
            research_layers = {
                axis.get("primary_research_layer")
                for axis in eligible_axes.values()
            }
            resolved_architectures = [
                self._axis_architecture_anchor(index, axis)
                for axis in eligible_axes.values()
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
                set(normalized) != set(eligible_axes)
                or len(eligible_axes) < standard["minimum_axes"]
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
            try:
                required_references_by_target = (
                    required_axes_scientific_references(
                        index,
                        targets=tuple(
                            (
                                science["active_mission"],
                                axis_id,
                                eligible_axes[axis_id]["axis_identity"],
                            )
                            for axis_id in sorted(eligible_axes)
                        ),
                    )
                )
            except AxisDispositionEvidenceError as exc:
                raise TransitionError(str(exc)) from exc
            try:
                diagnosis_projection = effective_study_diagnoses_by_study(
                    index,
                    mission_id=science["active_mission"],
                )
            except EffectiveStudyDiagnosisError as exc:
                raise RecoveryRequired(str(exc)) from exc
            family_executables: dict[str, set[str]] = {
                family: set() for family in families
            }
            axis_studies: dict[str, set[str]] = {
                axis_id: set() for axis_id in eligible_axes
            }
            axis_modes: dict[str, set[str]] = {
                axis_id: set() for axis_id in eligible_axes
            }
            global_executables: set[str] = set()
            scientifically_exhausted_axes: set[str] = set()
            carried_forward_axes: set[str] = set()
            retired_families: set[str] = set()
            disposition_summaries: dict[str, dict[str, Any]] = {}
            for axis_id, references in normalized.items():
                axis_identity = eligible_axes[axis_id]["axis_identity"]
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
                    required_references = required_references_by_target[
                        (
                            science["active_mission"],
                            axis_id,
                            axis_identity,
                        )
                    ]
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
                            diagnosis_projection=diagnosis_projection,
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
                    axis_modes[axis_id].update(
                        _terminal_scientific_evidence_modes(
                            binding.evidence_modes
                        )
                    )
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
                    family = eligible_axes[axis_id]["mechanism_family"]
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
                effective_scope = (
                    None
                    if not isinstance(scientific, dict)
                    else _effective_completion_scope(index, completion)
                )
                if (
                    completion.status != "success"
                    or not isinstance(scientific, dict)
                    or effective_scope is None
                    or effective_scope.candidate_eligible is not True
                ):
                    continue
                declaration = index.get(
                    "job-declared", completion.payload.get("job_id", "")
                )
                if (
                    declaration is None
                    or declaration.payload.get("mission_id")
                    != science["active_mission"]
                ):
                    continue
                declared_study_id = declaration.payload.get("study_id")
                if declared_study_id is None:
                    try:
                        holdout_lineage = holdout_completion_executable_lineage(
                            index, completion
                        )
                    except ExecutableAxisLineageError as exc:
                        raise TransitionError(
                            "Study-less positive evidence has malformed holdout lineage"
                        ) from exc
                    if holdout_lineage.mission_id != science["active_mission"]:
                        raise TransitionError(
                            "Study-less positive evidence changed Mission authority"
                        )
                    # Candidate authority is frozen from the originating Study
                    # evidence before holdout.  The Study-less holdout result is
                    # consumed by that candidate stream and must not manufacture
                    # a second axis completion or require a second disposition.
                    continue
                elif not isinstance(declared_study_id, str):
                    raise TransitionError(
                        "positive scientific evidence has malformed Study lineage"
                    )
                else:
                    try:
                        lineage = completion_executable_axis_lineage(
                            index, completion
                        )
                    except ExecutableAxisLineageError as exc:
                        raise TransitionError(
                            "positive scientific evidence has malformed Portfolio lineage"
                        ) from exc
                    axis_id = lineage.axis_id
                    axis_identity = lineage.axis_identity
                if (
                    axis_id not in axes
                    or axis_identity != axes[axis_id]["axis_identity"]
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
                    "active_holdout_evaluation",
                    "active_lineage",
                    "active_release",
                )
            ):
                raise TransitionError("external blocker requires preserved, disposed work")
            mission_id = science["active_mission"]
            next_action = current.get("next_action")
            if (
                not isinstance(next_action, dict)
                or next_action.get("kind") != "record_external_blocker"
                or next_action.get("dependency_id") != dependency_id
                or next_action.get("completion_record_ids")
                != list(completion_record_ids)
                or not isinstance(next_action.get("recovery_plan_id"), str)
            ):
                raise TransitionError(
                    "external blocker is not the exact judged recovery action"
                )
            plan_record = index.get(
                "external-recovery-plan", next_action["recovery_plan_id"]
            )
            try:
                recovery_plan = ExternalRecoveryPlan.from_identity_payload(
                    {} if plan_record is None else plan_record.payload
                )
            except ExternalDependencyContractError as exc:
                raise RecoveryRequired(
                    "external blocker recovery plan is unavailable"
                ) from exc
            if (
                plan_record is None
                or plan_record.record_id != recovery_plan.identity
                or plan_record.subject != f"Mission:{mission_id}"
                or recovery_plan.condition.dependency_id != dependency_id
                or len(completion_record_ids) != len(recovery_plan.paths)
            ):
                raise TransitionError(
                    "external blocker differs from its exact recovery plan"
                )
            attempts: list[IndexRecord] = []
            recovery_kinds: set[str] = set()
            recovery_paths: set[str] = set()
            required_changes: set[str] = set()
            resume_actions: set[str] = set()
            dependency_kinds: set[str] = set()
            blocked_capabilities: set[str] = set()
            reproduction_evidence: set[str] = set()
            completed_jobs: list[str] = []
            recovery_stream = f"external-recovery:{recovery_plan.identity}"
            for ordinal, completion_id in enumerate(completion_record_ids, start=1):
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
                decision = index.event_record(recovery_stream, ordinal)
                try:
                    attempt_plan = (
                        None
                        if not isinstance(binding, dict)
                        else external_plan_from_binding(binding)
                    )
                except ExternalDependencyContractError as exc:
                    raise TransitionError(str(exc)) from exc
                if (
                    completion is None
                    or completion.status != "failed"
                    or not isinstance(failure, dict)
                    or failure.get("failure_kind") != "external_dependency"
                    or failure.get("external_dependency_id") != dependency_id
                    or not isinstance(external, dict)
                    or external.get("dependency_id") != dependency_id
                    or external.get("verdict") != "failed"
                    or external.get("indispensable_to_mission_terminal") is not True
                    or external.get("contract_valid_next_action_found") is not False
                    or external.get("safe_substitute_found") is not False
                    or external.get("observed_external_state")
                    != failure.get("observed_external_state")
                    or declaration is None
                    or declaration.payload.get("mission_id") != mission_id
                    or not isinstance(binding, dict)
                    or binding.get("dependency_id") != dependency_id
                    or attempt_plan != recovery_plan
                    or binding.get("recovery_path_id")
                    != recovery_plan.paths[ordinal - 1].recovery_path_id
                    or decision is None
                    or decision.kind != "external-dependency-judgement"
                    or decision.status != "failed"
                    or decision.payload.get("blocker_credit") is not True
                    or decision.payload.get("completion_record_id")
                    != completion_id
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
                "candidate_delta": 0,
                "claim_delta": "none",
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
                "holdout_delta": 0,
                "preserved_state": {
                    "control_revision": current["revision"],
                    "journal_event_id": current["heads"]["journal"]["event_id"],
                    "mission_id": mission_id,
                },
                "required_external_change": next(iter(required_changes)),
                "safe_substitute_absent": True,
                "scientific_credit": 0,
                "contract_valid_next_action_absent": True,
                "indispensable_to_mission_terminal": True,
                "mission_resume_next_action": (
                    recovery_plan.condition.resume_action.to_next_action()
                ),
                "recovery_plan": recovery_plan.to_identity_payload(),
                "recovery_plan_id": recovery_plan.identity,
                "resume_condition": (
                    recovery_plan.condition.to_identity_payload()
                ),
                "resume_condition_id": recovery_plan.condition.identity,
                "terminal_scientific_credit": 0,
                "trial_delta": 0,
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
            effective_axis_blockers = self._mission_effective_axis_blockers(
                index,
                mission_id=mission_id,
            )
            if effective_axis_blockers:
                raise TransitionError(
                    "Mission terminal cannot bypass replay- or scope-blocked axis authority"
                )
            portfolio_snapshots = [
                record
                for record in index.records_by_payload_text(
                    "portfolio-snapshot",
                    "mission_id",
                    mission_id,
                )
                if record.subject == f"Mission:{mission_id}"
                and record.authority_sequence is not None
            ]
            if not portfolio_snapshots and outcome != "blocked_external":
                raise TransitionError(
                    "Mission terminal requires a durable Portfolio snapshot"
                )
            terminal_snapshot = (
                None
                if not portfolio_snapshots
                else max(
                    portfolio_snapshots,
                    key=lambda record: record.authority_sequence,
                )
            )
            terminal_axes = (
                {}
                if terminal_snapshot is None
                else {
                    axis["axis_id"]: axis
                    for axis in terminal_snapshot.payload.get("axes", [])
                    if isinstance(axis, dict)
                    and isinstance(axis.get("axis_id"), str)
                }
            )
            if terminal_snapshot is not None and len(terminal_axes) != len(
                terminal_snapshot.payload.get("axes", [])
            ):
                raise RecoveryRequired(
                    "Mission terminal Portfolio axis inventory is malformed"
                )
            terminal_axis_values = tuple(terminal_axes.values())
            terminal_resolutions = {
                axis["axis_id"]: resolution
                for axis, resolution in zip(
                    terminal_axis_values,
                    self._effective_axis_resolutions(
                        index,
                        terminal_axis_values,
                    ),
                    strict=True,
                )
            }
            terminal_hard_blockers = sorted(
                axis_id
                for axis_id, resolution in terminal_resolutions.items()
                if not resolution.terminal_eligible
            )
            if terminal_hard_blockers:
                exact_source_replacement_wait = False
                if outcome == "blocked_external":
                    blocker_basis = index.get("external-blocker", basis_record_id)
                    try:
                        blocker_plan_probe = (
                            ExternalRecoveryPlan.from_identity_payload(
                                {}
                                if blocker_basis is None
                                else blocker_basis.payload.get(
                                    "recovery_plan", {}
                                )
                            )
                        )
                    except ExternalDependencyContractError:
                        blocker_plan_probe = None
                    if blocker_plan_probe is not None:
                        expected_capability = (
                            _exact_source_replacement_wait_capability(
                                mission_id=mission_id,
                                terminal_axes=terminal_axes,
                                terminal_resolutions=terminal_resolutions,
                                terminal_hard_blockers=terminal_hard_blockers,
                            )
                        )
                        exact_source_replacement_wait = (
                            expected_capability is not None
                            and blocker_plan_probe.condition.blocked_mission_capability
                            == expected_capability
                        )
                if not exact_source_replacement_wait:
                    raise TransitionError(
                        "Mission terminal cannot bypass unresolved Portfolio axis "
                        "authority; blocked_external requires the exact source-"
                        "replacement capability"
                    )
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
                if terminal_snapshot is None:
                    raise RecoveryRequired(
                        "negative terminal lost its Portfolio snapshot"
                    )
                if (
                    science["active_executable"] is not None
                    or science.get("active_release") is not None
                    or science.get("active_holdout_evaluation") is not None
                    or basis is None
                    or basis.status != "accepted"
                    or basis.subject != f"Mission:{mission_id}"
                ):
                    raise TransitionError("negative terminal requires an exhaustion audit")
                if (
                    basis.payload.get("portfolio_snapshot_id")
                    != terminal_snapshot.record_id
                ):
                    raise TransitionError(
                        "negative terminal authority changed after its exhaustion audit"
                    )
            else:
                basis = index.get("external-blocker", basis_record_id)
                try:
                    blocker_plan = ExternalRecoveryPlan.from_identity_payload(
                        {} if basis is None else basis.payload.get("recovery_plan", {})
                    )
                except ExternalDependencyContractError as exc:
                    raise TransitionError(
                        "blocked terminal lacks its typed resume condition"
                    ) from exc
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
                    or basis.payload.get("recovery_plan_id")
                    != blocker_plan.identity
                    or basis.payload.get("resume_condition_id")
                    != blocker_plan.condition.identity
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
                    "mission_resume_next_action": basis.payload[
                        "mission_resume_next_action"
                    ],
                    "predecessor_mission_close_record_id": record_id,
                    "predecessor_mission_id": mission_id,
                    "required_external_change": basis.payload.get(
                        "required_external_change",
                        basis.payload.get("cause", {}).get(
                            "required_external_change"
                        ),
                    ),
                    "resume_condition_id": basis.payload["resume_condition_id"],
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
                    **(
                        {
                            "terminal_scientific_credit": 0,
                            "unresolved_axis_ids": terminal_hard_blockers,
                        }
                        if outcome == "blocked_external"
                        else {}
                    ),
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

    def _external_reentry_validation_dispatch_locked(
        self,
        *,
        current: Mapping[str, Any],
        index: LocalIndex | LocalIndexView,
        basis_record_id: str,
        mission_close_record_id: str,
        evidence: ExternalChangeEvidence,
    ) -> dict[str, Any]:
        """Freeze exact blocked-Mission evidence without executing a validator."""

        body = self._body(current)
        science = body["scientific"]
        boundary = body.get("next_action")
        if (
            science.get("active_mission") is not None
            or any(
                science.get(name) is not None
                for name in (
                    "active_batch",
                    "active_executable",
                    "active_holdout_evaluation",
                    "active_initiative",
                    "active_job",
                    "active_lineage",
                    "active_release",
                    "active_repair",
                    "active_study",
                )
            )
            or body.get("authorizations") != {}
            or not isinstance(boundary, Mapping)
            or boundary.get("kind") != "await_external_change"
            or boundary.get("basis_record_id") != basis_record_id
            or boundary.get("predecessor_mission_close_record_id")
            != mission_close_record_id
        ):
            raise TransitionError(
                "blocked Mission reentry is not at its exact wait boundary"
            )
        mission_id = boundary.get("predecessor_mission_id")
        blocker = index.get("external-blocker", basis_record_id)
        close_record = index.get("mission-close", mission_close_record_id)
        mission_open = (
            None
            if type(mission_id) is not str
            else index.get("mission-open", mission_id)
        )
        try:
            plan = ExternalRecoveryPlan.from_identity_payload(
                {}
                if blocker is None
                else blocker.payload.get("recovery_plan", {})
            )
        except ExternalDependencyContractError as exc:
            raise RecoveryRequired(
                "blocked Mission reentry lost its typed recovery plan"
            ) from exc
        condition = plan.condition
        if (
            blocker is None
            or blocker.status != "complete"
            or blocker.subject != f"Mission:{mission_id}"
            or blocker.payload.get("resume_condition_id")
            != condition.identity
            or blocker.payload.get("mission_resume_next_action")
            != condition.resume_action.to_next_action()
            or close_record is None
            or close_record.status != "blocked_external"
            or close_record.subject != f"Mission:{mission_id}"
            or close_record.payload.get("basis_record_id") != basis_record_id
            or mission_open is None
            or evidence.condition_id != condition.identity
            or boundary.get("resume_condition_id") != condition.identity
            or boundary.get("mission_resume_next_action")
            != condition.resume_action.to_next_action()
        ):
            raise TransitionError(
                "blocked Mission reentry differs from its exact terminal"
            )
        try:
            self.evidence.verify(condition.validation_plan_hash)
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
            raise RecoveryRequired(
                "blocked Mission validation plan is absent or corrupt"
            ) from exc
        dependency_head = index.event_head(
            f"external-dependency:{condition.dependency_id}"
        )
        dependency_latest = (
            None
            if dependency_head is None
            else index.get(
                dependency_head.record_kind,
                dependency_head.record_id,
            )
        )
        if (
            dependency_head is None
            or dependency_latest is None
            or dependency_latest.status != "external_unavailable"
        ):
            raise TransitionError(
                "blocked Mission dependency state is no longer the exact outage"
            )
        project_head = index.event_head("project-goal:OPERATING_DIRECTION.md")
        if (
            project_head is None
            or project_head.record_id != mission_close_record_id
        ):
            raise TransitionError(
                "blocked Mission close is not the current Project Goal boundary"
            )
        output_manifest = dict(evidence.output_manifest)
        result_hash = output_manifest[evidence.result_manifest_output]
        try:
            result_manifest = parse_canonical(
                self.evidence.read_verified(result_hash)
            )
        except ValueError as exc:
            raise TransitionError(
                "external change result manifest is not canonical"
            ) from exc
        required_result = {
            "blocker_basis_record_id",
            "condition_id",
            "measurement_artifact_hashes",
            "mission_close_record_id",
            "mission_id",
            "schema",
        }
        measurement_hashes = sorted(
            artifact_hash
            for output_name, artifact_hash in evidence.output_manifest
            if output_name != evidence.result_manifest_output
        )
        if (
            not isinstance(result_manifest, dict)
            or set(result_manifest) != required_result
            or result_manifest.get("schema") != "external_change_evidence.v1"
            or result_manifest.get("blocker_basis_record_id")
            != basis_record_id
            or result_manifest.get("condition_id") != condition.identity
            or result_manifest.get("mission_close_record_id")
            != mission_close_record_id
            or result_manifest.get("mission_id") != mission_id
            or result_manifest.get("measurement_artifact_hashes")
            != measurement_hashes
        ):
            raise TransitionError(
                "external change result differs from the blocked Mission"
            )
        validation_binding = {
            "blocked_mission_capability": condition.blocked_mission_capability,
            "dependency_id": condition.dependency_id,
            "result_manifest_output": evidence.result_manifest_output,
            "resume_condition_id": condition.identity,
        }
        expected_facts = {
            "blocked_mission_capability": condition.blocked_mission_capability,
            "dependency_id": condition.dependency_id,
            "external_change_satisfied": True,
            "resume_condition_id": condition.identity,
        }
        return {
            "artifact_rows": tuple(evidence.output_manifest),
            "condition": condition,
            "dependency_head": dependency_head,
            "expected_facts": expected_facts,
            "measurement_hashes": measurement_hashes,
            "mission_id": str(mission_id),
            "mission_open": mission_open,
            "project_head": project_head,
            "result_manifest": result_manifest,
            "result_hash": result_hash,
            "validation_binding": validation_binding,
        }

    def resume_blocked_mission(
        self,
        *,
        basis_record_id: str,
        mission_close_record_id: str,
        evidence: ExternalChangeEvidence,
        operation_id: str,
    ) -> TransitionResult:
        """Reenter the same blocked Mission from exact validated availability."""

        self._require_study_close_delivery_guard()
        if self.engineering_fixture:
            raise TransitionError(
                "engineering fixtures cannot reenter blocked Missions"
            )
        _require_digest("external blocker basis", basis_record_id)
        _require_digest("blocked Mission close", mission_close_record_id)
        if not isinstance(evidence, ExternalChangeEvidence):
            raise TransitionError(
                "blocked Mission reentry requires typed external change evidence"
            )

        request_hash = canonical_digest(
            domain="external-reentry-validation-request",
            payload={
                "basis_record_id": basis_record_id,
                "evidence_id": evidence.identity,
                "mission_close_record_id": mission_close_record_id,
            },
        )
        validation_capability: (
            _ExternalReentryValidationCapability | None
        ) = None
        with self.open_stable_index() as (frozen_control, frozen_index):
            frozen_boundary = frozen_control.get("next_action")
            exact_wait_boundary = (
                isinstance(frozen_boundary, Mapping)
                and frozen_boundary.get("kind") == "await_external_change"
                and frozen_boundary.get("basis_record_id")
                == basis_record_id
                and frozen_boundary.get(
                    "predecessor_mission_close_record_id"
                )
                == mission_close_record_id
            )
            frozen_dispatch = (
                self._external_reentry_validation_dispatch_locked(
                    current=frozen_control,
                    index=frozen_index,
                    basis_record_id=basis_record_id,
                    mission_close_record_id=mission_close_record_id,
                    evidence=evidence,
                )
                if exact_wait_boundary
                else None
            )
            frozen_control_hash = str(frozen_control["control_hash"])
        if frozen_dispatch is not None:
            artifacts = tuple(
                ValidationArtifact(
                    output_name=output_name,
                    sha256=artifact_hash,
                    _source=self.evidence.verified_path(artifact_hash),
                )
                for output_name, artifact_hash in frozen_dispatch[
                    "artifact_rows"
                ]
            )
            condition = frozen_dispatch["condition"]
            request = ExternalChangeValidationRequest(
                validator_id=condition.validator_id,
                validation_plan_hash=condition.validation_plan_hash,
                boundary_id=mission_close_record_id,
                condition_id=condition.identity,
                mission_id=frozen_dispatch["mission_id"],
                evidence_subject={
                    "kind": "Mission",
                    "id": frozen_dispatch["mission_id"],
                },
                binding=frozen_dispatch["validation_binding"],
                result_manifest=frozen_dispatch["result_manifest"],
                artifacts=artifacts,
                engineering_fixture=False,
            )
            try:
                validated, trace = self.validation_registry.validate(request)
            except EvidenceValidationError as exc:
                raise TransitionError(
                    f"registered external reentry validation failed: {exc}"
                ) from exc
            expected_facts = frozen_dispatch["expected_facts"]
            measurement_hashes = frozen_dispatch["measurement_hashes"]
            if (
                validated.verdict != "passed"
                or dict(validated.facts) != expected_facts
                or sorted(validated.measurement_artifact_hashes)
                != measurement_hashes
                or validated.claims
                or validated.artifact_roles
                or validated.scientific_eligible
                or validated.candidate_eligible
                or validated.release_eligible
            ):
                raise TransitionError(
                    "external change validator did not satisfy the exact condition"
                )
            validation_payload = {
                "blocker_basis_record_id": basis_record_id,
                "condition_id": condition.identity,
                "facts": expected_facts,
                "measurement_artifact_hashes": measurement_hashes,
                "mission_close_record_id": mission_close_record_id,
                "mission_id": frozen_dispatch["mission_id"],
                "result_manifest_hash": frozen_dispatch["result_hash"],
                "validation_plan_hash": condition.validation_plan_hash,
                "validation_trace": {
                    "declared_artifact_count": trace.declared_artifact_count,
                    "opened_artifact_count": trace.opened_artifact_count,
                    "validator_id": trace.validator_id,
                },
                "validator_id": condition.validator_id,
            }
            validation_payload_hash = canonical_digest(
                domain="external-reentry-validation-capability",
                payload=validation_payload,
            )
            validation_capability = _ExternalReentryValidationCapability(
                token=_EXTERNAL_REENTRY_VALIDATION_CAPABILITY_TOKEN,
                control_hash=frozen_control_hash,
                request_hash=request_hash,
                validation_payload=_copy(validation_payload),
                validation_payload_hash=validation_payload_hash,
            )

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            body = self._body(current)
            science = body["scientific"]
            boundary = body.get("next_action")
            if (
                science.get("active_mission") is not None
                or any(
                    science.get(name) is not None
                    for name in (
                        "active_batch",
                        "active_executable",
                        "active_holdout_evaluation",
                        "active_initiative",
                        "active_job",
                        "active_lineage",
                        "active_release",
                        "active_repair",
                        "active_study",
                    )
                )
                or body.get("authorizations") != {}
                or not isinstance(boundary, dict)
                or boundary.get("kind") != "await_external_change"
                or boundary.get("basis_record_id") != basis_record_id
                or boundary.get("predecessor_mission_close_record_id")
                != mission_close_record_id
            ):
                raise TransitionError(
                    "blocked Mission reentry is not at its exact wait boundary"
                )
            mission_id = boundary.get("predecessor_mission_id")
            blocker = index.get("external-blocker", basis_record_id)
            close_record = index.get("mission-close", mission_close_record_id)
            mission_open = (
                None
                if not isinstance(mission_id, str)
                else index.get("mission-open", mission_id)
            )
            try:
                plan = ExternalRecoveryPlan.from_identity_payload(
                    {} if blocker is None else blocker.payload.get("recovery_plan", {})
                )
            except ExternalDependencyContractError as exc:
                raise RecoveryRequired(
                    "blocked Mission reentry lost its typed recovery plan"
                ) from exc
            condition = plan.condition
            if (
                blocker is None
                or blocker.status != "complete"
                or blocker.subject != f"Mission:{mission_id}"
                or blocker.payload.get("resume_condition_id")
                != condition.identity
                or blocker.payload.get("mission_resume_next_action")
                != condition.resume_action.to_next_action()
                or close_record is None
                or close_record.status != "blocked_external"
                or close_record.subject != f"Mission:{mission_id}"
                or close_record.payload.get("basis_record_id") != basis_record_id
                or mission_open is None
                or evidence.condition_id != condition.identity
                or boundary.get("resume_condition_id") != condition.identity
                or boundary.get("mission_resume_next_action")
                != condition.resume_action.to_next_action()
            ):
                raise TransitionError(
                    "blocked Mission reentry differs from its exact terminal"
                )
            try:
                self.evidence.verify(condition.validation_plan_hash)
            except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                raise RecoveryRequired(
                    "blocked Mission validation plan is absent or corrupt"
                ) from exc
            dependency_head = index.event_head(
                f"external-dependency:{condition.dependency_id}"
            )
            dependency_latest = (
                None
                if dependency_head is None
                else index.get(
                    dependency_head.record_kind, dependency_head.record_id
                )
            )
            if (
                dependency_head is None
                or dependency_latest is None
                or dependency_latest.status != "external_unavailable"
            ):
                raise TransitionError(
                    "blocked Mission dependency state is no longer the exact outage"
                )
            project_head = index.event_head("project-goal:OPERATING_DIRECTION.md")
            if project_head is None or project_head.record_id != mission_close_record_id:
                raise TransitionError(
                    "blocked Mission close is not the current Project Goal boundary"
                )
            output_manifest = dict(evidence.output_manifest)
            result_hash = output_manifest[evidence.result_manifest_output]
            try:
                result_manifest = parse_canonical(
                    self.evidence.read_verified(result_hash)
                )
            except ValueError as exc:
                raise TransitionError(
                    "external change result manifest is not canonical"
                ) from exc
            required_result = {
                "blocker_basis_record_id",
                "condition_id",
                "measurement_artifact_hashes",
                "mission_close_record_id",
                "mission_id",
                "schema",
            }
            measurement_hashes = sorted(
                artifact_hash
                for output_name, artifact_hash in evidence.output_manifest
                if output_name != evidence.result_manifest_output
            )
            if (
                not isinstance(result_manifest, dict)
                or set(result_manifest) != required_result
                or result_manifest.get("schema")
                != "external_change_evidence.v1"
                or result_manifest.get("blocker_basis_record_id")
                != basis_record_id
                or result_manifest.get("condition_id") != condition.identity
                or result_manifest.get("mission_close_record_id")
                != mission_close_record_id
                or result_manifest.get("mission_id") != mission_id
                or result_manifest.get("measurement_artifact_hashes")
                != measurement_hashes
            ):
                raise TransitionError(
                    "external change result differs from the blocked Mission"
                )
            expected_facts = {
                "blocked_mission_capability": (
                    condition.blocked_mission_capability
                ),
                "dependency_id": condition.dependency_id,
                "external_change_satisfied": True,
                "resume_condition_id": condition.identity,
            }
            if (
                validation_capability is None
                or validation_capability.token
                is not _EXTERNAL_REENTRY_VALIDATION_CAPABILITY_TOKEN
                or validation_capability.control_hash
                != current.get("control_hash")
                or validation_capability.request_hash != request_hash
                or canonical_digest(
                    domain="external-reentry-validation-capability",
                    payload=dict(validation_capability.validation_payload),
                )
                != validation_capability.validation_payload_hash
            ):
                raise TransitionError(
                    "external reentry validation capability is absent or stale"
                )
            validation_payload = _copy(
                validation_capability.validation_payload
            )
            if any(
                validation_payload.get(name) != expected
                for name, expected in {
                    "blocker_basis_record_id": basis_record_id,
                    "condition_id": condition.identity,
                    "facts": expected_facts,
                    "measurement_artifact_hashes": measurement_hashes,
                    "mission_close_record_id": mission_close_record_id,
                    "mission_id": mission_id,
                    "result_manifest_hash": result_hash,
                    "validation_plan_hash": condition.validation_plan_hash,
                    "validator_id": condition.validator_id,
                }.items()
            ):
                raise TransitionError(
                    "external reentry validation capability differs from authority"
                )
            validation_id = canonical_digest(
                domain="external-change-validation",
                payload=validation_payload,
            )
            availability = _record(
                kind="external-change-validation",
                record_id=validation_id,
                subject=f"Mission:{mission_id}",
                status="available",
                fingerprint=condition.dependency_id,
                payload=validation_payload,
                event_stream=f"external-dependency:{condition.dependency_id}",
                event_sequence=dependency_head.sequence + 1,
            )
            authorization_head = index.event_head(
                f"mission-authorization:{mission_id}"
            )
            previous_authorization = (
                None
                if authorization_head is None
                else index.get(
                    authorization_head.record_kind,
                    authorization_head.record_id,
                )
            )
            if authorization_head is not None and (
                previous_authorization is None
                or previous_authorization.kind != "mission-authorization"
                or previous_authorization.subject != f"Mission:{mission_id}"
                or previous_authorization.payload.get("authorization_epoch")
                != authorization_head.sequence + 1
            ):
                raise RecoveryRequired(
                    "blocked Mission authorization history is malformed"
                )
            authorization_sequence = (
                1 if authorization_head is None else authorization_head.sequence + 1
            )
            authorization_epoch = authorization_sequence + 1
            activation_hash = canonical_digest(
                domain="mission-reentry-activation",
                payload={
                    "authorization_epoch": authorization_epoch,
                    "basis_record_id": basis_record_id,
                    "external_change_validation_id": validation_id,
                    "goal_hash": mission_open.payload.get("goal_hash"),
                    "mission_close_record_id": mission_close_record_id,
                    "mission_id": mission_id,
                },
            )
            authorization = self._authorization(
                kind=SubjectKind.MISSION,
                subject_id=mission_id,
                semantic_hash=activation_hash,
                epoch=authorization_epoch,
            )
            reentry_payload = {
                "authorization_epoch": authorization_epoch,
                "authorization_hash": authorization.authorization_hash,
                "basis_record_id": basis_record_id,
                "external_change_validation_id": validation_id,
                "mission_close_record_id": mission_close_record_id,
                "mission_id": mission_id,
                "mission_ordinal": mission_open.payload.get("mission_ordinal"),
                "project_goal_complete": False,
                "resume_next_action": condition.resume_action.to_next_action(),
                "trial_delta": 0,
                "claim_delta": 0,
                "holdout_delta": 0,
            }
            reentry_id = canonical_digest(
                domain="mission-reentry", payload=reentry_payload
            )
            reentry = _record(
                kind="mission-reentry",
                record_id=reentry_id,
                subject=f"Mission:{mission_id}",
                status="active",
                fingerprint=activation_hash,
                payload=reentry_payload,
                event_stream="project-goal:OPERATING_DIRECTION.md",
                event_sequence=project_head.sequence + 1,
            )
            authorization_record = _record(
                kind="mission-authorization",
                record_id=activation_hash,
                subject=f"Mission:{mission_id}",
                status="active",
                fingerprint=authorization.authorization_hash,
                payload={
                    **authorization.payload(),
                    "basis_record_id": basis_record_id,
                    "external_change_validation_id": validation_id,
                    "mission_close_record_id": mission_close_record_id,
                },
                event_stream=f"mission-authorization:{mission_id}",
                event_sequence=authorization_sequence,
            )
            science["active_mission"] = mission_id
            body["next_action"] = condition.resume_action.to_next_action()
            self._bind_authorization(body, authorization)
            return body, [availability, authorization_record, reentry], {
                "authorization_epoch": authorization_epoch,
                "external_change_validation_id": validation_id,
                "mission_id": mission_id,
                "mission_reentry_id": reentry_id,
                "project_goal_complete": False,
            }

        return self._commit(
            event_kind="blocked_mission_reentered",
            operation_id=operation_id,
            subject="ProjectGoal:OPERATING_DIRECTION.md",
            payload={
                "basis_record_id": basis_record_id,
                "evidence_id": evidence.identity,
                "mission_close_record_id": mission_close_record_id,
            },
            prepare=prepare,
            evidence_blobs=(),
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
