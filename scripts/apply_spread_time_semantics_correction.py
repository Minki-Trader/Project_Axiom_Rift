"""Plan or explicitly apply the seven-event spread/time audit correction.

The default mode is read-only.  ``--apply`` requires an unpublished local-main
code checkpoint, an exact origin/main baseline, an empty Git index, no foreign
worktree changes, and enough active-segment headroom for every remaining event
in the content-addressed plan.  This script never commits or pushes.

The immutable core SHA-256 is embedded in all seven operation ids.  A normal
append observes the real Writer clock once just in time, prepares an exact
shadow event with that UTC, and supplies a one-shot full-event expectation to
the Journal before any write.  Recovery treats a recorded timestamp only as a
byte-replay input, never as external wall-clock authority.  Journal sequence
and head identity provide ordering.  All seven events grant zero scientific,
economic, candidate, and terminal credit.  Exact post-append receipts are
sealed only in the separate final receipt envelope.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
from hashlib import sha256
import json
import importlib.metadata
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any, Callable, Iterator, Mapping, Sequence, TypeVar


ROOT = Path(__file__).resolve().parents[1]
_SAFE_STARTUP = bool(
    sys.flags.isolated
    and sys.flags.no_site
    and sys.flags.no_user_site
    and sys.flags.ignore_environment
    and sys.flags.safe_path
)
if "--apply" in sys.argv and not _SAFE_STARTUP:
    raise SystemExit(
        "apply requires `python -I -S scripts/"
        "apply_spread_time_semantics_correction.py --apply`"
    )
_SAFE_BYTECODE_CACHE: TemporaryDirectory[str] | None = None


def _require_safe_repository_import_surface(
    import_roots: Sequence[Path],
) -> None:
    """Reject ignored sourceless/native code before admitting repo imports."""

    forbidden: list[str] = []
    try:
        for import_root in import_roots:
            resolved_root = import_root.resolve(strict=True)
            for candidate in resolved_root.rglob("*"):
                suffix = candidate.suffix.casefold()
                sourceless_bytecode = (
                    suffix == ".pyc"
                    and candidate.parent.name.casefold() != "__pycache__"
                )
                native = suffix in {".dll", ".pyd", ".so"}
                if not (sourceless_bytecode or native):
                    continue
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(resolved_root)
                if candidate.is_symlink() or not resolved.is_file():
                    raise OSError("link-like repository executable")
                forbidden.append(resolved.as_posix())
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(
            "safe repository import surface cannot be inspected"
        ) from exc
    if forbidden:
        raise SystemExit(
            "safe repository import surface contains sourceless or native code: "
            + ", ".join(sorted(forbidden))
        )


if _SAFE_STARTUP:
    # ``-I -S`` suppresses every startup hook and .pth file.  Add only the
    # interpreter's resolved package directories so vetted dependencies remain
    # importable without executing the site module.
    roaming_buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(
        None,
        0x001A,  # CSIDL_APPDATA
        None,
        0,
        roaming_buffer,
    ):
        raise SystemExit("canonical Windows RoamingAppData is unavailable")
    package_roots = [
        (Path(sys.base_prefix) / "Lib" / "site-packages").resolve(),
        (
            Path(roaming_buffer.value)
            / "Python"
            / f"Python{sys.version_info.major}{sys.version_info.minor}"
            / "site-packages"
        ).resolve(),
    ]
    for package_root in package_roots:
        if package_root.is_dir() and str(package_root) not in sys.path:
            sys.path.append(str(package_root))
    # Redirect cache lookup before admitting the repository.  Existing ignored
    # ``__pycache__`` files are neither read nor deleted, and no repository
    # bytecode is created by this process.
    _SAFE_BYTECODE_CACHE = TemporaryDirectory(
        prefix="axiom-correction-bytecode-"
    )
    sys.pycache_prefix = str(
        Path(_SAFE_BYTECODE_CACHE.name).resolve(strict=True)
    )
    sys.dont_write_bytecode = True
    import yaml

    _require_safe_repository_import_surface((ROOT / "src",))
    sys.path.insert(0, str(ROOT / "src"))
else:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "src"))
    import yaml

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.content_addressed_correction import (
    AuthorityFileBinding,
    ContentAddressedCorrectionError,
    CorrectionReceiptEnvelope,
    CorrectionBaseline,
    CorrectionEventIntent,
    CorrectionEventReceiptBinding,
    CorrectionEvidenceBinding,
    CorrectionPlanCore,
    capture_local_correction_checkpoint,
    correction_suffix_from_journal,
    require_exact_correction_receipts,
    require_local_main_correction_boundary,
)
from axiom_rift.operations.completion_validity_projection import (
    completion_validity_invalidation_record,
)
from axiom_rift.operations.historical_cost_semantics_projection import (
    COMPLETION_SCOPE_RECORD_KIND,
    LATCH_RECORD_KIND,
    build_historical_spread_semantics_audit_manifest,
    historical_cost_semantics_activation_records,
    validate_historical_cost_semantics_latch_binding,
)
from axiom_rift.operations.replay_projection import (
    build_satisfaction_invalidation_plan,
    constraints_for_pending,
    effective_replay_priority,
    initial_obligation_record,
    obligation_heads,
    prepare_satisfaction_invalidation,
    replay_priority_escalation_record,
    satisfaction_invalidation_record,
    with_scheduler_constraints,
)
from axiom_rift.operations.validation import EvidenceValidatorRegistry
from axiom_rift.operations.validation_integrity import (
    validator_execution_dependency_paths,
)
from axiom_rift.operations.writer import RecoveryRequired, StateWriter
from axiom_rift.research.historical_cost_semantics import (
    HistoricalCostSemanticsLatch,
    HistoricalSpreadSemanticsAuditManifest,
)
from axiom_rift.research.historical_adjudication import (
    derive_historical_adjudication,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyAuthority,
    historical_family_from_manifest,
)
from axiom_rift.research.historical_family_stu0048 import (
    STU0048_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_stu0051 import (
    STU0051_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_spread_time_adjudication_builder import (
    EXPECTED_LEGACY_COMPLETION_COUNT,
    P0_REPLAY_FAMILY_ID,
    HistoricalSpreadTimeAdjudicationPlan,
    build_historical_spread_time_adjudication_plan,
)
from axiom_rift.research.historical_spread_time_invalidation_builder import (
    EXPECTED_COMPLETION_COUNT,
    HistoricalSpreadTimeInvalidationInventory,
    build_historical_spread_time_invalidation_inventory,
)
from axiom_rift.research.historical_study_registry import (
    HISTORICAL_FAMILY_IDENTITY_BY_MODULE,
    HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256,
)
from axiom_rift.research.protocol import (
    ResearchProtocol,
    ResearchProtocolActivation,
)
from axiom_rift.research.replay_obligation import (
    ReplayObligationStatus,
    ReplayPriority,
    ReplayPriorityEscalation,
    derive_historical_replay_obligation,
    historical_replay_obligation_from_identity_payload,
)
from axiom_rift.research.replay_satisfaction_invalidation import (
    replay_satisfaction_invalidation_manifest_from_mapping,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    ScientificAdjudicationValidatorV2,
)
from axiom_rift.storage.evidence import EvidenceArtifact, EvidenceStore
from axiom_rift.storage.journal import DurableJournal


AUDIT_REPORT_PATH = (
    "records/audits/"
    "2026-07-16_spread_time_semantics_and_historical_validity_audit.md"
)
OPERATION_NAMESPACE = "axiom-spread-time-correction"
AUTHORITY_REASON = (
    "bind completed-period spread timing repair historical correction and "
    "cost qualification"
)
PURPOSE = (
    "Activate the exhaustive spread/time repair, invalidate 34 historical "
    "scientific completions, supersede 26 legacy adjudications, revoke two "
    "invalid replay satisfactions, and latch the exact 501-completion "
    "completed-period cost interpretation without rewriting history."
)

_ZERO_AUTHORITY_DELTA = {
    "candidate": 0,
    "economic": 0,
    "holdout": 0,
    "scientific": 0,
    "terminal": 0,
    "trial": 0,
}

REPLAY_OBLIGATION_IDS = (
    "historical-replay-obligation:"
    "c537b4ebc7085331cd21e52c26fbc994728c0520d5474473cc246f4e8c85322e",
    "historical-replay-obligation:"
    "a8da0fda7ff53c1951c59bf2bdc4fb8db722cf21c2090dd2e5220c5d2069a904",
)
REPLAY_SATISFACTION_IDS = {
    REPLAY_OBLIGATION_IDS[0]: (
        "historical-replay-satisfaction:"
        "6a0d460befc957bad4cb250fdc1a0cb3a74fd7c00ed5643e93f7fc60a59790d4"
    ),
    REPLAY_OBLIGATION_IDS[1]: (
        "historical-replay-satisfaction:"
        "6b59a863de2e5f4833ae7dd6786423c7b1642b4c741db1bc10e8357648fdda2f"
    ),
}

_FAMILY_SPECS = {
    REPLAY_OBLIGATION_IDS[0]: (
        STU0048_HISTORICAL_FAMILY,
        "src/axiom_rift/research/historical_family_stu0048.py",
    ),
    REPLAY_OBLIGATION_IDS[1]: (
        STU0051_HISTORICAL_FAMILY,
        "src/axiom_rift/research/historical_family_stu0051.py",
    ),
}

_REQUIRED_WRITER_METHODS = (
    "activate_research_protocol",
    "invalidate_historical_replay_satisfaction",
    "migrate_authority",
    "record_historical_cost_semantics_latch",
    "record_historical_scientific_adjudications",
    "record_historical_scientific_validity_invalidations",
)


class SpreadTimeCorrectionError(RuntimeError):
    """The seven-event correction cannot be planned or applied exactly."""


def _require_safe_apply_startup() -> None:
    if not _SAFE_STARTUP:
        raise SpreadTimeCorrectionError(
            "apply requires `python -I -S scripts/"
            "apply_spread_time_semantics_correction.py --apply`"
        )


_T = TypeVar("_T")


class _SingleUseClock:
    """Observe one real or replay clock read and reject every extra read."""

    def __init__(self, source: Callable[[], str]) -> None:
        self._source = source
        self._calls = 0
        self.observed: str | None = None

    def __call__(self) -> str:
        if self._calls:
            raise SpreadTimeCorrectionError(
                "correction event clock was read more than once"
            )
        self._calls = 1
        observed = self._source()
        if type(observed) is not str or not observed:
            raise SpreadTimeCorrectionError("correction event clock is malformed")
        self.observed = observed
        return observed

    def require_consumed(self) -> None:
        if self._calls != 1:
            raise SpreadTimeCorrectionError(
                "correction event clock was not consumed exactly once"
            )


def _invoke_with_single_clock(
    writer: StateWriter,
    source: Callable[[], str],
    function: Callable[[], _T],
) -> tuple[_T, str]:
    """Run one transition and prove that it observed exactly one clock value."""

    clock = _SingleUseClock(source)
    prior_clock = writer.clock
    writer.clock = clock
    try:
        result = function()
    finally:
        writer.clock = prior_clock
    clock.require_consumed()
    if clock.observed is None:  # pragma: no cover - guarded above.
        raise SpreadTimeCorrectionError("correction event clock was not observed")
    return result, clock.observed


def _observe_writer_clock_once(writer: StateWriter) -> str:
    """Observe the canonical real clock once before exact shadow preparation."""

    clock = _SingleUseClock(writer.clock)
    observed = clock()
    clock.require_consumed()
    return observed


def _invoke_replay_transition(
    writer: StateWriter,
    occurred_at_utc: str,
    function: Callable[[], _T],
) -> _T:
    result, observed = _invoke_with_single_clock(
        writer,
        lambda: occurred_at_utc,
        function,
    )
    if observed != occurred_at_utc:
        raise SpreadTimeCorrectionError("replay event clock changed")
    return result


def _synthetic_preview_timestamps(count: int) -> tuple[str, ...]:
    """Return deterministic non-authority clocks used only for dry-run sizing."""

    if type(count) is not int or count < 1 or count > 99:
        raise SpreadTimeCorrectionError("synthetic preview count is invalid")
    return tuple(
        f"2000-01-01T00:00:00.{ordinal:06d}Z"
        for ordinal in range(1, count + 1)
    )


class _ReadOnlyEvidenceOverlay(EvidenceStore):
    """Read-only in-memory evidence additions over the durable local store."""

    def __init__(
        self,
        base: EvidenceStore,
        documents: Mapping[str, bytes],
    ) -> None:
        super().__init__(ROOT / "local" / "unmaterialized-read-only-overlay")
        self._base = base
        self._documents = dict(documents)
        if any(sha256(value).hexdigest() != key for key, value in documents.items()):
            raise SpreadTimeCorrectionError(
                "read-only evidence overlay contains a hash mismatch"
            )

    def read_verified(self, identity: str) -> bytes:
        document = self._documents.get(identity)
        if document is not None:
            if sha256(document).hexdigest() != identity:
                raise RuntimeError("read-only evidence overlay drifted")
            return document
        return self._base.read_verified(identity)

    def verify(self, identity: str) -> None:
        self.read_verified(identity)


class _ShadowEvidenceStore:
    """Memory-only publications over durable evidence for receipt preview."""

    def __init__(
        self,
        base: EvidenceStore,
        documents: Mapping[str, bytes],
    ) -> None:
        self._base = base
        self._documents = dict(documents)
        if any(sha256(value).hexdigest() != key for key, value in documents.items()):
            raise SpreadTimeCorrectionError(
                "shadow evidence contains a hash mismatch"
            )

    @staticmethod
    def _artifact(identity: str, document: bytes) -> EvidenceArtifact:
        return EvidenceArtifact(
            sha256=identity,
            size_bytes=len(document),
            relative_path=f"sha256/{identity[:2]}/{identity}",
        )

    def finalize(self, content: bytes) -> EvidenceArtifact:
        if type(content) is not bytes:
            raise TypeError("evidence content must be bytes")
        identity = sha256(content).hexdigest()
        existing = self._documents.setdefault(identity, content)
        if existing != content:
            raise RuntimeError("shadow evidence identity collided")
        return self._artifact(identity, content)

    def read_verified(self, identity: str) -> bytes:
        document = self._documents.get(identity)
        if document is not None:
            if sha256(document).hexdigest() != identity:
                raise RuntimeError("shadow evidence drifted")
            return document
        return self._base.read_verified(identity)

    def verify(self, identity: str) -> None:
        self.read_verified(identity)

    def exact_documents(self) -> dict[str, bytes]:
        """Return a defensive copy of every replay-materialized document."""

        return dict(self._documents)


@dataclass(frozen=True, slots=True)
class SpreadTimeCorrectionMaterial:
    core: CorrectionPlanCore
    preview_receipts: tuple[CorrectionEventReceiptBinding, ...]
    preview_events: tuple[Mapping[str, Any], ...]
    preview_dynamic_expectations: tuple[
        _DynamicActionExpectation | None, ...
    ]
    report_bytes: bytes
    invalidation_inventory: HistoricalSpreadTimeInvalidationInventory
    adjudication_plan: HistoricalSpreadTimeAdjudicationPlan | None
    cost_manifest: HistoricalSpreadSemanticsAuditManifest
    family_authorities: Mapping[str, HistoricalFamilyAuthority]
    predecessor_documents: Mapping[str, bytes]
    prospective_documents: Mapping[str, bytes]
    direct_evidence_hashes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ExpectedReadjudicationInventory:
    semantic_records: tuple[tuple[str, str], ...]
    semantic_rows: tuple[Mapping[str, Any], ...]
    adjudication_ids: tuple[str, ...]
    new_obligation_ids: tuple[str, ...]
    priority_escalation_ids: tuple[str, ...]
    scheduler_constraints_by_event: tuple[
        Mapping[str, Any] | None,
        Mapping[str, Any] | None,
        Mapping[str, Any] | None,
    ]


def _record_mapping(record: Any) -> dict[str, Any]:
    """Project one typed pure IndexRecord exactly as StateWriter does."""

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


def _row_sha256(row: Mapping[str, Any]) -> str:
    return sha256(canonical_bytes(dict(row))).hexdigest()


def _expected_readjudication_inventory(
    index: Any,
    evidence: EvidenceStore,
    *,
    adjudications: HistoricalSpreadTimeAdjudicationPlan,
    audit_artifact_hash: str,
    governing_mission_id: str,
) -> _ExpectedReadjudicationInventory:
    """Independently derive every row identity in the 51-row event."""

    semantic_rows: list[Mapping[str, Any]] = []
    adjudication_ids: list[str] = []
    new_obligation_ids: list[str] = []
    new_obligations: list[Any] = []
    reused_obligations: dict[str, Any] = {}
    escalations: list[str] = []
    try:
        resolved_obligation_heads = obligation_heads(
            index,
            mission_id=governing_mission_id,
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        raise SpreadTimeCorrectionError(
            "baseline replay scheduler projection is malformed"
        ) from exc
    existing_pending = [
        obligation
        for obligation, head in resolved_obligation_heads
        if head.status == ReplayObligationStatus.PENDING.value
    ]
    try:
        existing_pending_priorities = {
            obligation.identity: effective_replay_priority(index, obligation)
            for obligation in existing_pending
        }
    except (RuntimeError, TypeError, ValueError) as exc:
        raise SpreadTimeCorrectionError(
            "baseline replay priority projection is malformed"
        ) from exc
    p0_completion_ids = {
        member.completion_record_id
        for member in adjudications.family(P0_REPLAY_FAMILY_ID).members
    }
    for member in adjudications.members:
        completion = index.get("job-completed", member.completion_record_id)
        prior = index.get(
            "historical-scientific-adjudication",
            member.prior_adjudication_record_id,
        )
        scientific = None if completion is None else completion.payload.get(
            "scientific"
        )
        prior_payload = None if prior is None else prior.payload
        if (
            completion is None
            or not isinstance(scientific, Mapping)
            or not isinstance(prior_payload, Mapping)
        ):
            raise SpreadTimeCorrectionError(
                "readjudication source binding is unavailable"
            )
        plan_hash = scientific.get("validation_plan_hash")
        measurements = scientific.get("measurement_artifact_hashes")
        if (
            type(plan_hash) is not str
            or not isinstance(measurements, list)
            or len(measurements) != 1
            or type(measurements[0]) is not str
        ):
            raise SpreadTimeCorrectionError(
                "priority escalation scientific evidence binding is malformed"
            )
        try:
            plan = parse_canonical(evidence.read_verified(plan_hash))
            measurement = parse_canonical(evidence.read_verified(measurements[0]))
            superseding = derive_historical_adjudication(
                audit_artifact_hash=audit_artifact_hash,
                study_id=member.study_id,
                study_close_record_id=prior_payload["study_close_record_id"],
                completion_record_id=member.completion_record_id,
                executable_id=member.executable_id,
                validation_plan_hash=plan_hash,
                measurement_artifact_hash=measurements[0],
                original_job_status=completion.status,
                original_scientific_verdict=scientific["verdict"],
                plan=plan,
                measurement=measurement,
                request=member.request,
                negative_memory_ids=member.negative_memory_ids,
            )
        except (KeyError, OSError, RuntimeError, ValueError) as exc:
            raise SpreadTimeCorrectionError(
                "readjudication identity derivation failed"
            ) from exc

        adjudication_ids.append(superseding.identity)
        adjudication_payload = {
            **superseding.to_identity_payload(),
            "supersedes_record_id": member.prior_adjudication_record_id,
            "trial_delta": 0,
            "holdout_delta": 0,
            "candidate_delta": 0,
            "claim_authority": "additive_qualification_only",
            "profile_authority": "writer_derived_fixed_legacy_v1",
            "validity_override_authority": (
                "writer_derived_durable_invalidity_heads"
            ),
        }
        new_obligation_record: Any | None = None
        escalation_record: Any | None = None
        if (
            superseding.disposition.value == "replay_required"
            and member.replay_obligation_id is None
        ):
            try:
                obligation = derive_historical_replay_obligation(
                    governing_mission_id=governing_mission_id,
                    historical_adjudication_id=superseding.identity,
                    adjudication_payload=superseding.to_identity_payload(),
                )
            except (TypeError, ValueError) as exc:
                raise SpreadTimeCorrectionError(
                    "new replay obligation identity derivation failed"
                ) from exc
            new_obligation_ids.append(obligation.identity)
            new_obligations.append(obligation)
            adjudication_payload.update(
                {
                    "replay_obligation_id": obligation.identity,
                    "replay_obligation_origin_adjudication_id": (
                        superseding.identity
                    ),
                    "replay_obligation_authority": "derived_new",
                }
            )
            new_obligation_record = initial_obligation_record(obligation)
        elif superseding.disposition.value == "replay_required":
            initial_obligation = (
                None
                if member.replay_obligation_id is None
                else index.get(
                    "historical-replay-obligation",
                    member.replay_obligation_id,
                )
            )
            try:
                existing_obligation = (
                    historical_replay_obligation_from_identity_payload(
                        None
                        if initial_obligation is None
                        else initial_obligation.payload.get("obligation")
                    )
                )
            except (TypeError, ValueError) as exc:
                raise SpreadTimeCorrectionError(
                    "reused replay obligation identity is malformed"
                ) from exc
            if (
                member.completion_record_id not in p0_completion_ids
                or member.replay_obligation_id is None
                or member.accepted_satisfaction_record_id is None
                or existing_obligation.identity != member.replay_obligation_id
            ):
                raise SpreadTimeCorrectionError(
                    "reused replay obligation lacks its exact P0 satisfaction"
                )
            prior_reused = reused_obligations.setdefault(
                existing_obligation.identity,
                existing_obligation,
            )
            if prior_reused != existing_obligation:
                raise SpreadTimeCorrectionError(
                    "reused replay obligation identity collided"
                )
            adjudication_payload.update(
                {
                    "replay_obligation_id": member.replay_obligation_id,
                    "replay_obligation_origin_adjudication_id": (
                        existing_obligation.historical_adjudication_id
                    ),
                    "replay_obligation_authority": "reused_existing_lineage",
                }
            )
            try:
                escalation = ReplayPriorityEscalation(
                    governing_mission_id=governing_mission_id,
                    obligation_id=member.replay_obligation_id,
                    superseding_historical_adjudication_id=superseding.identity,
                    completion_validity_invalidation_id=(
                        member.invalidation_record_id
                    ),
                    accepted_satisfaction_record_id=(
                        member.accepted_satisfaction_record_id
                    ),
                    audit_artifact_hash=audit_artifact_hash,
                    reason_codes=superseding.reason_codes,
                )
            except ValueError as exc:
                raise SpreadTimeCorrectionError(
                    "priority escalation identity derivation failed"
                ) from exc
            escalations.append(escalation.identity)
            escalation_record = replay_priority_escalation_record(escalation)

        semantic_rows.append(
            {
                "kind": "historical-scientific-adjudication",
                "record_id": superseding.identity,
                "subject": f"Study:{member.study_id}",
                "status": superseding.disposition.value,
                "fingerprint": superseding.identity.removeprefix(
                    "historical-adjudication:"
                ),
                "payload": adjudication_payload,
                "event_stream": (
                    f"historical-adjudication:{member.completion_record_id}"
                ),
                "event_sequence": member.prior_adjudication_sequence + 1,
            }
        )
        if new_obligation_record is not None:
            semantic_rows.append(_record_mapping(new_obligation_record))
        if escalation_record is not None:
            semantic_rows.append(_record_mapping(escalation_record))

    semantic_records = tuple(
        (row["kind"], row["record_id"]) for row in semantic_rows
    )
    if set(reused_obligations) != set(REPLAY_OBLIGATION_IDS):
        raise SpreadTimeCorrectionError(
            "readjudication does not bind both satisfaction revocations"
        )
    pending_obligations = [*existing_pending, *new_obligations]
    effective_priorities = {
        **existing_pending_priorities,
        **{
            obligation.identity: obligation.replay_priority
            for obligation in new_obligations
        },
    }
    scheduler_constraints: list[Mapping[str, Any] | None] = []
    try:
        scheduler_constraints.append(
            constraints_for_pending(
                pending_obligations,
                effective_priorities=effective_priorities,
            )
        )
        for obligation_id in REPLAY_OBLIGATION_IDS:
            obligation = reused_obligations[obligation_id]
            if obligation.identity in {
                item.identity for item in pending_obligations
            }:
                raise SpreadTimeCorrectionError(
                    "satisfied replay obligation was already pending"
                )
            pending_obligations.append(obligation)
            effective_priorities[obligation.identity] = ReplayPriority.P0
            scheduler_constraints.append(
                constraints_for_pending(
                    pending_obligations,
                    effective_priorities=effective_priorities,
                )
            )
    except (RuntimeError, TypeError, ValueError) as exc:
        raise SpreadTimeCorrectionError(
            "corrected replay scheduler projection is malformed"
        ) from exc
    if len(scheduler_constraints) != 3:
        raise SpreadTimeCorrectionError(
            "corrected replay scheduler projection changed shape"
        )
    result = _ExpectedReadjudicationInventory(
        semantic_records=semantic_records,
        semantic_rows=tuple(semantic_rows),
        adjudication_ids=tuple(adjudication_ids),
        new_obligation_ids=tuple(new_obligation_ids),
        priority_escalation_ids=tuple(sorted(escalations)),
        scheduler_constraints_by_event=(
            scheduler_constraints[0],
            scheduler_constraints[1],
            scheduler_constraints[2],
        ),
    )
    if (
        len(result.semantic_records) != 51
        or len(set(result.semantic_records)) != 51
        or len(result.adjudication_ids) != 26
        or len(set(result.adjudication_ids)) != 26
        or len(result.new_obligation_ids) != 23
        or len(set(result.new_obligation_ids)) != 23
        or len(result.priority_escalation_ids) != 2
        or len(set(result.priority_escalation_ids)) != 2
    ):
        raise SpreadTimeCorrectionError(
            "readjudication exact 26+23+2 semantic inventory changed shape"
        )
    return result


def _expected_control_projection_sha256(
    baseline_control: Mapping[str, Any],
    *,
    prospective_authority_manifest_digest: str,
    readjudication_inventory: _ExpectedReadjudicationInventory,
) -> tuple[str, ...]:
    """Derive all seven control bodies without executing StateWriter."""

    raw_body = {
        key: value
        for key, value in baseline_control.items()
        if key not in {"control_hash", "heads", "revision"}
    }
    body = parse_canonical(canonical_bytes(raw_body))
    authority = body.get("authority") if isinstance(body, Mapping) else None
    next_action = body.get("next_action") if isinstance(body, Mapping) else None
    if not isinstance(body, dict) or not isinstance(authority, dict) or not isinstance(
        next_action, Mapping
    ):
        raise SpreadTimeCorrectionError(
            "baseline control body cannot be independently projected"
        )
    authority["manifest_digest"] = prospective_authority_manifest_digest

    def snapshot() -> str:
        return sha256(canonical_bytes(body)).hexdigest()

    # Events 1-3 change authority once and otherwise leave the body unchanged.
    projections = [snapshot(), snapshot(), snapshot()]
    for constraints in readjudication_inventory.scheduler_constraints_by_event:
        body["next_action"] = with_scheduler_constraints(
            body["next_action"],
            constraints,
        )
        projections.append(snapshot())
    # Event 7 records an index-only latch and preserves event 6's control body.
    projections.append(snapshot())
    if len(projections) != 7 or any(
        type(item) is not str or len(item) != 64 for item in projections
    ):
        raise SpreadTimeCorrectionError(
            "seven-event control projection changed shape"
        )
    return tuple(projections)


def _git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ("git", *arguments),
            cwd=ROOT,
            check=check,
            capture_output=True,
            timeout=2 * 60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SpreadTimeCorrectionError(
            f"Git inspection failed: {' '.join(arguments)}"
        ) from exc


def _git_blob(ref: str, relative: str) -> bytes:
    result = _git("show", f"{ref}:{relative}")
    if not result.stdout:
        raise SpreadTimeCorrectionError(f"Git blob is empty: {ref}:{relative}")
    return result.stdout


def _materialize_git_prefix(ref: str, relative: str, destination: Path) -> None:
    """Materialize an exact tracked tree prefix without reading worktree bytes."""

    try:
        names = _git(
            "ls-tree",
            "-r",
            "--name-only",
            ref,
            "--",
            relative,
        ).stdout.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise SpreadTimeCorrectionError("Git tree path is non-ASCII") from exc
    if not names:
        raise SpreadTimeCorrectionError(
            f"Git tree prefix is empty: {ref}:{relative}"
        )
    for name in names:
        if name != relative and not name.startswith(relative.rstrip("/") + "/"):
            raise SpreadTimeCorrectionError("Git tree prefix escaped its boundary")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_git_blob(ref, name))


def _runtime_provenance() -> dict[str, Any]:
    """Seal the exact interpreter and loaded PyYAML distribution boundary."""

    try:
        executable = Path(sys.executable).resolve(strict=True)
        executable_bytes = executable.read_bytes()
        distribution = importlib.metadata.distribution("PyYAML")
        distribution_root = Path(distribution.locate_file("")).resolve(strict=True)
        files = tuple(distribution.files or ())
        record_entries = tuple(
            item
            for item in files
            if item.as_posix().casefold().endswith(".dist-info/record")
        )
        if len(record_entries) != 1:
            raise ValueError("PyYAML RECORD inventory is ambiguous")
        record_path = Path(
            distribution.locate_file(record_entries[0])
        ).resolve(strict=True)
        record_bytes = record_path.read_bytes()
        executable_suffixes = {".dll", ".py", ".pyd", ".so"}
        execution_inventory: list[dict[str, str]] = []
        for entry in sorted(files, key=lambda item: item.as_posix()):
            relative = entry.as_posix()
            if (
                Path(relative).suffix.casefold() not in executable_suffixes
                or not (
                    relative.startswith("yaml/")
                    or relative.startswith("_yaml/")
                    or Path(relative).name.casefold().startswith("_yaml")
                )
            ):
                continue
            if entry.hash is None or entry.hash.mode != "sha256":
                raise ValueError("PyYAML executable lacks a RECORD SHA-256")
            source = Path(distribution.locate_file(entry))
            resolved = source.resolve(strict=True)
            resolved.relative_to(distribution_root)
            if source.is_symlink() or not resolved.is_file():
                raise ValueError("PyYAML executable is link-like or unavailable")
            content_sha256 = sha256(resolved.read_bytes()).hexdigest()
            record_sha256 = base64.urlsafe_b64decode(
                entry.hash.value + "=" * (-len(entry.hash.value) % 4)
            ).hex()
            if content_sha256 != record_sha256:
                raise ValueError("PyYAML executable differs from RECORD")
            execution_inventory.append(
                {"path": relative, "sha256": content_sha256}
            )
        if not execution_inventory:
            raise ValueError("PyYAML executable inventory is empty")
        execution_by_path = {
            item["path"]: item["sha256"] for item in execution_inventory
        }
        loaded_inventory: list[dict[str, str]] = []
        for module_name, module in sorted(sys.modules.items()):
            if not (
                module_name == "yaml"
                or module_name.startswith("yaml.")
                or module_name == "_yaml"
                or module_name.startswith("_yaml.")
            ):
                continue
            module_file = getattr(module, "__file__", None)
            if type(module_file) is not str:
                continue
            resolved = Path(module_file).resolve(strict=True)
            relative = resolved.relative_to(distribution_root).as_posix()
            expected = execution_by_path.get(relative)
            if expected is None or sha256(resolved.read_bytes()).hexdigest() != expected:
                raise ValueError("loaded PyYAML module is outside sealed RECORD")
            loaded_inventory.append({"path": relative, "sha256": expected})
        loaded_inventory = [
            dict(item)
            for item in {
                (item["path"], item["sha256"]): item
                for item in loaded_inventory
            }.values()
        ]
        loaded_inventory.sort(key=lambda item: item["path"])
        if not loaded_inventory:
            raise ValueError("loaded PyYAML module inventory is empty")
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise SpreadTimeCorrectionError(
            "current Python and PyYAML provenance cannot be sealed"
        ) from exc
    return {
        "python": {
            "bytecode_cache_policy": (
                "private_external_prefix"
                if _SAFE_STARTUP
                and sys.pycache_prefix is not None
                and Path(sys.pycache_prefix).resolve().is_relative_to(
                    Path(_SAFE_BYTECODE_CACHE.name).resolve()
                )
                else "ambient_read_only_planning"
            ),
            "dont_write_bytecode": sys.dont_write_bytecode,
            "executable": executable.as_posix(),
            "executable_sha256": sha256(executable_bytes).hexdigest(),
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "pyyaml": {
            "distribution": distribution.metadata["Name"],
            "execution_files": execution_inventory,
            "loaded_execution_files": loaded_inventory,
            "record_path": record_path.relative_to(
                distribution_root
            ).as_posix(),
            "record_sha256": sha256(record_bytes).hexdigest(),
            "version": distribution.version,
        },
        "schema": "correction_runtime_provenance.v1",
    }


def _reviewed_code_checkpoint() -> dict[str, Any]:
    try:
        paths = validator_execution_dependency_paths(
            Path(__file__).resolve(),
            include_deferred_imports=True,
        )
        checkpoint = capture_local_correction_checkpoint(
            ROOT,
            execution_paths=paths,
        )
        checkpoint["runtime_provenance"] = _runtime_provenance()
    except (ContentAddressedCorrectionError, OSError, RuntimeError, ValueError) as exc:
        raise SpreadTimeCorrectionError(
            "correction implementation closure cannot be sealed"
        ) from exc
    if (
        Path(__file__).resolve()
        not in {Path(path).resolve() for path in paths}
        or not checkpoint.get("execution_files")
    ):
        raise SpreadTimeCorrectionError(
            "correction implementation closure omitted its entrypoint"
        )
    return checkpoint


def _require_current_reviewed_execution_closure(
    plan: CorrectionPlanCore | CorrectionReceiptEnvelope,
) -> None:
    """Reject import resolution drift without claiming unrelated user code."""

    expected_provenance = plan.events[0].binding.get("runtime_provenance")
    if (
        not isinstance(expected_provenance, Mapping)
        or _runtime_provenance() != dict(expected_provenance)
    ):
        raise SpreadTimeCorrectionError(
            "Python or PyYAML runtime provenance differs from the reviewed core"
        )
    try:
        paths = validator_execution_dependency_paths(
            Path(__file__).resolve(),
            include_deferred_imports=True,
        )
        observed = tuple(
            sorted(
                (
                    path.resolve().relative_to(ROOT).as_posix(),
                    sha256(path.read_bytes()).hexdigest(),
                )
                for path in paths
            )
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise SpreadTimeCorrectionError(
            "correction execution closure cannot be revalidated"
        ) from exc
    expected = tuple(
        (item.path, item.sha256) for item in plan.execution_files
    )
    if observed != expected:
        raise SpreadTimeCorrectionError(
            "correction import resolution differs from the reviewed plan"
        )


def _read_control_bytes(document: bytes) -> dict[str, Any]:
    try:
        value = json.loads(document.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpreadTimeCorrectionError("canonical control is malformed") from exc
    if not isinstance(value, dict) or not isinstance(value.get("authority"), dict):
        raise SpreadTimeCorrectionError("canonical control authority is absent")
    return value


def _current_control() -> dict[str, Any]:
    try:
        return _read_control_bytes((ROOT / "state" / "control.json").read_bytes())
    except OSError as exc:
        raise SpreadTimeCorrectionError("canonical control is unavailable") from exc


def _governing_mission_id(control: Mapping[str, Any]) -> str:
    science = control.get("scientific")
    mission_id = None if not isinstance(science, Mapping) else science.get(
        "active_mission"
    )
    if type(mission_id) is not str or not mission_id or not mission_id.isascii():
        raise SpreadTimeCorrectionError("active governing Mission is unavailable")
    return mission_id


def _authority_paths(control: Mapping[str, Any]) -> tuple[str, ...]:
    authority = control.get("authority")
    if not isinstance(authority, Mapping):
        raise SpreadTimeCorrectionError("authority manifest is absent")
    operating = authority.get("operating_direction")
    contracts = authority.get("contracts")
    foundation = authority.get("foundation_inputs")
    if (
        type(operating) is not str
        or not isinstance(contracts, list)
        or not isinstance(foundation, list)
        or any(type(item) is not str for item in [*contracts, *foundation])
    ):
        raise SpreadTimeCorrectionError("authority path inventory is malformed")
    paths = tuple([operating, *contracts, *foundation])
    if len(paths) != len(set(paths)):
        raise SpreadTimeCorrectionError("authority path inventory is duplicated")
    return paths


def _manifest_digest_from_bytes(documents: Mapping[str, bytes]) -> str:
    return canonical_digest(
        domain="authority-manifest",
        payload={
            relative: sha256(content).hexdigest()
            for relative, content in sorted(documents.items())
        },
    )


def _journal_path() -> tuple[str, bytes | None]:
    manifest_path = ROOT / "records" / "journal" / "manifest.json"
    if not manifest_path.is_file():
        legacy = ROOT / "records" / "journal.jsonl"
        if not legacy.is_file():
            raise SpreadTimeCorrectionError("canonical Journal is unavailable")
        return "records/journal.jsonl", None
    try:
        document = manifest_path.read_bytes()
        manifest = json.loads(document.decode("ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpreadTimeCorrectionError("Journal manifest is malformed") from exc
    active = None if not isinstance(manifest, Mapping) else manifest.get(
        "active_segment"
    )
    relative = None if not isinstance(active, Mapping) else active.get("path")
    if (
        manifest.get("schema") != "journal_manifest_v1"
        or type(relative) is not str
        or not relative.startswith("records/journal/")
        or "\\" in relative
        or ":" in relative
        or any(part in {"", ".", ".."} for part in relative.split("/"))
        or not (ROOT / relative).is_file()
    ):
        raise SpreadTimeCorrectionError("Journal active segment is malformed")
    return relative, document


def _predecessor_authority_documents(
    baseline_control: Mapping[str, Any],
    paths: tuple[str, ...],
) -> tuple[str, dict[str, bytes]]:
    expected = baseline_control["authority"]["manifest_digest"]
    matches: list[tuple[str, dict[str, bytes]]] = []
    for ref in ("origin/main", "HEAD"):
        documents = {relative: _git_blob(ref, relative) for relative in paths}
        if _manifest_digest_from_bytes(documents) == expected:
            matches.append((ref, documents))
    if not matches:
        raise SpreadTimeCorrectionError(
            "neither origin/main nor local HEAD contains the control-bound predecessor"
        )
    return matches[0]


@contextmanager
def _predecessor_foundation(
    documents: Mapping[str, bytes],
    *,
    expected_digest: str,
) -> Iterator[Path]:
    with TemporaryDirectory(prefix="axiom-spread-time-predecessor-") as temporary:
        root = Path(temporary).resolve()
        for relative, content in documents.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        observed = _manifest_digest_from_bytes(
            {relative: (root / relative).read_bytes() for relative in documents}
        )
        if observed != expected_digest:
            raise SpreadTimeCorrectionError(
                "temporary predecessor foundation changed during materialization"
            )
        yield root


def _registry() -> EvidenceValidatorRegistry:
    return EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))


def _writer(
    *,
    foundation_root: Path | None = None,
    require_apply_api: bool = False,
) -> StateWriter:
    writer = StateWriter(
        ROOT,
        foundation_root=foundation_root,
        validation_registry=_registry() if require_apply_api else None,
    )
    if require_apply_api:
        missing = tuple(
            name
            for name in _REQUIRED_WRITER_METHODS
            if not callable(getattr(writer, name, None))
        )
        if missing:
            raise SpreadTimeCorrectionError(
                "spread/time apply requires missing StateWriter APIs: "
                + ", ".join(missing)
            )
    return writer


def _receipt_binding(event: Mapping[str, Any]) -> CorrectionEventReceiptBinding:
    rows = event.get("index_records")
    if (
        not isinstance(rows, list)
        or not rows
        or not isinstance(rows[0], Mapping)
        or rows[0].get("kind") != "operation"
        or not isinstance(rows[0].get("payload"), Mapping)
    ):
        raise SpreadTimeCorrectionError(
            "shadow transition omitted its exact operation receipt"
        )
    operation_result = rows[0]["payload"].get("result")
    if type(event.get("operation_id")) is not str:
        raise SpreadTimeCorrectionError("shadow transition operation id is absent")
    byte_upper_bound = len(canonical_bytes(dict(event))) + 1
    return CorrectionEventReceiptBinding(
        canonical_event_byte_count=byte_upper_bound,
        canonical_event_sha256=sha256(
            canonical_bytes(dict(event))
        ).hexdigest(),
        event_id=event["event_id"],
        occurred_at_utc=event["occurred_at_utc"],
        journal_offset=event["journal_offset"],
        event_payload_sha256=sha256(canonical_bytes(event.get("payload"))).hexdigest(),
        control_projection_sha256=sha256(
            canonical_bytes(event.get("control"))
        ).hexdigest(),
        operation_result_sha256=sha256(
            canonical_bytes(operation_result)
        ).hexdigest(),
        semantic_index_records_sha256=sha256(
            canonical_bytes(rows[1:])
        ).hexdigest(),
        semantic_index_record_count=len(rows) - 1,
    )


@dataclass(frozen=True, slots=True)
class _SyntheticPreview:
    receipts: tuple[CorrectionEventReceiptBinding, ...]
    events: tuple[Mapping[str, Any], ...]
    dynamic_expectations: tuple[_DynamicActionExpectation | None, ...]


def _preview_receipt_bindings(
    *,
    core: CorrectionPlanCore,
    event_timestamps: Sequence[str],
    baseline_control: Mapping[str, Any],
    predecessor_documents: Mapping[str, bytes],
    prospective_documents: Mapping[str, bytes],
    report_bytes: bytes,
    invalidations: HistoricalSpreadTimeInvalidationInventory,
    adjudications: HistoricalSpreadTimeAdjudicationPlan,
    cost_manifest: HistoricalSpreadSemanticsAuditManifest,
    family_authorities: Mapping[str, HistoricalFamilyAuthority],
    direct_evidence_hashes: Sequence[str],
) -> _SyntheticPreview:
    """Execute all seven transitions in an isolated projection for receipts."""

    if len(event_timestamps) != core.event_count or any(
        type(value) is not str or not value for value in event_timestamps
    ):
        raise SpreadTimeCorrectionError(
            "receipt preview requires one exact observed time per event"
        )
    baseline_sequence = baseline_control["heads"]["journal"]["sequence"]
    independent_cursor = _IndependentEventCursor(
        journal_offset=(
            core.baseline.journal_start_offset
            + core.baseline.journal_size_bytes
        ),
        previous_event_id=core.baseline.journal_event_id,
        index_record_count=core.baseline.index_record_count,
        index_projection_digest=core.baseline.index_projection_digest,
    )
    dynamic_expectations: list[_DynamicActionExpectation | None] = [None] * 7
    with TemporaryDirectory(prefix="axiom-spread-time-receipt-preview-") as temporary:
        shadow_root = Path(temporary).resolve()
        (shadow_root / "state").mkdir(parents=True)
        (shadow_root / "local").mkdir(parents=True)
        baseline_control_bytes = _git_blob("HEAD", "state/control.json")
        if (
            sha256(baseline_control_bytes).hexdigest()
            != core.baseline.control_sha256
            or _read_control_bytes(baseline_control_bytes) != baseline_control
        ):
            raise SpreadTimeCorrectionError(
                "shadow baseline control differs from the correction core"
            )
        (shadow_root / "state" / "control.json").write_bytes(
            baseline_control_bytes
        )
        if core.baseline.journal_path.startswith("records/journal/"):
            _materialize_git_prefix("HEAD", "records/journal", shadow_root)
        else:
            target = shadow_root / core.baseline.journal_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_git_blob("HEAD", core.baseline.journal_path))
        durable_evidence = EvidenceStore(ROOT / "local" / "evidence")
        for identity in direct_evidence_hashes:
            content = durable_evidence.read_verified(identity)
            target = (
                shadow_root
                / "local"
                / "evidence"
                / "sha256"
                / identity[:2]
                / identity
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        for relative, content in predecessor_documents.items():
            target = shadow_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        for _spec, relative in _FAMILY_SPECS.values():
            target = shadow_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())

        shadow = StateWriter(
            shadow_root,
            clock=lambda: "2000-01-01T00:00:00Z",
            engineering_fixture=True,
            foundation_root=shadow_root,
            validation_registry=_registry(),
        )
        recovery = shadow.recover()
        if (
            recovery.get("journal_sequence")
            != core.baseline.journal_sequence
            or recovery.get("index_rebuilt") is not True
        ):
            raise SpreadTimeCorrectionError(
                "shadow baseline projection was not rebuilt from Journal authority"
            )
        report_hash = sha256(report_bytes).hexdigest()
        cost_bytes = canonical_bytes(cost_manifest.to_payload())
        evidence = _ShadowEvidenceStore(
            durable_evidence,
            {
                report_hash: report_bytes,
                cost_manifest.artifact_hash: cost_bytes,
            },
        )
        shadow.evidence = evidence  # type: ignore[assignment]
        stable = shadow.require_stable_head()
        if (
            stable.get("control_revision") != baseline_control.get("revision")
            or stable.get("journal_event_id")
            != baseline_control["heads"]["journal"]["event_id"]
        ):
            raise SpreadTimeCorrectionError(
                "shadow receipt preview did not preserve the baseline"
            )
        verification_material = SpreadTimeCorrectionMaterial(
            core=core,
            preview_receipts=(),
            preview_events=(),
            preview_dynamic_expectations=(),
            report_bytes=report_bytes,
            invalidation_inventory=invalidations,
            adjudication_plan=adjudications,
            cost_manifest=cost_manifest,
            family_authorities=family_authorities,
            predecessor_documents=predecessor_documents,
            prospective_documents=prospective_documents,
            direct_evidence_hashes=tuple(direct_evidence_hashes),
        )

        def require_latest_preview(
            ordinal: int,
            dynamic_expectation: _DynamicActionExpectation | None = None,
        ) -> None:
            nonlocal independent_cursor
            _head, preview_event = shadow.journal.tail()
            if preview_event is None:
                raise SpreadTimeCorrectionError(
                    "shadow transition omitted its latest event"
                )
            _require_action_specific_binding(
                core,
                ordinal,
                preview_event,
                verification_material,
                dynamic_expectation,
            )
            independent_cursor = _require_independent_event_envelope(
                core,
                ordinal,
                preview_event,
                independent_cursor,
                occurred_at_utc=event_timestamps[ordinal - 1],
            )

        replacements = {
            relative: content
            for relative, content in prospective_documents.items()
            if content != predecessor_documents[relative]
        }
        _invoke_replay_transition(
            shadow,
            event_timestamps[0],
            lambda: shadow.migrate_authority(
                replacements=replacements,
                reason=AUTHORITY_REASON,
                operation_id=core.operation_id(1),
                allow_active_stable_boundary=True,
            ),
        )
        require_latest_preview(1)
        _invoke_replay_transition(
            shadow,
            event_timestamps[1],
            lambda: shadow.activate_research_protocol(
                activation=ResearchProtocolActivation(
                    protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
                    validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
                    authority_manifest_digest=_manifest_digest_from_bytes(
                        prospective_documents
                    ),
                    audit_artifact_hash=report_hash,
                ),
                operation_id=core.operation_id(2),
                allow_active_stable_boundary=True,
            ),
        )
        require_latest_preview(2)
        _invoke_replay_transition(
            shadow,
            event_timestamps[2],
            lambda: shadow.record_historical_scientific_validity_invalidations(
                invalidations=invalidations.invalidations,
                operation_id=core.operation_id(3),
            ),
        )
        require_latest_preview(3)
        _invoke_replay_transition(
            shadow,
            event_timestamps[3],
            lambda: shadow.record_historical_scientific_adjudications(
                requests=adjudications.requests,
                audit_artifact_hash=report_hash,
                operation_id=core.operation_id(4),
            ),
        )
        require_latest_preview(4)
        for ordinal, obligation_id in enumerate(REPLAY_OBLIGATION_IDS, start=5):
            dynamic_expectation = _derive_dynamic_action_expectation(
                shadow,
                verification_material,
                ordinal=ordinal,
            )
            dynamic_expectations[ordinal - 1] = dynamic_expectation
            def invalidate_replay(
                *,
                selected_ordinal: int = ordinal,
                selected_obligation_id: str = obligation_id,
            ) -> Any:
                invalidation_plan = shadow.plan_historical_replay_satisfaction_invalidation(
                    obligation_id=selected_obligation_id
                )
                manifest = invalidation_plan.get("audit_manifest")
                if not isinstance(manifest, Mapping):
                    raise SpreadTimeCorrectionError(
                        "shadow replay invalidation lacks its typed manifest"
                    )
                document = canonical_bytes(dict(manifest))
                artifact = evidence.finalize(document)
                if invalidation_plan.get("audit_manifest_sha256") != artifact.sha256:
                    raise SpreadTimeCorrectionError(
                        "shadow replay invalidation manifest is not exact"
                    )
                return shadow.invalidate_historical_replay_satisfaction(
                    obligation_id=selected_obligation_id,
                    audit_manifest_hash=artifact.sha256,
                    operation_id=core.operation_id(selected_ordinal),
                    historical_family_authority=family_authorities[
                        selected_obligation_id
                    ],
                )
            _invoke_replay_transition(
                shadow,
                event_timestamps[ordinal - 1],
                invalidate_replay,
            )
            require_latest_preview(ordinal, dynamic_expectation)
        _invoke_replay_transition(
            shadow,
            event_timestamps[6],
            lambda: shadow.record_historical_cost_semantics_latch(
                manifest_artifact_hash=cost_manifest.artifact_hash,
                operation_id=core.operation_id(7),
            ),
        )
        require_latest_preview(7)
        suffix = tuple(shadow.journal.read_all()[baseline_sequence:])

    receipts = tuple(_receipt_binding(event) for event in suffix)
    semantic_counts = tuple(
        receipt.semantic_index_record_count for receipt in receipts
    )
    if len(receipts) != 7 or semantic_counts != (1, 1, 34, 51, 2, 2, 502):
        raise SpreadTimeCorrectionError(
            "shadow seven-event receipt inventory changed shape"
        )
    return _SyntheticPreview(
        receipts=receipts,
        events=suffix,
        dynamic_expectations=tuple(dynamic_expectations),
    )


def _family_authority(
    index: Any,
    *,
    obligation_id: str,
) -> HistoricalFamilyAuthority:
    spec, relative = _FAMILY_SPECS[obligation_id]
    family = historical_family_from_manifest(spec.manifest())
    source = ROOT / relative
    try:
        content = source.read_bytes()
    except OSError as exc:
        raise SpreadTimeCorrectionError(
            "historical family reconstruction source is unavailable"
        ) from exc
    source_hash = sha256(content).hexdigest()
    module_name = source.name
    if (
        HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256.get(module_name) != source_hash
        or HISTORICAL_FAMILY_IDENTITY_BY_MODULE.get(module_name) != family.identity
    ):
        raise SpreadTimeCorrectionError(
            "historical family source differs from the frozen registry"
        )

    missing_by_member: set[tuple[str, ...]] = set()
    for member in family.members:
        trial = index.get("trial", member.historical_reference_executable_id)
        executable = None if trial is None else trial.payload.get("executable")
        parameters = (
            None if not isinstance(executable, Mapping) else executable.get("parameters")
        )
        expected = member.parameter_values()
        if trial is None or not isinstance(parameters, Mapping):
            raise SpreadTimeCorrectionError(
                "historical family member trial is unavailable"
            )
        missing = tuple(sorted(set(expected).difference(parameters)))
        if any(parameters.get(name) != value for name, value in expected.items() if name not in missing):
            raise SpreadTimeCorrectionError(
                "historical family member parameters differ from reconstruction"
            )
        missing_by_member.add(missing)
    if len(missing_by_member) != 1:
        raise SpreadTimeCorrectionError(
            "historical family reconstruction-only parameters are inconsistent"
        )
    reconstruction_only = next(iter(missing_by_member))
    if reconstruction_only:
        raise SpreadTimeCorrectionError(
            "historical family reconstruction unexpectedly omits parameters"
        )
    return HistoricalFamilyAuthority(
        replay_obligation_id=obligation_id,
        family=family,
        reconstruction_source_path=relative,
        reconstruction_source_sha256=source_hash,
        reconstruction_only_parameter_names=reconstruction_only,
    )


@dataclass(frozen=True, slots=True)
class _DerivedCorrectionInputs:
    invalidations: HistoricalSpreadTimeInvalidationInventory
    adjudications: HistoricalSpreadTimeAdjudicationPlan
    cost_manifest: HistoricalSpreadSemanticsAuditManifest
    family_authorities: Mapping[str, HistoricalFamilyAuthority]
    readjudication_inventory: _ExpectedReadjudicationInventory
    cost_completion_ids: tuple[str, ...]
    cost_semantic_rows: tuple[Mapping[str, Any], ...]
    protocol_activation_ordinal: int
    prior_protocol_activation_record_id: str | None
    direct_evidence_hashes: tuple[str, ...]


def _derive_correction_inputs(
    index: Any,
    evidence: EvidenceStore,
    *,
    report_bytes: bytes,
    control: Mapping[str, Any],
) -> _DerivedCorrectionInputs:
    """Derive the fixed seven-action inputs from one authenticated baseline."""

    report_hash = sha256(report_bytes).hexdigest()
    invalidations = build_historical_spread_time_invalidation_inventory(
        index,
        evidence,
        audit_artifact_hash=report_hash,
    )
    adjudications = build_historical_spread_time_adjudication_plan(
        index,
        invalidations,
    )
    cost_manifest = build_historical_spread_semantics_audit_manifest(
        index,
        audit_artifact_hash=report_hash,
    )
    cost_manifest.require_report(report_bytes)
    family_authorities = {
        obligation_id: _family_authority(index, obligation_id=obligation_id)
        for obligation_id in REPLAY_OBLIGATION_IDS
    }
    observed_replay = {
        member.replay_obligation_id: member.accepted_satisfaction_record_id
        for member in adjudications.family(P0_REPLAY_FAMILY_ID).members
    }
    if observed_replay != REPLAY_SATISFACTION_IDS:
        raise SpreadTimeCorrectionError(
            "readjudication plan does not bind the exact two satisfactions"
        )
    readjudication_inventory = _expected_readjudication_inventory(
        index,
        evidence,
        adjudications=adjudications,
        audit_artifact_hash=report_hash,
        governing_mission_id=_governing_mission_id(control),
    )
    try:
        cost_latch = HistoricalCostSemanticsLatch.from_audit_manifest(
            cost_manifest
        )
        cost_slice = validate_historical_cost_semantics_latch_binding(
            index,
            cost_latch,
            cost_manifest,
        )
    except (TypeError, ValueError) as exc:
        raise SpreadTimeCorrectionError(
            "historical cost completion identity derivation failed"
        ) from exc
    cost_completion_ids = tuple(
        member.completion_record_id for member in cost_slice.members
    )
    if (
        len(cost_completion_ids) != 501
        or len(set(cost_completion_ids)) != 501
        or cost_completion_ids != tuple(sorted(cost_completion_ids))
    ):
        raise SpreadTimeCorrectionError(
            "historical cost completion identity inventory changed shape"
        )
    cost_semantic_rows = tuple(
        _record_mapping(record)
        for record in historical_cost_semantics_activation_records(
            cost_latch,
            cost_slice,
        )
    )
    if len(cost_semantic_rows) != 502:
        raise SpreadTimeCorrectionError(
            "historical cost exact semantic row inventory changed shape"
        )
    protocol_head = index.event_head("research-protocol:scientific")
    prior_protocol = (
        None
        if protocol_head is None
        else index.get(protocol_head.record_kind, protocol_head.record_id)
    )
    if protocol_head is not None and (
        prior_protocol is None
        or prior_protocol.kind != "research-protocol-activation"
        or prior_protocol.event_sequence != protocol_head.sequence
    ):
        raise SpreadTimeCorrectionError(
            "prior research protocol activation is malformed"
        )
    protocol_activation_ordinal = (
        1 if protocol_head is None else protocol_head.sequence + 1
    )
    prior_protocol_activation_record_id = (
        None if prior_protocol is None else prior_protocol.record_id
    )
    receipt_completion_ids = {
        request.completion_record_id for request in adjudications.requests
    }
    for satisfaction_id in REPLAY_SATISFACTION_IDS.values():
        resolution = index.get(
            "historical-replay-obligation-resolution",
            satisfaction_id,
        )
        payload = None if resolution is None else resolution.payload.get(
            "resolution"
        )
        evidence_ids = (
            None
            if not isinstance(payload, Mapping)
            else payload.get("evidence_record_ids")
        )
        if not isinstance(evidence_ids, list):
            raise SpreadTimeCorrectionError(
                "replay satisfaction evidence inventory is unavailable"
            )
        receipt_completion_ids.update(
            identity
            for identity in evidence_ids
            if type(identity) is str
            and index.get("job-completed", identity) is not None
        )
    direct_evidence_hashes_set: set[str] = set()
    for completion_id in receipt_completion_ids:
        completion = index.get("job-completed", completion_id)
        scientific = (
            None if completion is None else completion.payload.get("scientific")
        )
        plan_hash = (
            None
            if not isinstance(scientific, Mapping)
            else scientific.get("validation_plan_hash")
        )
        if type(plan_hash) is not str:
            raise SpreadTimeCorrectionError(
                "receipt replay completion lacks a validation plan"
            )
        direct_evidence_hashes_set.add(plan_hash)
    direct_evidence_hashes = tuple(sorted(direct_evidence_hashes_set))
    if len(direct_evidence_hashes) < len(adjudications.requests):
        raise SpreadTimeCorrectionError(
            "receipt replay evidence inventory is incomplete"
        )
    return _DerivedCorrectionInputs(
        invalidations=invalidations,
        adjudications=adjudications,
        cost_manifest=cost_manifest,
        family_authorities=family_authorities,
        readjudication_inventory=readjudication_inventory,
        cost_completion_ids=cost_completion_ids,
        cost_semantic_rows=cost_semantic_rows,
        protocol_activation_ordinal=protocol_activation_ordinal,
        prior_protocol_activation_record_id=(
            prior_protocol_activation_record_id
        ),
        direct_evidence_hashes=direct_evidence_hashes,
    )


def _baseline(
    baseline_control: Mapping[str, Any],
    *,
    journal_path: str,
    journal_manifest_bytes: bytes | None,
    stable: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
) -> CorrectionBaseline:
    control_bytes = _git_blob("HEAD", "state/control.json")
    if control_bytes != _git_blob("origin/main", "state/control.json"):
        raise SpreadTimeCorrectionError(
            "local HEAD and origin/main do not share the state baseline"
        )
    journal_bytes = _git_blob("HEAD", journal_path)
    if journal_bytes != _git_blob("origin/main", journal_path):
        raise SpreadTimeCorrectionError(
            "local HEAD and origin/main do not share the Journal baseline"
        )
    heads = baseline_control.get("heads")
    journal_head = None if not isinstance(heads, Mapping) else heads.get("journal")
    index_head = None if not isinstance(heads, Mapping) else heads.get("index")
    science = baseline_control.get("scientific")
    next_action = baseline_control.get("next_action")
    if (
        not isinstance(journal_head, Mapping)
        or not isinstance(index_head, Mapping)
        or not isinstance(science, Mapping)
        or not isinstance(next_action, Mapping)
        or stable.get("control_revision") != baseline_control.get("revision")
        or stable.get("journal_event_id") != journal_head.get("event_id")
        or stable.get("index_record_count") != index_head.get("required_record_count")
        or stable.get("projection_digest") != index_head.get("required_projection_digest")
    ):
        raise SpreadTimeCorrectionError(
            "authenticated index does not match the Git baseline control"
        )
    manifest_hash = None
    journal_start_offset = 0
    if journal_manifest_bytes is not None:
        head_manifest = _git_blob("HEAD", "records/journal/manifest.json")
        if (
            head_manifest != _git_blob("origin/main", "records/journal/manifest.json")
            or head_manifest != journal_manifest_bytes
        ):
            raise SpreadTimeCorrectionError(
                "Journal manifest is not the unchanged Git baseline"
            )
        try:
            manifest = parse_canonical(head_manifest)
        except (TypeError, ValueError) as exc:
            raise SpreadTimeCorrectionError(
                "Git baseline Journal manifest is not canonical"
            ) from exc
        active = manifest.get("active_segment") if isinstance(
            manifest, Mapping
        ) else None
        if (
            not isinstance(active, Mapping)
            or active.get("path") != journal_path
            or type(active.get("start_offset")) is not int
            or active["start_offset"] < 0
        ):
            raise SpreadTimeCorrectionError(
                "Git baseline Journal active offset is malformed"
            )
        journal_start_offset = active["start_offset"]
        manifest_hash = sha256(head_manifest).hexdigest()
    return CorrectionBaseline(
        control_revision=baseline_control["revision"],
        journal_sequence=journal_head["sequence"],
        journal_event_id=journal_head["event_id"],
        journal_path=journal_path,
        control_sha256=sha256(control_bytes).hexdigest(),
        journal_sha256=sha256(journal_bytes).hexdigest(),
        journal_start_offset=journal_start_offset,
        journal_size_bytes=len(journal_bytes),
        authority_manifest_digest=baseline_control["authority"]["manifest_digest"],
        index_record_count=index_head["required_record_count"],
        index_projection_digest=index_head["required_projection_digest"],
        mission_id=science["active_mission"],
        initiative_id=science["active_initiative"],
        next_action_kind=next_action["kind"],
        code_checkpoint_commit=checkpoint["code_checkpoint_commit"],
        code_checkpoint_tree=checkpoint["code_checkpoint_tree"],
        origin_main_commit=checkpoint["origin_main_commit"],
        journal_manifest_sha256=manifest_hash,
    )


def _compose_correction_core(
    *,
    baseline_control: Mapping[str, Any],
    baseline: CorrectionBaseline,
    prospective_digest: str,
    authority_files: tuple[AuthorityFileBinding, ...],
    checkpoint: Mapping[str, Any],
    report_bytes: bytes,
    derived: _DerivedCorrectionInputs,
) -> CorrectionPlanCore:
    """Compose the sole fixed action registry from baseline-derived inputs."""

    report_hash = sha256(report_bytes).hexdigest()
    invalidations = derived.invalidations
    adjudications = derived.adjudications
    cost_manifest = derived.cost_manifest
    family_authorities = derived.family_authorities
    control_projection_sha256 = _expected_control_projection_sha256(
        baseline_control,
        prospective_authority_manifest_digest=prospective_digest,
        readjudication_inventory=derived.readjudication_inventory,
    )
    replacement_rows = sorted(
        [
        {
            "artifact_sha256": item.prospective_sha256,
            "new_sha256": item.prospective_sha256,
            "old_sha256": item.predecessor_sha256,
            "path": item.path,
        }
        for item in authority_files
        if item.changed
        ],
        key=lambda item: item["path"],
    )
    migration_payload = {
        "boundary": "active_stable",
        "holdout_delta": 0,
        "new_manifest_digest": prospective_digest,
        "old_manifest_digest": baseline.authority_manifest_digest,
        "reason": AUTHORITY_REASON,
        "replacements": replacement_rows,
        "schema": "authority_manifest_migration.v1",
        "scientific_claim": "none",
        "trial_delta": 0,
    }
    migration_record_id = canonical_digest(
        domain="authority-manifest-migration",
        payload=migration_payload,
    )
    activation = ResearchProtocolActivation(
        protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
        validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        authority_manifest_digest=prospective_digest,
        audit_artifact_hash=report_hash,
    )
    migration_semantic_row = {
        "kind": "authority-migration",
        "record_id": migration_record_id,
        "subject": "Authority:active",
        "status": "activated",
        "fingerprint": migration_record_id,
        "payload": migration_payload,
        "event_stream": None,
        "event_sequence": None,
    }
    activation_semantic_row = {
        "kind": "research-protocol-activation",
        "record_id": activation.identity,
        "subject": "ProjectGoal:OPERATING_DIRECTION.md",
        "status": "active",
        "fingerprint": activation.identity.removeprefix(
            "research-protocol:"
        ),
        "payload": {
            **activation.to_identity_payload(),
            "ordinal": derived.protocol_activation_ordinal,
            "scientific_trial_delta": 0,
            "supersedes_activation_record_id": (
                derived.prior_protocol_activation_record_id
            ),
        },
        "event_stream": "research-protocol:scientific",
        "event_sequence": derived.protocol_activation_ordinal,
    }
    invalidation_semantic_rows = tuple(
        _record_mapping(
            completion_validity_invalidation_record(item, sequence=1)
        )
        for item in invalidations.invalidations
    )
    event_three_result = {
        "authority_delta": dict(_ZERO_AUTHORITY_DELTA),
        "invalidations": [
            {
                "completion_record_id": item.completion_record_id,
                "invalidation_record_id": item.identity,
            }
            for item in invalidations.invalidations
        ],
    }
    event_four_result = {
        "adjudication_record_ids": list(
            derived.readjudication_inventory.adjudication_ids
        ),
        "audit_artifact_hash": report_hash,
        "candidate_delta": 0,
        "holdout_delta": 0,
        "replay_obligation_ids": list(
            derived.readjudication_inventory.new_obligation_ids
        ),
        "replay_priority_escalation_ids": list(
            derived.readjudication_inventory.priority_escalation_ids
        ),
        "reused_replay_obligation_ids": sorted(REPLAY_OBLIGATION_IDS),
        "trial_delta": 0,
    }
    event_seven_result = {
        "audit_manifest_hash": cost_manifest.artifact_hash,
        "authority_delta": dict(_ZERO_AUTHORITY_DELTA),
        "latch_record_id": HistoricalCostSemanticsLatch.from_audit_manifest(
            cost_manifest
        ).identity,
    }
    invalidation_payload_hash = sha256(
        canonical_bytes(
            [item.to_identity_payload() for item in invalidations.invalidations]
        )
    ).hexdigest()
    adjudication_manifest_bytes = canonical_bytes(
        adjudications.to_request_manifest_payload()
    )
    cost_manifest_bytes = canonical_bytes(cost_manifest.to_payload())
    evidence_bindings = (
        CorrectionEvidenceBinding(role="audit-report", sha256=report_hash),
        CorrectionEvidenceBinding(
            role="completion-invalidation-inventory",
            sha256=invalidation_payload_hash,
        ),
        CorrectionEvidenceBinding(
            role="completion-audit-slice-inventory",
            sha256=invalidations.audit_slice_digest_inventory_digest,
        ),
        CorrectionEvidenceBinding(
            role="legacy-readjudication-manifest",
            sha256=sha256(adjudication_manifest_bytes).hexdigest(),
        ),
        CorrectionEvidenceBinding(
            role="historical-cost-semantics-manifest",
            sha256=sha256(cost_manifest_bytes).hexdigest(),
        ),
        *(
            CorrectionEvidenceBinding(
                role=f"{authority.family.original_study_id.lower()}-family-source",
                sha256=authority.reconstruction_source_sha256,
            )
            for authority in family_authorities.values()
        ),
    )
    event_intents = (
        CorrectionEventIntent(
            action="authority-migration",
            event_kind="authority_migrated",
            subject="Authority:active",
            binding={
                "control_projection_sha256": control_projection_sha256[0],
                "new_manifest_digest": prospective_digest,
                "old_manifest_digest": baseline.authority_manifest_digest,
                "reason": AUTHORITY_REASON,
                "replacement_rows": replacement_rows,
                "runtime_provenance": checkpoint["runtime_provenance"],
                "operation_result": {
                    "migration_id": migration_record_id,
                    "new_manifest_digest": prospective_digest,
                },
                "semantic_row_sha256": [
                    _row_sha256(migration_semantic_row)
                ],
                "semantic_records": [
                    {
                        "kind": "authority-migration",
                        "record_id": migration_record_id,
                    }
                ],
                "semantic_record_count": 1,
            },
        ),
        CorrectionEventIntent(
            action="prospective-protocol-rebind",
            event_kind="research_protocol_activated",
            subject="ProjectGoal:OPERATING_DIRECTION.md",
            binding={
                "audit_artifact_hash": report_hash,
                "authority_manifest_digest": prospective_digest,
                "control_projection_sha256": control_projection_sha256[1],
                "protocol": ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2.value,
                "operation_result": {
                    "activation_record_id": activation.identity,
                    "ordinal": derived.protocol_activation_ordinal,
                    "protocol": activation.protocol.value,
                    "trial_delta": 0,
                    "validator_id": activation.validator_id,
                },
                "semantic_row_sha256": [
                    _row_sha256(activation_semantic_row)
                ],
                "semantic_records": [
                    {
                        "kind": "research-protocol-activation",
                        "record_id": activation.identity,
                    }
                ],
                "semantic_record_count": 1,
                "validator_id": SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
            },
        ),
        CorrectionEventIntent(
            action="completion-validity-invalidations",
            event_kind="historical_scientific_validity_invalidations_recorded",
            subject="ProjectGoal:OPERATING_DIRECTION.md",
            binding={
                "audit_artifact_hash": report_hash,
                "audit_slice_inventory_digest": (
                    invalidations.audit_slice_digest_inventory_digest
                ),
                "control_projection_sha256": control_projection_sha256[2],
                "invalidation_count": len(invalidations.invalidations),
                "invalidation_payload_sha256": invalidation_payload_hash,
                "operation_result": event_three_result,
                "semantic_row_sha256": [
                    _row_sha256(row) for row in invalidation_semantic_rows
                ],
                "semantic_records": [
                    {
                        "kind": "historical-scientific-validity-invalidation",
                        "record_id": item.identity,
                    }
                    for item in invalidations.invalidations
                ],
                "semantic_record_count": 34,
            },
        ),
        CorrectionEventIntent(
            action="historical-readjudication",
            event_kind="historical_scientific_adjudications_recorded",
            subject="ProjectGoal:OPERATING_DIRECTION.md",
            binding={
                "audit_artifact_hash": report_hash,
                "control_projection_sha256": control_projection_sha256[3],
                "family_counts": [
                    len(family.members) for family in adjudications.families
                ],
                "replay_priority_escalation_ids": list(
                    derived.readjudication_inventory.priority_escalation_ids
                ),
                "request_count": len(adjudications.requests),
                "request_manifest_digest": adjudications.request_manifest_digest,
                "request_manifest_sha256": sha256(
                    adjudication_manifest_bytes
                ).hexdigest(),
                "operation_result": event_four_result,
                "semantic_row_sha256": [
                    _row_sha256(row)
                    for row in derived.readjudication_inventory.semantic_rows
                ],
                "semantic_records": [
                    {"kind": kind, "record_id": record_id}
                    for kind, record_id in (
                        derived.readjudication_inventory.semantic_records
                    )
                ],
                "semantic_record_count": 51,
            },
        ),
        *(
            CorrectionEventIntent(
                action=(
                    "invalidate-c537-replay-satisfaction"
                    if obligation_id == REPLAY_OBLIGATION_IDS[0]
                    else "invalidate-a8da-replay-satisfaction"
                ),
                event_kind="historical_replay_satisfaction_invalidated",
                subject="Mission:active",
                binding={
                    "accepted_satisfaction_record_id": (
                        REPLAY_SATISFACTION_IDS[obligation_id]
                    ),
                    "audit_manifest_derivation": (
                        "writer_current_completion_validity_plan.v1"
                    ),
                    "control_projection_sha256": (
                        control_projection_sha256[4 + invalidation_index]
                    ),
                    "historical_family_authority_id": (
                        family_authorities[obligation_id].identity
                    ),
                    "obligation_id": obligation_id,
                    "semantic_record_kinds": [
                        "historical-replay-satisfaction-invalidation",
                        "historical-family-authority",
                    ],
                    "operation_result_fields": [
                        "audit_manifest_hash",
                        "candidate_delta",
                        "historical_family_authority_id",
                        "holdout_reveal_delta",
                        "invalidated_satisfaction_record_id",
                        "pending_replay_obligation_ids",
                        "replay_obligation_id",
                        "scientific_claim_delta",
                        "scientific_satisfaction_delta",
                        "scientific_trial_delta",
                    ],
                    "semantic_record_count": 2,
                },
            )
            for invalidation_index, obligation_id in enumerate(
                REPLAY_OBLIGATION_IDS
            )
        ),
        CorrectionEventIntent(
            action="historical-cost-semantics-latch",
            event_kind="historical_cost_semantics_latch_recorded",
            subject="ProjectGoal:OPERATING_DIRECTION.md",
            binding={
                "audit_manifest_hash": cost_manifest.artifact_hash,
                "audit_report_hash": report_hash,
                "completion_count": 501,
                "control_projection_sha256": control_projection_sha256[6],
                "latch_record_id": (
                    HistoricalCostSemanticsLatch.from_audit_manifest(
                        cost_manifest
                    ).identity
                ),
                "operation_result": event_seven_result,
                "semantic_row_sha256": [
                    _row_sha256(row) for row in derived.cost_semantic_rows
                ],
                "semantic_records": [
                    {
                        "kind": LATCH_RECORD_KIND,
                        "record_id": HistoricalCostSemanticsLatch.from_audit_manifest(
                            cost_manifest
                        ).identity,
                    },
                    *(
                        {
                            "kind": COMPLETION_SCOPE_RECORD_KIND,
                            "record_id": completion_id,
                        }
                        for completion_id in derived.cost_completion_ids
                    ),
                ],
                "semantic_record_count": 502,
            },
        ),
    )
    return CorrectionPlanCore(
        operation_namespace=OPERATION_NAMESPACE,
        baseline=baseline,
        prospective_authority_manifest_digest=prospective_digest,
        authority_files=authority_files,
        code_checkpoint_files=checkpoint["code_checkpoint_files"],
        execution_files=checkpoint["execution_files"],
        evidence_bindings=evidence_bindings,
        event_intents=event_intents,
        purpose=PURPOSE,
    )


def _build_material(*, include_synthetic_preview: bool = True) -> SpreadTimeCorrectionMaterial:
    if type(include_synthetic_preview) is not bool:
        raise SpreadTimeCorrectionError("synthetic preview flag must be bool")
    checkpoint = _reviewed_code_checkpoint()
    baseline_control = _read_control_bytes(_git_blob("HEAD", "state/control.json"))
    current = _current_control()
    if current != baseline_control:
        raise SpreadTimeCorrectionError(
            "a new plan may be built only before its first Journal event"
        )
    if current.get("next_action", {}).get("kind") != "portfolio_decision":
        raise SpreadTimeCorrectionError(
            "spread/time correction requires the stable Portfolio boundary"
        )
    paths = _authority_paths(baseline_control)
    _predecessor_ref, predecessor_documents = _predecessor_authority_documents(
        baseline_control,
        paths,
    )
    prospective_documents = {
        relative: (ROOT / relative).read_bytes() for relative in paths
    }
    prospective_digest = _manifest_digest_from_bytes(prospective_documents)
    if prospective_digest == baseline_control["authority"]["manifest_digest"]:
        raise SpreadTimeCorrectionError(
            "prospective authority does not differ from the predecessor"
        )
    authority_files = tuple(
        AuthorityFileBinding(
            path=relative,
            predecessor_sha256=sha256(predecessor_documents[relative]).hexdigest(),
            prospective_sha256=sha256(prospective_documents[relative]).hexdigest(),
        )
        for relative in paths
    )
    report_path = ROOT / AUDIT_REPORT_PATH
    try:
        report_bytes = report_path.read_bytes()
        report_bytes.decode("ascii")
    except (OSError, UnicodeDecodeError) as exc:
        raise SpreadTimeCorrectionError(
            "spread/time audit report is unavailable or non-ASCII"
        ) from exc
    report_hash = sha256(report_bytes).hexdigest()
    journal_path, journal_manifest_bytes = _journal_path()

    with _predecessor_foundation(
        predecessor_documents,
        expected_digest=baseline_control["authority"]["manifest_digest"],
    ) as foundation_root:
        writer = _writer(foundation_root=foundation_root)
        stable = writer.require_stable_head()
        evidence = _ReadOnlyEvidenceOverlay(
            writer.evidence,
            {report_hash: report_bytes},
        )
        with writer.open_stable_index() as (_control, index):
            derived = _derive_correction_inputs(
                index,
                evidence,
                report_bytes=report_bytes,
                control=baseline_control,
            )
    invalidations = derived.invalidations
    adjudications = derived.adjudications
    cost_manifest = derived.cost_manifest
    family_authorities = derived.family_authorities
    direct_evidence_hashes = derived.direct_evidence_hashes

    baseline = _baseline(
        baseline_control,
        journal_path=journal_path,
        journal_manifest_bytes=journal_manifest_bytes,
        stable=stable,
        checkpoint=checkpoint,
    )
    core = _compose_correction_core(
        baseline_control=baseline_control,
        baseline=baseline,
        prospective_digest=prospective_digest,
        authority_files=authority_files,
        checkpoint=checkpoint,
        report_bytes=report_bytes,
        derived=derived,
    )
    preview = (
        _preview_receipt_bindings(
            core=core,
            event_timestamps=_synthetic_preview_timestamps(core.event_count),
            baseline_control=baseline_control,
            predecessor_documents=predecessor_documents,
            prospective_documents=prospective_documents,
            report_bytes=report_bytes,
            invalidations=invalidations,
            adjudications=adjudications,
            cost_manifest=cost_manifest,
            family_authorities=family_authorities,
            direct_evidence_hashes=direct_evidence_hashes,
        )
        if include_synthetic_preview
        else _SyntheticPreview(receipts=(), events=(), dynamic_expectations=())
    )
    receipts = preview.receipts
    if (
        core.event_count != 7
        or len(invalidations.invalidations) != EXPECTED_COMPLETION_COUNT
        or len(adjudications.requests) != EXPECTED_LEGACY_COMPLETION_COUNT
        or len(
            core.events[3].binding["replay_priority_escalation_ids"]
        )
        != 2
        or core.events[4].binding["obligation_id"] != REPLAY_OBLIGATION_IDS[0]
        or core.events[5].binding["obligation_id"] != REPLAY_OBLIGATION_IDS[1]
        or core.events[6].binding["completion_count"] != 501
    ):
        raise SpreadTimeCorrectionError(
            "seven-event spread/time correction inventory changed shape"
        )
    return SpreadTimeCorrectionMaterial(
        core=core,
        preview_receipts=receipts,
        preview_events=preview.events,
        preview_dynamic_expectations=preview.dynamic_expectations,
        report_bytes=report_bytes,
        invalidation_inventory=invalidations,
        adjudication_plan=adjudications,
        cost_manifest=cost_manifest,
        family_authorities=family_authorities,
        predecessor_documents=predecessor_documents,
        prospective_documents=prospective_documents,
        direct_evidence_hashes=direct_evidence_hashes,
    )


def _semantic_rows(event: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    rows = event.get("index_records")
    if (
        not isinstance(rows, list)
        or not rows
        or any(not isinstance(row, Mapping) for row in rows)
    ):
        raise SpreadTimeCorrectionError("replayed event rows are malformed")
    return tuple(rows[1:])


def _operation_result(event: Mapping[str, Any]) -> Mapping[str, Any]:
    rows = event.get("index_records")
    operation = None if not isinstance(rows, list) or not rows else rows[0]
    payload = None if not isinstance(operation, Mapping) else operation.get("payload")
    result = None if not isinstance(payload, Mapping) else payload.get("result")
    if (
        not isinstance(operation, Mapping)
        or operation.get("kind") != "operation"
        or not isinstance(result, Mapping)
    ):
        raise SpreadTimeCorrectionError(
            "replayed event operation result is malformed"
        )
    return result


def _semantic_inventory(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[tuple[str, str], ...]:
    inventory = tuple(
        (row.get("kind"), row.get("record_id")) for row in rows
    )
    if any(
        type(kind) is not str or type(record_id) is not str
        for kind, record_id in inventory
    ):
        raise SpreadTimeCorrectionError(
            "replayed event semantic identity is malformed"
        )
    return inventory  # type: ignore[return-value]


def _bound_semantic_inventory(
    binding: Mapping[str, Any],
) -> tuple[tuple[str, str], ...]:
    raw = binding.get("semantic_records")
    if not isinstance(raw, list) or any(
        not isinstance(item, Mapping)
        or set(item) != {"kind", "record_id"}
        or type(item.get("kind")) is not str
        or type(item.get("record_id")) is not str
        for item in raw
    ):
        raise SpreadTimeCorrectionError(
            "correction core semantic inventory is malformed"
        )
    return tuple((item["kind"], item["record_id"]) for item in raw)


def _bound_semantic_row_sha256(
    binding: Mapping[str, Any],
) -> tuple[str, ...]:
    raw = binding.get("semantic_row_sha256")
    if (
        not isinstance(raw, list)
        or any(
            type(item) is not str
            or len(item) != 64
            or any(character not in "0123456789abcdef" for character in item)
            for item in raw
        )
    ):
        raise SpreadTimeCorrectionError(
            "correction core semantic row digest inventory is malformed"
        )
    return tuple(raw)


@dataclass(frozen=True, slots=True)
class _DynamicActionExpectation:
    event_payload: Mapping[str, Any]
    operation_result: Mapping[str, Any]
    semantic_rows: tuple[Mapping[str, Any], ...]


def _require_exact_bound_rows_and_result(
    *,
    ordinal: int,
    binding: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    result: Mapping[str, Any],
    dynamic_expectation: _DynamicActionExpectation | None,
) -> None:
    """Check full semantic rows and result without consulting StateWriter."""

    if ordinal in {5, 6}:
        if dynamic_expectation is None:
            raise SpreadTimeCorrectionError(
                "replay invalidation lacks its pre-mutation pure projection"
            )
        expected_row_sha256 = tuple(
            _row_sha256(row) for row in dynamic_expectation.semantic_rows
        )
        expected_result = dict(dynamic_expectation.operation_result)
    else:
        expected_row_sha256 = _bound_semantic_row_sha256(binding)
        raw_result = binding.get("operation_result")
        if not isinstance(raw_result, Mapping):
            raise SpreadTimeCorrectionError(
                "correction core operation result is malformed"
            )
        expected_result = dict(raw_result)
    if tuple(_row_sha256(row) for row in rows) != expected_row_sha256:
        raise SpreadTimeCorrectionError(
            "replayed semantic row bytes differ from the independent projection"
        )
    if dict(result) != expected_result:
        raise SpreadTimeCorrectionError(
            "replayed operation result differs from the independent projection"
        )


def _derive_dynamic_action_expectation(
    writer: StateWriter,
    material: SpreadTimeCorrectionMaterial,
    *,
    ordinal: int,
) -> _DynamicActionExpectation | None:
    """Purely project cursor-bound event 5/6 rows before Writer mutation."""

    if ordinal not in {5, 6}:
        return None
    obligation_id = REPLAY_OBLIGATION_IDS[ordinal - 5]
    authority = material.family_authorities[obligation_id]
    with writer.open_stable_index() as (control, index):
        mission_id = _governing_mission_id(control)
        try:
            plan = build_satisfaction_invalidation_plan(
                index,
                mission_id=mission_id,
                obligation_id=obligation_id,
            )
            manifest = (
                replay_satisfaction_invalidation_manifest_from_mapping(
                    plan["audit_manifest"]
                )
            )
            audit_manifest_hash = plan["audit_manifest_sha256"]
            records, _constraints, result = prepare_satisfaction_invalidation(
                index,
                mission_id=mission_id,
                obligation_id=obligation_id,
                manifest=manifest,
                audit_manifest_hash=audit_manifest_hash,
            )
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            raise SpreadTimeCorrectionError(
                "dynamic replay invalidation cannot be projected exactly"
            ) from exc
    if len(records) != 1:
        raise SpreadTimeCorrectionError(
            "dynamic replay invalidation row inventory changed shape"
        )
    family_row = {
        "kind": "historical-family-authority",
        "record_id": authority.identity,
        "subject": f"ReplayObligation:{obligation_id}",
        "status": "accepted",
        "fingerprint": authority.identity.removeprefix(
            "historical-family-authority:"
        ),
        "payload": authority.to_identity_payload(),
        "event_stream": None,
        "event_sequence": None,
    }
    exact_result = {
        **dict(result),
        "historical_family_authority_id": authority.identity,
    }
    event_payload = {
        "audit_manifest_hash": audit_manifest_hash,
        "evidence": [],
        "historical_family_authority": authority.to_identity_payload(),
        "obligation_id": obligation_id,
        "satisfaction_record_id": manifest.satisfaction_record_id,
    }
    return _DynamicActionExpectation(
        event_payload=event_payload,
        operation_result=exact_result,
        semantic_rows=(_record_mapping(records[0]), family_row),
    )


def _require_action_specific_binding(
    core: CorrectionPlanCore,
    ordinal: int,
    event: Mapping[str, Any],
    material: SpreadTimeCorrectionMaterial,
    dynamic_expectation: _DynamicActionExpectation | None = None,
) -> None:
    """Cross-check one Writer event against the independently composed intent."""

    action = core.events[ordinal - 1]
    binding = action.binding
    control = event.get("control")
    expected_control_sha256 = binding.get("control_projection_sha256")
    if (
        not isinstance(control, Mapping)
        or type(expected_control_sha256) is not str
        or sha256(canonical_bytes(dict(control))).hexdigest()
        != expected_control_sha256
    ):
        raise SpreadTimeCorrectionError(
            "replayed event control differs from the independent core projection"
        )
    rows = _semantic_rows(event)
    expected_count = binding.get("semantic_record_count")
    identities = _semantic_inventory(rows)
    if (
        event.get("event_kind") != action.event_kind
        or event.get("operation_id") != action.operation_id
        or event.get("subject") != action.subject
        or expected_count != len(rows)
        or len(set(identities)) != len(identities)
    ):
        raise SpreadTimeCorrectionError(
            "replayed event semantic inventory differs from its core binding"
        )
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        raise SpreadTimeCorrectionError("replayed event payload is malformed")
    result = _operation_result(event)
    operation_fingerprint = canonical_digest(
        domain="operation",
        payload={
            "event_kind": action.event_kind,
            "payload": dict(payload),
        },
    )
    expected_operation_row = {
        "kind": "operation",
        "record_id": action.operation_id,
        "subject": action.subject,
        "status": "success",
        "fingerprint": operation_fingerprint,
        "payload": {
            "event_kind": action.event_kind,
            "result": dict(result),
        },
        "event_stream": None,
        "event_sequence": None,
    }
    if dict(event["index_records"][0]) != expected_operation_row:
        raise SpreadTimeCorrectionError(
            "replayed event operation row is not exact"
        )
    _require_exact_bound_rows_and_result(
        ordinal=ordinal,
        binding=binding,
        rows=rows,
        result=result,
        dynamic_expectation=dynamic_expectation,
    )
    if ordinal == 1:
        migration_payload = {
            "boundary": "active_stable",
            "holdout_delta": 0,
            "new_manifest_digest": binding["new_manifest_digest"],
            "old_manifest_digest": binding["old_manifest_digest"],
            "reason": binding["reason"],
            "replacements": binding["replacement_rows"],
            "schema": "authority_manifest_migration.v1",
            "scientific_claim": "none",
            "trial_delta": 0,
        }
        evidence_manifests: list[dict[str, Any]] = []
        observed_evidence: set[str] = set()
        for replacement in binding["replacement_rows"]:
            document = material.prospective_documents[replacement["path"]]
            identity = sha256(document).hexdigest()
            if identity in observed_evidence:
                continue
            observed_evidence.add(identity)
            evidence_manifests.append(
                {
                    "relative_path": f"sha256/{identity[:2]}/{identity}",
                    "sha256": identity,
                    "size_bytes": len(document),
                }
            )
        expected_payload = {
            **migration_payload,
            "evidence": evidence_manifests,
        }
        expected_inventory = _bound_semantic_inventory(binding)
        if (
            dict(payload) != expected_payload
            or identities != expected_inventory
            or rows[0].get("payload") != migration_payload
            or result.get("migration_id") != expected_inventory[0][1]
            or result.get("new_manifest_digest")
            != binding["new_manifest_digest"]
        ):
            raise SpreadTimeCorrectionError(
                "authority migration exact binding differs from the core"
            )
    elif ordinal == 2:
        activation_payload = {
            "audit_artifact_hash": binding["audit_artifact_hash"],
            "authority_manifest_digest": binding[
                "authority_manifest_digest"
            ],
            "protocol": binding["protocol"],
            "schema": "research_protocol_activation.v1",
            "validator_id": binding["validator_id"],
        }
        expected_payload = {**activation_payload, "evidence": []}
        expected_inventory = _bound_semantic_inventory(binding)
        if (
            dict(payload) != expected_payload
            or identities != expected_inventory
            or result.get("activation_record_id") != expected_inventory[0][1]
            or result.get("protocol") != binding["protocol"]
            or result.get("validator_id") != binding["validator_id"]
        ):
            raise SpreadTimeCorrectionError(
                "protocol activation exact binding differs from the core"
            )
    elif ordinal == 3:
        normalized = tuple(
            sorted(
                material.invalidation_inventory.invalidations,
                key=lambda item: item.completion_record_id,
            )
        )
        expected_payload = {
            "evidence": [],
            "invalidations": [item.to_identity_payload() for item in normalized]
        }
        expected_inventory = _bound_semantic_inventory(binding)
        expected_result_inventory = [
            {
                "completion_record_id": item.completion_record_id,
                "invalidation_record_id": item.identity,
            }
            for item in normalized
        ]
        if (
            dict(payload) != expected_payload
            or identities != expected_inventory
            or result.get("invalidations") != expected_result_inventory
        ):
            raise SpreadTimeCorrectionError(
                "completion invalidation exact binding differs from baseline derivation"
            )
    elif ordinal == 4:
        if material.adjudication_plan is None:
            raise SpreadTimeCorrectionError("baseline adjudication plan is absent")
        request_manifest = (
            material.adjudication_plan.to_request_manifest_payload().get(
                "requests"
            )
        )
        expected_inventory = _bound_semantic_inventory(binding)
        expected_by_kind = {
            kind: [record_id for row_kind, record_id in expected_inventory if row_kind == kind]
            for kind in {
                "historical-scientific-adjudication",
                "historical-replay-obligation",
                "historical-replay-priority-escalation",
            }
        }
        if (
            dict(payload)
            != {
                "audit_artifact_hash": binding["audit_artifact_hash"],
                "evidence": [],
                "requests": request_manifest,
            }
            or identities != expected_inventory
            or result.get("adjudication_record_ids")
            != expected_by_kind["historical-scientific-adjudication"]
            or result.get("replay_obligation_ids")
            != expected_by_kind["historical-replay-obligation"]
            or result.get("reused_replay_obligation_ids")
            != sorted(REPLAY_OBLIGATION_IDS)
            or result.get("replay_priority_escalation_ids")
            != sorted(
                expected_by_kind[
                    "historical-replay-priority-escalation"
                ]
            )
        ):
            raise SpreadTimeCorrectionError(
                "readjudication exact 26+23+2 binding differs from the core"
            )
    elif ordinal in {5, 6}:
        if dynamic_expectation is None:
            raise SpreadTimeCorrectionError(
                "replay invalidation lacks its pre-mutation pure projection"
            )
        obligation_id = binding["obligation_id"]
        authority_id = binding["historical_family_authority_id"]
        authority = material.family_authorities[obligation_id]
        by_kind = {row["kind"]: row for row in rows}
        invalidation_row = by_kind.get(
            "historical-replay-satisfaction-invalidation"
        )
        family_row = by_kind.get("historical-family-authority")
        invalidation_payload = (
            None
            if not isinstance(invalidation_row, Mapping)
            else invalidation_row.get("payload")
        )
        raw_manifest = (
            None
            if not isinstance(invalidation_payload, Mapping)
            else invalidation_payload.get("audit_manifest")
        )
        try:
            manifest = replay_satisfaction_invalidation_manifest_from_mapping(
                raw_manifest
            )
        except (TypeError, ValueError) as exc:
            raise SpreadTimeCorrectionError(
                "replay invalidation typed manifest is malformed"
            ) from exc
        manifest_hash = sha256(
            canonical_bytes(manifest.to_identity_payload())
        ).hexdigest()
        expected_payload = dict(dynamic_expectation.event_payload)
        expected_inventory = (
            (
                "historical-replay-satisfaction-invalidation",
                manifest.identity,
            ),
            ("historical-family-authority", authority_id),
        )
        if (
            tuple(kind for kind, _record_id in identities)
            != tuple(binding["semantic_record_kinds"])
            or identities != expected_inventory
            or dict(payload) != expected_payload
            or tuple(_row_sha256(row) for row in rows)
            != tuple(
                _row_sha256(row)
                for row in dynamic_expectation.semantic_rows
            )
            or sorted(result) != sorted(binding["operation_result_fields"])
            or dict(result) != dict(dynamic_expectation.operation_result)
            or invalidation_payload.get("audit_manifest_hash")
            != manifest_hash
            or invalidation_payload.get("obligation_id") != obligation_id
            or invalidation_payload.get("prior_satisfaction_record_id")
            != binding["accepted_satisfaction_record_id"]
            or not isinstance(family_row, Mapping)
            or family_row.get("payload") != authority.to_identity_payload()
            or result.get("audit_manifest_hash") != manifest_hash
            or result.get("invalidated_satisfaction_record_id")
            != binding["accepted_satisfaction_record_id"]
            or result.get("replay_obligation_id") != obligation_id
            or result.get("historical_family_authority_id") != authority_id
        ):
            raise SpreadTimeCorrectionError(
                "replay invalidation exact typed binding differs from the core"
            )
    elif ordinal == 7:
        latch = HistoricalCostSemanticsLatch.from_audit_manifest(
            material.cost_manifest
        )
        expected_inventory = _bound_semantic_inventory(binding)
        if (
            dict(payload)
            != {
                "audit_manifest_hash": material.cost_manifest.artifact_hash,
                "audit_manifest_identity": material.cost_manifest.identity,
                "audit_report_hash": material.cost_manifest.audit_artifact_hash,
                "evidence": [],
            }
            or identities != expected_inventory
            or rows[0].get("payload") != latch.to_payload()
            or any(
                not isinstance(row.get("payload"), Mapping)
                for row in rows[1:]
            )
            or any(
                row["payload"].get("latch_record_id")
                != binding["latch_record_id"]
                for row in rows[1:]
            )
            or result.get("audit_manifest_hash")
            != material.cost_manifest.artifact_hash
            or result.get("latch_record_id") != binding["latch_record_id"]
        ):
            raise SpreadTimeCorrectionError(
                "historical cost latch exact 1+501 binding differs from the core"
            )
    else:  # pragma: no cover - core construction fixes seven actions.
        raise SpreadTimeCorrectionError("foreign correction action ordinal")


def _perform_correction_action(
    writer: StateWriter,
    material: SpreadTimeCorrectionMaterial,
    *,
    ordinal: int,
) -> Any:
    """Execute the sole fixed seven-action registry without clock policy."""

    core = material.core
    try:
        event = core.events[ordinal - 1]
    except IndexError as exc:
        raise SpreadTimeCorrectionError("foreign correction action ordinal") from exc
    if ordinal == 1:
        replacements = {
            relative: content
            for relative, content in material.prospective_documents.items()
            if content != material.predecessor_documents[relative]
        }
        return writer.migrate_authority(
            replacements=replacements,
            reason=AUTHORITY_REASON,
            operation_id=event.operation_id,
            allow_active_stable_boundary=True,
        )
    if ordinal == 2:
        return writer.activate_research_protocol(
            activation=ResearchProtocolActivation(
                protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
                validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
                authority_manifest_digest=(
                    core.prospective_authority_manifest_digest
                ),
                audit_artifact_hash=sha256(material.report_bytes).hexdigest(),
            ),
            operation_id=event.operation_id,
            allow_active_stable_boundary=True,
        )
    if ordinal == 3:
        return writer.record_historical_scientific_validity_invalidations(
            invalidations=material.invalidation_inventory.invalidations,
            operation_id=event.operation_id,
        )
    if ordinal == 4:
        if material.adjudication_plan is None:
            raise SpreadTimeCorrectionError("baseline adjudication plan is absent")
        return writer.record_historical_scientific_adjudications(
            requests=material.adjudication_plan.requests,
            audit_artifact_hash=sha256(material.report_bytes).hexdigest(),
            operation_id=event.operation_id,
        )
    if ordinal in {5, 6}:
        return _replay_invalidation(
            writer,
            material=material,
            obligation_id=REPLAY_OBLIGATION_IDS[ordinal - 5],
            operation_id=event.operation_id,
        )
    if ordinal == 7:
        return writer.record_historical_cost_semantics_latch(
            manifest_artifact_hash=material.cost_manifest.artifact_hash,
            operation_id=event.operation_id,
        )
    raise SpreadTimeCorrectionError("foreign correction action ordinal")


def _execute_shadow_action(
    writer: StateWriter,
    material: SpreadTimeCorrectionMaterial,
    *,
    ordinal: int,
    occurred_at_utc: str,
) -> Any:
    return _invoke_replay_transition(
        writer,
        occurred_at_utc,
        lambda: _perform_correction_action(
            writer,
            material,
            ordinal=ordinal,
        ),
    )


def _execute_actual_action(
    writer: StateWriter,
    material: SpreadTimeCorrectionMaterial,
    *,
    ordinal: int,
    occurred_at_utc: str,
) -> Any:
    """Execute the fixed registry with the one just-observed canonical clock."""

    return _invoke_replay_transition(
        writer,
        occurred_at_utc,
        lambda: _perform_correction_action(
            writer,
            material,
            ordinal=ordinal,
        ),
    )


_EXACT_JOURNAL_EVENT_FIELDS = {
    "control",
    "event_id",
    "event_kind",
    "index_projection_digest",
    "index_record_count",
    "index_records",
    "journal_offset",
    "occurred_at_utc",
    "operation_id",
    "payload",
    "previous_event_id",
    "schema",
    "sequence",
    "subject",
}
_EXACT_INDEX_ROW_FIELDS = {
    "event_sequence",
    "event_stream",
    "fingerprint",
    "kind",
    "payload",
    "record_id",
    "status",
    "subject",
}


@dataclass(frozen=True, slots=True)
class _IndependentEventCursor:
    journal_offset: int
    previous_event_id: str
    index_record_count: int
    index_projection_digest: str


def _index_projection_member_digest(row: Mapping[str, Any]) -> str:
    if set(row) != _EXACT_INDEX_ROW_FIELDS:
        raise SpreadTimeCorrectionError(
            "correction event index row fields are not exact"
        )
    return canonical_digest(
        domain="index-projection-member",
        payload={name: row.get(name) for name in sorted(_EXACT_INDEX_ROW_FIELDS)},
    )


def _require_independent_event_envelope(
    core: CorrectionPlanCore,
    ordinal: int,
    event: Mapping[str, Any],
    cursor: _IndependentEventCursor,
    *,
    occurred_at_utc: str,
) -> _IndependentEventCursor:
    """Verify the preappend envelope without using Writer or Journal output."""

    if set(event) != _EXACT_JOURNAL_EVENT_FIELDS:
        raise SpreadTimeCorrectionError(
            "correction event envelope fields are not exact"
        )
    action = core.events[ordinal - 1]
    rows = event.get("index_records")
    control = event.get("control")
    if (
        event.get("schema") != "journal_event"
        or event.get("event_kind") != action.event_kind
        or event.get("operation_id") != action.operation_id
        or event.get("subject") != action.subject
        or event.get("sequence") != core.baseline.journal_sequence + ordinal
        or event.get("previous_event_id") != cursor.previous_event_id
        or event.get("journal_offset") != cursor.journal_offset
        or event.get("occurred_at_utc") != occurred_at_utc
        or not isinstance(control, Mapping)
        or not isinstance(rows, list)
        or not rows
        or any(not isinstance(row, Mapping) for row in rows)
    ):
        raise SpreadTimeCorrectionError(
            "correction event envelope differs from its independent cursor"
        )
    expected_control_sha256 = action.binding.get(
        "control_projection_sha256"
    )
    if (
        type(expected_control_sha256) is not str
        or sha256(canonical_bytes(dict(control))).hexdigest()
        != expected_control_sha256
    ):
        raise SpreadTimeCorrectionError(
            "correction event control projection is not core-bound"
        )
    projection_digest = cursor.index_projection_digest
    for row in rows:
        projection_digest = canonical_digest(
            domain="index-projection-chain",
            payload={
                "member": _index_projection_member_digest(row),
                "previous": projection_digest,
            },
        )
    record_count = cursor.index_record_count + 1 + len(rows)
    event_id = canonical_digest(
        domain="journal-event",
        payload={key: value for key, value in event.items() if key != "event_id"},
    )
    try:
        framed_byte_count = len(canonical_bytes(dict(event))) + 1
    except (TypeError, ValueError) as exc:
        raise SpreadTimeCorrectionError(
            "correction event envelope is not canonical"
        ) from exc
    if (
        event.get("index_record_count") != record_count
        or event.get("index_projection_digest") != projection_digest
        or event.get("event_id") != event_id
        or framed_byte_count > DurableJournal.MAX_EVENT_BYTES
    ):
        raise SpreadTimeCorrectionError(
            "correction event digest or projection chain is not exact"
        )
    return _IndependentEventCursor(
        journal_offset=cursor.journal_offset + framed_byte_count,
        previous_event_id=event_id,
        index_record_count=record_count,
        index_projection_digest=projection_digest,
    )


@dataclass(slots=True)
class _CorrectionReplaySession:
    writer: StateWriter
    material: SpreadTimeCorrectionMaterial
    replay_evidence: _ShadowEvidenceStore
    baseline_sequence: int
    receipts: list[CorrectionEventReceiptBinding]
    verified_events: list[Mapping[str, Any]]
    independent_cursor: _IndependentEventCursor
    pending_expected: Mapping[str, Any] | None = None
    pending_independent_cursor: _IndependentEventCursor | None = None
    baseline_reconstruction_count: int = 1
    envelope_candidate_enumeration_count: int = 0

    def preview_next(self, occurred_at_utc: str) -> Mapping[str, Any]:
        if (
            self.pending_expected is not None
            or self.pending_independent_cursor is not None
        ):
            raise SpreadTimeCorrectionError(
                "correction expected event is already pending"
            )
        ordinal = len(self.verified_events) + 1
        if ordinal > self.material.core.event_count:
            raise SpreadTimeCorrectionError("correction suffix exceeds the core")
        if type(occurred_at_utc) is not str or not occurred_at_utc:
            raise SpreadTimeCorrectionError(
                "correction expected event clock is malformed"
            )
        dynamic_expectation = _derive_dynamic_action_expectation(
            self.writer,
            self.material,
            ordinal=ordinal,
        )
        _execute_shadow_action(
            self.writer,
            self.material,
            ordinal=ordinal,
            occurred_at_utc=occurred_at_utc,
        )
        head, expected = self.writer.journal.tail()
        if (
            expected is None
            or head.sequence
            != self.material.core.baseline.journal_sequence + ordinal
            or expected.get("occurred_at_utc") != occurred_at_utc
        ):
            raise SpreadTimeCorrectionError(
                "shadow correction action did not expose its exact next event"
            )
        _require_action_specific_binding(
            self.material.core,
            ordinal,
            expected,
            self.material,
            dynamic_expectation,
        )
        self.pending_independent_cursor = _require_independent_event_envelope(
            self.material.core,
            ordinal,
            expected,
            self.independent_cursor,
            occurred_at_utc=occurred_at_utc,
        )
        self.pending_expected = dict(expected)
        return self.pending_expected

    def accept_next(self, actual: Mapping[str, Any]) -> None:
        expected = self.pending_expected
        pending_cursor = self.pending_independent_cursor
        if expected is None or pending_cursor is None:
            raise SpreadTimeCorrectionError(
                "actual correction event lacks a shadow expectation"
            )
        if canonical_bytes(dict(expected)) != canonical_bytes(dict(actual)):
            raise SpreadTimeCorrectionError(
                "actual correction event bytes differ from deterministic replay"
            )
        self.receipts.append(_receipt_binding(expected))
        self.verified_events.append(dict(actual))
        self.independent_cursor = pending_cursor
        self.pending_expected = None
        self.pending_independent_cursor = None

    def verify_next(self, actual: Mapping[str, Any]) -> None:
        occurred_at_utc = actual.get("occurred_at_utc")
        if type(occurred_at_utc) is not str:
            raise SpreadTimeCorrectionError("actual correction event is malformed")
        self.preview_next(occurred_at_utc)
        self.accept_next(actual)

    def verify_prefix(self, suffix: Sequence[Mapping[str, Any]]) -> None:
        if (
            self.verified_events
            or self.pending_expected is not None
            or self.pending_independent_cursor is not None
        ):
            raise SpreadTimeCorrectionError("correction prefix was replayed twice")
        for event in suffix:
            self.verify_next(event)


@contextmanager
def _open_correction_replay_session(
    durable_core: CorrectionPlanCore,
) -> Iterator[_CorrectionReplaySession]:
    """Rebuild the Git baseline once and independently rederive the exact core."""

    _require_current_reviewed_execution_closure(durable_core)
    baseline_control_bytes = _git_blob("HEAD", "state/control.json")
    baseline_control = _read_control_bytes(baseline_control_bytes)
    paths = _authority_paths(baseline_control)
    _predecessor_ref, predecessor_documents = _predecessor_authority_documents(
        baseline_control,
        paths,
    )
    prospective_documents = {
        relative: _git_blob("HEAD", relative) for relative in paths
    }
    prospective_digest = _manifest_digest_from_bytes(prospective_documents)
    authority_files = tuple(
        AuthorityFileBinding(
            path=relative,
            predecessor_sha256=sha256(predecessor_documents[relative]).hexdigest(),
            prospective_sha256=sha256(prospective_documents[relative]).hexdigest(),
        )
        for relative in paths
    )
    report_bytes = (ROOT / AUDIT_REPORT_PATH).read_bytes()
    report_bytes.decode("ascii")
    report_hash = sha256(report_bytes).hexdigest()
    checkpoint = _reviewed_code_checkpoint()
    journal_path, journal_manifest_bytes = _journal_path()

    with TemporaryDirectory(prefix="axiom-correction-prefix-replay-") as temporary:
        shadow_root = Path(temporary).resolve()
        (shadow_root / "state").mkdir(parents=True)
        (shadow_root / "local").mkdir(parents=True)
        (shadow_root / "state" / "control.json").write_bytes(
            baseline_control_bytes
        )
        if journal_path.startswith("records/journal/"):
            _materialize_git_prefix("HEAD", "records/journal", shadow_root)
        else:
            target = shadow_root / journal_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_git_blob("HEAD", journal_path))
        for relative, content in predecessor_documents.items():
            target = shadow_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        for _spec, relative in _FAMILY_SPECS.values():
            target = shadow_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
        shadow = StateWriter(
            shadow_root,
            engineering_fixture=True,
            foundation_root=shadow_root,
            validation_registry=_registry(),
        )
        recovery = shadow.recover()
        if (
            recovery.get("journal_sequence")
            != baseline_control["heads"]["journal"]["sequence"]
            or recovery.get("index_rebuilt") is not True
        ):
            raise SpreadTimeCorrectionError(
                "baseline Journal projection was not reconstructed exactly once"
            )
        stable = shadow.require_stable_head()
        evidence = _ReadOnlyEvidenceOverlay(
            EvidenceStore(ROOT / "local" / "evidence"),
            {report_hash: report_bytes},
        )
        with shadow.open_stable_index() as (_control, index):
            derived = _derive_correction_inputs(
                index,
                evidence,
                report_bytes=report_bytes,
                control=baseline_control,
            )
        baseline = _baseline(
            baseline_control,
            journal_path=journal_path,
            journal_manifest_bytes=journal_manifest_bytes,
            stable=stable,
            checkpoint=checkpoint,
        )
        expected_core = _compose_correction_core(
            baseline_control=baseline_control,
            baseline=baseline,
            prospective_digest=prospective_digest,
            authority_files=authority_files,
            checkpoint=checkpoint,
            report_bytes=report_bytes,
            derived=derived,
        )
        if expected_core.core_bytes != durable_core.core_bytes:
            raise SpreadTimeCorrectionError(
                "durable correction core differs from independent baseline derivation"
            )
        durable_evidence = EvidenceStore(ROOT / "local" / "evidence")
        for identity in derived.direct_evidence_hashes:
            document = durable_evidence.read_verified(identity)
            target = (
                shadow_root
                / "local"
                / "evidence"
                / "sha256"
                / identity[:2]
                / identity
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(document)
        replay_evidence = _ShadowEvidenceStore(
            durable_evidence,
            {
                report_hash: report_bytes,
                derived.cost_manifest.artifact_hash: canonical_bytes(
                    derived.cost_manifest.to_payload()
                ),
            },
        )
        shadow.evidence = replay_evidence  # type: ignore[assignment]
        material = SpreadTimeCorrectionMaterial(
            core=expected_core,
            preview_receipts=(),
            preview_events=(),
            preview_dynamic_expectations=(),
            report_bytes=report_bytes,
            invalidation_inventory=derived.invalidations,
            adjudication_plan=derived.adjudications,
            cost_manifest=derived.cost_manifest,
            family_authorities=derived.family_authorities,
            predecessor_documents=predecessor_documents,
            prospective_documents=prospective_documents,
            direct_evidence_hashes=derived.direct_evidence_hashes,
        )
        yield _CorrectionReplaySession(
            writer=shadow,
            material=material,
            replay_evidence=replay_evidence,
            baseline_sequence=baseline.journal_sequence,
            receipts=[],
            verified_events=[],
            independent_cursor=_IndependentEventCursor(
                journal_offset=(
                    baseline.journal_start_offset
                    + baseline.journal_size_bytes
                ),
                previous_event_id=baseline.journal_event_id,
                index_record_count=baseline.index_record_count,
                index_projection_digest=baseline.index_projection_digest,
            ),
        )


def _durable_core_from_suffix(
    journal_events: Sequence[Mapping[str, Any]],
    *,
    baseline_sequence: int,
    evidence: EvidenceStore,
) -> CorrectionPlanCore | None:
    if len(journal_events) <= baseline_sequence:
        return None
    operation_id = journal_events[baseline_sequence].get("operation_id")
    if type(operation_id) is not str:
        raise SpreadTimeCorrectionError(
            "first correction suffix event lacks an operation id"
        )
    try:
        core_hash = CorrectionReceiptEnvelope.core_hash_from_operation_id(
            operation_id,
            namespace=OPERATION_NAMESPACE,
        )
        document = evidence.read_verified(core_hash)
        core = CorrectionPlanCore.from_bytes(
            document,
            expected_core_hash=core_hash,
        )
    except (ContentAddressedCorrectionError, OSError, RuntimeError, ValueError) as exc:
        raise SpreadTimeCorrectionError(
            "interrupted correction suffix lacks its exact durable core"
        ) from exc
    if core.core_hash != core_hash:
        raise SpreadTimeCorrectionError(
            "durable correction core hash differs from its operation id"
        )
    correction_suffix_from_journal(core, journal_events)
    return core


def read_only_plan() -> dict[str, Any]:
    """Rebuild the exact seven-event plan without repository mutation."""

    material = _build_material()
    writer = _writer()
    evidence_ready: dict[str, bool] = {}
    required = {
        "audit_report": sha256(material.report_bytes).hexdigest(),
        "cost_manifest": material.cost_manifest.artifact_hash,
        "correction_plan_core": material.core.core_hash,
    }
    for role, identity in required.items():
        try:
            evidence_ready[role] = writer.evidence.read_verified(identity) == (
                material.report_bytes
                if role == "audit_report"
                else canonical_bytes(material.cost_manifest.to_payload())
                if role == "cost_manifest"
                else material.core.core_bytes
            )
        except (FileNotFoundError, OSError, RuntimeError):
            evidence_ready[role] = False
    if material.adjudication_plan is None:  # pragma: no cover - builder invariant.
        raise SpreadTimeCorrectionError("read-only plan lost its adjudication plan")
    return {
        "apply_mutation_performed": False,
        "authority_replacement_paths": [
            item.path for item in material.core.authority_replacements
        ],
        "event_inventory": [item.to_payload() for item in material.core.events],
        "evidence_materialized": evidence_ready,
        "final_envelope_artifact_hash": None,
        "final_envelope_exists": False,
        "historical_cost_completion_count": 501,
        "historical_invalidation_count": len(
            material.invalidation_inventory.invalidations
        ),
        "historical_readjudication_count": len(
            material.adjudication_plan.requests
        ),
        "expected_replay_priority_escalation_ids": material.core.event(
            "historical-readjudication"
        ).binding["replay_priority_escalation_ids"],
        "plan_core": material.core.to_payload(),
        "plan_core_hash": material.core.core_hash,
        "replay_satisfaction_invalidation_count": 2,
        "synthetic_preflight_event_byte_counts": [
            receipt.canonical_event_byte_count
            for receipt in material.preview_receipts
        ],
        "schema": "spread_time_semantics_correction_read_only_core.v2",
    }


def _current_writer_for_plan(
    plan: CorrectionPlanCore | CorrectionReceiptEnvelope,
    *,
    require_apply_api: bool = False,
) -> Iterator[StateWriter]:
    current = _current_control()
    digest = current["authority"]["manifest_digest"]
    if digest == plan.prospective_authority_manifest_digest:
        @contextmanager
        def prospective() -> Iterator[StateWriter]:
            yield _writer(require_apply_api=require_apply_api)
        return prospective()
    if digest != plan.baseline.authority_manifest_digest:
        raise SpreadTimeCorrectionError(
            "control authority is outside the correction plan boundary"
        )
    documents = {
        item.path: _git_blob("origin/main", item.path)
        for item in plan.authority_files
    }
    if _manifest_digest_from_bytes(documents) != digest:
        documents = {
            item.path: _git_blob("HEAD", item.path)
            for item in plan.authority_files
        }
    @contextmanager
    def predecessor() -> Iterator[StateWriter]:
        with _predecessor_foundation(
            documents,
            expected_digest=plan.baseline.authority_manifest_digest,
        ) as foundation_root:
            yield _writer(
                foundation_root=foundation_root,
                require_apply_api=require_apply_api,
            )
    return predecessor()


def _assert_prefix(
    plan: CorrectionPlanCore | CorrectionReceiptEnvelope,
    *,
    expected_count: int,
) -> None:
    with _current_writer_for_plan(plan) as writer:
        writer.require_stable_head()
        suffix = correction_suffix_from_journal(plan, writer.journal.read_all())
    if len(suffix) != expected_count:
        raise SpreadTimeCorrectionError(
            "StateWriter transition did not advance the exact plan prefix"
        )


def _materialize_apply_evidence(
    evidence: EvidenceStore,
    material: SpreadTimeCorrectionMaterial,
    replay_documents: Mapping[str, bytes],
) -> None:
    artifacts = [
        (material.report_bytes, sha256(material.report_bytes).hexdigest()),
        (
            canonical_bytes(material.cost_manifest.to_payload()),
            material.cost_manifest.artifact_hash,
        ),
        (material.core.core_bytes, material.core.core_hash),
    ]
    for identity, document in replay_documents.items():
        if type(identity) is not str or type(document) is not bytes:
            raise SpreadTimeCorrectionError(
                "replay evidence inventory is malformed"
            )
        artifacts.append((document, identity))
    exact: dict[str, bytes] = {}
    for document, expected in artifacts:
        if sha256(document).hexdigest() != expected:
            raise SpreadTimeCorrectionError(
                "replay evidence document differs from its exact identity"
            )
        prior = exact.setdefault(expected, document)
        if prior != document:
            raise SpreadTimeCorrectionError("replay evidence identity collided")
    for expected, document in exact.items():
        artifact = evidence.finalize(document)
        try:
            readback = evidence.read_verified(expected)
        except (OSError, RuntimeError, ValueError) as exc:
            raise SpreadTimeCorrectionError(
                "apply evidence cannot be read back before recovery"
            ) from exc
        if artifact.sha256 != expected or readback != document:
            raise SpreadTimeCorrectionError(
                "apply evidence materialization changed an exact replay hash"
            )


def _materialize_final_envelope(
    writer: StateWriter,
    *,
    core: CorrectionPlanCore,
    receipts: Sequence[CorrectionEventReceiptBinding],
    suffix: Sequence[Mapping[str, Any]],
) -> CorrectionReceiptEnvelope:
    if len(receipts) != core.event_count or len(suffix) != core.event_count:
        raise SpreadTimeCorrectionError(
            "final correction envelope requires the complete verified suffix"
        )
    plan = CorrectionReceiptEnvelope(
        core=core,
        event_receipts=tuple(receipts),
    )
    require_exact_correction_receipts(plan, suffix)
    try:
        stored = writer.evidence.read_verified(plan.artifact_hash)
    except FileNotFoundError:
        artifact = writer.evidence.finalize(plan.artifact_bytes)
        if artifact.sha256 != plan.artifact_hash:
            raise SpreadTimeCorrectionError(
                "final correction envelope materialization changed identity"
            )
    except (OSError, RuntimeError, ValueError) as exc:
        raise SpreadTimeCorrectionError(
            "computed final correction envelope is unreadable"
        ) from exc
    else:
        rebuilt = CorrectionReceiptEnvelope.from_bytes(
            stored,
            expected_artifact_hash=plan.artifact_hash,
            expected_core_hash=core.core_hash,
        )
        if rebuilt.artifact_bytes != plan.artifact_bytes:
            raise SpreadTimeCorrectionError(
                "stored final correction envelope differs from exact replay"
            )
    return plan


def _replay_invalidation(
    writer: StateWriter,
    *,
    material: SpreadTimeCorrectionMaterial,
    obligation_id: str,
    operation_id: str,
) -> Any:
    plan = writer.plan_historical_replay_satisfaction_invalidation(
        obligation_id=obligation_id
    )
    if (
        not isinstance(plan, Mapping)
        or plan.get("schema") != "replay_satisfaction_invalidation_plan.v1"
        or plan.get("operation")
        != "invalidate_historical_replay_satisfaction"
        or not isinstance(plan.get("audit_manifest"), Mapping)
        or plan["audit_manifest"].get("obligation_id") != obligation_id
        or plan["audit_manifest"].get("satisfaction_record_id")
        != REPLAY_SATISFACTION_IDS[obligation_id]
    ):
        raise SpreadTimeCorrectionError(
            "Writer replay invalidation plan differs from the frozen subject"
        )
    document = canonical_bytes(plan["audit_manifest"])
    expected = sha256(document).hexdigest()
    if plan.get("audit_manifest_sha256") != expected:
        raise SpreadTimeCorrectionError(
            "Writer replay invalidation manifest hash is not canonical"
        )
    artifact = writer.evidence.finalize(document)
    if artifact.sha256 != expected:
        raise SpreadTimeCorrectionError(
            "replay invalidation manifest changed during publication"
        )
    return writer.invalidate_historical_replay_satisfaction(
        obligation_id=obligation_id,
        audit_manifest_hash=artifact.sha256,
        operation_id=operation_id,
        historical_family_authority=material.family_authorities[obligation_id],
    )


def _exact_trailing_recovery_arguments(
    suffix: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not suffix:
        raise RecoveryRequired(
            "correction recovery cannot repair the unrelated baseline"
        )
    trailing = suffix[-1]
    return {
        "expected_sequence": trailing.get("sequence"),
        "expected_event_id": trailing.get("event_id"),
        "expected_operation_id": trailing.get("operation_id"),
        "expected_previous_event_id": trailing.get("previous_event_id"),
    }


def _require_exact_trailing_recovery_boundary(
    writer: StateWriter,
    suffix: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    return writer.require_exact_trailing_event_recovery_boundary(
        **_exact_trailing_recovery_arguments(suffix)
    )


def apply(*, explicit_recovery: bool = False) -> dict[str, Any]:
    """Apply only the missing exact suffix; never commit or push it."""

    _require_safe_apply_startup()
    if type(explicit_recovery) is not bool:
        raise SpreadTimeCorrectionError("explicit recovery flag must be bool")
    _writer(require_apply_api=True)
    baseline_control = _read_control_bytes(_git_blob("HEAD", "state/control.json"))
    baseline_sequence = baseline_control["heads"]["journal"]["sequence"]
    journal = _writer().journal
    journal_events = journal.read_all()
    evidence = EvidenceStore(ROOT / "local" / "evidence")
    durable_core = _durable_core_from_suffix(
        journal_events,
        baseline_sequence=baseline_sequence,
        evidence=evidence,
    )
    recovery: dict[str, Any] = {"mode": "stable_head_no_recovery"}
    core = (
        durable_core
        if durable_core is not None
        else _build_material(include_synthetic_preview=False).core
    )
    _require_current_reviewed_execution_closure(core)

    with _open_correction_replay_session(core) as replay:
        material = replay.material
        suffix = correction_suffix_from_journal(core, journal_events)
        # This full semantic replay and expected-core comparison precede every
        # possible projection recovery.  The Journal operation id cannot select
        # a forged core or bless a forged one-event-lag suffix.
        replay.verify_prefix(suffix)
        _require_current_reviewed_execution_closure(core)
        # Fail before creating any durable evidence when Git, worktree, state,
        # Journal, or recovery authority is outside the reviewed boundary.
        # Recovery evidence must exist before recovery, but boundary admission
        # itself is a read-only prerequisite to that materialization.
        require_local_main_correction_boundary(
            ROOT,
            core,
            current_control=_current_control(),
            journal_events=journal_events,
            allow_one_event_projection_lag=explicit_recovery,
        )
        with _current_writer_for_plan(core) as preevidence_writer:
            try:
                preevidence_writer.require_stable_head()
            except RecoveryRequired:
                if not explicit_recovery or not suffix:
                    raise
                _require_exact_trailing_recovery_boundary(
                    preevidence_writer,
                    suffix,
                )
        _materialize_apply_evidence(
            evidence,
            material,
            replay.replay_evidence.exact_documents(),
        )
        if evidence.read_verified(core.core_hash) != core.core_bytes:
            raise SpreadTimeCorrectionError(
                "durable correction core changed before projection recovery"
            )

        with _current_writer_for_plan(core) as delivery_writer:
            delivery = require_local_main_correction_boundary(
                ROOT,
                core,
                current_control=_current_control(),
                journal_events=journal_events,
                allow_one_event_projection_lag=explicit_recovery,
            )
            try:
                delivery_writer.require_stable_head()
            except RecoveryRequired:
                if not explicit_recovery or not suffix:
                    raise
                recovery = {
                    "mode": "explicit_exact_core_prefix_recovery",
                    **delivery_writer.recover_exact_trailing_event(
                        **_exact_trailing_recovery_arguments(suffix)
                    ),
                }

        with _current_writer_for_plan(core) as delivery_writer:
            delivery_writer.require_stable_head()
            stable_events = delivery_writer.journal.read_all()
            stable_suffix = correction_suffix_from_journal(core, stable_events)
            if canonical_bytes(list(stable_suffix)) != canonical_bytes(list(suffix)):
                raise SpreadTimeCorrectionError(
                    "projection recovery changed the verified Journal suffix"
                )
            delivery = require_local_main_correction_boundary(
                ROOT,
                core,
                current_control=_current_control(),
                journal_events=stable_events,
            )
            if delivery_writer.evidence.read_verified(core.core_hash) != core.core_bytes:
                raise SpreadTimeCorrectionError(
                    "durable correction core changed before the first event"
                )

        initial_prefix = len(suffix)
        for ordinal in range(initial_prefix + 1, core.event_count + 1):
            _require_current_reviewed_execution_closure(core)
            with _current_writer_for_plan(
                core,
                require_apply_api=True,
            ) as actual_writer:
                actual_writer.require_stable_head()
                observed_utc = _observe_writer_clock_once(actual_writer)
                expected_event = replay.preview_next(observed_utc)
                _require_current_reviewed_execution_closure(core)
                actual_writer.require_stable_head()
                predecessor_head, _predecessor_event = actual_writer.journal.tail()
                expected_predecessor_id = (
                    core.baseline.journal_event_id
                    if ordinal == 1
                    else replay.verified_events[-1]["event_id"]
                )
                if (
                    predecessor_head.sequence
                    != core.baseline.journal_sequence + ordinal - 1
                    or predecessor_head.event_id != expected_predecessor_id
                ):
                    raise SpreadTimeCorrectionError(
                        "canonical head changed after shadow event preparation"
                    )
                with actual_writer.journal.expect_next_event(expected_event):
                    transition = _execute_actual_action(
                        actual_writer,
                        material,
                        ordinal=ordinal,
                        occurred_at_utc=observed_utc,
                    )
                head, actual_event = actual_writer.journal.tail()
                if (
                    actual_event is None
                    or head.sequence != core.baseline.journal_sequence + ordinal
                    or transition.reused is not False
                    or transition.revision
                    != core.baseline.control_revision + ordinal
                    or head.event_id != transition.event_id
                    or actual_event.get("occurred_at_utc") != observed_utc
                ):
                    raise SpreadTimeCorrectionError(
                        "actual Writer transition did not expose its exact event"
                    )
                if canonical_bytes(dict(expected_event)) != canonical_bytes(
                    dict(actual_event)
                ):
                    raise SpreadTimeCorrectionError(
                        "actual Writer event differs from its preappend expectation"
                    )
                replay.accept_next(actual_event)
                actual_writer.require_stable_head()

        if len(replay.verified_events) != core.event_count:
            raise SpreadTimeCorrectionError(
                "correction did not reach its complete verified suffix"
            )
        final_suffix = tuple(replay.verified_events)
        with _current_writer_for_plan(core) as final_writer:
            final_writer.require_stable_head()
            envelope = _materialize_final_envelope(
                final_writer,
                core=core,
                receipts=replay.receipts,
                suffix=final_suffix,
            )
            final_events = final_writer.journal.read_all()
            delivery = require_local_main_correction_boundary(
                ROOT,
                envelope,
                current_control=_current_control(),
                journal_events=final_events,
            )

        return {
            "already_complete": initial_prefix == core.event_count,
            "applied_event_count": core.event_count - initial_prefix,
            "baseline_reconstruction_count": (
                replay.baseline_reconstruction_count
            ),
            "envelope_candidate_enumeration_count": (
                replay.envelope_candidate_enumeration_count
            ),
            "final_envelope_artifact_hash": envelope.artifact_hash,
            "final_prefix_count": core.event_count,
            "local_main_delivery_boundary": delivery,
            "plan_core_hash": core.core_hash,
            "recovery": recovery,
            "schema": "spread_time_semantics_correction_apply_result.v2",
        }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        description=(
            "Plan or explicitly apply the exact seven-event spread/time "
            "historical correction."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply the exact missing StateWriter suffix; never commit or push",
    )
    parser.add_argument(
        "--recover",
        action="store_true",
        help=(
            "explicitly recover only one exact plan-bound trailing Journal "
            "event before resuming"
        ),
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    if arguments.recover and not arguments.apply:
        raise SystemExit("--recover requires --apply")
    result = (
        apply(explicit_recovery=arguments.recover)
        if arguments.apply
        else read_only_plan()
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
