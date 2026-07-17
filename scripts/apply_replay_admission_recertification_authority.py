"""Plan or apply the replay-admission authority activation.

The code checkpoint contains the prospective contract bytes while canonical
control still binds their predecessor.  The read-only plan binds that exact
Git boundary, the complete Python execution closure, the audit report, and two
ordered StateWriter transitions:

1. one old-to-final authority migration; and
2. one prospective scientific protocol rebind.

``--apply`` never stages, commits, or pushes.  It requires an unpublished
local-main code checkpoint and leaves only the exact control/Journal suffix for
the caller to deliver in a second local commit.  ``--recover`` is an explicit
capability for one exact plan-bound trailing event; routine reads never repair.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
import platform
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
        "apply_replay_admission_recertification_authority.py --apply`"
    )
_SAFE_BYTECODE_CACHE: TemporaryDirectory[str] | None = None


def _require_safe_repository_import_surface(
    import_roots: Sequence[Path],
) -> None:
    """Reject ignored sourceless or native code before project imports."""

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
    _SAFE_BYTECODE_CACHE = TemporaryDirectory(
        prefix="axiom-replay-activation-bytecode-"
    )
    sys.pycache_prefix = str(
        Path(_SAFE_BYTECODE_CACHE.name).resolve(strict=True)
    )
    sys.dont_write_bytecode = True
    import yaml

    _require_safe_repository_import_surface((ROOT / "src", ROOT / "scripts"))
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
from axiom_rift.operations.research_protocol_projection import (
    require_current_research_protocol_activation,
)
from axiom_rift.operations.study_close_git import (
    require_study_close_guard_ready,
)
from axiom_rift.operations.validation import EvidenceValidatorRegistry
from axiom_rift.operations.validation_integrity import (
    validator_execution_dependency_paths,
)
from axiom_rift.operations.writer import RecoveryRequired, StateWriter
from axiom_rift.research.protocol import (
    ResearchProtocol,
    ResearchProtocolActivation,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    ScientificAdjudicationValidatorV2,
)
from axiom_rift.storage.evidence import EvidenceStore
from axiom_rift.storage.journal import DurableJournal


OPERATION_NAMESPACE = "axiom-replay-admission-activation"
AUDIT_REPORT_PATH = (
    "records/audits/2026-07-17_replay_admission_recertification_audit.md"
)
AUTHORITY_REASON = (
    "bind audited replay admission recertification restart and lineage semantics"
)
PURPOSE = (
    "Activate the exhaustive replay-admission repair without scientific credit, "
    "then bind the prospective scientific validator to the exact final authority."
)
EXPECTED_BASELINE_REVISION = 5410
EXPECTED_BASELINE_EVENT_ID = (
    "1131db9825d7741847bda901ab56b4b3df3eb6a7400854819a76672a9be87319"
)
EXPECTED_PREDECESSOR_AUTHORITY_DIGEST = (
    "3e5638871b267d238077231265d92e091f6133449b3306b5c58aac39df98491b"
)
EXPECTED_PROSPECTIVE_AUTHORITY_DIGEST = (
    "cc556acff292f71d35a16fd528f174b4f6bc3758b8aaf033a53e8a2df44b39ab"
)
EXPECTED_CHANGED_AUTHORITY_HASHES = {
    "contracts/operations.yaml": (
        "1a9aa120b9877563028597e2973b665736e954c3212405aea006cba3a4b62930",
        "c8f085b06155ddc92b829154a3b0fdb669ca3f8c5ff5ab34811b2bf75b6ea1c6",
    ),
    "contracts/science.yaml": (
        "e9d6d917b1b6a1855f90a70d7053957f54f5f193ed096c4dee75618b7ca41283",
        "c27c2328231edd236b28d7e4e45c1674fbcfc0e00231e0151f793c221dece33a",
    ),
}
EXPECTED_MISSION_ID = "MIS-0006"
EXPECTED_INITIATIVE_ID = "INI-0025"
EXPECTED_SCIENTIFIC_INVENTORY = {
    "candidate": 0,
    "historical-scientific-adjudication": 496,
    "job-completed": 550,
    "negative-memory": 464,
    "release": 0,
    "trial": 612,
}
EXPECTED_NEXT_ACTION = {
    "kind": "portfolio_decision",
    "pending_replay_obligation_ids": [
        "historical-replay-obligation:"
        "c537b4ebc7085331cd21e52c26fbc994728c0520d5474473cc246f4e8c85322e"
    ],
    "portfolio_snapshot_id": (
        "portfolio:d7161d0a4b18cb8aebe0f2caac123932fafe271f52a9da5506230694fa144574"
    ),
    "required_replay_priority": "p0",
    "study_diagnosis_id": (
        "diagnosis:3d4d8fa540c01cfbbd4c41bcbfb48e12c1dfea6655c14458534138d7ff90bda1"
    ),
}
LOCAL_GIT_TIMEOUT_SECONDS = 120


class ReplayAdmissionActivationError(RuntimeError):
    """The frozen two-event activation boundary is not exact."""


_JOURNAL_EVENT_FIELDS = {
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


@dataclass(frozen=True, slots=True)
class _IndependentCursor:
    journal_offset: int
    previous_event_id: str
    index_record_count: int
    index_projection_digest: str


_T = TypeVar("_T")


class _SingleUseClock:
    def __init__(self, source: Callable[[], str]) -> None:
        self.source = source
        self.calls = 0
        self.observed: str | None = None

    def __call__(self) -> str:
        if self.calls:
            raise ReplayAdmissionActivationError(
                "activation event clock was read more than once"
            )
        self.calls += 1
        observed = self.source()
        if type(observed) is not str or not observed:
            raise ReplayAdmissionActivationError(
                "activation event clock is malformed"
            )
        self.observed = observed
        return observed

    def require_consumed(self) -> str:
        if self.calls != 1 or self.observed is None:
            raise ReplayAdmissionActivationError(
                "activation event clock was not consumed exactly once"
            )
        return self.observed


def _invoke_with_clock(
    writer: StateWriter,
    source: Callable[[], str],
    function: Callable[[], _T],
) -> tuple[_T, str]:
    clock = _SingleUseClock(source)
    prior = writer.clock
    writer.clock = clock
    try:
        result = function()
    finally:
        writer.clock = prior
    return result, clock.require_consumed()


def _observe_writer_clock_once(writer: StateWriter) -> str:
    clock = _SingleUseClock(writer.clock)
    clock()
    return clock.require_consumed()


def _invoke_at(
    writer: StateWriter,
    occurred_at_utc: str,
    function: Callable[[], _T],
) -> _T:
    result, observed = _invoke_with_clock(
        writer,
        lambda: occurred_at_utc,
        function,
    )
    if observed != occurred_at_utc:
        raise ReplayAdmissionActivationError("activation replay clock changed")
    return result


@dataclass(frozen=True, slots=True)
class ActivationMaterial:
    core: CorrectionPlanCore
    report_bytes: bytes
    activation: ResearchProtocolActivation
    migration_payload: Mapping[str, Any]
    prior_protocol_record_id: str
    protocol_ordinal: int
    non_authority_control_sha256: str
    scientific_inventory: Mapping[str, int]


def _git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ("git", *arguments),
            cwd=ROOT,
            check=check,
            capture_output=True,
            timeout=LOCAL_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReplayAdmissionActivationError(
            f"Git command failed: {' '.join(arguments)}"
        ) from exc


def _git_text(*arguments: str) -> str:
    try:
        return _git(*arguments).stdout.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ReplayAdmissionActivationError("Git output is non-ASCII") from exc


def _git_blob(reference: str, relative: str) -> bytes:
    result = _git("show", f"{reference}:{relative}")
    if not result.stdout:
        raise ReplayAdmissionActivationError(
            f"Git blob is empty: {reference}:{relative}"
        )
    return result.stdout


def _materialize_git_prefix(
    reference: str,
    relative: str,
    destination: Path,
) -> None:
    try:
        names = _git(
            "ls-tree",
            "-r",
            "--name-only",
            reference,
            "--",
            relative,
        ).stdout.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise ReplayAdmissionActivationError("Git tree path is non-ASCII") from exc
    if not names:
        raise ReplayAdmissionActivationError(
            f"Git tree prefix is empty: {reference}:{relative}"
        )
    boundary = relative.rstrip("/") + "/"
    for name in names:
        if name != relative and not name.startswith(boundary):
            raise ReplayAdmissionActivationError(
                "Git tree prefix escaped its boundary"
            )
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_git_blob(reference, name))


def _canonical_object(document: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = parse_canonical(document)
    except (TypeError, ValueError) as exc:
        raise ReplayAdmissionActivationError(f"{label} is not canonical") from exc
    if not isinstance(value, dict) or canonical_bytes(value) != document:
        raise ReplayAdmissionActivationError(f"{label} is not a canonical object")
    return value


def _head_control(
    *,
    require_worktree_baseline: bool = True,
) -> tuple[bytes, dict[str, Any]]:
    document = _git_blob("HEAD", "state/control.json")
    if _git_blob("origin/main", "state/control.json") != document:
        raise ReplayAdmissionActivationError(
            "HEAD and origin/main do not share the control baseline"
        )
    if require_worktree_baseline:
        try:
            current = (ROOT / "state/control.json").read_bytes()
        except OSError as exc:
            raise ReplayAdmissionActivationError(
                "current control is unavailable"
            ) from exc
        if current != document:
            raise ReplayAdmissionActivationError(
                "worktree control is outside the Git baseline"
            )
    control = _canonical_object(document, label="baseline control")
    science = control.get("scientific")
    authority = control.get("authority")
    if (
        control.get("revision") != EXPECTED_BASELINE_REVISION
        or control.get("next_action") != EXPECTED_NEXT_ACTION
        or not isinstance(science, Mapping)
        or science.get("active_mission") != EXPECTED_MISSION_ID
        or science.get("active_initiative") != EXPECTED_INITIATIVE_ID
        or not isinstance(authority, Mapping)
        or authority.get("manifest_digest")
        != EXPECTED_PREDECESSOR_AUTHORITY_DIGEST
        or control.get("heads", {}).get("journal", {}).get("event_id")
        != EXPECTED_BASELINE_EVENT_ID
    ):
        raise ReplayAdmissionActivationError(
            "canonical control differs from the frozen revision-5410 boundary"
        )
    return document, control


def _authority_paths(control: Mapping[str, Any]) -> tuple[str, ...]:
    authority = control.get("authority")
    if not isinstance(authority, Mapping):
        raise ReplayAdmissionActivationError("control authority is absent")
    operating = authority.get("operating_direction")
    contracts = authority.get("contracts")
    foundations = authority.get("foundation_inputs")
    if (
        type(operating) is not str
        or not isinstance(contracts, list)
        or not isinstance(foundations, list)
        or any(type(item) is not str for item in [*contracts, *foundations])
    ):
        raise ReplayAdmissionActivationError("authority path inventory is malformed")
    result = (operating, *contracts, *foundations)
    if len(result) != len(set(result)):
        raise ReplayAdmissionActivationError("authority path inventory is duplicated")
    return result


def _manifest_digest(documents: Mapping[str, bytes]) -> str:
    hashes = {
        relative: sha256(content).hexdigest()
        for relative, content in sorted(documents.items())
    }
    return canonical_digest(
        domain="authority-manifest",
        payload=hashes,
    )


def _authority_bindings(
    control: Mapping[str, Any],
) -> tuple[tuple[AuthorityFileBinding, ...], dict[str, bytes]]:
    paths = _authority_paths(control)
    predecessor = {path: _git_blob("origin/main", path) for path in paths}
    prospective = {path: _git_blob("HEAD", path) for path in paths}
    for relative, content in prospective.items():
        try:
            current = (ROOT / relative).read_bytes()
        except OSError as exc:
            raise ReplayAdmissionActivationError(
                f"authority file is unavailable: {relative}"
            ) from exc
        if current != content:
            raise ReplayAdmissionActivationError(
                f"authority worktree bytes differ from HEAD: {relative}"
            )
    predecessor_digest = _manifest_digest(predecessor)
    prospective_digest = _manifest_digest(prospective)
    if (
        predecessor_digest != EXPECTED_PREDECESSOR_AUTHORITY_DIGEST
        or prospective_digest != EXPECTED_PROSPECTIVE_AUTHORITY_DIGEST
    ):
        raise ReplayAdmissionActivationError(
            "authority manifests differ from the reviewed old-to-final boundary"
        )
    bindings = tuple(
        AuthorityFileBinding(
            path=relative,
            predecessor_sha256=sha256(predecessor[relative]).hexdigest(),
            prospective_sha256=sha256(prospective[relative]).hexdigest(),
        )
        for relative in paths
    )
    changed = {
        item.path: (item.predecessor_sha256, item.prospective_sha256)
        for item in bindings
        if item.changed
    }
    if changed != EXPECTED_CHANGED_AUTHORITY_HASHES:
        raise ReplayAdmissionActivationError(
            "changed authority files differ from the reviewed two-contract repair"
        )
    return bindings, prospective


def _runtime_provenance() -> dict[str, Any]:
    """Seal the interpreter and every executable PyYAML RECORD member."""

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
            content_hash = sha256(resolved.read_bytes()).hexdigest()
            record_hash = base64.urlsafe_b64decode(
                entry.hash.value + "=" * (-len(entry.hash.value) % 4)
            ).hex()
            if content_hash != record_hash:
                raise ValueError("PyYAML executable differs from RECORD")
            execution_inventory.append(
                {"path": relative, "sha256": content_hash}
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
        raise ReplayAdmissionActivationError(
            "current Python and PyYAML provenance cannot be sealed"
        ) from exc
    return {
        "python": {
            "bytecode_cache_policy": (
                "private_external_prefix"
                if _SAFE_STARTUP
                and sys.pycache_prefix is not None
                and _SAFE_BYTECODE_CACHE is not None
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
            "record_path": record_path.relative_to(distribution_root).as_posix(),
            "record_sha256": sha256(record_bytes).hexdigest(),
            "version": distribution.version,
        },
        "schema": "correction_runtime_provenance.v1",
    }


def _study_close_guard_binding() -> dict[str, Any]:
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
            raise OSError("worktree guard bytes differ")
    except OSError as exc:
        raise ReplayAdmissionActivationError(
            "Study-close guard worktree bytes drifted"
        ) from exc
    hook_mode = _git_text("ls-files", "--stage", "--", hook_path).split()[0]
    hooks_path = _git_text("config", "--get", "core.hooksPath")
    if hook_mode != "100755" or hooks_path != ".githooks":
        raise ReplayAdmissionActivationError("Study-close Git guard is inactive")
    return {
        "checkpoint_path": checkpoint_path,
        "checkpoint_sha256": sha256(checkpoint).hexdigest(),
        "commit_msg_hook_path": hook_path,
        "commit_msg_hook_sha256": sha256(hook.replace(b"\r\n", b"\n")).hexdigest(),
        "core_hooks_path": hooks_path,
        "hook_mode": hook_mode,
        "schema": "study_close_guard_binding.v1",
    }


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
        raise ReplayAdmissionActivationError(
            "activation execution closure cannot be sealed"
        ) from exc
    if Path(__file__).resolve() not in {Path(path).resolve() for path in paths}:
        raise ReplayAdmissionActivationError(
            "activation execution closure omitted its entrypoint"
        )
    return checkpoint


def _active_journal_baseline(
    control: Mapping[str, Any],
) -> tuple[str, int, bytes, str | None]:
    manifest_path = ROOT / "records/journal/manifest.json"
    if not manifest_path.is_file():
        relative = "records/journal.jsonl"
        content = _git_blob("HEAD", relative)
        if _git_blob("origin/main", relative) != content:
            raise ReplayAdmissionActivationError("legacy Journal baseline drifted")
        return relative, 0, content, None
    manifest_document = _git_blob("HEAD", "records/journal/manifest.json")
    if (
        _git_blob("origin/main", "records/journal/manifest.json")
        != manifest_document
        or manifest_path.read_bytes() != manifest_document
    ):
        raise ReplayAdmissionActivationError("Journal manifest baseline drifted")
    manifest = _canonical_object(manifest_document, label="Journal manifest")
    active = manifest.get("active_segment")
    if (
        not isinstance(active, Mapping)
        or type(active.get("path")) is not str
        or type(active.get("start_offset")) is not int
        or active["start_offset"] < 0
    ):
        raise ReplayAdmissionActivationError("active Journal binding is malformed")
    relative = active["path"]
    content = _git_blob("HEAD", relative)
    if _git_blob("origin/main", relative) != content:
        raise ReplayAdmissionActivationError("active Journal baseline drifted")
    head = control.get("heads", {}).get("journal", {})
    if head.get("sequence") != EXPECTED_BASELINE_REVISION:
        raise ReplayAdmissionActivationError("Journal baseline sequence differs")
    return (
        relative,
        active["start_offset"],
        content,
        sha256(manifest_document).hexdigest(),
    )


@contextmanager
def _predecessor_foundation(
    authority_files: Sequence[AuthorityFileBinding],
) -> Iterator[Path]:
    with TemporaryDirectory(prefix="axiom-replay-activation-predecessor-") as name:
        root = Path(name)
        for item in authority_files:
            target = root / item.path
            target.parent.mkdir(parents=True, exist_ok=True)
            content = _git_blob("origin/main", item.path)
            if sha256(content).hexdigest() != item.predecessor_sha256:
                raise ReplayAdmissionActivationError(
                    "predecessor authority changed during reconstruction"
                )
            target.write_bytes(content)
        yield root


def _registry() -> EvidenceValidatorRegistry:
    validator = ScientificAdjudicationValidatorV2()
    if validator.validator_id != SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID:
        raise ReplayAdmissionActivationError("current v2 validator identity drifted")
    return EvidenceValidatorRegistry((validator,))


def _writer(*, foundation_root: Path | None = None) -> StateWriter:
    return StateWriter(
        ROOT,
        foundation_root=foundation_root,
        validation_registry=_registry(),
    )


@contextmanager
def _baseline_shadow(
    authority_files: Sequence[AuthorityFileBinding],
    *,
    report_bytes: bytes | None = None,
) -> Iterator[StateWriter]:
    """Rebuild the exact Git baseline in one isolated non-authority root."""

    with TemporaryDirectory(prefix="axiom-replay-activation-shadow-") as name:
        shadow_root = Path(name).resolve()
        (shadow_root / "state").mkdir(parents=True)
        (shadow_root / "local").mkdir(parents=True)
        (shadow_root / "state/control.json").write_bytes(
            _git_blob("HEAD", "state/control.json")
        )
        if (ROOT / "records/journal/manifest.json").is_file():
            _materialize_git_prefix("HEAD", "records/journal", shadow_root)
        else:
            target = shadow_root / "records/journal.jsonl"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_git_blob("HEAD", "records/journal.jsonl"))
        for item in authority_files:
            target = shadow_root / item.path
            target.parent.mkdir(parents=True, exist_ok=True)
            content = _git_blob("origin/main", item.path)
            if sha256(content).hexdigest() != item.predecessor_sha256:
                raise ReplayAdmissionActivationError(
                    "shadow predecessor authority differs from the plan"
                )
            target.write_bytes(content)
        shadow = StateWriter(
            shadow_root,
            engineering_fixture=True,
            foundation_root=shadow_root,
            validation_registry=_registry(),
        )
        recovered = shadow.recover()
        if (
            recovered.get("journal_sequence") != EXPECTED_BASELINE_REVISION
            or recovered.get("index_rebuilt") is not True
        ):
            raise ReplayAdmissionActivationError(
                "shadow baseline was not rebuilt from exact Journal authority"
            )
        if report_bytes is not None:
            artifact = shadow.evidence.finalize(report_bytes)
            if shadow.evidence.read_verified(artifact.sha256) != report_bytes:
                raise ReplayAdmissionActivationError(
                    "shadow audit report evidence drifted"
                )
        stable = shadow.require_stable_head()
        if (
            stable.get("control_revision") != EXPECTED_BASELINE_REVISION
            or stable.get("journal_event_id") != EXPECTED_BASELINE_EVENT_ID
        ):
            raise ReplayAdmissionActivationError(
                "shadow stable head differs from the frozen baseline"
            )
        yield shadow


@contextmanager
def _writer_for_core(core: CorrectionPlanCore) -> Iterator[StateWriter]:
    try:
        control = _canonical_object(
            (ROOT / "state/control.json").read_bytes(),
            label="current control",
        )
    except OSError as exc:
        raise ReplayAdmissionActivationError("current control is unavailable") from exc
    digest = control.get("authority", {}).get("manifest_digest")
    if digest == core.prospective_authority_manifest_digest:
        yield _writer()
        return
    if digest != core.baseline.authority_manifest_digest:
        raise ReplayAdmissionActivationError(
            "control authority is outside the activation plan"
        )
    with _predecessor_foundation(core.authority_files) as foundation:
        yield _writer(foundation_root=foundation)


def _scientific_inventory(
    control: Mapping[str, Any],
    index: Any,
) -> dict[str, int]:
    inventory = {
        kind: len(index.records_by_kind(kind))
        for kind in EXPECTED_SCIENTIFIC_INVENTORY
    }
    science = control.get("scientific")
    if (
        not isinstance(science, Mapping)
        or science.get("claim") != "none"
        or science.get("holdout_reveals") != 0
    ):
        raise ReplayAdmissionActivationError(
            "scientific credit baseline is not zero-claim and sealed"
        )
    if inventory != EXPECTED_SCIENTIFIC_INVENTORY:
        raise ReplayAdmissionActivationError(
            "scientific inventory differs from the frozen revision-5410 baseline"
        )
    return inventory


def _prior_protocol(
    authority_files: Sequence[AuthorityFileBinding],
) -> tuple[str, int, dict[str, int]]:
    with _baseline_shadow(authority_files) as writer:
        with writer.open_stable_index() as (control, index):
            head = index.event_head("research-protocol:scientific")
            record = (
                None
                if head is None
                else index.get(head.record_kind, head.record_id)
            )
            if (
                head is None
                or record is None
                or record.kind != "research-protocol-activation"
                or record.status != "active"
                or record.event_sequence != head.sequence
                or type(head.sequence) is not int
                or head.sequence < 1
            ):
                raise ReplayAdmissionActivationError(
                    "prior prospective protocol authority is malformed"
                )
            return (
                record.record_id,
                head.sequence,
                _scientific_inventory(control, index),
            )


def _non_authority_control_sha256(control: Mapping[str, Any]) -> str:
    projected = {
        key: value
        for key, value in control.items()
        if key not in {"authority", "control_hash", "heads", "revision"}
    }
    return sha256(canonical_bytes(projected)).hexdigest()


def _migration_payload(
    authority_files: Sequence[AuthorityFileBinding],
) -> dict[str, Any]:
    replacements = [
        {
            "artifact_sha256": item.prospective_sha256,
            "new_sha256": item.prospective_sha256,
            "old_sha256": item.predecessor_sha256,
            "path": item.path,
        }
        for item in authority_files
        if item.changed
    ]
    return {
        "boundary": "active_stable",
        "holdout_delta": 0,
        "new_manifest_digest": EXPECTED_PROSPECTIVE_AUTHORITY_DIGEST,
        "old_manifest_digest": EXPECTED_PREDECESSOR_AUTHORITY_DIGEST,
        "reason": AUTHORITY_REASON,
        "replacements": replacements,
        "schema": "authority_manifest_migration.v1",
        "scientific_claim": "none",
        "trial_delta": 0,
    }


def _build_material() -> ActivationMaterial:
    control_document, control = _head_control()
    authority_files, _prospective = _authority_bindings(control)
    checkpoint = _reviewed_checkpoint()
    report = ROOT / AUDIT_REPORT_PATH
    try:
        report_bytes = report.read_bytes()
    except OSError as exc:
        raise ReplayAdmissionActivationError("audit report is unavailable") from exc
    if (
        _git_blob("HEAD", AUDIT_REPORT_PATH) != report_bytes
        or not report_bytes.isascii()
    ):
        raise ReplayAdmissionActivationError(
            "audit report is not exact tracked ASCII checkpoint evidence"
        )
    journal_path, journal_start, journal_bytes, manifest_hash = (
        _active_journal_baseline(control)
    )
    heads = control.get("heads")
    science = control.get("scientific")
    if not isinstance(heads, Mapping) or not isinstance(science, Mapping):
        raise ReplayAdmissionActivationError("baseline heads are malformed")
    index_head = heads.get("index")
    journal_head = heads.get("journal")
    if not isinstance(index_head, Mapping) or not isinstance(journal_head, Mapping):
        raise ReplayAdmissionActivationError("baseline projection heads are absent")
    baseline = CorrectionBaseline(
        control_revision=control["revision"],
        journal_sequence=journal_head["sequence"],
        journal_event_id=journal_head["event_id"],
        journal_path=journal_path,
        control_sha256=sha256(control_document).hexdigest(),
        journal_sha256=sha256(journal_bytes).hexdigest(),
        journal_start_offset=journal_start,
        journal_size_bytes=len(journal_bytes),
        authority_manifest_digest=EXPECTED_PREDECESSOR_AUTHORITY_DIGEST,
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
    prior_protocol_record_id, prior_ordinal, scientific_inventory = (
        _prior_protocol(authority_files)
    )
    protocol_ordinal = prior_ordinal + 1
    report_hash = sha256(report_bytes).hexdigest()
    activation = ResearchProtocolActivation(
        protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
        validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        authority_manifest_digest=EXPECTED_PROSPECTIVE_AUTHORITY_DIGEST,
        audit_artifact_hash=report_hash,
    )
    migration = _migration_payload(authority_files)
    non_authority_hash = _non_authority_control_sha256(control)
    runtime = _runtime_provenance()
    study_close_guard = _study_close_guard_binding()
    core = CorrectionPlanCore(
        operation_namespace=OPERATION_NAMESPACE,
        baseline=baseline,
        prospective_authority_manifest_digest=(
            EXPECTED_PROSPECTIVE_AUTHORITY_DIGEST
        ),
        authority_files=tuple(authority_files),
        code_checkpoint_files=tuple(checkpoint["code_checkpoint_files"]),
        execution_files=tuple(checkpoint["execution_files"]),
        evidence_bindings=(
            CorrectionEvidenceBinding(role="audit-report", sha256=report_hash),
        ),
        event_intents=(
            CorrectionEventIntent(
                action="authority-migration",
                event_kind="authority_migrated",
                subject="Authority:active",
                binding={
                    "migration": migration,
                    "non_authority_control_sha256": non_authority_hash,
                    "runtime": runtime,
                    "scientific_inventory": scientific_inventory,
                    "study_close_guard": study_close_guard,
                },
            ),
            CorrectionEventIntent(
                action="protocol-rebind",
                event_kind="research_protocol_activated",
                subject="ProjectGoal:OPERATING_DIRECTION.md",
                binding={
                    "activation": activation.to_identity_payload(),
                    "non_authority_control_sha256": non_authority_hash,
                    "ordinal": protocol_ordinal,
                    "runtime": runtime,
                    "scientific_inventory": scientific_inventory,
                    "study_close_guard": study_close_guard,
                    "supersedes_activation_record_id": prior_protocol_record_id,
                },
            ),
        ),
        purpose=PURPOSE,
    )
    return ActivationMaterial(
        core=core,
        report_bytes=report_bytes,
        activation=activation,
        migration_payload=migration,
        prior_protocol_record_id=prior_protocol_record_id,
        protocol_ordinal=protocol_ordinal,
        non_authority_control_sha256=non_authority_hash,
        scientific_inventory=scientific_inventory,
    )


def _material_from_core(core: CorrectionPlanCore) -> ActivationMaterial:
    control_document, baseline_control = _head_control(
        require_worktree_baseline=False
    )
    authority_files, _prospective = _authority_bindings(baseline_control)
    checkpoint = _reviewed_checkpoint()
    prior_record_id, prior_ordinal, scientific_inventory = _prior_protocol(
        authority_files
    )
    expected_triples = (
        ("authority-migration", "authority_migrated", "Authority:active"),
        (
            "protocol-rebind",
            "research_protocol_activated",
            "ProjectGoal:OPERATING_DIRECTION.md",
        ),
    )
    if (
        core.operation_namespace != OPERATION_NAMESPACE
        or core.purpose != PURPOSE
        or core.baseline.control_revision != EXPECTED_BASELINE_REVISION
        or core.baseline.journal_event_id != EXPECTED_BASELINE_EVENT_ID
        or core.baseline.authority_manifest_digest
        != EXPECTED_PREDECESSOR_AUTHORITY_DIGEST
        or core.prospective_authority_manifest_digest
        != EXPECTED_PROSPECTIVE_AUTHORITY_DIGEST
        or tuple(
            (item.action, item.event_kind, item.subject)
            for item in core.event_intents
        )
        != expected_triples
        or core.authority_files != authority_files
        or core.code_checkpoint_files
        != tuple(checkpoint["code_checkpoint_files"])
        or core.execution_files != tuple(checkpoint["execution_files"])
        or core.baseline.code_checkpoint_commit
        != checkpoint["code_checkpoint_commit"]
        or core.baseline.code_checkpoint_tree != checkpoint["code_checkpoint_tree"]
        or core.baseline.origin_main_commit != checkpoint["origin_main_commit"]
        or core.baseline.control_sha256
        != sha256(control_document).hexdigest()
        or core.baseline.mission_id != EXPECTED_MISSION_ID
        or core.baseline.initiative_id != EXPECTED_INITIATIVE_ID
        or core.baseline.next_action_kind != "portfolio_decision"
    ):
        raise ReplayAdmissionActivationError(
            "durable activation core is outside the frozen correction"
        )
    migration_binding = core.intent("authority-migration").binding
    protocol_binding = core.intent("protocol-rebind").binding
    migration = migration_binding.get("migration")
    activation_payload = protocol_binding.get("activation")
    prior = protocol_binding.get("supersedes_activation_record_id")
    ordinal = protocol_binding.get("ordinal")
    control_hash = protocol_binding.get("non_authority_control_sha256")
    expected_control_hash = _non_authority_control_sha256(baseline_control)
    expected_runtime = _runtime_provenance()
    expected_study_close_guard = _study_close_guard_binding()
    if (
        not isinstance(migration, Mapping)
        or migration != _migration_payload(core.authority_files)
        or not isinstance(activation_payload, Mapping)
        or type(prior) is not str
        or type(ordinal) is not int
        or ordinal != prior_ordinal + 1
        or prior != prior_record_id
        or type(control_hash) is not str
        or control_hash != expected_control_hash
        or migration_binding.get("runtime") != expected_runtime
        or protocol_binding.get("runtime") != expected_runtime
        or migration_binding.get("non_authority_control_sha256") != control_hash
        or migration_binding.get("scientific_inventory")
        != scientific_inventory
        or protocol_binding.get("scientific_inventory")
        != scientific_inventory
        or migration_binding.get("study_close_guard")
        != expected_study_close_guard
        or protocol_binding.get("study_close_guard")
        != expected_study_close_guard
    ):
        raise ReplayAdmissionActivationError("durable activation bindings drifted")
    try:
        activation = ResearchProtocolActivation(
            protocol=ResearchProtocol(activation_payload["protocol"]),
            validator_id=activation_payload["validator_id"],
            authority_manifest_digest=activation_payload[
                "authority_manifest_digest"
            ],
            audit_artifact_hash=activation_payload["audit_artifact_hash"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayAdmissionActivationError(
            "durable protocol activation is malformed"
        ) from exc
    if (
        activation.to_identity_payload() != dict(activation_payload)
        or activation.validator_id != SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
        or activation.authority_manifest_digest
        != EXPECTED_PROSPECTIVE_AUTHORITY_DIGEST
    ):
        raise ReplayAdmissionActivationError(
            "durable protocol activation names foreign authority"
        )
    report_path = ROOT / AUDIT_REPORT_PATH
    try:
        report_bytes = report_path.read_bytes()
    except OSError as exc:
        raise ReplayAdmissionActivationError("audit report is unavailable") from exc
    evidence = {item.role: item.sha256 for item in core.evidence_bindings}
    if (
        evidence != {"audit-report": sha256(report_bytes).hexdigest()}
        or activation.audit_artifact_hash != evidence["audit-report"]
        or _git_blob("HEAD", AUDIT_REPORT_PATH) != report_bytes
    ):
        raise ReplayAdmissionActivationError("audit report binding drifted")
    return ActivationMaterial(
        core=core,
        report_bytes=report_bytes,
        activation=activation,
        migration_payload=dict(migration),
        prior_protocol_record_id=prior,
        protocol_ordinal=ordinal,
        non_authority_control_sha256=control_hash,
        scientific_inventory=scientific_inventory,
    )


def _durable_core(
    journal_events: Sequence[Mapping[str, Any]],
) -> CorrectionPlanCore | None:
    suffix = tuple(journal_events[EXPECTED_BASELINE_REVISION:])
    if not suffix:
        return None
    operation_id = suffix[0].get("operation_id")
    if type(operation_id) is not str:
        raise ReplayAdmissionActivationError("activation suffix operation is absent")
    try:
        core_hash = CorrectionPlanCore.hash_from_operation_id(
            operation_id,
            namespace=OPERATION_NAMESPACE,
        )
        document = EvidenceStore(ROOT / "local/evidence").read_verified(core_hash)
        return CorrectionPlanCore.from_bytes(
            document,
            expected_core_hash=core_hash,
        )
    except (ContentAddressedCorrectionError, OSError, RuntimeError, ValueError) as exc:
        raise ReplayAdmissionActivationError(
            "activation suffix lacks its exact durable core"
        ) from exc


def _baseline_control_from_core(core: CorrectionPlanCore) -> dict[str, Any]:
    document = _git_blob("HEAD", "state/control.json")
    if sha256(document).hexdigest() != core.baseline.control_sha256:
        raise ReplayAdmissionActivationError("Git baseline control drifted")
    return _canonical_object(document, label="core baseline control")


def _operation_row(
    *,
    operation_id: str,
    event_kind: str,
    subject: str,
    payload: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "event_sequence": None,
        "event_stream": None,
        "fingerprint": canonical_digest(
            domain="operation",
            payload={"event_kind": event_kind, "payload": dict(payload)},
        ),
        "kind": "operation",
        "payload": {"event_kind": event_kind, "result": dict(result)},
        "record_id": operation_id,
        "status": "success",
        "subject": subject,
    }


def _evidence_manifest(content: bytes) -> dict[str, Any]:
    identity = sha256(content).hexdigest()
    return {
        "relative_path": f"sha256/{identity[:2]}/{identity}",
        "sha256": identity,
        "size_bytes": len(content),
    }


def _expected_event_components(
    material: ActivationMaterial,
    ordinal: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    core = material.core
    baseline = _baseline_control_from_core(core)
    control = {
        key: value
        for key, value in baseline.items()
        if key not in {"control_hash", "heads", "revision"}
    }
    control = json.loads(json.dumps(control))
    control["authority"]["manifest_digest"] = (
        EXPECTED_PROSPECTIVE_AUTHORITY_DIGEST
    )
    if ordinal == 1:
        payload = {
            **dict(material.migration_payload),
            "evidence": [
                _evidence_manifest(_git_blob("HEAD", item.path))
                for item in material.core.authority_replacements
            ],
        }
        migration_id = canonical_digest(
            domain="authority-manifest-migration",
            payload=material.migration_payload,
        )
        result = {
            "migration_id": migration_id,
            "new_manifest_digest": EXPECTED_PROSPECTIVE_AUTHORITY_DIGEST,
        }
        semantic = {
            "event_sequence": None,
            "event_stream": None,
            "fingerprint": migration_id,
            "kind": "authority-migration",
            "payload": dict(material.migration_payload),
            "record_id": migration_id,
            "status": "activated",
            "subject": "Authority:active",
        }
    elif ordinal == 2:
        activation_payload = material.activation.to_identity_payload()
        payload = {**activation_payload, "evidence": []}
        result = {
            "activation_record_id": material.activation.identity,
            "ordinal": material.protocol_ordinal,
            "protocol": material.activation.protocol.value,
            "trial_delta": 0,
            "validator_id": material.activation.validator_id,
        }
        semantic = {
            "event_sequence": material.protocol_ordinal,
            "event_stream": "research-protocol:scientific",
            "fingerprint": material.activation.identity.removeprefix(
                "research-protocol:"
            ),
            "kind": "research-protocol-activation",
            "payload": {
                **activation_payload,
                "ordinal": material.protocol_ordinal,
                "scientific_trial_delta": 0,
                "supersedes_activation_record_id": (
                    material.prior_protocol_record_id
                ),
            },
            "record_id": material.activation.identity,
            "status": "active",
            "subject": "ProjectGoal:OPERATING_DIRECTION.md",
        }
    else:
        raise ReplayAdmissionActivationError("activation ordinal is invalid")
    return control, payload, result, semantic


def _projection_member_digest(record: Mapping[str, Any]) -> str:
    return canonical_digest(
        domain="index-projection-member",
        payload={
            "event_sequence": record.get("event_sequence"),
            "event_stream": record.get("event_stream"),
            "fingerprint": record.get("fingerprint"),
            "kind": record.get("kind"),
            "payload": record.get("payload"),
            "record_id": record.get("record_id"),
            "status": record.get("status"),
            "subject": record.get("subject"),
        },
    )


def _validate_event_envelope(
    material: ActivationMaterial,
    event: Mapping[str, Any],
    *,
    ordinal: int,
    cursor: _IndependentCursor,
    occurred_at_utc: str,
) -> _IndependentCursor:
    resolved = material.core.events[ordinal - 1]
    control, payload, result, semantic = _expected_event_components(
        material,
        ordinal,
    )
    operation = _operation_row(
        operation_id=resolved.operation_id,
        event_kind=resolved.event_kind,
        subject=resolved.subject,
        payload=payload,
        result=result,
    )
    rows = event.get("index_records")
    event_id = event.get("event_id")
    expected_event_id = (
        None
        if not isinstance(event, Mapping)
        else canonical_digest(
            domain="journal-event",
            payload={key: value for key, value in event.items() if key != "event_id"},
        )
    )
    if (
        set(event) != _JOURNAL_EVENT_FIELDS
        or event.get("schema") != "journal_event"
        or event.get("sequence")
        != material.core.baseline.journal_sequence + ordinal
        or event.get("previous_event_id") != cursor.previous_event_id
        or event.get("journal_offset") != cursor.journal_offset
        or event.get("occurred_at_utc") != occurred_at_utc
        or event.get("operation_id") != resolved.operation_id
        or event.get("event_kind") != resolved.event_kind
        or event.get("subject") != resolved.subject
        or event.get("control") != control
        or event.get("payload") != payload
        or rows != [operation, semantic]
        or type(event_id) is not str
        or event_id != expected_event_id
        or _non_authority_control_sha256(control)
        != material.non_authority_control_sha256
    ):
        raise ReplayAdmissionActivationError(
            "activation event differs from its full independent envelope"
        )
    projection_digest = cursor.index_projection_digest
    assert isinstance(rows, list)
    for row in rows:
        projection_digest = canonical_digest(
            domain="index-projection-chain",
            payload={
                "member": _projection_member_digest(row),
                "previous": projection_digest,
            },
        )
    record_count = cursor.index_record_count + 1 + len(rows)
    framed_bytes = len(canonical_bytes(dict(event))) + 1
    if (
        event.get("index_projection_digest") != projection_digest
        or event.get("index_record_count") != record_count
        or framed_bytes > DurableJournal.MAX_EVENT_BYTES
    ):
        raise ReplayAdmissionActivationError(
            "activation event projection or framed size differs"
        )
    return _IndependentCursor(
        journal_offset=cursor.journal_offset + framed_bytes,
        previous_event_id=event_id,
        index_record_count=record_count,
        index_projection_digest=projection_digest,
    )


class _ActivationReplaySession:
    def __init__(
        self,
        *,
        writer: StateWriter,
        material: ActivationMaterial,
    ) -> None:
        self.writer = writer
        self.material = material
        self.cursor = _IndependentCursor(
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
        self.verified_events: list[Mapping[str, Any]] = []
        self.receipts: list[CorrectionEventReceiptBinding] = []
        self.pending_event: Mapping[str, Any] | None = None
        self.pending_cursor: _IndependentCursor | None = None

    def preview_next(self, occurred_at_utc: str) -> Mapping[str, Any]:
        if self.pending_event is not None or self.pending_cursor is not None:
            raise ReplayAdmissionActivationError(
                "activation replay already has a pending event"
            )
        ordinal = len(self.verified_events) + 1
        if ordinal > self.material.core.event_count:
            raise ReplayAdmissionActivationError(
                "activation replay exceeds its fixed event inventory"
            )
        _invoke_at(
            self.writer,
            occurred_at_utc,
            lambda: _apply_action(self.writer, self.material, ordinal),
        )
        _head, expected = self.writer.journal.tail()
        if expected is None:
            raise ReplayAdmissionActivationError(
                "shadow activation omitted its event"
            )
        pending_cursor = _validate_event_envelope(
            self.material,
            expected,
            ordinal=ordinal,
            cursor=self.cursor,
            occurred_at_utc=occurred_at_utc,
        )
        self.pending_event = expected
        self.pending_cursor = pending_cursor
        return expected

    def accept_next(self, actual: Mapping[str, Any]) -> None:
        if self.pending_event is None or self.pending_cursor is None:
            raise ReplayAdmissionActivationError(
                "activation replay has no pending event"
            )
        if canonical_bytes(dict(actual)) != canonical_bytes(dict(self.pending_event)):
            raise ReplayAdmissionActivationError(
                "durable activation event differs from the shadow event"
            )
        self.receipts.append(_receipt(self.pending_event))
        self.verified_events.append(dict(actual))
        self.cursor = self.pending_cursor
        self.pending_event = None
        self.pending_cursor = None

    def verify_next(self, actual: Mapping[str, Any]) -> None:
        occurred_at_utc = actual.get("occurred_at_utc")
        if type(occurred_at_utc) is not str:
            raise ReplayAdmissionActivationError(
                "durable activation timestamp is malformed"
            )
        self.preview_next(occurred_at_utc)
        self.accept_next(actual)

    def verify_prefix(self, suffix: Sequence[Mapping[str, Any]]) -> None:
        if self.verified_events or self.pending_event is not None:
            raise ReplayAdmissionActivationError(
                "activation replay prefix was already consumed"
            )
        for event in suffix:
            self.verify_next(event)


@contextmanager
def _open_replay_session(
    material: ActivationMaterial,
) -> Iterator[_ActivationReplaySession]:
    with _baseline_shadow(
        material.core.authority_files,
        report_bytes=material.report_bytes,
    ) as shadow:
        yield _ActivationReplaySession(writer=shadow, material=material)


def _verify_suffix(
    material: ActivationMaterial,
    journal_events: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    core = material.core
    try:
        suffix = correction_suffix_from_journal(core, journal_events)
        expected = require_exact_correction_prefix(core, suffix)
    except ContentAddressedCorrectionError as exc:
        raise ReplayAdmissionActivationError(str(exc)) from exc
    del expected
    with _open_replay_session(material) as replay:
        replay.verify_prefix(suffix)
        if len(suffix) == core.event_count:
            envelope = CorrectionReceiptEnvelope(
                core=core,
                event_receipts=tuple(replay.receipts),
            )
            try:
                require_exact_correction_receipts(envelope, suffix)
            except ContentAddressedCorrectionError as exc:
                raise ReplayAdmissionActivationError(str(exc)) from exc
    return suffix


def _receipt(event: Mapping[str, Any]) -> CorrectionEventReceiptBinding:
    rows = event.get("index_records")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], Mapping):
        raise ReplayAdmissionActivationError("activation event rows are malformed")
    result = rows[0].get("payload", {}).get("result")
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


def _final_envelope(
    material: ActivationMaterial,
    suffix: Sequence[Mapping[str, Any]],
    evidence: EvidenceStore,
) -> CorrectionReceiptEnvelope:
    if len(suffix) != material.core.event_count:
        raise ReplayAdmissionActivationError(
            "final envelope requires the complete activation suffix"
        )
    envelope = CorrectionReceiptEnvelope(
        core=material.core,
        event_receipts=tuple(_receipt(event) for event in suffix),
    )
    try:
        require_exact_correction_receipts(envelope, suffix)
    except ContentAddressedCorrectionError as exc:
        raise ReplayAdmissionActivationError(str(exc)) from exc
    artifact = evidence.finalize(envelope.artifact_bytes)
    if (
        artifact.sha256 != envelope.artifact_hash
        or evidence.read_verified(envelope.artifact_hash)
        != envelope.artifact_bytes
    ):
        raise ReplayAdmissionActivationError("final activation envelope drifted")
    return envelope


def _materialize_plan_evidence(
    material: ActivationMaterial,
    evidence: EvidenceStore,
) -> None:
    documents = [
        (material.report_bytes, material.activation.audit_artifact_hash),
        (material.core.core_bytes, material.core.core_hash),
        *[
            (_git_blob("HEAD", item.path), item.prospective_sha256)
            for item in material.core.authority_replacements
        ],
    ]
    for document, expected in documents:
        artifact = evidence.finalize(document)
        if (
            artifact.sha256 != expected
            or evidence.read_verified(expected) != document
        ):
            raise ReplayAdmissionActivationError(
                "activation plan evidence changed during finalization"
            )


def _require_existing_plan_evidence(
    material: ActivationMaterial,
    evidence: EvidenceStore,
) -> None:
    documents = [
        (material.report_bytes, material.activation.audit_artifact_hash),
        (material.core.core_bytes, material.core.core_hash),
        *[
            (_git_blob("HEAD", item.path), item.prospective_sha256)
            for item in material.core.authority_replacements
        ],
    ]
    for document, expected in documents:
        try:
            observed = evidence.read_verified(expected)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ReplayAdmissionActivationError(
                "interrupted activation lacks preappend evidence"
            ) from exc
        if observed != document:
            raise ReplayAdmissionActivationError(
                "interrupted activation evidence differs from its plan"
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
        raise ReplayAdmissionActivationError(
            "current activation execution closure cannot be inspected"
        ) from exc
    expected = tuple((item.path, item.sha256) for item in core.execution_files)
    if observed != expected:
        raise ReplayAdmissionActivationError(
            "current activation execution closure differs from the plan"
        )


def _read_journal() -> tuple[dict[str, Any], ...]:
    return tuple(DurableJournal(ROOT / "records/journal.jsonl").read_all())


def _exact_recovery_arguments(
    suffix: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not suffix:
        raise ReplayAdmissionActivationError(
            "recovery requires a plan-bound trailing event"
        )
    event = suffix[-1]
    return {
        "expected_sequence": event.get("sequence"),
        "expected_event_id": event.get("event_id"),
        "expected_operation_id": event.get("operation_id"),
        "expected_previous_event_id": event.get("previous_event_id"),
    }


def _apply_action(
    writer: StateWriter,
    material: ActivationMaterial,
    ordinal: int,
) -> Any:
    event = material.core.events[ordinal - 1]
    if ordinal == 1:
        replacements = {
            item.path: _git_blob("HEAD", item.path)
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
            activation=material.activation,
            operation_id=event.operation_id,
            allow_active_stable_boundary=True,
        )
    raise ReplayAdmissionActivationError("activation action ordinal is invalid")


def _current_control() -> dict[str, Any]:
    try:
        return _canonical_object(
            (ROOT / "state/control.json").read_bytes(),
            label="current control",
        )
    except OSError as exc:
        raise ReplayAdmissionActivationError("current control is unavailable") from exc


def _material() -> ActivationMaterial:
    events = _read_journal()
    durable = _durable_core(events)
    material = _build_material() if durable is None else _material_from_core(durable)
    _require_execution_closure(material.core)
    _verify_suffix(material, events)
    return material


def read_only_plan() -> dict[str, Any]:
    material = _material()
    events = _read_journal()
    suffix = _verify_suffix(material, events)
    return {
        "apply_mutation_performed": False,
        "authority_replacement_paths": [
            item.path for item in material.core.authority_replacements
        ],
        "event_inventory": [item.to_payload() for item in material.core.events],
        "existing_prefix_count": len(suffix),
        "plan_core_hash": material.core.core_hash,
        "prospective_authority_manifest_digest": (
            material.core.prospective_authority_manifest_digest
        ),
        "schema": "replay_admission_authority_plan.v1",
    }


def _require_final_scientific_inventory(
    material: ActivationMaterial,
) -> dict[str, Any]:
    writer = _writer()
    with writer.open_stable_index() as (control, index):
        inventory = _scientific_inventory(control, index)
        activation = require_current_research_protocol_activation(
            index,
            authority_manifest_digest=EXPECTED_PROSPECTIVE_AUTHORITY_DIGEST,
        )
        if (
            inventory != material.scientific_inventory
            or activation.record_id != material.activation.identity
            or index.record_count()
            != material.core.baseline.index_record_count + 6
            or control.get("revision") != EXPECTED_BASELINE_REVISION + 2
        ):
            raise ReplayAdmissionActivationError(
                "final activation inventory or protocol projection differs"
            )
        return {
            "claim": control["scientific"]["claim"],
            "holdout_reveals": control["scientific"]["holdout_reveals"],
            "index_record_count": index.record_count(),
            "protocol_activation_record_id": activation.record_id,
            "record_counts": inventory,
            "revision": control["revision"],
        }


def apply(*, explicit_recovery: bool = False) -> dict[str, Any]:
    """Apply only the missing exact two-event suffix; never commit or push."""

    if not _SAFE_STARTUP:
        raise ReplayAdmissionActivationError(
            "apply requires `python -I -S scripts/"
            "apply_replay_admission_recertification_authority.py --apply`"
        )
    if type(explicit_recovery) is not bool:
        raise ReplayAdmissionActivationError("recovery capability must be boolean")
    material = _material()
    core = material.core
    events = _read_journal()
    suffix = _verify_suffix(material, events)
    require_local_main_correction_boundary(
        ROOT,
        core,
        current_control=_current_control(),
        journal_events=events,
        allow_one_event_projection_lag=explicit_recovery,
    )
    evidence = EvidenceStore(ROOT / "local/evidence")
    recovery: dict[str, Any] = {"mode": "stable_head_no_recovery"}
    with _writer_for_core(core) as writer:
        try:
            writer.require_stable_head()
        except RecoveryRequired:
            if not explicit_recovery or not suffix:
                raise
            writer.require_exact_trailing_event_recovery_boundary(
                **_exact_recovery_arguments(suffix)
            )
            _require_existing_plan_evidence(material, evidence)
            recovery = {
                "mode": "explicit_exact_plan_prefix_recovery",
                **writer.recover_exact_trailing_event(
                    **_exact_recovery_arguments(suffix)
                ),
            }
        else:
            writer.require_study_close_delivery_guard()
    events = _read_journal()
    suffix = _verify_suffix(material, events)
    require_local_main_correction_boundary(
        ROOT,
        core,
        current_control=_current_control(),
        journal_events=events,
    )
    with _writer_for_core(core) as writer:
        writer.require_stable_head()
        writer.require_study_close_delivery_guard()
    if suffix:
        _require_existing_plan_evidence(material, evidence)
    _materialize_plan_evidence(material, evidence)
    # Evidence publication is not a Git capability.  Re-authenticate the full
    # boundary and Study-close checkpoint before any Journal append.
    require_local_main_correction_boundary(
        ROOT,
        core,
        current_control=_current_control(),
        journal_events=events,
    )
    with _writer_for_core(core) as writer:
        writer.require_stable_head()
        writer.require_study_close_delivery_guard()

    initial_prefix = len(suffix)
    with _open_replay_session(material) as replay:
        replay.verify_prefix(suffix)
        for ordinal in range(initial_prefix + 1, core.event_count + 1):
            _require_execution_closure(core)
            events = _read_journal()
            require_local_main_correction_boundary(
                ROOT,
                core,
                current_control=_current_control(),
                journal_events=events,
            )
            with _writer_for_core(core) as writer:
                writer.require_stable_head()
                writer.require_study_close_delivery_guard()
                occurred_at_utc = _observe_writer_clock_once(writer)
                expected_event = replay.preview_next(occurred_at_utc)
                _require_execution_closure(core)
                require_local_main_correction_boundary(
                    ROOT,
                    core,
                    current_control=_current_control(),
                    journal_events=_read_journal(),
                )
                writer.require_stable_head()
                writer.require_study_close_delivery_guard()
                with writer.journal.expect_next_event(expected_event):
                    result = _invoke_at(
                        writer,
                        occurred_at_utc,
                        lambda: _apply_action(writer, material, ordinal),
                    )
                _head, actual_event = writer.journal.tail()
            if (
                result.reused is not False
                or actual_event is None
                or result.event_id != actual_event.get("event_id")
                or result.revision != core.baseline.control_revision + ordinal
            ):
                raise ReplayAdmissionActivationError(
                    "activation action did not commit its exact new event"
                )
            replay.accept_next(actual_event)
            events = _read_journal()
            suffix = tuple(replay.verified_events)
            if (
                correction_suffix_from_journal(core, events) != suffix
                or len(suffix) != ordinal
            ):
                raise ReplayAdmissionActivationError(
                    "activation action did not advance one exact prefix event"
                )
            require_local_main_correction_boundary(
                ROOT,
                core,
                current_control=_current_control(),
                journal_events=events,
            )
    envelope = _final_envelope(material, suffix, evidence)
    with _writer_for_core(core) as writer:
        stable = writer.require_stable_head()
    final_control = stable["control"]
    if (
        final_control.get("authority", {}).get("manifest_digest")
        != EXPECTED_PROSPECTIVE_AUTHORITY_DIGEST
        or _non_authority_control_sha256(final_control)
        != material.non_authority_control_sha256
    ):
        raise ReplayAdmissionActivationError(
            "activation changed non-authority control or missed final authority"
        )
    final_inventory = _require_final_scientific_inventory(material)
    delivery = require_local_main_correction_boundary(
        ROOT,
        envelope,
        current_control=final_control,
        journal_events=_read_journal(),
    )
    return {
        "already_complete": initial_prefix == core.event_count,
        "applied_event_count": core.event_count - initial_prefix,
        "final_envelope_artifact_hash": envelope.artifact_hash,
        "final_prefix_count": len(suffix),
        "final_scientific_inventory": final_inventory,
        "local_main_delivery_boundary": delivery,
        "plan_core_hash": core.core_hash,
        "recovery": recovery,
        "schema": "replay_admission_authority_apply.v1",
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        description=(
            "Plan or apply the exact two-event replay-admission authority activation."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply the missing Writer suffix without staging, committing, or pushing",
    )
    parser.add_argument(
        "--recover",
        action="store_true",
        help="recover only one exact plan-bound trailing event before resuming",
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
