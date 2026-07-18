"""Shadow-prove or atomically apply the complete claim-scoped diagnosis audit.

The original Study, completion, replay-satisfaction, trial, holdout, candidate,
and Decision records remain immutable.  One additive event records the complete
mismatch audit plus every correction.  Real apply requires an unpublished
local-main code checkpoint and an exact pre-audited Journal boundary.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any, Callable, TypeVar


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ORIGIN_MAIN_COMMIT = "0dded642e2ae6437b558a6fa9bd0dbf2d7947669"
EXPECTED_BASE_REVISION = 5703
EXPECTED_BASE_EVENT_ID = (
    "9f583ddf911c038b79e406234742e026de26c6e321a36d6dcd87a91b495a7d0b"
)
EXPECTED_MISSION_ID = "MIS-0006"
EXPECTED_CURRENT_DIAGNOSIS_ID = (
    "diagnosis:fca33e0b786cb4fec440ea6aee493fc8081a9852a28f7253804a5300687195d2"
)
EXPECTED_PORTFOLIO_SNAPSHOT_ID = (
    "portfolio:ee7db49e0f33f8857cb0dee70c145d343c59909d1ddb2f4bfee02c69ea0508ad"
)
EXPECTED_MISMATCH_IDS = (
    "diagnosis:18a6eabad893f6b2ed5f0e7db96c793481070fb89222df5fcb6dfe66922da515",
    "diagnosis:1a9d1f87d05b757f66e8e5a0911f93894c8cd47fc438c1eae60bfad6f805d003",
    "diagnosis:231ca89cdacb9d800f259d900568ddef512e60bf4c55c8f7422acf8260dba5b4",
    "diagnosis:2736a9976e24ca60a06c870a4c7629d5dc6119892d1ec8f2f8eb229c7d1b7301",
    "diagnosis:77601b1a26e73567017a5462b275d670847b893fbfb165b325486d34e4d26234",
    "diagnosis:a3186b65951e2268c3d6c9dfae65aa98d518667668d79c715b164c3e4be395eb",
    "diagnosis:abfbd5546a3849022bbeb311dab2c62f1e340ab7c4ad996f172bcd8a6c069fd2",
    "diagnosis:c4d7f67f43759c44f0339a1608fa1088ebce68c44c25e50ff42df5b7d9edf4c4",
    "diagnosis:c8843207121cde1acbf5493645e2a421ad0d79b35e0dfe40fa62dfbc657d2336",
    "diagnosis:d805fc2624588982305af5753da9a97c04ffde60f9190abeb7cb8e4a8daae148",
    "diagnosis:e0b51800b142c0cda80f10a0a3a8bad9d4a6dd1b6a21d79c5490d2f24e26fdf2",
    "diagnosis:f9d07817cb57e1d46c0272b7539f760486c0b3e769f09177a1dc6e84e493ee02",
    EXPECTED_CURRENT_DIAGNOSIS_ID,
    "diagnosis:fcd02eab65d53b32cbd9a2fb84d52462f7426dddb2aa9ed9571ee31c226caff0",
)
EXPECTED_STABILITY_DIAGNOSIS_ID = (
    "diagnosis:77601b1a26e73567017a5462b275d670847b893fbfb165b325486d34e4d26234"
)
EXPECTED_AFFECTED_COMPLETION_COUNT = 78
EXPECTED_AUTHORITY_MANIFEST_DIGEST = (
    "d3621aec120be6989261c219275bfda23977159bedea1c2c1ab9ca9365a22fb9"
)
EXPECTED_INITIATIVE_ID = "INI-0025"
SHADOW_OPERATION_ID = "audit-correct-claim-scoped-study-diagnoses-shadow-v1"
OPERATION_NAMESPACE = "axiom-diagnosis-correction"
PURPOSE = (
    "Apply the existing noncompensating claim-scoped diagnosis authority to "
    "the complete audited mismatch inventory without changing scientific credit."
)
class ClaimScopedCorrectionApplyError(RuntimeError):
    """The exact audited correction boundary or projection drifted."""


_SAFE_STARTUP = bool(
    sys.flags.isolated
    and sys.flags.no_site
    and sys.flags.no_user_site
    and sys.flags.ignore_environment
    and sys.flags.safe_path
)
_EXACT_MODE_FLAGS = frozenset({"--apply", "--plan", "--recover"})
if _EXACT_MODE_FLAGS.intersection(sys.argv) and not _SAFE_STARTUP:
    raise SystemExit(
        "exact diagnosis correction modes require `python -I -S scripts/"
        "apply_claim_scoped_diagnosis_corrections.py MODE`"
    )

_SAFE_BYTECODE_CACHE: TemporaryDirectory[str] | None = None


def _require_safe_repository_import_surface(
    import_roots: Sequence[Path],
) -> None:
    forbidden: list[str] = []
    try:
        for import_root in import_roots:
            resolved_root = import_root.resolve(strict=True)
            for candidate in resolved_root.rglob("*"):
                suffix = candidate.suffix.casefold()
                sourceless = (
                    suffix == ".pyc"
                    and candidate.parent.name.casefold() != "__pycache__"
                )
                native = suffix in {".dll", ".pyd", ".so"}
                if not (sourceless or native):
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
    roaming_buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(
        None,
        0x001A,
        None,
        0,
        roaming_buffer,
    ):
        raise SystemExit("canonical Windows RoamingAppData is unavailable")
    package_roots = (
        (Path(sys.base_prefix) / "Lib" / "site-packages").resolve(),
        (
            Path(roaming_buffer.value)
            / "Python"
            / f"Python{sys.version_info.major}{sys.version_info.minor}"
            / "site-packages"
        ).resolve(),
    )
    for package_root in package_roots:
        if package_root.is_dir() and str(package_root) not in sys.path:
            sys.path.append(str(package_root))
    _SAFE_BYTECODE_CACHE = TemporaryDirectory(
        prefix="axiom-diagnosis-correction-bytecode-"
    )
    sys.pycache_prefix = str(
        Path(_SAFE_BYTECODE_CACHE.name).resolve(strict=True)
    )
    sys.dont_write_bytecode = True
    import yaml

    _require_safe_repository_import_surface((ROOT / "src", ROOT / "scripts"))
else:
    import yaml
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.content_addressed_correction import (
    AuthorityFileBinding,
    ContentAddressedCorrectionError,
    CorrectionBaseline,
    CorrectionEventIntent,
    CorrectionEvidenceBinding,
    CorrectionPlanCore,
    CorrectionReceiptEnvelope,
    capture_local_correction_checkpoint,
    correction_suffix_from_journal,
    require_exact_correction_prefix,
    require_exact_correction_receipts,
    require_local_main_correction_boundary,
)
from axiom_rift.operations.correction_runtime_provenance import (
    capture_correction_runtime_provenance,
)
from axiom_rift.operations.effective_study_diagnosis import (
    EffectiveStudyDiagnosisError,
    effective_study_diagnoses_by_study,
    effective_study_diagnoses_for_mission,
)
from axiom_rift.operations.axis_disposition import (
    AxisDispositionEvidenceError,
    derive_axis_evidence_binding,
)
from axiom_rift.operations.evidence_scope_projection import (
    effective_completion_evidence_scope,
)
from axiom_rift.operations.study_close_delivery import StudyCloseGuardCapability
from axiom_rift.operations.study_close_delivery import (
    StudyCloseDeliveryObservation,
)
from axiom_rift.operations.study_close_git import (
    capture_study_close_delivery_observation,
    require_study_close_guard_ready,
)
from axiom_rift.operations.single_event_correction import (
    SingleEventCorrectionBinding,
    SingleEventCorrectionError,
    build_single_correction_event,
    correction_event_receipt,
    require_bound_single_correction_suffix,
)
from axiom_rift.operations.validation_integrity import (
    validator_execution_dependency_paths,
)
from axiom_rift.operations.writer import (
    RecoveryRequired,
    StateWriter,
    TransitionError,
)
from axiom_rift.research.study_diagnosis_correction import (
    StudyDiagnosisCorrectionAudit,
)
from axiom_rift.research.governance import (
    EvidenceState,
    ResearchLayer,
    diagnosis_branch,
)
from axiom_rift.research.scientific_diagnosis import (
    ScientificDiagnosisError,
    diagnose_scientific_adjudications,
)
from axiom_rift.research.axis_disposition import (
    AxisEvidenceKind,
    AxisEvidenceReference,
    AxisEvidenceState,
)
from axiom_rift.storage.evidence import EvidenceStore
from axiom_rift.storage.journal import DurableJournal


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _git_bytes(*arguments: str, check: bool = True) -> bytes:
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=ROOT,
            check=check,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ClaimScopedCorrectionApplyError(
            f"Git command failed: {' '.join(arguments)}"
        ) from exc
    return completed.stdout


def _git_blob(reference: str, relative: str) -> bytes:
    content = _git_bytes("show", f"{reference}:{relative}")
    if not content:
        raise ClaimScopedCorrectionApplyError(
            f"Git blob is empty: {reference}:{relative}"
        )
    return content


def _canonical_object(document: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = parse_canonical(document)
    except (TypeError, ValueError) as exc:
        raise ClaimScopedCorrectionApplyError(
            f"{label} is not canonical"
        ) from exc
    if not isinstance(value, dict) or canonical_bytes(value) != document:
        raise ClaimScopedCorrectionApplyError(
            f"{label} is not a canonical mapping"
        )
    return value


def _materialize_git_prefix(
    reference: str,
    relative: str,
    destination: Path,
) -> None:
    try:
        names = _git_bytes(
            "ls-tree",
            "-r",
            "--name-only",
            reference,
            "--",
            relative,
        ).decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise ClaimScopedCorrectionApplyError(
            "Git tree path is non-ASCII"
        ) from exc
    if not names:
        raise ClaimScopedCorrectionApplyError(
            f"Git tree prefix is empty: {reference}:{relative}"
        )
    boundary = relative.rstrip("/") + "/"
    for name in names:
        if name != relative and not name.startswith(boundary):
            raise ClaimScopedCorrectionApplyError(
                "Git tree prefix escaped its boundary"
            )
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_git_blob(reference, name))


_T = TypeVar("_T")


class _SingleUseClock:
    def __init__(self, source: Callable[[], str]) -> None:
        self.source = source
        self.calls = 0
        self.observed: str | None = None

    def __call__(self) -> str:
        if self.calls:
            raise ClaimScopedCorrectionApplyError(
                "diagnosis correction clock was read more than once"
            )
        self.calls += 1
        observed = self.source()
        if type(observed) is not str or not observed:
            raise ClaimScopedCorrectionApplyError(
                "diagnosis correction clock is malformed"
            )
        self.observed = observed
        return observed

    def require_consumed(self) -> str:
        if self.calls != 1 or self.observed is None:
            raise ClaimScopedCorrectionApplyError(
                "diagnosis correction clock was not consumed exactly once"
            )
        return self.observed


def _observe_writer_clock_once(writer: StateWriter) -> str:
    clock = _SingleUseClock(writer.clock)
    clock()
    return clock.require_consumed()


def _invoke_at(
    writer: StateWriter,
    occurred_at_utc: str,
    function: Callable[[], _T],
) -> _T:
    clock = _SingleUseClock(lambda: occurred_at_utc)
    previous = writer.clock
    writer.clock = clock
    try:
        result = function()
    finally:
        writer.clock = previous
    if clock.require_consumed() != occurred_at_utc:
        raise ClaimScopedCorrectionApplyError(
            "diagnosis correction replay clock changed"
        )
    return result


@dataclass(frozen=True, slots=True)
class CorrectionMaterial:
    core: CorrectionPlanCore
    audit: StudyDiagnosisCorrectionAudit
    audit_evidence: bytes
    study_close_delivery_observation: StudyCloseDeliveryObservation


@dataclass(frozen=True, slots=True)
class IndependentCorrectionMapping:
    control_projection: Mapping[str, Any]
    event_payload: Mapping[str, Any]
    operation_result: Mapping[str, Any]
    semantic_index_records: tuple[Mapping[str, Any], ...]


def _control_boundary(control: dict[str, Any]) -> None:
    science = control.get("scientific", {})
    expected_action = {
        "kind": "portfolio_decision",
        "portfolio_snapshot_id": EXPECTED_PORTFOLIO_SNAPSHOT_ID,
        "study_diagnosis_id": EXPECTED_CURRENT_DIAGNOSIS_ID,
    }
    if (
        control.get("revision") != EXPECTED_BASE_REVISION
        or control.get("heads", {}).get("journal")
        != {
            "event_id": EXPECTED_BASE_EVENT_ID,
            "sequence": EXPECTED_BASE_REVISION,
        }
        or science.get("active_mission") != EXPECTED_MISSION_ID
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
        or control.get("next_action") != expected_action
    ):
        raise ClaimScopedCorrectionApplyError(
            "claim-scoped correction baseline boundary drifted"
        )


def _inventory(
    writer: StateWriter,
    control: dict[str, Any],
    index: Any,
) -> tuple[
    tuple[str, ...],
    dict[str, str],
    dict[str, str],
    dict[str, str],
]:
    mission_id = control["scientific"]["active_mission"]
    mismatch_states: dict[str, str] = {}
    original_payload_digests: dict[str, str] = {}
    replay_satisfaction_digests: dict[str, str] = {}
    try:
        diagnoses = effective_study_diagnoses_for_mission(
            index,
            mission_id=mission_id,
        )
    except EffectiveStudyDiagnosisError as exc:
        raise ClaimScopedCorrectionApplyError(str(exc)) from exc
    for effective in diagnoses:
        original_payload_digests[effective.record_id] = canonical_digest(
            domain="study-diagnosis-payload",
            payload=dict(effective.original.payload),
        )
        study_id = effective.payload.get("study_id")
        if not isinstance(study_id, str):
            raise ClaimScopedCorrectionApplyError(
                "diagnosis inventory lost its Study identity"
            )
        try:
            pattern = writer._study_claim_scoped_diagnosis(
                index,
                study_id=study_id,
            )
        except TransitionError:
            if effective.status == "engineering_gap":
                continue
            raise
        if pattern is not None and pattern.evidence_state.value != effective.status:
            mismatch_states[effective.record_id] = pattern.evidence_state.value
    for resolution in index.records_by_kind(
        "historical-replay-obligation-resolution"
    ):
        payload = resolution.payload.get("resolution")
        if (
            isinstance(payload, dict)
            and payload.get("study_diagnosis_id") in EXPECTED_MISMATCH_IDS
        ):
            replay_satisfaction_digests[resolution.record_id] = canonical_digest(
                domain="historical-replay-satisfaction-payload",
                payload=dict(resolution.payload),
            )
    mismatch_ids = tuple(sorted(mismatch_states))
    if (
        mismatch_ids != EXPECTED_MISMATCH_IDS
        or mismatch_states.get(EXPECTED_STABILITY_DIAGNOSIS_ID)
        != "stability_concentration"
        or any(
            state != "absent_information"
            for diagnosis_id, state in mismatch_states.items()
            if diagnosis_id != EXPECTED_STABILITY_DIAGNOSIS_ID
        )
    ):
        raise ClaimScopedCorrectionApplyError(
            "claim-scoped mismatch inventory differs from the audited 13+1 set"
        )
    return (
        mismatch_ids,
        mismatch_states,
        original_payload_digests,
        dict(sorted(replay_satisfaction_digests.items())),
    )


def _audit(
    control: dict[str, Any],
    mismatch_ids: tuple[str, ...],
) -> StudyDiagnosisCorrectionAudit:
    journal = control["heads"]["journal"]
    return StudyDiagnosisCorrectionAudit(
        mission_id=EXPECTED_MISSION_ID,
        original_diagnosis_ids=mismatch_ids,
        prior_journal_event_id=journal["event_id"],
        prior_journal_sequence=journal["sequence"],
        rationale=(
            "Correct the complete evidence-derived claim-scoped mismatch set; "
            "preserve useful component evidence without allowing unrelated "
            "claims to compensate for the registered causal question."
        ),
    )


def _apply_one(
    writer: StateWriter,
    *,
    operation_id: str = SHADOW_OPERATION_ID,
) -> dict[str, Any]:
    with writer.open_stable_index() as (control, index):
        _control_boundary(control)
        (
            mismatch_ids,
            mismatch_states,
            original_payload_digests,
            replay_satisfaction_digests,
        ) = _inventory(writer, control, index)
        audit = _audit(control, mismatch_ids)
    result = writer.record_study_diagnosis_corrections(
        audit=audit,
        operation_id=operation_id,
    )
    with writer.open_stable_index() as (final_control, index):
        if final_control.get("revision") != EXPECTED_BASE_REVISION + 1:
            raise ClaimScopedCorrectionApplyError(
                "diagnosis correction did not advance exactly one event"
            )
        action = final_control.get("next_action", {})
        if (
            action.get("study_diagnosis_id") != EXPECTED_CURRENT_DIAGNOSIS_ID
            or action.get("diagnosis_correction_audit_id") != audit.identity
            or not isinstance(
                action.get("study_diagnosis_correction_id"), str
            )
        ):
            raise ClaimScopedCorrectionApplyError(
                "corrected Portfolio action lost its authority packet"
            )
        corrected = effective_study_diagnoses_for_mission(
            index,
            mission_id=EXPECTED_MISSION_ID,
        )
        effective_states = {
            value.record_id: value.status
            for value in corrected
            if value.record_id in EXPECTED_MISMATCH_IDS
        }
        if effective_states != mismatch_states:
            raise ClaimScopedCorrectionApplyError(
                "effective diagnosis projection differs after correction"
            )
        diagnosis_projection = effective_study_diagnoses_by_study(
            index,
            mission_id=EXPECTED_MISSION_ID,
        )
        projected_completion_count = 0
        zero_credit_completion_count = 0
        for value in corrected:
            if value.record_id not in EXPECTED_MISMATCH_IDS:
                continue
            expected_axis_state = (
                AxisEvidenceState.PARTIAL_POSITIVE
                if value.record_id == EXPECTED_STABILITY_DIAGNOSIS_ID
                else AxisEvidenceState.LOW_INFORMATION
            )
            if value.correction is None:
                raise ClaimScopedCorrectionApplyError(
                    "effective correction record is unavailable"
                )
            completion_ids = value.correction.payload.get(
                "affected_completion_record_ids"
            )
            axis_id = value.payload.get("portfolio_axis_id")
            axis_identity = value.payload.get("portfolio_axis_identity")
            if (
                not isinstance(completion_ids, list)
                or not isinstance(axis_id, str)
                or not isinstance(axis_identity, str)
            ):
                raise ClaimScopedCorrectionApplyError(
                    "corrected axis projection scope is malformed"
                )
            for completion_id in completion_ids:
                try:
                    binding = derive_axis_evidence_binding(
                        index,
                        reference=AxisEvidenceReference(
                            kind=AxisEvidenceKind.JOB_COMPLETION,
                            record_id=completion_id,
                        ),
                        mission_id=EXPECTED_MISSION_ID,
                        axis_id=axis_id,
                        axis_identity=axis_identity,
                        diagnosis_projection=diagnosis_projection,
                    )
                except AxisDispositionEvidenceError:
                    completion = index.get("job-completed", completion_id)
                    if completion is None:
                        raise
                    scope = effective_completion_evidence_scope(
                        index,
                        completion,
                    )
                    if scope.scientific_eligible and scope.scientific_credit == 1:
                        raise
                    zero_credit_completion_count += 1
                    continue
                latch_qualified_unresolved = False
                if (
                    expected_axis_state is AxisEvidenceState.LOW_INFORMATION
                    and binding.state is AxisEvidenceState.UNRESOLVED
                ):
                    completion = index.get("job-completed", completion_id)
                    if completion is not None:
                        latch_qualified_unresolved = (
                            effective_completion_evidence_scope(
                                index,
                                completion,
                            ).cost_semantics_latch_id
                            is not None
                        )
                if (
                    binding.state is not expected_axis_state
                    and not latch_qualified_unresolved
                ):
                    raise ClaimScopedCorrectionApplyError(
                        "corrected completion axis state is inconsistent: "
                        f"{value.record_id} {completion_id} "
                        f"{binding.state.value} != {expected_axis_state.value}"
                    )
                projected_completion_count += 1
        if (
            projected_completion_count + zero_credit_completion_count
            != EXPECTED_AFFECTED_COMPLETION_COUNT
        ):
            raise ClaimScopedCorrectionApplyError(
                "corrected completion reference inventory is incomplete"
            )
        for value in corrected:
            if value.record_id not in EXPECTED_MISMATCH_IDS:
                continue
            if canonical_digest(
                domain="study-diagnosis-payload",
                payload=dict(value.original.payload),
            ) != original_payload_digests[value.record_id]:
                raise ClaimScopedCorrectionApplyError(
                    "original diagnosis bytes changed during additive correction"
                )
        final_replay_digests = {
            resolution.record_id: canonical_digest(
                domain="historical-replay-satisfaction-payload",
                payload=dict(resolution.payload),
            )
            for resolution in index.records_by_kind(
                    "historical-replay-obligation-resolution"
            )
            if isinstance(resolution.payload.get("resolution"), dict)
            and resolution.payload["resolution"].get("study_diagnosis_id")
            in EXPECTED_MISMATCH_IDS
        }
        if dict(sorted(final_replay_digests.items())) != replay_satisfaction_digests:
            raise ClaimScopedCorrectionApplyError(
                "replay satisfaction authority changed during diagnosis correction"
            )
        if index.get("study-diagnosis-correction-audit", audit.identity) is None:
            raise ClaimScopedCorrectionApplyError(
                "durable diagnosis correction audit is unavailable"
            )
    return {
        "audit_id": audit.identity,
        "event_id": result.event_id,
        "effective_absent_information_count": sum(
            state == "absent_information" for state in effective_states.values()
        ),
        "effective_stability_concentration_count": sum(
            state == "stability_concentration"
            for state in effective_states.values()
        ),
        "operation_result": dict(result.result),
        "projected_completion_count": projected_completion_count,
        "revision": result.revision,
        "schema": "claim_scoped_diagnosis_correction_result.v1",
        "zero_credit_completion_count": zero_credit_completion_count,
    }


def shadow_plan() -> dict[str, Any]:
    audit, mapping, evidence, _inventory = _shadow_event_material()
    document = _canonical_object(evidence, label="shadow audit evidence")
    states = tuple(
        row["status"]
        for row in mapping.semantic_index_records
        if row["kind"] == "study-diagnosis-correction"
    )
    return {
        "audit_id": audit.identity,
        "effective_absent_information_count": states.count(
            "absent_information"
        ),
        "effective_stability_concentration_count": states.count(
            "stability_concentration"
        ),
        "mode": "reconstructed_shadow",
        "operation_result": dict(mapping.operation_result),
        "projected_completion_count": document[
            "expected_projected_completion_count"
        ],
        "semantic_record_count": len(mapping.semantic_index_records),
        "zero_credit_completion_count": document[
            "expected_zero_credit_completion_count"
        ],
    }


def _authority_paths(control: Mapping[str, Any]) -> tuple[str, ...]:
    authority = control.get("authority")
    if not isinstance(authority, Mapping):
        raise ClaimScopedCorrectionApplyError("control authority is malformed")
    operating_direction = authority.get("operating_direction")
    contracts = authority.get("contracts")
    foundation = authority.get("foundation_inputs")
    if (
        type(operating_direction) is not str
        or not isinstance(contracts, list)
        or not isinstance(foundation, list)
    ):
        raise ClaimScopedCorrectionApplyError(
            "control authority inventory is malformed"
        )
    paths = tuple([operating_direction, *contracts, *foundation])
    if (
        len(set(paths)) != len(paths)
        or any(
            type(path) is not str
            or not path
            or not path.isascii()
            or "\\" in path
            or ":" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
            for path in paths
        )
    ):
        raise ClaimScopedCorrectionApplyError(
            "control authority paths are not canonical"
        )
    return paths


def _authority_bindings(
    control: Mapping[str, Any],
) -> tuple[AuthorityFileBinding, ...]:
    hashes: dict[str, str] = {}
    bindings: list[AuthorityFileBinding] = []
    for relative in _authority_paths(control):
        head = _git_blob("HEAD", relative)
        origin = _git_blob("origin/main", relative)
        try:
            worktree = (ROOT / relative).read_bytes()
        except OSError as exc:
            raise ClaimScopedCorrectionApplyError(
                "authority file is unavailable"
            ) from exc
        if head != origin or worktree != head:
            raise ClaimScopedCorrectionApplyError(
                "implementation-only correction cannot change authority bytes"
            )
        digest = sha256(head).hexdigest()
        hashes[relative] = digest
        bindings.append(
            AuthorityFileBinding(
                path=relative,
                predecessor_sha256=digest,
                prospective_sha256=digest,
            )
        )
    manifest = canonical_digest(
        domain="authority-manifest",
        payload=dict(sorted(hashes.items())),
    )
    if (
        manifest != EXPECTED_AUTHORITY_MANIFEST_DIGEST
        or control.get("authority", {}).get("manifest_digest") != manifest
    ):
        raise ClaimScopedCorrectionApplyError(
            "unchanged authority manifest differs from the audited baseline"
        )
    return tuple(sorted(bindings, key=lambda item: item.path))


def _active_journal_baseline(
    control: Mapping[str, Any],
) -> tuple[str, int, bytes, str | None]:
    manifest_path = ROOT / "records/journal/manifest.json"
    if not manifest_path.is_file():
        relative = "records/journal.jsonl"
        content = _git_blob("HEAD", relative)
        if _git_blob("origin/main", relative) != content:
            raise ClaimScopedCorrectionApplyError(
                "legacy Journal baseline drifted"
            )
        return relative, 0, content, None
    manifest_document = _git_blob("HEAD", "records/journal/manifest.json")
    if _git_blob("origin/main", "records/journal/manifest.json") != manifest_document:
        raise ClaimScopedCorrectionApplyError(
            "Journal manifest baseline drifted"
        )
    manifest = _canonical_object(
        manifest_document,
        label="Journal manifest",
    )
    active = manifest.get("active_segment")
    if (
        not isinstance(active, Mapping)
        or type(active.get("path")) is not str
        or type(active.get("start_offset")) is not int
        or active["start_offset"] < 0
    ):
        raise ClaimScopedCorrectionApplyError(
            "active Journal binding is malformed"
        )
    relative = active["path"]
    content = _git_blob("HEAD", relative)
    if _git_blob("origin/main", relative) != content:
        raise ClaimScopedCorrectionApplyError(
            "active Journal baseline drifted"
        )
    if control.get("heads", {}).get("journal", {}).get("sequence") != (
        EXPECTED_BASE_REVISION
    ):
        raise ClaimScopedCorrectionApplyError(
            "Journal baseline sequence differs"
        )
    return (
        relative,
        active["start_offset"],
        content,
        sha256(manifest_document).hexdigest(),
    )


def _reviewed_checkpoint() -> dict[str, Any]:
    try:
        paths = validator_execution_dependency_paths(
            Path(__file__).resolve(),
            include_deferred_imports=True,
        )
        checkpoint = capture_local_correction_checkpoint(
            ROOT,
            execution_paths=paths,
        )
    except (ContentAddressedCorrectionError, OSError, RuntimeError, ValueError) as exc:
        raise ClaimScopedCorrectionApplyError(
            "diagnosis correction execution closure cannot be sealed"
        ) from exc
    resolved = {Path(path).resolve() for path in paths}
    if Path(__file__).resolve() not in resolved:
        raise ClaimScopedCorrectionApplyError(
            "diagnosis correction closure omitted its entrypoint"
        )
    return checkpoint


def _study_close_guard_binding(
    *,
    checkpoint_commit: str,
    origin_main_commit: str,
) -> tuple[dict[str, Any], StudyCloseDeliveryObservation]:
    require_study_close_guard_ready(ROOT)
    checkpoint_path = "records/STUDY_CLOSE_DELIVERY_CHECKPOINT.json"
    hook_path = ".githooks/commit-msg"
    checkpoint = _git_blob("HEAD", checkpoint_path)
    hook = _git_blob("HEAD", hook_path)
    try:
        if (
            (ROOT / checkpoint_path).read_bytes() != checkpoint
            or (ROOT / hook_path).read_bytes().replace(b"\r\n", b"\n")
            != hook.replace(b"\r\n", b"\n")
        ):
            raise OSError("worktree Study-close guard differs")
    except OSError as exc:
        raise ClaimScopedCorrectionApplyError(
            "Study-close guard worktree bytes drifted"
        ) from exc
    hook_stage = _git("ls-files", "--stage", "--", hook_path).split()
    hooks_path = _git("config", "--get", "core.hooksPath")
    if not hook_stage or hook_stage[0] != "100755" or hooks_path != ".githooks":
        raise ClaimScopedCorrectionApplyError(
            "Study-close Git guard is inactive"
        )
    observation = capture_study_close_delivery_observation(
        ROOT,
        expected_main_head=checkpoint_commit,
        expected_origin_main=origin_main_commit,
    )
    return (
        {
            "checkpoint_path": checkpoint_path,
            "checkpoint_sha256": sha256(checkpoint).hexdigest(),
            "commit_msg_hook_path": hook_path,
            "commit_msg_hook_sha256": sha256(
                hook.replace(b"\r\n", b"\n")
            ).hexdigest(),
            "core_hooks_path": hooks_path,
            "delivery_observation": observation.to_payload(),
            "hook_mode": hook_stage[0],
            "schema": "study_close_guard_binding.v2",
        },
        observation,
    )


def _scientific_inventory(
    control: Mapping[str, Any],
    index: Any,
) -> dict[str, Any]:
    science = control.get("scientific")
    if not isinstance(science, Mapping):
        raise ClaimScopedCorrectionApplyError(
            "scientific control inventory is malformed"
        )
    return {
        "claim": science.get("claim"),
        "holdout_reveals": science.get("holdout_reveals"),
        "record_counts": {
            kind: index.count_by_kind(kind)
            for kind in (
                "candidate",
                "historical-replay-obligation-resolution",
                "job-completed",
                "negative-memory",
                "release",
                "study-diagnosis",
                "trial",
            )
        },
        "schema": "diagnosis_correction_scientific_inventory.v1",
    }


def _derive_and_verify_full_semantic_mapping(
    writer: StateWriter,
    index: Any,
    *,
    audit: StudyDiagnosisCorrectionAudit,
    baseline_control: Mapping[str, Any],
    event: Mapping[str, Any],
    operation_result: Mapping[str, Any],
) -> IndependentCorrectionMapping:
    """Independently derive every control, payload, and semantic record byte."""

    event_payload = {"audit_id": audit.identity, "evidence": []}
    operation_fingerprint = canonical_digest(
        domain="operation",
        payload={
            "event_kind": "study_diagnoses_corrected",
            "payload": event_payload,
        },
    )
    rows = event.get("index_records")
    if not isinstance(rows, list) or len(rows) != 16:
        raise ClaimScopedCorrectionApplyError(
            "correction semantic mapping must contain one audit and 14 corrections"
        )
    audit_digest = audit.identity.removeprefix("diagnosis-correction-audit:")
    expected_audit_row = {
        "event_sequence": None,
        "event_stream": None,
        "fingerprint": audit_digest,
        "kind": "study-diagnosis-correction-audit",
        "payload": audit.to_identity_payload(),
        "record_id": audit.identity,
        "status": "complete_mismatch_inventory",
        "subject": f"Mission:{audit.mission_id}",
    }
    expected_corrections: list[dict[str, Any]] = []
    for original_id in audit.original_diagnosis_ids:
        original = index.get("study-diagnosis", original_id)
        if original is None:
            raise ClaimScopedCorrectionApplyError(
                "semantic correction derivation lost an original diagnosis"
            )
        study_id = original.payload.get("study_id")
        study = (
            None
            if not isinstance(study_id, str)
            else index.get("study-open", study_id)
        )
        if study is None or not isinstance(study_id, str):
            raise ClaimScopedCorrectionApplyError(
                "semantic correction derivation lost its Study"
            )
        try:
            primary_layer = ResearchLayer(
                study.payload["primary_research_layer"]
            )
            changed_layers = tuple(
                ResearchLayer(value)
                for value in study.payload.get("changed_domains", [])
            )
            completions = writer._study_primary_scientific_completions(
                index,
                study_id=study_id,
            )
            adjudications = tuple(
                completion.payload["scientific"]["adjudication"]
                for completion in completions
            )
            pattern = diagnose_scientific_adjudications(adjudications)
            allowed_actions, allowed_layers = diagnosis_branch(
                pattern.evidence_state,
                primary_layer=primary_layer,
                changed_layers=changed_layers,
                reason_code=pattern.reason_code,
            )
        except (
            KeyError,
            ScientificDiagnosisError,
            TransitionError,
            TypeError,
            ValueError,
        ) as exc:
            raise ClaimScopedCorrectionApplyError(
                "semantic correction diagnosis cannot be independently derived"
            ) from exc
        if not pattern.primary_question_recognized:
            raise ClaimScopedCorrectionApplyError(
                "semantic correction lacks a recognized primary question"
            )
        completion_basis: list[dict[str, str]] = []
        for completion in completions:
            scientific = completion.payload.get("scientific")
            adjudication = (
                None
                if not isinstance(scientific, Mapping)
                else scientific.get("adjudication")
            )
            executable_id = (
                None
                if not isinstance(scientific, Mapping)
                else scientific.get("executable_id")
            )
            if not isinstance(adjudication, Mapping) or not isinstance(
                executable_id,
                str,
            ):
                raise ClaimScopedCorrectionApplyError(
                    "semantic correction completion basis is malformed"
                )
            completion_basis.append(
                {
                    "adjudication_digest": canonical_digest(
                        domain="scientific-adjudication",
                        payload=dict(adjudication),
                    ),
                    "completion_record_id": completion.record_id,
                    "executable_id": executable_id,
                }
            )
        satisfaction_ids = tuple(
            sorted(
                resolution.record_id
                for resolution in index.records_by_kind(
                    "historical-replay-obligation-resolution"
                )
                if isinstance(resolution.payload.get("resolution"), Mapping)
                and resolution.payload["resolution"].get("study_diagnosis_id")
                == original_id
            )
        )
        decision_qualifications: list[dict[str, str]] = []
        for decision in index.records_by_kind("portfolio-decision"):
            if decision.payload.get("study_diagnosis_id") != original_id:
                continue
            active = writer._active_portfolio_decision(index, decision.record_id)
            action = decision.status
            qualification = (
                "withdrawn_no_effect"
                if active is None
                else "historical_only_no_confirmation_credit"
                if action == "preserve"
                else "independent_protocol_authority_preserved"
                if action == "revise_protocol"
                else "direction_compatible_no_inherited_positive_credit"
                if action in allowed_actions
                else "historical_only_requires_reassessment"
            )
            decision_qualifications.append(
                {
                    "action": action,
                    "decision_id": decision.record_id,
                    "qualification": qualification,
                }
            )
        affected_completion_ids = sorted(
            reference.get("record_id")
            for reference in original.payload.get("evidence_basis", [])
            if isinstance(reference, Mapping)
            and reference.get("kind") == "job-completed"
            and isinstance(reference.get("record_id"), str)
        )
        original_payload_digest = canonical_digest(
            domain="study-diagnosis-payload",
            payload=dict(original.payload),
        )
        correction_payload = {
            "affected_completion_record_ids": affected_completion_ids,
            "allowed_actions": list(allowed_actions),
            "allowed_research_layers": list(allowed_layers),
            "audit_id": audit.identity,
            "audit_protocol_id": audit.protocol_id,
            "candidate_authority_delta": 0,
            "claim_scoped_diagnosis": pattern.to_payload(),
            "completion_basis": completion_basis,
            "confirmation_credit_delta": (
                -1
                if original.payload.get("evidence_state")
                == EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION.value
                and pattern.evidence_state
                is not EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION
                else 0
            ),
            "decision_qualifications": decision_qualifications,
            "effective_confidence": pattern.confidence.value,
            "effective_evidence_state": pattern.evidence_state.value,
            "effective_reason_code": pattern.reason_code,
            "evidence_basis_digest": canonical_digest(
                domain="study-diagnosis-evidence-basis",
                payload=original.payload.get("evidence_basis", []),
            ),
            "holdout_reveal_delta": 0,
            "mission_id": audit.mission_id,
            "original_confidence": original.payload.get("confidence"),
            "original_diagnosis_id": original.record_id,
            "original_diagnosis_payload_digest": original_payload_digest,
            "original_evidence_state": original.payload.get("evidence_state"),
            "portfolio_axis_id": original.payload.get("portfolio_axis_id"),
            "portfolio_axis_identity": original.payload.get(
                "portfolio_axis_identity"
            ),
            "portfolio_snapshot_id": original.payload.get(
                "portfolio_snapshot_id"
            ),
            "projection_scope": (
                "study_primary_question_over_all_completion_references"
            ),
            "replay_satisfaction_delta": 0,
            "replay_satisfaction_record_ids": list(satisfaction_ids),
            "schema": "study_diagnosis_correction.v1",
            "scientific_trial_delta": 0,
            "study_close_record_id": original.payload.get(
                "study_close_record_id"
            ),
            "study_id": study_id,
            "system_architecture_family": (
                writer._study_resolved_architecture_family(
                    index=index,
                    study=study,
                )
            ),
        }
        digest = canonical_digest(
            domain="study-diagnosis-correction",
            payload=correction_payload,
        )
        expected_corrections.append(
            {
                "event_sequence": 1,
                "event_stream": (
                    f"study-diagnosis-correction:{original.record_id}"
                ),
                "fingerprint": digest,
                "kind": "study-diagnosis-correction",
                "payload": correction_payload,
                "record_id": "diagnosis-correction:" + digest,
                "status": pattern.evidence_state.value,
                "subject": original.subject,
            }
        )
    expected_result = {
        "audit_id": audit.identity,
        "candidate_authority_delta": 0,
        "corrected_diagnosis_count": len(expected_corrections),
        "holdout_reveal_delta": 0,
        "replay_satisfaction_delta": 0,
        "scientific_trial_delta": 0,
        "study_diagnosis_correction_ids": sorted(
            row["record_id"] for row in expected_corrections
        ),
    }
    expected_operation_row = {
        "event_sequence": None,
        "event_stream": None,
        "fingerprint": operation_fingerprint,
        "kind": "operation",
        "payload": {
            "event_kind": "study_diagnoses_corrected",
            "result": expected_result,
        },
        "record_id": SHADOW_OPERATION_ID,
        "status": "success",
        "subject": f"Mission:{audit.mission_id}",
    }
    expected_control = writer._body(baseline_control)
    current_correction = next(
        row["record_id"]
        for row in expected_corrections
        if row["payload"]["original_diagnosis_id"]
        == EXPECTED_CURRENT_DIAGNOSIS_ID
    )
    expected_control["next_action"] = {
        **dict(baseline_control["next_action"]),
        "diagnosis_correction_audit_id": audit.identity,
        "study_diagnosis_correction_id": current_correction,
    }
    if (
        event.get("event_kind") != "study_diagnoses_corrected"
        or event.get("operation_id") != SHADOW_OPERATION_ID
        or event.get("subject") != f"Mission:{audit.mission_id}"
        or event.get("payload") != event_payload
        or event.get("control") != expected_control
        or rows != [
            expected_operation_row,
            expected_audit_row,
            *expected_corrections,
        ]
        or dict(operation_result) != expected_result
    ):
        raise ClaimScopedCorrectionApplyError(
            "shadow Writer output differs from the independently derived full mapping"
        )
    return IndependentCorrectionMapping(
        control_projection=expected_control,
        event_payload=event_payload,
        operation_result=expected_result,
        semantic_index_records=tuple(
            [expected_audit_row, *expected_corrections]
        ),
    )


@contextmanager
def _reconstructed_baseline_shadow() -> Iterator[StateWriter]:
    """Rebuild one independent complete-history projection from Git bytes."""

    control_document = _git_blob("HEAD", "state/control.json")
    control = _canonical_object(control_document, label="baseline control")
    _control_boundary(control)
    with TemporaryDirectory(
        prefix="axiom-diagnosis-correction-reconstruction-"
    ) as name:
        shadow_root = Path(name).resolve()
        (shadow_root / "state").mkdir(parents=True)
        (shadow_root / "state/control.json").write_bytes(control_document)
        if (ROOT / "records/journal/manifest.json").is_file():
            _materialize_git_prefix("HEAD", "records/journal", shadow_root)
        else:
            target = shadow_root / "records/journal.jsonl"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_git_blob("HEAD", "records/journal.jsonl"))
        for relative in _authority_paths(control):
            target = shadow_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_git_blob("HEAD", relative))
        writer = StateWriter(
            shadow_root,
            foundation_root=shadow_root,
            study_close_guard_capability=(
                StudyCloseGuardCapability.ISOLATED_ENGINEERING_FIXTURE
            ),
        )
        recovered = writer.recover()
        if (
            recovered.get("journal_sequence") != EXPECTED_BASE_REVISION
            or recovered.get("index_rebuilt") is not True
        ):
            raise ClaimScopedCorrectionApplyError(
                "independent correction baseline reconstruction failed"
            )
        stable = writer.require_stable_head()
        if (
            stable.get("control_revision") != EXPECTED_BASE_REVISION
            or stable.get("journal_event_id") != EXPECTED_BASE_EVENT_ID
        ):
            raise ClaimScopedCorrectionApplyError(
                "reconstructed correction head differs from Git baseline"
            )
        yield writer


def _shadow_event_material() -> tuple[
    StudyDiagnosisCorrectionAudit,
    IndependentCorrectionMapping,
    bytes,
    dict[str, Any],
]:
    with _reconstructed_baseline_shadow() as writer:
        with writer.open_stable_index() as (control, index):
            (
                mismatch_ids,
                mismatch_states,
                original_payload_digests,
                replay_satisfaction_digests,
            ) = _inventory(writer, control, index)
            audit = _audit(control, mismatch_ids)
            scientific_inventory = _scientific_inventory(control, index)
        result = _invoke_at(
            writer,
            "2000-01-01T00:00:00Z",
            lambda: _apply_one(
                writer,
                operation_id=SHADOW_OPERATION_ID,
            ),
        )
        _head, raw_event = writer.journal.tail()
        if raw_event is None:
            raise ClaimScopedCorrectionApplyError(
                "shadow correction did not produce one Journal event"
            )
        event = _canonical_object(
            canonical_bytes(dict(raw_event)),
            label="shadow correction event",
        )
        with writer.open_stable_index() as (_final_control, final_index):
            independent_mapping = _derive_and_verify_full_semantic_mapping(
                writer,
                final_index,
                audit=audit,
                baseline_control=control,
                event=event,
                operation_result=result["operation_result"],
            )
    rows = event.get("index_records")
    if (
        not isinstance(rows, list)
        or len(rows) != 16
        or not isinstance(rows[0], Mapping)
        or rows[0].get("kind") != "operation"
        or rows[0].get("payload", {}).get("result")
        != result["operation_result"]
    ):
        raise ClaimScopedCorrectionApplyError(
            "shadow correction full semantic mapping is malformed"
        )
    audit_evidence = canonical_bytes(
        {
            "audit": audit.to_identity_payload(),
            "expected_mismatch_states": mismatch_states,
            "expected_original_diagnosis_payload_digests": (
                original_payload_digests
            ),
            "expected_projected_completion_count": (
                result["projected_completion_count"]
            ),
            "expected_replay_satisfaction_payload_digests": (
                replay_satisfaction_digests
            ),
            "expected_zero_credit_completion_count": (
                result["zero_credit_completion_count"]
            ),
            "operation_result": dict(independent_mapping.operation_result),
            "schema": "claim_scoped_diagnosis_correction_audit_evidence.v1",
            "scientific_inventory": scientific_inventory,
        }
    )
    return audit, independent_mapping, audit_evidence, scientific_inventory


def _build_material() -> CorrectionMaterial:
    control_document = _git_blob("HEAD", "state/control.json")
    if _git_blob("origin/main", "state/control.json") != control_document:
        raise ClaimScopedCorrectionApplyError(
            "HEAD and origin/main do not share the control baseline"
        )
    control = _canonical_object(control_document, label="baseline control")
    _control_boundary(control)
    checkpoint = _reviewed_checkpoint()
    if checkpoint["origin_main_commit"] != EXPECTED_ORIGIN_MAIN_COMMIT:
        raise ClaimScopedCorrectionApplyError(
            "origin/main differs from the audited diagnosis boundary"
        )
    authority_files = _authority_bindings(control)
    journal_path, journal_start, journal_bytes, manifest_hash = (
        _active_journal_baseline(control)
    )
    index_head = control.get("heads", {}).get("index")
    journal_head = control.get("heads", {}).get("journal")
    if not isinstance(index_head, Mapping) or not isinstance(
        journal_head,
        Mapping,
    ):
        raise ClaimScopedCorrectionApplyError(
            "baseline projection heads are malformed"
        )
    audit, independent_mapping, audit_evidence, scientific_inventory = (
        _shadow_event_material()
    )
    runtime = capture_correction_runtime_provenance(
        safe_startup=_SAFE_STARTUP,
        private_bytecode_cache_root=(
            None
            if _SAFE_BYTECODE_CACHE is None
            else _SAFE_BYTECODE_CACHE.name
        ),
    )
    study_close_guard, observation = _study_close_guard_binding(
        checkpoint_commit=checkpoint["code_checkpoint_commit"],
        origin_main_commit=checkpoint["origin_main_commit"],
    )
    binding = SingleEventCorrectionBinding(
        control_projection=independent_mapping.control_projection,
        event_payload=independent_mapping.event_payload,
        operation_result=independent_mapping.operation_result,
        semantic_index_records=independent_mapping.semantic_index_records,
        guards={
            "audit_evidence_sha256": sha256(audit_evidence).hexdigest(),
            "authority_manifest_digest": EXPECTED_AUTHORITY_MANIFEST_DIGEST,
            "runtime": runtime,
            "scientific_inventory": scientific_inventory,
            "study_close_guard": study_close_guard,
        },
    )
    baseline = CorrectionBaseline(
        control_revision=control["revision"],
        journal_sequence=journal_head["sequence"],
        journal_event_id=journal_head["event_id"],
        journal_path=journal_path,
        control_sha256=sha256(control_document).hexdigest(),
        journal_sha256=sha256(journal_bytes).hexdigest(),
        journal_start_offset=journal_start,
        journal_size_bytes=len(journal_bytes),
        authority_manifest_digest=EXPECTED_AUTHORITY_MANIFEST_DIGEST,
        index_record_count=index_head["required_record_count"],
        index_projection_digest=index_head["required_projection_digest"],
        mission_id=EXPECTED_MISSION_ID,
        initiative_id=EXPECTED_INITIATIVE_ID,
        next_action_kind="portfolio_decision",
        code_checkpoint_commit=checkpoint["code_checkpoint_commit"],
        code_checkpoint_tree=checkpoint["code_checkpoint_tree"],
        origin_main_commit=checkpoint["origin_main_commit"],
        journal_manifest_sha256=manifest_hash,
    )
    core = CorrectionPlanCore(
        operation_namespace=OPERATION_NAMESPACE,
        baseline=baseline,
        prospective_authority_manifest_digest=(
            EXPECTED_AUTHORITY_MANIFEST_DIGEST
        ),
        authority_files=authority_files,
        code_checkpoint_files=tuple(checkpoint["code_checkpoint_files"]),
        execution_files=tuple(checkpoint["execution_files"]),
        evidence_bindings=(
            CorrectionEvidenceBinding(
                role="diagnosis-audit",
                sha256=sha256(audit_evidence).hexdigest(),
            ),
        ),
        event_intents=(
            CorrectionEventIntent(
                action="diagnosis-correction",
                event_kind="study_diagnoses_corrected",
                subject=f"Mission:{EXPECTED_MISSION_ID}",
                binding=binding.to_payload(),
            ),
        ),
        purpose=PURPOSE,
    )
    return CorrectionMaterial(
        core=core,
        audit=audit,
        audit_evidence=audit_evidence,
        study_close_delivery_observation=observation,
    )


def _require_execution_closure(core: CorrectionPlanCore) -> None:
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
        raise ClaimScopedCorrectionApplyError(
            "current diagnosis correction closure cannot be inspected"
        ) from exc
    expected = tuple((item.path, item.sha256) for item in core.execution_files)
    if observed != expected:
        raise ClaimScopedCorrectionApplyError(
            "current diagnosis correction closure differs from the plan"
        )


def _read_journal() -> tuple[dict[str, Any], ...]:
    return tuple(DurableJournal(ROOT / "records/journal.jsonl").read_all())


def _current_control() -> dict[str, Any]:
    try:
        return _canonical_object(
            (ROOT / "state/control.json").read_bytes(),
            label="current control",
        )
    except OSError as exc:
        raise ClaimScopedCorrectionApplyError(
            "current control is unavailable"
        ) from exc


def _materialize_plan_evidence(
    material: CorrectionMaterial,
    evidence: EvidenceStore,
) -> None:
    for document, expected in (
        (material.audit_evidence, sha256(material.audit_evidence).hexdigest()),
        (material.core.core_bytes, material.core.core_hash),
    ):
        artifact = evidence.finalize(document)
        if (
            artifact.sha256 != expected
            or evidence.read_verified(expected) != document
        ):
            raise ClaimScopedCorrectionApplyError(
                "diagnosis correction plan evidence drifted"
            )


def _require_plan_evidence(
    material: CorrectionMaterial,
    evidence: EvidenceStore,
) -> None:
    for document, expected in (
        (material.audit_evidence, sha256(material.audit_evidence).hexdigest()),
        (material.core.core_bytes, material.core.core_hash),
    ):
        try:
            observed = evidence.read_verified(expected)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ClaimScopedCorrectionApplyError(
                "interrupted diagnosis correction lacks its plan evidence"
            ) from exc
        if observed != document:
            raise ClaimScopedCorrectionApplyError(
                "interrupted diagnosis correction evidence drifted"
            )


def _exact_recovery_arguments(
    suffix: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if len(suffix) != 1:
        raise ClaimScopedCorrectionApplyError(
            "recovery requires the exact one-event correction suffix"
        )
    event = suffix[0]
    return {
        "expected_sequence": event.get("sequence"),
        "expected_event_id": event.get("event_id"),
        "expected_operation_id": event.get("operation_id"),
        "expected_previous_event_id": event.get("previous_event_id"),
    }


def _verify_final_projection(
    material: CorrectionMaterial,
) -> dict[str, Any]:
    writer = StateWriter(
        ROOT,
        study_close_delivery_observation=(
            material.study_close_delivery_observation
        ),
    )
    binding = SingleEventCorrectionBinding.from_mapping(
        material.core.event_intents[0].binding
    )
    guards = binding.guards
    with writer.open_stable_index() as (control, index):
        corrected = effective_study_diagnoses_for_mission(
            index,
            mission_id=EXPECTED_MISSION_ID,
        )
        states = {
            value.record_id: value.status
            for value in corrected
            if value.record_id in EXPECTED_MISMATCH_IDS
        }
        current_correction = next(
            (
                value.correction.record_id
                for value in corrected
                if value.record_id == EXPECTED_CURRENT_DIAGNOSIS_ID
                and value.correction is not None
            ),
            None,
        )
        expected_action = {
            "diagnosis_correction_audit_id": material.audit.identity,
            "kind": "portfolio_decision",
            "portfolio_snapshot_id": EXPECTED_PORTFOLIO_SNAPSHOT_ID,
            "study_diagnosis_correction_id": current_correction,
            "study_diagnosis_id": EXPECTED_CURRENT_DIAGNOSIS_ID,
        }
        inventory = _scientific_inventory(control, index)
        if (
            control.get("revision") != EXPECTED_BASE_REVISION + 1
            or control.get("next_action") != expected_action
            or inventory != guards.get("scientific_inventory")
            or index.record_count()
            != material.core.baseline.index_record_count + 17
            or index.get(
                "study-diagnosis-correction-audit",
                material.audit.identity,
            )
            is None
            or set(states) != set(EXPECTED_MISMATCH_IDS)
            or states.get(EXPECTED_STABILITY_DIAGNOSIS_ID)
            != "stability_concentration"
            or any(
                state != "absent_information"
                for diagnosis_id, state in states.items()
                if diagnosis_id != EXPECTED_STABILITY_DIAGNOSIS_ID
            )
        ):
            raise ClaimScopedCorrectionApplyError(
                "final diagnosis correction projection differs"
            )
        return {
            "effective_absent_information_count": sum(
                state == "absent_information" for state in states.values()
            ),
            "effective_stability_concentration_count": sum(
                state == "stability_concentration" for state in states.values()
            ),
            "index_record_count": index.record_count(),
            "revision": control["revision"],
            "scientific_inventory": inventory,
        }


def read_only_plan() -> dict[str, Any]:
    if not _SAFE_STARTUP:
        raise ClaimScopedCorrectionApplyError(
            "exact planning requires the isolated no-site Python boundary"
        )
    material = _build_material()
    events = _read_journal()
    try:
        suffix = correction_suffix_from_journal(material.core, events)
        require_exact_correction_prefix(material.core, suffix)
        suffix = require_bound_single_correction_suffix(
            material.core,
            suffix,
        )
        boundary = require_local_main_correction_boundary(
            ROOT,
            material.core,
            current_control=_current_control(),
            journal_events=events,
        )
    except (ContentAddressedCorrectionError, SingleEventCorrectionError) as exc:
        raise ClaimScopedCorrectionApplyError(str(exc)) from exc
    _require_execution_closure(material.core)
    return {
        "apply_mutation_performed": False,
        "authority_replacement_count": 0,
        "event_inventory": [
            item.to_payload() for item in material.core.events
        ],
        "existing_prefix_count": len(suffix),
        "local_main_boundary": boundary,
        "plan_core_hash": material.core.core_hash,
        "schema": "claim_scoped_diagnosis_correction_plan.v2",
    }


def apply(*, explicit_recovery: bool = False) -> dict[str, Any]:
    """Apply one exact preappend-proven correction; never commit or push."""

    if not _SAFE_STARTUP:
        raise ClaimScopedCorrectionApplyError(
            "apply requires the isolated no-site Python boundary"
        )
    if type(explicit_recovery) is not bool:
        raise ClaimScopedCorrectionApplyError(
            "correction recovery capability must be boolean"
        )
    material = _build_material()
    core = material.core
    _require_execution_closure(core)
    events = _read_journal()
    try:
        suffix = correction_suffix_from_journal(core, events)
        require_exact_correction_prefix(core, suffix)
        suffix = require_bound_single_correction_suffix(core, suffix)
        require_local_main_correction_boundary(
            ROOT,
            core,
            current_control=_current_control(),
            journal_events=events,
            allow_one_event_projection_lag=explicit_recovery,
        )
    except (ContentAddressedCorrectionError, SingleEventCorrectionError) as exc:
        raise ClaimScopedCorrectionApplyError(str(exc)) from exc
    initial_prefix = len(suffix)
    if explicit_recovery and not suffix:
        raise ClaimScopedCorrectionApplyError(
            "explicit recovery requires the exact trailing correction event"
        )
    evidence = EvidenceStore(ROOT / "local/evidence")
    if suffix:
        _require_plan_evidence(material, evidence)
    else:
        _materialize_plan_evidence(material, evidence)

    writer = StateWriter(
        ROOT,
        study_close_delivery_observation=(
            material.study_close_delivery_observation
        ),
    )
    recovery: dict[str, Any] = {"mode": "stable_head_no_recovery"}
    try:
        writer.require_stable_head()
    except RecoveryRequired:
        if not explicit_recovery or not suffix:
            raise
        arguments = _exact_recovery_arguments(suffix)
        writer.require_exact_trailing_event_recovery_boundary(**arguments)
        _require_plan_evidence(material, evidence)
        recovery = {
            "mode": "explicit_exact_plan_prefix_recovery",
            **writer.recover_exact_trailing_event(**arguments),
        }
    else:
        writer.require_study_close_delivery_guard()

    if not suffix:
        _require_execution_closure(core)
        occurred_at_utc = _observe_writer_clock_once(writer)
        try:
            expected_event = build_single_correction_event(
                core,
                occurred_at_utc=occurred_at_utc,
            )
            require_local_main_correction_boundary(
                ROOT,
                core,
                current_control=_current_control(),
                journal_events=events,
            )
        except (ContentAddressedCorrectionError, SingleEventCorrectionError) as exc:
            raise ClaimScopedCorrectionApplyError(str(exc)) from exc
        _require_execution_closure(core)
        writer.require_stable_head()
        writer.require_study_close_delivery_guard()
        with writer.journal.expect_next_event(expected_event):
            result = _invoke_at(
                writer,
                occurred_at_utc,
                lambda: _apply_one(
                    writer,
                    operation_id=core.events[0].operation_id,
                ),
            )
        _head, actual_event = writer.journal.tail()
        if (
            actual_event is None
            or canonical_bytes(dict(actual_event))
            != canonical_bytes(expected_event)
            or result["event_id"] != actual_event.get("event_id")
            or result["revision"] != EXPECTED_BASE_REVISION + 1
        ):
            raise ClaimScopedCorrectionApplyError(
                "durable diagnosis correction differs from preappend authority"
            )
        events = (*events, dict(actual_event))
        suffix = (dict(actual_event),)

    if len(suffix) != 1:
        raise ClaimScopedCorrectionApplyError(
            "diagnosis correction did not reach its exact one-event boundary"
        )
    try:
        suffix = require_bound_single_correction_suffix(core, suffix)
        receipt = correction_event_receipt(suffix[0])
    except SingleEventCorrectionError as exc:
        raise ClaimScopedCorrectionApplyError(str(exc)) from exc
    envelope = CorrectionReceiptEnvelope(
        core=core,
        event_receipts=(receipt,),
    )
    try:
        require_exact_correction_receipts(envelope, suffix)
    except ContentAddressedCorrectionError as exc:
        raise ClaimScopedCorrectionApplyError(str(exc)) from exc
    envelope_artifact = evidence.finalize(envelope.artifact_bytes)
    if (
        envelope_artifact.sha256 != envelope.artifact_hash
        or evidence.read_verified(envelope.artifact_hash)
        != envelope.artifact_bytes
    ):
        raise ClaimScopedCorrectionApplyError(
            "final diagnosis correction receipt envelope drifted"
        )
    final_projection = _verify_final_projection(material)
    try:
        delivery = require_local_main_correction_boundary(
            ROOT,
            envelope,
            current_control=_current_control(),
            journal_events=events,
        )
    except ContentAddressedCorrectionError as exc:
        raise ClaimScopedCorrectionApplyError(str(exc)) from exc
    return {
        "already_complete": initial_prefix == core.event_count,
        "applied_event_count": core.event_count - initial_prefix,
        "final_envelope_artifact_hash": envelope.artifact_hash,
        "final_prefix_count": len(suffix),
        "final_projection": final_projection,
        "local_main_delivery_boundary": delivery,
        "mode": "apply",
        "plan_core_hash": core.core_hash,
        "recovery": recovery,
        "schema": "claim_scoped_diagnosis_correction_apply.v2",
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument(
        "--plan",
        action="store_true",
        help="build and verify the exact content-addressed correction plan",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply the one-event content-addressed additive correction",
    )
    parser.add_argument(
        "--recover",
        action="store_true",
        help="recover only one exact plan-bound trailing correction event",
    )
    arguments = parser.parse_args()
    if sum(bool(value) for value in (arguments.plan, arguments.apply, arguments.recover)) > 1:
        parser.error("choose at most one of --plan, --apply, or --recover")
    return arguments


def main() -> int:
    arguments = parse_arguments()
    if arguments.plan:
        result = read_only_plan()
    elif arguments.apply or arguments.recover:
        result = apply(explicit_recovery=arguments.recover)
    else:
        result = shadow_plan()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
