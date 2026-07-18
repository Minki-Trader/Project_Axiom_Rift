"""Plan or apply the effective-scope Study diagnosis correction.

The exact three-event suffix migrates authority, rebinds the prospective
scientific protocol, and appends the complete diagnosis mismatch correction.
It never rewrites a Study, completion, prior correction, trial, or claim.
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
EXPECTED_BASE_REVISION = 5708
EXPECTED_BASE_EVENT_ID = (
    "f95050a5dca1ba2a956a20dfc1a0495f0fda612be35ccb513021ce8e525b7769"
)
EXPECTED_ORIGIN_MAIN_COMMIT = "57d48c241d7a39cb7e31fc4fda6e4bfc0522b7d5"
MISSION_ID = "MIS-0006"
INITIATIVE_ID = "INI-0025"
PORTFOLIO_SNAPSHOT_ID = (
    "portfolio:083c52d62b53de26c18d04372ebd84fca6942d5e27710a72e7bd591c325e20f5"
)
REPORT_PATH = "records/audits/2026-07-19_effective_diagnosis_scope_audit.md"
AUTHORITY_REASON = "bind effective completion scope before Study diagnosis"
AUDIT_RATIONALE = (
    "Correct every Study diagnosis whose disposition-driving completion lost "
    "scientific authority; preserve exact audit and invalidation claims without "
    "confirmation, trial, or candidate credit."
)
MISMATCH_IDS = (
    "diagnosis:023fcedeee24fc4882227ed37696ce05d7f537179a30895317d9797a771c26e7",
    "diagnosis:77601b1a26e73567017a5462b275d670847b893fbfb165b325486d34e4d26234",
    "diagnosis:abfbd5546a3849022bbeb311dab2c62f1e340ab7c4ad996f172bcd8a6c069fd2",
)
PRIOR_CORRECTION_IDS = (
    "diagnosis-correction:37bd6153a543fce121a1f3b318123ff4e65d36a43130cca22a25c35cf4127091",
    "diagnosis-correction:50e00faa0521b72ce89b3a4f5b209248568ebb8f8a91e22f4db4a630bf8dc0a1",
)
EXPECTED_STATES = {diagnosis_id: "not_identifiable" for diagnosis_id in MISMATCH_IDS}
OPERATION_NAMESPACE = "axiom-effective-diagnosis-scope"
PURPOSE = (
    "Apply effective completion scope before Study diagnosis and append the "
    "complete three-diagnosis zero-credit correction chain."
)
_EXACT_FLAGS = frozenset({"--plan", "--apply", "--recover"})
_SAFE_STARTUP = bool(
    sys.flags.isolated
    and sys.flags.no_site
    and sys.flags.no_user_site
    and sys.flags.ignore_environment
    and sys.flags.safe_path
)
if _EXACT_FLAGS.intersection(sys.argv) and not _SAFE_STARTUP:
    raise SystemExit(
        "exact effective diagnosis correction modes require `python -I -S "
        "scripts/apply_effective_diagnosis_scope_correction.py MODE`"
    )


class EffectiveDiagnosisScopeCorrectionError(RuntimeError):
    """The reviewed correction boundary or deterministic replay drifted."""


def _require_safe_repository_import_surface(paths: Sequence[Path]) -> None:
    forbidden: list[str] = []
    for root in paths:
        for candidate in root.resolve(strict=True).rglob("*"):
            suffix = candidate.suffix.casefold()
            if suffix in {".dll", ".pyd", ".so"} or (
                suffix == ".pyc"
                and candidate.parent.name.casefold() != "__pycache__"
            ):
                forbidden.append(candidate.resolve(strict=True).as_posix())
    if forbidden:
        raise SystemExit(
            "safe repository import surface contains native or sourceless code: "
            + ", ".join(sorted(forbidden))
        )


_SAFE_BYTECODE_CACHE: TemporaryDirectory[str] | None = None
if _SAFE_STARTUP:
    roaming = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x001A, None, 0, roaming):
        raise SystemExit("canonical Windows RoamingAppData is unavailable")
    package_roots = (
        (Path(sys.base_prefix) / "Lib" / "site-packages").resolve(),
        (
            Path(roaming.value)
            / "Python"
            / f"Python{sys.version_info.major}{sys.version_info.minor}"
            / "site-packages"
        ).resolve(),
    )
    for root in package_roots:
        if root.is_dir() and str(root) not in sys.path:
            sys.path.append(str(root))
    _SAFE_BYTECODE_CACHE = TemporaryDirectory(
        prefix="axiom-effective-diagnosis-bytecode-"
    )
    sys.pycache_prefix = str(Path(_SAFE_BYTECODE_CACHE.name).resolve(strict=True))
    sys.dont_write_bytecode = True
    import yaml  # noqa: F401

    _require_safe_repository_import_surface((ROOT / "src", ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.content_addressed_correction import (
    AuthorityFileBinding,
    ContentAddressedCorrectionError,
    CorrectionBaseline,
    CorrectionEventIntent,
    CorrectionEventReceiptBinding,
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
    effective_study_diagnoses_by_study,
    effective_study_diagnoses_for_mission,
)
from axiom_rift.operations.evidence_scope_projection import (
    effective_completion_evidence_scope,
)
from axiom_rift.operations.study_close_delivery import (
    StudyCloseDeliveryObservation,
    StudyCloseGuardCapability,
)
from axiom_rift.operations.study_close_git import (
    capture_study_close_delivery_observation,
    require_study_close_guard_ready,
)
from axiom_rift.operations.validation import EvidenceValidatorRegistry
from axiom_rift.operations.validation_integrity import (
    validator_execution_dependency_paths,
)
from axiom_rift.operations.writer import RecoveryRequired, StateWriter, TransitionError
from axiom_rift.research.governance import (
    EvidenceState,
    ResearchLayer,
    diagnosis_branch,
)
from axiom_rift.research.protocol import ResearchProtocol, ResearchProtocolActivation
from axiom_rift.research.study_diagnosis_correction import (
    StudyDiagnosisCorrectionAudit,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    ScientificAdjudicationValidatorV2,
)
from axiom_rift.storage.evidence import EvidenceStore
from axiom_rift.storage.journal import DurableJournal


_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class CorrectionMaterial:
    core: CorrectionPlanCore
    report_bytes: bytes
    predecessor_documents: Mapping[str, bytes]
    prospective_documents: Mapping[str, bytes]
    delivery_observation: StudyCloseDeliveryObservation


@dataclass(frozen=True, slots=True)
class _Cursor:
    journal_offset: int
    previous_event_id: str
    index_record_count: int
    index_projection_digest: str


@dataclass(frozen=True, slots=True)
class _ExpectedDiagnosisAction:
    audit: StudyDiagnosisCorrectionAudit
    semantic_rows: tuple[Mapping[str, Any], ...]
    operation_result: Mapping[str, Any]
    states_by_study: Mapping[str, str]


def _git(*arguments: str) -> bytes:
    try:
        return subprocess.run(
            ("git", *arguments),
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise EffectiveDiagnosisScopeCorrectionError(
            f"Git inspection failed: {' '.join(arguments)}"
        ) from exc


def _git_text(*arguments: str) -> str:
    try:
        return _git(*arguments).decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise EffectiveDiagnosisScopeCorrectionError(
            "Git output is non-ASCII"
        ) from exc


def _git_blob(reference: str, relative: str) -> bytes:
    content = _git("show", f"{reference}:{relative}")
    if not content:
        raise EffectiveDiagnosisScopeCorrectionError(
            f"Git blob is empty: {reference}:{relative}"
        )
    return content


def _canonical_mapping(document: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = parse_canonical(document)
    except (TypeError, ValueError) as exc:
        raise EffectiveDiagnosisScopeCorrectionError(
            f"{label} is not canonical"
        ) from exc
    if not isinstance(value, dict) or canonical_bytes(value) != document:
        raise EffectiveDiagnosisScopeCorrectionError(
            f"{label} is not a canonical mapping"
        )
    return value


def _current_control() -> dict[str, Any]:
    try:
        return _canonical_mapping(
            (ROOT / "state/control.json").read_bytes(),
            label="current control",
        )
    except OSError as exc:
        raise EffectiveDiagnosisScopeCorrectionError(
            "current control is unavailable"
        ) from exc


def _authority_paths(control: Mapping[str, Any]) -> tuple[str, ...]:
    authority = control.get("authority")
    if not isinstance(authority, Mapping):
        raise EffectiveDiagnosisScopeCorrectionError("authority is malformed")
    operating = authority.get("operating_direction")
    contracts = authority.get("contracts")
    foundation = authority.get("foundation_inputs")
    if (
        type(operating) is not str
        or not isinstance(contracts, list)
        or not isinstance(foundation, list)
        or any(type(value) is not str for value in [*contracts, *foundation])
    ):
        raise EffectiveDiagnosisScopeCorrectionError(
            "authority path inventory is malformed"
        )
    paths = tuple([operating, *contracts, *foundation])
    if len(paths) != len(set(paths)):
        raise EffectiveDiagnosisScopeCorrectionError(
            "authority path inventory is duplicated"
        )
    return paths


def _manifest_digest(documents: Mapping[str, bytes]) -> str:
    return canonical_digest(
        domain="authority-manifest",
        payload={
            path: sha256(content).hexdigest()
            for path, content in sorted(documents.items())
        },
    )


@contextmanager
def _foundation(
    documents: Mapping[str, bytes],
    *,
    expected_digest: str,
) -> Iterator[Path]:
    with TemporaryDirectory(prefix="axiom-effective-diagnosis-foundation-") as name:
        root = Path(name).resolve()
        for relative, content in documents.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        observed = _manifest_digest(
            {relative: (root / relative).read_bytes() for relative in documents}
        )
        if observed != expected_digest:
            raise EffectiveDiagnosisScopeCorrectionError(
                "temporary authority foundation drifted"
            )
        yield root


def _registry() -> EvidenceValidatorRegistry:
    return EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))


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
        checkpoint["runtime_provenance"] = capture_correction_runtime_provenance(
            safe_startup=_SAFE_STARTUP,
            private_bytecode_cache_root=(
                None
                if _SAFE_BYTECODE_CACHE is None
                else _SAFE_BYTECODE_CACHE.name
            ),
        )
    except (ContentAddressedCorrectionError, OSError, RuntimeError, ValueError) as exc:
        raise EffectiveDiagnosisScopeCorrectionError(
            "reviewed correction checkpoint cannot be sealed"
        ) from exc
    if checkpoint.get("origin_main_commit") != EXPECTED_ORIGIN_MAIN_COMMIT:
        raise EffectiveDiagnosisScopeCorrectionError(
            "origin/main differs from the audited baseline"
        )
    return checkpoint


def _delivery_observation(checkpoint: Mapping[str, Any]) -> StudyCloseDeliveryObservation:
    require_study_close_guard_ready(ROOT)
    return capture_study_close_delivery_observation(
        ROOT,
        expected_main_head=checkpoint["code_checkpoint_commit"],
        expected_origin_main=checkpoint["origin_main_commit"],
    )


def _active_journal_baseline() -> tuple[str, int, bytes, str | None]:
    manifest_path = "records/journal/manifest.json"
    try:
        manifest_bytes = _git_blob("HEAD", manifest_path)
    except EffectiveDiagnosisScopeCorrectionError:
        journal_path = "records/journal.jsonl"
        journal_bytes = _git_blob("HEAD", journal_path)
        if journal_bytes != _git_blob("origin/main", journal_path):
            raise EffectiveDiagnosisScopeCorrectionError(
                "legacy Journal baseline diverged"
            )
        return journal_path, 0, journal_bytes, None
    if manifest_bytes != _git_blob("origin/main", manifest_path):
        raise EffectiveDiagnosisScopeCorrectionError(
            "Journal manifest baseline diverged"
        )
    manifest = _canonical_mapping(manifest_bytes, label="Journal manifest")
    active = manifest.get("active_segment")
    if not isinstance(active, Mapping) or type(active.get("path")) is not str:
        raise EffectiveDiagnosisScopeCorrectionError(
            "active Journal segment is malformed"
        )
    journal_path = active["path"]
    journal_bytes = _git_blob("HEAD", journal_path)
    if journal_bytes != _git_blob("origin/main", journal_path):
        raise EffectiveDiagnosisScopeCorrectionError(
            "active Journal baseline diverged"
        )
    return (
        journal_path,
        int(active["start_offset"]),
        journal_bytes,
        sha256(manifest_bytes).hexdigest(),
    )


def _control_body(control: Mapping[str, Any]) -> dict[str, Any]:
    return _canonical_mapping(
        canonical_bytes(
            {
                key: value
                for key, value in control.items()
                if key not in {"control_hash", "heads", "revision"}
            }
        ),
        label="control body",
    )


def _record_mapping(record: Any) -> dict[str, Any]:
    return {
        "event_sequence": record.event_sequence,
        "event_stream": record.event_stream,
        "fingerprint": record.fingerprint,
        "kind": record.kind,
        "payload": dict(record.payload),
        "record_id": record.record_id,
        "status": record.status,
        "subject": record.subject,
    }


def _baseline_inventory(
    control: Mapping[str, Any],
    predecessor_documents: Mapping[str, bytes],
) -> tuple[str, int, str]:
    with _foundation(
        predecessor_documents,
        expected_digest=control["authority"]["manifest_digest"],
    ) as foundation_root:
        writer = StateWriter(ROOT, foundation_root=foundation_root)
        with writer.open_stable_index() as (_stable, index):
            diagnoses = effective_study_diagnoses_for_mission(
                index,
                mission_id=MISSION_ID,
            )
            states: dict[str, str] = {}
            prior_ids: list[str] = []
            for effective in diagnoses:
                study_id = effective.payload.get("study_id")
                if not isinstance(study_id, str):
                    raise EffectiveDiagnosisScopeCorrectionError(
                        "diagnosis inventory lost its Study"
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
                    states[effective.record_id] = pattern.evidence_state.value
                    if effective.correction is not None:
                        prior_ids.append(effective.correction.record_id)
            if tuple(sorted(states)) != MISMATCH_IDS or states != EXPECTED_STATES:
                raise EffectiveDiagnosisScopeCorrectionError(
                    "effective diagnosis mismatch inventory drifted"
                )
            if tuple(sorted(prior_ids)) != PRIOR_CORRECTION_IDS:
                raise EffectiveDiagnosisScopeCorrectionError(
                    "prior diagnosis correction inventory drifted"
                )
            head = index.event_head("research-protocol:scientific")
            record = None if head is None else index.get(head.record_kind, head.record_id)
            if (
                head is None
                or record is None
                or record.payload.get("validator_id")
                != SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
            ):
                raise EffectiveDiagnosisScopeCorrectionError(
                    "prospective protocol baseline is unavailable"
                )
            return record.record_id, head.sequence, record.payload["protocol"]


def _build_material() -> CorrectionMaterial:
    baseline_document = _git_blob("origin/main", "state/control.json")
    if _git_blob("HEAD", "state/control.json") != baseline_document:
        raise EffectiveDiagnosisScopeCorrectionError(
            "local HEAD does not preserve the Git control baseline"
        )
    control = _canonical_mapping(baseline_document, label="baseline control")
    if (
        control.get("revision") != EXPECTED_BASE_REVISION
        or control.get("heads", {}).get("journal")
        != {"event_id": EXPECTED_BASE_EVENT_ID, "sequence": EXPECTED_BASE_REVISION}
        or control.get("scientific", {}).get("active_mission") != MISSION_ID
        or control.get("scientific", {}).get("active_initiative") != INITIATIVE_ID
        or control.get("next_action")
        != {"kind": "portfolio_decision", "portfolio_snapshot_id": PORTFOLIO_SNAPSHOT_ID}
    ):
        raise EffectiveDiagnosisScopeCorrectionError(
            "effective diagnosis correction baseline drifted"
        )
    checkpoint = _reviewed_checkpoint()
    observation = _delivery_observation(checkpoint)
    paths = _authority_paths(control)
    predecessor = {path: _git_blob("origin/main", path) for path in paths}
    prospective = {path: _git_blob("HEAD", path) for path in paths}
    if _manifest_digest(predecessor) != control["authority"]["manifest_digest"]:
        raise EffectiveDiagnosisScopeCorrectionError(
            "predecessor authority differs from control"
        )
    prospective_digest = _manifest_digest(prospective)
    if prospective_digest == control["authority"]["manifest_digest"]:
        raise EffectiveDiagnosisScopeCorrectionError(
            "prospective authority did not change"
        )
    authority_files = tuple(
        AuthorityFileBinding(
            path=path,
            predecessor_sha256=sha256(predecessor[path]).hexdigest(),
            prospective_sha256=sha256(prospective[path]).hexdigest(),
        )
        for path in paths
    )
    changed = tuple(item for item in authority_files if item.changed)
    if tuple(item.path for item in changed) != (
        "OPERATING_DIRECTION.md",
        "contracts/science.yaml",
    ):
        raise EffectiveDiagnosisScopeCorrectionError(
            "authority replacement inventory is not the reviewed pair"
        )
    prior_activation_id, prior_ordinal, protocol = _baseline_inventory(
        control,
        predecessor,
    )
    try:
        report_bytes = _git_blob("HEAD", REPORT_PATH)
        report_bytes.decode("ascii")
    except (UnicodeDecodeError, EffectiveDiagnosisScopeCorrectionError) as exc:
        raise EffectiveDiagnosisScopeCorrectionError(
            "effective diagnosis audit report is unavailable"
        ) from exc
    report_hash = sha256(report_bytes).hexdigest()
    journal_path, journal_start, journal_bytes, manifest_hash = (
        _active_journal_baseline()
    )
    index_head = control["heads"]["index"]
    baseline = CorrectionBaseline(
        control_revision=EXPECTED_BASE_REVISION,
        journal_sequence=EXPECTED_BASE_REVISION,
        journal_event_id=EXPECTED_BASE_EVENT_ID,
        journal_path=journal_path,
        control_sha256=sha256(baseline_document).hexdigest(),
        journal_sha256=sha256(journal_bytes).hexdigest(),
        journal_start_offset=journal_start,
        journal_size_bytes=len(journal_bytes),
        authority_manifest_digest=control["authority"]["manifest_digest"],
        index_record_count=index_head["required_record_count"],
        index_projection_digest=index_head["required_projection_digest"],
        mission_id=MISSION_ID,
        initiative_id=INITIATIVE_ID,
        next_action_kind="portfolio_decision",
        code_checkpoint_commit=checkpoint["code_checkpoint_commit"],
        code_checkpoint_tree=checkpoint["code_checkpoint_tree"],
        origin_main_commit=checkpoint["origin_main_commit"],
        journal_manifest_sha256=manifest_hash,
    )
    replacement_rows = [
        {
            "artifact_sha256": item.prospective_sha256,
            "new_sha256": item.prospective_sha256,
            "old_sha256": item.predecessor_sha256,
            "path": item.path,
        }
        for item in changed
    ]
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
    migration_id = canonical_digest(
        domain="authority-manifest-migration",
        payload=migration_payload,
    )
    activation = ResearchProtocolActivation(
        protocol=ResearchProtocol(protocol),
        validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        authority_manifest_digest=prospective_digest,
        audit_artifact_hash=report_hash,
    )
    body = _control_body(control)
    body["authority"]["manifest_digest"] = prospective_digest
    control_body_hash = sha256(canonical_bytes(body)).hexdigest()
    event_intents = (
        CorrectionEventIntent(
            action="authority-migration",
            event_kind="authority_migrated",
            subject="Authority:active",
            binding={
                "control_projection_sha256": control_body_hash,
                "delivery_observation": observation.to_payload(),
                "migration_id": migration_id,
                "new_manifest_digest": prospective_digest,
                "old_manifest_digest": baseline.authority_manifest_digest,
                "operation_result": {
                    "migration_id": migration_id,
                    "new_manifest_digest": prospective_digest,
                },
                "reason": AUTHORITY_REASON,
                "replacement_rows": replacement_rows,
                "runtime_provenance": checkpoint["runtime_provenance"],
                "semantic_record_count": 1,
            },
        ),
        CorrectionEventIntent(
            action="protocol-rebind",
            event_kind="research_protocol_activated",
            subject="ProjectGoal:OPERATING_DIRECTION.md",
            binding={
                "activation_id": activation.identity,
                "audit_artifact_hash": report_hash,
                "authority_manifest_digest": prospective_digest,
                "control_projection_sha256": control_body_hash,
                "ordinal": prior_ordinal + 1,
                "prior_activation_id": prior_activation_id,
                "protocol": activation.protocol.value,
                "semantic_record_count": 1,
                "validator_id": activation.validator_id,
            },
        ),
        CorrectionEventIntent(
            action="diagnosis-correction",
            event_kind="study_diagnoses_corrected",
            subject=f"Mission:{MISSION_ID}",
            binding={
                "audit_protocol_id": (
                    "protocol:claim_scoped_noncompensating_diagnosis.v1"
                ),
                "audit_rationale": AUDIT_RATIONALE,
                "audit_uses_immediate_prior_event": True,
                "candidate_authority_delta": 0,
                "expected_effective_states": EXPECTED_STATES,
                "holdout_reveal_delta": 0,
                "original_diagnosis_ids": list(MISMATCH_IDS),
                "prior_correction_ids": list(PRIOR_CORRECTION_IDS),
                "replay_satisfaction_delta": 0,
                "scientific_trial_delta": 0,
                "semantic_record_count": 4,
            },
        ),
    )
    core = CorrectionPlanCore(
        operation_namespace=OPERATION_NAMESPACE,
        baseline=baseline,
        prospective_authority_manifest_digest=prospective_digest,
        authority_files=authority_files,
        code_checkpoint_files=tuple(checkpoint["code_checkpoint_files"]),
        execution_files=tuple(checkpoint["execution_files"]),
        evidence_bindings=(
            CorrectionEvidenceBinding(role="audit-report", sha256=report_hash),
        ),
        event_intents=event_intents,
        purpose=PURPOSE,
    )
    return CorrectionMaterial(
        core=core,
        report_bytes=report_bytes,
        predecessor_documents=predecessor,
        prospective_documents=prospective,
        delivery_observation=observation,
    )


class _SingleClock:
    def __init__(self, value: str) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> str:
        if self.calls:
            raise EffectiveDiagnosisScopeCorrectionError(
                "correction clock was consumed more than once"
            )
        self.calls += 1
        return self.value


def _invoke_at(writer: StateWriter, occurred_at_utc: str, action: Callable[[], _T]) -> _T:
    clock = _SingleClock(occurred_at_utc)
    previous = writer.clock
    writer.clock = clock
    try:
        result = action()
    finally:
        writer.clock = previous
    if clock.calls != 1:
        raise EffectiveDiagnosisScopeCorrectionError(
            "correction transition did not consume one clock value"
        )
    return result


def _observe_clock(writer: StateWriter) -> str:
    value = writer.clock()
    if type(value) is not str or not value:
        raise EffectiveDiagnosisScopeCorrectionError(
            "canonical Writer clock is malformed"
        )
    return value


def _audit_for_current_head(writer: StateWriter) -> StudyDiagnosisCorrectionAudit:
    with writer.open_stable_index() as (control, _index):
        head = control["heads"]["journal"]
    return StudyDiagnosisCorrectionAudit(
        mission_id=MISSION_ID,
        original_diagnosis_ids=MISMATCH_IDS,
        prior_correction_ids=PRIOR_CORRECTION_IDS,
        prior_journal_event_id=head["event_id"],
        prior_journal_sequence=head["sequence"],
        rationale=AUDIT_RATIONALE,
    )


def _derive_expected_diagnosis_action(
    writer: StateWriter,
) -> _ExpectedDiagnosisAction:
    """Independently seal every semantic correction field before mutation."""

    with writer.open_stable_index() as (control, index):
        if control.get("next_action") != {
            "kind": "portfolio_decision",
            "portfolio_snapshot_id": PORTFOLIO_SNAPSHOT_ID,
        }:
            raise EffectiveDiagnosisScopeCorrectionError(
                "diagnosis correction preview lost its stable Portfolio boundary"
            )
        head = control["heads"]["journal"]
        audit = StudyDiagnosisCorrectionAudit(
            mission_id=MISSION_ID,
            original_diagnosis_ids=MISMATCH_IDS,
            prior_correction_ids=PRIOR_CORRECTION_IDS,
            prior_journal_event_id=head["event_id"],
            prior_journal_sequence=head["sequence"],
            rationale=AUDIT_RATIONALE,
        )
        effective_diagnoses = effective_study_diagnoses_for_mission(
            index,
            mission_id=MISSION_ID,
        )
        mismatches: list[tuple[Any, Any]] = []
        for effective in effective_diagnoses:
            study_id = effective.original.payload.get("study_id")
            if not isinstance(study_id, str):
                raise EffectiveDiagnosisScopeCorrectionError(
                    "effective diagnosis lost its Study identity"
                )
            try:
                pattern = writer._study_claim_scoped_diagnosis(
                    index,
                    study_id=study_id,
                )
            except TransitionError as exc:
                if effective.status == EvidenceState.ENGINEERING_GAP.value:
                    continue
                raise EffectiveDiagnosisScopeCorrectionError(
                    "effective diagnosis cannot be independently derived"
                ) from exc
            if pattern is not None and pattern.evidence_state.value != effective.status:
                mismatches.append((effective, pattern))
        observed_ids = tuple(
            sorted(effective.record_id for effective, _pattern in mismatches)
        )
        observed_prior_ids = tuple(
            sorted(
                effective.correction.record_id
                for effective, _pattern in mismatches
                if effective.correction is not None
            )
        )
        if observed_ids != MISMATCH_IDS or observed_prior_ids != PRIOR_CORRECTION_IDS:
            raise EffectiveDiagnosisScopeCorrectionError(
                "independent diagnosis mismatch inventory drifted"
            )

        audit_payload = audit.to_identity_payload()
        audit_digest = audit.identity.removeprefix(
            "diagnosis-correction-audit:"
        )
        rows: list[Mapping[str, Any]] = [
            {
                "event_sequence": None,
                "event_stream": None,
                "fingerprint": audit_digest,
                "kind": "study-diagnosis-correction-audit",
                "payload": audit_payload,
                "record_id": audit.identity,
                "status": "complete_mismatch_inventory",
                "subject": f"Mission:{MISSION_ID}",
            }
        ]
        decisions_by_diagnosis: dict[str, list[Any]] = {}
        for decision in index.records_by_kind("portfolio-decision"):
            diagnosis_id = decision.payload.get("study_diagnosis_id")
            if isinstance(diagnosis_id, str):
                decisions_by_diagnosis.setdefault(diagnosis_id, []).append(
                    decision
                )
        satisfactions_by_diagnosis: dict[str, list[str]] = {}
        for resolution in index.records_by_kind(
            "historical-replay-obligation-resolution"
        ):
            resolution_payload = resolution.payload.get("resolution")
            diagnosis_id = (
                None
                if not isinstance(resolution_payload, Mapping)
                else resolution_payload.get("study_diagnosis_id")
            )
            if isinstance(diagnosis_id, str):
                satisfactions_by_diagnosis.setdefault(
                    diagnosis_id,
                    [],
                ).append(resolution.record_id)

        states_by_study: dict[str, str] = {}
        correction_ids: list[str] = []
        for effective, pattern in sorted(
            mismatches,
            key=lambda item: item[0].record_id,
        ):
            original = effective.original
            study_id = original.payload["study_id"]
            study = index.get("study-open", study_id)
            if study is None:
                raise EffectiveDiagnosisScopeCorrectionError(
                    "diagnosis correction lost its Study record"
                )
            try:
                primary_layer = ResearchLayer(
                    study.payload["primary_research_layer"]
                )
                changed_layers = tuple(
                    ResearchLayer(value)
                    for value in study.payload.get("changed_domains", [])
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise EffectiveDiagnosisScopeCorrectionError(
                    "diagnosis correction Study layers are malformed"
                ) from exc
            allowed_actions, allowed_layers = diagnosis_branch(
                pattern.evidence_state,
                primary_layer=primary_layer,
                changed_layers=changed_layers,
                reason_code=pattern.reason_code,
            )
            completions = writer._study_primary_scientific_completions(
                index,
                study_id=study_id,
            )
            completion_basis: list[dict[str, str]] = []
            effective_scope_basis: list[dict[str, Any]] = []
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
                    raise EffectiveDiagnosisScopeCorrectionError(
                        "diagnosis completion basis is malformed"
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
                scope = effective_completion_evidence_scope(index, completion)
                effective_scope_basis.append(
                    {
                        "candidate_credit": scope.candidate_credit,
                        "completion_record_id": completion.record_id,
                        "cost_semantics_latch_id": scope.cost_semantics_latch_id,
                        "economic_credit": scope.economic_credit,
                        "evidence_modes": list(scope.evidence_modes),
                        "invalidation_record_id": scope.invalidation_record_id,
                        "overlay_record_id": scope.overlay_record_id,
                        "scientific_credit": scope.scientific_credit,
                        "scientific_eligible": scope.scientific_eligible,
                        "terminal_credit": scope.terminal_credit,
                    }
                )
            decision_qualifications: list[dict[str, str]] = []
            for decision in decisions_by_diagnosis.get(original.record_id, []):
                active = writer._active_portfolio_decision(
                    index,
                    decision.record_id,
                )
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
            architecture = writer._study_resolved_architecture_family(
                index=index,
                study=study,
            )
            stream = f"study-diagnosis-correction:{original.record_id}"
            stream_head = index.event_head(stream)
            prior_correction = effective.correction
            if (
                (stream_head is None) != (prior_correction is None)
                or (
                    stream_head is not None
                    and prior_correction is not None
                    and (
                        stream_head.record_kind != prior_correction.kind
                        or stream_head.record_id != prior_correction.record_id
                        or stream_head.sequence != prior_correction.event_sequence
                    )
                )
            ):
                raise EffectiveDiagnosisScopeCorrectionError(
                    "diagnosis correction stream head drifted"
                )
            correction_sequence = (
                1 if stream_head is None else stream_head.sequence + 1
            )
            satisfaction_ids = tuple(
                sorted(
                    satisfactions_by_diagnosis.get(original.record_id, [])
                )
            )
            correction_payload = {
                "affected_completion_record_ids": sorted(
                    reference.get("record_id")
                    for reference in original.payload.get("evidence_basis", [])
                    if isinstance(reference, Mapping)
                    and reference.get("kind") == "job-completed"
                    and isinstance(reference.get("record_id"), str)
                ),
                "allowed_actions": list(allowed_actions),
                "allowed_research_layers": list(allowed_layers),
                "audit_id": audit.identity,
                "audit_protocol_id": audit.protocol_id,
                "candidate_authority_delta": 0,
                "claim_scoped_diagnosis": pattern.to_payload(),
                "completion_basis": completion_basis,
                "confirmation_credit_delta": (
                    -1
                    if effective.status
                    == EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION.value
                    and pattern.evidence_state
                    is not EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION
                    else 0
                ),
                "decision_qualifications": decision_qualifications,
                "effective_confidence": pattern.confidence.value,
                "effective_completion_scope_basis": effective_scope_basis,
                "effective_evidence_state": pattern.evidence_state.value,
                "effective_reason_code": pattern.reason_code,
                "evidence_basis_digest": canonical_digest(
                    domain="study-diagnosis-evidence-basis",
                    payload=original.payload.get("evidence_basis", []),
                ),
                "holdout_reveal_delta": 0,
                "mission_id": MISSION_ID,
                "original_confidence": original.payload.get("confidence"),
                "original_diagnosis_id": original.record_id,
                "original_diagnosis_payload_digest": canonical_digest(
                    domain="study-diagnosis-payload",
                    payload=dict(original.payload),
                ),
                "original_evidence_state": original.payload.get(
                    "evidence_state"
                ),
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
                "prior_effective_authority_record_id": (
                    effective.authority_record_id
                ),
                "prior_effective_evidence_state": effective.status,
                "replay_satisfaction_delta": 0,
                "replay_satisfaction_record_ids": list(satisfaction_ids),
                "schema": "study_diagnosis_correction.v2",
                "scientific_trial_delta": 0,
                "study_close_record_id": original.payload.get(
                    "study_close_record_id"
                ),
                "study_id": study_id,
                "system_architecture_family": architecture,
                "supersedes_audit_id": (
                    None
                    if prior_correction is None
                    else prior_correction.payload.get("audit_id")
                ),
                "supersedes_correction_id": (
                    None
                    if prior_correction is None
                    else prior_correction.record_id
                ),
            }
            digest = canonical_digest(
                domain="study-diagnosis-correction",
                payload=correction_payload,
            )
            correction_id = "diagnosis-correction:" + digest
            rows.append(
                {
                    "event_sequence": correction_sequence,
                    "event_stream": stream,
                    "fingerprint": digest,
                    "kind": "study-diagnosis-correction",
                    "payload": correction_payload,
                    "record_id": correction_id,
                    "status": pattern.evidence_state.value,
                    "subject": original.subject,
                }
            )
            correction_ids.append(correction_id)
            states_by_study[study_id] = pattern.evidence_state.value
        operation_result = {
            "audit_id": audit.identity,
            "candidate_authority_delta": 0,
            "corrected_diagnosis_count": len(correction_ids),
            "holdout_reveal_delta": 0,
            "replay_satisfaction_delta": 0,
            "scientific_trial_delta": 0,
            "study_diagnosis_correction_ids": sorted(correction_ids),
        }
        return _ExpectedDiagnosisAction(
            audit=audit,
            semantic_rows=tuple(rows),
            operation_result=operation_result,
            states_by_study=states_by_study,
        )


def _perform_action(
    writer: StateWriter,
    material: CorrectionMaterial,
    ordinal: int,
) -> Any:
    event = material.core.events[ordinal - 1]
    if ordinal == 1:
        replacements = {
            item.path: material.prospective_documents[item.path]
            for item in material.core.authority_replacements
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
                    material.core.prospective_authority_manifest_digest
                ),
                audit_artifact_hash=sha256(material.report_bytes).hexdigest(),
            ),
            operation_id=event.operation_id,
            allow_active_stable_boundary=True,
        )
    if ordinal == 3:
        return writer.record_study_diagnosis_corrections(
            audit=_audit_for_current_head(writer),
            operation_id=event.operation_id,
        )
    raise EffectiveDiagnosisScopeCorrectionError("correction ordinal is foreign")


def _materialize_git_prefix(reference: str, relative: str, root: Path) -> None:
    names = _git_text("ls-tree", "-r", "--name-only", reference, "--", relative).splitlines()
    if not names:
        raise EffectiveDiagnosisScopeCorrectionError(
            f"Git prefix is empty: {reference}:{relative}"
        )
    for name in names:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_git_blob(reference, name))


@contextmanager
def _shadow(material: CorrectionMaterial) -> Iterator[StateWriter]:
    with TemporaryDirectory(prefix="axiom-effective-diagnosis-shadow-") as name:
        root = Path(name).resolve()
        control = _git_blob("origin/main", "state/control.json")
        (root / "state").mkdir(parents=True)
        (root / "state/control.json").write_bytes(control)
        _materialize_git_prefix("origin/main", "records/journal", root)
        for relative, content in material.predecessor_documents.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        writer = StateWriter(
            root,
            foundation_root=root,
            study_close_guard_capability=(
                StudyCloseGuardCapability.ISOLATED_ENGINEERING_FIXTURE
            ),
            validation_registry=_registry(),
        )
        recovered = writer.recover()
        if recovered.get("journal_sequence") != EXPECTED_BASE_REVISION:
            raise EffectiveDiagnosisScopeCorrectionError(
                "shadow baseline reconstruction drifted"
            )
        artifact = writer.evidence.finalize(material.report_bytes)
        if artifact.sha256 != sha256(material.report_bytes).hexdigest():
            raise EffectiveDiagnosisScopeCorrectionError(
                "shadow audit evidence identity drifted"
            )
        yield writer


def _operation_result(event: Mapping[str, Any]) -> Mapping[str, Any]:
    rows = event.get("index_records")
    if (
        not isinstance(rows, list)
        or not rows
        or not isinstance(rows[0], Mapping)
        or not isinstance(rows[0].get("payload"), Mapping)
        or not isinstance(rows[0]["payload"].get("result"), Mapping)
    ):
        raise EffectiveDiagnosisScopeCorrectionError(
            "correction operation result is malformed"
        )
    return rows[0]["payload"]["result"]


def _receipt(event: Mapping[str, Any]) -> CorrectionEventReceiptBinding:
    rows = event["index_records"]
    result = _operation_result(event)
    return CorrectionEventReceiptBinding(
        canonical_event_byte_count=len(canonical_bytes(dict(event))) + 1,
        canonical_event_sha256=sha256(canonical_bytes(dict(event))).hexdigest(),
        event_id=event["event_id"],
        occurred_at_utc=event["occurred_at_utc"],
        journal_offset=event["journal_offset"],
        event_payload_sha256=sha256(canonical_bytes(event["payload"])).hexdigest(),
        control_projection_sha256=sha256(
            canonical_bytes(event["control"])
        ).hexdigest(),
        operation_result_sha256=sha256(canonical_bytes(result)).hexdigest(),
        semantic_index_records_sha256=sha256(
            canonical_bytes(rows[1:])
        ).hexdigest(),
        semantic_index_record_count=len(rows) - 1,
    )


_EVENT_FIELDS = {
    "control", "event_id", "event_kind", "index_projection_digest",
    "index_record_count", "index_records", "journal_offset", "occurred_at_utc",
    "operation_id", "payload", "previous_event_id", "schema", "sequence",
    "subject",
}
_ROW_FIELDS = {
    "event_sequence", "event_stream", "fingerprint", "kind", "payload",
    "record_id", "status", "subject",
}


def _projection_member(row: Mapping[str, Any]) -> str:
    if set(row) != _ROW_FIELDS:
        raise EffectiveDiagnosisScopeCorrectionError(
            "correction index row fields are not exact"
        )
    return canonical_digest(
        domain="index-projection-member",
        payload={name: row.get(name) for name in sorted(_ROW_FIELDS)},
    )


def _verify_envelope(
    material: CorrectionMaterial,
    ordinal: int,
    event: Mapping[str, Any],
    cursor: _Cursor,
    occurred_at_utc: str,
) -> _Cursor:
    action = material.core.events[ordinal - 1]
    rows = event.get("index_records")
    if (
        set(event) != _EVENT_FIELDS
        or event.get("schema") != "journal_event"
        or event.get("event_kind") != action.event_kind
        or event.get("operation_id") != action.operation_id
        or event.get("subject") != action.subject
        or event.get("sequence") != EXPECTED_BASE_REVISION + ordinal
        or event.get("previous_event_id") != cursor.previous_event_id
        or event.get("journal_offset") != cursor.journal_offset
        or event.get("occurred_at_utc") != occurred_at_utc
        or not isinstance(rows, list)
        or not rows
        or any(not isinstance(row, Mapping) for row in rows)
    ):
        raise EffectiveDiagnosisScopeCorrectionError(
            "correction event differs from its independent envelope"
        )
    digest = cursor.index_projection_digest
    for row in rows:
        digest = canonical_digest(
            domain="index-projection-chain",
            payload={"member": _projection_member(row), "previous": digest},
        )
    count = cursor.index_record_count + 1 + len(rows)
    event_id = canonical_digest(
        domain="journal-event",
        payload={key: value for key, value in event.items() if key != "event_id"},
    )
    framed = len(canonical_bytes(dict(event))) + 1
    if (
        event.get("index_projection_digest") != digest
        or event.get("index_record_count") != count
        or event.get("event_id") != event_id
        or framed > DurableJournal.MAX_EVENT_BYTES
    ):
        raise EffectiveDiagnosisScopeCorrectionError(
            "correction event digest or projection chain drifted"
        )
    return _Cursor(
        journal_offset=cursor.journal_offset + framed,
        previous_event_id=event_id,
        index_record_count=count,
        index_projection_digest=digest,
    )


def _verify_operation_row(material: CorrectionMaterial, ordinal: int, event: Mapping[str, Any]) -> None:
    action = material.core.events[ordinal - 1]
    payload = event["payload"]
    result = _operation_result(event)
    expected = {
        "event_sequence": None,
        "event_stream": None,
        "fingerprint": canonical_digest(
            domain="operation",
            payload={"event_kind": action.event_kind, "payload": dict(payload)},
        ),
        "kind": "operation",
        "payload": {"event_kind": action.event_kind, "result": dict(result)},
        "record_id": action.operation_id,
        "status": "success",
        "subject": action.subject,
    }
    if dict(event["index_records"][0]) != expected:
        raise EffectiveDiagnosisScopeCorrectionError(
            "correction operation row is not exact"
        )


def _verify_fixed_action(material: CorrectionMaterial, ordinal: int, event: Mapping[str, Any]) -> None:
    action = material.core.events[ordinal - 1]
    binding = action.binding
    _verify_operation_row(material, ordinal, event)
    rows = event["index_records"][1:]
    if len(rows) != binding["semantic_record_count"]:
        raise EffectiveDiagnosisScopeCorrectionError(
            "correction semantic record count drifted"
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
        evidence: list[dict[str, Any]] = []
        observed: set[str] = set()
        for replacement in binding["replacement_rows"]:
            content = material.prospective_documents[replacement["path"]]
            identity = sha256(content).hexdigest()
            if identity in observed:
                continue
            observed.add(identity)
            evidence.append(
                {
                    "relative_path": f"sha256/{identity[:2]}/{identity}",
                    "sha256": identity,
                    "size_bytes": len(content),
                }
            )
        if (
            event["payload"] != {**migration_payload, "evidence": evidence}
            or rows[0]["record_id"] != binding["migration_id"]
            or _operation_result(event) != binding["operation_result"]
            or sha256(canonical_bytes(event["control"])).hexdigest()
            != binding["control_projection_sha256"]
        ):
            raise EffectiveDiagnosisScopeCorrectionError(
                "authority migration binding drifted"
            )
    elif ordinal == 2:
        activation_payload = {
            "audit_artifact_hash": binding["audit_artifact_hash"],
            "authority_manifest_digest": binding["authority_manifest_digest"],
            "protocol": binding["protocol"],
            "schema": "research_protocol_activation.v1",
            "validator_id": binding["validator_id"],
        }
        expected_result = {
            "activation_record_id": binding["activation_id"],
            "ordinal": binding["ordinal"],
            "protocol": binding["protocol"],
            "trial_delta": 0,
            "validator_id": binding["validator_id"],
        }
        expected_row_payload = {
            **activation_payload,
            "ordinal": binding["ordinal"],
            "scientific_trial_delta": 0,
            "supersedes_activation_record_id": binding["prior_activation_id"],
        }
        if (
            event["payload"] != {**activation_payload, "evidence": []}
            or _operation_result(event) != expected_result
            or rows[0]["record_id"] != binding["activation_id"]
            or rows[0]["payload"] != expected_row_payload
            or sha256(canonical_bytes(event["control"])).hexdigest()
            != binding["control_projection_sha256"]
        ):
            raise EffectiveDiagnosisScopeCorrectionError(
                "protocol rebind binding drifted"
            )


def _verify_diagnosis_action(
    writer: StateWriter,
    material: CorrectionMaterial,
    event: Mapping[str, Any],
    expected: _ExpectedDiagnosisAction,
) -> None:
    _verify_operation_row(material, 3, event)
    binding = material.core.events[2].binding
    audit = expected.audit
    rows = tuple(dict(row) for row in event["index_records"][1:])
    if (
        audit.prior_journal_event_id != event["previous_event_id"]
        or audit.prior_journal_sequence != event["sequence"] - 1
        or event["payload"] != {"audit_id": audit.identity, "evidence": []}
        or len(rows) != binding["semantic_record_count"]
        or canonical_bytes(list(rows))
        != canonical_bytes(list(expected.semantic_rows))
    ):
        raise EffectiveDiagnosisScopeCorrectionError(
            "diagnosis correction differs from its independent semantic plan"
        )
    if (
        binding["audit_protocol_id"] != audit.protocol_id
        or binding["audit_rationale"] != audit.rationale
        or tuple(binding["original_diagnosis_ids"]) != MISMATCH_IDS
        or tuple(binding["prior_correction_ids"]) != PRIOR_CORRECTION_IDS
        or binding["expected_effective_states"] != EXPECTED_STATES
        or expected.states_by_study
        != {
            "STU-0105": "not_identifiable",
            "STU-0107": "not_identifiable",
            "STU-0108": "not_identifiable",
        }
    ):
        raise EffectiveDiagnosisScopeCorrectionError(
            "diagnosis correction core differs from independent derivation"
        )
    if _operation_result(event) != expected.operation_result:
        raise EffectiveDiagnosisScopeCorrectionError(
            "diagnosis correction result drifted"
        )
    with writer.open_stable_index() as (_control, index):
        diagnoses = effective_study_diagnoses_by_study(index, mission_id=MISSION_ID)
        observed_states = {
            study_id: diagnoses[study_id].status
            for study_id in expected.states_by_study
        }
        if observed_states != expected.states_by_study:
            raise EffectiveDiagnosisScopeCorrectionError(
                "effective diagnosis projection differs after correction"
            )


def _verify_event(
    writer: StateWriter,
    material: CorrectionMaterial,
    ordinal: int,
    event: Mapping[str, Any],
    cursor: _Cursor,
    occurred_at_utc: str,
    expected_diagnosis: _ExpectedDiagnosisAction | None = None,
) -> _Cursor:
    next_cursor = _verify_envelope(
        material,
        ordinal,
        event,
        cursor,
        occurred_at_utc,
    )
    if ordinal in {1, 2}:
        _verify_fixed_action(material, ordinal, event)
    else:
        if expected_diagnosis is None:
            raise EffectiveDiagnosisScopeCorrectionError(
                "diagnosis correction lacks its premutation semantic plan"
            )
        _verify_diagnosis_action(
            writer,
            material,
            event,
            expected_diagnosis,
        )
    return next_cursor


class _ReplaySession:
    """Replay the complete suffix over one baseline reconstruction."""

    def __init__(self, writer: StateWriter, material: CorrectionMaterial) -> None:
        self.writer = writer
        self.material = material
        self.cursor = _Cursor(
            journal_offset=(
                material.core.baseline.journal_start_offset
                + material.core.baseline.journal_size_bytes
            ),
            previous_event_id=material.core.baseline.journal_event_id,
            index_record_count=material.core.baseline.index_record_count,
            index_projection_digest=(
                material.core.baseline.index_projection_digest
            ),
        )
        self.events: list[Mapping[str, Any]] = []
        self.receipts: list[CorrectionEventReceiptBinding] = []

    def append(self, occurred_at_utc: str) -> Mapping[str, Any]:
        ordinal = len(self.events) + 1
        if ordinal > self.material.core.event_count:
            raise EffectiveDiagnosisScopeCorrectionError(
                "replay session exceeds the correction event inventory"
            )
        expected_diagnosis = (
            _derive_expected_diagnosis_action(self.writer)
            if ordinal == 3
            else None
        )
        _invoke_at(
            self.writer,
            occurred_at_utc,
            lambda: _perform_action(self.writer, self.material, ordinal),
        )
        _head, event = self.writer.journal.tail()
        if event is None:
            raise EffectiveDiagnosisScopeCorrectionError(
                "shadow action omitted its event"
            )
        self.cursor = _verify_event(
            self.writer,
            self.material,
            ordinal,
            event,
            self.cursor,
            occurred_at_utc,
            expected_diagnosis,
        )
        sealed = dict(event)
        self.events.append(sealed)
        self.receipts.append(_receipt(sealed))
        return sealed


def _require_execution_closure(material: CorrectionMaterial) -> None:
    binding = material.core.events[0].binding
    current_runtime = capture_correction_runtime_provenance(
        safe_startup=_SAFE_STARTUP,
        private_bytecode_cache_root=(
            None if _SAFE_BYTECODE_CACHE is None else _SAFE_BYTECODE_CACHE.name
        ),
    )
    if current_runtime != binding["runtime_provenance"]:
        raise EffectiveDiagnosisScopeCorrectionError(
            "correction runtime provenance drifted"
        )
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
    expected = tuple((item.path, item.sha256) for item in material.core.execution_files)
    if observed != expected:
        raise EffectiveDiagnosisScopeCorrectionError(
            "correction execution closure drifted"
        )


def _writer_for_current(material: CorrectionMaterial) -> Iterator[StateWriter]:
    digest = _current_control()["authority"]["manifest_digest"]

    @contextmanager
    def prospective() -> Iterator[StateWriter]:
        yield StateWriter(
            ROOT,
            validation_registry=_registry(),
            study_close_delivery_observation=material.delivery_observation,
        )

    @contextmanager
    def predecessor() -> Iterator[StateWriter]:
        with _foundation(
            material.predecessor_documents,
            expected_digest=material.core.baseline.authority_manifest_digest,
        ) as foundation_root:
            yield StateWriter(
                ROOT,
                foundation_root=foundation_root,
                validation_registry=_registry(),
                study_close_delivery_observation=material.delivery_observation,
            )

    if digest == material.core.prospective_authority_manifest_digest:
        return prospective()
    if digest == material.core.baseline.authority_manifest_digest:
        return predecessor()
    raise EffectiveDiagnosisScopeCorrectionError(
        "control authority is outside the correction plan"
    )


def _materialize_evidence(material: CorrectionMaterial) -> None:
    evidence = EvidenceStore(ROOT / "local/evidence")
    for document, identity in (
        (material.report_bytes, sha256(material.report_bytes).hexdigest()),
        (material.core.core_bytes, material.core.core_hash),
    ):
        artifact = evidence.finalize(document)
        if artifact.sha256 != identity or evidence.read_verified(identity) != document:
            raise EffectiveDiagnosisScopeCorrectionError(
                "correction evidence materialization drifted"
            )


def _preview(
    material: CorrectionMaterial,
    timestamps: Sequence[str],
) -> tuple[tuple[Mapping[str, Any], ...], tuple[CorrectionEventReceiptBinding, ...]]:
    if len(timestamps) != material.core.event_count:
        raise EffectiveDiagnosisScopeCorrectionError(
            "preview timestamp inventory is incomplete"
        )
    with _shadow(material) as writer:
        replay = _ReplaySession(writer, material)
        for timestamp in timestamps:
            replay.append(timestamp)
        return tuple(replay.events), tuple(replay.receipts)


def read_only_plan() -> dict[str, Any]:
    material = _build_material()
    _require_execution_closure(material)
    timestamps = (
        "2099-12-31T23:59:59.999997Z",
        "2099-12-31T23:59:59.999998Z",
        "2099-12-31T23:59:59.999999Z",
    )
    events, receipts = _preview(material, timestamps)
    required_bytes = sum(item.canonical_event_byte_count for item in receipts)
    if material.core.baseline.journal_size_bytes + required_bytes > DurableJournal.MAX_SEGMENT_BYTES:
        raise EffectiveDiagnosisScopeCorrectionError(
            "complete correction inventory does not fit the active segment"
        )
    return {
        "apply_mutation_performed": False,
        "authority_replacement_paths": [
            item.path for item in material.core.authority_replacements
        ],
        "event_byte_counts": [item.canonical_event_byte_count for item in receipts],
        "event_ids": [event["event_id"] for event in events],
        "mismatch_ids": list(MISMATCH_IDS),
        "plan_core_hash": material.core.core_hash,
        "required_active_segment_bytes": required_bytes,
        "schema": "effective_diagnosis_scope_correction_plan.v1",
    }


def _journal_events() -> tuple[Mapping[str, Any], ...]:
    return tuple(StateWriter(ROOT).journal.read_all())


def _durable_core(events: Sequence[Mapping[str, Any]]) -> CorrectionPlanCore | None:
    if len(events) <= EXPECTED_BASE_REVISION:
        return None
    operation_id = events[EXPECTED_BASE_REVISION].get("operation_id")
    if type(operation_id) is not str:
        raise EffectiveDiagnosisScopeCorrectionError(
            "correction suffix operation id is absent"
        )
    try:
        core_hash = CorrectionPlanCore.hash_from_operation_id(
            operation_id,
            namespace=OPERATION_NAMESPACE,
        )
        document = EvidenceStore(ROOT / "local/evidence").read_verified(core_hash)
        return CorrectionPlanCore.from_bytes(document, expected_core_hash=core_hash)
    except (ContentAddressedCorrectionError, OSError, RuntimeError, ValueError) as exc:
        raise EffectiveDiagnosisScopeCorrectionError(
            "interrupted correction lacks its durable core"
        ) from exc


def _material_from_core(core: CorrectionPlanCore) -> CorrectionMaterial:
    baseline_document = _git_blob("origin/main", "state/control.json")
    control = _canonical_mapping(baseline_document, label="baseline control")
    if (
        core.operation_namespace != OPERATION_NAMESPACE
        or core.purpose != PURPOSE
        or core.baseline.control_revision != EXPECTED_BASE_REVISION
        or core.baseline.journal_sequence != EXPECTED_BASE_REVISION
        or core.baseline.journal_event_id != EXPECTED_BASE_EVENT_ID
        or core.baseline.origin_main_commit != EXPECTED_ORIGIN_MAIN_COMMIT
        or core.baseline.control_sha256
        != sha256(baseline_document).hexdigest()
        or _git_blob("HEAD", "state/control.json") != baseline_document
        or control.get("revision") != EXPECTED_BASE_REVISION
        or control.get("heads", {}).get("journal")
        != {
            "event_id": EXPECTED_BASE_EVENT_ID,
            "sequence": EXPECTED_BASE_REVISION,
        }
        or control.get("scientific", {}).get("active_mission") != MISSION_ID
        or control.get("scientific", {}).get("active_initiative")
        != INITIATIVE_ID
        or control.get("next_action")
        != {
            "kind": "portfolio_decision",
            "portfolio_snapshot_id": PORTFOLIO_SNAPSHOT_ID,
        }
    ):
        raise EffectiveDiagnosisScopeCorrectionError(
            "durable core baseline differs from the audited Git boundary"
        )
    index_head = control["heads"]["index"]
    if (
        core.baseline.authority_manifest_digest
        != control["authority"]["manifest_digest"]
        or core.baseline.index_record_count
        != index_head["required_record_count"]
        or core.baseline.index_projection_digest
        != index_head["required_projection_digest"]
        or core.baseline.mission_id != MISSION_ID
        or core.baseline.initiative_id != INITIATIVE_ID
        or core.baseline.next_action_kind != "portfolio_decision"
    ):
        raise EffectiveDiagnosisScopeCorrectionError(
            "durable core projection baseline is not exact"
        )
    journal_path, journal_start, journal_bytes, manifest_hash = (
        _active_journal_baseline()
    )
    if (
        core.baseline.journal_path != journal_path
        or core.baseline.journal_start_offset != journal_start
        or core.baseline.journal_size_bytes != len(journal_bytes)
        or core.baseline.journal_sha256 != sha256(journal_bytes).hexdigest()
        or core.baseline.journal_manifest_sha256 != manifest_hash
    ):
        raise EffectiveDiagnosisScopeCorrectionError(
            "durable core Journal baseline is not exact"
        )
    paths = _authority_paths(control)
    predecessor = {path: _git_blob("origin/main", path) for path in paths}
    prospective = {path: _git_blob("HEAD", path) for path in paths}
    authority_files = tuple(
        AuthorityFileBinding(
            path=path,
            predecessor_sha256=sha256(predecessor[path]).hexdigest(),
            prospective_sha256=sha256(prospective[path]).hexdigest(),
        )
        for path in paths
    )
    if (
        authority_files != core.authority_files
        or _manifest_digest(predecessor)
        != core.baseline.authority_manifest_digest
        or _manifest_digest(prospective)
        != core.prospective_authority_manifest_digest
        or tuple(item.path for item in core.authority_replacements)
        != ("OPERATING_DIRECTION.md", "contracts/science.yaml")
    ):
        raise EffectiveDiagnosisScopeCorrectionError(
            "durable core authority inventory differs from Git"
        )
    checkpoint = _reviewed_checkpoint()
    if (
        checkpoint["code_checkpoint_commit"]
        != core.baseline.code_checkpoint_commit
        or checkpoint["code_checkpoint_tree"] != core.baseline.code_checkpoint_tree
        or tuple(checkpoint["code_checkpoint_files"])
        != core.code_checkpoint_files
        or tuple(checkpoint["execution_files"]) != core.execution_files
    ):
        raise EffectiveDiagnosisScopeCorrectionError(
            "durable core code checkpoint differs from the reviewed checkout"
        )
    observation = _delivery_observation(checkpoint)
    if (
        core.events[0].binding.get("delivery_observation")
        != observation.to_payload()
        or core.events[0].binding.get("runtime_provenance")
        != checkpoint["runtime_provenance"]
    ):
        raise EffectiveDiagnosisScopeCorrectionError(
            "durable core runtime or delivery observation drifted"
        )
    try:
        report_bytes = _git_blob("HEAD", REPORT_PATH)
        report_bytes.decode("ascii")
    except (UnicodeDecodeError, EffectiveDiagnosisScopeCorrectionError) as exc:
        raise EffectiveDiagnosisScopeCorrectionError(
            "durable correction audit report is unavailable"
        ) from exc
    report_hash = sha256(report_bytes).hexdigest()
    if (
        tuple((binding.role, binding.sha256) for binding in core.evidence_bindings)
        != (("audit-report", report_hash),)
        or core.events[1].binding.get("audit_artifact_hash") != report_hash
    ):
        raise EffectiveDiagnosisScopeCorrectionError(
            "durable core audit evidence binding drifted"
        )
    return CorrectionMaterial(
        core=core,
        report_bytes=report_bytes,
        predecessor_documents=predecessor,
        prospective_documents=prospective,
        delivery_observation=observation,
    )


def apply(*, explicit_recovery: bool = False) -> dict[str, Any]:
    if not _SAFE_STARTUP:
        raise EffectiveDiagnosisScopeCorrectionError(
            "apply requires isolated no-site Python"
        )
    events = _journal_events()
    durable = _durable_core(events)
    material = _build_material() if durable is None else _material_from_core(durable)
    core = material.core
    _require_execution_closure(material)
    suffix = correction_suffix_from_journal(core, events)
    require_exact_correction_prefix(core, suffix)
    require_local_main_correction_boundary(
        ROOT,
        core,
        current_control=_current_control(),
        journal_events=events,
        allow_one_event_projection_lag=explicit_recovery,
    )
    _materialize_evidence(material)
    recovery: dict[str, Any] = {"mode": "stable_head_no_recovery"}
    with _writer_for_current(material) as writer:
        try:
            writer.require_stable_head()
        except RecoveryRequired:
            if not explicit_recovery or not suffix:
                raise
            trailing = suffix[-1]
            arguments = {
                "expected_sequence": trailing.get("sequence"),
                "expected_event_id": trailing.get("event_id"),
                "expected_operation_id": trailing.get("operation_id"),
                "expected_previous_event_id": trailing.get("previous_event_id"),
            }
            writer.require_exact_trailing_event_recovery_boundary(**arguments)
            recovery = {
                "mode": "explicit_exact_trailing_recovery",
                **writer.recover_exact_trailing_event(**arguments),
            }
    initial_prefix = len(suffix)
    with _shadow(material) as replay_writer:
        replay = _ReplaySession(replay_writer, material)
        for actual in suffix:
            expected = replay.append(actual["occurred_at_utc"])
            if canonical_bytes(dict(actual)) != canonical_bytes(dict(expected)):
                raise EffectiveDiagnosisScopeCorrectionError(
                    "existing correction prefix differs from deterministic replay"
                )
        for ordinal in range(initial_prefix + 1, core.event_count + 1):
            _require_execution_closure(material)
            with _writer_for_current(material) as writer:
                writer.require_stable_head()
                occurred_at_utc = _observe_clock(writer)
            expected = replay.append(occurred_at_utc)
            with _writer_for_current(material) as writer:
                writer.require_stable_head()
                with writer.journal.expect_next_event(expected):
                    transition = _invoke_at(
                        writer,
                        occurred_at_utc,
                        lambda selected=ordinal: _perform_action(
                            writer,
                            material,
                            selected,
                        ),
                    )
                _head, actual = writer.journal.tail()
                if (
                    actual is None
                    or transition.reused
                    or transition.revision != EXPECTED_BASE_REVISION + ordinal
                    or canonical_bytes(dict(actual))
                    != canonical_bytes(dict(expected))
                ):
                    raise EffectiveDiagnosisScopeCorrectionError(
                        "canonical correction event differs from preappend authority"
                    )
                writer.require_stable_head()
                suffix = (*suffix, dict(actual))
        verified_events = tuple(replay.events)
        receipts = tuple(replay.receipts)
    if canonical_bytes(list(verified_events)) != canonical_bytes(list(suffix)):
        raise EffectiveDiagnosisScopeCorrectionError(
            "final correction suffix differs from deterministic replay"
        )
    envelope = CorrectionReceiptEnvelope(core=core, event_receipts=receipts)
    require_exact_correction_receipts(envelope, suffix)
    evidence = EvidenceStore(ROOT / "local/evidence")
    artifact = evidence.finalize(envelope.artifact_bytes)
    if artifact.sha256 != envelope.artifact_hash:
        raise EffectiveDiagnosisScopeCorrectionError(
            "final correction envelope identity drifted"
        )
    final_events = _journal_events()
    delivery = require_local_main_correction_boundary(
        ROOT,
        envelope,
        current_control=_current_control(),
        journal_events=final_events,
    )
    with _writer_for_current(material) as writer:
        stable = writer.require_stable_head()
        with writer.open_stable_index() as (control, index):
            diagnoses = effective_study_diagnoses_by_study(index, mission_id=MISSION_ID)
            states = {
                study_id: diagnoses[study_id].status
                for study_id in ("STU-0105", "STU-0107", "STU-0108")
            }
            if (
                control["revision"] != EXPECTED_BASE_REVISION + core.event_count
                or control["next_action"]
                != {"kind": "portfolio_decision", "portfolio_snapshot_id": PORTFOLIO_SNAPSHOT_ID}
                or set(states.values()) != {"not_identifiable"}
            ):
                raise EffectiveDiagnosisScopeCorrectionError(
                    "final effective diagnosis projection is incomplete"
                )
    return {
        "applied_event_count": core.event_count - initial_prefix,
        "final_envelope_artifact_hash": envelope.artifact_hash,
        "final_prefix_count": len(suffix),
        "final_revision": stable["control_revision"],
        "local_main_delivery_boundary": delivery,
        "plan_core_hash": core.core_hash,
        "recovery": recovery,
        "schema": "effective_diagnosis_scope_correction_apply.v1",
        "states": states,
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--recover", action="store_true")
    arguments = parser.parse_args()
    if sum(bool(value) for value in (arguments.plan, arguments.apply, arguments.recover)) > 1:
        parser.error("choose at most one exact mode")
    return arguments


def main() -> int:
    arguments = parse_arguments()
    if arguments.apply or arguments.recover:
        result = apply(explicit_recovery=arguments.recover)
    else:
        result = read_only_plan()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
